"""Verify parent cleanup with real Windows writers and isolated SQLite claims."""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import psutil
import pytest
from structlog.contextvars import bound_contextvars

from app.control.supervisor import HostSupervisor
from app.database import db
from app.domain.enums import DeviceClaimState, DeviceType, PolicyMode, RuntimeOwnershipState, SessionStatus
from app.models.device_config import DeviceConfig
from app.models.operation import Operation
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.services.sessions import stop_managed

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows owned process trees")


def _wait_for(path, process=None, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        if process is not None and process.poll() is not None:
            pytest.fail(f"helper exited {process.returncode}: {process.stderr.read()}")
        time.sleep(0.02)
    pytest.fail(f"fixture did not become ready: {path}")


def _alive(pid):
    try:
        return psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        return False


def _assert_released(session, claim, pids, sentinel):
    assert all(not _alive(pid) for pid in pids), f"owned processes still alive: {pids}"
    assert sentinel.poll() is None, "unrelated process was terminated"
    assert session.status is SessionStatus.COMPLETED
    assert claim.claimed_session_id is None
    assert claim.claim_state is DeviceClaimState.FREE
    operation = db.session.scalar(db.select(Operation).where(Operation.command == "stop"))
    assert operation.details["teardown_confirmed"] is True
    assert operation.details["output_integrity_confirmed"] is False
    assert operation.details.get("stop_finished_report_id") is None


def _stop(session, supervisor):
    with bound_contextvars(request_id=uuid4().hex):
        stop_managed(session.id, supervisor)


@contextmanager
def _case(app, tmp_path, generations, *, separate_owners=False, host_mode="dead"):
    helper = tmp_path / "parent_cleanup_fixture.py"
    helper.write_text(HELPER_SOURCE)
    processes = []
    identities = []
    try:
        with app.app_context():
            app.config["WATCHDOG_HARDWARE_LOCK_DIR"] = str(tmp_path / "hardware-locks")
            app.config["RUNTIME_HOST_STOP_DRAIN_TIMEOUT_SECONDS"] = 0.15
            app.config["WATCHDOG_RECOVERY_MAX_ATTEMPTS"] = 1
            flow = DeviceFlow(device_id="oracle-device", name="oracle-device",
                hardware_id="oracle-" + uuid4().hex, port="oracle-no-hardware", parameters={},
                sink_type="csv", sink_location=str(tmp_path / "output.csv"))
            manifest = Manifest(schema_version=MANIFEST_SCHEMA_VERSION, dataflow_id="oracle-flow",
                policy=PolicyMode.RECOMMEND, device_flows=(flow,))
            session = Session(name="parent cleanup oracle", status=SessionStatus.ACTIVE,
                dataflow_id=manifest.dataflow_id, policy=manifest.policy,
                device_flows=[flow.to_dict()], command_in_flight=False)
            db.session.add(session)
            db.session.flush()
            claim = DeviceConfig(device_type=DeviceType.POD8206HR, hardware_id=flow.hardware_id,
                port=flow.port, claim_state=DeviceClaimState.CLAIMED, claimed_session_id=session.id)
            db.session.add(claim)
            host = subprocess.Popen([sys.executable, "-c",
                "pass" if host_mode == "dead" else "import time; time.sleep(60)"])
            processes.append(host)
            host_identity = None
            if host_mode == "dead":
                host.wait(timeout=5)
            else:
                from app.runtime_host.process_evidence import record_process_identity
                host_identity = record_process_identity(host.pid)
                assert host_identity is not None
                if host_mode == "reused":
                    host_identity["creation_filetime"] = str(int(host_identity["creation_filetime"]) - 1)
                else:
                    identities.append(psutil.Process(host.pid))
            references = []
            for index in range(generations):
                directory = tmp_path / f"generation-{index}"
                directory.mkdir()
                watchdog_id = "oracle-watchdog-" + uuid4().hex
                outbox_path = directory / "outbox.sqlite3"
                process = subprocess.Popen([sys.executable, str(helper), "watchdog", str(directory),
                    str(outbox_path), watchdog_id, manifest.dataflow_id, manifest.hash],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                processes.append(process)
                worker_pid = int(_wait_for(directory / "worker.pid", process))
                pids = [process.pid, worker_pid]
                pids += [int(_wait_for(directory / f"{label}.pid", process))
                         for label in ("child", "grandchild")]
                assert all(_alive(pid) for pid in pids)
                identities.extend(psutil.Process(pid) for pid in pids)
                (directory / "exit-worker").write_text("exit")
                assert _wait_for(directory / "worker-exited", process) == "17"
                assert not _alive(worker_pid)
                assert all(_alive(pid) for pid in [process.pid, *pids[2:]])
                sizes = [(directory / f"{label}.writes").stat().st_size for label in ("child", "grandchild")]
                time.sleep(0.12)
                assert all((directory / f"{label}.writes").stat().st_size > size
                           for label, size in zip(("child", "grandchild"), sizes))
                references.append(dict(watchdog_id=watchdog_id, runtime_id="oracle-runtime",
                    dataflow_id=manifest.dataflow_id, manifest_hash=manifest.hash, pid=process.pid,
                    outbox_path=str(outbox_path), exit_details=None))
            if separate_owners:
                for index, reference in enumerate(references[:-1]):
                    db.session.add(RuntimeOwnership(
                        runtime_id=f"oracle-runtime-old-{index}", session_id=session.id,
                        dataflow_id=manifest.dataflow_id, manifest_hash=manifest.hash, pid=host.pid,
                        watchdog_id=reference["watchdog_id"], watchdog_pid=reference["pid"],
                        watchdog_outbox_path=reference["outbox_path"],
                        state=RuntimeOwnershipState.UNCERTAIN,
                    ))
                    db.session.flush()
            latest = references[-1]
            owner = RuntimeOwnership(runtime_id="oracle-runtime", session_id=session.id,
                dataflow_id=manifest.dataflow_id, manifest_hash=manifest.hash, pid=host.pid,
                watchdog_id=latest["watchdog_id"], watchdog_pid=latest["pid"],
                watchdog_outbox_path=latest["outbox_path"], state=RuntimeOwnershipState.UNCERTAIN,
                details={"predecessor_watchdogs": [] if separate_owners else references[:-1],
                         "host_process_identity": host_identity})
            db.session.add(owner)
            db.session.commit()
            sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            processes.append(sentinel)
            yield session, claim, owner, [proc.pid for proc in identities], sentinel
    finally:
        for process in reversed(identities):
            try:
                if process.is_running():
                    process.kill()
                    process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        for process in reversed(processes):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize(("generations", "outbox_state"), [(1, "missing"), (3, "missing"), (1, "corrupt")])
def test_missing_reports_cleanup_writers_and_release_claims(app, tmp_path, generations, outbox_state):
    with _case(app, tmp_path, generations) as (session, claim, owner, pids, sentinel):
        assert owner.watchdog_exit_details is None
        if outbox_state == "corrupt":
            Path(owner.watchdog_outbox_path).write_bytes(b"unreadable watchdog report channel")
        _stop(session, HostSupervisor())
        db.session.refresh(session)
        db.session.refresh(claim)
        _assert_released(session, claim, pids, sentinel)


def test_failed_native_termination_retains_claims_then_retry_releases(app, tmp_path, monkeypatch):
    import ctypes
    from app.watchdog_process import process_tree

    configure = process_tree._configure_kernel32
    attempts = []

    def deny_termination(kernel32):
        configure(kernel32)

        def denied(handle, exit_code):
            attempts.append((handle, exit_code))
            ctypes.set_last_error(5)
            return False

        kernel32.TerminateJobObject = denied

    with _case(app, tmp_path, 1) as (session, claim, owner, pids, sentinel):
        supervisor = HostSupervisor()
        with monkeypatch.context() as patch:
            patch.setattr(process_tree, "_configure_kernel32", deny_termination)
            _stop(session, supervisor)
            db.session.refresh(session)
            db.session.refresh(claim)
            assert attempts, "negative control did not reach native termination"
            assert session.status is SessionStatus.STOPPING
            assert claim.claimed_session_id == session.id
            assert claim.claim_state is DeviceClaimState.CLAIMED
            with pytest.raises(AssertionError, match="owned processes still alive"):
                _assert_released(session, claim, pids, sentinel)
            assert sentinel.poll() is None
            operation = db.session.scalar(db.select(Operation).where(Operation.command == "stop"))
            assert operation.details.get("teardown_confirmed") is not True
        _stop(session, supervisor)
        db.session.refresh(session)
        db.session.refresh(claim)
        _assert_released(session, claim, pids, sentinel)


def test_earlier_runtime_owners_are_cleaned_before_claim_release(app, tmp_path):
    with _case(app, tmp_path, 3, separate_owners=True) as (session, claim, owner, pids, sentinel):
        supervisor = HostSupervisor()
        _stop(session, supervisor)
        for _ in range(4):
            db.session.refresh(session)
            db.session.refresh(claim)
            if any(_alive(pid) for pid in pids):
                assert session.status is SessionStatus.STOPPING
                assert claim.claimed_session_id == session.id
            if session.status is SessionStatus.COMPLETED:
                break
            supervisor.reconcile_teardown(session, owner)
        db.session.refresh(session)
        db.session.refresh(claim)
        _assert_released(session, claim, pids, sentinel)


@pytest.mark.parametrize("host_mode", ["live", "reused"])
def test_recorded_host_identity_controls_parent_termination(app, tmp_path, host_mode):
    with _case(app, tmp_path, 1, host_mode=host_mode) as (session, claim, owner, pids, sentinel):
        assert _alive(owner.pid)
        _stop(session, HostSupervisor())
        db.session.refresh(session)
        db.session.refresh(claim)
        _assert_released(session, claim, pids, sentinel)
        if host_mode == "reused":
            assert _alive(owner.pid), "replacement process sharing an old recorded PID was terminated"


@pytest.mark.parametrize("failed_call", ["TerminateJobObject", "QueryInformationJobObject"])
def test_old_receipt_cannot_override_failed_native_cleanup(app, tmp_path, monkeypatch, failed_call):
    import ctypes

    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
    from app.control.orphan_teardown import assess_orphan_teardown
    from app.runtime_host.process_evidence import probe_process
    from app.watchdog_process import process_tree
    from app.watchdog_process.outbox import WatchdogOutbox

    with _case(app, tmp_path, 1) as (session, claim, owner, pids, sentinel):
        actual_watchdog_pid = owner.watchdog_pid
        owner.watchdog_pid = int(Path(owner.watchdog_outbox_path).with_name("worker.pid").read_text())
        db.session.commit()
        assert not _alive(owner.watchdog_pid)
        assert _alive(actual_watchdog_pid)
        assert all(_alive(pid) for pid in pids[-2:])
        receipt = {
            "command_id": "old-stop", "requested_at": "2026-10-14T00:00:00+00:00",
            "stop_reason": "runtime_failure", "teardown_confirmed": False,
            "output_integrity_confirmed": False, "errors": ["historical unclean shutdown"],
            "shutdown_result": {"worker_inventory_complete": True,
                "previous_stream_results": [], "resources_teardown_confirmed": True,
                "stream_results": [{"stream_index": 0, "worker_exited": True,
                    "worker_exitcode": 17, "descendants_teardown_confirmed": True}]},
        }
        assert assess_orphan_teardown(
            runtime_id=owner.runtime_id, watchdog_id=owner.watchdog_id,
            dataflow_id=owner.dataflow_id, manifest_hash=owner.manifest_hash,
            receipt=receipt, expected_streams=1, host=probe_process(owner.pid),
            watchdog=probe_process(owner.watchdog_pid), hardware_leases_free=True,
            predecessors_confirmed=True,
        ) is not None
        with WatchdogOutbox(owner.watchdog_outbox_path) as outbox:
            outbox.enqueue(WatchdogTelemetryEnvelope(
                report_id="historical-receipt", runtime_id=owner.runtime_id,
                watchdog_id=owner.watchdog_id, dataflow_id=owner.dataflow_id,
                manifest_hash=owner.manifest_hash, event_type="runtime.stop_finished",
                payload=receipt,
            ))
        configure = process_tree._configure_kernel32
        attempts = []

        def fail_native_call(api):
            configure(api)

            def denied(*args):
                attempts.append(args)
                ctypes.set_last_error(5)
                return False

            setattr(api, failed_call, denied)

        supervisor = HostSupervisor()
        with monkeypatch.context() as patch:
            patch.setattr(process_tree, "_configure_kernel32", fail_native_call)
            _stop(session, supervisor)
            db.session.refresh(session)
            db.session.refresh(claim)
            assert attempts
            assert all(_alive(pid) for pid in [actual_watchdog_pid, *pids[-2:]])
            assert sentinel.poll() is None
            assert session.status is SessionStatus.STOPPING
            assert claim.claimed_session_id == session.id
            assert claim.claim_state is DeviceClaimState.CLAIMED
        _stop(session, supervisor)
        db.session.refresh(session)
        db.session.refresh(claim)
        _assert_released(session, claim, pids, sentinel)


HELPER_SOURCE = r"""
import os
from pathlib import Path
import subprocess
import sys
import time


class OracleSource:
    def get_dict(self):
        return {}


class SilentWriterSink:
    owns_child_processes = True

    def __init__(self, directory, run=False, pod=None):
        self.directory = str(directory)
        if run:
            subprocess.Popen(
                [sys.executable, __file__, "writer", self.directory, "child", "grandchild"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if (Path(self.directory) / "exit-worker").exists():
                    os._exit(17)
                time.sleep(0.02)
            os._exit(18)

    def get_dict(self):
        return {"directory": self.directory, "run": True}


def writer(directory, label, nested=None):
    directory = Path(directory)
    if nested:
        subprocess.Popen(
            [sys.executable, __file__, "writer", str(directory), nested],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    (directory / f"{label}.pid").write_text(str(os.getpid()))
    with (directory / f"{label}.writes").open("ab", buffering=0) as output:
        until = time.monotonic() + 60
        while time.monotonic() < until:
            output.write(b"x")
            time.sleep(0.05)


def watchdog(directory, outbox_path, watchdog_id, dataflow_id, manifest_hash):
    from app.runtime_child.acknowledged_dataflow import AcknowledgedDataFlow
    from app.watchdog_process.process_tree import install_owned_process_tree

    guard = install_owned_process_tree(
        outbox_path, watchdog_id=watchdog_id, dataflow_id=dataflow_id,
        manifest_hash=manifest_hash,
    )
    flow = AcknowledgedDataFlow([(OracleSource(), [SilentWriterSink(directory)])])
    flow.collect()
    Path(directory, "worker.pid").write_text(str(flow._workers[0].pid))
    flow._workers[0].join(35)
    Path(directory, "worker-exited").write_text(str(flow._workers[0].exitcode))
    time.sleep(60)


if __name__ == "__main__":
    if sys.argv[1] == "watchdog":
        watchdog(*sys.argv[2:])
    else:
        writer(*sys.argv[2:])
"""
