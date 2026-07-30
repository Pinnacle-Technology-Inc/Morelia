"""Session services — pure business logic, no Flask imports.

Each function raises a typed domain exception (app.domain.errors) on failure.
The Flask adapter (app/api/sessions.py) and the CLI adapter (app/cli/)
translate those into their respective transports.

Note: prepare_command() reads request_id from structlog contextvars. Flask
wires this via request_logging middleware. CLI callers must bind it manually:
    from structlog.contextvars import bind_contextvars
    bind_contextvars(request_id=uuid4().hex)
"""

from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import structlog
from structlog.contextvars import get_contextvars

from app.database import transaction
from app.domain.enums import OperationState, SessionStatus, SinkCategory
from app.domain.errors import (
    CommandInFlight,
    EmptySession,
    InvalidSessionEntry,
    InvalidTransition,
    SessionNotFound,
    SinkParentUnavailable,
)
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository, default_session_name
from app.services import (
    device_configs,
    experiments,
    manifests,
    output_finalization,
    sink_paths,
)
from app.services.operations import (
    OperationConflict,
    create_operation,
    stamp_runtime_id,
    transition_operation,
    record_operation_failure_event,
)
from app.services.registry import UnknownConfigType, sink_parameter_schema
from app.services.session_config import validate_entries
from app.watchdog.commands import prepare_command

_log = structlog.get_logger(__name__)

_repo = SessionRepository()
_runtimes = RuntimeOwnershipRepository()


def _active_runtime_id(dataflow_id: str) -> str | None:
    """The runtime_id of the currently-live host for a dataflow, if any.

    Best-effort: an operation is still worth recording even when there is no
    live ownership row to attribute it to (e.g. the fallback single-watchdog
    path has no per-dataflow host at all).
    """
    ownership = _runtimes.active_for_dataflow(dataflow_id)
    return ownership.runtime_id if ownership is not None else None


def _active_watchdog_id(dataflow_id: str) -> str | None:
    """The watchdog PROCESS id that the runtime host is currently supervising, if any.
    """
    ownership = _runtimes.active_for_dataflow(dataflow_id)
    return ownership.watchdog_id if ownership is not None else None

# Statuses from which a session has NOT yet started — still safe to delete or start.
_PRE_START = {SessionStatus.DRAFT, SessionStatus.SCHEDULED, SessionStatus.STOPPED}
_STOPPABLE = {SessionStatus.ACTIVE}
# Recovery only makes sense against a live dataflow.
_RECOVERABLE = {SessionStatus.ACTIVE}
# The three escalating recovery intensities; all are STREAM-scope commands.
RECOVER_ACTIONS = frozenset({"reconnect", "restart", "reset-stream"})


def create(data: dict) -> Session:
    canonical = dict(data)
    experiments.ensure_assignable(canonical.get("experiment_id"))
    flows = canonical.get("device_flows") or []
    if flows:
        canonical["device_flows"] = validate_entries(flows)
    return _repo.create(canonical)


def get(session_id: int) -> Session:
    session = _repo.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)
    return session


def get_by_name(name: str) -> Session | None:
    return _repo.get_by_name(name)


def suggest_name() -> str:
    """The name create() would mint for a session submitted without one.

    A preview, not a reservation: it reads peek_next_id(), so a concurrent
    create can make it stale. Intended for display as a form placeholder, where
    being wrong costs nothing — the authoritative name is still assigned by
    create() from the real auto-increment id.
    """
    return default_session_name(_repo.peek_next_id())


def list_all() -> list[Session]:
    return _repo.all()


def delete(session_id: int) -> None:
    session = get(session_id)
    if session.status not in _PRE_START:
        raise InvalidTransition(session.status)
    _repo.delete(session_id)


