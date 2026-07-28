"""Validate and translate HTTP requests into service calls.
"""

import structlog
from flask import current_app
from flask_smorest import Blueprint, abort

import app.services.session_status as session_status_service
import app.services.session_templates as session_template_service
import app.services.sessions as session_service
from app.api.schemas import (
    CreateSessionSchema,
    ExportSessionTemplateSchema,
    FleetOverviewSchema,
    RecoverSessionSchema,
    SessionNameSuggestionSchema,
    SessionSchema,
    SessionStatusSnapshotSchema,
    SessionTemplateSchema,
    StartSessionSchema,
    StopSessionSchema,
)

_log = structlog.get_logger(__name__)

blp = Blueprint(
    "sessions",
    __name__,
    url_prefix="/api/v1/sessions",
    description="Create and supervise acquisition sessions.",
)


def _require_lifecycle_commands_enabled() -> None:
    state = current_app.extensions.get("control_plane_state")
    if state is not None and state.quiescing:
        abort(
            503,
            message="The control plane is quiescing for restart; lifecycle commands are disabled.",
            code="control_plane_quiescing",
        )


def _live_health():
    """Bridge the poller's in-memory snapshots into a ``dataflow_id -> HealthState`` map.

    Health depends on live plane→host reachability, which only the ``EventPoller``
    (owned by the ``HostSupervisor``) observes. When no supervisor/poller is
    running (e.g. the single-watchdog path or tests), there is no live health and
    the aggregation service reports it as ``None`` rather than guessing.
    """
    supervisor = current_app.extensions.get("host_supervisor")
    if supervisor is None:
        return {}
    try:
        snapshots = supervisor.event_poller.snapshots()
    except Exception as exc:
        _log.warning(
            "live health unavailable — poller snapshots failed",
            error=type(exc).__name__,
            message=str(exc),
        )
        return {}
    return {
        dataflow_id: snapshot.health_state for dataflow_id, snapshot in snapshots.items()
    }


@blp.route("/", methods=["POST"])
@blp.arguments(CreateSessionSchema)
@blp.response(201, SessionSchema)
def create_session(new_data):
    """Create a Draft session. Schema-validation failures surface as 422."""
    return session_service.create(new_data)


@blp.route("/", methods=["GET"])
@blp.response(200, SessionSchema(many=True))
def list_sessions():
    return session_service.list_all()


@blp.route("/name-suggestion", methods=["GET"])
@blp.response(200, SessionNameSuggestionSchema)
def session_name_suggestion():
    """Preview the name POST / would mint for a session created without one.

    """
    return {"name": session_service.suggest_name()}


@blp.route("/overview", methods=["GET"])
@blp.response(200, FleetOverviewSchema)
def sessions_overview():
    """Fleet overview (6f): running tally + per-session lifecycle/health/phase."""
    return session_status_service.fleet_overview(live_health=_live_health())


@blp.route("/<int:session_id>", methods=["GET"])
@blp.response(200, SessionSchema)
def get_session(session_id):
    return session_service.get(session_id)


@blp.route("/<int:session_id>/status", methods=["GET"])
@blp.response(200, SessionStatusSnapshotSchema)
def session_status(session_id):
    """Detail snapshot (6g): aggregate join across sessions/runtime/events/ops/incidents/gaps."""
    return session_status_service.detail(session_id, live_health=_live_health())


@blp.route("/<int:session_id>", methods=["DELETE"])
@blp.response(204)
def delete_session(session_id):
    session_service.delete(session_id)
    return ""


@blp.route("/<int:session_id>/commands/start", methods=["POST"])
@blp.arguments(StartSessionSchema)
@blp.response(202, SessionSchema)
def start_session(payload, session_id):
    _require_lifecycle_commands_enabled()
    if current_app.config.get("SESSION_RUNTIME_HOST_ENABLED"):
        supervisor = current_app.extensions.get("host_supervisor")
        if supervisor is not None:
            return session_service.start_managed(
                session_id,
                supervisor,
                sink_overrides=payload.get("sink_overrides") or None,
                force=bool(payload.get("force", False)),
            )
    return session_service.start(session_id, current_app.extensions["watchdog_adapter"])


@blp.route("/<int:session_id>/commands/stop", methods=["POST"])
@blp.arguments(StopSessionSchema)
@blp.response(202, SessionSchema)
def stop_session(payload, session_id):
    _require_lifecycle_commands_enabled()
    force = bool(payload.get("force", False))
    if current_app.config.get("SESSION_RUNTIME_HOST_ENABLED"):
        supervisor = current_app.extensions.get("host_supervisor")
        if supervisor is not None:
            return session_service.stop_managed(session_id, supervisor, force=force)
    return session_service.stop(session_id, current_app.extensions["watchdog_adapter"])


@blp.route("/<int:session_id>/commands/recover", methods=["POST"])
@blp.arguments(RecoverSessionSchema)
@blp.response(202, SessionSchema)
def recover_session(payload, session_id):
    _require_lifecycle_commands_enabled()
    if current_app.config.get("SESSION_RUNTIME_HOST_ENABLED"):
        supervisor = current_app.extensions.get("host_supervisor")
        if supervisor is not None:
            return session_service.recover_managed(
                session_id, payload["device_id"], payload["action"], supervisor
            )
    return session_service.recover(
        session_id,
        payload["device_id"],
        payload["action"],
        current_app.extensions["watchdog_adapter"],
    )


@blp.route("/<int:session_id>/complete", methods=["POST"])
@blp.response(202, SessionSchema)
def complete_session(session_id):
    _require_lifecycle_commands_enabled()
    return session_service.complete(session_id)


@blp.route("/<int:session_id>/template-export", methods=["POST"])
@blp.arguments(ExportSessionTemplateSchema)
@blp.response(201, SessionTemplateSchema)
def export_session_template(payload, session_id):
    """Snapshot-copy this session's composition into a new named session template."""
    session = session_service.get(session_id)
    return session_template_service.create_from_session(
        session,
        payload["name"],
        include_hardware_id=payload.get("binding_mode") == "device-hardcoded",
    )
