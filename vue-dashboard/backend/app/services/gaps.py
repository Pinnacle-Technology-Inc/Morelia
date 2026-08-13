"""Recovery-gap creation from the ingest report stream + operator read surface.

A *recovery gap* is the output-continuity discontinuity a recovery leaves behind:
the pre-recovery segment ended somewhere, the post-recovery segment began
somewhere else, and the samples in between are lost. Like incidents, gaps are born
on the daemon side — ``event_ingest.ingest_report`` hands each report to
``evaluate_report`` — because the DB-free runtime host only pushes reports.

Confidence is always ``UNCERTAIN`` in this slice: the report wire carries no
byte/row offsets, so the plane cannot *prove* where the pre-gap segment ended or
the post-gap one resumed. (The exact-offset "confirmed" path needs the host to
report segment boundaries — deferred.)

One recovery episode (one ``recovery_id``) yields at most one gap, linked to the
incident that was open for the recovered stream and to the recovery operation.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime

from app.database import db, transaction
from app.domain.enums import GapConfidence, IncidentStatus, StreamStatus
from app.models.incident import Incident
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.models.recovery_gap import RecoveryGap
from app.output import boundaries
from app.repositories.incidents import IncidentRepository
from app.repositories.recovery_gaps import RecoveryGapRepository
from app.runtime_child.driver import DeviceReport, RuntimeReport, SinkHealth
from app.services import session_activity
from app.services.incidents import (
    SINK_DEGRADED_REASON,
    SINK_FAILED_REASON,
    STREAM_UNHEALTHY_REASON,
)

_gaps = RecoveryGapRepository()
_incidents = IncidentRepository()


def evaluate_report(report: RuntimeReport, *, session_id: int) -> None:
    """Record the recovery gap for this report's episode, once it has healed.

    Runs BEFORE ``incidents.evaluate_report`` in the ingest path so the incident
    opened for the recovered stream is still unresolved and can be linked here.
    """
    disconnect_gap = _record_disconnect_gap(report, session_id=session_id)
    if disconnect_gap is not None:
        # The physical episode is the more precise source-level account. A
        # control-plane recovery_id may be present on the same healed report;
        # do not create a second generic "stream recovered" gap for it.
        return

    recovery_id = report.recovery_id
    if recovery_id is None:
        return  # not part of a recovery episode
    if _gaps.find_by_recovery_id(recovery_id) is not None:
        return  # gap already recorded for this episode (dedup)

    operation = _recovery_operation(recovery_id)
    if operation is None or operation.target_device_id is None:
        return  # no known control-plane recovery target for this id
    device_id = operation.target_device_id
    device = _device_report(report, device_id)

    if not _recovery_healed(device):
        return

    # reason-scoped: a stream-scope recovery op failing on the SAME device would
    # also leave an open device_id-keyed incident (a different reason) — without
    # the filter, an unlucky ordering could link the gap to the wrong incident.
    incident = _incidents.find_open_for_device(
        session_id, report.dataflow_id, device_id, reason=STREAM_UNHEALTHY_REASON
    )
    details = {
        "note": "continuity cannot be proven from the report stream",
        "sequence": report.sequence,
    }
    with transaction():
        gap = _gaps.create(
            session_id=session_id,
            dataflow_id=report.dataflow_id,
            device_id=device_id,
            operation_id=operation.operation_id,
            recovery_id=recovery_id,
            incident_id=incident.incident_id if incident is not None else None,
            reason="stream recovered",
            confidence=GapConfidence.UNCERTAIN,
            details=details,
            commit=False,
        )
        _record_gap_activity(
            gap,
            summary=(
                f"{device_id} recovered; output continuity could not be proven "
                "from the runtime report."
            ),
            details=details,
        )


def _record_disconnect_gap(
    report: RuntimeReport, *, session_id: int
) -> RecoveryGap | None:
    """Persist a healed physical-disconnect episode without requiring an operation."""
    diagnostics = report.diagnostics
    if not isinstance(diagnostics, Mapping):
        return None
    streams = diagnostics.get("streams")
    if not isinstance(streams, (list, tuple)):
        return None

    for stream in streams:
        if not isinstance(stream, Mapping) or stream.get("action") != "connection_restored":
            continue
        disconnect = stream.get("disconnect")
        if not isinstance(disconnect, Mapping):
            continue
        episode_id = disconnect.get("episode_id")
        started_at = disconnect.get("started_at")
        ended_at = disconnect.get("ended_at")
        if not isinstance(episode_id, str) or not episode_id or len(episode_id) > 64:
            continue
        existing = _gaps.get(episode_id)
        if existing is not None:
            return existing
        if not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
            continue
        if not isinstance(ended_at, (int, float)) or isinstance(ended_at, bool):
            continue
        if ended_at < started_at:
            continue

        device_id = stream.get("device_id")
        incident = (
            _incidents.find_open_for_device(
                session_id,
                report.dataflow_id,
                device_id,
                reason=STREAM_UNHEALTHY_REASON,
            )
            if isinstance(device_id, str) and device_id
            else None
        )
        recording_continued = disconnect.get("recording_continued") is True
        duration = float(ended_at - started_at)
        operation = _recovery_operation(report.recovery_id) if report.recovery_id else None
        details = {
            "episode_id": episode_id,
            "duration_seconds": duration,
            "recording_continued": recording_continued,
            "missing_value": "NaN",
            "report_sequence": report.sequence,
        }
        device_label = device_id if isinstance(device_id, str) and device_id else "The stream"
        duration_label = f"{duration:g} second" + ("" if duration == 1 else "s")
        continuity = (
            "recording continued with NaN placeholders"
            if recording_continued
            else "the stream restarted and output continuity must be verified per sink"
        )
        with transaction():
            gap = _gaps.create(
                gap_id=episode_id,
                session_id=session_id,
                dataflow_id=report.dataflow_id,
                device_id=device_id if isinstance(device_id, str) else None,
                incident_id=incident.incident_id if incident is not None else None,
                operation_id=operation.operation_id if operation is not None else None,
                recovery_id=report.recovery_id,
                # This row proves a source-level time window only. File/segment
                # boundary kinds require sink output ids and offsets, which are
                # recorded separately when that evidence exists.
                boundary_kind=None,
                boundary_version=None,
                reason="physical disconnect",
                confidence=GapConfidence.UNCERTAIN,
                gap_start={"timestamp": float(started_at)},
                gap_end={"timestamp": float(ended_at)},
                details=details,
                commit=False,
            )
            session_activity.record(
                session_id=session_id,
                dataflow_id=report.dataflow_id,
                kind="gap.recorded",
                category="dataflow",
                severity="warning",
                title="Data gap recorded",
                summary=f"{device_label} was disconnected for {duration_label}; {continuity}.",
                source_type="gap",
                source_id=gap.gap_id,
                event_type="gap.recorded",
                event_payload={"gap_id": gap.gap_id},
                operation_id=gap.operation_id,
                incident_id=gap.incident_id,
                gap_id=gap.gap_id,
                recovery_id=gap.recovery_id,
                details=details,
                occurred_at=datetime.fromtimestamp(float(ended_at), tz=UTC),
                commit=False,
            )
        return gap

    return None


def _recovery_healed(device: DeviceReport | None) -> bool:
    """Decide whether the targeted stream has healed, so its gap can be recorded.

    Only a confirmed ``HEALTHY`` counts as healed — the episode is over and the gap
    is final. Everything else waits for a later report: ``SUSPECT`` is still
    in-window (not yet settled), ``UNHEALTHY`` is still broken, and ``device is
    None`` (the target absent from this report) means we cannot confirm recovery.
    """
    return device is not None and device.stream_status is StreamStatus.HEALTHY


# -- per-sink output state + recovery boundaries (ingest path) ----------------
#
# Per-sink output evidence lives on a SEPARATE axis from source/stream health:
# current delivery disposition and durable loss counters are denormalized onto
# the sink's ``output_files`` row, and a recovery boundary (SINK-18/SINK-23) is
# recorded per sink identity, never once-per-recovery-episode. Loss counters are
# monotonic; a replayed/out-of-order report never lowers them and never writes a
# second boundary for the same (recovery_id, sink) pair.


def evaluate_sink_reports(report: RuntimeReport, *, session_id: int) -> None:
    """Persist per-sink current state/loss and record per-sink recovery boundaries.

    Runs BEFORE ``incidents.evaluate_sink_reports`` in the ingest path so a sink
    boundary can still link to the sink-incident opened by an earlier report.
    """
    _persist_sink_output_state(report, session_id=session_id)
    _record_sink_boundaries(report, session_id=session_id)


def _persist_sink_output_state(report: RuntimeReport, *, session_id: int) -> None:
    """Denormalize each sink's current delivery state + durable loss onto its row.

    Updates the most-recent ``output_files`` row for the sink identity when one
    exists (file sinks always have one; service sinks that have been allocated a
    delivery row do too). Loss counters are treated as durable cumulative totals
    and clamped to a monotonic maximum, so replays and out-of-order reports are
    idempotent and can never regress a loss count. Rows are never fabricated here
    — component/row allocation is the writer/allocator's job, out of this scope.
    """
    for sink in report.sinks:
        row = _latest_output_file(report.dataflow_id, sink.sink_id)
        if row is None:
            continue
        with transaction():
            row.delivery_state = sink.delivery.value
            if sink.byte_loss > (row.byte_loss or 0):
                row.byte_loss = sink.byte_loss
            if sink.sample_loss > (row.sample_loss or 0):
                row.sample_loss = sink.sample_loss


def _record_sink_boundaries(report: RuntimeReport, *, session_id: int) -> None:
    """Record one recovery boundary per healed sink of the recovering source.

    Gated on the recovery episode having healed (the target stream is HEALTHY and
    the sink itself HEALTHY again), so a continuation/reconnect boundary is only
    written once the episode is settled. Deduped by ``(recovery_id, sink_id)`` so
    each sibling sink gets its OWN sink-addressed boundary and a repeated report
    writes none — unlike the source gap's once-per-``recovery_id`` rule.
    """
    recovery_id = report.recovery_id
    if recovery_id is None:
        return
    operation = _recovery_operation(recovery_id)
    if operation is None or operation.target_device_id is None:
        return
    target = operation.target_device_id
    if not _recovery_healed(_device_report(report, target)):
        return

    for sink in report.sinks:
        if sink.source_id != target:
            continue  # only sinks owned by the recovering source
        if sink.health is not SinkHealth.HEALTHY:
            continue  # this sink has not itself healed yet
        if _sink_boundary_recorded(session_id, recovery_id, sink.sink_id):
            continue  # already recorded for this (recovery, sink) — dedup
        row = _latest_output_file(report.dataflow_id, sink.sink_id)
        incident = _open_sink_incident(
            session_id, report.dataflow_id, sink.source_id, sink.sink_id
        )
        boundary_kind = boundaries.SEGMENTED if row is not None else boundaries.REMOTE
        details = {
            "note": "continuity cannot be proven from the report stream",
            "sink_class": sink.sink_class,
            "sample_loss": sink.sample_loss,
            "byte_loss": sink.byte_loss,
            "sink_sequence": sink.sequence,
            "report_sequence": report.sequence,
        }
        with transaction():
            gap = _gaps.create(
                session_id=session_id,
                dataflow_id=report.dataflow_id,
                device_id=sink.source_id,
                sink_id=sink.sink_id,
                operation_id=operation.operation_id,
                recovery_id=recovery_id,
                incident_id=incident.incident_id if incident is not None else None,
                output_id=row.output_id if row is not None else None,
                boundary_kind=boundary_kind,
                boundary_version=boundaries.BOUNDARY_VERSION,
                reason="sink recovered",
                confidence=GapConfidence.UNCERTAIN,
                details=details,
                commit=False,
            )
            _record_gap_activity(
                gap,
                summary=(
                    f"{sink.sink_id} recovered for {sink.source_id}; a "
                    f"{boundary_kind} boundary was recorded with "
                    f"{sink.sample_loss} reported lost samples."
                ),
                details=details,
            )


# -- helpers -----------------------------------------------------------------


def _record_gap_activity(
    gap: RecoveryGap, *, summary: str, details: Mapping[str, object]
) -> None:
    """Project a gap and its live notification inside the caller's transaction."""
    session_activity.record(
        session_id=gap.session_id,
        dataflow_id=gap.dataflow_id,
        kind="gap.recorded",
        category="dataflow",
        severity="warning",
        title="Data gap recorded",
        summary=summary,
        source_type="gap",
        source_id=gap.gap_id,
        event_type="gap.recorded",
        event_payload={"gap_id": gap.gap_id},
        operation_id=gap.operation_id,
        incident_id=gap.incident_id,
        gap_id=gap.gap_id,
        recovery_id=gap.recovery_id,
        details=details,
        commit=False,
    )


