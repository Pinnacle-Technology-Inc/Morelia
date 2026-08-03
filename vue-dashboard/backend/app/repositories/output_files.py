"""Repository access for output-file finalization coordination (packet 16).

A *logical output* is one operator-visible recording identified by
``logical_sink_id``; it owns one or more ordered physical *components*
(``app.models.output_file.OutputFile`` rows) linked by ``previous_output_id``
and ordered by ``segment_index`` (packet 11). CSV normally has a single
component; an error-interrupted EDF/PVFS recording owns several linked
segments that a finalizer later merges into ONE published artifact.

This module owns the *durable, fenced* persistence for that finalization JOB.
It never performs format I/O and never touches hardware — it only mutates the
``output_files`` rows that packet 10 added:

- ``artifact_state``        -- ``not_required`` -> ``merge_pending`` ->
  ``merging`` -> ``merged`` | ``merge_failed``.
- ``finalization_id``       -- id of the merge attempt that currently owns the
  logical output.
- ``finalizer_fence_token`` -- monotonic generation number. Every claim (fresh
  or stale-lease takeover) increments it; a transition that names an older
  token is rejected, so a superseded finalizer can neither publish nor fail
  the job out from under the live one.
- ``finalized_at``          -- dual-purpose progress timestamp: while
  ``merging`` it is the lease *heartbeat* (advanced by :meth:`heartbeat`); on
  ``merged`` it is the commit time from which component-retention is measured.
  Downstream code must treat "durably finalized" as
  ``artifact_state == 'merged'`` and read ``finalized_at`` only then.
- ``final_output_id``       -- ``output_id`` of the published merged artifact,
  stamped onto every component on commit.

The canonical carrier of finalization state for a logical output is its
*head component* — the row with ``segment_index == 0``. All claim/transition
mutators operate on that row via a guarded compare-and-set so they stay atomic
under concurrent SQLite writers.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.database import db, transaction
from app.models.output_file import OutputFile

# ---------------------------------------------------------------------------
# State vocabulary (kept as plain strings to match the packet-10 model, which
# stores these columns as String, and to avoid coupling to app.domain.enums
# while a sibling packet is editing it).
# ---------------------------------------------------------------------------

ARTIFACT_NOT_REQUIRED = "not_required"
ARTIFACT_MERGE_PENDING = "merge_pending"
ARTIFACT_MERGING = "merging"
ARTIFACT_MERGED = "merged"
ARTIFACT_MERGE_FAILED = "merge_failed"
ARTIFACT_MERGE_BLOCKED = "merge_blocked"

ACQUISITION_OPEN = "open"
ACQUISITION_INTERRUPTED = "interrupted"
ACQUISITION_COMPLETE = "complete"

STATUS_CLOSED = "closed"

# States a fresh claim may take over. ``merging`` is only claimable when its
# lease is stale (see :meth:`claim`); it is intentionally NOT in this set so a
# healthy in-progress merge is never stolen on the strength of state alone.
_CLAIMABLE_STATES = (ARTIFACT_MERGE_PENDING, ARTIFACT_MERGE_FAILED)


class StaleFinalizerClaim(Exception):
    """A finalization transition named a superseded attempt / fence token.

    Raised when a mutator is asked to advance a logical output on behalf of a
    ``(finalization_id, fence_token)`` pair that no longer owns the row — e.g.
    a crashed finalizer that woke up after a stale-lease takeover tried to
    publish. It is raised (not silently dropped) so the fenced-out attempt is
    auditable, mirroring ``StaleWatchdogReport``.
    """

    def __init__(
        self,
        logical_sink_id: str,
        *,
        reported_finalization_id: str | None,
        reported_fence_token: int | None,
        active_finalization_id: str | None,
        active_fence_token: int | None,
        active_state: str | None,
    ) -> None:
        self.logical_sink_id = logical_sink_id
        self.reported_finalization_id = reported_finalization_id
        self.reported_fence_token = reported_fence_token
        self.active_finalization_id = active_finalization_id
        self.active_fence_token = active_fence_token
        self.active_state = active_state
        super().__init__(
            f"stale finalizer transition on logical output {logical_sink_id!r}: "
            f"reported attempt {reported_finalization_id!r} (token "
            f"{reported_fence_token!r}) is not the active attempt "
            f"{active_finalization_id!r} (token {active_fence_token!r}, state "
            f"{active_state!r})"
        )


class NotFinalizable(Exception):
    """Finalization was requested for an output that is not acquisition-complete.

    Enforces the packet invariant *only a completed acquisition can be
    finalized*: every writer must be closed and the last component's
    ``acquisition_state`` must be ``complete``.
    """

    def __init__(self, logical_sink_id: str, reason: str) -> None:
        self.logical_sink_id = logical_sink_id
        self.reason = reason
        super().__init__(
            f"logical output {logical_sink_id!r} is not finalizable: {reason}"
        )


@dataclass(frozen=True)
class ComponentRef:
    """Immutable snapshot of one physical component handed to a merger.

    Carries only what a format-aware merger needs to read a segment; it grants
    NO permission to delete or mutate the component (see the audit's rule that
    ``get_dict()`` carries identity, not delete/reuse rights).
    """

    output_id: str
    segment_index: int
    path: str
    previous_output_id: str | None
    sink_type: str
    schema_hash: str | None
    byte_offset: int
    row_offset: int
    acquisition_state: str
    termination_reason: str | None


@dataclass(frozen=True)
class FinalizationClaim:
    """A durable, fenced lease on one logical output's merge attempt.

    Handed back by :meth:`claim` / :meth:`claim_next`. The
    ``(finalization_id, fence_token)`` pair must accompany every later
    transition; a transition naming a superseded pair raises
    :class:`StaleFinalizerClaim`.
    """

    logical_sink_id: str
    finalization_id: str
    fence_token: int
    sink_type: str
    base_path: str
    components: tuple[ComponentRef, ...] = field(default_factory=tuple)

    @property
    def component_count(self) -> int:
        return len(self.components)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_ref(row: OutputFile) -> ComponentRef:
    return ComponentRef(
        output_id=row.output_id,
        segment_index=row.segment_index,
        path=row.path,
        previous_output_id=row.previous_output_id,
        sink_type=row.sink_type,
        schema_hash=row.schema_hash,
        byte_offset=row.byte_offset,
        row_offset=row.row_offset,
        acquisition_state=row.acquisition_state,
        termination_reason=row.termination_reason,
    )


class OutputFilesRepository:
    """Fenced persistence for the output finalization job state machine."""

    # -- reads --------------------------------------------------------------

    def list_components(self, logical_sink_id: str) -> list[OutputFile]:
        """Every component of a logical output, ordered by ``segment_index``."""
        return list(
            db.session.scalars(
                db.select(OutputFile)
                .where(OutputFile.logical_sink_id == logical_sink_id)
                .order_by(OutputFile.segment_index.asc())
            ).all()
        )

    def get_head(self, logical_sink_id: str) -> OutputFile | None:
        """The canonical finalization-state carrier (``segment_index == 0``)."""
        return db.session.scalars(
            db.select(OutputFile).where(
                OutputFile.logical_sink_id == logical_sink_id,
                OutputFile.segment_index == 0,
            )
        ).first()

    def _require_head(self, logical_sink_id: str) -> OutputFile:
        head = self.get_head(logical_sink_id)
        if head is None:
            raise KeyError(
                f"no head component (segment_index=0) for logical output "
                f"{logical_sink_id!r}"
            )
        return head

    # -- finalizability -----------------------------------------------------

    def is_finalizable(self, logical_sink_id: str) -> bool:
        """True when every writer is closed and the acquisition is complete."""
        components = self.list_components(logical_sink_id)
        return self._finalizable_reason(components) is None

    @staticmethod
    def _finalizable_reason(components: list[OutputFile]) -> str | None:
        if not components:
            return "no components exist"
        if any(c.status != STATUS_CLOSED for c in components):
            return "not every writer is closed"
        last = max(components, key=lambda c: c.segment_index)
        if last.acquisition_state != ACQUISITION_COMPLETE:
            return (
                f"last component acquisition_state is "
                f"{last.acquisition_state!r}, not {ACQUISITION_COMPLETE!r}"
            )
        return None

    # -- scheduling ---------------------------------------------------------

    def mark_merge_pending(self, logical_sink_id: str) -> OutputFile:
        """Schedule finalization for a completed logical output (idempotent).

        Only a completed acquisition may be scheduled (the contract). A
        single-component output needs no merge and is marked ``not_required``;
        a multi-component output becomes ``merge_pending`` awaiting a claim.
        Calling this again after a claim/publish is a no-op that returns the
        current head.
        """
        with transaction():
            components = self.list_components(logical_sink_id)
            reason = self._finalizable_reason(components)
            if reason is not None:
                raise NotFinalizable(logical_sink_id, reason)

            head = next(c for c in components if c.segment_index == 0)

            # Once a merge has been claimed or committed, scheduling is a no-op.
            if head.artifact_state in (
                ARTIFACT_MERGE_PENDING,
                ARTIFACT_MERGING,
                ARTIFACT_MERGED,
                ARTIFACT_MERGE_FAILED,
                ARTIFACT_MERGE_BLOCKED,
            ):
                return head

            if len(components) <= 1:
                head.artifact_state = ARTIFACT_NOT_REQUIRED
            else:
                head.artifact_state = ARTIFACT_MERGE_PENDING
            db.session.flush()
        return head

    def mark_merge_blocked(
        self,
        logical_sink_id: str,
        *,
        finalization_id: str | None = None,
        fence_token: int | None = None,
        now: datetime | None = None,
    ) -> OutputFile:
        """Quarantine a deterministic or structurally invalid merge.

        Without an attempt identity this is the scheduling-boundary path for a
        chain that cannot be finalized. With an identity it is a fenced terminal
        transition from an active merge attempt. Components are never modified.
        """
        now = now or _now()
        with transaction():
            head = self._require_head(logical_sink_id)
            if head.artifact_state == ARTIFACT_MERGE_BLOCKED:
                return head

            if finalization_id is None and fence_token is None:
                if head.artifact_state not in (
                    ARTIFACT_NOT_REQUIRED,
                    ARTIFACT_MERGE_PENDING,
                    ARTIFACT_MERGE_FAILED,
                ):
                    raise RuntimeError(
                        f"cannot block logical output {logical_sink_id!r} "
                        f"from state {head.artifact_state!r} without a fence"
                    )
                head.artifact_state = ARTIFACT_MERGE_BLOCKED
                head.finalized_at = now
                db.session.flush()
                return head

            if finalization_id is None or fence_token is None:
                raise ValueError("finalization_id and fence_token must be provided together")

            result = db.session.execute(
                db.update(OutputFile)
                .where(
                    OutputFile.logical_sink_id == logical_sink_id,
                    OutputFile.segment_index == 0,
                    OutputFile.artifact_state == ARTIFACT_MERGING,
                    OutputFile.finalization_id == finalization_id,
                    OutputFile.finalizer_fence_token == fence_token,
                )
                .values(artifact_state=ARTIFACT_MERGE_BLOCKED, finalized_at=now)
            )
            if result.rowcount != 1:
                self._raise_stale(logical_sink_id, finalization_id, fence_token)
            db.session.flush()
            return self._require_head(logical_sink_id)

    # -- claim / lease ------------------------------------------------------

    def claim(
        self,
        logical_sink_id: str,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease_ttl_seconds: float,
        max_attempts: int | None = None,
        retry_backoff_seconds: tuple[float, ...] = (),
    ) -> FinalizationClaim | None:
        """Atomically claim the merge attempt for one logical output.

        Returns a fenced :class:`FinalizationClaim` on success, or ``None`` when
        the output is not claimable (already ``merged``/``not_required``, or a
        healthy in-progress ``merging`` lease that has not gone stale, or lost
        to a concurrent claimer).

        Claimable states are ``merge_pending`` and ``merge_failed`` (retry). A
        ``merging`` row is only claimable when its lease heartbeat
        (``finalized_at``) is older than ``lease_ttl_seconds`` — that is the
        crash/stale-lease recovery path. Every successful claim increments the
        fence token and mints a fresh ``finalization_id``, fencing out any
        prior attempt.
        """
        now = now or _now()
        with transaction():
            head = self.get_head(logical_sink_id)
            if head is None:
                return None

            state = head.artifact_state
            attempt_count = head.finalizer_fence_token or 0
            exhausted = max_attempts is not None and attempt_count >= max_attempts
            if state == ARTIFACT_MERGE_FAILED and exhausted:
                head.artifact_state = ARTIFACT_MERGE_BLOCKED
                db.session.flush()
                return None
            if state == ARTIFACT_MERGE_FAILED and not self._retry_is_ready(
                head,
                now=now,
                attempt_count=attempt_count,
                retry_backoff_seconds=retry_backoff_seconds,
            ):
                return None
            claimable = state in _CLAIMABLE_STATES
            if state == ARTIFACT_MERGING and self._lease_is_stale(
                head, now=now, lease_ttl_seconds=lease_ttl_seconds
            ):
                if exhausted:
                    head.artifact_state = ARTIFACT_MERGE_BLOCKED
                    db.session.flush()
                    return None
                claimable = True
            if not claimable:
                return None

            old_token = head.finalizer_fence_token
            new_token = (old_token or 0) + 1
            new_fid = uuid.uuid4().hex

            guard = [
                OutputFile.id == head.id,
                OutputFile.artifact_state == state,
            ]
            if old_token is None:
                guard.append(OutputFile.finalizer_fence_token.is_(None))
            else:
                guard.append(OutputFile.finalizer_fence_token == old_token)

            result = db.session.execute(
                db.update(OutputFile)
                .where(*guard)
                .values(
                    artifact_state=ARTIFACT_MERGING,
                    finalizer_fence_token=new_token,
                    finalization_id=new_fid,
                    finalized_at=now,
                )
            )
            if result.rowcount != 1:
                # Lost a concurrent race for this same generation.
                return None

            db.session.flush()
            components = self.list_components(logical_sink_id)

        head_ref = next(c for c in components if c.segment_index == 0)
        return FinalizationClaim(
            logical_sink_id=logical_sink_id,
            finalization_id=new_fid,
            fence_token=new_token,
            sink_type=head_ref.sink_type,
            base_path=head_ref.path,
            components=tuple(_as_ref(c) for c in components),
        )

    def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease_ttl_seconds: float,
        max_attempts: int | None = None,
        retry_backoff_seconds: tuple[float, ...] = (),
    ) -> FinalizationClaim | None:
        """Claim the oldest claimable logical output, if any.

        Scans head rows that are ``merge_pending``, ``merge_failed`` (retry), or
        a stale ``merging`` lease, oldest first, and attempts to claim each
        until one succeeds. Returns ``None`` when nothing is claimable.
        """
        now = now or _now()
        candidates = db.session.scalars(
            db.select(OutputFile)
            .where(
                OutputFile.segment_index == 0,
                OutputFile.artifact_state.in_(
                    (ARTIFACT_MERGE_PENDING, ARTIFACT_MERGE_FAILED, ARTIFACT_MERGING)
                ),
            )
            .order_by(OutputFile.created_at.asc(), OutputFile.id.asc())
        ).all()

        for head in candidates:
            if head.artifact_state == ARTIFACT_MERGING and not self._lease_is_stale(
                head, now=now, lease_ttl_seconds=lease_ttl_seconds
            ):
                continue
            claim = self.claim(
                head.logical_sink_id,
                worker_id=worker_id,
                now=now,
                lease_ttl_seconds=lease_ttl_seconds,
                max_attempts=max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            if claim is not None:
                return claim
        return None

    @staticmethod
    def _retry_is_ready(
        head: OutputFile,
        *,
        now: datetime,
        attempt_count: int,
        retry_backoff_seconds: tuple[float, ...],
    ) -> bool:
        if not retry_backoff_seconds or head.finalized_at is None:
            return True
        last = head.finalized_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        delay_index = min(max(attempt_count - 1, 0), len(retry_backoff_seconds) - 1)
        retry_at = last + timedelta(seconds=retry_backoff_seconds[delay_index])
        return now >= retry_at

    @staticmethod
    def _lease_is_stale(
        head: OutputFile, *, now: datetime, lease_ttl_seconds: float
    ) -> bool:
        last = head.finalized_at
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return now - last >= timedelta(seconds=lease_ttl_seconds)

    def heartbeat(
        self,
        logical_sink_id: str,
        *,
        finalization_id: str,
        fence_token: int,
        now: datetime | None = None,
    ) -> None:
        """Refresh the lease heartbeat for the owning attempt.

        Raises :class:`StaleFinalizerClaim` if this attempt no longer owns the
        merge (a newer claim superseded it), so a fenced-out worker learns to
        stop rather than keep writing.
        """
        now = now or _now()
        with transaction():
            result = db.session.execute(
                db.update(OutputFile)
                .where(
                    OutputFile.logical_sink_id == logical_sink_id,
                    OutputFile.segment_index == 0,
                    OutputFile.artifact_state == ARTIFACT_MERGING,
                    OutputFile.finalization_id == finalization_id,
                    OutputFile.finalizer_fence_token == fence_token,
                )
                .values(finalized_at=now)
            )
            if result.rowcount != 1:
                self._raise_stale(logical_sink_id, finalization_id, fence_token)

    # -- terminal transitions ----------------------------------------------

    def publish_under_fence(
        self,
        logical_sink_id: str,
        *,
        finalization_id: str,
        fence_token: int,
        final_output_id: str,
        publish: Callable[[], None],
        now: datetime | None = None,
    ) -> OutputFile:
        """Run the filesystem publish while holding the active DB write fence.

        The guarded heartbeat update acquires the writer lock before invoking
        ``publish``. A stale claimant is rejected before touching the target;
        competing takeovers cannot advance until this transaction commits.
        """
        now = now or _now()
        with transaction():
            fenced = db.session.execute(
                db.update(OutputFile)
                .where(
                    OutputFile.logical_sink_id == logical_sink_id,
                    OutputFile.segment_index == 0,
                    OutputFile.artifact_state == ARTIFACT_MERGING,
                    OutputFile.finalization_id == finalization_id,
                    OutputFile.finalizer_fence_token == fence_token,
                )
                .values(finalized_at=now)
            )
            if fenced.rowcount != 1:
                self._raise_stale(logical_sink_id, finalization_id, fence_token)

            publish()

            db.session.execute(
                db.update(OutputFile)
                .where(
                    OutputFile.logical_sink_id == logical_sink_id,
                    OutputFile.segment_index == 0,
                    OutputFile.finalization_id == finalization_id,
                    OutputFile.finalizer_fence_token == fence_token,
                )
                .values(
                    artifact_state=ARTIFACT_MERGED,
                    final_output_id=final_output_id,
                    finalized_at=now,
                )
            )
            db.session.execute(
                db.update(OutputFile)
                .where(OutputFile.logical_sink_id == logical_sink_id)
                .values(final_output_id=final_output_id)
            )
            db.session.flush()
            return self._require_head(logical_sink_id)

    def mark_merged(
        self,
        logical_sink_id: str,
        *,
        finalization_id: str,
        fence_token: int,
        final_output_id: str,
        now: datetime | None = None,
    ) -> OutputFile:
        """Publish: commit the verified merged artifact under fence protection.

        Fenced compare-and-set on the owning ``(finalization_id, fence_token)``:
        a superseded attempt raises :class:`StaleFinalizerClaim` and CANNOT
        publish. ``final_output_id`` is stamped onto EVERY component so each
        segment links to the published artifact. Idempotent: re-committing the
        same attempt with the same ``final_output_id`` returns the merged head.
        """
        now = now or _now()
        with transaction():
            head = self._require_head(logical_sink_id)

            # Idempotent replay of our own successful commit.
            if (
                head.artifact_state == ARTIFACT_MERGED
                and head.finalization_id == finalization_id
                and head.finalizer_fence_token == fence_token
                and head.final_output_id == final_output_id
            ):
                return head

            result = db.session.execute(
                db.update(OutputFile)
                .where(
                    OutputFile.logical_sink_id == logical_sink_id,
                    OutputFile.segment_index == 0,
                    OutputFile.artifact_state == ARTIFACT_MERGING,
                    OutputFile.finalization_id == finalization_id,
                    OutputFile.finalizer_fence_token == fence_token,
                )
                .values(
                    artifact_state=ARTIFACT_MERGED,
                    final_output_id=final_output_id,
                    finalized_at=now,
                )
            )
            if result.rowcount != 1:
                self._raise_stale(logical_sink_id, finalization_id, fence_token)

            # Stamp the published id onto every component (fenced by the head
            # transition above having succeeded within this same transaction).
            db.session.execute(
                db.update(OutputFile)
                .where(OutputFile.logical_sink_id == logical_sink_id)
                .values(final_output_id=final_output_id)
            )
            db.session.flush()
            return self._require_head(logical_sink_id)

    def mark_merge_failed(
        self,
        logical_sink_id: str,
        *,
        finalization_id: str,
        fence_token: int,
        now: datetime | None = None,
    ) -> OutputFile:
        """Release the lease into ``merge_failed`` via a fenced transition.

        Publishes NO artifact: ``final_output_id`` stays NULL, every component
        row is left byte-for-byte intact. A superseded attempt raises
        :class:`StaleFinalizerClaim` (it must not fail the job out from under
        the live owner). The output stays retryable via a later :meth:`claim`.
        """
        now = now or _now()
        with transaction():
            head = self._require_head(logical_sink_id)
            if (
                head.artifact_state == ARTIFACT_MERGE_FAILED
                and head.finalization_id == finalization_id
                and head.finalizer_fence_token == fence_token
            ):
                return head  # idempotent replay

            result = db.session.execute(
                db.update(OutputFile)
                .where(
                    OutputFile.logical_sink_id == logical_sink_id,
                    OutputFile.segment_index == 0,
                    OutputFile.artifact_state == ARTIFACT_MERGING,
                    OutputFile.finalization_id == finalization_id,
                    OutputFile.finalizer_fence_token == fence_token,
                )
                .values(artifact_state=ARTIFACT_MERGE_FAILED, finalized_at=now)
            )
            if result.rowcount != 1:
                self._raise_stale(logical_sink_id, finalization_id, fence_token)
            db.session.flush()
            return self._require_head(logical_sink_id)

    def _raise_stale(
        self, logical_sink_id: str, finalization_id: str, fence_token: int
    ) -> None:
        head = self.get_head(logical_sink_id)
        raise StaleFinalizerClaim(
            logical_sink_id,
            reported_finalization_id=finalization_id,
            reported_fence_token=fence_token,
            active_finalization_id=head.finalization_id if head else None,
            active_fence_token=head.finalizer_fence_token if head else None,
            active_state=head.artifact_state if head else None,
        )
