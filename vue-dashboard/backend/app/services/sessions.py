"""Session services — pure business logic, no Flask imports.

Each function raises a typed domain exception (app.domain.errors) on failure.
The Flask adapter (app/api/sessions.py) and the CLI adapter (app/cli/)
translate those into their respective transports.

Note: prepare_command() reads request_id from structlog contextvars. Flask
wires this via request_logging middleware. CLI callers must bind it manually:
    from structlog.contextvars import bind_contextvars
    bind_contextvars(request_id=uuid4().hex)
"""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import structlog
from sqlalchemy.exc import IntegrityError
from structlog.contextvars import bound_contextvars, get_contextvars

from app.database import db, transaction
from app.domain.enums import OperationState, PolicyMode, SessionStatus
from app.domain.errors import (
    CommandInFlight,
    EmptySession,
    InvalidSessionEntry,
    InvalidTransition,
    RuntimeStartupFailed,
    SessionNotFound,
    SessionRunRequestConflict,
)
from app.models.backend_event import BackendEvent
from app.models.incident import Incident
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.models.recovery_gap import RecoveryGap
from app.models.runtime_manifest import RuntimeManifest
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.services import (
    device_configs,
    experiments,
    manifests,
    output_finalization,
    session_templates,
)
from app.services.device_list import build_pool_rows
from app.services.operations import (
    OperationConflict,
    create_operation,
    record_operation_failure_event,
    stamp_runtime_id,
    transition_operation,
)
from app.services.session_config import materialize_template_flows
from app.watchdog.commands import prepare_command, publish_command

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

# Safe to start: never run yet. One session = one run; repeat = new session.
_STARTABLE = {SessionStatus.PREPARING, SessionStatus.SCHEDULED}
_STOPPABLE = {SessionStatus.ACTIVE}
# Recovery only makes sense against a live dataflow.
_RECOVERABLE = {SessionStatus.ACTIVE}
# The three escalating recovery intensities; all are STREAM-scope commands.
RECOVER_ACTIONS = frozenset({"reconnect", "restart", "reset-stream"})


def create(
    data: dict,
    *,
    status: SessionStatus = SessionStatus.PREPARING,
    creation_request_key: str | None = None,
    creation_request_fingerprint: str | None = None,
    require_device_template_match: bool = False,
) -> Session:
    """Create an internal run row from one trusted registered template revision.

    Ordering matters and is the whole point of this function. The template is
    resolved and reread first, and its canonical content is frozen into the
    session's source snapshot BEFORE any run-specific assignment is applied —
    so the snapshot records what the template said, not what this run did with
    it. The effective ``policy``/``device_flows`` are materialized afterwards
    and stored separately; runtime start reads only those and never rereads the
    template.

    Nothing is claimed here. A device assignment and an output path are both
    validated for the operator's benefit and acquired only at start, so a run
    that is reviewed and abandoned leaves nothing held.
    """
    experiments.ensure_assignable(data.get("experiment_id"))

    # The HTTP schema already requires both, but the service is also called
    # directly (CLI, tests, other services), and those callers deserve the same
    # typed failure rather than a KeyError from three frames down.
    for required in ("source_template_id", "expected_template_hash"):
        if not data.get(required):
            raise InvalidSessionEntry(required, "is required; a session runs one template revision")

    resolution = session_templates.resolve_for_run(data["source_template_id"])
    template = resolution.template

    # Two independent proofs must agree before anything is inserted: the bytes
    # on disk still hash to the accepted revision (checked in resolve_for_run),
    # and they still hash to what the client was shown when it built this
    # request. A stale client hash means the operator reviewed a revision that
    # is no longer the one they are about to run.
    if resolution.content_hash != data.get("expected_template_hash"):
        raise session_templates.SessionTemplateStateConflict(
            f"Session template {template.name!r} changed since it was read; "
            "review the current revision before starting a run.",
            template.state,
            template.allowed_actions,
        )

    source_snapshot = {
        "canonical_hash_version": session_templates.CANONICAL_HASH_VERSION,
        "content": resolution.content,
    }
    device_flows = materialize_template_flows(
        resolution.content,
        data.get("assignments") or [],
        require_device_template_match=require_device_template_match,
    )

    return _repo.create({
        "name": data.get("name"),
        "experiment_id": data.get("experiment_id"),
        "notes": data.get("notes"),
        "schedule": data.get("schedule"),
        "policy": PolicyMode(resolution.content["policy"]),
        "device_flows": device_flows,
        "source_template_id": template.template_id,
        "source_template_name": template.name,
        "source_template_ref": template.reference,
        "source_template_hash": template.registered_hash,
        "source_template_snapshot": source_snapshot,
        "status": status,
        "creation_request_key": creation_request_key,
        "creation_request_fingerprint": creation_request_fingerprint,
    })