def complete(session_id: int) -> Session:
    """Explicitly archive a resource-free stopped session.

    Completion is its own durable dataflow operation. It never calls Stop and
    therefore cannot infer terminal history from a prior stop operation.
    """
    session = get(session_id)
    if session.command_in_flight:
        raise CommandInFlight(session_id)
    if session.status is not SessionStatus.STOPPED:
        raise InvalidTransition(session.status)

    dataflow_id = session.dataflow_id or uuid4().hex
    request_id = _request_id("completing")
    try:
        operation = create_operation(
            session_id=session_id,
            dataflow_id=dataflow_id,
            command="complete",
            request_key=request_id,
            request_id=request_id,
        )
    except OperationConflict as exc:
        raise CommandInFlight(session_id, code=exc.code, details=exc.details) from exc

    # A retried request with the same durable request key is idempotent after
    # successful completion; it must not create a second terminal operation.
    if operation.state is OperationState.SUCCEEDED:
        return session
    if operation.state is not OperationState.QUEUED:
        raise CommandInFlight(session_id)

    transition_operation(operation.operation_id, OperationState.CLAIMED)
    try:
        with transaction():
            if not _repo.try_acquire_in_flight_lock(session_id):
                raise CommandInFlight(session_id)
            session.command_in_flight = True
            session.command_id = operation.command_id
            session.status = SessionStatus.COMPLETED
            session.command_in_flight = False
        transition_operation(operation.operation_id, OperationState.DISPATCHED)
        transition_operation(operation.operation_id, OperationState.SUCCEEDED)
    except Exception as exc:
        with transaction():
            session.command_in_flight = False
        transition_operation(
            operation.operation_id,
            OperationState.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        raise
    return session


def start(
    session_id: int,
    watchdog,
    *,
    sink_overrides: dict[str, str] | None = None,
) -> Session:
    """Transition a session to STARTING and dispatch the start command.

    ``sink_overrides`` relocates file sinks before the manifest resolves — see
    ``_apply_sink_overrides``. Accepted here as well as in ``start_managed`` so
    an operator's chosen output names are never silently dropped just because
    this deployment runs without a per-dataflow runtime host.

    Guard ordering matters — the lock check (command_in_flight) must come
    BEFORE state/precondition checks so a busy dataflow gets a 423, not a 409.

    The Python fast-path checks (command_in_flight, status, device_flows) are
    non-atomic but cheap; they short-circuit the common case without a DB round-
    trip. The atomic UPDATE WHERE inside the transaction() is the real gate for
    concurrent requests — two simultaneous callers can both pass the Python checks
    but only one will get rowcount=1 from try_acquire_in_flight_lock().

    watchdog.dispatch() runs inside the same transaction so a dispatch failure
    triggers the transaction() rollback, releasing the lock automatically with
    no cleanup code required.

    Raises:
        SessionNotFound     — no session with that id
        CommandInFlight     — another command is already running (423)
        InvalidTransition   — session is not in a startable status (409)
        EmptySession        — session has no device flows (409)
        WatchdogAdapterError and subclasses propagate from watchdog.dispatch()
    """
    session = get(session_id)
    if session.command_in_flight:
        raise CommandInFlight(session_id)
    if session.status not in _PRE_START:
        raise InvalidTransition(session.status)
    if not session.device_flows:
        raise EmptySession(session_id)
    if sink_overrides:
        _apply_sink_overrides(session, sink_overrides)

    # A stopped session starts a new generation. Never reuse the prior
    # dataflow/watchdog identity or append to its concluded outputs.
    dataflow_id = uuid4().hex if session.status is SessionStatus.STOPPED else (session.dataflow_id or uuid4().hex)
    watchdog_id = uuid4().hex if session.status is SessionStatus.STOPPED else (session.watchdog_id or uuid4().hex)
    request_id = get_contextvars().get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("request_id must be bound before starting a session")

    try:
        operation = create_operation(
            session_id=session_id,
            dataflow_id=dataflow_id,
            command="start",
            request_key=request_id,
            request_id=request_id,
            watchdog_id=watchdog_id,
        )
    except OperationConflict as exc:
        raise CommandInFlight(
            session_id,
            code=exc.code,
            details=exc.details,
        ) from exc

    transition_operation(operation.operation_id, OperationState.CLAIMED)

    envelope = prepare_command(
        command="start",
        dataflow_id=dataflow_id,
        watchdog_id=watchdog_id,
        command_id=operation.command_id,
        runtime_id=_active_runtime_id(dataflow_id),
    )

    try:
        with transaction():
            if not _repo.try_acquire_in_flight_lock(session_id):
                raise CommandInFlight(session_id)
            session.command_in_flight = True
            session.command_id = envelope.correlation.command_id
            session.dataflow_id = dataflow_id
            session.watchdog_id = watchdog_id
            session.status = SessionStatus.STARTING
            watchdog.dispatch(envelope)
    except Exception as exc:
        failed_operation = transition_operation(
            operation.operation_id,
            OperationState.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        try:
            record_operation_failure_event(
                failed_operation,
                error_code=type(exc).__name__,
                error_message=str(exc),
                details={"startup_rollback": True},
            )
        except Exception as event_exc:
            _log.error(
                "start rollback: durable failure event could not be persisted",
                session_id=session_id,
                operation_id=operation.operation_id,
                error=type(event_exc).__name__,
                message=str(event_exc),
            )
        raise

    transition_operation(operation.operation_id, OperationState.DISPATCHED)

    return session


# The key that identifies one file sink in a ``sink_overrides`` mapping. This
# IS the label a SinkLocationExists conflict reports, not a parallel copy of
# it — the retry sends back exactly what the conflict handed out.
sink_override_label = manifests.conflict_label


def _is_file_sink(sink_type: object) -> bool:
    """True for csv/edf/pvfs — the only sinks that own a ``sink_location``."""
    try:
        schema = sink_parameter_schema(str(sink_type))
    except UnknownConfigType:
        return False
    return schema["category"] == SinkCategory.FILE.value


def sink_restart_plan(session_id: int) -> dict:
    """Every file sink this session would write to on its next start.

    Read-only and side-effect free: it resolves and probes paths but creates
    nothing, so a UI can call it to build a "name the outputs" prompt before
    committing to a start.

    Each entry's ``key`` is the ``sink_overrides`` key that relocates it, so a
    caller can build the retry payload straight from this response without
    reconstructing labels. Sinks with no explicit ``sink_location`` are reported
    as ``assignment: "automatic"`` — start-time allocation names those inside
    OUTPUT_DIR and deduplicates them on its own, so they never block a restart
    and have no stable path to suggest ahead of time.

    Non-file sinks (service, plot) are omitted entirely: they own no path, so
    there is nothing to name and nothing that can collide.
    """
    session = get(session_id)
    entries: list[dict] = []
    for flow in session.device_flows or []:
        nickname = flow.get("nickname")
        for sink in flow.get("sinks") or []:
            sink_name = sink.get("sink_name")
            if sink_name is None or not _is_file_sink(sink.get("sink_type")):
                continue
            entry = {
                "key": sink_override_label(nickname, str(sink_name)),
                "nickname": nickname,
                "sink_name": str(sink_name),
                "sink_type": str(sink.get("sink_type")),
            }
            raw_location = sink.get("sink_location")
            if not raw_location:
                entries.append(
                    entry
                    | {
                        "assignment": "automatic",
                        "current_location": None,
                        "occupied": False,
                        "suggested_location": None,
                    }
                )
                continue

            resolved = sink_paths.resolve_sink_location(str(raw_location))
            occupied = sink_paths.path_is_claimed(resolved)
            entries.append(
                entry
                | {
                    "assignment": "explicit",
                    "current_location": resolved,
                    "occupied": occupied,
                    "suggested_location": str(
                        sink_paths.next_available_path(
                            Path(resolved), session_id=session_id
                        )
                    )
                    if occupied
                    else resolved,
                }
            )

    return {"session_id": session_id, "status": session.status, "sinks": entries}


def _apply_sink_overrides(session: Session, overrides: dict[str, str]) -> None:
    """Persist operator-confirmed sink_location fixes onto a not-yet-started session.

    Keys are the labels the conflict reported (``sink_override_label``):
    ``"<nickname>:<sink_name>"``, or a bare ``"<sink_name>"`` when the flow has
    no nickname. One source can own several file sinks, so a nickname alone
    cannot say *which* sink moved — and the new location is written onto the
    sink entry itself, which is the only place start-time resolution
    (``manifests._build_sink``) ever reads it from.

    Raises InvalidSessionEntry for a key matching no file sink — a stale
    override (the flows changed since the caller computed it) must fail loud
    rather than silently apply nothing and then re-raise the same conflict.
    """
    flows = [dict(flow) for flow in session.device_flows or []]
    matched: set[str] = set()
    for flow in flows:
        nickname = flow.get("nickname")
        sinks = [dict(sink) for sink in flow.get("sinks") or []]
        for sink in sinks:
            sink_name = sink.get("sink_name")
            if sink_name is None:
                continue
            label = sink_override_label(nickname, str(sink_name))
            if label not in overrides:
                continue
            if not _is_file_sink(sink.get("sink_type")):
                raise InvalidSessionEntry(
                    f"sink_overrides.{label}",
                    f"sink_location is only valid for file sinks (csv, edf, pvfs); "
                    f"{sink.get('sink_type')!r} is not one",
                )
            requested_location = str(overrides[label])
            resolved_location = sink_paths.resolve_sink_location(requested_location)
            parent_issue = sink_paths.sink_parent_issue(resolved_location)
            if parent_issue is not None:
                directory, reason = parent_issue
                raise SinkParentUnavailable(
                    resolved_location,
                    directory=directory,
                    reason=reason,
                    nickname=label,
                )
            sink["sink_location"] = requested_location
            matched.add(label)
        flow["sinks"] = sinks

    unknown = set(overrides) - matched
    if unknown:
        raise InvalidSessionEntry(
            "sink_overrides",
            f"no file sink matches override key(s): {sorted(unknown)}",
        )

    with transaction():
        session.device_flows = flows


def start_managed(
    session_id: int,
    supervisor,
    *,
    sink_overrides: dict[str, str] | None = None,
    force: bool = False,
) -> Session:
    """Start a session through a per-dataflow runtime host managed by the daemon.
    """
    session = get(session_id)
    if session.command_in_flight:
        raise CommandInFlight(session_id)
    if session.status not in _PRE_START:
        raise InvalidTransition(session.status)
    if not session.device_flows:
        raise EmptySession(session_id)
    if sink_overrides:
        _apply_sink_overrides(session, sink_overrides)

    original_status = session.status
    dataflow_id = uuid4().hex if session.status is SessionStatus.STOPPED else (session.dataflow_id or uuid4().hex)
    watchdog_id = uuid4().hex if session.status is SessionStatus.STOPPED else (session.watchdog_id or uuid4().hex)
    request_id = _request_id("starting")
    manifest = manifests.resolve(session_id, dataflow_id=dataflow_id)

    try:
        operation = create_operation(
            session_id=session_id,
            dataflow_id=dataflow_id,
            command="start",
            request_key=request_id,
            request_id=request_id,
            watchdog_id=watchdog_id,
            manifest_hash=manifest.hash,
        )
    except OperationConflict as exc:
        raise CommandInFlight(
            session_id,
            code=exc.code,
            details=exc.details,
        ) from exc

    transition_operation(operation.operation_id, OperationState.CLAIMED)

    claimed_config_ids: list[int] = []
    spawned = False
    try:
        claimed_config_ids = _claim_device_configs(session, session_id, force=force)
        with transaction():
            if not _repo.try_acquire_in_flight_lock(session_id):
                raise CommandInFlight(session_id)
            session.command_in_flight = True
            session.command_id = operation.command_id
            session.dataflow_id = dataflow_id
            session.watchdog_id = watchdog_id
            session.status = SessionStatus.STARTING

        supervisor.spawn(session, manifest=manifest)
        spawned = True
        runtime_id = _active_runtime_id(dataflow_id)
        if runtime_id is not None:
            operation = stamp_runtime_id(operation.operation_id, runtime_id)

        # The readiness barrier now starts the child watchdog before the host
        # accepts commands. The session-level watchdog UUID was minted before
        # spawn and is not the child-process identity used for fencing, so the
        # start envelope must target the identity discovered after spawn.
        envelope = prepare_command(
            command="start",
            dataflow_id=dataflow_id,
            watchdog_id=_active_watchdog_id(dataflow_id) or watchdog_id,
            command_id=operation.command_id,
            runtime_id=runtime_id,
        )
        supervisor.dispatch(session, envelope)
    except Exception as exc:
        if spawned:
            try:
                supervisor.stop(session)
            except Exception as stop_exc:
                _log.warning(
                    "start rollback: stopping the just-spawned host failed — "
                    "a zombie runtime host may be left running",
                    dataflow_id=dataflow_id,
                    session_id=session.id,
                    error=type(stop_exc).__name__,
                    message=str(stop_exc),
                )
        _release_device_configs(claimed_config_ids)
        with transaction():
            session.command_in_flight = False
            session.status = original_status
            session.runtime_port = None
            session.runtime_token = None
        failed_operation = transition_operation(
            operation.operation_id,
            OperationState.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        try:
            record_operation_failure_event(
                failed_operation,
                error_code=type(exc).__name__,
                error_message=str(exc),
                details={"startup_rollback": True},
            )
        except Exception as event_exc:
            _log.error(
                "start rollback: durable failure event could not be persisted",
                session_id=session_id,
                operation_id=operation.operation_id,
                error=type(event_exc).__name__,
                message=str(event_exc),
            )
        raise

    transition_operation(operation.operation_id, OperationState.DISPATCHED)
    transition_operation(operation.operation_id, OperationState.SUCCEEDED)

    for config_id in claimed_config_ids:
        device_configs.activate(config_id, session_id)

    with transaction():
        session.command_in_flight = False
        session.status = SessionStatus.ACTIVE

    return session


def stop(session_id: int, watchdog) -> Session:
    """Transition an active session to ENDING and dispatch the stop command.

    Guard ordering intentionally mirrors start(): an in-flight command is
    reported before lifecycle precondition failures.
    """
    session = get(session_id)
    if session.command_in_flight:
        raise CommandInFlight(session_id)
    if session.status not in _STOPPABLE:
        raise InvalidTransition(session.status)

    dataflow_id = session.dataflow_id or uuid4().hex
    watchdog_id = session.watchdog_id or uuid4().hex
    request_id = get_contextvars().get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("request_id must be bound before stopping a session")

    try:
        operation = create_operation(
            session_id=session_id,
            dataflow_id=dataflow_id,
            command="stop",
            request_key=request_id,
            request_id=request_id,
            watchdog_id=watchdog_id,
        )
    except OperationConflict as exc:
        raise CommandInFlight(
            session_id,
            code=exc.code,
            details=exc.details,
        ) from exc

    transition_operation(operation.operation_id, OperationState.CLAIMED)

    envelope = prepare_command(
        command="stop",
        dataflow_id=dataflow_id,
        watchdog_id=watchdog_id,
        command_id=operation.command_id,
        runtime_id=_active_runtime_id(dataflow_id),
    )

    try:
        with transaction():
            if not _repo.try_acquire_in_flight_lock(session_id):
                raise CommandInFlight(session_id)
            session.command_in_flight = True
            session.command_id = envelope.correlation.command_id
            session.dataflow_id = dataflow_id
            session.watchdog_id = watchdog_id
            session.status = SessionStatus.ENDING
            watchdog.dispatch(envelope)
    except Exception as exc:
        transition_operation(
            operation.operation_id,
            OperationState.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        raise

    transition_operation(operation.operation_id, OperationState.DISPATCHED)

    return session


def stop_managed(session_id: int, supervisor, *, force: bool = False) -> Session:
    """Stop a managed runtime host and release the session's claimed configs."""
    session = get(session_id)
    if session.command_in_flight:
        raise CommandInFlight(session_id)
    if session.status not in _STOPPABLE:
        raise InvalidTransition(session.status)

    dataflow_id = session.dataflow_id or uuid4().hex
    watchdog_id = session.watchdog_id or uuid4().hex
    request_id = _request_id("stopping")
    # validate_sink_locations=False: this session is ACTIVE, so its sink
    # files already exist by design (the running host is writing to them
    # right now) — re-checking here would reject the stop over the
    # session's own output file (see manifests.resolve's docstring).
    manifest = manifests.resolve(session_id, dataflow_id=dataflow_id, validate_sink_locations=False)

    active_runtime_id = _active_runtime_id(dataflow_id)
    try:
        operation = create_operation(
            session_id=session_id,
            dataflow_id=dataflow_id,
            command="stop",
            request_key=request_id,
            request_id=request_id,
            watchdog_id=watchdog_id,
            manifest_hash=manifest.hash,
            runtime_id=active_runtime_id,
        )
    except OperationConflict as exc:
        raise CommandInFlight(
            session_id,
            code=exc.code,
            details=exc.details,
        ) from exc

    transition_operation(operation.operation_id, OperationState.CLAIMED)

    envelope = prepare_command(
        command="stop",
        dataflow_id=dataflow_id,
        # Target the runtime host's actual actively-tracked watchdog process
        # identity when one is known — not the session's own watchdog_id —
        # so a WatchdogProcessDriver-backed host doesn't silently 400-reject
        # this as a stale command (see _active_watchdog_id). Falls back to
        # the session-level identity for drivers that don't supervise a
        # separate watchdog process at all (no active identity to target).
        watchdog_id=_active_watchdog_id(dataflow_id) or watchdog_id,
        command_id=operation.command_id,
        runtime_id=active_runtime_id,
    )

    try:
        with transaction():
            if not _repo.try_acquire_in_flight_lock(session_id):
                raise CommandInFlight(session_id)
            session.command_in_flight = True
            session.command_id = envelope.correlation.command_id
            session.dataflow_id = dataflow_id
            session.watchdog_id = watchdog_id
            session.status = SessionStatus.ENDING

        supervisor.stop(session, envelope=envelope)
    except Exception as exc:
        if force:
            # A forced stop still terminalizes the session and frees its
            # devices — otherwise the claim outlives the (now untracked or
            # unreachable) runtime with no recovery route but DB surgery. The
            # operation stays UNCERTAIN to record that teardown was unclean.
            _release_session_device_configs(session)
            with transaction():
                session.command_in_flight = False
                session.status = SessionStatus.STOPPED
                session.runtime_port = None
                session.runtime_token = None
            transition_operation(
                operation.operation_id,
                OperationState.UNCERTAIN,
                error_code="forced_stop",
                error_message=str(exc),
                details={"forced": True},
            )
            return session
        with transaction():
            session.command_in_flight = False
            session.status = SessionStatus.ACTIVE
        transition_operation(
            operation.operation_id,
            OperationState.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        raise

    transition_operation(operation.operation_id, OperationState.DISPATCHED)
    transition_operation(operation.operation_id, OperationState.SUCCEEDED)

    # Clean user stop is a generation boundary: finalize each logical output's
    # acquisition complete and enqueue any EDF/PVFS merge WITHOUT waiting for it
    # (packet 29). Best-effort — a scheduling failure leaves the outputs in a
    # retryable, already-completed state and must never block the stop or trap
    # the hardware; the acquisition is never reopened on a later start.
    _schedule_stop_finalization(session)

    _release_session_device_configs(session)

    with transaction():
        session.command_in_flight = False
        session.status = SessionStatus.STOPPED
        session.runtime_port = None
        session.runtime_token = None

    return session


def _schedule_stop_finalization(session: Session) -> None:
    """Complete + enqueue finalization for a cleanly-stopped session's outputs.

    Never raises: the stop has already succeeded and released (or is about to
    release) the hardware, so a finalization-scheduling hiccup must not turn a
    clean stop into a failure. The logical outputs stay completed and
    schedulable by the finalizer/reconciler on a later pass.
    """
    try:
        output_finalization.complete_session_acquisitions(
            session.id,
            completion_cause=output_finalization.COMPLETION_USER_STOP,
        )
    except Exception as exc:  # noqa: BLE001 - completion must not fail the stop
        _log.warning(
            "stop: scheduling output finalization failed — outputs remain "
            "completed and retryable; hardware release proceeds",
            session_id=session.id,
            dataflow_id=session.dataflow_id,
            error=type(exc).__name__,
            message=str(exc),
        )


def recover(session_id: int, device_id: str, action: str, watchdog) -> Session:
    """Command a targeted per-stream recovery through the single watchdog adapter."""
    return _recover(
        session_id,
        device_id,
        action,
        dispatch=lambda session, envelope: watchdog.dispatch(envelope),
    )


def recover_managed(session_id: int, device_id: str, action: str, supervisor) -> Session:
    """Command a targeted per-stream recovery through the per-dataflow runtime host."""
    return _recover(
        session_id,
        device_id,
        action,
        dispatch=supervisor.dispatch,
        resolve_runtime_id=_active_runtime_id,
    )


def _recover(
    session_id: int,
    device_id: str,
    action: str,
    *,
    dispatch,
    resolve_runtime_id=lambda dataflow_id: None,
) -> Session:
    """Create a stream-scope recovery operation and dispatch its targeted command.

    Recovery is per-stream by design (decision: stream-scoped only): it names ONE
    ``device_id`` and does NOT take the session's dataflow-level ``command_in_flight``
    lock, nor change the session's status — the session stays ACTIVE throughout. The
    real guard is the durable operation's STREAM-scope conflict check, which serializes
    only same-stream (or dataflow-wide) work while allowing concurrent recovery of
    distinct streams.

    A fresh ``recovery_id`` is minted per call and rides both the operation and the
    command envelope, so every report the host emits during the episode is tagged
    with it (the id the ingest path keys incidents/gaps off).

    Raises:
        SessionNotFound   — no session with that id
        InvalidTransition — session is not ACTIVE, or was never started (no dataflow_id)
        CommandInFlight   — a conflicting recovery/lifecycle operation is already active
        ValueError        — action is not a known recovery intensity
    """
    if action not in RECOVER_ACTIONS:
        raise ValueError(
            f"unknown recovery action {action!r}; expected one of {sorted(RECOVER_ACTIONS)}"
        )

    session = get(session_id)
    if session.status not in _RECOVERABLE:
        raise InvalidTransition(session.status)
    dataflow_id = session.dataflow_id
    if not dataflow_id:
        raise InvalidTransition(session.status)

    watchdog_id = session.watchdog_id or uuid4().hex
    request_id = _request_id("recovering")
    recovery_id = uuid4().hex
    active_runtime_id = resolve_runtime_id(dataflow_id)

    try:
        operation = create_operation(
            session_id=session_id,
            dataflow_id=dataflow_id,
            command=action,
            request_key=request_id,
            target_device_id=device_id,
            request_id=request_id,
            watchdog_id=watchdog_id,
            recovery_id=recovery_id,
            runtime_id=active_runtime_id,
        )
    except OperationConflict as exc:
        raise CommandInFlight(
            session_id,
            code=exc.code,
            details=exc.details,
        ) from exc

    transition_operation(operation.operation_id, OperationState.CLAIMED)

    envelope = prepare_command(
        command=action,
        dataflow_id=dataflow_id,
        watchdog_id=watchdog_id,
        command_id=operation.command_id,
        recovery_id=recovery_id,
        target_device_id=device_id,
        runtime_id=active_runtime_id,
    )

    try:
        dispatch(session, envelope)
    except Exception as exc:
        transition_operation(
            operation.operation_id,
            OperationState.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
        raise

    transition_operation(operation.operation_id, OperationState.DISPATCHED)
    transition_operation(operation.operation_id, OperationState.SUCCEEDED)

    with transaction():
        session.command_id = envelope.correlation.command_id

    return session


def _request_id(action: str) -> str:
    request_id = get_contextvars().get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError(f"request_id must be bound before {action} a session")
    return request_id


def _device_config_ids(session: Session) -> list[int]:
    config_ids: list[int] = []
    seen: set[int] = set()
    for flow in session.device_flows or []:
        config_id = flow.get("device_config_id") if isinstance(flow, dict) else None
        if config_id is None:
            continue
        normalized = int(config_id)
        if normalized not in seen:
            config_ids.append(normalized)
            seen.add(normalized)
    return config_ids


def _claim_device_configs(session: Session, session_id: int, *, force: bool = False) -> list[int]:
    claimed: list[int] = []
    try:
        for config_id in _device_config_ids(session):
            device_configs.claim(config_id, session_id, force=force, starting=True)
            claimed.append(config_id)
    except Exception:
        _release_device_configs(claimed)
        raise
    return claimed


def _release_session_device_configs(session: Session) -> None:
    _release_device_configs(_device_config_ids(session))


def _release_device_configs(config_ids: list[int]) -> None:
    for config_id in reversed(config_ids):
        try:
            device_configs.release(config_id)
        except Exception as exc:
            _log.warning(
                "releasing device config claim failed — claim may be leaked "
                "(next session on this device will see DeviceConfigNotFree)",
                error=type(exc).__name__,
                message=str(exc),
            )
