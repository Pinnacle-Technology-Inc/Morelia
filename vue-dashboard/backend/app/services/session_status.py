"""Read-only session status aggregation — the fleet overview (6f) and the
one-shot detail snapshot (6g).

Pure business logic, no Flask imports. Both entry points fuse durable DB state
(session lifecycle, latest persisted report, operations/incidents/gaps history,
runtime ownership) with the *live* health the ``EventPoller`` owns in memory.

Health vs. phase — two different provenances:
  - ``health`` (``HealthState``) is a live property: it depends on plane→host
    reachability (``LinkStatus``), which only the poller can observe by probing.
    The caller passes it in as ``live_health`` (``dataflow_id -> HealthState``);
    when there is no live snapshot for a dataflow, health is ``None`` — we do not
    fabricate reachability from a stale persisted report.
  - ``phase`` (``RuntimePhase``) and the per-device stream states come from the
    newest ``backend_events`` row, so they stay meaningful with nothing live.

The ``suspect``-hidden rule: a ``suspect`` stream status is an in-window,
non-operator-facing state (architecture plan lines 75-77). ``health_state.derive``
already folds it into ``healthy``; ``detail`` re-applies the same fold when it
surfaces the *raw* per-device stream states, so the two views cannot disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.config import get_config
from app.control.event_poller import telemetry_freshness
from app.database import db
from app.domain.enums import HealthState, IncidentStatus, SessionStatus
from app.domain.errors import SessionNotFound
from app.models.backend_event import BackendEvent
from app.models.incident import Incident
from app.models.output_file import OutputFile
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.backend_events import BackendEventRepository
from app.repositories.incidents import IncidentRepository
from app.repositories.recovery_gaps import RecoveryGapRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.services import operations

# A session counts as "running" in the fleet tally when its lifecycle is ACTIVE
# (started, not yet ended). Lifecycle is the authority here — not liveness — so
# the count is stable even while the poller is catching up on health.
_RUNNING_STATUSES = frozenset({SessionStatus.ACTIVE})

# Cap the operation ledger surfaced in a detail snapshot so the payload stays
# bounded; newest first, so the cap drops only the oldest rows.
_OPERATIONS_LIMIT = 50

# An incident is still "open" for the sink-status axis while it is OPEN or
# ACKNOWLEDGED (ack is an annotation, not a resolution — see app.services.incidents).
_OPEN_INCIDENT_STATUSES = frozenset(
    {IncidentStatus.OPEN.value, IncidentStatus.ACKNOWLEDGED.value}
)

# Per-sink freshness markers — a SEPARATE axis from SinkHealth. ``current`` when
# the newest live report carried the sink; ``stale`` when only durable evidence
# (open incidents / output_files) exists; ``unknown`` when live sink state could
# not be loaded at all (failure-handling path).
_SINK_STATUS_CURRENT = "current"
_SINK_STATUS_STALE = "stale"
_SINK_STATUS_UNKNOWN = "unknown"

# Bounded, already-redacted per-sink diagnostic fields carried through from the
# report wire (SinkReport) — never secrets or raw samples.
_SINK_DIAGNOSTIC_FIELDS = ("failure_kind", "exception_type", "message", "last_success_seq")

_sessions = SessionRepository()
_events = BackendEventRepository()
_runtimes = RuntimeOwnershipRepository()
_incidents = IncidentRepository()
_gaps = RecoveryGapRepository()


def _health_value(
    session: Session,
    live_health: Mapping[str, HealthState] | None,
) -> str | None:
    """Live health for a session's dataflow, or None when nothing is live."""
    if not session.dataflow_id or not live_health:
        return None
    state = live_health.get(session.dataflow_id)
    return state.value if state is not None else None


def _phase_value(latest: BackendEvent | None) -> str | None:
    return latest.phase if latest is not None else None


