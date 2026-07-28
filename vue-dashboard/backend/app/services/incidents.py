"""Incident lifecycle — opened from daemon-side signals, surfaced to operators.

The runtime host is DB-free: it only pushes ``RuntimeReport``s to the daemon's
ingest endpoint, and the daemon's own poller independently probes host liveness.
Every incident is born here, from one of these triggers:

  1. ``evaluate_report``              — a device's stream went UNHEALTHY.
  2. ``evaluate_link_status``         — control plane can't reach the host.
  3. ``evaluate_operation_failure``/``evaluate_operation_success``
                                       — a start/stop/recover command failed
                                         (or later succeeded).
  4. ``evaluate_watchdog_crash``      — the watchdog process crashed.
  5. ``evaluate_crash_loop``          — the watchdog respawn budget is exhausted.
  6. ``evaluate_stale_process``       — the watchdog's poll-observed heartbeat
                                         went stale.
  7. ``evaluate_telemetry_freshness`` — the watchdog's direct telemetry push
                                         went stale, or stale long enough to
                                         imply its outbox isn't draining.

Triggers 2 and 4-7 are called from ``app.control.event_poller``.

Dedup is keyed on (session, dataflow, device, reason): while an incident of the
SAME reason is still OPEN or ACKNOWLEDGED for that key, a fresh trigger of that
kind does not open a second. ``reason`` matters because every dataflow-scope
trigger uses ``device_id=None`` and would otherwise collide.

Each trigger auto-resolves on its own "back to normal" signal. Operator ``ack``
is an annotation in between — it does not itself resolve.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime

from app.database import db
from app.domain.enums import IncidentStatus, LinkStatus, StreamStatus
from app.domain.errors import IncidentNotFound
from app.models.incident import Incident
from app.models.operation import Operation
from app.repositories.incidents import IncidentRepository
from app.runtime_child.driver import RuntimeReport, SinkHealth, SinkReport

_repo = IncidentRepository()

STREAM_UNHEALTHY_REASON = "stream unhealthy"
HOST_UNREACHABLE_REASON = "runtime host unreachable"
WATCHDOG_CRASH_REASON = "watchdog process crash"
CRASH_LOOP_REASON = "watchdog crash loop"
STALE_PROCESS_REASON = "stale watchdog process"
STALE_TELEMETRY_REASON = "stale telemetry"
OUTBOX_OVERFLOW_REASON = "outbox overflow"
# Per-sink incident reasons. These live on a SEPARATE axis from source/stream
# health (STREAM_UNHEALTHY_REASON): a failing or degraded sink is attributed to
# exactly one sink identity and never mutates the source's stream incident.
SINK_FAILED_REASON = "sink failed"
SINK_DEGRADED_REASON = "sink degraded"
_SINK_REASONS = (SINK_FAILED_REASON, SINK_DEGRADED_REASON)


def _operation_failure_reason(command: str) -> str:
    return f"operation failed: {command}"


# -- trigger 1: per-device stream health (ingest path) -----------------------


def evaluate_report(report: RuntimeReport, *, session_id: int) -> None:
    """Open or resolve incidents implied by one report's per-device stream health."""
    for device in report.devices:
        if device.stream_status is StreamStatus.UNHEALTHY:
            _open_if_absent(report, session_id=session_id, device_id=device.device_id)
        elif device.stream_status is StreamStatus.HEALTHY:
            _resolve_if_present(report, session_id=session_id, device_id=device.device_id)
        # SUSPECT: in-window, non-operator-facing — no incident state change.


def _open_if_absent(report: RuntimeReport, *, session_id: int, device_id: str) -> None:
    if _repo.find_open_for_device(
        session_id, report.dataflow_id, device_id, reason=STREAM_UNHEALTHY_REASON
    ) is not None:
        return
    _repo.create(
        session_id=session_id,
        dataflow_id=report.dataflow_id,
        device_id=device_id,
        reason=STREAM_UNHEALTHY_REASON,
        recovery_id=report.recovery_id,
        details={"stream_status": StreamStatus.UNHEALTHY.value, "sequence": report.sequence},
    )


def _resolve_if_present(report: RuntimeReport, *, session_id: int, device_id: str) -> None:
    existing = _repo.find_open_for_device(
        session_id, report.dataflow_id, device_id, reason=STREAM_UNHEALTHY_REASON
    )
    if existing is None:
        return
    _repo.resolve(existing.incident_id, resolution="stream recovered")


