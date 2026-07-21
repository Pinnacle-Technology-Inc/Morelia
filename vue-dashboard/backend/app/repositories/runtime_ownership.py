from datetime import UTC, datetime

from app.database import db, transaction
from app.domain.enums import RuntimeOwnershipState, WatchdogProcessState
from app.domain.errors import StaleWatchdogReport
from app.models.runtime_ownership import RuntimeOwnership

ACTIVE_RUNTIME_STATES = (
    RuntimeOwnershipState.STARTING,
    RuntimeOwnershipState.RUNNING,
    RuntimeOwnershipState.ADOPTED,
    RuntimeOwnershipState.RECOVERING,
    RuntimeOwnershipState.STOPPING,
)


class RuntimeOwnershipRepository:
    """Persistence operations for runtime host ownership records."""

    def create_starting(
        self,
        *,
        runtime_id: str,
        session_id: int,
        dataflow_id: str,
        manifest_hash: str,
        token: str | None,
        details: dict | None = None,
    ) -> RuntimeOwnership:
        with transaction():
            row = RuntimeOwnership(
                runtime_id=runtime_id,
                session_id=session_id,
                dataflow_id=dataflow_id,
                manifest_hash=manifest_hash,
                token=token,
                state=RuntimeOwnershipState.STARTING,
                details=dict(details) if details is not None else None,
            )
            db.session.add(row)
            db.session.flush()
        return row

    def get(self, runtime_id: str) -> RuntimeOwnership | None:
        return db.session.scalars(
            db.select(RuntimeOwnership).where(RuntimeOwnership.runtime_id == runtime_id)
        ).first()

    def list_for_session(self, session_id: int) -> list[RuntimeOwnership]:
        """Every runtime host ever registered for a session, newest first."""
        return list(
            db.session.scalars(
                db.select(RuntimeOwnership)
                .where(RuntimeOwnership.session_id == session_id)
                .order_by(RuntimeOwnership.started_at.desc(), RuntimeOwnership.id.desc())
            ).all()
        )

    def list_active(self) -> list[RuntimeOwnership]:
        """Every row still in an active state, across all dataflows."""
        return list(
            db.session.scalars(
                db.select(RuntimeOwnership).where(
                    RuntimeOwnership.state.in_(ACTIVE_RUNTIME_STATES)
                )
            ).all()
        )

    def active_for_dataflow(self, dataflow_id: str) -> RuntimeOwnership | None:
        return db.session.scalars(
            db.select(RuntimeOwnership)
            .where(
                RuntimeOwnership.dataflow_id == dataflow_id,
                RuntimeOwnership.state.in_(ACTIVE_RUNTIME_STATES),
            )
            .order_by(RuntimeOwnership.started_at.desc())
        ).first()

    def mark_running(self, runtime_id: str, *, pid: int, port: int) -> RuntimeOwnership:
        with transaction():
            row = self._required(runtime_id)
            row.pid = pid
            row.port = port
            row.state = RuntimeOwnershipState.RUNNING
            row.last_seen_at = datetime.now(UTC)
            db.session.flush()
        return row

    def mark_seen(self, runtime_id: str) -> RuntimeOwnership:
        with transaction():
            row = self._required(runtime_id)
            row.last_seen_at = datetime.now(UTC)
            db.session.flush()
        return row

    def mark_adopted(self, runtime_id: str, *, port: int) -> RuntimeOwnership:
        with transaction():
            row = self._required(runtime_id)
            now = datetime.now(UTC)
            row.port = port
            row.state = RuntimeOwnershipState.ADOPTED
            row.adopted_at = now
            row.last_seen_at = now
            db.session.flush()
        return row

    def mark_stopping(self, runtime_id: str) -> RuntimeOwnership:
        with transaction():
            row = self._required(runtime_id)
            row.state = RuntimeOwnershipState.STOPPING
            db.session.flush()
        return row

    def mark_stopped(self, runtime_id: str) -> RuntimeOwnership:
        with transaction():
            row = self._required(runtime_id)
            row.state = RuntimeOwnershipState.STOPPED
            row.stopped_at = datetime.now(UTC)
            db.session.flush()
        return row

    def mark_uncertain(self, runtime_id: str, *, details: dict | None = None) -> RuntimeOwnership:
        with transaction():
            row = self._required(runtime_id)
            row.state = RuntimeOwnershipState.UNCERTAIN
            if details is not None:
                row.details = dict(details)
            db.session.flush()
        return row

    def mark_recovering(
        self,
        runtime_id: str,
        *,
        phase: str,
        reason: str,
        attempt: int,
        next_retry_at: str | None,
        evidence: dict | None = None,
    ) -> RuntimeOwnership:
        """Persist an automatic recovery that continues to fence hardware."""
        with transaction():
            row = self._required(runtime_id)
            row.state = RuntimeOwnershipState.RECOVERING
            details = dict(row.details or {})
            details["recovery"] = {
                "phase": phase,
                "reason": reason,
                "attempt": int(attempt),
                "next_retry_at": next_retry_at,
                "hardware_access": "blocked",
                "evidence": dict(evidence or {}),
            }
            row.details = details
            db.session.flush()
        return row

    def set_watchdog(
        self,
        runtime_id: str,
        *,
        watchdog_id: str,
        token_hash: str | None = None,
        pid: int | None = None,
        outbox_path: str | None = None,
        control_port: int | None = None,
    ) -> RuntimeOwnership:
        """Register a freshly spawned watchdog process as the active one.

        Clears any exit/crash details from a prior watchdog process under the
        same ``runtime_id`` — this is a new identity, not a continuation.
        """
        with transaction():
            row = self._required(runtime_id)
            row.watchdog_id = watchdog_id
            row.watchdog_token_hash = token_hash
            row.watchdog_pid = pid
            row.watchdog_control_port = control_port
            row.watchdog_outbox_path = outbox_path
            row.watchdog_state = WatchdogProcessState.STARTING
            row.watchdog_last_seen_at = datetime.now(UTC)
            row.watchdog_adopted_at = None
            row.watchdog_exit_details = None
            db.session.flush()
        return row

    def mark_watchdog_adopted(
        self,
        runtime_id: str,
        *,
        watchdog_id: str,
        pid: int | None = None,
        control_port: int | None = None,
    ) -> RuntimeOwnership:
        """Record that runtime_host reattached to a watchdog process it didn't spawn.

        Mirrors ``mark_adopted()`` one layer down: this is for a restarted
        ``runtime_host`` finding a live, identity-matching watchdog process
        (verified by the caller against the persisted watchdog_id/pid/
        token_hash) and reattaching rather than killing and respawning it —
        distinct from ``set_watchdog``'s fresh-identity claim, which would
        wrongly clear exit details and lose the "this was a reattach" signal.

        ``watchdog_id`` must match the row's current active ``watchdog_id``
        (same fencing as ``update_watchdog_seen``); a mismatch means the
        caller is about to adopt a stale/wrong identity, so it raises
        ``StaleWatchdogReport`` rather than silently claiming it.
        """
        with transaction():
            row = self._required(runtime_id)
            self._fence_watchdog_report(row, watchdog_id)
            now = datetime.now(UTC)
            if pid is not None:
                row.watchdog_pid = pid
            if control_port is not None:
                row.watchdog_control_port = control_port
            row.watchdog_state = WatchdogProcessState.ADOPTED
            row.watchdog_adopted_at = now
            row.watchdog_last_seen_at = now
            db.session.flush()
        return row

    def adopt_watchdog(
        self,
        runtime_id: str,
        *,
        watchdog_id: str,
        pid: int | None = None,
        control_port: int | None = None,
    ) -> RuntimeOwnership:
        """Claim a watchdog process that survived a runtime_host restart.

        Distinct from ``mark_watchdog_adopted`` (which reattaches to a
        watchdog THIS SAME row already claimed via ``set_watchdog``, and
        fences on a matching ``watchdog_id``): this is for a brand-new
        ``runtime_id`` row — a freshly spawned runtime_host (packet 06) that
        never spawned its own watchdog and is instead claiming, for the first
        time, a watchdog_id an *earlier* (now-dead) runtime_host's row left
        behind. See ``app.runtime_host.watchdog_process_driver`` and
        ``HostSupervisor.reconcile()``. No fencing check applies — there is
        nothing to fence against yet — but a row that already has an active
        watchdog_id cannot be adopted into a second time.
        """
        with transaction():
            row = self._required(runtime_id)
            if row.watchdog_id is not None:
                raise ValueError(
                    f"runtime {runtime_id!r} already has an active watchdog "
                    f"{row.watchdog_id!r}; cannot adopt {watchdog_id!r} over it "
                    "(use mark_watchdog_adopted for a same-row reattach)"
                )
            now = datetime.now(UTC)
            row.watchdog_id = watchdog_id
            row.watchdog_pid = pid
            row.watchdog_control_port = control_port
            row.watchdog_state = WatchdogProcessState.ADOPTED
            row.watchdog_adopted_at = now
            row.watchdog_last_seen_at = now
            db.session.flush()
        return row

    def update_watchdog_seen(
        self,
        runtime_id: str,
        *,
        watchdog_id: str,
        pid: int | None = None,
        control_port: int | None = None,
        state: WatchdogProcessState = WatchdogProcessState.RUNNING,
    ) -> RuntimeOwnership:
        """Record a heartbeat/state update from the active watchdog process.

        ``watchdog_id`` is the identity of the watchdog process instance
        reporting the update. It must match the row's current active
        ``watchdog_id``, fencing out late reports from a dead/respawned
        watchdog (see ``StaleWatchdogReport``).
        """
        with transaction():
            row = self._required(runtime_id)
            self._fence_watchdog_report(row, watchdog_id)
            if pid is not None:
                row.watchdog_pid = pid
            if control_port is not None:
                row.watchdog_control_port = control_port
            row.watchdog_state = state
            row.watchdog_last_seen_at = datetime.now(UTC)
            db.session.flush()
        return row

    def mark_watchdog_crashed(
        self, runtime_id: str, *, watchdog_id: str, details: dict | None = None
    ) -> RuntimeOwnership:
        """Record that the active watchdog process crashed.

        ``watchdog_id`` must match the row's current active ``watchdog_id``
        (see ``update_watchdog_seen``). This mutator is for evidence local to
        the runtime agent (exit code, local probe timeout) — control-plane-
        observed telemetry staleness must never call this.
        """
        with transaction():
            row = self._required(runtime_id)
            self._fence_watchdog_report(row, watchdog_id)
            row.watchdog_state = WatchdogProcessState.CRASHED
            row.watchdog_exit_details = dict(details) if details is not None else None
            db.session.flush()
        return row

    def mark_watchdog_stopped(
        self, runtime_id: str, *, watchdog_id: str, details: dict | None = None
    ) -> RuntimeOwnership:
        """Record that the active watchdog process stopped cleanly.

        ``watchdog_id`` must match the row's current active ``watchdog_id``
        (see ``update_watchdog_seen``).
        """
        with transaction():
            row = self._required(runtime_id)
            self._fence_watchdog_report(row, watchdog_id)
            row.watchdog_state = WatchdogProcessState.STOPPED
            row.watchdog_exit_details = dict(details) if details is not None else None
            db.session.flush()
        return row

    def mark_watchdog_uncertain(
        self, runtime_id: str, *, watchdog_id: str, details: dict
    ) -> RuntimeOwnership:
        """Mark uncertain when control plane have no conclusion about watchdog, different from
        "crashed" where we know the exact exit code and have evidence about what happened
        """
        if not details:
            raise ValueError(
                "mark_watchdog_uncertain requires non-empty provenance details"
            )
        with transaction():
            row = self._required(runtime_id)
            self._fence_watchdog_report(row, watchdog_id)
            row.watchdog_state = WatchdogProcessState.UNCERTAIN
            row.watchdog_exit_details = dict(details)
            db.session.flush()
        return row

    def clear_watchdog(self, runtime_id: str) -> RuntimeOwnership:
        """Wipe the active watchdog identity, e.g. before a respawn claims a new one."""
        with transaction():
            row = self._required(runtime_id)
            row.watchdog_id = None
            row.watchdog_token_hash = None
            row.watchdog_pid = None
            row.watchdog_control_port = None
            row.watchdog_outbox_path = None
            row.watchdog_state = None
            row.watchdog_last_seen_at = None
            row.watchdog_adopted_at = None
            row.watchdog_exit_details = None
            db.session.flush()
        return row

    @staticmethod
    def _required(runtime_id: str) -> RuntimeOwnership:
        row = db.session.scalars(
            db.select(RuntimeOwnership).where(RuntimeOwnership.runtime_id == runtime_id)
        ).first()
        if row is None:
            raise KeyError(f"runtime ownership not found: {runtime_id!r}")
        return row

    @staticmethod
    def _fence_watchdog_report(row: RuntimeOwnership, watchdog_id: str) -> None:
        """Reject a watchdog-state write that does not name the active watchdog_id.

        Also rejects when no watchdog is currently claimed (``row.watchdog_id``
        is ``None``) — a report naming an id is never valid against "no active
        watchdog". Raises rather than silently dropping the write so a stale
        report stays auditable instead of vanishing (see ``StaleWatchdogReport``).
        """
        if row.watchdog_id != watchdog_id:
            raise StaleWatchdogReport(
                row.runtime_id,
                reported_watchdog_id=watchdog_id,
                active_watchdog_id=row.watchdog_id,
            )
