"""Runtime ownership resource."""

import os
import signal
import threading

from flask import current_app, request
from flask_smorest import Blueprint, abort

import app.services.runtimes as runtime_service
from app.api.schemas import ReconciliationSummarySchema, RuntimeOwnershipSchema
from app.services.reconciliation import reconcile_startup

blp = Blueprint(
    "runtimes",
    __name__,
    url_prefix="/api/v1/runtimes",
    description="Inspect runtime ownership and trigger reconciliation.",
)


@blp.route("/", methods=["GET"])
@blp.response(200, RuntimeOwnershipSchema(many=True))
def list_runtimes():
    return runtime_service.list_runtimes()


@blp.route("/reconcile", methods=["POST"])
@blp.response(200, ReconciliationSummarySchema)
def reconcile_runtimes():
    _require_lifecycle_commands_enabled()
    return reconcile_startup(
        status_probe=current_app.config["STARTUP_RECONCILIATION_STATUS_PROBE"]
    )


@blp.route("/shutdown", methods=["POST"])
def shutdown_runtimes():
    _require_lifecycle_commands_enabled()
    payload = request.get_json(silent=True) or {}
    force = bool(payload.get("force", False)) if isinstance(payload, dict) else False
    return _shutdown_runtime_hosts(force=force)


@blp.route("/control-plane-shutdown", methods=["POST"])
def shutdown_control_plane():
    _require_lifecycle_commands_enabled()
    payload = request.get_json(silent=True) or {}
    force = bool(payload.get("force", False)) if isinstance(payload, dict) else False
    runtime_shutdown = _shutdown_runtime_hosts(force=force)
    _schedule_process_shutdown()
    return {
        "shutdown_scheduled": True,
        "runtime_shutdown": runtime_shutdown,
    }, 202


@blp.route("/control-plane-restart", methods=["POST"])
def restart_control_plane():
    state = current_app.extensions["control_plane_state"]
    state.begin_restart()
    supervisor = current_app.extensions.get("host_supervisor")
    result = supervisor.quiesce() if supervisor is not None else {"tracked_runtime_count": 0}
    _schedule_process_shutdown()
    return {
        "quiesced": True,
        "shutdown_scheduled": True,
        "tracked_runtime_count": int(result.get("tracked_runtime_count", 0)),
    }, 202


@blp.route("/restart-report", methods=["GET"])
def restart_report():
    return current_app.extensions.get(
        "restart_reconciliation_report",
        {"adopted": [], "uncertain": []},
    )


def _require_lifecycle_commands_enabled() -> None:
    state = current_app.extensions.get("control_plane_state")
    if state is not None and state.quiescing:
        abort(
            503,
            message="The control plane is quiescing for restart; lifecycle commands are disabled.",
            code="control_plane_quiescing",
        )


def _shutdown_runtime_hosts(*, force: bool) -> dict[str, object]:
    supervisor = current_app.extensions.get("host_supervisor")
    if supervisor is None:
        return {
            "running_count": 0,
            "stopped_count": 0,
            "failed_count": 0,
            "failures": [],
            "forced": force,
        }
    return supervisor.stop_all(force=force)


def _schedule_process_shutdown() -> None:
    def _terminate_self() -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Timer(0.2, _terminate_self).start()
