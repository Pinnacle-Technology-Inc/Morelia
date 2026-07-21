"""Device template resource for the reusable parameter library."""

from flask_smorest import Blueprint, abort

import app.services.device_templates as device_template_service
from app.api.schemas import (
    CreateDeviceTemplateSchema,
    DeviceTemplateContentSchema,
    DeviceTemplateDeleteResponseSchema,
    DeviceTemplateRenameResponseSchema,
    DeviceTemplateSchema,
    RenameDeviceTemplateSchema,
)
from app.domain.errors import DeviceTemplateNotFound, UnknownConfigType

blp = Blueprint(
    "device_templates",
    __name__,
    url_prefix="/api/v1/device-templates",
    description="Manage reusable, mutable device templates.",
)


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
    try:
        return device_template_service.import_config(payload)
    except (UnknownConfigType, ValueError) as exc:
        _invalid_template(exc)


@blp.route("", methods=["GET"])
@blp.response(200, DeviceTemplateSchema(many=True))
def list_device_templates():
    return device_template_service.list()


@blp.route("/<string:name>", methods=["GET"])
@blp.response(200, DeviceTemplateSchema)
def get_device_template(name):
    template = device_template_service.get_by_name(name)
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
