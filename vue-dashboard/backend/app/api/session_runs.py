"""Atomic immediate-run and durable scheduled-run HTTP command."""

from flask import current_app
from flask_smorest import Blueprint, abort

import app.services.sessions as session_service
from app.api.schemas import CreateSessionRunSchema, SessionSchema

blp = Blueprint(
    "session-runs",
    __name__,
    url_prefix="/api/v1/session-runs",
    description="Atomically create an immediate or scheduled session run.",
)


@blp.route("", methods=["POST"])
@blp.arguments(CreateSessionRunSchema)
@blp.response(202, SessionSchema)
def create_session_run(payload):
    state = current_app.extensions.get("control_plane_state")
    if state is not None and state.quiescing:
        abort(
            503,
            message="The control plane is quiescing; new runs are disabled.",
            code="control_plane_quiescing",
        )
    supervisor = current_app.extensions["host_supervisor"]
    return session_service.create_run(
        payload,
        supervisor=supervisor,
    )
