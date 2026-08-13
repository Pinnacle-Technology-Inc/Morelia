"""Durable operation creation, scoped conflict checks, and state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.database import db, transaction
from app.domain.enums import OperationScope, OperationState
from app.domain.errors import OperationNotFound, OperationResolutionError
from app.models.operation import Operation
from app.models.session import Session
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import published_session_clause
from app.services import incidents, session_activity

DATAFLOW_COMMANDS = frozenset({"start", "stop", "complete", "restart-all-streams"})
STREAM_COMMANDS = frozenset({"reconnect", "restart", "reset-stream"})
ACTIVE_STATES = frozenset(
    {
        OperationState.QUEUED,
        OperationState.CLAIMED,
        OperationState.DISPATCHED,
        OperationState.RUNNING,
        OperationState.VERIFYING,
    }
)
TERMINAL_STATES = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.UNCERTAIN,
    }
)
ALLOWED_TRANSITIONS = {
    OperationState.QUEUED: frozenset(
        {
            OperationState.CLAIMED,
            OperationState.FAILED,
            OperationState.UNCERTAIN,
        }
    ),
    OperationState.CLAIMED: frozenset(
        {
            OperationState.DISPATCHED,
            OperationState.FAILED,
            OperationState.UNCERTAIN,
        }
    ),
    OperationState.DISPATCHED: frozenset(
        {
            OperationState.RUNNING,
            OperationState.VERIFYING,
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.UNCERTAIN,
        }
    ),
    OperationState.RUNNING: frozenset(
        {
            OperationState.VERIFYING,
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.UNCERTAIN,
        }
    ),
    OperationState.VERIFYING: frozenset(
        {
            OperationState.SUCCEEDED,
            OperationState.FAILED,
            OperationState.UNCERTAIN,
        }
    ),
}


class OperationConflict(Exception):
    """A new operation conflicts with active or unresolved work."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "command_in_flight",
        blocking_operation: Operation | None = None,
    ) -> None:
        self.code = code
        self.details = (
            _blocking_operation_details(blocking_operation)
            if blocking_operation is not None
            else {}
        )
        super().__init__(message)


class RequestKeyConflict(Exception):
    """A request key was reused with a different operation payload."""


class OperationTransitionError(Exception):
    """An operation state transition is not legal from the current state."""


@dataclass(frozen=True, slots=True)
class OperationClassification:
    scope: OperationScope
    requires_target: bool


def classify_command(command: str) -> OperationClassification:
    """Return the durable operation scope for a command."""
    if command in DATAFLOW_COMMANDS:
        return OperationClassification(
            scope=OperationScope.DATAFLOW,
            requires_target=False,
        )
    if command in STREAM_COMMANDS:
        return OperationClassification(
            scope=OperationScope.STREAM,
            requires_target=True,
        )
    raise ValueError(f"unsupported operation command: {command!r}")


