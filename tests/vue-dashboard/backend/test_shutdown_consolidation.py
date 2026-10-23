"""Independent user-requirement oracle for the shutdown entry points.

Real SQLite, HostSupervisor, evidence assessment, OS file leases, session
projection, and output finalization execute. Only host HTTP and process
observations are substituted; no device or daemon process is started.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from structlog.contextvars import bound_contextvars

from app.control import supervisor as supervisor_module
from app.control.supervisor import HostSupervisor, _ChildEntry
from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
from app.database import create_database_app, db
from app.domain.enums import DeviceClaimState, DeviceType, OperationState, RuntimeOwnershipState, SessionStatus
from app.models.backend_event import BackendEvent
from app.models.device_config import DeviceConfig
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.runtime_host.process_evidence import ProcessEvidence, ProcessState
from app.services import output_finalization, sessions
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet
from app.watchdog_process.outbox import WatchdogOutbox


def _receipt(*, teardown=False, integrity=False):
    return {
        "command_id": "original-stop", "stop_reason": "application_shutdown",
        "requested_at": "2026-09-28T12:00:00+00:00",
        "teardown_confirmed": teardown, "output_integrity_confirmed": integrity,
        "errors": [] if integrity else ["sink flush failed"],
        "shutdown_result": {
            "ok": integrity, "worker_inventory_complete": True,
            "resources_teardown_confirmed": True, "previous_stream_results": [],
            "stream_results": [{"stream_index": 0, "worker_started": True,
                "worker_exited": True, "worker_exitcode": 0,
                "descendants_teardown_confirmed": True}],
        },
    }


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    app = create_database_app("testing", {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'shutdown.sqlite3'}",
        "WATCHDOG_HARDWARE_LOCK_DIR": str(tmp_path / "hardware-locks"),
        "RUNTIME_HOST_STOP_DRAIN_TIMEOUT_SECONDS": 0,
    })
    with app.app_context():
        db.create_all()
        supervisor = HostSupervisor()
        session = Session(name="shutdown oracle", status=SessionStatus.STOPPING,
            dataflow_id="oracle-flow", watchdog_id="oracle-watchdog", device_flows=[],
            runtime_port=43210, runtime_token="test-token", command_in_flight=False)
        db.session.add(session)
        db.session.flush()
        config = DeviceConfig(device_type=DeviceType.POD8206HR,
            hardware_id="shutdown-oracle-hardware", port="COM99",
            parameters={"preamp_gain": 10, "sample_rate": 2000},
            claim_state=DeviceClaimState.CLAIMED, claimed_session_id=session.id)
        db.session.add(config)
        db.session.flush()
        session.device_flows = [{"device_config_id": config.id, "sinks": [
            {"sink_type": "csv", "sink_name": "recording",
             "sink_location": str(tmp_path / "recording.csv")}]}]
        db.session.commit()
        manifest = supervisor._manifest_for_reconcile(session, session.dataflow_id)
        owner = RuntimeOwnership(runtime_id="oracle-runtime", session_id=session.id,
            dataflow_id=session.dataflow_id, manifest_hash=manifest.hash,
            watchdog_id=session.watchdog_id, pid=987650, watchdog_pid=987651,
            state=RuntimeOwnershipState.UNCERTAIN, watchdog_exit_details=_receipt())
        outputs = []
        for index in range(2):
            path = tmp_path / f"component-{index}.edf"
            path.write_bytes(b"unaltered interrupted component")
            outputs.append(OutputFile(session_id=session.id, output_id=f"output-{index}",
                logical_sink_id="oracle-output", segment_index=index,
                previous_output_id="output-0" if index else None,
                dataflow_id=session.dataflow_id, sink_type="edf", path=str(path),
                status="closed", acquisition_state="interrupted", artifact_state="merge_pending",
                termination_reason="writer_failure"))
        db.session.add_all([owner, *outputs])
        db.session.commit()
        status = {"phase": "stopping", "stop_result": _receipt()}
        monkeypatch.setattr(supervisor_module, "probe_process",
            lambda pid: ProcessEvidence(pid, ProcessState.DEAD, "test OS observation"))
        monkeypatch.setattr(supervisor_module.ControlPlaneCommandSender, "dispatch",
            lambda self, envelope: None)
        monkeypatch.setattr(supervisor, "_probe_status", lambda port: deepcopy(status))
        yield SimpleNamespace(app=app, supervisor=supervisor, session=session, owner=owner,
            config=config, outputs=outputs, manifest=manifest, status=status, tmp_path=tmp_path)
        supervisor.quiesce()
        db.session.remove()
        db.engine.dispose()


def _stop(runtime, route):
    if route == "orphan":
        runtime.owner.state = RuntimeOwnershipState.RECOVERING
        db.session.commit()
    if route != "orphan":
        runtime.supervisor._children[runtime.session.dataflow_id] = _ChildEntry(
            proc=None, runtime_id=runtime.owner.runtime_id, port=43210,
            token="test-token", manifest_path="")
    if route == "manual":
        with bound_contextvars(request_id="shutdown-oracle-request"):
            sessions.stop_managed(runtime.session.id, runtime.supervisor)
        return None
    return runtime.supervisor.stop_all(force=True)


def _operation():
    return db.session.scalar(db.select(Operation).where(Operation.command == "stop"))


def _assert_outputs_blocked(runtime):
    output_finalization.reconcile_completed_session_acquisitions()
    assert [row.acquisition_state for row in runtime.outputs] == ["interrupted", "interrupted"]
    assert all(row.artifact_state == "merge_blocked" for row in runtime.outputs)
    coordinator = output_finalization.FinalizationCoordinator(
        temp_dir=str(runtime.tmp_path / "merge"), lease_ttl_seconds=30, retention_seconds=60)
    assert coordinator.finalize_once(lambda request: pytest.fail("unclean output reached merger"),
        worker_id="oracle-finalizer", logical_sink_id="oracle-output") is None
    assert all(row.final_output_id is None for row in runtime.outputs)
    assert all((runtime.tmp_path / f"component-{index}.edf").read_bytes()
        == b"unaltered interrupted component" for index in range(2))


@pytest.mark.parametrize("route", ["manual", "tracked", "orphan"])
def test_administrative_shutdown_keeps_integrity_failure_across_entry_points(runtime, route):
    original = deepcopy(runtime.owner.watchdog_exit_details)
    summary = _stop(runtime, route)
    if summary is not None:
        assert summary["failed_count"] == 0, summary
        assert summary["stopped_count"] == 1
    assert runtime.session.status == SessionStatus.COMPLETED
    assert runtime.owner.state == RuntimeOwnershipState.STOPPED
    assert runtime.config.claim_state == DeviceClaimState.FREE
    assert runtime.config.claimed_session_id is None
    assert runtime.owner.watchdog_exit_details == original
    operation = _operation()
    assert operation.state == OperationState.SUCCEEDED
    assert operation.error_code is None
    assert operation.details["output_integrity_confirmed"] is False
    assert operation.details["warnings"]
    assert db.session.scalar(db.select(db.func.count()).select_from(BackendEvent).where(
        BackendEvent.event_type == "runtime.stop_finished")) == 0
    _assert_outputs_blocked(runtime)


@pytest.mark.parametrize("route", ["manual", "tracked"])
def test_shutdown_cannot_release_claim_while_another_owner_lacks_proof(runtime, route):
    # An old STOPPED label without exact teardown evidence is still unresolved.
    older = RuntimeOwnership(runtime_id="older-unproven", session_id=runtime.session.id,
        dataflow_id=runtime.session.dataflow_id, manifest_hash=runtime.manifest.hash,
        watchdog_id="older-watchdog", state=RuntimeOwnershipState.STOPPED,
        started_at=datetime.now(UTC) - timedelta(minutes=1))
    db.session.add(older)
    db.session.commit()
    _stop(runtime, route)
    assert runtime.owner.state == RuntimeOwnershipState.STOPPED
    assert runtime.session.status == SessionStatus.STOPPING
    assert runtime.config.claimed_session_id == runtime.session.id
    assert runtime.config.claim_state == DeviceClaimState.CLAIMED
    assert all(row.acquisition_state == "interrupted" for row in runtime.outputs)


def test_manual_administrative_projection_runs_once_under_real_lease(runtime, monkeypatch):
    actual_projection = sessions.apply_administrative_stop_evidence
    observations = []

    def observe_projection(*args, **kwargs):
        competitor = HardwareLeaseSet(runtime.manifest,
            directory=runtime.app.config["WATCHDOG_HARDWARE_LOCK_DIR"])
        held = False
        try:
            competitor.acquire()
        except HardwareLeaseBusy:
            held = True
        finally:
            competitor.release()
        observations.append(held)
        return actual_projection(*args, **kwargs)

    monkeypatch.setattr(sessions, "apply_administrative_stop_evidence", observe_projection)
    _stop(runtime, "manual")
    assert observations == [True], "one durable projection must execute while lease is held"
    with HardwareLeaseSet(runtime.manifest,
            directory=runtime.app.config["WATCHDOG_HARDWARE_LOCK_DIR"]):
        pass
    assert runtime.session.status == SessionStatus.COMPLETED


@pytest.mark.parametrize("route", ["manual", "tracked"])
def test_genuine_receipt_dict_completes_without_administrative_reclassification(runtime, route):
    receipt = _receipt(teardown=True, integrity=True)
    runtime.owner.watchdog_exit_details = None
    runtime.status.update(phase="stopped", stop_result=receipt)
    db.session.commit()
    summary = _stop(runtime, route)
    assert summary is None or summary["failed_count"] == 0
    assert runtime.session.status == SessionStatus.COMPLETED
    assert runtime.owner.watchdog_exit_details == receipt
    operation = _operation()
    assert operation.state == OperationState.SUCCEEDED
    assert operation.details["output_integrity_confirmed"] is True
    assert not operation.details.get("warnings")
    assert "administrative_stop_evidence" not in (runtime.owner.details or {})


@pytest.mark.parametrize("route", ["manual", "tracked"])
def test_legacy_none_cannot_complete_a_managed_watchdog_shutdown(runtime, route):
    runtime.owner.watchdog_exit_details = None
    runtime.status.clear()
    runtime.status["phase"] = "stopped"  # Host phase alone is not a producer receipt.
    db.session.commit()
    summary = _stop(runtime, route)
    assert runtime.session.status == SessionStatus.STOPPING
    assert runtime.config.claimed_session_id == runtime.session.id
    assert runtime.config.claim_state == DeviceClaimState.CLAIMED
    assert all(row.acquisition_state == "interrupted" for row in runtime.outputs)
    if summary is not None:
        assert summary["failed_count"] >= 1
    else:
        assert _operation().state != OperationState.SUCCEEDED


def test_nonforced_shutdown_finishes_all_producers_before_releasing_session(runtime):
    receipt = _receipt(teardown=True, integrity=True)
    runtime.owner.watchdog_exit_details = None
    runtime.status.update(phase="stopped", stop_result=receipt)
    older = RuntimeOwnership(runtime_id="older-active", session_id=runtime.session.id,
        dataflow_id=runtime.session.dataflow_id, manifest_hash=runtime.manifest.hash,
        watchdog_id="older-watchdog", state=RuntimeOwnershipState.RECOVERING,
        started_at=datetime.now(UTC) - timedelta(minutes=1),
        watchdog_outbox_path=str(runtime.tmp_path / "older-watchdog.sqlite3"))
    db.session.add(older)
    db.session.commit()
    with WatchdogOutbox(older.watchdog_outbox_path) as outbox:
        outbox.enqueue(WatchdogTelemetryEnvelope(report_id="older-stop-report",
            runtime_id=older.runtime_id, watchdog_id=older.watchdog_id,
            dataflow_id=older.dataflow_id, manifest_hash=older.manifest_hash,
            event_type="runtime.stop_finished", payload=receipt))
    runtime.supervisor._children[runtime.session.dataflow_id] = _ChildEntry(
        proc=None, runtime_id=runtime.owner.runtime_id, port=43210,
        token="test-token", manifest_path="")

    summary = runtime.supervisor.stop_all(force=False)

    assert summary["failed_count"] == 0, summary
    assert older.watchdog_exit_details == receipt
    assert runtime.owner.watchdog_exit_details == receipt
    assert older.state == runtime.owner.state == RuntimeOwnershipState.STOPPED
    assert runtime.session.status == SessionStatus.COMPLETED
    assert runtime.config.claimed_session_id is None
    assert runtime.config.claim_state == DeviceClaimState.FREE
    assert _operation().state == OperationState.SUCCEEDED


def test_start_rollback_without_published_owner_cannot_accept_legacy_none(runtime, monkeypatch):
    # The launch can have reached the OS before runtime identity is persisted.
    # No return value from the rollback transport proves that launch did not run.
    db.session.delete(runtime.owner)
    runtime.session.status = SessionStatus.PREPARING
    runtime.session.dataflow_id = None
    runtime.session.watchdog_id = None
    runtime.session.runtime_port = None
    runtime.session.runtime_token = None
    runtime.config.claimed_session_id = None
    runtime.config.claim_state = DeviceClaimState.FREE
    db.session.commit()
    monkeypatch.setattr(sessions.manifests, "refresh_port", lambda *args: "COM99")
    calls = []

    class LaunchFailure:
        def spawn(self, session, *, manifest):
            calls.append("spawn")
            raise RuntimeError("launch acknowledgement lost before owner publication")

        def stop(self, session):
            calls.append("stop")
            return None

    with bound_contextvars(request_id="startup-rollback-oracle"):
        with pytest.raises(RuntimeError, match="launch acknowledgement lost"):
            sessions.start_managed(runtime.session.id, LaunchFailure())

    assert calls == ["spawn", "stop"]
    assert runtime.session.status == SessionStatus.STOPPING
    assert runtime.session.dataflow_id is not None
    assert runtime.config.claimed_session_id == runtime.session.id
    assert runtime.config.claim_state != DeviceClaimState.FREE
    assert all(row.acquisition_state == "interrupted" for row in runtime.outputs)


def test_orphan_without_watchdog_or_nonlaunch_proof_remains_retryable(runtime):
    runtime.owner.state = RuntimeOwnershipState.RECOVERING
    runtime.owner.watchdog_id = None
    runtime.owner.watchdog_pid = None
    runtime.owner.pid = None
    runtime.owner.watchdog_exit_details = None
    db.session.commit()

    for _ in range(2):
        summary = runtime.supervisor.stop_all(force=True)
        assert summary["failed_count"] >= 1, summary
        assert runtime.owner.state != RuntimeOwnershipState.STOPPED
        assert runtime.session.status == SessionStatus.STOPPING
        assert runtime.config.claimed_session_id == runtime.session.id
        assert runtime.config.claim_state == DeviceClaimState.CLAIMED
