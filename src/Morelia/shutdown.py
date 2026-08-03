"""Pure protocol state machine for one DataFlow shutdown attempt.

This module deliberately has no process, logging, filesystem, or application
dependencies.  The worker and watchdog can therefore share the record schema
without sharing lifecycle ownership.
"""

from dataclasses import dataclass, replace
from enum import Enum
from queue import Empty
import time
from typing import Iterable


class ShutdownPhase(str, Enum):
    REQUESTED = "requested"
    STOP_OBSERVED = "stop_observed"
    SOURCE_STOPPED = "source_stopped"
    SINKS_FINALIZING = "sinks_finalizing"
    SINKS_FINALIZED = "sinks_finalized"
    WORKER_EXITING = "worker_exiting"
    WORKER_EXITED = "worker_exited"
    COMPLETE = "complete"
    PHASE_FAILED = "phase_failed"
    PROTOCOL_VIOLATION = "protocol_violation"
    DEADLINE_EXPIRED = "deadline_expired"
    FORCE_TERMINATION_REQUESTED = "force_termination_requested"
    FORCED_TERMINATION = "forced_termination"
    FAILED = "failed"


class ShutdownOutcome(str, Enum):
    STARTED = "started"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    FORCED = "forced"
    DUPLICATE = "duplicate"


class ShutdownActor(str, Enum):
    RUNTIME = "runtime"
    MONITOR = "monitor"
    DATAFLOW_WORKER = "dataflow_worker"
    SINK = "sink"
    PVFS_WRITER = "pvfs_writer"


REQUIRED_SHUTDOWN_PHASES = (
    ShutdownPhase.STOP_OBSERVED,
    ShutdownPhase.SOURCE_STOPPED,
    ShutdownPhase.SINKS_FINALIZING,
    ShutdownPhase.SINKS_FINALIZED,
    ShutdownPhase.WORKER_EXITING,
    ShutdownPhase.WORKER_EXITED,
)
SHUTDOWN_PHASE_SEQUENCE = (ShutdownPhase.REQUESTED, *REQUIRED_SHUTDOWN_PHASES)
TERMINAL_SHUTDOWN_PHASES = (ShutdownPhase.COMPLETE, ShutdownPhase.FAILED)
MAX_SHUTDOWN_ACTIONS = 256


def _enum_value(value):
    return value.value if isinstance(value, Enum) else value


def _bounded_text(value, limit):
    if value is None:
        return None
    return str(value)[:limit]


@dataclass(frozen=True)
class ShutdownAction:
    """One stable, picklable shutdown transcript record."""

    shutdown_id: str
    stream_index: int
    actor: str
    actor_pid: int | None
    phase: ShutdownPhase | str
    action: str
    outcome: ShutdownOutcome | str
    emitted_at_ns: int
    sink_id: str | None = None
    output_id: str | None = None
    worker_exitcode: int | None = None
    error_type: str | None = None
    reason: str | None = None
    schema_version: int = 1
    action_seq: int | None = None
    elapsed_ms: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "phase", ShutdownPhase(_enum_value(self.phase)))
        object.__setattr__(self, "outcome", ShutdownOutcome(_enum_value(self.outcome)))
        object.__setattr__(self, "actor", ShutdownActor(_enum_value(self.actor)).value)
        if self.schema_version != 1:
            raise ValueError("unsupported shutdown action schema")
        if not isinstance(self.shutdown_id, str) or not self.shutdown_id:
            raise ValueError("shutdown_id must be a non-empty string")
        if not isinstance(self.stream_index, int) or self.stream_index < 0:
            raise ValueError("stream_index must be a non-negative integer")
        if self.actor_pid is not None and not isinstance(self.actor_pid, int):
            raise ValueError("actor_pid must be an integer or None")
        if not isinstance(self.emitted_at_ns, int):
            raise ValueError("emitted_at_ns must be an integer")
        if not isinstance(self.action, str) or not self.action:
            raise ValueError("action must be a non-empty string")
        object.__setattr__(self, "sink_id", _bounded_text(self.sink_id, 120))
        object.__setattr__(self, "output_id", _bounded_text(self.output_id, 120))
        object.__setattr__(self, "error_type", _bounded_text(self.error_type, 120))
        object.__setattr__(self, "reason", _bounded_text(self.reason, 500))