def create_operation(
    *,
    session_id: int,
    dataflow_id: str,
    command: str,
    request_key: str,
    target_device_id: str | None = None,
    request_id: str | None = None,
    command_id: str | None = None,
    watchdog_id: str | None = None,
    recovery_id: str | None = None,
    manifest_hash: str | None = None,
    runtime_id: str | None = None,
    details: dict | None = None,
) -> Operation:
    """Create or return a durable operation after scoped conflict checks.

    Conflict domains:
    - dataflow-scope operations conflict with all active stream work in the dataflow.
    - stream-scope operations conflict only with the same stream and active dataflow work.
    - unresolved uncertain operations block the same conflict domain.
    """
    classification = classify_command(command)
    if classification.requires_target and not target_device_id:
        raise ValueError(f"command {command!r} requires target_device_id")
    if not classification.requires_target and target_device_id is not None:
        raise ValueError(f"command {command!r} must not include target_device_id")

    try:
        with transaction():
            existing = _find_by_request_key(dataflow_id, request_key)
            if existing is not None:
                _ensure_same_payload(
                    existing,
                    session_id=session_id,
                    command=command,
                    scope=classification.scope,
                    target_device_id=target_device_id,
                    recovery_id=recovery_id,
                    manifest_hash=manifest_hash,
                )
                return existing

            _raise_for_uncertain_conflict(
                dataflow_id=dataflow_id,
                scope=classification.scope,
                target_device_id=target_device_id,
            )
            _raise_for_active_conflict(
                dataflow_id=dataflow_id,
                scope=classification.scope,
                target_device_id=target_device_id,
            )

            operation_id = uuid4().hex
            row = Operation(
                operation_id=operation_id,
                request_key=request_key,
                session_id=session_id,
                dataflow_id=dataflow_id,
                scope=classification.scope,
                target_device_id=target_device_id,
                command=command,
                request_id=request_id,
                command_id=command_id or operation_id,
                watchdog_id=watchdog_id,
                recovery_id=recovery_id,
                manifest_hash=manifest_hash,
                runtime_id=runtime_id,
                state=OperationState.QUEUED,
                queued_at=datetime.now(UTC),
                details=dict(details) if details is not None else None,
            )
            db.session.add(row)
            db.session.flush()
            session_activity.record(
                session_id=row.session_id,
                dataflow_id=row.dataflow_id,
                kind="operation.requested",
                category="recovery" if row.recovery_id else "session",
                severity="info",
                title=f"{_command_label(row.command)} requested",
                summary=_operation_summary(row, "requested"),
                source_type="operation",
                source_id=row.operation_id,
                operation_id=row.operation_id,
                command_id=row.command_id,
                recovery_id=row.recovery_id,
                details=_activity_details(row),
                occurred_at=row.queued_at,
                commit=False,
            )
            return row
    except IntegrityError as exc:
        raise OperationConflict("operation conflicts with active operation") from exc


def stamp_runtime_id(operation_id: str, runtime_id: str) -> Operation:
    """Record which runtime host instance a dispatched command actually reached.

    Used for start, where the host (and its runtime_id) is only minted by
    ``supervisor.spawn()`` after the operation row already exists — unlike
    stop/recover, which can pass ``runtime_id`` straight into
    ``create_operation`` since the host is already running.
    """
    with transaction():
        operation = db.session.scalars(
            db.select(Operation).where(Operation.operation_id == operation_id)
        ).first()
        if operation is None:
            raise KeyError(f"operation not found: {operation_id!r}")
        operation.runtime_id = runtime_id
        db.session.flush()
    return operation


def transition_operation(
    operation_id: str,
    next_state: OperationState,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    details: dict | None = None,
) -> Operation:
    """Move an operation through the durable state machine.

    On landing in the terminal FAILED state, opens (or leaves open) a durable
    incident for the operation's conflict domain — the "failed-op" incident
    trigger. On landing in SUCCEEDED, resolves any incident opened by a prior
    failure of the SAME command in the SAME domain, so a retried operation that
    succeeds closes the loop without operator action. Both run AFTER the state
    transition commits (not nested inside its transaction()).
    """
    with transaction():
        operation = db.session.scalars(
            db.select(Operation).where(Operation.operation_id == operation_id)
        ).first()
        if operation is None:
            raise KeyError(f"operation not found: {operation_id!r}")

        current = operation.state
        if current in TERMINAL_STATES:
            raise OperationTransitionError(
                f"operation {operation_id!r} is terminal in state {current.value!r}"
            )
        if next_state not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise OperationTransitionError(
                f"cannot transition operation {operation_id!r} "
                f"from {current.value!r} to {next_state.value!r}"
            )

        operation.state = next_state
        _stamp_transition(operation, next_state)
        if error_code is not None:
            operation.error_code = error_code
        if error_message is not None:
            operation.error_message = error_message
        if details is not None:
            operation.details = dict(details)
        db.session.flush()
        if next_state in TERMINAL_STATES:
            _record_terminal_activity(operation, next_state)

    if next_state is OperationState.FAILED:
        incidents.evaluate_operation_failure(operation)
    elif next_state is OperationState.SUCCEEDED:
        incidents.evaluate_operation_success(operation)

    return operation


def record_operation_failure_event(
    operation: Operation,
    *,
    error_code: str,
    error_message: str,
    details: dict | None = None,
) -> int:
    """Persist an idempotent event describing a failed runtime command."""
    payload = {
        "operation_id": operation.operation_id,
        "command": operation.command,
        "command_id": operation.command_id,
        "error_code": error_code,
        "error_message": error_message,
    }
    if details:
        payload["details"] = dict(details)
    return BackendEventRepository().append(
        event_type="runtime.command_failed",
        session_id=operation.session_id,
        dataflow_id=operation.dataflow_id,
        payload=payload,
        runtime_id=operation.runtime_id,
        watchdog_id=operation.watchdog_id,
        # command_id is already bounded to the event model's 64-char limit and
        # is stable across retries, making the failure event idempotent.
        report_id=operation.command_id,
    )