def _latest_report(latest: BackendEvent | None) -> dict[str, object] | None:
    """Shape the newest persisted report for the snapshot."""
    if latest is None:
        return None
    payload = latest.payload or {}
    raw_devices = payload.get("devices") or []
    diagnostics = payload.get("diagnostics")
    diagnostic_streams = diagnostics.get("streams") if isinstance(diagnostics, Mapping) else []
    diagnostic_by_device = {
        stream.get("device_id"): stream
        for stream in diagnostic_streams or []
        if isinstance(stream, Mapping) and stream.get("device_id") is not None
    }
    devices = [
        _latest_report_device(device, diagnostic_by_device.get(device.get("device_id"), {}))
        for device in raw_devices
        if isinstance(device, Mapping)
    ]
    return {
        "event_id": latest.id,
        "sequence": latest.sequence,
        "phase": latest.phase,
        "comms": latest.comms,
        "recovery_id": latest.recovery_id,
        "received_at": latest.received_at,
        "devices": devices,
        "diagnostics": diagnostics,
    }


def _latest_report_device(
    device: Mapping[str, object], diagnostic: Mapping[str, object]
) -> dict[str, object | None]:
    """Project bounded watchdog recovery context onto one device row."""
    heartbeat = diagnostic.get("heartbeat")
    heartbeat = heartbeat if isinstance(heartbeat, Mapping) else {}
    recovery = diagnostic.get("recovery")
    recovery = recovery if isinstance(recovery, Mapping) else {}
    action = diagnostic.get("action")
    reason = (
        diagnostic.get("initiating_failure_reason")
        or diagnostic.get("failure_reason")
        or heartbeat.get("reason")
    )
    stage = recovery.get("status")
    pending = action in {"waiting_for_port", "waiting_for_port_release"} or stage in {
        "waiting_for_port",
        "waiting_for_port_release",
        "retry_wait",
    }
    return {
        "device_id": device.get("device_id"),
        "stream_status": device.get("stream_status"),
        "action": action,
        "reason": reason,
        "recovery_stage": stage,
        "recovery_attempt": diagnostic.get("consecutive_nonhealthy_ticks"),
        "pending_recovery": pending,
    }


def _active_runtime_view(runtimes: list[RuntimeOwnership]) -> dict[str, object | None]:
    """The newest runtime-ownership row for a session, in ANY state.

    Not filtered to "active" states like ``active_for_dataflow`` is — a
    stop-proof-missing session (UNCERTAIN) should still show its last-known
    identity. ``runtimes`` is already newest-first, so row 0 is current.
    """
    ownership = runtimes[0] if runtimes else None
    recovery = None
    if ownership is not None:
        raw_recovery = (ownership.details or {}).get("recovery")
        if isinstance(raw_recovery, Mapping):
            recovery = dict(raw_recovery)
            recovery["operator_message"] = (
                "Automatic recovery is retrying while hardware access remains blocked."
                if recovery.get("phase") == "retry_wait"
                else "Automatic runtime recovery is in progress."
            )
    return {
        "runtime_id": ownership.runtime_id if ownership is not None else None,
        "watchdog_id": ownership.watchdog_id if ownership is not None else None,
        "watchdog_state": (
            ownership.watchdog_state.value
            if ownership is not None and ownership.watchdog_state is not None
            else None
        ),
        "recovery": recovery,
    }


def _telemetry_view(session_id: int) -> dict[str, object | None]:
    """Freshness of the latest direct watchdog-process telemetry for a session.

    Same classification/thresholds the poller uses for its telemetry
    incidents (``app.control.event_poller.telemetry_freshness``), so this
    field and those incidents never disagree.
    """
    latest = _events.latest_direct_telemetry_for_session(session_id)
    config = get_config()
    return {
        "last_report_at": latest.received_at if latest is not None else None,
        "outbox_health": telemetry_freshness(
            latest,
            now=datetime.now(UTC),
            stale_after_seconds=config.WATCHDOG_TELEMETRY_STALE_AFTER_SECONDS,
            overflow_after_seconds=config.WATCHDOG_TELEMETRY_OVERFLOW_AFTER_SECONDS,
        ),
        "telemetry_diagnostics": (
            (latest.payload or {}).get("diagnostics") if latest is not None else None
        ),
    }


def _live_sinks(latest: BackendEvent | None) -> dict[tuple[object, object], Mapping]:
    """Per-sink live snapshots from the newest report, keyed by ``(source_id, sink_id)``.

    Per-sink state rides its own ``sinks`` key in the report payload, strictly
    separate from ``devices`` (source/stream health). A report predating the
    per-sink contract simply has no ``sinks`` key and yields no live snapshots.
    """
    if latest is None:
        return {}
    raw = (latest.payload or {}).get("sinks") or []
    live: dict[tuple[object, object], Mapping] = {}
    for sink in raw:
        if not isinstance(sink, Mapping):
            continue
        live[(sink.get("source_id"), sink.get("sink_id"))] = sink
    return live


