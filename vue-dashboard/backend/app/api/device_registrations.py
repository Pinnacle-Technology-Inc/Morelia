"""Pre-configuration names for physical devices."""

from flask_smorest import Blueprint, abort

import app.services.device_registrations as registration_service
from app.api.schemas import DeviceRegistrationSchema, RegisterDeviceNameSchema
from app.domain.errors import DeviceNicknameExists, InvalidHardwareId

blp = Blueprint(
    "device_registrations",
    __name__,
    url_prefix="/api/v1/device-registrations",
    description="Register operator names before physical devices are configured.",
)


@blp.route("", methods=["POST"])
@blp.arguments(RegisterDeviceNameSchema)
@blp.response(200, DeviceRegistrationSchema)
def register_device_name(payload):
    try:
        return registration_service.register(**payload)
    except (DeviceNicknameExists, InvalidHardwareId):
        raise
    except ValueError as exc:
        abort(422, message=str(exc), code="invalid_device_registration")


@blp.route("", methods=["GET"])
@blp.response(200, DeviceRegistrationSchema(many=True))
def list_device_registrations():
    return registration_service.list()
