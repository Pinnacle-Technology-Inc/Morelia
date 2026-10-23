"""User acceptance oracle: Stop fails only while the session remains running.

Frozen from the 2026-09-28 user clarification, independently of the candidate:
confirmed teardown completes Stop, with warnings when output integrity is not
confirmed. Missing teardown proof must never claim completion. Executes real
SQLite persistence, receipt ingest, projections, incidents and HTTP serialization;
no hardware or process-supervision execution is claimed.
"""

from copy import deepcopy

import pytest

from app.control.orphan_teardown import AdministrativeStopEvidence
from app.database import db
from app.domain.enums import OperationState, RuntimeOwnershipState, SessionStatus
from app.models.backend_event import BackendEvent
from app.models.incident import Incident
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.services import incidents, output_finalization, sessions


def seed_run():
    session = Session(name="stop outcome acceptance", status=SessionStatus.ACTIVE,
                      dataflow_id="oracle-flow", watchdog_id="oracle-watchdog",
                      device_flows=[])
    db.session.add(session)
    db.session.flush()
    owner = RuntimeOwnership(runtime_id="oracle-runtime", session_id=session.id,
                             dataflow_id=session.dataflow_id, manifest_hash="oracle-manifest",
                             watchdog_id=session.watchdog_id, state=RuntimeOwnershipState.RUNNING)
    output = OutputFile(output_id="oracle-output", logical_sink_id="oracle-sink",
                        session_id=session.id, dataflow_id=session.dataflow_id,
                        sink_type="csv", path="never-read-oracle.csv",
                        acquisition_state="open", artifact_state="merge_pending")
    db.session.add_all([owner, output])
    db.session.commit()
    return session, owner, output


def receipt(*, teardown=True, integrity=False, reason="duration_ended"):
    return {"command_id": "oracle-stop", "stop_reason": reason,
            "requested_at": "2026-09-28T13:29:29+00:00",
            "shutdown_result": {"ok": integrity, "stream_results": [
                {"worker_exitcode": 0, "teardown_confirmed": teardown,
                 "ok": integrity, "missing_phases": [] if integrity else ["source_stopped"]}]},
            "teardown_confirmed": teardown, "output_integrity_confirmed": integrity,
            "errors": [] if integrity else ["device shutdown failed: IO_ERROR"]}


def operation():
    return db.session.scalar(db.select(Operation).where(Operation.command == "stop"))


def assert_completed(op, *, warning):
    assert op.state == OperationState.SUCCEEDED
    assert op.finished_at is not None
    assert op.error_code is None and op.error_message is None
    warnings = (op.details or {}).get("warnings", [])
    assert bool(warnings) is warning
    for item in warnings:
        assert isinstance(item["code"], str) and item["code"]
        assert isinstance(item["message"], str) and item["message"]