@dataclass(frozen=True)
class ShutdownSnapshot:
    """Immutable reducer state returned after every action."""

    shutdown_id: str
    stream_index: int
    phase: ShutdownPhase = ShutdownPhase.REQUESTED
    ok: bool | None = None
    reason: str | None = None
    forced_termination: bool = False
    worker_exitcode: int | None = None
    transcript: tuple[ShutdownAction, ...] = ()
    started_at_ns: int = 0
    max_actions: int = MAX_SHUTDOWN_ACTIONS

    @property
    def missing_phases(self) -> tuple[ShutdownPhase, ...]:
        acknowledged = {record.phase for record in self.transcript}
        return tuple(phase for phase in REQUIRED_SHUTDOWN_PHASES if phase not in acknowledged)

    @property
    def terminal_phase(self) -> ShutdownPhase | None:
        return self.phase if self.phase in TERMINAL_SHUTDOWN_PHASES else None


ShutdownResult = ShutdownSnapshot


def _elapsed_ms(state: ShutdownSnapshot, action: ShutdownAction) -> int:
    if action.elapsed_ms is not None:
        return max(0, int(action.elapsed_ms))
    if state.started_at_ns > 0 and action.emitted_at_ns > 0:
        return max(0, (action.emitted_at_ns - state.started_at_ns) // 1_000_000)
    return 0


def _append_action(state: ShutdownSnapshot, action: ShutdownAction):
    """Append in parent consumption order, reserving one bounded overflow slot."""
    if len(state.transcript) >= state.max_actions - 1 and action.action != "transcript_overflow":
        overflow = ShutdownAction(
            shutdown_id=state.shutdown_id,
            stream_index=state.stream_index,
            actor=ShutdownActor.MONITOR,
            actor_pid=None,
            phase=ShutdownPhase.FAILED,
            action="transcript_overflow",
            outcome=ShutdownOutcome.FAILED,
            emitted_at_ns=action.emitted_at_ns,
            reason="transcript_overflow",
            action_seq=len(state.transcript) + 1,
            elapsed_ms=_elapsed_ms(state, action),
        )
        return replace(
            state,
            phase=ShutdownPhase.FAILED,
            ok=False,
            reason="transcript_overflow",
            transcript=(*state.transcript, overflow),
        ), None

    recorded = replace(
        action,
        action_seq=len(state.transcript) + 1,
        elapsed_ms=_elapsed_ms(state, action),
    )
    return replace(state, transcript=(*state.transcript, recorded)), None


def _failure_action(state, source: ShutdownAction, phase: ShutdownPhase, reason: str):
    failure = ShutdownAction(
        shutdown_id=state.shutdown_id,
        stream_index=state.stream_index,
        actor=source.actor,
        actor_pid=source.actor_pid,
        phase=phase,
        action=source.action or phase.value,
        outcome=ShutdownOutcome.FAILED if phase != ShutdownPhase.DEADLINE_EXPIRED else ShutdownOutcome.TIMED_OUT,
        emitted_at_ns=source.emitted_at_ns,
        error_type=source.error_type,
        reason=reason,
        worker_exitcode=source.worker_exitcode,
        sink_id=source.sink_id,
        output_id=source.output_id,
        elapsed_ms=source.elapsed_ms,
    )
    state, _ = _append_action(state, failure)
    return replace(state, phase=phase, reason=reason, ok=False if phase == ShutdownPhase.FAILED else None)


def _terminal_failure(state, source: ShutdownAction, reason: str):
    state = _failure_action(state, source, ShutdownPhase.FAILED, reason)
    return replace(state, ok=False, reason=reason)


def _protocol_failure(state, source: ShutdownAction, reason: str):
    state = _failure_action(state, source, ShutdownPhase.PROTOCOL_VIOLATION, reason)
    return _terminal_failure(state, source, reason)


def reduce_shutdown(state: ShutdownSnapshot, action: ShutdownAction) -> ShutdownSnapshot:
    """Purely apply one action to a shutdown snapshot."""
    if len(state.transcript) >= state.max_actions:
        return state

    if action.shutdown_id != state.shutdown_id or action.stream_index != state.stream_index:
        return _protocol_failure(state, action, "protocol_violation")

    acknowledged = {record.phase for record in state.transcript}
    if action.phase in acknowledged and action.phase not in (ShutdownPhase.FAILED, ShutdownPhase.COMPLETE):
        duplicate = replace(action, outcome=ShutdownOutcome.DUPLICATE)
        state, _ = _append_action(state, duplicate)
        return state

    if state.phase in TERMINAL_SHUTDOWN_PHASES:
        return state

    if action.phase is ShutdownPhase.FAILED:
        state, _ = _append_action(state, action)
        return replace(state, phase=ShutdownPhase.FAILED, ok=False, reason=action.reason or "phase_failed")

    if action.phase in (
        ShutdownPhase.PHASE_FAILED,
        ShutdownPhase.PROTOCOL_VIOLATION,
        ShutdownPhase.DEADLINE_EXPIRED,
    ):
        reason = action.reason or action.phase.value
        if action.phase is ShutdownPhase.PROTOCOL_VIOLATION:
            return _protocol_failure(state, action, reason)
        return _failure_action(state, action, action.phase, reason)

    if state.phase is ShutdownPhase.DEADLINE_EXPIRED:
        expected = ShutdownPhase.FORCE_TERMINATION_REQUESTED
    elif state.phase is ShutdownPhase.FORCE_TERMINATION_REQUESTED:
        expected = ShutdownPhase.FORCED_TERMINATION
    elif state.phase is ShutdownPhase.FORCED_TERMINATION:
        expected = ShutdownPhase.FAILED
    else:
        expected_index = SHUTDOWN_PHASE_SEQUENCE.index(state.phase) + (0 if state.phase not in acknowledged else 1)
        expected = SHUTDOWN_PHASE_SEQUENCE[expected_index] if expected_index < len(SHUTDOWN_PHASE_SEQUENCE) else None
    if action.phase is ShutdownPhase.COMPLETE:
        if state.phase is ShutdownPhase.WORKER_EXITED and state.worker_exitcode == 0:
            state, _ = _append_action(state, action)
            return replace(state, phase=ShutdownPhase.COMPLETE, ok=True, reason=None)
        return _protocol_failure(state, action, "protocol_violation")

    if action.phase is not expected:
        return _protocol_failure(state, action, "protocol_violation")

    if action.phase is ShutdownPhase.WORKER_EXITED:
        state, _ = _append_action(state, action)
        if action.worker_exitcode != 0:
            return _terminal_failure(state, action, "worker_exit_nonzero")
        return replace(state, phase=action.phase, worker_exitcode=action.worker_exitcode)

    state, _ = _append_action(state, action)
    return replace(state, phase=action.phase)


class ShutdownProtocol:
    """Small mutable façade around the pure :func:`reduce_shutdown` reducer."""

    def __init__(self, shutdown_id: str, stream_index: int, *, started_at_ns: int = 0, max_actions: int = MAX_SHUTDOWN_ACTIONS):
        if max_actions < 2:
            raise ValueError("max_actions must leave room for a failure record")
        self.shutdown_id = shutdown_id
        self.stream_index = stream_index
        self._state = ShutdownSnapshot(
            shutdown_id=shutdown_id,
            stream_index=stream_index,
            started_at_ns=started_at_ns,
            max_actions=max_actions,
        )

    def snapshot(self) -> ShutdownSnapshot:
        return self._state

    @property
    def transcript(self):
        return self._state.transcript

    def apply(self, action: ShutdownAction) -> ShutdownSnapshot:
        self._state = reduce_shutdown(self._state, action)
        return self._state

    def _monitor_action(self, phase, action_name, outcome, *, reason=None, worker_exitcode=None):
        return self.apply(
            ShutdownAction(
                shutdown_id=self.shutdown_id,
                stream_index=self.stream_index,
                actor=ShutdownActor.MONITOR,
                actor_pid=None,
                phase=phase,
                action=action_name,
                outcome=outcome,
                emitted_at_ns=time.time_ns(),
                reason=reason,
                worker_exitcode=worker_exitcode,
            )
        )

    def request(self):
        return self._monitor_action(ShutdownPhase.REQUESTED, "stop_requested", ShutdownOutcome.STARTED)

    def deadline_expired(self, *, reason="required_acknowledgement_timeout"):
        return self._monitor_action(
            ShutdownPhase.DEADLINE_EXPIRED,
            "phase_deadline_expired",
            ShutdownOutcome.TIMED_OUT,
            reason=reason,
        )

    def force_termination_requested(self):
        return self._monitor_action(
            ShutdownPhase.FORCE_TERMINATION_REQUESTED,
            "worker_terminate_requested",
            ShutdownOutcome.STARTED,
        )

    def forced_termination(self, *, worker_exitcode=None):
        result = self._monitor_action(
            ShutdownPhase.FORCED_TERMINATION,
            "worker_terminated",
            ShutdownOutcome.FORCED,
            worker_exitcode=worker_exitcode,
        )
        if result.phase is ShutdownPhase.FORCED_TERMINATION:
            result = self._monitor_action(
                ShutdownPhase.FAILED,
                "shutdown_failed",
                ShutdownOutcome.FAILED,
                reason="forced_termination",
                worker_exitcode=worker_exitcode,
            )
        self._state = replace(result, forced_termination=True, ok=False, reason="forced_termination", worker_exitcode=worker_exitcode)
        return self._state

    def complete(self):
        return self.apply(
            ShutdownAction(
                shutdown_id=self.shutdown_id,
                stream_index=self.stream_index,
                actor=ShutdownActor.MONITOR,
                actor_pid=None,
                phase=ShutdownPhase.COMPLETE,
                action="shutdown_completed",
                outcome=ShutdownOutcome.COMPLETED,
                emitted_at_ns=time.time_ns(),
            )
        )

    def fail(self, reason: str = "phase_failed"):
        """Record a terminal parent-owned failure from any non-terminal state."""
        return self.apply(
            ShutdownAction(
                shutdown_id=self.shutdown_id,
                stream_index=self.stream_index,
                actor=ShutdownActor.MONITOR,
                actor_pid=None,
                phase=ShutdownPhase.FAILED,
                action="shutdown_failed",
                outcome=ShutdownOutcome.FAILED,
                emitted_at_ns=time.time_ns(),
                reason=reason,
            )
        )


def coordinate_shutdown(
    worker,
    stop_event,
    status_queue,
    shutdown_id: str,
    stream_index: int,
    join_timeout_sec: float,
    *,
    deadline: float | None = None,
):
    """Stop one worker and return the complete, bounded acknowledgement result.

    ``deadline`` lets a whole-flow caller share a single monotonic budget across
    every stream.  A single-stream caller can omit it and receives the same
    timeout semantics as the legacy monitor.
    """
    protocol = ShutdownProtocol(shutdown_id, stream_index, started_at_ns=time.time_ns())
    protocol.request()
    if stop_event is not None:
        stop_event.set()

    deadline = deadline if deadline is not None else time.monotonic() + max(0.0, float(join_timeout_sec))
    while worker is not None and worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if status_queue is not None:
            try:
                protocol.apply(status_queue.get(timeout=min(remaining, 0.05)))
                continue
            except Empty:
                pass
        worker.join(timeout=0)

    if worker is not None and worker.is_alive():
        protocol.deadline_expired()
        protocol.force_termination_requested()
        worker.terminate()
        worker.join(timeout=1.0)
        protocol.forced_termination(worker_exitcode=getattr(worker, "exitcode", None))
    elif worker is not None:
        worker.join(timeout=0)

    if status_queue is not None:
        while True:
            try:
                protocol.apply(status_queue.get_nowait())
            except Empty:
                break

    if protocol.snapshot().phase not in (
        ShutdownPhase.FAILED,
        ShutdownPhase.COMPLETE,
        ShutdownPhase.PHASE_FAILED,
        ShutdownPhase.PROTOCOL_VIOLATION,
        ShutdownPhase.DEADLINE_EXPIRED,
    ):
        protocol.apply(
            ShutdownAction(
                shutdown_id=shutdown_id,
                stream_index=stream_index,
                actor=ShutdownActor.MONITOR,
                actor_pid=None,
                phase=ShutdownPhase.WORKER_EXITED,
                action="worker_exit_observed",
                outcome=ShutdownOutcome.COMPLETED,
                emitted_at_ns=time.time_ns(),
                worker_exitcode=getattr(worker, "exitcode", None),
            )
        )

    snapshot = protocol.snapshot()
    if snapshot.phase not in (
        ShutdownPhase.COMPLETE,
        ShutdownPhase.FAILED,
        ShutdownPhase.PHASE_FAILED,
        ShutdownPhase.PROTOCOL_VIOLATION,
        ShutdownPhase.DEADLINE_EXPIRED,
    ):
        protocol.complete()
        snapshot = protocol.snapshot()
    if snapshot.phase not in (ShutdownPhase.COMPLETE, ShutdownPhase.FAILED):
        protocol.fail("missing_required_acknowledgement")
        snapshot = protocol.snapshot()

    return {
        "ok": snapshot.ok is True,
        "stream_index": stream_index,
        "worker_status": "stopped" if snapshot.ok is True else "failed",
        "shutdown_id": shutdown_id,
        "terminal_phase": snapshot.phase.value,
        "shutdown_phase": snapshot.phase.value,
        "forced_termination": snapshot.forced_termination,
        "worker_exitcode": snapshot.worker_exitcode
        if snapshot.worker_exitcode is not None
        else getattr(worker, "exitcode", None),
        "missing_phases": [phase.value for phase in snapshot.missing_phases],
        "transcript": snapshot.transcript,
        "shutdown_transcript": snapshot.transcript,
    }


__all__ = [
    "MAX_SHUTDOWN_ACTIONS",
    "REQUIRED_SHUTDOWN_PHASES",
    "SHUTDOWN_PHASE_SEQUENCE",
    "ShutdownAction",
    "ShutdownActor",
    "ShutdownOutcome",
    "ShutdownPhase",
    "ShutdownProtocol",
    "ShutdownResult",
    "ShutdownSnapshot",
    "coordinate_shutdown",
    "reduce_shutdown",
]