# -- trigger 1b: per-sink health (ingest path) -------------------------------
#
# A dataflow report carries source/stream health (``devices``) and, on a
# strictly separate axis, per-sink state (``sinks``). Sink incidents are keyed
# by durable ``(source_id, sink_id)`` identity — stored as ``device_id`` (the
# owning source) plus the dedicated ``sink_id`` column — so packet 22 can query
# a sink's lifecycle directly, and a sink failure never masquerades as source
# health (gaps SINK-08/SINK-23). At most one sink-incident stays open per sink,
# reflecting its current health; the source's stream incident is untouched.


def evaluate_sink_reports(report: RuntimeReport, *, session_id: int) -> None:
    """Open or resolve per-sink incidents from one report's per-sink health.

    Idempotent by durable sink identity: replaying a report of the same health
    opens no second incident (open-if-absent), and a health transition resolves
    the stale-reason incident before opening the new-reason one, so a sink never
    has two open incidents at once. Source/stream health is never read or
    written here.
    """
    for sink in report.sinks:
        desired = _sink_reason_for_health(sink.health)
        # A transition (e.g. degraded -> failed, or anything -> healthy) resolves
        # every OTHER open sink-incident for this exact sink, keeping at most one
        # open and making replays/out-of-order same-state reports no-ops.
        for reason in _SINK_REASONS:
            if reason == desired:
                continue
            existing = _find_open_for_sink(
                session_id, report.dataflow_id, sink.source_id, sink.sink_id, reason
            )
            if existing is not None:
                resolution = "sink recovered" if desired is None else "sink health changed"
                _repo.resolve(existing.incident_id, resolution=resolution)
        if desired is None:
            continue  # HEALTHY sink — nothing to open
        if _find_open_for_sink(
            session_id, report.dataflow_id, sink.source_id, sink.sink_id, desired
        ) is not None:
            continue  # already open for this reason — dedup
        _repo.create(
            session_id=session_id,
            dataflow_id=report.dataflow_id,
            device_id=sink.source_id,
            sink_id=sink.sink_id,
            recovery_id=report.recovery_id,
            reason=desired,
            details=_sink_incident_details(sink, report),
        )


def _sink_reason_for_health(health: SinkHealth) -> str | None:
    if health is SinkHealth.FAILED:
        return SINK_FAILED_REASON
    if health is SinkHealth.DEGRADED:
        return SINK_DEGRADED_REASON
    return None  # HEALTHY


def _find_open_for_sink(
    session_id: int,
    dataflow_id: str,
    source_id: str,
    sink_id: str,
    reason: str,
) -> Incident | None:
    """Newest unresolved incident for one durable sink identity + reason.

    Keys on the ``sink_id`` column (plus ``device_id`` = owning source), never on
    the source-stream dedup path, so sink and source incidents cannot collide.
    """
    query = db.select(Incident).where(
        Incident.session_id == session_id,
        Incident.dataflow_id == dataflow_id,
        Incident.device_id == source_id,
        Incident.sink_id == sink_id,
        Incident.reason == reason,
        Incident.status.in_(
            (IncidentStatus.OPEN.value, IncidentStatus.ACKNOWLEDGED.value)
        ),
    )
    return db.session.scalars(query.order_by(Incident.opened_at.desc())).first()


def _sink_incident_details(sink: SinkReport, report: RuntimeReport) -> dict:
    """Bounded, already-redacted per-sink diagnostics for the incident row.

    Only carries the wire's redacted fields (message <= 500 chars, no secrets, no
    raw samples). ``sink_sequence`` records the per-sink ordering marker distinct
    from the enclosing report ``sequence``.
    """
    details: dict = {
        "sink_id": sink.sink_id,
        "source_id": sink.source_id,
        "sink_class": sink.sink_class,
        "health": sink.health.value,
        "delivery": sink.delivery.value,
        "sample_loss": sink.sample_loss,
        "byte_loss": sink.byte_loss,
        "sink_sequence": sink.sequence,
        "report_sequence": report.sequence,
    }
    if sink.component is not None:
        details["component"] = sink.component
    if sink.finalization is not None:
        details["finalization"] = sink.finalization.value
    for name in ("failure_kind", "exception_type", "message", "last_success_seq"):
        value = getattr(sink, name)
        if value is not None:
            details[name] = value
    return details


# -- trigger 2: control-plane <-> host reachability (poller path) ------------


