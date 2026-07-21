"""Session template resource — the reusable, portable composition library."""

from flask_smorest import Blueprint, abort

import app.services.session_templates as session_template_service
from app.api.schemas import CreateSessionTemplateSchema, SessionTemplateSchema
from app.domain.errors import SessionTemplateNameExists, SessionTemplateNotFound

blp = Blueprint(
    "session_templates",
    __name__,
    url_prefix="/api/v1/session-templates",
    description="Manage reusable session-template compositions (Flow 2's snapshot-copy source).",
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


@blp.route("/<string:name>", methods=["GET"])
@blp.response(200, SessionTemplateSchema)
def get_session_template(name):
    template = session_template_service.get_by_name(name)
    if template is None:
        raise SessionTemplateNotFound(name)
    return template


@blp.route("/<string:name>", methods=["PUT"])
@blp.arguments(CreateSessionTemplateSchema)
@blp.response(200, SessionTemplateSchema)
def update_session_template(payload, name):
    try:
        payload = dict(payload)
        payload.pop("name", None)
        return session_template_service.update(name, payload)
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


@blp.route("/<string:name>", methods=["DELETE"])
@blp.response(204)
def delete_session_template(name):
    session_template_service.delete(name)
    return ""