@pytest.mark.parametrize("reason", ["duration_ended", "user_stop", "application_shutdown"])
@pytest.mark.parametrize("integrity", [True, False])
def test_proven_stop_completes_and_exposes_only_integrity_warning(app, client, integrity, reason):
    with app.app_context():
        session, owner, output = seed_run()
        raw = receipt(integrity=integrity, reason=reason)
        sessions.apply_shutdown_result(session, raw, owner)
        op = operation()
        assert session.status == SessionStatus.COMPLETED
        assert_completed(op, warning=not integrity)
        assert owner.watchdog_exit_details == raw
        assert op.details["errors"] == raw["errors"]
        assert op.details["output_integrity_confirmed"] is integrity
        if not integrity:
            output_finalization.reconcile_completed_session_acquisitions()
            assert output.acquisition_state == "interrupted"
            assert output.artifact_state == "merge_blocked"
        assert db.session.scalar(db.select(Incident).where(Incident.status == "open")) is None
        op_id = op.operation_id
    response = client.get(f"/api/v1/operations/{op_id}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "succeeded"
    assert body["error_code"] is None and body["error_message"] is None
    assert bool(body["details"].get("warnings", [])) is (not integrity)


def test_missing_teardown_proof_does_not_claim_completed(app):
    with app.app_context():
        session, owner, _ = seed_run()
        sessions.apply_shutdown_result(session, receipt(teardown=False), owner)
        assert session.status == SessionStatus.STOPPING
        assert operation().state != OperationState.SUCCEEDED
        assert operation().details["teardown_confirmed"] is False


def test_administrative_stop_completes_with_warning_and_preserves_raw_failure(app):
    with app.app_context():
        session, owner, output = seed_run()
        raw = receipt(teardown=False)
        sessions.apply_shutdown_result(session, raw, owner)
        proof = AdministrativeStopEvidence(
            runtime_id=owner.runtime_id, watchdog_id=owner.watchdog_id,
            dataflow_id=owner.dataflow_id, manifest_hash=owner.manifest_hash,
            payload=receipt(), observations={"host": "dead", "watchdog": "dead", "leases": "free"})
        sessions.apply_administrative_stop_evidence(session, proof, owner)
        sessions.apply_administrative_stop_evidence(session, proof, owner)
        assert session.status == SessionStatus.COMPLETED
        assert_completed(operation(), warning=True)
        assert owner.watchdog_exit_details == raw
        assert operation().details["output_integrity_confirmed"] is False
        assert output.acquisition_state == "interrupted"
        assert output.artifact_state == "merge_blocked"
        assert db.session.scalar(db.select(Incident).where(Incident.status == "open")) is None


def test_replaying_legacy_failed_stop_repairs_outcome_and_resolves_incident(app, client):
    with app.app_context():
        session, owner, _ = seed_run()
        raw = receipt()
        sessions.apply_shutdown_result(session, raw, owner)
        op = operation()
        old_details = deepcopy(op.details)
        op.state = OperationState.FAILED
        op.error_code = "unclean_shutdown"
        op.error_message = raw["errors"][0]
        db.session.commit()
        incidents.evaluate_operation_failure(op)
        incident = db.session.scalar(db.select(Incident).where(Incident.status == "open"))
        assert incident is not None
        receipt_count = db.select(db.func.count()).select_from(BackendEvent).where(
            BackendEvent.event_type == "runtime.stop_finished")
        before = db.session.scalar(receipt_count)
        sessions.apply_shutdown_result(session, raw, owner)
        sessions.apply_shutdown_result(session, raw, owner)
        assert_completed(op, warning=True)
        assert incident.status == "resolved" and incident.resolved_at is not None
        assert op.details["errors"] == old_details["errors"]
        assert op.details["shutdown_result"] == old_details["shutdown_result"]
        assert op.details["stop_finished_report_id"] == old_details["stop_finished_report_id"]
        assert db.session.scalar(receipt_count) == before
        op_id = op.operation_id
    assert client.get(f"/api/v1/operations/{op_id}").get_json()["state"] == "succeeded"


def test_later_clean_receipt_completes_stop_without_erasing_earlier_integrity_failure(app):
    with app.app_context():
        session, owner, output = seed_run()
        sessions.apply_shutdown_result(session, receipt(teardown=False), owner)
        first_errors = deepcopy(operation().details["errors"])
        sessions.apply_shutdown_result(session, receipt(integrity=True), owner)
        assert session.status == SessionStatus.COMPLETED
        assert_completed(operation(), warning=True)
        assert operation().details["output_integrity_confirmed"] is False
        history = operation().details["shutdown_receipt_history"]
        assert any(row["errors"] == first_errors for row in history.values())
        assert output.acquisition_state == "interrupted"
        assert output.artifact_state == "merge_blocked"


@pytest.mark.parametrize("status,teardown,same_flow,repair", [
    (SessionStatus.COMPLETED, True, True, True),
    (SessionStatus.COMPLETED, False, True, False),
    (SessionStatus.ACTIVE, True, True, False),
    (SessionStatus.COMPLETED, True, False, False),
])
def test_legacy_backfill_is_idempotent_and_requires_current_completed_session(
        app, status, teardown, same_flow, repair):
    with app.app_context():
        session, owner, _ = seed_run()
        sessions.apply_shutdown_result(session, receipt(teardown=teardown), owner)
        op = operation()
        session.status = status
        if not same_flow:
            session.dataflow_id = "replacement-flow"
        op.state = OperationState.FAILED
        op.error_code = "unclean_shutdown"
        op.error_message = "Original receipt error"
        op.details = {key: value for key, value in op.details.items() if key != "warnings"}
        db.session.commit()
        before = deepcopy(op.details)
        original_receipt = deepcopy(owner.watchdog_exit_details)
        incidents.evaluate_operation_failure(op)
        assert sessions.reconcile_completed_stop_operations() == int(repair)
        assert sessions.reconcile_completed_stop_operations() == 0
        assert owner.watchdog_exit_details == original_receipt
        assert session.status == status
        if repair:
            assert_completed(op, warning=True)
            for key, value in before.items():
                assert op.details[key] == value
            assert db.session.scalar(db.select(Incident).where(Incident.status == "open")) is None
        else:
            assert op.state == OperationState.FAILED
            assert op.error_code == "unclean_shutdown"
