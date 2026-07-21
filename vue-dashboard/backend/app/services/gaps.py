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
    _gaps.create(
        session_id=session_id,
        dataflow_id=report.dataflow_id,
        device_id=device_id,
        operation_id=operation.operation_id,
        recovery_id=recovery_id,
        incident_id=incident.incident_id if incident is not None else None,
        reason="stream recovered",
        confidence=GapConfidence.UNCERTAIN,
        details={
            "note": "continuity cannot be proven from the report stream",
            "sequence": report.sequence,
        },
    )


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
        _gaps.create(
            session_id=session_id,
            dataflow_id=report.dataflow_id,
            device_id=sink.source_id,
            sink_id=sink.sink_id,
            operation_id=operation.operation_id,
            recovery_id=recovery_id,
            incident_id=incident.incident_id if incident is not None else None,
            output_id=row.output_id if row is not None else None,
            boundary_kind=(boundaries.SEGMENTED if row is not None else boundaries.REMOTE),
            boundary_version=boundaries.BOUNDARY_VERSION,
            reason="sink recovered",
            confidence=GapConfidence.UNCERTAIN,
            details={
                "note": "continuity cannot be proven from the report stream",
                "sink_class": sink.sink_class,
                "sample_loss": sink.sample_loss,
                "byte_loss": sink.byte_loss,
                "sink_sequence": sink.sequence,
                "report_sequence": report.sequence,
            },
        )


# -- helpers -----------------------------------------------------------------


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
