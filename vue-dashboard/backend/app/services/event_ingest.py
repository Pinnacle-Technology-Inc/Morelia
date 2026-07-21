"""Ingest pipeline: validate → resolve session → stamp UTC → persist.

Two independent pipelines live here:
- ``ingest_report``: how runtime_host report to control plane
- ``ingest_watchdog_report``: how watchdog report directly to control plane its output.
Details are in the implementation
"""

from __future__ import annotations

from collections.abc import Mapping

from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
from app.domain.errors import StaleWatchdogReport, UnknownDataflow
from app.repositories.backend_events import BackendEventRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import RuntimeReport
from app.services import gaps, incidents


def ingest_report(raw: Mapping) -> int:
    """Validate, resolve session, stamp UTC, and persist one backend_events row.

    Steps:
      1. Validate via RuntimeReport.from_dict — unknown field → ValueError, no write.
      2. Resolve session_id from dataflow_id — unknown dataflow → UnknownDataflow, no write.
      3. received_at is stamped by the BackendEvent model default (datetime.now(UTC) at insert).
      4. Flatten devices into the JSON payload; lift phase/comms/recovery_id/sequence to columns.
      5. Persist via append (idempotent on (dataflow_id, sequence)); return the event id.

    Returns the event id — new on first delivery, pre-existing on duplicate.
    """
    # Step 1: strict validation — raises ValueError on unknown or missing fields
    report = RuntimeReport.from_dict(raw)

    # Step 2: session resolution — raises UnknownDataflow if no session owns this dataflow
    session = SessionRepository().get_by_dataflow_id(report.dataflow_id)
    if session is None:
        raise UnknownDataflow(report.dataflow_id)

    # Step 3: payload carries the opaque device list; queryable fields are lifted to columns
    payload = {"devices": [device.to_dict() for device in report.devices]}
    if report.diagnostics is not None:
        payload["diagnostics"] = dict(report.diagnostics)
    # Per-sink state rides a SEPARATE payload key from ``devices`` (source health),
    # present only when the report carries sinks — the durable, idempotent record
    # of each sink's health/delivery/loss keyed by (dataflow_id, sequence).
    if report.sinks:
        payload["sinks"] = [sink.to_dict() for sink in report.sinks]

    # Step 4: idempotent persist — duplicate (dataflow_id, sequence) returns the existing id
    event_id = BackendEventRepository().append(
        event_type="runtime.report",
        session_id=session.id,
        dataflow_id=report.dataflow_id,
        sequence=report.sequence,
        payload=payload,
        recovery_id=report.recovery_id,
        phase=report.phase.value,
        comms=report.comms.value,
    )

    # Step 5: derive operator history from the report. Gaps run first so the
    # incident opened for a recovered stream is still unresolved and linkable.
    # Source-health signals (devices) and per-sink signals (sinks) are two
    # independent axes: sink evaluation never mutates source incidents/gaps, and
    # a sink-only failure leaves source running-state untouched (SINK-23). Within
    # each axis, gaps precede incidents so a gap can link to a still-open incident.
    gaps.evaluate_report(report, session_id=session.id)
    incidents.evaluate_report(report, session_id=session.id)
    gaps.evaluate_sink_reports(report, session_id=session.id)
    incidents.evaluate_sink_reports(report, session_id=session.id)

    return event_id


def ingest_watchdog_report(raw: Mapping) -> int:
    """Validate, fence staleness, and persist one direct watchdog-telemetry row.

    Steps:
      1. Validate via WatchdogTelemetryEnvelope.from_dict — unknown/missing
         field, or a non-string identifier, raises ValueError with no write.
      2. Look up the runtime's active identity via RuntimeOwnershipRepository
         — a missing runtime_id is treated the same as "no active watchdog".
      3. Fence: the envelope's watchdog_id must match the active watchdog_id
         for that runtime_id, else raise StaleWatchdogReport with no write, preventing
         a stale Watchdog from updating the status.
      4. Cross-check dataflow_id/manifest_hash against the runtime's ownership
         row — the envelope must describe the runtime it names, not merely a
         runtime_id that happens to exist.
      5. Persist via append (idempotent on report_id, not (dataflow_id,
         sequence)); return the event id.

    Returns the event id — new on first delivery, pre-existing on duplicate
    report_id.
    """
    # Step 1: strict validation — raises ValueError on unknown/missing fields
    envelope = WatchdogTelemetryEnvelope.from_dict(raw)

    # Step 2: active identity lookup — an untracked runtime_id has no active watchdog
    ownership = RuntimeOwnershipRepository().get(envelope.runtime_id)
    active_watchdog_id = ownership.watchdog_id if ownership is not None else None

    # Step 3: fence — reject a watchdog_id that is not the active one
    if active_watchdog_id != envelope.watchdog_id:
        raise StaleWatchdogReport(
            envelope.runtime_id,
            reported_watchdog_id=envelope.watchdog_id,
            active_watchdog_id=active_watchdog_id,
        )

    # Step 4: the runtime is tracked and the watchdog_id matched, so `ownership`
    # is not None here — cross-check the rest of the envelope against it
    if ownership.dataflow_id != envelope.dataflow_id:
        raise ValueError(
            f"dataflow_id {envelope.dataflow_id!r} does not match runtime "
            f"{envelope.runtime_id!r}'s active dataflow"
        )
    if ownership.manifest_hash != envelope.manifest_hash:
        raise ValueError(
            f"manifest_hash {envelope.manifest_hash!r} does not match runtime "
            f"{envelope.runtime_id!r}'s active manifest"
        )

    # Step 5: idempotent persist — duplicate report_id returns the existing id
    return BackendEventRepository().append(
        event_type=envelope.event_type,
        session_id=ownership.session_id,
        dataflow_id=envelope.dataflow_id,
        payload=dict(envelope.payload),
        runtime_id=envelope.runtime_id,
        watchdog_id=envelope.watchdog_id,
        report_id=envelope.report_id,
    )
