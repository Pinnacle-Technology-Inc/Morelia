"""Session-template resource backed by the flat TOML library."""

from flask_smorest import Blueprint, abort

import app.services.session_templates as session_template_service
from app.api.schemas import (
    AssignmentPlanSchema,
    CreateSessionTemplateFromTomlSchema,
    CreateSessionTemplateSchema,
    ResolveSessionTemplateRenameSchema,
    SessionTemplateSchema,
    SessionTemplateSourceSchema,
    SessionTemplateTomlSchema,
    SessionTemplateTomlValidationSchema,
)
from app.domain.errors import (
    SessionTemplateDuplicate,
    SessionTemplateNameExists,
    SessionTemplateNotFound,
    SessionTemplateStateConflict,
)

blp = Blueprint(
    "session_templates",
    __name__,
    url_prefix="/api/v1/session-templates",
    description="Manage flat-file session-template definitions and registry metadata.",
)
source_blp = Blueprint(
    "session_template_sources",
    __name__,
    url_prefix="/api/v1/session-template-sources",
    description="Read and repair editable session-template TOML source.",
)


def _raise_name_conflict(exc, requested_name):
    existing = session_template_service.get_by_name(exc.name)
    if existing is not None:
        if exc.name != requested_name:
            raise SessionTemplateDuplicate(
                {
                    "template_id": existing.template_id,
                    "name": existing.name,
                    "reference": existing.reference,
                    "detail_url": f"/api/v1/session-templates/{existing.template_id}",
                },
                existing.state,
                existing.allowed_actions,
            ) from exc
        exc.details = {
            "current_state": existing.state,
            "allowed_actions": existing.allowed_actions,
        }
    raise exc


@blp.route("", methods=["POST"])
@blp.arguments(CreateSessionTemplateSchema)
@blp.response(201, SessionTemplateSchema)
def create_session_template(payload):
    try:
        return session_template_service.import_config(payload)
    except SessionTemplateNameExists as exc:
        _raise_name_conflict(exc, payload["name"])
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


@blp.route("/validations", methods=["POST"])
@blp.arguments(SessionTemplateTomlSchema)
@blp.response(200, SessionTemplateTomlValidationSchema)
def validate_session_template_toml(payload):
    """Validate a TOML draft without creating template or registry files."""

    try:
        content = session_template_service.validate_toml(payload["toml"])
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")
    flows = content["device_flows"]
    return {
        "content": content,
        "summary": {
            "device_flows": len(flows),
            "sinks": sum(len(flow["sinks"]) for flow in flows),
            "hardware_preferences": sum("hardware_id" in flow for flow in flows),
            "policy": content["policy"],
        },
    }


@blp.route("/imports", methods=["POST"])
@blp.arguments(CreateSessionTemplateFromTomlSchema)
@blp.response(201, SessionTemplateSchema)
def import_session_template_toml(payload):
    """Create a registered template from user-authored TOML text."""

    try:
        return session_template_service.import_toml(payload["toml"], name=payload["name"])
    except SessionTemplateNameExists as exc:
        _raise_name_conflict(exc, payload["name"])
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


@blp.route("", methods=["GET"])
@blp.response(200, SessionTemplateSchema(many=True))
def list_session_templates():
    return session_template_service.list()


@blp.route("/catalog", methods=["GET"])
@blp.response(200, SessionTemplateSchema(many=True))
def list_session_template_catalog():
    """The file-authoritative template list, joined with each revision's runs."""
    return session_template_service.catalog_with_run_history()


@source_blp.route("/<path:reference>", methods=["GET"])
@source_blp.response(200, SessionTemplateSourceSchema)
def get_session_template_source(reference):
    """Return editable TOML source without exposing arbitrary filesystem paths."""

    try:
        return {
            "reference": reference,
            "toml": session_template_service.read_source(reference),
        }
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


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
        template = session_template_service.get_by_id(reference)
    if template is None:
        raise SessionTemplateNotFound(reference)
    return template


@source_blp.route("/<path:reference>", methods=["PUT"])
@source_blp.arguments(SessionTemplateTomlSchema)
@source_blp.response(200, SessionTemplateSchema)
def repair_session_template_source(payload, reference):
    """Validate and atomically replace the source of an invalid template."""

    try:
        return session_template_service.repair_source(reference, payload["toml"])
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_session_template")


def _template_by_id(template_id):
    template = session_template_service.get_by_id(template_id)
    if template is None:
        raise SessionTemplateNotFound(template_id)
    return template


def _raise_state_conflict(template, exc):
    raise SessionTemplateStateConflict(
        str(exc),
        template.state,
        template.allowed_actions,
    ) from exc


@blp.route("/<path:reference>/actions/register", methods=["POST"])
@blp.response(200, SessionTemplateSchema)
def register_discovered_template(reference):
    template = session_template_service.get_by_reference(reference)
    if template is None:
        raise SessionTemplateNotFound(reference)
    if template.state == "INVALID":
        abort(
            422,
            message=f"session template {reference!r} is not valid TOML",
            code="invalid_session_template",
        )
    try:
        return session_template_service.register_discovered(reference)
    except ValueError as exc:
        _raise_state_conflict(template, exc)


@blp.route("/<string:template_id>/actions/accept-change", methods=["POST"])
@blp.response(200, SessionTemplateSchema)
def accept_template_change(template_id):
    template = _template_by_id(template_id)
    try:
        return session_template_service.accept_change(template_id)
    except ValueError as exc:
        _raise_state_conflict(template, exc)


@blp.route("/<string:template_id>/actions/refresh-dependency-revision", methods=["POST"])
@blp.response(200, SessionTemplateSchema)
def refresh_dependency_revision(template_id):
    template = _template_by_id(template_id)
    try:
        return session_template_service.refresh_dependency_revision(template_id)
    except ValueError as exc:
        _raise_state_conflict(template, exc)


@blp.route("/<string:template_id>/actions/archive", methods=["POST"])
@blp.response(200, SessionTemplateSchema)
def archive_template(template_id):
    template = _template_by_id(template_id)
    try:
        return session_template_service.archive(template_id)
    except ValueError as exc:
        _raise_state_conflict(template, exc)


@blp.route("/<string:template_id>/actions/resolve-rename", methods=["POST"])
@blp.arguments(ResolveSessionTemplateRenameSchema)
@blp.response(200, SessionTemplateSchema)
def resolve_template_rename(payload, template_id):
    template = _template_by_id(template_id)
    try:
        return session_template_service.resolve_ambiguous_rename(
            template_id,
            payload["selected_relative_path"],
        )
    except ValueError as exc:
        _raise_state_conflict(template, exc)


@blp.route("/<path:reference>", methods=["DELETE"])
@blp.response(204)
def delete_session_template(reference):
    session_template_service.delete(reference)
    return ""
