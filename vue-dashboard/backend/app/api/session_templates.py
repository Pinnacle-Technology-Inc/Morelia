"""Session-template resource backed by the flat TOML library."""

from flask_smorest import Blueprint, abort

import app.services.session_templates as session_template_service
from app.api.schemas import (
    AssignmentPlanSchema,
    CreateSessionTemplateSchema,
    SessionTemplateSchema,
)
from app.domain.errors import SessionTemplateNameExists, SessionTemplateNotFound

blp = Blueprint(
    "session_templates",
    __name__,
    url_prefix="/api/v1/session-templates",
    description="Manage flat-file session-template definitions and registry metadata.",
)


@blp.route("", methods=["POST"])
@blp.arguments(CreateSessionTemplateSchema)
@blp.response(201, SessionTemplateSchema)
def create_session_template(payload):
    try:
        return session_template_service.import_config(payload)
    except SessionTemplateNameExists:
        # SessionTemplateNameExists/DeviceTemplateNotFound propagate to their
        # own registered handlers (409/404); this only catches genuine
        # validation failures (InvalidSessionEntry is itself a ValueError).
        raise
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


@blp.route("", methods=["GET"])
@blp.response(200, SessionTemplateSchema(many=True))
def list_session_templates():
    return session_template_service.list()


@blp.route("/catalog", methods=["GET"])
@blp.response(200, SessionTemplateSchema(many=True))
def list_session_template_catalog():
    """Compatibility alias for the file-authoritative template list."""
    return session_template_service.catalog()


@blp.route("/<path:reference>/assignment-plan", methods=["POST"])
@blp.response(200, AssignmentPlanSchema)
def assignment_plan(reference):
    """Plan assignments for a chosen session template when user in create sessions view.

    """
    from app.services.template_assignments import plan

    return plan(reference)


@blp.route("/<path:reference>", methods=["GET"])
@blp.response(200, SessionTemplateSchema)
def get_session_template(reference):
    template = session_template_service.get_by_reference(reference)
    if template is None:
        template = session_template_service.get_by_name(reference)
    if template is None:
        raise SessionTemplateNotFound(reference)
    return template


@blp.route("/<path:reference>", methods=["PUT"])
@blp.arguments(CreateSessionTemplateSchema)
@blp.response(200, SessionTemplateSchema)
def update_session_template(payload, reference):
    try:
        payload = dict(payload)
        payload.pop("name", None)
        return session_template_service.update(reference, payload)
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


@blp.route("/<path:reference>", methods=["DELETE"])
@blp.response(204)
def delete_session_template(reference):
    session_template_service.delete(reference)
    return ""
