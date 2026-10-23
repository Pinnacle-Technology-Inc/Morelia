"""Device discovery resource."""

from flask import current_app
from flask_smorest import Blueprint, abort

from app.api.schemas import DevicePoolSchema, DeviceScanSchema, ScanResultSchema
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
        "devices": build_pool_rows(scan.devices, warnings=scan.warnings),
        "warnings": list(getattr(scan, "warnings", ())),
    }


def _scan_payload(scan):
    return {
        "scan_id": scan.scan_id,
        "scanned_at": scan.scanned_at,
        "state": scan.state,
        "revision": scan.revision,
        "completed": scan.completed,
        "total": scan.total,
        "finished_at": scan.finished_at,
        "error": scan.error,
        "devices": build_pool_rows(scan.devices, scan_state=scan.state, warnings=scan.warnings),
        "warnings": list(scan.warnings),
    }


@blp.route("/scans", methods=["POST"])
@blp.response(202, DeviceScanSchema)
def start_scan():
    return _scan_payload(current_app.extensions["device_discovery_service"].start())


@blp.route("/scans/<scan_id>", methods=["GET"])
@blp.response(200, DeviceScanSchema)
def scan_progress(scan_id):
    try:
        snapshot = current_app.extensions["device_discovery_service"].snapshot(scan_id)
    except KeyError:
        abort(404, message="This device scan is no longer retained. Start a new scan.")
    return _scan_payload(snapshot)