def evaluate_link_status(session_id: int, dataflow_id: str, link_status: LinkStatus) -> None:
    """Open/resolve a dataflow-level incident from control-plane reachability.

    Only UNREACHABLE opens one — DELAYED is staleness-but-still-talking, not one
    of the audit's incident triggers. ``device_id`` is None: an unreachable host
    is a whole-dataflow problem, not one stream's.
    """
    if link_status is LinkStatus.UNREACHABLE:
        if _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=HOST_UNREACHABLE_REASON
        ) is not None:
            return
        _repo.create(
            session_id=session_id,
            dataflow_id=dataflow_id,
            device_id=None,
            reason=HOST_UNREACHABLE_REASON,
            details={"link_status": LinkStatus.UNREACHABLE.value},
        )
    elif link_status is LinkStatus.REACHABLE:
        existing = _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=HOST_UNREACHABLE_REASON
        )
        if existing is not None:
            _repo.resolve(existing.incident_id, resolution="runtime host reachable")


# -- watchdog-process supervision (poller path, live /status) ---


def evaluate_watchdog_crash(session_id: int, dataflow_id: str, *, crashed: bool) -> None:
    """Open/resolve a dataflow-level incident from watchdog_state == CRASHED.

    Resolves once the watchdog is running again (fresh respawn or adoption).
    """
    if crashed:
        if _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=WATCHDOG_CRASH_REASON
        ) is not None:
            return
        _repo.create(
            session_id=session_id,
            dataflow_id=dataflow_id,
            device_id=None,
            reason=WATCHDOG_CRASH_REASON,
            details={"watchdog_state": "crashed"},
        )
    else:
        existing = _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=WATCHDOG_CRASH_REASON
        )
        if existing is not None:
            _repo.resolve(existing.incident_id, resolution="watchdog process running again")


def evaluate_crash_loop(session_id: int, dataflow_id: str, *, respawn_exhausted: bool) -> None:
    """Open/resolve an incident once the watchdog respawn budget is exhausted.

    Resolves once a fresh runtime reports a non-exhausted budget again.
    """
    if respawn_exhausted:
        if _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=CRASH_LOOP_REASON
        ) is not None:
            return
        _repo.create(
            session_id=session_id,
            dataflow_id=dataflow_id,
            device_id=None,
            reason=CRASH_LOOP_REASON,
            details={"respawn_exhausted": True},
        )
    else:
        existing = _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=CRASH_LOOP_REASON
        )
        if existing is not None:
            _repo.resolve(existing.incident_id, resolution="fresh respawn budget")


# -- watchdog heartbeat staleness (poller path, durable state) ----


def evaluate_stale_process(session_id: int, dataflow_id: str, *, stale: bool) -> None:
    """Open/resolve an incident from watchdog heartbeat staleness (poll-observed).

    Distinct from telemetry freshness (trigger 7): this tracks
    ``RuntimeOwnership.watchdog_last_seen_at``, reconciled from polling
    runtime_host's ``/status`` — separate from the watchdog's own direct push
    to the ingest endpoint, which can keep working even if runtime_host wedges.
    """
    if stale:
        if _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=STALE_PROCESS_REASON
        ) is not None:
            return
        _repo.create(
            session_id=session_id,
            dataflow_id=dataflow_id,
            device_id=None,
            reason=STALE_PROCESS_REASON,
            details={"signal": "watchdog_last_seen_at"},
        )
    else:
        existing = _repo.find_open_for_device(
            session_id, dataflow_id, None, reason=STALE_PROCESS_REASON
        )
        if existing is not None:
            _repo.resolve(existing.incident_id, resolution="watchdog heartbeat current again")


# -- trigger 7: direct watchdog-telemetry freshness (poller path, durable) ---


def evaluate_telemetry_freshness(session_id: int, dataflow_id: str, *, freshness: str) -> None:
    """Open/resolve incidents from direct watchdog-telemetry freshness.

    ``freshness`` is "current"/"stale"/"overflow"/"unknown" — see
    ``app.control.event_poller.telemetry_freshness``, the same classification
    session_status's ``outbox_health`` field uses. "overflow" resolves the
    milder "stale" incident rather than leaving both open; "unknown"/"current"
    resolve both.
    """
    stale_open = _repo.find_open_for_device(
        session_id, dataflow_id, None, reason=STALE_TELEMETRY_REASON
    )
    overflow_open = _repo.find_open_for_device(
        session_id, dataflow_id, None, reason=OUTBOX_OVERFLOW_REASON
    )

    if freshness == "overflow":
        if overflow_open is None:
            _repo.create(
                session_id=session_id,
                dataflow_id=dataflow_id,
                device_id=None,
                reason=OUTBOX_OVERFLOW_REASON,
                details={"freshness": freshness},
            )
        if stale_open is not None:
            _repo.resolve(stale_open.incident_id, resolution="escalated to outbox overflow")
    elif freshness == "stale":
        if stale_open is None:
            _repo.create(
                session_id=session_id,
                dataflow_id=dataflow_id,
                device_id=None,
                reason=STALE_TELEMETRY_REASON,
                details={"freshness": freshness},
            )
        if overflow_open is not None:
            _repo.resolve(overflow_open.incident_id, resolution="telemetry resumed")
    else:  # "current" or "unknown" — telemetry is fine, or there is nothing to judge yet
        if stale_open is not None:
            _repo.resolve(stale_open.incident_id, resolution="telemetry current again")
        if overflow_open is not None:
            _repo.resolve(overflow_open.incident_id, resolution="telemetry current again")


