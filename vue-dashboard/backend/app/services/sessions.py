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
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import structlog
from sqlalchemy.exc import IntegrityError
from structlog.contextvars import bound_contextvars, get_contextvars

from app.config import get_config
from app.control.event_poller import telemetry_freshness
from app.control.orphan_teardown import AdministrativeStopEvidence, ownership_teardown_confirmed
from app.database import db, transaction
from app.domain.duration import validate_duration_seconds
from app.domain.enums import OperationState, PolicyMode, SessionStatus, RuntimeOwnershipState, WatchdogProcessState
from app.domain.errors import (
    CommandInFlight,
    EmptySession,
    InvalidSessionEntry,
    InvalidTransition,
    RecoveryCommandNotAllowed,
    RuntimeStartupFailed,
    SessionNotFound,
    SessionRunRequestConflict,
    StopProofMissing,
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
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from app.services import (
    device_configs,
    device_templates,
    experiments,
    incidents,
    manifests,
    output_finalization,
    session_activity,
    session_templates,
    recovery_contract,
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
_events = BackendEventRepository()


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
_STOPPABLE = {SessionStatus.STARTING, SessionStatus.ACTIVE}
# Recovery only makes sense against a live dataflow.
_RECOVERABLE = {SessionStatus.ACTIVE}
# The runtime currently implements one honest, stream-scoped operation.
RECOVER_ACTIONS = frozenset({"restart"})


def _recovery_command_view(session: Session, device_id: str) -> dict[str, object]:
    """Resolve command eligibility from current direct watchdog telemetry."""
    latest = _events.latest_direct_telemetry_for_session(session.id)
    config = get_config()
    freshness = telemetry_freshness(
        latest,
        now=datetime.now(UTC),
        stale_after_seconds=config.WATCHDOG_TELEMETRY_STALE_AFTER_SECONDS,
        overflow_after_seconds=config.WATCHDOG_TELEMETRY_OVERFLOW_AFTER_SECONDS,
    )
    ownership = (
        _runtimes.active_for_dataflow(session.dataflow_id)
        if session.dataflow_id
        else None
    )
    controls_current = bool(
        freshness == "current"
        and ownership is not None
        and latest is not None
        and latest.runtime_id == ownership.runtime_id
        and latest.watchdog_id == ownership.watchdog_id
        and ownership.watchdog_state is not None
        and ownership.watchdog_state.value == "running"
        and ownership.watchdog_control_port is not None
    )

    payload = latest.payload if latest is not None and isinstance(latest.payload, Mapping) else {}
    diagnostics = payload.get("diagnostics")
    streams = diagnostics.get("streams") if isinstance(diagnostics, Mapping) else []
    diagnostic = next(
        (
            stream
            for stream in streams or []
            if isinstance(stream, Mapping) and stream.get("device_id") == device_id
        ),
        {},
    )
    recovery = diagnostic.get("recovery") if isinstance(diagnostic, Mapping) else {}
    recovery = recovery if isinstance(recovery, Mapping) else {}
    source_read = diagnostic.get("source_read") if isinstance(diagnostic, Mapping) else {}
    source_read = source_read if isinstance(source_read, Mapping) else {}
    return recovery_contract.project(
        action=diagnostic.get("action") if isinstance(diagnostic, Mapping) else None,
        stage=recovery.get("status"),
        source_read_state=source_read.get("state"),
        policy=recovery.get("policy") or session.policy,
        hardware_present=recovery.get("hardware_present"),
        controls_current=controls_current,
        failure_reason=diagnostic.get("initiating_failure_reason"),
    )


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
        "duration_seconds": data.get("duration_seconds"),
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
    snapshot = (
        session.source_template_snapshot
        if isinstance(session.source_template_snapshot, Mapping)
        else {}
    )
    snapshot_content = snapshot.get("content")
    snapshot_flows = (
        snapshot_content.get("device_flows")
        if isinstance(snapshot_content, Mapping)
        else []
    ) or []
    for flow_index, flow in enumerate(session.device_flows or []):
        config_id = int(flow["device_config_id"])
        config = device_configs.get_by_id(config_id)
        if config is None:
            # Materialization normally proves this, but keep the snapshot
            # builder safe when called directly or under a delete race.
            from app.domain.errors import DeviceConfigNotFound

            raise DeviceConfigNotFound(config_id)
        device_type = (
            str(config.device_type.value)
            if hasattr(config.device_type, "value")
            else str(config.device_type)
        )
        preferred_parameters = dict(config.parameters or {})
        snapshot_flow = (
            snapshot_flows[flow_index]
            if flow_index < len(snapshot_flows)
            and isinstance(snapshot_flows[flow_index], Mapping)
            else {}
        )
        template_path = snapshot_flow.get("device_template_path")
        required_template = (
            device_templates.get_by_path(template_path)
            if isinstance(template_path, str) and template_path
            else None
        )
        if required_template is None:
            raise InvalidSessionEntry(
                f"device_flows[{flow_index}].device_template_path",
                "scheduled runs need the referenced device template to snapshot its settings",
            )
        required_parameters = dict(required_template.content.get("parameters") or {})
        required_hash = snapshot_flow.get("device_template_content_hash")
        if not isinstance(required_hash, str):
            required_hash = device_templates.content_hash(
                {"type": device_type, "parameters": required_parameters}
            )
        requirements.append(
            {
                "flow_index": flow_index,
                "preferred_device_config_id": config_id,
                "required_device_type": device_type,
                "required_device_template_path": required_template.file_path,
                "required_configuration_hash": required_hash,
                "required_parameters": required_parameters,
                "preferred_hardware_id": config.hardware_id,
                "preferred_parameters": preferred_parameters,
                "selected_device_config_id": None,
                "match": None,
            }
        )
    return requirements


def _discard_provisional_session(session_id: int) -> None:
    """Remove a never-dispatched run and its provisional internal evidence.

    This is deliberately not the ordinary session delete path: it is valid only
    for the new atomic command before any dispatch attempt. Explicit child
    deletion keeps the existing non-cascading historical FKs intact elsewhere.
    """
    row = db.session.get(Session, session_id)
    if row is not None and row.creation_request_key:
        # Keep the public idempotency tombstone even if no process launched.
        # Retrying cannot produce another run/window under the same key.
        with transaction():
            row.status = SessionStatus.COMPLETED
            row.command_in_flight = False
        return
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
    execution = dict(data["execution"])
    if "duration_seconds" in execution:
        try:
            validate_duration_seconds(execution["duration_seconds"])
        except ValueError as exc:
            raise InvalidSessionEntry("duration_seconds", str(exc)) from exc
        if execution.get("mode") != "immediate":
            raise InvalidSessionEntry("duration_seconds", "is only supported for immediate runs")
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
    create_data["duration_seconds"] = execution.get("duration_seconds")
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
        _discard_provisional_session(session.id)
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


def _required_scheduled_parameters(requirement: Mapping) -> dict:
    required = requirement.get("required_parameters")
    if isinstance(required, Mapping):
        return dict(required)
    preferred = requirement.get("preferred_parameters")
    return dict(preferred) if isinstance(preferred, Mapping) else {}


def _candidate_rank(row: dict, requirement: dict) -> tuple:
    config = device_configs.get_by_id(int(row["id"]))
    preferred = _required_scheduled_parameters(requirement)
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
        required_hash = requirement.get("required_configuration_hash")
        if not required_hash:
            required_hash = device_templates.content_hash(
                {
                    "type": required_type,
                    "parameters": _required_scheduled_parameters(requirement),
                }
            )
        compatible = [
            row
            for row in available
            if int(row["id"]) not in used
            and row.get("type") == required_type
        ]
        preferred_id = int(requirement["preferred_device_config_id"])
        exact = next((row for row in compatible if int(row["id"]) == preferred_id), None)
        chosen = exact
        if chosen is not None:
            reconfigure = chosen.get("configuration_hash") != required_hash
            match = "preferred_reconfigured" if reconfigure else "exact"
        else:
            matching = [
                row for row in compatible if row.get("configuration_hash") == required_hash
            ]
            candidates = matching or compatible
            chosen = (
                sorted(candidates, key=lambda row: _candidate_rank(row, requirement))[0]
                if candidates
                else None
            )
            reconfigure = bool(chosen and chosen.get("configuration_hash") != required_hash)
            match = "closest_compatible_reconfigured" if reconfigure else "configuration_match"
        if chosen is None:
            unresolved.append(flow_index)
            continue
        selected_id = int(chosen["id"])
        used.add(selected_id)
        selected.append({
            "flow_index": flow_index,
            "device_config_id": selected_id,
            "match": match,
            "reconfigure": reconfigure,
        })
    return selected, unresolved


def _apply_scheduled_configuration(requirement: Mapping, result: Mapping) -> None:
    """Bring one selected free fallback to the frozen scheduled settings."""
    if not result.get("reconfigure"):
        return
    required_parameters = _required_scheduled_parameters(requirement)
    required_hash = requirement.get("required_configuration_hash")
    template_path = requirement.get("required_device_template_path")
    source_template = None
    if isinstance(template_path, str) and template_path:
        current_template = device_templates.get_by_path(template_path)
        if current_template is not None and current_template.content_hash == required_hash:
            source_template = current_template.file_path
    device_configs.edit(
        int(result["device_config_id"]),
        parameters=required_parameters,
        update_source_template=False,
        source_template=source_template,
    )


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
    for requirement in requirements:
        result = selected_by_flow[int(requirement["flow_index"])]
        _apply_scheduled_configuration(requirement, result)

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
            reserved = db.session.execute(db.update(Session).where(
                Session.id == session_id, Session.status.in_(_STARTABLE),
                Session.command_in_flight.is_(False),
            ).values(command_in_flight=True, command_id=operation.command_id,
                     dataflow_id=dataflow_id, watchdog_id=watchdog_id,
                     status=SessionStatus.STARTING))
            if reserved.rowcount != 1:
                raise CommandInFlight(session_id)

        session._pending_dataflow_id = dataflow_id
        session._pending_request_id = request_id
        spawn_attempted = True
        supervisor.spawn(session, manifest=manifest)
        db.session.refresh(session)
        if session.status in {SessionStatus.STOPPING, SessionStatus.COMPLETED}:
            # Stop arrived while hardware was opening. Use its original command
            # identity and never dispatch a new start after cancellation.
            if session.status == SessionStatus.STOPPING:
                with transaction():
                    session.command_in_flight = False
                pending_stop = _stop_operation(session)
                stop_envelope = prepare_command(command="stop", dataflow_id=dataflow_id,
                    watchdog_id=_active_watchdog_id(dataflow_id) or watchdog_id,
                    command_id=pending_stop.command_id, runtime_id=_active_runtime_id(dataflow_id))
                owners = _runtimes.list_for_session(session.id)
                owner = _runtimes.unresolved_for_dataflow(dataflow_id) or (owners[0] if owners else None)
                result = supervisor.stop(session, envelope=stop_envelope)
                if result is None:
                    raise StopProofMissing(dataflow_id, runtime_id=owner.runtime_id if owner else None)
                apply_shutdown_result(session, result, owner)
            with transaction():
                operation.state = OperationState.FAILED
                operation.error_code = "start_cancelled"
                operation.error_message = "Start was cancelled by user Stop."
                session.command_in_flight = False
            _clear_pending_start_identity(session)
            return session
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
                owners = _runtimes.list_for_session(session.id)
                owner = _runtimes.unresolved_for_dataflow(dataflow_id) or (owners[0] if owners else None)
                shutdown_result = supervisor.stop(session)
                if shutdown_result is None:
                    raise StopProofMissing(dataflow_id, runtime_id=owner.runtime_id if owner else None)
                apply_shutdown_result(session, shutdown_result, owner)
                teardown_proven = session.status == SessionStatus.COMPLETED
            except Exception as stop_exc:
                _log.warning(
                    "start rollback: stopping the just-spawned host failed — "
                    "a zombie runtime host may be left running",
                    request_id=request_id,
                    error=type(stop_exc).__name__,
                    message=str(stop_exc),
                )
                # Missing identity is not proof that a child never launched.
                owners = _runtimes.list_for_session(session.id)
                teardown_proven = bool(owners) and all(
                    (owner.details or {}).get("host_launch_failed") is True
                    and not owner.watchdog_id for owner in owners
                )
        db.session.refresh(session)
        cancellation_committed = session.status in {SessionStatus.STOPPING, SessionStatus.COMPLETED}
        if teardown_proven:
            _release_device_configs(claimed_config_ids, session_id=session.id)
        if (
            discard_on_predispatch_failure
            and not dispatch_attempted
            and teardown_proven
            and not cancellation_committed
        ):
            _discard_provisional_session(session_id)
            _clear_pending_start_identity(session)
            raise
        publish_for_reconciliation = dispatch_attempted or (
            spawn_attempted and not teardown_proven
        )
        with transaction():
            rollback_values = {"command_in_flight": False}
            if publish_for_reconciliation:
                rollback_values.update(dataflow_id=dataflow_id, watchdog_id=watchdog_id)
            if discard_on_predispatch_failure and dispatch_attempted:
                # Never expose a repairable pre-run record. A dispatch error is ambiguous with
                # respect to command acceptance; proven teardown makes the run
                # completed, while unproven teardown remains a STARTING recovery
                # case with its claims and runtime identity intact.
                rollback_status = (
                    SessionStatus.COMPLETED if teardown_proven else SessionStatus.STOPPING
                )
            elif publish_for_reconciliation and not teardown_proven:
                rollback_status = SessionStatus.STOPPING
            else:
                rollback_status = original_status
            if teardown_proven:
                rollback_values.update(runtime_port=None, runtime_token=None)
            db.session.execute(db.update(Session).where(Session.id == session_id)
                .values(**rollback_values))
            # A Stop can commit after the refresh above. Preserve cancellation
            # at the actual database write, not merely in this ORM snapshot.
            db.session.execute(db.update(Session).where(
                Session.id == session_id,
                Session.status.not_in([SessionStatus.STOPPING, SessionStatus.COMPLETED,
                                       SessionStatus.CANCELLED]),
            ).values(status=rollback_status))
        db.session.refresh(session)
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

    db.session.refresh(session)
    with transaction():
        session.dataflow_id = dataflow_id
        session.watchdog_id = watchdog_id
        if session.status in _STARTABLE:
            session.status = SessionStatus.STARTING
    _clear_pending_start_identity(session)
    publish_command(envelope)
    transition_operation(operation.operation_id, OperationState.DISPATCHED)
    transition_operation(operation.operation_id, OperationState.SUCCEEDED)

    db.session.refresh(session)
    if session.status in {SessionStatus.STOPPING, SessionStatus.COMPLETED}:
        with transaction():
            session.command_in_flight = False
        return session
    for config_id in claimed_config_ids:
        device_configs.activate(config_id, session_id)

    with transaction():
        session.command_in_flight = False

    return session


def _clear_pending_start_identity(session: Session) -> None:
    for name in ("_pending_dataflow_id", "_pending_request_id"):
        if hasattr(session, name):
            delattr(session, name)


def _stop_operation(session: Session, *, command_id=None, requested_at=None) -> Operation:
    """One logical shutdown per dataflow, shared by manual and autonomous stops."""
    existing = db.session.scalars(db.select(Operation).where(
        Operation.session_id == session.id, Operation.command == "stop"
    ).order_by(Operation.id.asc())).first()
    if existing is not None:
        return existing
    dataflow_id = session.dataflow_id or f"unstarted-{session.id}"
    try:
        operation = create_operation(
            session_id=session.id, dataflow_id=dataflow_id, command="stop",
            request_key=f"stop:{dataflow_id}", command_id=command_id,
            runtime_id=_active_runtime_id(dataflow_id),
            watchdog_id=_active_watchdog_id(dataflow_id),
            details={"requested_reason": "user_stop"} if command_id is None else {},
        )
    except OperationConflict:
        # Simultaneous user/expiry requests may both observe no operation.
        # The unique key elects one; all losing requests join that shutdown.
        operation = db.session.scalars(db.select(Operation).where(
            Operation.session_id == session.id, Operation.command == "stop"
        ).order_by(Operation.id.asc())).first()
        if operation is None:
            raise
        return operation
    if requested_at is not None:
        with transaction():
            operation.queued_at = requested_at
    return operation


def apply_shutdown_result(
    session: Session,
    result: Mapping | AdministrativeStopEvidence | None,
    ownership: RuntimeOwnership | None,
    *,
    stop_reason: str = "user_stop",
) -> Session:
    """Consume a supervisor result without inventing a second completion policy.

    Administrative evidence has already been projected under the hardware lease.
    Validate that persisted proof, but do not project it again after lease release.
    Reconciliation explicitly calls apply_administrative_stop_evidence to replay
    historical proof when another producer's teardown changes the all-owner gate.
    """
    if isinstance(result, AdministrativeStopEvidence):
        expected = asdict(result)
        if ownership is None or ownership.session_id != session.id or any(
            getattr(ownership, key) != getattr(result, key)
            for key in ("runtime_id", "watchdog_id", "dataflow_id", "manifest_hash")
        ):
            raise StopProofMissing(session.dataflow_id, runtime_id=result.runtime_id)
        details = ownership.details or {}
        persisted = details.get("administrative_stop_evidence")
        historical = (details.get("historical_administrative_stop_evidence") or {}).get(result.watchdog_id)
        if expected not in (persisted, historical):
            raise StopProofMissing(session.dataflow_id, runtime_id=result.runtime_id)
        return get(session.id)
    if result is None:
        # A missing receipt is compatible only with an untracked legacy driver.
        # Cleared ports or a historical STOPPED row do not erase producer history.
        if (session.duration_seconds is not None or session.runtime_port is not None
                or ownership is not None or _runtimes.list_for_session(session.id)):
            raise StopProofMissing(session.dataflow_id,
                                   runtime_id=ownership.runtime_id if ownership else None)
        return _complete_legacy_stop(session, stop_reason=stop_reason)
    if not isinstance(result, Mapping) or ownership is None or ownership.session_id != session.id:
        raise StopProofMissing(session.dataflow_id,
                               runtime_id=ownership.runtime_id if ownership else None)
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
    from app.services.event_ingest import ingest_watchdog_report
    payload = dict(result)
    command_id = payload.get("command_id")
    if not command_id:
        raise ValueError("shutdown receipt is missing command identity")
    receipt_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report_id = sha256(f"{ownership.runtime_id}:{ownership.watchdog_id}:{command_id}:stop-result:{receipt_hash}".encode()).hexdigest()
    ingest_watchdog_report(WatchdogTelemetryEnvelope(
        report_id=report_id, dataflow_id=ownership.dataflow_id,
        runtime_id=ownership.runtime_id, watchdog_id=ownership.watchdog_id,
        manifest_hash=ownership.manifest_hash, event_type="runtime.stop_finished", payload=payload,
    ).to_dict())
    return get(session.id)


def replay_shutdown_result(session: Session, ownership: RuntimeOwnership) -> Session:
    """Reconsider durable proof after another producer's teardown changes the gate."""
    record = (ownership.details or {}).get("administrative_stop_evidence")
    receipt = ownership.watchdog_exit_details or {}
    if (isinstance(record, Mapping) and isinstance(record.get("payload"), Mapping)
            and record.get("runtime_id") == ownership.runtime_id
            and record.get("watchdog_id") == ownership.watchdog_id):
        return apply_administrative_stop_evidence(
            session, AdministrativeStopEvidence(**record), ownership,
        )
    if receipt.get("teardown_confirmed") is True and ownership.watchdog_id:
        return apply_shutdown_result(session, receipt, ownership)
    return session


def _complete_legacy_stop(session: Session, *, stop_reason: str) -> Session:
    """Complete the explicitly qualified, untracked synchronous driver path."""
    operation = _stop_operation(session)
    _schedule_stop_finalization(session, completion_cause=stop_reason)
    _release_session_device_configs(session)
    with transaction():
        operation.state = OperationState.SUCCEEDED
        operation.finished_at = datetime.now(UTC)
        operation.details = dict(operation.details or {}) | {
            "stop_reason": stop_reason, "requested_at": datetime.now(UTC).isoformat(),
            "legacy_synchronous_stop": True,
        }
        session.command_in_flight = False
        session.status = SessionStatus.COMPLETED
        session.runtime_port = None
        session.runtime_token = None
    _resolve_stop_supervision_incidents(session, session.dataflow_id or f"unstarted-{session.id}")
    return session


def _complete_stop_operation(operation: Operation, details: dict) -> None:
    """Stopping succeeds when teardown is proven; recording concerns are warnings.

    The caller owns the transaction and verifies the current producer identity.
    Raw receipts and output-integrity evidence are retained independently.
    """
    if details.get("teardown_confirmed") is not True:
        raise ValueError("stop completion requires confirmed teardown")
    details = dict(details)
    if operation.error_code or operation.error_message:
        details.setdefault("previous_stop_error", {
            "code": operation.error_code, "message": operation.error_message,
        })
    warnings = [warning for warning in details.get("warnings", [])
                if warning.get("code") != "unclean_shutdown"]
    if details.get("output_integrity_confirmed") is not True:
        warnings.append({
            "code": "unclean_shutdown",
            "message": "Session stopped, but recording integrity could not be confirmed. Review the recording diagnostics.",
        })
    details["warnings"] = warnings
    operation.details = details
    operation.state = OperationState.SUCCEEDED
    operation.finished_at = operation.finished_at or datetime.now(UTC)
    operation.error_code = None
    operation.error_message = None
    if not details.get("completion_activity_id"):
        activity = session_activity.record(
            session_id=operation.session_id, dataflow_id=operation.dataflow_id,
            kind="operation.completed", category="session",
            severity="warning" if warnings else "success",
            title="Stop completed with warnings" if warnings else "Stop completed",
            summary="; ".join(warning["message"] for warning in warnings) if warnings else "The session stopped.",
            source_type="operation", source_id=operation.operation_id,
            operation_id=operation.operation_id, command_id=operation.command_id,
            details={"command": "stop", "warnings": warnings},
            occurred_at=operation.finished_at, commit=False,
        )
        operation.details = {**details, "completion_activity_id": activity.activity_id}


def reconcile_completed_stop_operations(*, session_ids: tuple[int, ...] | None = None) -> int:
    """Upgrade old failed-stop projections without changing shutdown evidence."""
    repaired = []
    with transaction():
        query = db.select(Operation).join(
            Session, Session.id == Operation.session_id,
        ).where(
            Operation.command == "stop",
            Operation.state.in_((OperationState.FAILED, OperationState.UNCERTAIN, OperationState.SUCCEEDED)),
            Session.status == SessionStatus.COMPLETED,
            Operation.dataflow_id == Session.dataflow_id,
        )
        if session_ids is not None:
            query = query.where(Operation.session_id.in_(session_ids))
        operations = db.session.scalars(query).all()
        for operation in operations:
            details = dict(operation.details or {})
            if (details.get("teardown_confirmed") is True
                    and (operation.state != OperationState.SUCCEEDED
                         or not details.get("completion_activity_id"))):
                _complete_stop_operation(operation, details)
                repaired.append(operation)
    for operation in repaired:
        incidents.evaluate_operation_success(operation)
    return len(repaired)


def apply_administrative_stop_evidence(
    session: Session, evidence: AdministrativeStopEvidence, ownership: RuntimeOwnership,
) -> Session:
    """Project independently proven process teardown without inventing a receipt.

    Administrative cleanup cannot certify output integrity. The original watchdog
    receipt and its failures remain intact, even when cleanup repairs projection.
    """
    payload = dict(evidence.payload)
    if (evidence.runtime_id != ownership.runtime_id
            or evidence.dataflow_id != ownership.dataflow_id
            or evidence.manifest_hash != ownership.manifest_hash
            or ownership.session_id != session.id
            or payload.get("teardown_confirmed") is not True
            or payload.get("output_integrity_confirmed") is not False):
        raise ValueError("administrative teardown evidence identity or proof mismatch")
    for key in ("command_id", "stop_reason", "requested_at"):
        if not payload.get(key):
            raise ValueError(f"administrative teardown evidence missing {key}")
    record = {"runtime_id": evidence.runtime_id, "watchdog_id": evidence.watchdog_id,
              "dataflow_id": evidence.dataflow_id, "manifest_hash": evidence.manifest_hash,
              "payload": payload, "observations": dict(evidence.observations)}
    operation = _stop_operation(session, command_id=payload["command_id"])
    current = False
    with transaction():
        # Serialize the projection and claim release against session mutations.
        db.session.execute(db.update(Session).where(Session.id == session.id)
                           .values(command_in_flight=Session.command_in_flight))
        db.session.refresh(session)
        db.session.refresh(ownership)
        db.session.refresh(operation)
        owners = _runtimes.list_for_session(session.id)
        exact_owner = (ownership.watchdog_id == evidence.watchdog_id
                       and ownership.manifest_hash == evidence.manifest_hash
                       and ownership.dataflow_id == evidence.dataflow_id
                       and ownership.session_id == session.id)
        current = bool(owners and owners[0].runtime_id == evidence.runtime_id
                       and exact_owner
                       and session.dataflow_id == evidence.dataflow_id
                       and all(owner.runtime_id == evidence.runtime_id
                               or ownership_teardown_confirmed(owner) for owner in owners))
        owner_details = dict(ownership.details or {})
        details = dict(operation.details or {})
        if not current:
            history = dict(details.get("historical_administrative_stop_evidence") or {})
            history[f"{evidence.runtime_id}:{evidence.watchdog_id}"] = record
            details["historical_administrative_stop_evidence"] = history
            operation.details = details
            owner_history = dict(owner_details.get("historical_administrative_stop_evidence") or {})
            owner_history[evidence.watchdog_id] = record
            ownership.details = {**owner_details, "historical_administrative_stop_evidence": owner_history}
            if exact_owner:
                # Proof retires this exact producer even when a different
                # unproven owner prevents session-wide terminal projection.
                ownership.details = {**ownership.details, "administrative_stop_evidence": record}
                ownership.state = RuntimeOwnershipState.STOPPED
                ownership.stopped_at = ownership.stopped_at or datetime.now(UTC)
                ownership.watchdog_state = WatchdogProcessState.STOPPED
            return session
        owner_details["administrative_stop_evidence"] = record
        ownership.details = owner_details
        details["administrative_stop_evidence"] = record
        details.setdefault("stop_reason", payload["stop_reason"])
        details.setdefault("requested_at", payload["requested_at"])
        details.setdefault("shutdown_command_id", payload["command_id"])
        details["teardown_confirmed"] = True
        details["output_integrity_confirmed"] = False
        ownership.state = RuntimeOwnershipState.STOPPED
        ownership.stopped_at = ownership.stopped_at or datetime.now(UTC)
        ownership.watchdog_state = WatchdogProcessState.STOPPED
        _complete_proven_stop(session, operation, details)
    incidents.evaluate_operation_success(operation)
    return session


def _interrupt_session_outputs(session_id: int) -> None:
    """Preserve incomplete output inside the caller's projection transaction."""
    for output in db.session.scalars(db.select(OutputFile).where(OutputFile.session_id == session_id)):
        if output.acquisition_state != "complete":
            output.acquisition_state = "interrupted"
        output.termination_reason = output.termination_reason or "forced"
        if output.artifact_state in {"merge_pending", "merging"}:
            output.artifact_state = "merge_blocked"


def _complete_proven_stop(session: Session, operation: Operation, details: dict) -> None:
    """Apply terminal state inside the caller's fenced proof transaction.

    Receipt authentication and the all-owner check remain with each evidence
    source. Both sources share these output, operation and claim mutations.
    """
    from app.models.device_config import DeviceConfig
    from app.domain.enums import DeviceClaimState

    _complete_stop_operation(operation, details)
    if details.get("output_integrity_confirmed") is not True:
        _interrupt_session_outputs(session.id)
    db.session.execute(db.update(DeviceConfig).where(
        DeviceConfig.claimed_session_id == session.id,
    ).values(claim_state=DeviceClaimState.FREE, claimed_session_id=None,
             claim_expires_at=None))
    session.status = SessionStatus.COMPLETED
    session.command_in_flight = False
    session.runtime_port = None
    session.runtime_token = None


def reconcile_terminal_run(session_id: int, event, supervisor=None) -> Session:
    """Project authenticated stop evidence without confusing teardown and samples.

    Historical receipts are retained but cannot complete a newer producer.
    Replaying a receipt repairs projection/finalization after a interrupted commit.
    """
    from app.services.event_ingest import _utc_timestamp
    session = get(session_id)
    payload = dict(event.payload)
    ownership = _runtimes.get(event.runtime_id)
    if ownership is None:
        raise ValueError("stop evidence has no recorded runtime ownership")
    request_time = _utc_timestamp(payload["requested_at"], "requested_at")
    operation = _stop_operation(session, command_id=payload["command_id"], requested_at=request_time)
    finished = event.event_type == "runtime.stop_finished"
    with transaction():
        db.session.execute(db.update(Session).where(Session.id == session.id)
                           .values(command_in_flight=Session.command_in_flight))
        db.session.refresh(session)
        db.session.refresh(ownership)
        db.session.refresh(operation)
        owners = _runtimes.list_for_session(session_id)
        exact_owner = (ownership.watchdog_id == event.watchdog_id
                       and ownership.dataflow_id == event.dataflow_id
                       and ownership.manifest_hash == event.manifest_hash
                       and ownership.session_id == session.id)
        current = bool(owners and owners[0].runtime_id == event.runtime_id
                       and exact_owner
                       and session.dataflow_id == event.dataflow_id)
        releasable = current and all(
            owner.runtime_id == event.runtime_id or ownership_teardown_confirmed(owner)
            or (owner.watchdog_id == event.watchdog_id
                and owner.dataflow_id == ownership.dataflow_id
                and owner.manifest_hash == ownership.manifest_hash) for owner in owners
        )
        owner_details = dict(ownership.details or {})
        owner_details.setdefault("stop_intent", {
            key: payload[key] for key in ("command_id", "stop_reason", "requested_at")
        })
        ownership.details = owner_details
        details = dict(operation.details or {})
        # A later request/report cannot rewrite the accepted cause or replace
        # a cached failure with a generic CLOSED state.
        details.setdefault("stop_reason", payload["stop_reason"])
        details.setdefault("requested_at", payload["requested_at"])
        details.setdefault("shutdown_command_id", payload["command_id"])
        if not current:
            history = dict(details.get("historical_shutdown_results") or {})
            history[event.watchdog_id] = payload
            details["historical_shutdown_results"] = history
            if (finished and payload["teardown_confirmed"] is True and exact_owner
                    and owners and owners[0].runtime_id != event.runtime_id):
                ownership.watchdog_exit_details = payload
                ownership.state = RuntimeOwnershipState.STOPPED
                ownership.stopped_at = ownership.stopped_at or datetime.now(UTC)
                ownership.watchdog_state = WatchdogProcessState.STOPPED
        elif finished and (not details.get("stop_finished_report_id") or (
            details.get("teardown_confirmed") is not True and payload["teardown_confirmed"] is True
        )):
            old_reason = details.get("stop_reason")
            old_request = details.get("requested_at")
            previous_receipt = details.get("stop_finished_report_id")
            administrative_teardown = bool(details.get("administrative_stop_evidence"))
            original_failure = administrative_teardown or (
                previous_receipt and details.get("output_integrity_confirmed") is not True
            )
            if previous_receipt:
                history = dict(details.get("shutdown_receipt_history") or {})
                history[previous_receipt] = {key: details.get(key) for key in (
                    "shutdown_result", "teardown_confirmed", "output_integrity_confirmed", "errors"
                )}
                details["shutdown_receipt_history"] = history
            details.update(payload)
            details["stop_reason"] = old_reason or payload["stop_reason"]
            details["requested_at"] = old_request or payload["requested_at"]
            if original_failure:
                details["output_integrity_confirmed"] = False
            if administrative_teardown:
                # A delayed raw receipt records the watchdog's earlier view;
                # it cannot revoke independently established process teardown.
                details["teardown_confirmed"] = True
            details["stop_finished_report_id"] = event.report_id
            operation.finished_at = datetime.now(UTC)
            teardown = details["teardown_confirmed"]
            operation.state = OperationState.SUCCEEDED if teardown and releasable else OperationState.UNCERTAIN
            if not teardown or not releasable:
                operation.error_code = "stop_proof_missing"
                operation.error_message = "; ".join(str(x) for x in payload.get("errors", []))[:1024] or operation.error_code
            ownership.watchdog_exit_details = payload
            ownership.state = RuntimeOwnershipState.STOPPED if teardown else RuntimeOwnershipState.UNCERTAIN
            if teardown:
                ownership.stopped_at = datetime.now(UTC)
                ownership.watchdog_state = WatchdogProcessState.STOPPED
        elif operation.state not in {OperationState.SUCCEEDED, OperationState.FAILED, OperationState.UNCERTAIN}:
            operation.state = OperationState.RUNNING
        operation.details = details
        if current and session.status != SessionStatus.COMPLETED:
            session.status = SessionStatus.STOPPING
        if current:
            session.command_in_flight = False
        if releasable and finished and details.get("teardown_confirmed") is True:
            _complete_proven_stop(session, operation, details)

    evidence = operation.details or {}
    if releasable and finished and evidence.get("teardown_confirmed") is True:
        if evidence.get("output_integrity_confirmed") is True:
            _schedule_stop_finalization(session, completion_cause=evidence["stop_reason"])
        incidents.evaluate_operation_success(operation)
        _resolve_stop_supervision_incidents(session, event.dataflow_id)
    elif finished and current:
        incidents.evaluate_operation_failure(operation)
    return session


def stop_managed(session_id: int, supervisor, *, force: bool = False) -> Session:
    """Cancel at any lifecycle stage; join a previously accepted shutdown."""
    session = get(session_id)
    if session.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
        return session
    operation = _stop_operation(session)
    now = datetime.now(UTC)
    # Atomically win against schedule/start reservation. If dispatch already
    # owns the row, persist cancellation below and let its launch observe it.
    with transaction():
        result = db.session.execute(db.update(Session).where(
            Session.id == session_id,
            Session.status.in_((SessionStatus.PREPARING, SessionStatus.SCHEDULED)),
            Session.command_in_flight.is_(False),
            Session.dataflow_id.is_(None),
        ).values(status=SessionStatus.COMPLETED, scheduled_for=None,
                 schedule_claim_token=None, schedule_claim_expires_at=None,
                 cancelled_at=now,
                 cancellation_details={"reason": "user_stop", "requested_at": now.isoformat()}))
        if result.rowcount:
            operation.state = OperationState.SUCCEEDED
            operation.finished_at = now
            operation.details = {"stop_reason": "user_stop", "requested_at": now.isoformat(),
                "before_scheduled_start": bool(session.schedule), "teardown_confirmed": True,
                "output_integrity_confirmed": True, "non_launch_confirmed": True}
            return session
    with transaction():
        db.session.execute(db.update(Session).where(
            Session.id == session_id,
            Session.status.not_in([SessionStatus.COMPLETED, SessionStatus.CANCELLED]),
        ).values(status=SessionStatus.STOPPING))
        details = dict(operation.details or {})
        details.setdefault("requested_reason", "user_stop")
        details.setdefault("manual_requested_at", now.isoformat())
        db.session.execute(db.update(Operation).where(
            Operation.id == operation.id,
            Operation.details["stop_finished_report_id"].as_string().is_(None),
        ).values(details=details).execution_options(synchronize_session=False))
    db.session.refresh(operation)
    db.session.refresh(session)
    if session.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED}:
        return session
    dataflow_id = session.dataflow_id or f"unstarted-{session.id}"
    ownership = _runtimes.unresolved_for_dataflow(dataflow_id)
    if ownership is None:
        ownership = next((owner for owner in _runtimes.list_for_session(session.id)
                          if owner.dataflow_id == dataflow_id), None)
    # Startup owns dispatch until it has a target identity. A historical
    # STOPPED label cannot hide an existing identity behind this guard.
    if session.command_in_flight and ownership is None:
        return session
    if ownership is not None:
        with transaction():
            owner_details = dict(ownership.details or {})
            owner_details.setdefault("pending_stop_request", {
                "command_id": operation.command_id,
                "stop_reason": (operation.details or {}).get("stop_reason", "user_stop"),
                "requested_at": (operation.details or {}).get("requested_at") or (operation.details or {}).get("manual_requested_at", now.isoformat()),
            })
            ownership.details = owner_details
    envelope = prepare_command(command="stop", dataflow_id=dataflow_id,
        watchdog_id=(ownership.watchdog_id if ownership is not None else None) or session.watchdog_id or uuid4().hex,
        command_id=operation.command_id, runtime_id=ownership.runtime_id if ownership is not None else None)
    try:
        with transaction():
            db.session.execute(db.update(Operation).where(
                Operation.id == operation.id,
                Operation.details["stop_finished_report_id"].as_string().is_(None),
            ).values(state=OperationState.DISPATCHED, dispatched_at=now)
                .execution_options(synchronize_session=False))
        result = supervisor.stop(session, envelope=envelope)
        if isinstance(result, Mapping):
            # Supply this request's context for synchronous custom supervisors.
            result = dict(result)
            result.setdefault("command_id", operation.command_id)
            result.setdefault("stop_reason", "user_stop")
            result.setdefault("requested_at", now.isoformat())
            result.setdefault("shutdown_result", {})
            result.setdefault("teardown_confirmed", False)
            result.setdefault("output_integrity_confirmed", False)
        return apply_shutdown_result(session, result, ownership)
    except Exception as exc:
        db.session.refresh(operation)
        with transaction():
            db.session.execute(db.update(Session).where(
                Session.id == session_id,
                Session.status.not_in([SessionStatus.COMPLETED, SessionStatus.CANCELLED]),
            ).values(command_in_flight=False, status=SessionStatus.STOPPING))
            db.session.execute(db.update(Operation).where(
                Operation.id == operation.id,
                Operation.details["stop_finished_report_id"].as_string().is_(None),
            ).values(state=OperationState.UNCERTAIN, error_code="stop_proof_missing",
                error_message=str(exc)[:1024],
                details=dict(operation.details or {}) | {"force_requested": force})
                .execution_options(synchronize_session=False))
        db.session.refresh(operation)
        db.session.refresh(session)
        if operation.state == OperationState.UNCERTAIN:
            incidents.evaluate_operation_failure(operation)
        # A repeated Stop returns this progress/result. Neither a transport
        # failure nor force=True is evidence that devices may be released.
        return session


def _resolve_stop_supervision_incidents(session: Session, dataflow_id: str) -> None:
    """Best-effort retirement of incidents made irrelevant by an intentional stop."""
    try:
        incidents.resolve_terminal_supervision_incidents(session.id, dataflow_id)
    except Exception as exc:  # noqa: BLE001 - incident cleanup must not fail a stop
        _log.warning(
            "stop: resolving terminal supervision incidents failed",
            session_id=session.id,
            dataflow_id=dataflow_id,
            error=type(exc).__name__,
            message=str(exc),
        )


def _schedule_stop_finalization(session: Session, *, completion_cause: str = "user_stop") -> None:
    """Complete + enqueue finalization for a cleanly-stopped session's outputs.

    Never raises: the stop has already succeeded and released (or is about to
    release) the hardware, so a finalization-scheduling hiccup must not turn a
    clean stop into a failure. The logical outputs stay completed and
    schedulable by the finalizer/reconciler on a later pass.
    """
    try:
        output_finalization.complete_session_acquisitions(
            session.id,
            completion_cause=completion_cause,
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

    command_view = _recovery_command_view(session, device_id)
    allowed_actions = command_view["allowed_recovery_actions"]
    if action not in allowed_actions:
        state = command_view["recovery_state"]
        raise RecoveryCommandNotAllowed(
            "Recovery is not currently available for this device.",
            details={
                "device_id": device_id,
                "recovery_state": state,
                "control_available": command_view["control_available"],
                "hardware_present": command_view["hardware_present"],
                "allowed_actions": allowed_actions,
            },
        )

    watchdog_id = _active_watchdog_id(dataflow_id) or session.watchdog_id or uuid4().hex
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

    transition_operation(operation.operation_id, OperationState.DISPATCHED)
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
        _release_device_configs(claimed, session_id=session_id)
        raise
    return claimed


def _release_session_device_configs(session: Session) -> None:
    from app.models.device_config import DeviceConfig
    from app.domain.enums import DeviceClaimState
    # A duplicate terminal event may arrive after another session claimed the
    # same device. Release only the ownership proven by this session's receipt.
    with transaction():
        db.session.execute(db.update(DeviceConfig).where(
            DeviceConfig.id.in_(_device_config_ids(session)),
            DeviceConfig.claimed_session_id == session.id,
        ).values(claim_state=DeviceClaimState.FREE, claimed_session_id=None,
                 claim_expires_at=None))


def _release_device_configs(config_ids: list[int], *, session_id: int) -> None:
    from app.models.device_config import DeviceConfig
    from app.domain.enums import DeviceClaimState
    with transaction():
        db.session.execute(db.update(DeviceConfig).where(
            DeviceConfig.id.in_(config_ids), DeviceConfig.claimed_session_id == session_id,
        ).values(claim_state=DeviceClaimState.FREE, claimed_session_id=None, claim_expires_at=None))
