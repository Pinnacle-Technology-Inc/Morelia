"""Device config resource for persisted physical device bindings."""

from flask_smorest import Blueprint, abort

import app.services.device_configs as device_config_service
import app.services.device_templates as device_template_service
from app.api.schemas import (
    CreateDeviceConfigFromTemplateSchema,
    CreateDeviceConfigSchema,
    DeviceConfigDeleteResponseSchema,
    DeviceConfigSchema,
    EditDeviceConfigSchema,
    NameDeviceConfigSchema,
)
from app.domain.errors import (
    DeviceConfigExists,
    DeviceNicknameExists,
    DeviceTemplateNotFound,
    UnknownConfigType,
    UnsupportedDeviceType,
)

blp = Blueprint(
    "device_configs",
    __name__,
    url_prefix="/api/v1/device-configs",
    description="Manage persisted, port-bound physical device configs.",
)


def _invalid_config(exc: Exception) -> None:
    abort(422, message=str(exc), code="invalid_device_config")


@blp.route("", methods=["POST"])
@blp.arguments(CreateDeviceConfigSchema)
@blp.response(201, DeviceConfigSchema)
def create_device_config(payload):
    try:
        return device_config_service.create(**payload)
    except (DeviceConfigExists, DeviceNicknameExists):
        raise
    except (UnknownConfigType, UnsupportedDeviceType, ValueError) as exc:
        _invalid_config(exc)


@blp.route("/from-template", methods=["POST"])
@blp.arguments(CreateDeviceConfigFromTemplateSchema)
@blp.response(201, DeviceConfigSchema)
def create_device_config_from_template(payload):
    template = device_template_service.get_by_name(payload["template_name"])
    if template is None:
        raise DeviceTemplateNotFound(payload["template_name"])
    try:
        return device_config_service.create_from_template(
            template,
            hardware_id=payload["hardware_id"],
            port=payload["port"],
            nickname=payload["nickname"],
        )
    except (DeviceConfigExists, DeviceNicknameExists):
        raise
    except (UnknownConfigType, UnsupportedDeviceType, ValueError) as exc:
        _invalid_config(exc)


@blp.route("/name", methods=["POST"])
@blp.arguments(NameDeviceConfigSchema)
@blp.response(200, DeviceConfigSchema)
def name_device_config(payload):
    return device_config_service.rename(
        device_type=payload["device_type"],
        hardware_id=payload["hardware_id"],
        nickname=payload["nickname"],
    )


@blp.route("", methods=["GET"])
@blp.response(200, DeviceConfigSchema(many=True))
def list_device_configs():
    return device_config_service.list()


@blp.route("/<int:config_id>", methods=["GET"])
@blp.response(200, DeviceConfigSchema)
def get_device_config(config_id: int):
    row = device_config_service.get_by_id(config_id)
    if row is None:
        from app.domain.errors import DeviceConfigNotFound

        raise DeviceConfigNotFound(config_id)
    return row


@blp.route("/<int:config_id>", methods=["PATCH"])
@blp.arguments(EditDeviceConfigSchema)
@blp.response(200, DeviceConfigSchema)
def edit_device_config(payload, config_id: int):
    try:
        return device_config_service.edit(
            config_id,
            parameters=payload["parameters"],
            update_source_template=payload["update_source_template"],
            source_template=payload["source_template"],
        )
    except DeviceTemplateNotFound:
        # Has its own registered 404 handler — an unknown relink target is a
        # missing template, not a malformed config.
        raise
    except (UnknownConfigType, UnsupportedDeviceType, ValueError) as exc:
        _invalid_config(exc)


@blp.route("/<int:config_id>", methods=["DELETE"])
@blp.response(200, DeviceConfigDeleteResponseSchema)
def delete_device_config(config_id: int):
    device_config_service.delete(config_id)
    return {"deleted_id": config_id}