def _open_sink_incidents(
    incidents: list[Incident],
) -> dict[tuple[object, object], list[Incident]]:
    """Group still-open per-sink incidents by ``(source_id, sink_id)``.

    A sink incident carries ``device_id`` = owning source AND a non-null
    ``sink_id`` (packet 21). Source incidents (``sink_id`` NULL) belong to the
    source axis and are excluded here, so a sink failure never reads as source
    failure and vice versa.
    """
    grouped: dict[tuple[object, object], list[Incident]] = {}
    for incident in incidents:
        if incident.sink_id is None:
            continue
        if incident.status not in _OPEN_INCIDENT_STATUSES:
            continue
        grouped.setdefault((incident.device_id, incident.sink_id), []).append(incident)
    return grouped


def _sink_outputs(session_id: int) -> dict[tuple[object, object], dict[str, object]]:
    """Durable per-sink output evidence from ``output_files``, keyed by identity.

    Loss counters are monotonic, so the sink's durable loss is the max across all
    of its components/logical outputs. The current finalization/delivery
    disposition comes from the newest logical output's head component
    (``segment_index == 0``). Only rows carrying a ``sink_id`` participate; a
    query failure degrades to "no durable evidence" rather than breaking status.
    """
    try:
        rows = db.session.scalars(
            db.select(OutputFile)
            .where(
                OutputFile.session_id == session_id,
                OutputFile.sink_id.is_not(None),
            )
            .order_by(OutputFile.created_at.asc(), OutputFile.id.asc())
        ).all()
    except Exception:
        return {}

    by_sink: dict[tuple[object, object], list[OutputFile]] = {}
    for row in rows:
        by_sink.setdefault((row.device_id, row.sink_id), []).append(row)

    outputs: dict[tuple[object, object], dict[str, object]] = {}
    for identity, sink_rows in by_sink.items():
        newest = sink_rows[-1]  # rows ascending by created_at
        head = next(
            (
                r
                for r in sink_rows
                if r.logical_sink_id == newest.logical_sink_id and r.segment_index == 0
            ),
            newest,
        )
        outputs[identity] = {
            "logical_sink_id": head.logical_sink_id,
            "artifact_state": head.artifact_state,
            "delivery_state": newest.delivery_state,
            "sample_loss": max((r.sample_loss or 0) for r in sink_rows),
            "byte_loss": max((r.byte_loss or 0) for r in sink_rows),
        }
    return outputs


def _sink_diagnostics(snapshot: Mapping) -> dict[str, object] | None:
    """Bounded, pre-redacted diagnostic fields from one live sink snapshot."""
    diagnostics = {
        name: snapshot[name]
        for name in _SINK_DIAGNOSTIC_FIELDS
        if snapshot.get(name) is not None
    }
    return diagnostics or None


def _sink_entry_from_snapshot(
    source_id: object,
    sink_id: object,
    snapshot: Mapping,
    last_update: object,
) -> dict[str, object]:
    """A ``current`` per-sink entry built from its live report snapshot."""
    return {
        "source_id": source_id,
        "sink_id": sink_id,
        "sink_class": snapshot.get("sink_class"),
        "status": _SINK_STATUS_CURRENT,
        "last_update": last_update,
        "health": snapshot.get("health"),
        "delivery": snapshot.get("delivery"),
        "finalization": snapshot.get("finalization"),
        "component": snapshot.get("component"),
        "buffered_samples": snapshot.get("buffered_samples"),
        "buffered_bytes": snapshot.get("buffered_bytes"),
        "sample_loss": snapshot.get("sample_loss"),
        "byte_loss": snapshot.get("byte_loss"),
        "sink_sequence": snapshot.get("sequence"),
        "diagnostics": _sink_diagnostics(snapshot),
    }


