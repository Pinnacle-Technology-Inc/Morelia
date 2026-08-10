"""Device template resource for the reusable parameter library."""

from flask_smorest import Blueprint, abort

import app.services.device_templates as device_template_service
from app.api.schemas import (
    CreateDeviceTemplateSchema,
    DeviceTemplateContentSchema,
    DeviceTemplateDeleteResponseSchema,
    DeviceTemplateMatchSchema,
    DeviceTemplateRenameResponseSchema,
    DeviceTemplateSchema,
    DeviceTemplateSourceSchema,
    DeviceTemplateTomlSchema,
    DeviceTemplateTomlValidationSchema,
    DeviceTemplateTypeSchema,
    RenameDeviceTemplateSchema,
)
from app.domain.errors import DeviceTemplateNameExists, DeviceTemplateNotFound, UnknownConfigType
from app.services.registry import supported_device_types

blp = Blueprint(
    "device_templates",
    __name__,
    url_prefix="/api/v1/device-templates",
    description="Manage reusable, mutable device templates.",
)
source_blp = Blueprint(
    "device_template_sources",
    __name__,
    url_prefix="/api/v1/device-template-sources",
    description="Read and repair editable device-template TOML source.",
)
# TODO Something changed with the DeviceTemplate id because it no longer exists. What did it change to or should it be added back?

def _invalid_template(exc: Exception) -> None:
    abort(422, message=str(exc), code="invalid_device_template")


def _reference_warning_payload(referencing_sessions):
    return {
        "referencing_sessions": referencing_sessions,
        "warning": "referencing_sessions",
    }


@blp.route("", methods=["POST"])
@blp.arguments(CreateDeviceTemplateSchema)
@blp.response(201, DeviceTemplateSchema)
def create_device_template(payload):
    if device_template_service.get_by_name(payload["name"]) is not None:
        raise DeviceTemplateNameExists(payload["name"])
    try:
        return device_template_service.import_config(payload)
    except (UnknownConfigType, ValueError) as exc:
        _invalid_template(exc)


@blp.route("", methods=["GET"])
@blp.response(200, DeviceTemplateSchema(many=True))
def list_device_templates():
    return device_template_service.list()


@blp.route("/catalog", methods=["GET"])
@blp.response(200, DeviceTemplateSchema(many=True))
def list_device_template_catalog():
    return device_template_service.catalog()


@blp.route("/supported-types", methods=["GET"])
@blp.response(200, DeviceTemplateTypeSchema(many=True))
def list_device_template_types():
    return supported_device_types()


@blp.route("/match", methods=["POST"])
@blp.arguments(DeviceTemplateContentSchema)
@blp.response(200, DeviceTemplateMatchSchema)
def match_device_template(payload):
    try:
        content = device_template_service.canonical_content(payload)
    except (UnknownConfigType, ValueError) as exc:
        _invalid_template(exc)
    content_hash = device_template_service.content_hash(content)
    return {
        "content": content,
        "content_hash": content_hash,
        "matches": device_template_service.find_by_content_hash(content_hash),
    }


@blp.route("/validations", methods=["POST"])
@blp.arguments(DeviceTemplateTomlSchema)
@blp.response(200, DeviceTemplateTomlValidationSchema)
def validate_device_template_toml(payload):
    try:
        content = device_template_service.validate_toml(payload["toml"])
    except (UnknownConfigType, ValueError) as exc:
        _invalid_template(exc)
    content_hash = device_template_service.content_hash(content)
    return {
        "content": content,
        "parameter_count": len(content.get("parameters", {})),
        "content_hash": content_hash,
        "matches": device_template_service.find_by_content_hash(content_hash),
    }


@source_blp.route("/<path:reference>", methods=["GET"])
@source_blp.response(200, DeviceTemplateSourceSchema)
def get_device_template_source(reference):
    return {
        "reference": reference,
        "toml": device_template_service.read_source(reference),
    }


@source_blp.route("/<path:reference>", methods=["PUT"])
@source_blp.arguments(DeviceTemplateTomlSchema)
@source_blp.response(200, DeviceTemplateSchema)
def repair_device_template_source(payload, reference):
    try:
        return device_template_service.repair_source(reference, payload["toml"])
    except (UnknownConfigType, ValueError) as exc:
        _invalid_template(exc)


@blp.route("/<string:name>", methods=["GET"])
@blp.response(200, DeviceTemplateSchema)
def get_device_template(name):
    try:
        template = device_template_service.get_by_path(name)
    except ValueError:
        template = None
    template = template or device_template_service.get_by_name(name)
    if template is None:
        raise DeviceTemplateNotFound(name)
    return template


@blp.route("/<string:name>", methods=["PUT"])
@blp.arguments(DeviceTemplateContentSchema)
@blp.response(200, DeviceTemplateSchema)
def update_device_template(payload, name):
    try:
        return device_template_service.update(name, payload)
    except (UnknownConfigType, ValueError) as exc:
        _invalid_template(exc)


@blp.route("/<string:name>/rename", methods=["POST"])
@blp.arguments(RenameDeviceTemplateSchema)
@blp.response(200, DeviceTemplateRenameResponseSchema)
def rename_device_template(payload, name):
    template, referencing_sessions = device_template_service.rename(
        name,
        payload["new_name"],
    )
    return {
        "device_template": template,
        **_reference_warning_payload(referencing_sessions),
    }


@blp.route("/<string:name>", methods=["DELETE"])
@blp.response(200, DeviceTemplateDeleteResponseSchema)
def delete_device_template(name):
    referencing_sessions = device_template_service.delete(name)
    return {
        "deleted_name": name,
        **_reference_warning_payload(referencing_sessions),
    }
