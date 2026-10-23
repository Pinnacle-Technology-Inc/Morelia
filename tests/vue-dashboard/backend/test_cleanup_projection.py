"""SQLite acceptance checks: teardown proof never implies healthy samples."""
from datetime import UTC, datetime, timedelta
import os
import subprocess
import sys

import pytest
from structlog.contextvars import bound_contextvars

from app.control.orphan_teardown import AdministrativeStopEvidence
from app.control.orphan_teardown import ownership_teardown_confirmed
from app.database import create_database_app, db
from app.domain.enums import DeviceClaimState, DeviceType, OperationState, RuntimeOwnershipState, SessionStatus
from app.models.backend_event import BackendEvent
from app.models.device_config import DeviceConfig
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.services import sessions
from app.services.reconciliation import reconcile_startup


@pytest.fixture
def database(tmp_path):
    app = create_database_app("testing", {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'projection.sqlite3'}"})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.engine.dispose()


def run(*, claim=True, state=RuntimeOwnershipState.UNCERTAIN):
    session = Session(name="cleanup", status=SessionStatus.STOPPING, dataflow_id="flow",
                      watchdog_id="watchdog", device_flows=[], command_in_flight=False)
    db.session.add(session)
    db.session.flush()
    owner = RuntimeOwnership(runtime_id="runtime", session_id=session.id,
                             dataflow_id="flow", manifest_hash="manifest", watchdog_id="watchdog",
                             state=state, details={"pending_stop_request": {"command_id": "original"}})
    db.session.add(owner)
    config = None
    if claim:
        config = DeviceConfig(device_type=DeviceType.POD8206HR, hardware_id="hw", port="COM1",
                              claim_state=DeviceClaimState.CLAIMED, claimed_session_id=session.id)
        db.session.add(config)
        db.session.flush()
        session.device_flows = [{"device_config_id": config.id}]
    db.session.commit()
    return session, owner, config


def receipt(*, teardown=False):
    return {"command_id": "original", "stop_reason": "duration_ended",
            "requested_at": "2026-09-25T12:00:00+00:00", "shutdown_result": {"ok": False},
            "teardown_confirmed": teardown, "output_integrity_confirmed": False,
            "errors": ["sink flush failed"]}


def proof(owner):
    return AdministrativeStopEvidence(
        runtime_id=owner.runtime_id, watchdog_id=owner.watchdog_id,
        dataflow_id=owner.dataflow_id, manifest_hash=owner.manifest_hash,
        payload=receipt(teardown=True), observations={"host": "dead", "watchdog": "dead", "leases": "free"},
    )


def test_negative_receipt_stop_retries_and_preserves_original_identity(database):
    session, owner, config = run()
    sessions.apply_shutdown_result(session, receipt(), owner)
    operation = db.session.scalar(db.select(Operation))
    report_id = operation.details["stop_finished_report_id"]
    calls = []

    class Supervisor:
        def stop(self, current, *, envelope):
            calls.append(envelope.correlation.command_id)
            evidence = proof(owner)
            # The real supervisor persists administrative proof under its
            # hardware lease before returning it to the command caller.
            sessions.apply_administrative_stop_evidence(current, evidence, owner)
            return evidence

    with bound_contextvars(request_id="retry-stop"):
        sessions.stop_managed(session.id, Supervisor())
    assert calls == ["original"]
    assert operation.command_id == "original"
    assert operation.details["stop_reason"] == "duration_ended"
    assert operation.details["stop_finished_report_id"] == report_id
    assert operation.details["errors"] == ["sink flush failed"]
    assert operation.state == OperationState.SUCCEEDED
    assert config.claim_state == DeviceClaimState.FREE
    assert session.status == SessionStatus.COMPLETED


def test_administrative_projection_replay_preserves_receipt_and_blocks_outputs(database):
    session, owner, config = run()
    output = OutputFile(session_id=session.id, output_id="output", logical_sink_id="sink",
                        dataflow_id="flow", sink_type="csv", path="component.csv",
                        acquisition_state="open", artifact_state="merge_pending")
    db.session.add(output)
    db.session.commit()
    sessions.apply_shutdown_result(session, receipt(), owner)
    operation = db.session.scalar(db.select(Operation))
    original = dict(owner.watchdog_exit_details)
    receipt_count = db.select(db.func.count()).select_from(BackendEvent).where(
        BackendEvent.event_type == "runtime.stop_finished")
    reports = db.session.scalar(receipt_count)
    evidence = proof(owner)
    sessions.apply_administrative_stop_evidence(session, evidence, owner)
    sessions.apply_administrative_stop_evidence(session, evidence, owner)
    assert owner.watchdog_exit_details == original
    assert db.session.scalar(receipt_count) == reports
    assert operation.details["administrative_stop_evidence"]["observations"] == evidence.observations
    assert operation.details["output_integrity_confirmed"] is False
    assert operation.details["errors"] == original["errors"]
    assert output.acquisition_state == "interrupted"
    assert output.artifact_state == "merge_blocked"
    assert output.termination_reason == "forced"
    assert session.started_at is None and session.ended_at is None
    assert config.claimed_session_id is None


def test_historical_administrative_proof_cannot_stop_newer_owner(database):
    session, owner, config = run()
    newer = RuntimeOwnership(runtime_id="newer", session_id=session.id, dataflow_id="flow",
                             manifest_hash="manifest", watchdog_id="new-watchdog",
                             state=RuntimeOwnershipState.RUNNING,
                             started_at=datetime.now(UTC) + timedelta(seconds=1))
    session.status = SessionStatus.ACTIVE
    session.runtime_port = 51111
    session.command_in_flight = True
    db.session.add(newer)
    db.session.commit()
    sessions.apply_administrative_stop_evidence(session, proof(owner), owner)
    assert newer.state == RuntimeOwnershipState.RUNNING
    assert session.status == SessionStatus.ACTIVE
    assert session.runtime_port == 51111 and session.command_in_flight is True
    assert config.claimed_session_id == session.id
    assert owner.state == RuntimeOwnershipState.STOPPED
    operation = db.session.scalar(db.select(Operation))
    assert "historical_administrative_stop_evidence" in operation.details
    assert "stop_finished_report_id" not in operation.details


@pytest.mark.parametrize("administrative", [True, False])
@pytest.mark.parametrize("latest_administrative", [True, False])
def test_historical_exact_proof_converges_after_latest_receipt_replay(database, administrative, latest_administrative):
    session, latest, config = run()
    older = RuntimeOwnership(runtime_id="older", session_id=session.id, dataflow_id="flow",
                             manifest_hash="manifest", watchdog_id="older-watchdog",
                             state=RuntimeOwnershipState.UNCERTAIN, watchdog_exit_details=receipt(),
                             started_at=datetime.now(UTC) - timedelta(minutes=1))
    db.session.add(older)
    db.session.commit()
    positive = receipt(teardown=True)
    if latest_administrative:
        sessions.apply_administrative_stop_evidence(session, proof(latest), latest)
    else:
        sessions.apply_shutdown_result(session, positive, latest)
    operation = db.session.scalar(db.select(Operation))
    outcome = operation.state
    assert session.status == SessionStatus.STOPPING
    assert config.claimed_session_id == session.id
    if administrative:
        sessions.apply_administrative_stop_evidence(session, proof(older), older)
        assert older.watchdog_exit_details == receipt()
        assert older.details["administrative_stop_evidence"]["watchdog_id"] == "older-watchdog"
    else:
        sessions.apply_shutdown_result(session, positive, older)
        assert older.watchdog_exit_details == positive
    assert older.state == RuntimeOwnershipState.STOPPED
    assert session.status == SessionStatus.STOPPING
    assert operation.state == outcome
    assert config.claimed_session_id == session.id
    if latest_administrative:
        sessions.apply_administrative_stop_evidence(session, proof(latest), latest)
    else:
        sessions.apply_shutdown_result(session, positive, latest)
    assert session.status == SessionStatus.COMPLETED
    assert config.claimed_session_id is None


@pytest.mark.parametrize("administrative", [True, False])
def test_stale_watchdog_on_reused_runtime_cannot_retire_current_owner(database, administrative):
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    session, owner, config = run()
    stale = proof(owner)
    owner.watchdog_id = "replacement-watchdog"
    session.status = SessionStatus.ACTIVE
    db.session.commit()
    if administrative:
        sessions.apply_administrative_stop_evidence(session, stale, owner)
    else:
        sessions.reconcile_terminal_run(session.id, WatchdogTelemetryEnvelope(
            report_id="old-report", event_type="runtime.stop_finished", payload=receipt(teardown=True),
            runtime_id=owner.runtime_id, watchdog_id=stale.watchdog_id,
            dataflow_id=owner.dataflow_id, manifest_hash=owner.manifest_hash,
        ))
    assert owner.state == RuntimeOwnershipState.UNCERTAIN
    assert owner.watchdog_exit_details is None
    assert session.status == SessionStatus.ACTIVE
    assert config.claimed_session_id == session.id


def test_reconciliation_attempts_older_owner_when_latest_receipt_is_held(database):
    session, latest, config = run()
    latest.watchdog_exit_details = receipt(teardown=True)
    older = RuntimeOwnership(runtime_id="older", session_id=session.id, dataflow_id="flow",
                             manifest_hash="manifest", watchdog_id="older-watchdog",
                             state=RuntimeOwnershipState.UNCERTAIN,
                             started_at=datetime.now(UTC) - timedelta(minutes=1))
    db.session.add(older)
    db.session.commit()
    calls = []

    class Supervisor:
        def reconcile_teardown(self, current, owner):
            calls.append(owner.runtime_id)
            sessions.apply_administrative_stop_evidence(current, proof(owner), owner)

    reconcile_startup(status_probe=lambda _: {}, supervisor=Supervisor())
    assert calls == [older.runtime_id]
    assert session.status == SessionStatus.STOPPING
    reconcile_startup(status_probe=lambda _: {}, supervisor=Supervisor())
    assert calls == [older.runtime_id]
    assert session.status == SessionStatus.COMPLETED
    assert config.claimed_session_id is None


def test_stop_with_all_owners_labeled_stopped_keeps_unproven_older_claim(database):
    session, latest, config = run(state=RuntimeOwnershipState.STOPPED)
    older = RuntimeOwnership(runtime_id="older", session_id=session.id, dataflow_id="flow",
                             manifest_hash="manifest", watchdog_id="older-watchdog",
                             state=RuntimeOwnershipState.STOPPED,
                             started_at=datetime.now(UTC) - timedelta(minutes=1))
    latest.watchdog_exit_details = receipt(teardown=True)
    db.session.add(older)
    db.session.commit()

    class Supervisor:
        def stop(self, current, *, envelope):
            assert envelope.correlation.runtime_id == latest.runtime_id
            return receipt(teardown=True)

    with bound_contextvars(request_id="stopped-owner-retry"):
        sessions.stop_managed(session.id, Supervisor())
    assert session.status == SessionStatus.STOPPING
    assert config.claimed_session_id == session.id
    assert older.watchdog_exit_details is None


@pytest.mark.parametrize("administrative", [True, False])
@pytest.mark.parametrize("previous_state", [RuntimeOwnershipState.UNCERTAIN, RuntimeOwnershipState.STOPPED])
def test_latest_owner_proof_cannot_release_older_unproven_producer(database, administrative, previous_state):
    session, owner, config = run()
    previous = RuntimeOwnership(runtime_id="previous", session_id=session.id, dataflow_id="flow",
                                manifest_hash="manifest", watchdog_id="previous-watchdog",
                                state=previous_state,
                                started_at=datetime.now(UTC) - timedelta(minutes=1))
    db.session.add(previous)
    db.session.commit()
    if administrative:
        sessions.apply_administrative_stop_evidence(session, proof(owner), owner)
        assert ownership_teardown_confirmed(owner)
        assert owner.state == RuntimeOwnershipState.STOPPED
    else:
        sessions.apply_shutdown_result(session, receipt(teardown=True), owner)
    assert session.status == SessionStatus.STOPPING
    assert config.claimed_session_id == session.id
    assert previous.state == previous_state


def test_replay_does_not_release_device_reassigned_to_another_session(database):
    session, owner, config = run()
    sessions.apply_administrative_stop_evidence(session, proof(owner), owner)
    other = Session(name="other", status=SessionStatus.ACTIVE, device_flows=[])
    db.session.add(other)
    db.session.flush()
    config.claimed_session_id = other.id
    config.claim_state = DeviceClaimState.CLAIMED
    db.session.commit()
    sessions.apply_administrative_stop_evidence(session, proof(owner), owner)
    assert config.claimed_session_id == other.id
    assert config.claim_state == DeviceClaimState.CLAIMED


def test_later_clean_receipt_cannot_upgrade_administrative_integrity_failure(database):
    session, owner, _ = run()
    sessions.apply_administrative_stop_evidence(session, proof(owner), owner)
    clean = receipt(teardown=True) | {"output_integrity_confirmed": True, "errors": []}
    sessions.apply_shutdown_result(session, clean, owner)
    operation = db.session.scalar(db.select(Operation))
    assert operation.state == OperationState.SUCCEEDED
    assert operation.details["output_integrity_confirmed"] is False
    assert operation.error_code is None
    assert operation.details["warnings"][0]["code"] == "unclean_shutdown"


def test_delayed_negative_receipt_cannot_revoke_administrative_teardown(database):
    session, owner, config = run()
    sessions.apply_administrative_stop_evidence(session, proof(owner), owner)
    negative = receipt()
    sessions.apply_shutdown_result(session, negative, owner)
    operation = db.session.scalar(db.select(Operation))
    assert operation.details["teardown_confirmed"] is True
    assert operation.details["output_integrity_confirmed"] is False
    assert operation.state == OperationState.SUCCEEDED
    assert owner.state == RuntimeOwnershipState.STOPPED
    assert owner.watchdog_exit_details == negative
    assert session.status == SessionStatus.COMPLETED
    assert config.claimed_session_id is None


@pytest.mark.parametrize("state", [RuntimeOwnershipState.UNCERTAIN, RuntimeOwnershipState.STOPPING])
def test_no_port_no_claim_managed_session_is_selected_and_deferred(database, state):
    session, owner, _ = run(claim=False, state=state)
    assert SessionRepository().with_runtime_host_identity() == [session]
    summary = reconcile_startup(status_probe=lambda _: pytest.fail("no port to probe"))
    assert session.status == SessionStatus.STOPPING
    assert owner.state in {RuntimeOwnershipState.UNCERTAIN, RuntimeOwnershipState.STOPPING}
    assert summary.stopped_runtimes == 0


def test_unresolved_expired_startup_claim_is_not_swept(database):
    session, owner, config = run()
    config.claim_state = DeviceClaimState.STARTING
    config.claim_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.session.commit()
    summary = reconcile_startup(status_probe=lambda _: {})
    assert config.claimed_session_id == session.id
    assert config.claim_state == DeviceClaimState.STARTING
    assert session.status == SessionStatus.STOPPING
    assert owner.details["pending_stop_request"]["command_id"] == "original"
    assert summary.released_orphan_sessions == 0


def test_manual_reconciliation_invokes_cleanup_for_uncertain_no_port_run(database):
    session, owner, _ = run(claim=False)
    calls = []

    class Supervisor:
        def reconcile_teardown(self, current, ownership):
            calls.append((current.id, ownership.runtime_id))
            return sessions.apply_administrative_stop_evidence(current, proof(ownership), ownership)

    summary = reconcile_startup(status_probe=lambda _: {}, supervisor=Supervisor())
    assert calls == [(session.id, owner.runtime_id)]
    assert summary.stopped_runtimes == 1
    assert session.status == SessionStatus.COMPLETED
    assert db.session.scalar(db.select(Operation)).state == OperationState.SUCCEEDED


def test_stopped_row_without_positive_receipt_is_not_success(database):
    session, owner, config = run(state=RuntimeOwnershipState.STOPPED)
    sessions._stop_operation(session)
    reconcile_startup(status_probe=lambda _: {})
    assert session.status == SessionStatus.STOPPING
    assert config.claimed_session_id == session.id
    assert db.session.scalar(db.select(Operation)).state == OperationState.UNCERTAIN


def test_manual_route_uses_registered_supervisor_cleanup(database):
    from flask_smorest import Api
    from app.api.runtimes import blp

    session, owner, _ = run(claim=False)
    calls = []

    class Supervisor:
        def reconcile_teardown(self, current, ownership):
            calls.append(ownership.runtime_id)
            sessions.apply_administrative_stop_evidence(current, proof(ownership), ownership)

    database.config.update(API_TITLE="test", API_VERSION="v1", OPENAPI_VERSION="3.0.3",
                           STARTUP_RECONCILIATION_STATUS_PROBE=lambda _: {})
    database.extensions["host_supervisor"] = Supervisor()
    Api(database).register_blueprint(blp)
    response = database.test_client().post("/api/v1/runtimes/reconcile")
    assert response.status_code == 200
    assert calls == [owner.runtime_id]
    assert session.status == SessionStatus.COMPLETED


@pytest.mark.parametrize("command_owned", [True, False])
def test_manual_reconcile_never_cancels_live_starting_host_without_port(database, command_owned):
    session, owner, config = run(state=RuntimeOwnershipState.STARTING)
    session.status = SessionStatus.STARTING
    session.command_in_flight = command_owned
    owner.details = {}
    owner.pid = os.getpid()
    db.session.commit()

    class Supervisor:
        def reconcile_teardown(self, *_):
            pytest.fail("live startup must not receive a cancellation")

    for _ in range(2):
        summary = reconcile_startup(status_probe=lambda _: {}, supervisor=Supervisor())
        assert summary.deferred_runtimes == 1
    assert session.status == SessionStatus.STARTING
    assert owner.state == RuntimeOwnershipState.STARTING
    assert config.claimed_session_id == session.id


def test_manual_reconcile_does_not_cancel_unknown_starting_host(database):
    session, owner, config = run(state=RuntimeOwnershipState.STARTING)
    session.status = SessionStatus.STARTING
    owner.details = {}
    owner.pid = None
    db.session.commit()

    class Supervisor:
        def reconcile_teardown(self, *_):
            pytest.fail("unknown startup process is not proof of an orphan")

    reconcile_startup(status_probe=lambda _: {}, supervisor=Supervisor())
    assert session.status == SessionStatus.STARTING
    assert config.claimed_session_id == session.id


def test_dead_recorded_starting_host_retries_despite_stale_command_flag(database):
    session, owner, config = run(state=RuntimeOwnershipState.STARTING)
    session.status = SessionStatus.STARTING
    session.command_in_flight = True
    owner.details = {}
    child = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    child.wait(timeout=10)
    owner.pid = child.pid
    db.session.commit()
    calls = []

    class Supervisor:
        def reconcile_teardown(self, current, ownership):
            calls.append((current.id, ownership.runtime_id))

    reconcile_startup(status_probe=lambda _: {}, supervisor=Supervisor())
    assert calls == [(session.id, owner.runtime_id)]
    assert session.status == SessionStatus.STARTING
    assert config.claimed_session_id == session.id


def test_real_supervisor_reconciliation_retires_old_then_replays_latest(database, monkeypatch):
    from types import SimpleNamespace
    from app.control.supervisor import HostSupervisor
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    session, latest, config = run()
    older = RuntimeOwnership(runtime_id="older", session_id=session.id, dataflow_id="flow",
                             manifest_hash="manifest", watchdog_id="older-watchdog",
                             state=RuntimeOwnershipState.UNCERTAIN,
                             started_at=datetime.now(UTC) - timedelta(minutes=1))
    db.session.add(older)
    db.session.commit()
    sessions.apply_shutdown_result(session, receipt(teardown=True), latest)
    assert session.status == SessionStatus.STOPPING
    supervisor = HostSupervisor()
    receipts_read = []
    scheduled = []

    def lifecycle_reports(owner):
        receipts_read.append(owner.runtime_id)
        envelope = WatchdogTelemetryEnvelope(
            report_id=f"{owner.runtime_id}-exact", runtime_id=owner.runtime_id,
            watchdog_id=owner.watchdog_id, dataflow_id=owner.dataflow_id,
            manifest_hash=owner.manifest_hash, event_type="runtime.stop_finished",
            payload=receipt(teardown=True),
        )
        return [("test-outbox", SimpleNamespace(envelope=envelope))]

    monkeypatch.setattr(supervisor, "_lifecycle_reports", lifecycle_reports)
    monkeypatch.setattr(supervisor, "_schedule_recovery_retry", lambda **kwargs: scheduled.append(kwargs))
    supervisor.reconcile_teardown(session, older)
    assert receipts_read == [older.runtime_id]
    assert older.state == RuntimeOwnershipState.STOPPED
    assert latest.state == RuntimeOwnershipState.STOPPED
    assert session.status == SessionStatus.COMPLETED
    assert config.claimed_session_id is None
    assert db.session.scalar(db.select(Operation)).state == OperationState.SUCCEEDED