def list_operations(
    *,
    state: OperationState | None = None,
    session_id: int | None = None,
    dataflow_id: str | None = None,
) -> list[Operation]:
    """Return operation ledger rows, newest first, optionally filtered."""
    query = (
        db.select(Operation)
        .join(Session, Session.id == Operation.session_id)
        .where(published_session_clause())
        .order_by(Operation.created_at.desc(), Operation.id.desc())
    )
    if state is not None:
        query = query.where(Operation.state == state)
    if session_id is not None:
        query = query.where(Operation.session_id == session_id)
    if dataflow_id is not None:
        query = query.where(Operation.dataflow_id == dataflow_id)
    return db.session.scalars(query).all()


def list_for_session(session_id: int, *, limit: int | None = None) -> list[Operation]:
    """Return a session's operation ledger rows, newest first (optionally capped)."""
    query = (
        db.select(Operation)
        .where(Operation.session_id == session_id)
        .order_by(Operation.created_at.desc(), Operation.id.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return db.session.scalars(query).all()


def get_operation(operation_id: str) -> Operation:
    """Return one operation ledger row by public operation id."""
    operation = db.session.scalars(
        db.select(Operation).where(Operation.operation_id == operation_id)
    ).first()
    if operation is None:
        raise OperationNotFound(operation_id)
    return operation


def resolve_uncertain_operation(
    operation_id: str,
    *,
    outcome: str,
    resolved_by: str,
    resolution_note: str,
) -> Operation:
    """Atomically terminalize an uncertain operation with an explicit outcome."""
    try:
        next_state = OperationState(outcome)
    except ValueError as exc:
        raise OperationResolutionError(operation_id, "outcome must be succeeded or failed") from exc
    if next_state not in {OperationState.SUCCEEDED, OperationState.FAILED}:
        raise OperationResolutionError(operation_id, "outcome must be succeeded or failed")
    with transaction():
        operation = db.session.scalars(
            db.select(Operation).where(Operation.operation_id == operation_id)
        ).first()
        if operation is None:
            raise OperationNotFound(operation_id)
        if (
            operation.state in {OperationState.SUCCEEDED, OperationState.FAILED}
            and operation.resolved_at
        ):
            if operation.state is next_state:
                return operation
            raise OperationResolutionError(
                operation_id, "a different terminal outcome was already recorded"
            )
        if operation.state != OperationState.UNCERTAIN or operation.resolved_at is not None:
            raise OperationResolutionError(operation_id, "operation is not unresolved uncertain")

        operation.resolved_by = resolved_by
        operation.resolved_at = datetime.now(UTC)
        operation.resolution_note = resolution_note
        _stamp_transition(operation, next_state)
        operation.state = next_state
        db.session.flush()
        _record_terminal_activity(operation, next_state, summary=resolution_note)
    if next_state is OperationState.FAILED:
        incidents.evaluate_operation_failure(operation)
    else:
        incidents.evaluate_operation_success(operation)
    return operation


def _stamp_transition(operation: Operation, state: OperationState) -> None:
    now = datetime.now(UTC)
    if state == OperationState.CLAIMED:
        operation.claimed_at = now
    elif state == OperationState.DISPATCHED:
        operation.dispatched_at = now
    elif state == OperationState.RUNNING:
        operation.running_at = now
    elif state == OperationState.VERIFYING:
        operation.verifying_at = now
    elif state in TERMINAL_STATES:
        operation.finished_at = now


def _command_label(command: str) -> str:
    return command.replace("-", " ").capitalize()


def _record_terminal_activity(
    operation: Operation,
    state: OperationState,
    *,
    summary: str | None = None,
) -> None:
    session_activity.record(
        session_id=operation.session_id,
        dataflow_id=operation.dataflow_id,
        kind=f"operation.{state.value}",
        category="recovery" if operation.recovery_id else "session",
        severity={
            OperationState.SUCCEEDED: "success",
            OperationState.FAILED: "error",
            OperationState.UNCERTAIN: "warning",
        }[state],
        title=(
            f"{_command_label(operation.command)} completed"
            if state is OperationState.SUCCEEDED
            else f"{_command_label(operation.command)} {state.value}"
        ),
        summary=(
            summary
            or operation.error_message
            or _operation_summary(operation, state.value)
        ),
        source_type="operation",
        source_id=operation.operation_id,
        operation_id=operation.operation_id,
        command_id=operation.command_id,
        recovery_id=operation.recovery_id,
        details=_activity_details(operation),
        occurred_at=operation.finished_at,
        commit=False,
    )


def _operation_summary(operation: Operation, outcome: str) -> str:
    target = (
        f" for device {operation.target_device_id}"
        if operation.target_device_id
        else ""
    )
    return f"{_command_label(operation.command)} was {outcome}{target}."


def _activity_details(operation: Operation) -> dict[str, object | None]:
    return {
        "command": operation.command,
        "scope": operation.scope.value,
        "target_device_id": operation.target_device_id,
        "runtime_id": operation.runtime_id,
        "watchdog_id": operation.watchdog_id,
        "error_code": operation.error_code,
    }


def _find_by_request_key(dataflow_id: str, request_key: str) -> Operation | None:
    return db.session.scalars(
        db.select(Operation).where(
            Operation.dataflow_id == dataflow_id,
            Operation.request_key == request_key,
        )
    ).first()


def _ensure_same_payload(
    operation: Operation,
    *,
    session_id: int,
    command: str,
    scope: OperationScope,
    target_device_id: str | None,
    recovery_id: str | None,
    manifest_hash: str | None,
) -> None:
    expected = (
        operation.session_id,
        operation.command,
        operation.scope,
        operation.target_device_id,
        operation.recovery_id,
        operation.manifest_hash,
    )
    incoming = (
        session_id,
        command,
        scope,
        target_device_id,
        recovery_id,
        manifest_hash,
    )
    if expected != incoming:
        raise RequestKeyConflict(
            "request key was reused with a different operation payload"
        )


def _raise_for_uncertain_conflict(
    *,
    dataflow_id: str,
    scope: OperationScope,
    target_device_id: str | None,
) -> None:
    unresolved = db.session.scalars(
        db.select(Operation).where(
            Operation.dataflow_id == dataflow_id,
            Operation.state == OperationState.UNCERTAIN,
            Operation.resolved_at.is_(None),
        )
    ).all()

    for operation in unresolved:
        if operation.scope == OperationScope.DATAFLOW:
            raise OperationConflict(
                "unresolved uncertain dataflow-scope operation blocks this dataflow",
                code="operation_blocked_by_uncertain",
                blocking_operation=operation,
            )
        if scope == OperationScope.DATAFLOW or operation.target_device_id == target_device_id:
            raise OperationConflict(
                "unresolved uncertain stream-scope operation blocks this conflict domain",
                code="operation_blocked_by_uncertain",
                blocking_operation=operation,
            )


def _raise_for_active_conflict(
    *,
    dataflow_id: str,
    scope: OperationScope,
    target_device_id: str | None,
) -> None:
    active = db.session.scalars(
        db.select(Operation).where(
            Operation.dataflow_id == dataflow_id,
            Operation.state.in_(ACTIVE_STATES),
        )
    ).all()

    for operation in active:
        if operation.scope == OperationScope.DATAFLOW:
            raise OperationConflict(
                "active dataflow-scope operation blocks this dataflow",
                blocking_operation=operation,
            )
        if scope == OperationScope.DATAFLOW:
            raise OperationConflict(
                "active stream-scope operation blocks dataflow-scope operation",
                blocking_operation=operation,
            )
        if operation.target_device_id == target_device_id:
            raise OperationConflict(
                "active stream-scope operation blocks this stream",
                blocking_operation=operation,
            )


def _blocking_operation_details(operation: Operation) -> dict:
    return {
        "operation_id": operation.operation_id,
        "dataflow_id": operation.dataflow_id,
        "scope": operation.scope.value,
        "target_device_id": operation.target_device_id,
        "command": operation.command,
        "operation_state": operation.state.value,
        "resolution_required": (
            operation.state == OperationState.UNCERTAIN
            and operation.resolved_at is None
        ),
    }
