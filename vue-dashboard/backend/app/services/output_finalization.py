r"""Output finalization coordinator (packet 16).

The control plane owns a durable, fenced finalization JOB; this service is the
orchestration layer that turns one fenced :class:`FinalizationClaim` into a
single merge attempt and a fenced terminal transition. It performs NO format
I/O itself — the actual EDF/PVFS byte merge is injected as a ``Merger``
callable (packets 17/18). It never owns hardware and never blocks a stop.

State machine (per logical output, carried on the head component)::

    not_required                      (single component: nothing to merge)
    merge_pending --claim--> merging --publish--> merged
                                     \--fail-----> merge_failed --claim--> merging ...

Every transition out of ``merging`` is fenced by the claim's
``(finalization_id, fence_token)``: a crashed-then-revived finalizer whose
lease was taken over cannot publish a false artifact or fail the job out from
under the live owner (see ``app.repositories.output_files``).

Merger contract (the downstream boundary for packets 17/18)
-----------------------------------------------------------
A merger is ``Callable[[MergeRequest], MergeResult]``. It must:

1. write a temporary artifact on the SAME filesystem as the components
   (``request.temp_dir`` is the configured fallback base);
2. verify it (readability, expected sample counts, chronological order,
   durable metadata);
3. leave the verified temporary artifact in place for the coordinator;
4. return :class:`MergeResult` with ``ok=True``, the intended ``published_path``, a
   fresh ``final_output_id``, and (optionally) ``sample_count``.

On any failure it returns ``ok=False`` with a ``reason`` and leaves the
components untouched; it should retain ``temp_path`` for diagnosis rather than
delete it. The coordinator re-verifies the published artifact exists before it
commits, so a merger that reports success without a real file is downgraded to
``merge_failed`` rather than publishing a false artifact.

Cleanup eligibility (the boundary for packet 29)
------------------------------------------------
Component cleanup is NEVER part of the merge transaction. A component may be
deleted only once :func:`cleanup_eligibility` reports eligible: the logical
output is ``merged``, ``final_output_id`` is set, and the configured retention
window has elapsed since the durable publish (``finalized_at``).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.database import db, transaction
from app.models.output_file import OutputFile
from app.repositories.output_files import (
    ACQUISITION_COMPLETE,
    ARTIFACT_MERGE_FAILED,
    ARTIFACT_MERGE_PENDING,
    ARTIFACT_MERGED,
    ARTIFACT_MERGING,
    ARTIFACT_NOT_REQUIRED,
    STATUS_CLOSED,
    ComponentRef,
    FinalizationClaim,
    OutputFilesRepository,
    StaleFinalizerClaim,
)

# ---------------------------------------------------------------------------
# Merger contract (published for packets 17 and 18)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeRequest:
    """Everything a merger needs to read the components and write a temp merge.

    Grants no delete/mutate rights over the components — only their paths for
    reading. ``finalization_id``/``fence_token`` are echoed so a merger may
    heartbeat the lease during a long merge.
    """

    logical_sink_id: str
    finalization_id: str
    fence_token: int
    sink_type: str
    base_path: str
    temp_dir: str
    components: tuple[ComponentRef, ...]


@dataclass(frozen=True)
class MergeResult:
    """A merger's verification result and publish outcome.

    ``ok`` means the merger wrote, verified, and atomically published a merged
    artifact at ``published_path`` under identity ``final_output_id``.
    ``temp_path`` is the (retained-on-failure) diagnostic temporary artifact.
    """

    ok: bool
    temp_path: str | None = None
    published_path: str | None = None
    final_output_id: str | None = None
    sample_count: int | None = None
    reason: str | None = None
    details: dict = field(default_factory=dict)


Merger = Callable[[MergeRequest], MergeResult]


@dataclass(frozen=True)
class FinalizationOutcome:
    """What one :meth:`FinalizationCoordinator.finalize_once` attempt did."""

    logical_sink_id: str
    action: str  # "merged" | "failed" | "not_required" | "skipped" | "idempotent"
    final_output_id: str | None = None
    published_path: str | None = None
    temp_path: str | None = None
    reason: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class FinalizationCoordinator:
    """Orchestrates one fenced merge attempt without owning hardware."""

    def __init__(
        self,
        *,
        repository: OutputFilesRepository | None = None,
        temp_dir: str,
        lease_ttl_seconds: float,
        retention_seconds: float,
        heartbeat_interval_seconds: float = 15.0,
        now_fn: Callable[[], datetime] = _now,
    ) -> None:
        self._repo = repository or OutputFilesRepository()
        self._temp_dir = temp_dir
        self._lease_ttl_seconds = lease_ttl_seconds
        self._retention_seconds = retention_seconds
        self._heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        if self._heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be greater than zero")
        self._now_fn = now_fn

    @property
    def repository(self) -> OutputFilesRepository:
        return self._repo

    # -- scheduling ---------------------------------------------------------

    def schedule(self, logical_sink_id: str):
        """Persist that a completed logical output is ready for finalization.

        Thin pass-through to the repository so the stop/completion boundary
        (``app/services/sessions.py``, a different packet) can request
        background finalization without waiting on it. Marks ``not_required``
        for a single-component output and ``merge_pending`` otherwise.
        """
        return self._repo.mark_merge_pending(logical_sink_id)

    # -- one attempt --------------------------------------------------------

    def finalize_once(
        self,
        merger: Merger,
        *,
        worker_id: str,
        logical_sink_id: str | None = None,
    ) -> FinalizationOutcome | None:
        """Claim one logical output and run a single fenced merge attempt.

        If ``logical_sink_id`` is given, only that output is considered;
        otherwise the oldest claimable output is picked. Returns ``None`` when
        nothing was claimable.
        """
        now = self._now_fn()
        if logical_sink_id is not None:
            claim = self._repo.claim(
                logical_sink_id,
                worker_id=worker_id,
                now=now,
                lease_ttl_seconds=self._lease_ttl_seconds,
            )
        else:
            claim = self._repo.claim_next(
                worker_id=worker_id,
                now=now,
                lease_ttl_seconds=self._lease_ttl_seconds,
            )
        if claim is None:
            return None

        return self._run_attempt(merger, claim)

    def _run_attempt(
        self, merger: Merger, claim: FinalizationClaim
    ) -> FinalizationOutcome:
        request = MergeRequest(
            logical_sink_id=claim.logical_sink_id,
            finalization_id=claim.finalization_id,
            fence_token=claim.fence_token,
            sink_type=claim.sink_type,
            base_path=claim.base_path,
            temp_dir=self._temp_dir,
            components=claim.components,
        )

        try:
            result = self._merge_with_heartbeats(merger, request, claim)
        except Exception as exc:  # noqa: BLE001 - a crashing merger must not publish
            return self._fail(claim, reason=f"merger raised: {exc!r}", temp_path=None)

        # Verify before publish: never commit a merged state the merger cannot
        # back with a real, published file and a fresh artifact id.
        verification = self._verify(result)
        if verification is not None:
            return self._fail(
                claim, reason=verification, temp_path=result.temp_path
            )

        try:
            assert result.temp_path is not None
            assert result.published_path is not None
            self._repo.publish_under_fence(
                claim.logical_sink_id,
                finalization_id=claim.finalization_id,
                fence_token=claim.fence_token,
                final_output_id=result.final_output_id,
                publish=lambda: os.replace(result.temp_path, result.published_path),
                now=self._now_fn(),
            )
        except StaleFinalizerClaim:
            # A stale-lease takeover fenced us out between merge and commit.
            # Do NOT retry the publish — the live owner will finalize. Our temp
            # artifact is retained for the reconciler/diagnosis.
            return FinalizationOutcome(
                logical_sink_id=claim.logical_sink_id,
                action="skipped",
                temp_path=result.temp_path,
                reason="fenced out by a newer finalization attempt",
            )
        except Exception as exc:  # noqa: BLE001 - publish faults are durable failures
            return self._fail(
                claim,
                reason=f"atomic publish failed: {exc!r}",
                temp_path=result.temp_path,
            )

        return FinalizationOutcome(
            logical_sink_id=claim.logical_sink_id,
            action="merged",
            final_output_id=result.final_output_id,
            published_path=result.published_path,
            temp_path=result.temp_path,
        )

    def _merge_with_heartbeats(
        self, merger: Merger, request: MergeRequest, claim: FinalizationClaim
    ) -> MergeResult:
        """Run format I/O off-thread while this thread refreshes the DB lease."""
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="output-merger") as executor:
            future = executor.submit(merger, request)
            while True:
                try:
                    return future.result(timeout=self._heartbeat_interval_seconds)
                except FutureTimeout:
                    self._repo.heartbeat(
                        claim.logical_sink_id,
                        finalization_id=claim.finalization_id,
                        fence_token=claim.fence_token,
                        now=self._now_fn(),
                    )

    def _verify(self, result: MergeResult) -> str | None:
        """Return a failure reason if the result cannot back a publish, else None."""
        if not result.ok:
            return result.reason or "merger reported failure"
        if not result.final_output_id:
            return "merger reported ok without a final_output_id"
        if not result.temp_path:
            return "merger reported ok without a temp_path"
        if not Path(result.temp_path).exists():
            return f"verified temporary artifact missing at {result.temp_path!r}"
        if not result.published_path:
            return "merger reported ok without a published_path"
        return None

    def _fail(
        self, claim: FinalizationClaim, *, reason: str, temp_path: str | None
    ) -> FinalizationOutcome:
        try:
            self._repo.mark_merge_failed(
                claim.logical_sink_id,
                finalization_id=claim.finalization_id,
                fence_token=claim.fence_token,
                now=self._now_fn(),
            )
        except StaleFinalizerClaim:
            return FinalizationOutcome(
                logical_sink_id=claim.logical_sink_id,
                action="skipped",
                temp_path=temp_path,
                reason="fenced out by a newer finalization attempt",
            )
        return FinalizationOutcome(
            logical_sink_id=claim.logical_sink_id,
            action="failed",
            temp_path=temp_path,
            reason=reason,
        )

    # -- cleanup gate (boundary for packet 29) ------------------------------

    def cleanup_eligibility(self, logical_sink_id: str) -> bool:
        """True only when superseded components may be deleted.

        Cleanup cannot run until a verified publish is durable: the output must
        be ``merged`` with a ``final_output_id`` and the configured retention
        window must have elapsed since ``finalized_at``. Single-component
        (``not_required``) outputs are never eligible — the component *is* the
        output.
        """
        head = self._repo.get_head(logical_sink_id)
        if head is None:
            return False
        if head.artifact_state != ARTIFACT_MERGED:
            return False
        if head.final_output_id is None or head.finalized_at is None:
            return False
        finalized_at = head.finalized_at
        if finalized_at.tzinfo is None:
            finalized_at = finalized_at.replace(tzinfo=UTC)
        deadline = finalized_at + timedelta(seconds=self._retention_seconds)
        return self._now_fn() >= deadline


def coordinator_from_config(
    config, *, now_fn: Callable[[], datetime] = _now
) -> FinalizationCoordinator:
    """Build a coordinator from a resolved config class (see app.config)."""
    return FinalizationCoordinator(
        temp_dir=config.FINALIZER_TEMP_DIR,
        lease_ttl_seconds=config.FINALIZER_LEASE_TTL_SECONDS,
        retention_seconds=config.FINALIZER_COMPONENT_RETENTION_SECONDS,
        heartbeat_interval_seconds=config.FINALIZER_HEARTBEAT_INTERVAL_SECONDS,
        now_fn=now_fn,
    )


# ---------------------------------------------------------------------------
# Stop / completion boundary (packet 29)
# ---------------------------------------------------------------------------
#
# A clean user stop (or another terminal recording completion such as a daemon
# shutdown) is a COMPLETION BOUNDARY for every logical output the stopped
# session owns. This is the control-plane side of the SINK-24/SINK-26 contract:
#
#   * mark each logical output's terminal component acquisition-``complete`` and
#     durably record WHY writing ended (``termination_reason``), so a completed
#     acquisition can never be confused with an error-recovery continuation or a
#     forced/crash termination;
#   * SCHEDULE finalization (``mark_merge_pending``) — ``merge_pending`` for a
#     multi-component EDF/PVFS output, ``not_required`` for a single component —
#     WITHOUT waiting for the merge;
#   * never reuse the completed logical output's identity: a later start
#     allocates a wholly new ``logical_sink_id`` + path (see
#     ``app.output.managed_file.create``), so a stale finalizer holding the prior
#     logical output's fenced claim physically cannot touch the new acquisition's
#     rows.
#
# It NEVER owns hardware and NEVER blocks the stop on merge completion.

# Completion causes: WHICH control-plane path completed the acquisition. The
# durable evidence of a clean completion is the component's
# ``acquisition_state``/``termination_reason``; the cause labels the origin so
# release gates and operator status can distinguish an operator stop from a
# daemon shutdown.
COMPLETION_USER_STOP = "user_stop"
COMPLETION_SHUTDOWN = "shutdown"

# Terminal ``termination_reason`` recorded on the completing component. Kept in
# the packet-11 vocabulary (``clean`` / ``recovery`` / ``watchdog_crash`` /
# ``forced`` / ``writer_failure``); a clean stop ends writing cleanly.
TERMINATION_CLEAN = "clean"

# Head ``artifact_state`` values that already reflect a scheduled/finalized job,
# so re-scheduling is a no-op.
_SCHEDULED_STATES = frozenset(
    {
        ARTIFACT_MERGE_PENDING,
        ARTIFACT_MERGING,
        ARTIFACT_MERGED,
        ARTIFACT_MERGE_FAILED,
    }
)


@dataclass(frozen=True)
class AcquisitionCompletion:
    """What completing + scheduling one logical output at a stop boundary did."""

    logical_sink_id: str
    completion_cause: str
    termination_reason: str
    artifact_state: str  # head state after scheduling
    finalization_scheduled: bool  # True when a multi-component merge was enqueued
    already_complete: bool  # the writers had already recorded completion


def _session_head_logical_ids(session_id: int) -> list[str]:
    """The ``logical_sink_id`` of every logical output owned by ``session_id``.

    Ordered by creation so a caller-visible summary is stable. Reads head rows
    (``segment_index == 0``) — the canonical finalization-state carriers.
    """
    rows = db.session.scalars(
        db.select(OutputFile.logical_sink_id)
        .where(
            OutputFile.session_id == session_id,
            OutputFile.segment_index == 0,
        )
        .order_by(OutputFile.created_at.asc(), OutputFile.id.asc())
    ).all()
    seen: set[str] = set()
    ordered: list[str] = []
    for logical in rows:
        if logical not in seen:
            seen.add(logical)
            ordered.append(logical)
    return ordered


def _mark_terminal_complete(
    component: OutputFile, *, termination_reason: str, now: datetime
) -> None:
    """Durably record the completion boundary on one terminal component.

    Idempotent and non-destructive: it closes the row and stamps
    ``acquisition_state='complete'``, but never OVERWRITES a
    ``termination_reason`` a writer already recorded (e.g. a more specific
    ``forced``/``recovery``) — it only fills one in when absent.
    """
    with transaction():
        component.status = STATUS_CLOSED
        component.acquisition_state = ACQUISITION_COMPLETE
        if component.termination_reason is None:
            component.termination_reason = termination_reason


def complete_session_acquisitions(
    session_id: int,
    *,
    completion_cause: str = COMPLETION_USER_STOP,
    termination_reason: str = TERMINATION_CLEAN,
    repository: OutputFilesRepository | None = None,
    now_fn: Callable[[], datetime] = _now,
) -> list[AcquisitionCompletion]:
    """Complete a stopped session's acquisitions and enqueue any finalization.

    The stop-boundary primitive for packet 29. For every logical output owned by
    ``session_id`` it (1) records the completion boundary on the terminal
    component — ``acquisition_state='complete'`` + a durable
    ``termination_reason`` — then (2) schedules finalization via
    :meth:`OutputFilesRepository.mark_merge_pending`: ``merge_pending`` for a
    multi-component output, ``not_required`` for a single component.

    Returns one :class:`AcquisitionCompletion` per logical output. It never
    waits for the merge, never owns hardware, and never reuses a completed
    logical output's identity — so it is safe to call on the stop path and an
    immediate later start allocates entirely fresh output identities.
    """
    repo = repository or OutputFilesRepository()
    now = now_fn()
    outcomes: list[AcquisitionCompletion] = []

    for logical in _session_head_logical_ids(session_id):
        components = repo.list_components(logical)
        if not components:
            continue

        terminal = components[-1]  # highest segment_index (ordered ascending)
        already_complete = (
            terminal.acquisition_state == ACQUISITION_COMPLETE
            and all(c.status == STATUS_CLOSED for c in components)
        )
        if not already_complete:
            _mark_terminal_complete(
                terminal, termination_reason=termination_reason, now=now
            )

        head = repo.mark_merge_pending(logical)
        outcomes.append(
            AcquisitionCompletion(
                logical_sink_id=logical,
                completion_cause=completion_cause,
                termination_reason=terminal.termination_reason or termination_reason,
                artifact_state=head.artifact_state,
                finalization_scheduled=head.artifact_state == ARTIFACT_MERGE_PENDING,
                already_complete=already_complete,
            )
        )

    return outcomes


# A merger registry maps a sink_type to its Merger. Real mergers (EDF/PVFS)
# land in packets 17/18; until then the registry is empty and an unmatched
# sink_type leaves the job retryable (merge_failed) rather than crashing the
# finalizer process — never publishing a false artifact.
MergerRegistry = dict[str, Merger]


def resolve_merger(
    registry: MergerRegistry, sink_type: str
) -> Merger:
    """Return a merger for ``sink_type`` or a no-op that fails the attempt.

    The fallback keeps the finalizer process alive and the job retryable when
    no format merger is registered yet (e.g. before packets 17/18 land).
    """
    merger = registry.get(sink_type)
    if merger is not None:
        return merger

    def _no_merger(_request: MergeRequest) -> MergeResult:
        return MergeResult(
            ok=False,
            reason=f"no merger registered for sink_type {sink_type!r}",
        )

    return _no_merger


def register_merger(
    registry: MergerRegistry, sink_type: str, merger: Merger
) -> MergerRegistry:
    """Register ``merger`` for ``sink_type`` in ``registry`` (additive, in place).

    A ``register``-style hook shared by every format-merger packet: packet 17
    registers ``"edf"`` and packet 18 registers ``"pvfs"`` through this same
    function, so the registry grows without any packet rewriting another's
    wiring or packet 16's coordinator/contract. Returns the (mutated) registry
    for chaining.
    """
    registry[sink_type] = merger
    return registry


def build_default_merger_registry() -> MergerRegistry:
    """Build the merger registry a finalizer process injects at startup.

    Additive by construction — each format packet contributes exactly one
    ``register_merger`` line here. Imports are deferred so this module keeps its
    zero hard-dependency on the format/native libraries at import time; the
    finalizer only imports them when a real merge runs.
    """
    registry: MergerRegistry = {}

    # Packet 17 — EDF continuation-component merge.
    from app.output.edf_merger import edf_staging_merger

    register_merger(registry, "edf", edf_staging_merger)

    # Packet 18 — PVFS continuation-component merge.
    from app.output.pvfs_merger import pvfs_staging_merger

    register_merger(registry, "pvfs", pvfs_staging_merger)

    return registry