def _run_request_fingerprint(data: dict) -> str:
    content = {key: value for key, value in data.items() if key != "idempotency_key"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _create_idempotent_run_session(
    data: dict,
    *,
    status: SessionStatus,
    request_key: str,
    fingerprint: str,
    require_device_template_match: bool = False,
) -> tuple[Session, bool]:
    try:
        return (
            create(
                data,
                status=status,
                creation_request_key=request_key,
                creation_request_fingerprint=fingerprint,
                require_device_template_match=require_device_template_match,
            ),
            True,
        )
    except IntegrityError:
        # A concurrent request with the same global key may have won between
        # the lookup and insert. The transaction helper already rolled back.
        existing = _repo.get_by_creation_request_key(request_key)
        if existing is None:
            raise
        if existing.creation_request_fingerprint != fingerprint:
            raise SessionRunRequestConflict(request_key) from None
        return existing, False


def _scheduled_requirements(session: Session) -> list[dict]:
    requirements: list[dict] = []
    for flow_index, flow in enumerate(session.device_flows or []):
        config_id = int(flow["device_config_id"])
        config = device_configs.get_by_id(config_id)
        if config is None:
            # Materialization normally proves this, but keep the snapshot
            # builder safe when called directly or under a delete race.
            from app.domain.errors import DeviceConfigNotFound

            raise DeviceConfigNotFound(config_id)
        requirements.append({
            "flow_index": flow_index,
            "preferred_device_config_id": config_id,
            "required_device_type": str(config.device_type.value)
            if hasattr(config.device_type, "value")
            else str(config.device_type),
            "preferred_hardware_id": config.hardware_id,
            "preferred_parameters": dict(config.parameters or {}),
            "selected_device_config_id": None,
            "match": None,
        })
    return requirements


def _discard_provisional_session(session_id: int) -> None:
    """Remove a never-dispatched run and its provisional internal evidence.

    This is deliberately not the ordinary session delete path: it is valid only
    for the new atomic command before any dispatch attempt. Explicit child
    deletion keeps the existing non-cascading historical FKs intact elsewhere.
    """
    with transaction():
        db.session.execute(db.delete(RecoveryGap).where(RecoveryGap.session_id == session_id))
        db.session.execute(db.delete(BackendEvent).where(BackendEvent.session_id == session_id))
        db.session.execute(db.delete(OutputFile).where(OutputFile.session_id == session_id))
        db.session.execute(db.delete(Incident).where(Incident.session_id == session_id))
        db.session.execute(db.delete(Operation).where(Operation.session_id == session_id))
        db.session.execute(
            db.delete(RuntimeOwnership).where(RuntimeOwnership.session_id == session_id)
        )
        db.session.execute(
            db.delete(RuntimeManifest).where(RuntimeManifest.session_id == session_id)
        )
        row = db.session.get(Session, session_id)
        if row is not None:
            db.session.delete(row)


def create_run(data: dict, *, supervisor=None) -> Session:
    """Create one immediate or scheduled run as a single public command.

    The idempotency key is global to this command. An identical retry returns
    the original row; reusing the key with different input is a typed conflict.
    """
    request_key = str(data["idempotency_key"])
    fingerprint = _run_request_fingerprint(data)
    existing = _repo.get_by_creation_request_key(request_key)
    if existing is not None:
        if existing.creation_request_fingerprint != fingerprint:
            raise SessionRunRequestConflict(request_key)
        return existing

    execution = dict(data["execution"])
    create_data = {
        key: value
        for key, value in data.items()
        if key not in {"execution", "force", "idempotency_key", "schedule"}
    }
    if execution["mode"] == "scheduled":
        start_at = execution["start_at"]
        aware = start_at if start_at.tzinfo else start_at.replace(tzinfo=UTC)
        session, created = _create_idempotent_run_session(
            create_data,
            status=SessionStatus.SCHEDULED,
            request_key=request_key,
            fingerprint=fingerprint,
        )
        if not created:
            return session
        try:
            schedule = {
                "mode": "once",
                "start_at": aware.isoformat(),
                "fallback_policy": "closest_compatible",
                "requirements": _scheduled_requirements(session),
                "cancellation": None,
            }
            with transaction():
                session.schedule = schedule
                session.scheduled_for = aware
            return session
        except Exception:
            _repo.delete(session.id)
            raise

    session, created = _create_idempotent_run_session(
        create_data,
        status=SessionStatus.PREPARING,
        request_key=request_key,
        fingerprint=fingerprint,
        require_device_template_match=True,
    )
    if not created:
        return session
    if supervisor is None:
        _repo.delete(session.id)
        raise RuntimeStartupFailed(
            error_type="RuntimeSupervisorUnavailable",
            message="The managed runtime supervisor is unavailable.",
        )
    return start_managed(
        session.id,
        supervisor,
        force=bool(data.get("force", False)),
        discard_on_predispatch_failure=True,
    )


def _candidate_rank(row: dict, requirement: dict) -> tuple:
    config = device_configs.get_by_id(int(row["id"]))
    preferred = requirement.get("preferred_parameters") or {}
    parameters = dict(config.parameters or {}) if config is not None else {}
    equal_parameters = sum(
        1 for key, value in preferred.items() if parameters.get(key) == value
    )
    return (
        -equal_parameters,
        str(row.get("hardware_id") or ""),
        str(row.get("port") or ""),
        int(row["id"]),
    )


def _resolve_scheduled_assignments(
    requirements: list[dict],
    pool: list[dict],
) -> tuple[list[dict], list[int]]:
    available = [
        row
        for row in pool
        if isinstance(row.get("id"), int)
        and row.get("status") == "free"
        and row.get("availability") == "available"
    ]
    used: set[int] = set()
    selected: list[dict] = []
    unresolved: list[int] = []
    for requirement in sorted(requirements, key=lambda item: int(item["flow_index"])):
        flow_index = int(requirement["flow_index"])
        required_type = requirement.get("required_device_type")
        compatible = [
            row
            for row in available
            if int(row["id"]) not in used and row.get("type") == required_type
        ]
        preferred_id = int(requirement["preferred_device_config_id"])
        exact = next((row for row in compatible if int(row["id"]) == preferred_id), None)
        chosen = exact
        match = "exact"
        if chosen is None and compatible:
            chosen = sorted(compatible, key=lambda row: _candidate_rank(row, requirement))[0]
            match = "closest_compatible"
        if chosen is None:
            unresolved.append(flow_index)
            continue
        selected_id = int(chosen["id"])
        used.add(selected_id)
        selected.append({
            "flow_index": flow_index,
            "device_config_id": selected_id,
            "match": match,
        })
    return selected, unresolved


def execute_scheduled(
    session_id: int,
    *,
    supervisor,
    discovery_service,
) -> Session:
    """Resolve current hardware for one leased due schedule and start it."""
    session = get(session_id)
    if session.status is not SessionStatus.SCHEDULED:
        raise InvalidTransition(session.status)
    schedule = dict(session.schedule or {})
    requirements = list(schedule.get("requirements") or [])
    pool = build_pool_rows(discovery_service.scan().devices)
    selected, unresolved = _resolve_scheduled_assignments(
        requirements,
        pool,
    )
    if unresolved:
        now = datetime.now(UTC)
        details = {
            "code": "no_compatible_device",
            "detail": "No compatible free and available device remained at start time.",
            "unresolved_flows": unresolved,
            "cancelled_at": now.isoformat(),
        }
        schedule["cancellation"] = details
        with transaction():
            session.status = SessionStatus.CANCELLED
            session.cancellation_details = details
            session.cancelled_at = now
            session.schedule = schedule
            session.schedule_claim_token = None
            session.schedule_claim_expires_at = None
        return session

    selected_by_flow = {item["flow_index"]: item for item in selected}
    flows = [dict(flow) for flow in (session.device_flows or [])]
    resolved_requirements: list[dict] = []
    for requirement in requirements:
        result = selected_by_flow[int(requirement["flow_index"])]
        flows[int(requirement["flow_index"])] = (
            flows[int(requirement["flow_index"])]
            | {"device_config_id": result["device_config_id"]}
        )
        resolved_requirements.append(
            requirement
            | {
                "selected_device_config_id": result["device_config_id"],
                "match": result["match"],
            }
        )
    schedule["requirements"] = resolved_requirements
    with transaction():
        session.device_flows = flows
        session.schedule = schedule
        session.schedule_claim_token = None
        session.schedule_claim_expires_at = None
    with bound_contextvars(request_id=f"scheduled-{session_id}-{uuid4().hex}"):
        return start_managed(session_id, supervisor)


def execute_due_scheduled(
    *,
    supervisor,
    discovery_service,
    now: datetime | None = None,
) -> list[Session]:
    """Lease and execute every due schedule once for this coordinator pass."""
    current = now or datetime.now(UTC)
    results: list[Session] = []
    for due in _repo.due_scheduled(current):
        token = uuid4().hex
        if not _repo.try_claim_schedule(
            due.id,
            token=token,
            now=current,
            expires_at=current + timedelta(minutes=2),
        ):
            continue
        try:
            results.append(
                execute_scheduled(
                    due.id,
                    supervisor=supervisor,
                    discovery_service=discovery_service,
                )
            )
        except Exception:
            _repo.release_schedule_claim(due.id, token)
            _log.exception("scheduled run execution failed", session_id=due.id)
    return results


def get(session_id: int) -> Session:
    session = _repo.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)
    return session