def _latest_output_file(dataflow_id: str, sink_id: str) -> OutputFile | None:
    """The most-recently created output_files row for one durable sink identity."""
    return db.session.scalars(
        db.select(OutputFile)
        .where(OutputFile.dataflow_id == dataflow_id, OutputFile.sink_id == sink_id)
        .order_by(OutputFile.id.desc())
    ).first()


def _sink_boundary_recorded(session_id: int, recovery_id: str, sink_id: str) -> bool:
    """Whether a sink-addressed gap already exists for this (recovery, sink)."""
    return db.session.scalars(
        db.select(RecoveryGap).where(
            RecoveryGap.session_id == session_id,
            RecoveryGap.recovery_id == recovery_id,
            RecoveryGap.sink_id == sink_id,
        )
    ).first() is not None


def _open_sink_incident(
    session_id: int, dataflow_id: str, source_id: str, sink_id: str
) -> Incident | None:
    """Newest still-open sink-incident for one durable sink identity, if any."""
    return db.session.scalars(
        db.select(Incident)
        .where(
            Incident.session_id == session_id,
            Incident.dataflow_id == dataflow_id,
            Incident.device_id == source_id,
            Incident.sink_id == sink_id,
            Incident.reason.in_((SINK_FAILED_REASON, SINK_DEGRADED_REASON)),
            Incident.status.in_(
                (IncidentStatus.OPEN.value, IncidentStatus.ACKNOWLEDGED.value)
            ),
        )
        .order_by(Incident.opened_at.desc())
    ).first()


