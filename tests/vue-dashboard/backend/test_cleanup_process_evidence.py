"""Real process observations and shutdown-policy negative controls."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.control.orphan_teardown import assess_orphan_teardown, workers_exited
from app.control.supervisor import HostSupervisor
from app.runtime_host.process_evidence import ProcessEvidence, ProcessState, probe_process


def test_real_process_alive_then_exited():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert probe_process(child.pid).state is ProcessState.ALIVE
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert probe_process(child.pid).state is ProcessState.DEAD
    assert probe_process(os.getpid()).state is ProcessState.ALIVE


@pytest.mark.parametrize("pid", [None, 0, -1, True])
def test_missing_identity_is_unknown(pid):
    assert probe_process(pid).state is ProcessState.UNKNOWN


def test_os_query_error_is_unknown(monkeypatch):
    from app.runtime_host import process_evidence
    monkeypatch.setattr(process_evidence, "sys", SimpleNamespace(platform="posix"))
    monkeypatch.setattr(process_evidence.os, "kill", Mock(side_effect=PermissionError()))
    assert probe_process(123).state is ProcessState.UNKNOWN


def stream(index=0, **changes):
    return dict(stream_index=index, worker_exited=True, worker_exitcode=1,
                teardown_confirmed=False, descendants_teardown_confirmed=True, **changes)


def assess(result=None, **changes):
    receipt = {"command_id": "original", "stop_reason": "runtime_failure",
               "requested_at": "2026-09-25T00:00:00+00:00",
               "shutdown_result": {"worker_inventory_complete": True, "previous_stream_results": [],
                                   "resources_teardown_confirmed": True,
                                   **(result or {"stream_results": [stream()]})},
               "output_integrity_confirmed": False, "errors": ["worker crashed"]}
    values = dict(runtime_id="runtime", watchdog_id="watchdog", dataflow_id="flow",
                  manifest_hash="manifest", receipt=receipt, expected_streams=1,
                  host=ProcessEvidence(1, ProcessState.DEAD, "exit"),
                  watchdog=ProcessEvidence(2, ProcessState.DEAD, "exit"),
                  hardware_leases_free=True, predecessors_confirmed=True)
    values.update(changes)
    return assess_orphan_teardown(**values)


def test_crashed_exit_proves_teardown_but_never_integrity():
    proof = assess()
    assert proof.payload["teardown_confirmed"] is True
    assert proof.payload["output_integrity_confirmed"] is False
    assert proof.payload["errors"][0] == "worker crashed"


@pytest.mark.parametrize("field,value", [
    ("host", ProcessEvidence(1, ProcessState.ALIVE, "exists")),
    ("watchdog", ProcessEvidence(2, ProcessState.UNKNOWN, "access_denied")),
    ("hardware_leases_free", False), ("predecessors_confirmed", False),
])
def test_incomplete_parent_or_lease_evidence_blocks_cleanup(field, value):
    assert assess(**{field: value}) is None


@pytest.mark.parametrize("result", [
    {"stream_results": [], "worker_inventory_complete": False},
    {"stream_results": [dict(stream(), descendants_teardown_confirmed=False)]},
    {"stream_results": [stream()], "resources_teardown_confirmed": False},
    {"stream_results": [stream(), stream()]},
    {"stream_results": [dict(stream(), worker_exited=False)]},
    {"stream_results": [dict(stream(), worker_exitcode=None)]},
    {"stream_results": [stream()], "previous_stream_results": [dict(stream(), worker_exited=False)]},
])
def test_missing_or_live_generation_blocks_cleanup(result):
    assert assess(result) is None


def test_partial_start_has_explicit_nonlaunch_evidence():
    result = {"stream_results": [{"stream_index": 0, "worker_started": False,
        "worker_status": "not_started", "teardown_confirmed": True}]}
    assert assess(result) is not None


def test_saved_incident_crashed_workers_are_not_live():
    snapshot = Path(__file__).resolve().parents[3] / ".audit/stale-session-2-20260925/before.sqlite3"
    if not snapshot.exists():
        pytest.skip("local incident oracle is not distributed")
    with sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True) as connection:
        raw = connection.execute("SELECT details FROM operations WHERE session_id=2 AND command='stop'").fetchone()[0]
    result = json.loads(raw)["shutdown_result"]
    assert len(result["stream_results"]) == 13
    assert sum(row["worker_exitcode"] == 1 for row in result["stream_results"]) == 5
    assert not workers_exited(result, 13)  # Legacy receipt has no inventory-completeness assertion.
    assert all(row["worker_exited"] and type(row["worker_exitcode"]) is int
               for row in result["stream_results"])
    # The saved host PID is missing: generic cleanup cannot invent that proof.
    assert assess(result, expected_streams=13, host=probe_process(None)) is None


def test_negative_historical_receipt_does_not_abort_fresh_drain(app, monkeypatch):
    from app.watchdog_process import control
    with app.app_context():
        app.config["RUNTIME_HOST_STOP_DRAIN_TIMEOUT_SECONDS"] = 1
        supervisor = HostSupervisor()
        owner = SimpleNamespace(runtime_id="runtime", watchdog_id="watchdog", manifest_hash="hash",
            dataflow_id="flow", watchdog_pid=123, watchdog_control_port=4000, token="token")
        client = Mock()
        client.probe.return_value = dict(runtime_id="runtime", watchdog_id="watchdog",
            manifest_hash="hash", dataflow_id="flow", pid=123)
        monkeypatch.setattr(control, "WatchdogControlClient", Mock(return_value=client))
        def report(proven):
            return ("outbox", SimpleNamespace(envelope=SimpleNamespace(watchdog_id="watchdog",
                event_type="runtime.stop_finished", payload={"teardown_confirmed": proven})))
        supervisor._lifecycle_reports = Mock(side_effect=[[], [report(False)], [report(False), report(True)]])
        supervisor._ownerships = Mock()
        supervisor._administrative_stop_evidence = Mock(return_value=None)
        assert supervisor._stop_starting_watchdog(None, owner, None)["teardown_confirmed"] is True
        client.stop_watchdog.assert_called_once()


def test_no_port_cleanup_converges_after_real_watchdog_exit(app, tmp_path):
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
    from app.database import db
    from app.domain.enums import DeviceClaimState, DeviceType, PolicyMode, RuntimeOwnershipState, SessionStatus
    from app.models.device_config import DeviceConfig
    from app.models.operation import Operation
    from app.models.runtime_ownership import RuntimeOwnership
    from app.models.session import Session
    from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
    from app.watchdog_process.hardware_lease import HardwareLeaseSet
    from app.watchdog_process.outbox import WatchdogOutbox

    host = subprocess.Popen([sys.executable, "-c", "pass"])
    host.wait(timeout=5)
    watchdog = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with app.app_context():
            lock_dir = tmp_path / "hardware-locks"
            app.config["WATCHDOG_HARDWARE_LOCK_DIR"] = str(lock_dir)
            flow = DeviceFlow(device_id="test-device", name="test-device", hardware_id="cleanup-test-only",
                              port="test-port", parameters={}, sink_type="csv", sink_location=str(tmp_path / "out.csv"))
            manifest = Manifest(schema_version=MANIFEST_SCHEMA_VERSION, dataflow_id="flow", policy=PolicyMode.RECOMMEND,
                                device_flows=(flow,))
            session = Session(name="cleanup integration", status=SessionStatus.STOPPING, dataflow_id="flow",
                              policy=manifest.policy, device_flows=[flow.to_dict()], command_in_flight=False)
            db.session.add(session)
            db.session.flush()
            path = tmp_path / "outbox.sqlite3"
            owner = RuntimeOwnership(runtime_id="runtime", session_id=session.id, dataflow_id="flow",
                watchdog_id="watchdog", manifest_hash=manifest.hash, pid=host.pid, watchdog_pid=watchdog.pid,
                watchdog_outbox_path=str(path), state=RuntimeOwnershipState.UNCERTAIN)
            claim = DeviceConfig(device_type=DeviceType.POD8206HR, hardware_id="cleanup-test-only", port="test-port",
                                 claim_state=DeviceClaimState.CLAIMED, claimed_session_id=session.id)
            db.session.add_all([owner, claim])
            db.session.commit()
            payload = assess().payload
            payload["teardown_confirmed"] = False
            with WatchdogOutbox(path) as outbox:
                outbox.enqueue(WatchdogTelemetryEnvelope(report_id="failed-receipt", runtime_id="runtime",
                    watchdog_id="watchdog", dataflow_id="flow", manifest_hash=manifest.hash,
                    event_type="runtime.stop_finished", payload=payload))
            supervisor = HostSupervisor()
            supervisor.reconcile_teardown(session, owner)
            assert session.status is SessionStatus.STOPPING
            assert claim.claimed_session_id == session.id
            watchdog.terminate()
            watchdog.wait(timeout=5)
            # An independently held physical lease must still prevent release.
            with HardwareLeaseSet(manifest, directory=lock_dir):
                supervisor.reconcile_teardown(session, owner)
                assert session.status is SessionStatus.STOPPING
                assert claim.claimed_session_id == session.id
            supervisor.reconcile_teardown(session, owner)
            assert session.status is SessionStatus.COMPLETED
            assert claim.claimed_session_id is None
            operation = db.session.scalar(db.select(Operation).where(Operation.command == "stop"))
            assert operation.details["output_integrity_confirmed"] is False
            assert operation.details["administrative_stop_evidence"]["payload"]["command_id"] == "original"
    finally:
        if watchdog.poll() is None:
            watchdog.terminate()
            watchdog.wait(timeout=5)