def get_by_name(name: str) -> Session | None:
    return _repo.get_by_name(name)


def suggest_name(source_template_id: str) -> str:
    """The name create() would mint for an unlabeled run of one template.

    This is a preview, not a reservation, so a concurrent create can make it
    stale. The repository recomputes the authoritative name during create().
    """
    template = session_templates.get_by_id(source_template_id)
    if template is None:
        raise session_templates.SessionTemplateNotFound(source_template_id)
    return _repo.next_template_session_name(source_template_id, template.name)


def list_all() -> list[Session]:
    return _repo.public_all()


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


def start_managed(
    session_id: int,
    supervisor,
    *,
    force: bool = False,
    discard_on_predispatch_failure: bool = False,
) -> Session:
    """Start a session through a per-dataflow runtime host managed by the daemon.
    """
    session = get(session_id)
    if session.command_in_flight:
        raise CommandInFlight(session_id)
    if session.status not in _STARTABLE:
        raise InvalidTransition(session.status)
    if not session.device_flows:
        raise EmptySession(session_id)

    original_status = session.status
    # One generation per session, minted on first start and never replaced.
    dataflow_id = session.dataflow_id or uuid4().hex
    watchdog_id = session.watchdog_id or uuid4().hex
    request_id = _request_id("starting")
    _log.info("session_start_predispatch")
    try:
        manifest = manifests.resolve(session_id, dataflow_id=dataflow_id)
    except Exception:
        if discard_on_predispatch_failure:
            _discard_provisional_session(session_id)
        _clear_pending_start_identity(session)
        raise

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
        if discard_on_predispatch_failure:
            _discard_provisional_session(session_id)
        _clear_pending_start_identity(session)
        raise CommandInFlight(
            session_id,
            code=exc.code,
            details=exc.details,
        ) from exc

    transition_operation(operation.operation_id, OperationState.CLAIMED)

    claimed_config_ids: list[int] = []
    spawn_attempted = False
    dispatch_attempted = False
    envelope = None
    try:
        claimed_config_ids = _claim_device_configs(session, session_id, force=force)
        with transaction():
            if not _repo.try_acquire_in_flight_lock(session_id):
                raise CommandInFlight(session_id)
            session.command_in_flight = True
            session.command_id = operation.command_id

        session._pending_dataflow_id = dataflow_id
        session._pending_request_id = request_id
        spawn_attempted = True
        supervisor.spawn(session, manifest=manifest)
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
            publish=False,
        )
        dispatch_attempted = True
        supervisor.dispatch(session, envelope)
    except Exception as exc:
        teardown_proven = not spawn_attempted
        if spawn_attempted:
            try:
                supervisor.stop(session)
                teardown_proven = True
            except Exception as stop_exc:
                _log.warning(
                    "start rollback: stopping the just-spawned host failed — "
                    "a zombie runtime host may be left running",
                    request_id=request_id,
                    error=type(stop_exc).__name__,
                    message=str(stop_exc),
                )
                # A spawn that failed before recording any identity has no
                # child for stop() to find; absence of both durable and local
                # identity is positive proof that there is nothing to retain.
                teardown_proven = (
                    session.runtime_port is None
                    and _runtimes.active_for_dataflow(dataflow_id) is None
                )
        if not dispatch_attempted or teardown_proven:
            _release_device_configs(claimed_config_ids)
        if (
            discard_on_predispatch_failure
            and not dispatch_attempted
            and teardown_proven
        ):
            _discard_provisional_session(session_id)
            _clear_pending_start_identity(session)
            raise
        publish_for_reconciliation = dispatch_attempted or (
            spawn_attempted and not teardown_proven
        )
        with transaction():
            session.command_in_flight = False
            if publish_for_reconciliation:
                session.dataflow_id = dataflow_id
                session.watchdog_id = watchdog_id
            if discard_on_predispatch_failure and dispatch_attempted:
                # Never expose a repairable pre-run record. A dispatch error is ambiguous with
                # respect to command acceptance; proven teardown makes the run
                # stopped, while unproven teardown remains a STARTING recovery
                # case with its claims and runtime identity intact.
                session.status = (
                    SessionStatus.STOPPED if teardown_proven else SessionStatus.STARTING
                )
            elif publish_for_reconciliation and not teardown_proven:
                session.status = SessionStatus.STARTING
            else:
                session.status = original_status
            if teardown_proven:
                session.runtime_port = None
                session.runtime_token = None
        if publish_for_reconciliation and envelope is not None:
            publish_command(envelope)
        _clear_pending_start_identity(session)
        terminal_state = (
            OperationState.UNCERTAIN
            if discard_on_predispatch_failure and dispatch_attempted
            else OperationState.FAILED
        )
        failed_operation = transition_operation(
            operation.operation_id,
            terminal_state,
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

    with transaction():
        session.dataflow_id = dataflow_id
        session.watchdog_id = watchdog_id
        session.status = SessionStatus.STARTING
    _clear_pending_start_identity(session)
    publish_command(envelope)
    transition_operation(operation.operation_id, OperationState.DISPATCHED)
    transition_operation(operation.operation_id, OperationState.SUCCEEDED)

    for config_id in claimed_config_ids:
        device_configs.activate(config_id, session_id)

    with transaction():
        session.command_in_flight = False
        session.status = SessionStatus.ACTIVE

    return session


def _clear_pending_start_identity(session: Session) -> None:
    for name in ("_pending_dataflow_id", "_pending_request_id"):
        if hasattr(session, name):
            delattr(session, name)


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
    resolve_runtime_id,
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
