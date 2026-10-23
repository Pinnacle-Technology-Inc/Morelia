"""Ingest pipeline: validate → resolve session → stamp UTC → persist.

Two independent pipelines live here:
- ``ingest_report``: how runtime_host report to control plane
- ``ingest_watchdog_report``: how watchdog report directly to control plane its output.
Details are in the implementation
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import math

from app.config import get_config
from app.database import db, transaction
from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
from app.domain.duration import validate_duration_seconds
from app.domain.errors import StaleWatchdogReport, UnknownDataflow
from app.models.backend_event import BackendEvent
from app.repositories.backend_events import BackendEventRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import RuntimePhase, RuntimeReport
from app.services import gaps, incidents, operations

LIFECYCLE_EVENTS = frozenset({
    "runtime.acquisition_started",
    "runtime.recording_started", "runtime.recording_progress",
    "runtime.stop_requested", "runtime.stop_finished",
})


def _utc_timestamp(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO UTC timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _validate_lifecycle(envelope):
    """Validate evidence before inserting an event or projecting any state."""
    payload = envelope.payload
    for field in ("started_at", "ended_at"):
        if payload.get(field) is not None:
            _utc_timestamp(payload[field], field)
    bounds = payload.get("recording_bounds", [])
    if not isinstance(bounds, list):
        raise ValueError("recording_bounds must be a list")
    for bound in bounds:
        if not isinstance(bound, Mapping) or any(
            not isinstance(bound.get(key), str) or not bound[key]
            for key in ("source_id", "sink_id")
        ):
            raise ValueError("recording bounds require source_id and sink_id")
        first = _utc_timestamp(bound.get("first_sample_at"), "first_sample_at")
        last = _utc_timestamp(bound.get("last_sample_at"), "last_sample_at")
        if last < first:
            raise ValueError("last sample precedes first sample")
    anchor = payload.get("clock_anchor")
    if anchor is not None:
        if not isinstance(anchor, Mapping) or not isinstance(anchor.get("boot_id"), str):
            raise ValueError("invalid clock_anchor")
        deadline = anchor.get("deadline_elapsed")
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("invalid elapsed deadline")
    if envelope.event_type == "runtime.acquisition_started":
        _utc_timestamp(payload.get("started_at"), "started_at")
        if anchor is None:
            raise ValueError("acquisition evidence requires clock_anchor")
    elif envelope.event_type.startswith("runtime.recording_"):
        _utc_timestamp(payload.get("started_at"), "started_at")
        if not bounds:
            raise ValueError("recording evidence requires acknowledged sample bounds")
    else:
        if not isinstance(payload.get("command_id"), str) or not payload["command_id"]:
            raise ValueError("stop event requires command_id")
        if payload.get("stop_reason") not in {
            "user_stop", "duration_ended", "application_shutdown", "runtime_failure"
        }:
            raise ValueError("invalid stop_reason")
        _utc_timestamp(payload.get("requested_at"), "requested_at")
        if envelope.event_type == "runtime.stop_finished":
            if not isinstance(payload.get("shutdown_result"), Mapping):
                raise ValueError("stop_finished requires structured shutdown_result")
            for field in ("teardown_confirmed", "output_integrity_confirmed"):
                if type(payload.get(field)) is not bool:
                    raise ValueError(f"stop_finished requires boolean {field}")
            if payload["output_integrity_confirmed"] and not payload["teardown_confirmed"]:
                raise ValueError("output integrity requires teardown evidence")


def _project_recording(session, ownership, payload, *, current_producer=True):
    """Keep the first HealthSink arrival as session start and merge saved bounds."""
    from app.models.session import Session
    started = payload.get("started_at")
    bounds = payload.get("recording_bounds", [])
    if started is not None:
        origin = _utc_timestamp(started, "started_at")
        if session.duration_seconds is not None:
            validate_duration_seconds(session.duration_seconds, start_at=origin)
        db.session.execute(db.update(Session).where(
            Session.id == session.id, Session.started_at.is_(None)
        ).values(started_at=origin).execution_options(synchronize_session="fetch"))
    if bounds:
        latest = max(_utc_timestamp(b["last_sample_at"], "last_sample_at") for b in bounds)
        db.session.execute(db.update(Session).where(
            Session.id == session.id, db.or_(Session.ended_at.is_(None), Session.ended_at < latest)
        ).values(ended_at=latest).execution_options(synchronize_session="fetch"))
    details = dict(ownership.details or {})
    previous = dict(details.get("recording_state") or {})
    # Preserve the established anchor even when old outbox checkpoints arrive late.
    if not previous.get("started_at") and started:
        previous["started_at"] = started
        if payload.get("clock_anchor") is not None:
            previous["clock_anchor"] = dict(payload["clock_anchor"])
    elif (current_producer and started == previous.get("started_at")
          and payload.get("clock_anchor") is not None):
        saved_anchor = previous.get("clock_anchor") or {}
        incoming_anchor = payload["clock_anchor"]
        if saved_anchor.get("boot_id") != incoming_anchor.get("boot_id"):
            # A replacement persists its confirmed-reboot reconstruction before
            # recording. Historical outboxes cannot roll this anchor backward.
            previous["clock_anchor"] = dict(incoming_anchor)
    merged = {(b["source_id"], b["sink_id"]): dict(b) for b in previous.get("recording_bounds", [])}
    for bound in bounds:
        key = (bound["source_id"], bound["sink_id"])
        old = merged.get(key)
        if old is None:
            merged[key] = dict(bound)
        else:
            old["first_sample_at"] = min(_utc_timestamp(old["first_sample_at"], "first"),
                _utc_timestamp(bound["first_sample_at"], "first")).isoformat()
            old["last_sample_at"] = max(_utc_timestamp(old["last_sample_at"], "last"),
                _utc_timestamp(bound["last_sample_at"], "last")).isoformat()
    previous["recording_bounds"] = list(merged.values())
    last = max((_utc_timestamp(b["last_sample_at"], "last") for b in merged.values()), default=None)
    previous["ended_at"] = last.isoformat() if last else None
    details["recording_state"] = previous
    ownership.details = details


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

    if report.phase is RuntimePhase.RUNNING:
        SessionRepository().mark_active_if_starting(report.dataflow_id)

    # Step 5: derive operator history from the report. Gaps run first so the
    # incident opened for a recovered stream is still unresolved and linkable.
    # Source-health signals (devices) and per-sink signals (sinks) are two
    # independent axes: sink evaluation never mutates source incidents/gaps, and
    # a sink-only failure leaves source running-state untouched (SINK-23). Within
    # each axis, gaps precede incidents so a gap can link to a still-open incident.
    #
    # Gaps are recorded unconditionally — every healed episode is a fact about
    # missing data. Incidents are not: they open only when the report shows
    # something waiting on a person (app.services.escalation), so an automatic
    # reconnect that works leaves a gap and nothing to acknowledge. The session's
    # policy is a FALLBACK; the report's own per-stream policy wins.
    config = get_config()
    gaps.evaluate_report(report, session_id=session.id)
    incidents.evaluate_report(
        report,
        session_id=session.id,
        policy=session.policy,
        port_absent_limit_seconds=config.STREAM_PORT_ABSENT_ESCALATION_SECONDS,
    )
    gaps.evaluate_sink_reports(report, session_id=session.id)
    incidents.evaluate_sink_reports(
        report, session_id=session.id, policy=session.policy
    )
    operations.verify_recovery_report(report)

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
    lifecycle = envelope.event_type in LIFECYCLE_EVENTS
    historical = bool(lifecycle and ownership is not None and any(
        ref.get("watchdog_id") == envelope.watchdog_id
        and ref.get("runtime_id") == envelope.runtime_id
        and ref.get("dataflow_id") == envelope.dataflow_id
        and ref.get("manifest_hash") == envelope.manifest_hash
        for ref in (ownership.details or {}).get("predecessor_watchdogs", [])
    ))

    # Step 3: fence — reject a watchdog_id that is not the active one
    if active_watchdog_id != envelope.watchdog_id and not historical:
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

    if lifecycle:
        _validate_lifecycle(envelope)
        session = SessionRepository().get(ownership.session_id)
        if session is None:
            raise UnknownDataflow(envelope.dataflow_id)
        with transaction():
            event_id = BackendEventRepository().append(
                event_type=envelope.event_type, session_id=session.id,
                dataflow_id=envelope.dataflow_id, payload=dict(envelope.payload),
                runtime_id=envelope.runtime_id, watchdog_id=envelope.watchdog_id,
                report_id=envelope.report_id, commit=False,
            )
            accepted = db.session.get(BackendEvent, event_id)
            if (accepted.event_type != envelope.event_type
                    or accepted.session_id != session.id
                    or accepted.watchdog_id != envelope.watchdog_id
                    or accepted.dataflow_id != envelope.dataflow_id
                    or accepted.payload != dict(envelope.payload)):
                raise ValueError("report_id already identifies different durable evidence")
            # Adoption may rebind the same watchdog's pending outbox to its
            # new host runtime_id. Producer/session/dataflow and payload remain
            # immutable; the active ownership checks above authenticate rebinding.
            _project_recording(session, ownership, envelope.payload, current_producer=not historical)
        if envelope.event_type.startswith("runtime.stop_"):
            from app.services.sessions import reconcile_terminal_run
            reconcile_terminal_run(session.id, envelope)
        return event_id

    # Step 5: idempotent persist — duplicate report_id returns the existing id
    event_id = BackendEventRepository().append(
        event_type=envelope.event_type,
        session_id=ownership.session_id,
        dataflow_id=envelope.dataflow_id,
        payload=dict(envelope.payload),
        runtime_id=envelope.runtime_id,
        watchdog_id=envelope.watchdog_id,
        report_id=envelope.report_id,
        recovery_id=(
            envelope.payload.get("recovery_id")
            if isinstance(envelope.payload.get("recovery_id"), str)
            else None
        ),
    )

    # Direct watchdog reports remain authoritative even when the runtime host
    # is unavailable. Feed their runtime-report shape through the same incident
    # evaluator so fatal worker/sink faults cannot remain telemetry-only.
    if envelope.event_type == "runtime.report":
        try:
            sequence = int(envelope.report_id.rsplit(":", 1)[1])
            report_values = {
                "dataflow_id": envelope.dataflow_id,
                "phase": "running",
                "comms": "current",
                "devices": envelope.payload.get("devices", []),
                "sequence": sequence,
            }
            if isinstance(envelope.payload.get("recovery_id"), str):
                report_values["recovery_id"] = envelope.payload["recovery_id"]
            for optional in ("diagnostics", "sinks"):
                if optional in envelope.payload:
                    report_values[optional] = envelope.payload[optional]
            report = RuntimeReport.from_dict(report_values)
        except (ValueError, TypeError, IndexError):
            report = None
        session = SessionRepository().get(ownership.session_id)
        if report is not None and session is not None:
            SessionRepository().mark_active_if_starting(report.dataflow_id)
            config = get_config()
            # The direct watchdog path is the real-time authority while the
            # runtime-host report stream is quiet. Project the same healed gap
            # facts here, in the same gap-before-incident order as ingest_report.
            # Episode/source identities make replay across both paths idempotent.
            gaps.evaluate_report(report, session_id=session.id)
            incidents.evaluate_report(
                report,
                session_id=session.id,
                policy=session.policy,
                port_absent_limit_seconds=config.STREAM_PORT_ABSENT_ESCALATION_SECONDS,
            )
            gaps.evaluate_sink_reports(report, session_id=session.id)
            incidents.evaluate_sink_reports(
                report, session_id=session.id, policy=session.policy
            )
            operations.verify_recovery_report(report)

    return event_id
