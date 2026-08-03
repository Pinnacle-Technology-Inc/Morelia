"""Startup reconciliation for interrupted operations and runtime ownership rows."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import inspect

from app.database import db, transaction
from app.domain.enums import (
    OperationState,
    RuntimeOwnershipState,
    SessionStatus,
    WatchdogProcessState,
)
from app.models.device_config import DeviceConfig
from app.models.operation import Operation
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.runtime_ownership import (
    ACTIVE_RUNTIME_STATES,
    RuntimeOwnershipRepository,
)
from app.services import device_configs
from app.services.operations import ACTIVE_STATES, transition_operation

_log = structlog.get_logger(__name__)

StatusProbe = Callable[[int], Mapping[str, Any]]

REQUIRED_RECONCILIATION_TABLES = frozenset(
    {"operations", "runtime_ownerships", "sessions"}
)


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    succeeded_operations: int = 0
    failed_operations: int = 0
    uncertain_operations: int = 0
    adopted_runtimes: int = 0
    stopped_runtimes: int = 0
    uncertain_runtimes: int = 0
    deferred_runtimes: int = 0
    released_orphan_sessions: int = 0


@dataclass(frozen=True, slots=True)
class _RuntimeEvidence:
    ownership: RuntimeOwnership
    status: Mapping[str, Any] | None
    matches: bool
    error: str | None = None
    mismatch: str | None = None


def reconcile_startup(
    *,
    status_probe: StatusProbe | None = None,
) -> ReconciliationSummary:
    """Resolve persisted interrupted work into succeeded, failed, or uncertain.

    This function performs no spawning. It only reconciles durable rows from
    evidence available after a backend restart.
    """
    probe = status_probe or _probe_status
    summary = ReconciliationSummary()
    evidence_by_dataflow: dict[str, _RuntimeEvidence] = {}

    released_claims = device_configs.release_expired_starting_claims()
    if released_claims:
        _log.warning(
            "startup reconcile: released expired starting device claims",
            count=released_claims,
        )

    for ownership in _active_runtime_ownerships():
        evidence = _probe_ownership(ownership, probe)
        evidence_by_dataflow[ownership.dataflow_id] = evidence
        summary = _reconcile_runtime_ownership(summary, evidence)

    for operation in _active_operations():
        summary = _reconcile_operation(summary, operation, evidence_by_dataflow)

    summary = _reconcile_orphan_sessions(summary)

    return summary


def reconcile_startup_if_tables_exist(
    *,
    status_probe: StatusProbe | None = None,
) -> ReconciliationSummary | None:
    """Run startup reconciliation only after all required tables are present."""
    if not reconciliation_tables_ready():
        return None
    return reconcile_startup(status_probe=status_probe)


def reconciliation_tables_ready() -> bool:
    """Return whether startup reconciliation can safely query current models."""
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if not REQUIRED_RECONCILIATION_TABLES.issubset(tables):
        return False
    # During `flask db upgrade`, application code can be newer than the
    # database. SQLAlchemy selects every mapped column, so table existence
    # alone is insufficient: skip reconciliation until Alembic has added all
    # columns used by the current models.
    for table_name in REQUIRED_RECONCILIATION_TABLES:
        expected = set(db.metadata.tables[table_name].columns.keys())
        present = {column["name"] for column in inspector.get_columns(table_name)}
        if not expected.issubset(present):
            return False
    return True


def _probe_status(port: int) -> Mapping[str, Any]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/status", method="GET")
    with urllib.request.urlopen(req, timeout=2) as resp:
        payload = json.loads(resp.read())
    if not isinstance(payload, Mapping):
        raise ValueError("runtime status response is not an object")
    return payload


def _active_runtime_ownerships() -> list[RuntimeOwnership]:
    return db.session.scalars(
        db.select(RuntimeOwnership)
        .where(RuntimeOwnership.state.in_(ACTIVE_RUNTIME_STATES))
        .order_by(RuntimeOwnership.started_at.desc(), RuntimeOwnership.id.desc())
    ).all()


def _active_operations() -> list[Operation]:
    return db.session.scalars(
        db.select(Operation)
        .where(Operation.state.in_(ACTIVE_STATES))
        .order_by(Operation.created_at.asc(), Operation.id.asc())
    ).all()


def _orphan_session_candidates() -> list[Session]:
    """Sessions that could be orphaned managed runtimes.

    A NULL ``runtime_port`` keeps this disjoint from ``HostSupervisor.reconcile``,
    which only rehydrates (adopts/respawns) sessions that still carry a port —
    so the two reconcilers never fight over the same session. Excluding
    ``command_in_flight`` avoids racing a live daemon mid-command.
    """
    return db.session.scalars(
        db.select(Session).where(
            Session.status.in_((SessionStatus.ACTIVE, SessionStatus.ENDING)),
            Session.runtime_port.is_(None),
            Session.command_in_flight == False,  # noqa: E712
            Session.dataflow_id.isnot(None),
        )
    ).all()


def _configs_claimed_by(session_id: int) -> list[DeviceConfig]:
    return db.session.scalars(
        db.select(DeviceConfig).where(DeviceConfig.claimed_session_id == session_id)
    ).all()


def _reconcile_orphan_sessions(summary: ReconciliationSummary) -> ReconciliationSummary:
    """Close orphaned managed sessions and free their leaked device claims.

    A daemon shutdown, or a stop whose runtime was already gone, can leave a
    session ACTIVE/ENDING with its device configs still CLAIMED — the claim then
    outlives the runtime and blocks the next session that needs the device.

    The signal is deliberately narrow to avoid touching a healthy session:
      * no live runtime owns the dataflow (``active_for_dataflow`` is None), and
      * the session still holds at least one device-config claim.
    The claim requirement excludes non-managed ``start()`` sessions (which are
    legitimately ACTIVE with a NULL port and claim nothing). This runs after the
    ownership loop above, so a STOPPING host has already settled to STOPPED.

    This is the durable recovery route that makes ``--force`` a convenience
    rather than the only escape hatch out of a stuck claim.
    """
    ownerships = RuntimeOwnershipRepository()
    for session in _orphan_session_candidates():
        if ownerships.active_for_dataflow(session.dataflow_id) is not None:
            continue  # a live/pending host owns this dataflow — not orphaned
        claimed = _configs_claimed_by(session.id)
        if not claimed:
            continue  # nothing leaked (e.g. a non-managed session)
        with transaction():
            session.status = SessionStatus.STOPPED
            session.runtime_port = None
            session.runtime_token = None
            session.command_in_flight = False
        for config in claimed:
            try:
                device_configs.release(config.id)
            except Exception as exc:
                _log.warning(
                    "startup reconcile: releasing orphaned device claim failed",
                    session_id=session.id,
                    error=type(exc).__name__,
                    message=str(exc),
                )
        summary = _inc(summary, released_orphan_sessions=1)
    return summary


def _probe_ownership(
    ownership: RuntimeOwnership,
    probe: StatusProbe,
) -> _RuntimeEvidence:
    if ownership.port is None:
        return _RuntimeEvidence(
            ownership=ownership,
            status=None,
            matches=False,
            error="runtime_port_missing",
        )

    try:
        status = probe(ownership.port)
    except Exception as exc:  # noqa: BLE001 - any failed probe is reconciliation data
        return _RuntimeEvidence(
            ownership=ownership,
            status=None,
            matches=False,
            error=type(exc).__name__,
        )

    mismatch = _identity_mismatch(ownership, status)
    return _RuntimeEvidence(
        ownership=ownership,
        status=status,
        matches=mismatch is None,
        mismatch=mismatch,
    )


def _identity_mismatch(
    ownership: RuntimeOwnership,
    status: Mapping[str, Any],
) -> str | None:
    if status.get("runtime_id") != ownership.runtime_id:
        return "runtime_id"
    if status.get("dataflow_id") != ownership.dataflow_id:
        return "dataflow_id"
    if status.get("manifest_hash") != ownership.manifest_hash:
        return "manifest_hash"
    return None


def _reconcile_runtime_ownership(
    summary: ReconciliationSummary,
    evidence: _RuntimeEvidence,
) -> ReconciliationSummary:
    ownership = evidence.ownership
    if evidence.matches:
        if ownership.state == RuntimeOwnershipState.STOPPING:
            _mark_runtime_uncertain(
                ownership,
                reason="stopping_runtime_still_live",
                status=evidence.status,
            )
            return _inc(summary, uncertain_runtimes=1)
        _mark_runtime_adopted(ownership, evidence.status)
        return _inc(summary, adopted_runtimes=1)

    if ownership.state == RuntimeOwnershipState.STOPPING and evidence.status is None:
        _mark_runtime_stopped(ownership)
        return _inc(summary, stopped_runtimes=1)

    if ownership.state == RuntimeOwnershipState.RECOVERING and evidence.status is None:
        # The HostSupervisor owns evidence collection, authenticated watchdog
        # control, hardware fencing, and retry scheduling. Preserve this row as
        # active so the DB-only startup pass cannot erase that recovery state.
        return _inc(summary, deferred_runtimes=1)

    if (
        evidence.status is None
        and ownership.state is not RuntimeOwnershipState.STOPPING
        and ownership.watchdog_id
        and ownership.watchdog_pid
        and ownership.watchdog_state
        not in {WatchdogProcessState.CRASHED, WatchdogProcessState.STOPPED}
    ):
        # HostSupervisor.reconcile() runs immediately after this DB-only pass.
        # Keep the active ownership visible so its adoption-hint branch can
        # stop the old runtime row and spawn a replacement host that verifies
        # and adopts the surviving watchdog.
        _log.info(
            "startup reconcile: host unreachable but watchdog claim looks live — "
            "deferring to supervisor reconcile for adoption",
            dataflow_id=ownership.dataflow_id,
            runtime_id=ownership.runtime_id,
            watchdog_id=ownership.watchdog_id,
            watchdog_pid=ownership.watchdog_pid,
            watchdog_state=(
                ownership.watchdog_state.value if ownership.watchdog_state else None
            ),
        )
        return _inc(summary, deferred_runtimes=1)

    _mark_runtime_uncertain(
        ownership,
        reason=(
            "runtime_identity_mismatch"
            if evidence.mismatch is not None
            else "runtime_status_unreachable"
        ),
        status=evidence.status,
        error=evidence.error,
        mismatch=evidence.mismatch,
    )
    return _inc(summary, uncertain_runtimes=1)


def _reconcile_operation(
    summary: ReconciliationSummary,
    operation: Operation,
    evidence_by_dataflow: dict[str, _RuntimeEvidence],
) -> ReconciliationSummary:
    if (
        operation.state in {OperationState.QUEUED, OperationState.CLAIMED}
        and operation.dispatched_at is None
    ):
        _finish_operation(
            operation,
            OperationState.FAILED,
            error_code="interrupted_before_dispatch",
            error_message="Backend restarted before dispatch was durably recorded.",
        )
        _release_session_lock(operation, release_device_configs=True)
        return _inc(summary, failed_operations=1)

    evidence = evidence_by_dataflow.get(operation.dataflow_id)
    if operation.command == "start":
        return _reconcile_start_operation(summary, operation, evidence)
    if operation.command == "stop":
        return _reconcile_stop_operation(summary, operation)
    return _reconcile_recovery_operation(summary, operation, evidence)


def _reconcile_start_operation(
    summary: ReconciliationSummary,
    operation: Operation,
    evidence: _RuntimeEvidence | None,
) -> ReconciliationSummary:
    if (
        evidence is not None
        and evidence.matches
        and evidence.status is not None
        and evidence.status.get("phase") == "running"
    ):
        _finish_operation(operation, OperationState.SUCCEEDED)
        _release_session_lock(operation, status=SessionStatus.ACTIVE)
        return _inc(summary, succeeded_operations=1)

    error_code = (
        "runtime_identity_mismatch"
        if evidence is not None and evidence.mismatch is not None
        else "runtime_evidence_missing"
    )
    _finish_operation(
        operation,
        OperationState.UNCERTAIN,
        error_code=error_code,
        error_message="Could not prove whether interrupted start completed.",
        details=_operation_details(evidence),
    )
    _release_session_lock(operation)
    return _inc(summary, uncertain_operations=1)


def _reconcile_stop_operation(
    summary: ReconciliationSummary,
    operation: Operation,
) -> ReconciliationSummary:
    ownership = _latest_runtime_ownership(operation.dataflow_id)
    if ownership is not None and ownership.state == RuntimeOwnershipState.STOPPED:
        _finish_operation(operation, OperationState.SUCCEEDED)
        _release_session_lock(
            operation,
            status=SessionStatus.STOPPED,
            release_device_configs=True,
        )
        return _inc(summary, succeeded_operations=1)

    _finish_operation(
        operation,
        OperationState.UNCERTAIN,
        error_code="runtime_absence_not_proven",
        error_message="Could not prove the interrupted stop removed the runtime.",
    )
    _release_session_lock(operation)
    return _inc(summary, uncertain_operations=1)


def _reconcile_recovery_operation(
    summary: ReconciliationSummary,
    operation: Operation,
    evidence: _RuntimeEvidence | None,
) -> ReconciliationSummary:
    status = evidence.status if evidence is not None and evidence.matches else None
    if status is None:
        _finish_operation(
            operation,
            OperationState.UNCERTAIN,
            error_code="runtime_evidence_missing",
            error_message="Could not prove whether interrupted recovery completed.",
            details=_operation_details(evidence),
        )
        _release_session_lock(operation)
        return _inc(summary, uncertain_operations=1)

    reports = _reports_for_recovery(status, operation.recovery_id)
    if any(_explicit_failure_report(report) for report in reports):
        _finish_operation(
            operation,
            OperationState.FAILED,
            error_code="runtime_reported_failure",
            error_message="Runtime reported recovery failure.",
            details={"reports": reports},
        )
        _release_session_lock(operation)
        return _inc(summary, failed_operations=1)

    if operation.target_device_id is not None:
        if any(_target_healthy(report, operation.target_device_id) for report in reports):
            _finish_operation(operation, OperationState.SUCCEEDED)
            _release_session_lock(operation)
            return _inc(summary, succeeded_operations=1)
    elif reports and any(_all_reported_devices_healthy(report) for report in reports):
        _finish_operation(operation, OperationState.SUCCEEDED)
        _release_session_lock(operation)
        return _inc(summary, succeeded_operations=1)

    _finish_operation(
        operation,
        OperationState.UNCERTAIN,
        error_code="recovery_evidence_missing",
        error_message="Runtime status did not prove recovery success or failure.",
        details={"reports": reports},
    )
    _release_session_lock(operation)
    return _inc(summary, uncertain_operations=1)


def _finish_operation(
    operation: Operation,
    state: OperationState,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    details: dict | None = None,
) -> Operation:
    return transition_operation(
        operation.operation_id,
        state,
        error_code=error_code,
        error_message=error_message,
        details=details,
    )


def _release_session_lock(
    operation: Operation,
    *,
    status: SessionStatus | None = None,
    release_device_configs: bool = False,
) -> None:
    with transaction():
        session = db.session.get(Session, operation.session_id)
        if session is None:
            return
        session.command_in_flight = False
        if status is not None:
            session.status = status
        flows = list(session.device_flows or []) if release_device_configs else []

    for flow in flows:
        if isinstance(flow, Mapping) and flow.get("device_config_id") is not None:
            try:
                device_configs.release(int(flow["device_config_id"]))
            except Exception as exc:
                _log.warning(
                    "startup reconcile: releasing device claim for interrupted "
                    "operation failed",
                    session_id=operation.session_id,
                    error=type(exc).__name__,
                    message=str(exc),
                )


def _latest_runtime_ownership(dataflow_id: str) -> RuntimeOwnership | None:
    return db.session.scalars(
        db.select(RuntimeOwnership)
        .where(RuntimeOwnership.dataflow_id == dataflow_id)
        .order_by(RuntimeOwnership.started_at.desc(), RuntimeOwnership.id.desc())
    ).first()


def _mark_runtime_adopted(
    ownership: RuntimeOwnership,
    status: Mapping[str, Any] | None,
) -> None:
    with transaction():
        now = datetime.now(UTC)
        ownership.state = RuntimeOwnershipState.ADOPTED
        ownership.last_seen_at = now
        ownership.adopted_at = ownership.adopted_at or now
        if status is not None:
            pid = status.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool):
                ownership.pid = pid


def _mark_runtime_stopped(ownership: RuntimeOwnership) -> None:
    with transaction():
        ownership.state = RuntimeOwnershipState.STOPPED
        ownership.stopped_at = datetime.now(UTC)


def _mark_runtime_uncertain(
    ownership: RuntimeOwnership,
    *,
    reason: str,
    status: Mapping[str, Any] | None = None,
    error: str | None = None,
    mismatch: str | None = None,
) -> None:
    details: dict[str, Any] = {"reason": reason}
    if status is not None:
        details["status"] = dict(status)
    if error is not None:
        details["error"] = error
    if mismatch is not None:
        details["mismatch"] = mismatch

    with transaction():
        ownership.state = RuntimeOwnershipState.UNCERTAIN
        ownership.details = details


def _operation_details(evidence: _RuntimeEvidence | None) -> dict[str, Any]:
    if evidence is None:
        return {"reason": "no_runtime_ownership"}
    details: dict[str, Any] = {}
    if evidence.status is not None:
        details["status"] = dict(evidence.status)
    if evidence.error is not None:
        details["probe_error"] = evidence.error
    if evidence.mismatch is not None:
        details["mismatch"] = evidence.mismatch
    return details


def _reports_for_recovery(
    status: Mapping[str, Any],
    recovery_id: str | None,
) -> list[dict[str, Any]]:
    reports = status.get("reports")
    if not isinstance(reports, list):
        return []
    if recovery_id is None:
        return [dict(report) for report in reports if isinstance(report, Mapping)]
    return [
        dict(report)
        for report in reports
        if isinstance(report, Mapping) and report.get("recovery_id") == recovery_id
    ]


def _explicit_failure_report(report: Mapping[str, Any]) -> bool:
    return (
        report.get("status") == "failed"
        or report.get("outcome") == "failed"
        or report.get("error_code") is not None
        or report.get("error") is not None
    )


def _target_healthy(report: Mapping[str, Any], target_device_id: str) -> bool:
    devices = report.get("devices")
    if not isinstance(devices, list):
        return False
    return any(
        isinstance(device, Mapping)
        and device.get("device_id") == target_device_id
        and device.get("stream_status") == "healthy"
        for device in devices
    )


def _all_reported_devices_healthy(report: Mapping[str, Any]) -> bool:
    devices = report.get("devices")
    if not isinstance(devices, list) or not devices:
        return False
    return all(
        isinstance(device, Mapping) and device.get("stream_status") == "healthy"
        for device in devices
    )


def _inc(summary: ReconciliationSummary, **changes: int) -> ReconciliationSummary:
    values = {
        "succeeded_operations": summary.succeeded_operations,
        "failed_operations": summary.failed_operations,
        "uncertain_operations": summary.uncertain_operations,
        "adopted_runtimes": summary.adopted_runtimes,
        "stopped_runtimes": summary.stopped_runtimes,
        "uncertain_runtimes": summary.uncertain_runtimes,
        "deferred_runtimes": summary.deferred_runtimes,
        "released_orphan_sessions": summary.released_orphan_sessions,
    }
    for key, amount in changes.items():
        values[key] += amount
    return ReconciliationSummary(**values)