# -- trigger 3: durable operation outcome (operations path) ------------------


def evaluate_operation_failure(operation: Operation) -> None:
    """Open a device/dataflow-scope incident when a durable operation fails.

    ``device_id`` mirrors the operation's own scope: None for dataflow-scope
    commands (start/stop/restart-all-streams), the targeted stream for recovery
    commands. Dedup keys on (session, dataflow, device, command) via the reason
    string, so a failed "start" and a failed "reconnect" on the same stream are
    tracked as distinct problems, and repeated failures of the SAME command
    don't stack duplicate incidents.
    """
    reason = _operation_failure_reason(operation.command)
    if _repo.find_open_for_device(
        operation.session_id, operation.dataflow_id, operation.target_device_id, reason=reason
    ) is not None:
        return
    _repo.create(
        session_id=operation.session_id,
        dataflow_id=operation.dataflow_id,
        device_id=operation.target_device_id,
        operation_id=operation.operation_id,
        recovery_id=operation.recovery_id,
        reason=reason,
        details={"error_code": operation.error_code, "error_message": operation.error_message},
    )


def evaluate_operation_success(operation: Operation) -> None:
    """Resolve a previously open failed-op incident once the same command succeeds.

    Mirrors the auto-resolve pattern on the other two triggers: a retried
    start/stop/recover that succeeds closes the loop without operator action.
    """
    reason = _operation_failure_reason(operation.command)
    existing = _repo.find_open_for_device(
        operation.session_id, operation.dataflow_id, operation.target_device_id, reason=reason
    )
    if existing is not None:
        _repo.resolve(existing.incident_id, resolution=f"{operation.command} succeeded")


# -- operator-facing read/ack surface ----------------------------------------


def list_for_session(session_id: int, *, status: IncidentStatus | None = None) -> list[Incident]:
    return _repo.list_for_session(session_id, status=status)


def _encode_cursor(*, session_id, status, row: Incident) -> str:
    """Opaque bookmark for the next page: last row position + the filters used."""
    payload = {
        "v": 1,
        "k": "incidents",
        "t": row.opened_at.isoformat() if row.opened_at else None,
        "id": row.id,
        "session": session_id,
        "status": status.value if isinstance(status, IncidentStatus) else status,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, session_id, status) -> tuple[datetime | None, int]:
    """Unpack a cursor into (opened_at, id); reject ones from a different filter set."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("v") != 1 or payload.get("k") != "incidents":
            raise ValueError
        # Cursor is bound to the query that produced it — don't resume under different filters.
        if payload.get("session") != session_id or payload.get("status") != (
            status.value if isinstance(status, IncidentStatus) else status
        ):
            raise ValueError
        row_id = int(payload["id"])
        timestamp = payload.get("t")
        return (datetime.fromisoformat(timestamp) if timestamp else None, row_id)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid incident cursor") from exc


def list_page(*, session_id: int | None, status: IncidentStatus | None, page_size: int, cursor: str | None) -> dict:
    """Return one page of incidents; pass next_cursor back as cursor to continue."""
    after = _decode_cursor(cursor, session_id=session_id, status=status) if cursor else None
    rows, has_more = _repo.list_page(session_id=session_id, status=status, page_size=page_size, after=after)
    return {
        "items": rows,
        "has_more": has_more,
        "next_cursor": (
            _encode_cursor(session_id=session_id, status=status, row=rows[-1])
            if has_more and rows
            else None
        ),
    }


def get(incident_id: str) -> Incident:
    incident = _repo.get(incident_id)
    if incident is None:
        raise IncidentNotFound(incident_id)
    return incident


def acknowledge(
    incident_id: str,
    *,
    acknowledged_by: str | None = None,
    note: str | None = None,
) -> Incident:
    get(incident_id)  # raise IncidentNotFound before the repo's KeyError path
    return _repo.acknowledge(incident_id, acknowledged_by=acknowledged_by, note=note)
