"""Device discovery resource."""

from flask import current_app
from flask_smorest import Blueprint

from app.api.schemas import DevicePoolSchema, ScanResultSchema
from app.services.device_list import build_pool_rows

blp = Blueprint(
    "devices",
    __name__,
    url_prefix="/api/v1/devices",
    description="Discover attached acquisition devices.",
)


@blp.route("/", methods=["GET"])
@blp.response(200, ScanResultSchema)
def list_devices():
    return current_app.extensions["device_discovery_service"].scan()


@blp.route("/pool", methods=["GET"])
@blp.response(200, DevicePoolSchema)
def list_device_pool():
    scan = current_app.extensions["device_discovery_service"].scan()
    return {
        "scan_id": scan.scan_id,
        "scanned_at": scan.scanned_at,
        "devices": build_pool_rows(scan.devices),
    }
