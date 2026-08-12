"""Validate and translate HTTP requests into service calls.
"""

import structlog
from flask import current_app
from flask_smorest import Blueprint, abort

import app.services.session_notes as session_note_service
import app.services.session_status as session_status_service
import app.services.session_templates as session_template_service
import app.services.sessions as session_service
from app.api.schemas import (
    CreateSessionNoteSchema,
    ExportSessionTemplateSchema,
    FleetOverviewSchema,
    RecoverSessionSchema,
    SessionNameSuggestionQuerySchema,
    SessionNameSuggestionSchema,
    SessionNoteListQuerySchema,
    SessionNotePageSchema,
    SessionNoteSchema,
    SessionSchema,
    SessionStatusSnapshotSchema,
    SessionTemplateSchema,
    StopSessionSchema,
    UpdateSessionNoteSchema,
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


@blp.route("/", methods=["GET"])
@blp.response(200, SessionSchema(many=True))
def list_sessions():
    return session_service.list_all()


@blp.route("/name-suggestion", methods=["GET"])
@blp.arguments(SessionNameSuggestionQuerySchema, location="query")
@blp.response(200, SessionNameSuggestionSchema)
def session_name_suggestion(query):
    """Preview the name POST / would mint for a session created without one.

    """
    return {"name": session_service.suggest_name(query["source_template_id"])}


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


@blp.route("/<int:session_id>/notes", methods=["GET"])
@blp.arguments(SessionNoteListQuerySchema, location="query")
@blp.response(200, SessionNotePageSchema)
def list_session_notes(query, session_id):
    return session_note_service.list_page(
        session_id,
        limit=query["limit"],
        before_id=query.get("before_id"),
    )


@blp.route("/<int:session_id>/notes", methods=["POST"])
@blp.arguments(CreateSessionNoteSchema)
@blp.response(201, SessionNoteSchema)
def create_session_note(payload, session_id):
    return session_note_service.create(
        session_id,
        body=payload["body"],
        show_timestamp=payload["show_timestamp"],
    )


@blp.route("/<int:session_id>/notes/<int:note_id>", methods=["PATCH"])
@blp.arguments(UpdateSessionNoteSchema)
@blp.response(200, SessionNoteSchema)
def update_session_note(payload, session_id, note_id):
    return session_note_service.update(
        session_id,
        note_id,
        body=payload.get("body"),
        show_timestamp=payload.get("show_timestamp"),
    )


@blp.route("/<int:session_id>/commands/stop", methods=["POST"])
@blp.arguments(StopSessionSchema)
@blp.response(202, SessionSchema)
def stop_session(payload, session_id):
    _require_lifecycle_commands_enabled()
    force = bool(payload.get("force", False))
    if current_app.config.get("SESSION_RUNTIME_HOST_ENABLED"):
        supervisor = current_app.extensions.get("host_supervisor") #Check if  the runtime host is running, else use the watchdog adapter to shutdown
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