def _recovery_operation(recovery_id: str) -> Operation | None:
    """The control-plane recovery operation that minted this recovery_id."""
    return db.session.scalars(
        db.select(Operation)
        .where(Operation.recovery_id == recovery_id)
        .order_by(Operation.id.desc())
    ).first()


def _device_report(report: RuntimeReport, device_id: str) -> DeviceReport | None:
    for device in report.devices:
        if device.device_id == device_id:
            return device
    return None


# -- operator-facing read surface --------------------------------------------


def list_for_session(session_id: int) -> list[RecoveryGap]:
    return _gaps.list_for_session(session_id)


def _encode_cursor(*, session_id, confidence, row: RecoveryGap) -> str:
    payload = {
        "v": 1,
        "k": "gaps",
        "t": row.created_at.isoformat() if row.created_at else None,
        "id": row.id,
        "session": session_id,
        "confidence": confidence,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _decode_cursor(cursor: str, *, session_id, confidence) -> tuple[datetime | None, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("v") != 1 or payload.get("k") != "gaps":
            raise ValueError
        if payload.get("session") != session_id or payload.get("confidence") != confidence:
            raise ValueError
        row_id = int(payload["id"])
        timestamp = payload.get("t")
        return (datetime.fromisoformat(timestamp) if timestamp else None, row_id)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid gap cursor") from exc


def list_page(
    *,
    session_id: int | None,
    confidence: str | None,
    page_size: int,
    cursor: str | None,
) -> dict:
    after = (
        _decode_cursor(cursor, session_id=session_id, confidence=confidence)
        if cursor
        else None
    )
    rows, has_more = _gaps.list_page(
        session_id=session_id,
        confidence=confidence,
        page_size=page_size,
        after=after,
    )
    return {
        "items": rows,
        "has_more": has_more,
        "next_cursor": (
            _encode_cursor(
                session_id=session_id, confidence=confidence, row=rows[-1]
            )
            if has_more and rows
            else None
        ),
    }
