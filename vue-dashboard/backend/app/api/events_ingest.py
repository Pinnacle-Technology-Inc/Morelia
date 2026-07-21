"""Northbound ingest endpoint — POST /api/v1/internal/events.

Two callers share this one endpoint, distinguished by envelope shape:

- The runtime host, once per report.
- A watchdog process reporting telemetry directly.

Internal — registered directly on the Flask app, not on the OpenAPI `api`
object, so it is excluded from the generated spec.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_smorest import abort

from app.domain.errors import StaleWatchdogReport, UnknownDataflow
from app.services.event_ingest import ingest_report, ingest_watchdog_report

blp = Blueprint("events_ingest", __name__, url_prefix="/api/v1/internal")

_RUNTIME_HOST_ENVELOPE_FIELDS = frozenset({"protocol_version", "report"})
_DIRECT_ENVELOPE_FIELDS = frozenset(
    {
        "report_id",
        "session_id",
        "dataflow_id",
        "runtime_id",
        "watchdog_id",
        "manifest_hash",
        "event_type",
        "payload",
    }
)


@blp.route("/events", methods=["POST"])
def ingest_event():
    # Loopback-only — mirrors the south contract's IP restriction.
    if request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403, message="loopback only")

    # Optional token seam — checked only when INGEST_TOKEN is configured.
    expected_token = current_app.config.get("INGEST_TOKEN")
    if expected_token is not None:
        if request.headers.get("X-Agent-Token") != expected_token:
            abort(401, message="invalid or missing token")

    raw = request.get_json(silent=True, force=True)
    if raw is None or not isinstance(raw, dict):
        abort(400, message="request body must be a JSON object")

    if "report_id" in raw:
        return _ingest_direct(raw)
    return _ingest_runtime_host(raw)


def _ingest_direct(raw: dict):
    """Direct watchdog-process telemetry envelope (packet 03)."""
    unknown = set(raw) - _DIRECT_ENVELOPE_FIELDS
    if unknown:
        abort(400, message=f"unknown envelope fields: {', '.join(sorted(unknown))}")

    try:
        event_id = ingest_watchdog_report(raw)
    except ValueError as exc:
        abort(400, message=str(exc))
    except StaleWatchdogReport as exc:
        abort(409, message=str(exc))

    return jsonify({"event_id": event_id}), 202


def _ingest_runtime_host(raw: dict):
    """Runtime-host push/poll envelope: {protocol_version, report}. Currently the
    primary telemetry path — see module docstring."""
    unknown = set(raw) - _RUNTIME_HOST_ENVELOPE_FIELDS
    if unknown:
        abort(400, message=f"unknown envelope fields: {', '.join(sorted(unknown))}")

    if raw.get("protocol_version") != "1":
        abort(400, message="protocol_version must be '1'")

    if "report" not in raw:
        abort(400, message="missing required field: report")

    try:
        event_id = ingest_report(raw["report"])
    except ValueError as exc:
        abort(400, message=str(exc))
    except UnknownDataflow as exc:
        abort(404, message=str(exc))

    return jsonify({"event_id": event_id}), 202