def _sink_entry_without_live(
    source_id: object,
    sink_id: object,
    status: str,
) -> dict[str, object]:
    """A per-sink entry with no live snapshot (``stale`` or ``unknown``).

    Live runtime axes are None (not fabricated); durable evidence (open
    incidents / output_files) is attached by the caller.
    """
    return {
        "source_id": source_id,
        "sink_id": sink_id,
        "sink_class": None,
        "status": status,
        "last_update": None,
        "health": None,
        "delivery": None,
        "finalization": None,
        "component": None,
        "buffered_samples": None,
        "buffered_bytes": None,
        "sample_loss": None,
        "byte_loss": None,
        "sink_sequence": None,
        "diagnostics": None,
    }


def _sink_status_view(
    session_id: int,
    latest: BackendEvent | None,
    incidents: list[Incident],
) -> list[dict[str, object]]:
    """Per-sink status, keyed by ``(source_id, sink_id)`` — separate from source health.

    Fuses three provenances kept apart: the newest report's live per-sink
    snapshot (health/delivery/buffer/loss/component/finalization), still-open
    per-sink incidents, and durable ``output_files`` finalization/delivery/loss.
    A sink present in the live report is ``current``; one known only from durable
    evidence is ``stale``; a sink whose live snapshot cannot be parsed degrades
    to ``unknown`` — never fabricated as healthy. Source status is untouched:
    this axis is never folded back into ``health``/``phase``.
    """
    live = _live_sinks(latest)
    open_incidents = _open_sink_incidents(incidents)
    outputs = _sink_outputs(session_id)

    last_update = latest.received_at if latest is not None else None
    identities = set(live) | set(open_incidents) | set(outputs)

    entries: list[dict[str, object]] = []
    for identity in identities:
        source_id, sink_id = identity
        snapshot = live.get(identity)
        if snapshot is not None:
            try:
                entry = _sink_entry_from_snapshot(
                    source_id, sink_id, snapshot, last_update
                )
            except Exception:
                # Failure handling: a malformed live snapshot yields a
                # sink-addressed unknown status rather than breaking the rest.
                entry = _sink_entry_without_live(
                    source_id, sink_id, _SINK_STATUS_UNKNOWN
                )
        else:
            entry = _sink_entry_without_live(source_id, sink_id, _SINK_STATUS_STALE)
        entry["open_incidents"] = open_incidents.get(identity, [])
        entry["output"] = outputs.get(identity)
        entries.append(entry)

    # Stable ordering so the response fixture can be frozen for downstream
    # CLI/Vue/release tests.
    entries.sort(key=lambda e: (str(e["source_id"] or ""), str(e["sink_id"] or "")))
    return entries


def fleet_overview(
    *,
    live_health: Mapping[str, HealthState] | None = None,
) -> dict[str, object]:
    """Fleet-wide overview: running tally + per-session lifecycle/health/phase (6f)."""
    sessions = _sessions.all()
    rows: list[dict[str, object]] = []
    running = 0
    for session in sessions:
        if session.status in _RUNNING_STATUSES:
            running += 1
        latest = _events.latest_for_session(session.id)
        rows.append(
            {
                "id": session.id,
                "name": session.name,
                "status": session.status,
                "phase": _phase_value(latest),
                "health": _health_value(session, live_health),
            }
        )
    return {
        "running_count": running,
        "total_count": len(sessions),
        "sessions": rows,
    }


def detail(
    session_id: int,
    *,
    live_health: Mapping[str, HealthState] | None = None,
) -> dict[str, object]:
    """One-shot detail snapshot for a session (6g).

    Aggregate join across the session row, its runtime ownership records, the
    latest persisted stream report (suspect folded away), the operation ledger,
    and the incident/recovery-gap history.

    Raises SessionNotFound when no session has that id.
    """
    session = _sessions.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)

    latest = _events.latest_for_session(session_id)
    runtimes = _runtimes.list_for_session(session_id)
    incidents = _incidents.list_for_session(session_id)
    try:
        sinks = _sink_status_view(session_id, latest, incidents)
    except Exception:
        # Failure handling: never let per-sink aggregation break the rest of
        # the session response.
        sinks = []
    return {
        "session": session,
        "health": _health_value(session, live_health),
        "phase": _phase_value(latest),
        "latest_report": _latest_report(latest),
        "runtimes": runtimes,
        "operations": operations.list_for_session(session_id, limit=_OPERATIONS_LIMIT),
        "incidents": incidents,
        "gaps": _gaps.list_for_session(session_id),
        "sinks": sinks,
        **_active_runtime_view(runtimes),
        **_telemetry_view(session_id),
    }
