"""Acceptance tests — host supervisor spawn/stop (Slice 6) + reconcile (Slice 7).

Uses a real Flask app on an on-disk SQLite database. ``HostSupervisor``
spawns a real ``python -m app.runtime_host`` subprocess; the test drives the
full lifecycle and asserts both the DB state and the process state.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request

import pytest
from sqlalchemy import URL

from app import create_app
from app.control.supervisor import HostAlreadyRunning, HostSupervisor, _ChildEntry
from app.database import db
from app.domain.enums import (
    DeviceType,
    PolicyMode,
    RuntimeOwnershipState,
    SessionStatus,
    SinkType,
    WatchdogProcessState,
)
from app.domain.errors import RuntimeNotTracked, StopProofMissing
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.__main__ import _prepare_driver_for_host_start
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.runtime_host.watchdog_process_driver import WatchdogProcessDriver
from app.services.device_configs import create as create_device_config


class _StartupDriver:
    def __init__(self, phase, *, watchdog_preflight_ready=False):
        self.phase = phase
        self.watchdog_preflight_ready = watchdog_preflight_ready
        self.preflight_calls = 0
        self.ensure_preflight_ready_calls = 0

    def preflight(self):
        self.preflight_calls += 1
        self.phase = RuntimePhase.PREFLIGHT

    def ensure_preflight_ready(self):
        self.ensure_preflight_ready_calls += 1


def test_adopted_runtime_host_skips_fresh_preflight_barrier():
    driver = _StartupDriver(RuntimePhase.RUNNING, watchdog_preflight_ready=True)

    _prepare_driver_for_host_start(driver)

    assert driver.preflight_calls == 0
    assert driver.ensure_preflight_ready_calls == 0


def test_fresh_runtime_host_still_runs_preflight_barrier():
    driver = _StartupDriver(RuntimePhase.IDLE)

    _prepare_driver_for_host_start(driver)

    assert driver.preflight_calls == 1
    assert driver.ensure_preflight_ready_calls == 1

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sup_app(tmp_path):
    """Fresh Flask app on an on-disk SQLite file (survives across contexts)."""
    url = URL.create("sqlite", database=str(tmp_path / "sup.sqlite3"))
    app = create_app("testing", config_overrides={"SQLALCHEMY_DATABASE_URI": url})
    with app.app_context():
        db.create_all()
    return app


@pytest.fixture()
def session_id(sup_app):
    """A session with Manifest-format device_flows; yields its integer PK."""
    with sup_app.app_context():
        row = Session(
            name="sup-test",
            dataflow_id="df-sup-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=[
                {
                    "device_id": "dev-sup-1",
                    "name": "device-sup-1",
                    "nickname": None,
                    "hardware_id": "001",
                    "port": "usb-1",
                    "parameters": {},
                    "sink_type": "csv",
                    "sink_location": "/data/dev-sup-1.csv",
                }
            ],
        )
        db.session.add(row)
        db.session.commit()
        return row.id


@pytest.fixture()
def auto_supervisor():
    """HostSupervisor that terminates any remaining children on teardown."""
    sup = HostSupervisor()
    yield sup
    for entry in list(sup._children.values()):
        try:
            if entry.proc is not None:
                entry.proc.terminate()
                entry.proc.wait(timeout=5)
        except Exception:
            pass
    sup._children.clear()


def _get_status(port: int) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/status", method="GET")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


def _create_session_config_shape_session(
    *,
    name: str,
    dataflow_id: str,
    hardware_id: str,
    status: SessionStatus = SessionStatus.ACTIVE,
) -> Session:
    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id=hardware_id,
        port="COM3",
        parameters={
            "preamp_gain": 10,
            "sample_rate": 2000,
            },
    )
    session = Session(
        name=name,
        dataflow_id=dataflow_id,
        status=status,
        policy=PolicyMode.RECOMMEND,
        device_flows=[
            {
                "device_config_id": config.id,
                "sink_type": "csv",
                "sink_location": f"C:/data/{hardware_id}.csv",
            }
        ],
    )
    db.session.add(session)
    db.session.commit()
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpawnStop:
    def test_spawn_rejects_session_without_dataflow_id(self, sup_app, auto_supervisor):
        with sup_app.app_context():
            row = Session(
                name="no-dataflow",
                policy=PolicyMode.RECOMMEND,
                device_flows=[],
            )
            db.session.add(row)
            db.session.commit()

            with pytest.raises(ValueError, match="no dataflow_id"):
                auto_supervisor.spawn(row)

    def test_stop_raises_runtime_not_tracked_when_never_spawned(
        self, sup_app, session_id, auto_supervisor
    ):
        """Simulates a daemon restart that never reconciled this dataflow back in."""
        with sup_app.app_context():
            session = db.session.get(Session, session_id)

            with pytest.raises(RuntimeNotTracked) as exc_info:
                auto_supervisor.stop(session)
            assert exc_info.value.dataflow_id == "df-sup-1"

    def test_stop_raises_stop_proof_missing_when_host_is_unreachable(
        self, sup_app, session_id, auto_supervisor
    ):
        """No live probe, no durable terminal report: the host cannot prove a
        clean stop. The (already-dead) entry is still torn down/discarded, but
        ownership is left UNCERTAIN rather than STOPPED, and StopProofMissing
        is raised so the caller never treats this as a clean stop."""
        with sup_app.app_context():
            session = db.session.get(Session, session_id)
            RuntimeOwnershipRepository().create_starting(
                runtime_id="rt-unreachable",
                session_id=session.id,
                dataflow_id="df-sup-1",
                manifest_hash="hash-unreachable",
                token=None,
            )

            # A closed port the OS briefly owned but is now dead — every probe
            # against it raises, mirroring an unreachable/crashed host.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                dead_port = s.getsockname()[1]

            auto_supervisor._children["df-sup-1"] = _ChildEntry(
                proc=None,
                runtime_id="rt-unreachable",
                port=dead_port,
                token=None,
                manifest_path="",
            )

            with pytest.raises(StopProofMissing) as exc_info:
                auto_supervisor.stop(session)
            assert exc_info.value.dataflow_id == "df-sup-1"
            assert exc_info.value.runtime_id == "rt-unreachable"

            ownership = db.session.scalars(
                db.select(RuntimeOwnership).where(RuntimeOwnership.runtime_id == "rt-unreachable")
            ).one()
            assert ownership.state is RuntimeOwnershipState.UNCERTAIN
            assert ownership.details.get("reason") == "stop_proof_missing"
            # An unproven stop must not be mistaken for a clean one.
            assert "df-sup-1" not in auto_supervisor._children

    def test_stop_after_daemon_restart_still_raises_runtime_not_tracked(
        self, sup_app, session_id, auto_supervisor
    ):
        """A dataflow that was never proof-missing (no UNCERTAIN/stop_proof_missing
        ownership row at all — e.g. a genuine daemon-restart-before-reconcile
        case) must still raise the plain RuntimeNotTracked, not StopProofMissing."""
        with sup_app.app_context():
            session = db.session.get(Session, session_id)
            RuntimeOwnershipRepository().create_starting(
                runtime_id="rt-clean-restart",
                session_id=session.id,
                dataflow_id="df-sup-1",
                manifest_hash="hash-clean-restart",
                token=None,
            )
            # No child entry was ever registered on this (fresh) supervisor —
            # simulates a restart that hasn't reconciled yet. Ownership stays
            # RUNNING (create_starting's default), never UNCERTAIN.

            with pytest.raises(RuntimeNotTracked) as exc_info:
                auto_supervisor.stop(session)
            assert exc_info.value.dataflow_id == "df-sup-1"

    def test_dispatch_raises_runtime_not_tracked_when_never_spawned(
        self, sup_app, session_id, auto_supervisor
    ):
        from uuid import uuid4

        from app.watchdog.messages import CommandEnvelope, CorrelationEnvelope

        with sup_app.app_context():
            session = db.session.get(Session, session_id)
            envelope = CommandEnvelope(
                command="stop",
                correlation=CorrelationEnvelope(
                    request_id=uuid4().hex,
                    dataflow_id="df-sup-1",
                    command_id=uuid4().hex,
                    watchdog_id="supervisor",
                    recovery_id=None,
                ),
                target_device_id=None,
            )

            with pytest.raises(RuntimeNotTracked) as exc_info:
                auto_supervisor.dispatch(session, envelope)
            assert exc_info.value.dataflow_id == "df-sup-1"


class TestShutdownFinalization:
    """Packet 29 — a clean daemon shutdown is a completion boundary too: it
    completes each session's acquisitions and enqueues any EDF/PVFS merge
    without waiting for it or owning hardware."""

    def test_clean_shutdown_completes_and_schedules_multi_component_output(
        self, sup_app, tmp_path
    ):
        from app.domain.enums import SinkType
        from app.output.managed_file import allocate_continuation, create
        from app.repositories.output_files import (
            ACQUISITION_COMPLETE,
            ARTIFACT_MERGE_PENDING,
            OutputFilesRepository,
        )
        from app.services.output_finalization import COMPLETION_SHUTDOWN

        with sup_app.app_context():
            session = _create_session_config_shape_session(
                name="shutdown-finalize",
                dataflow_id="df-shutdown-final",
                hardware_id="001",
            )

            head = create(
                tmp_path / "rec.bin",
                dataflow_id=session.dataflow_id,
                sink_type=SinkType.CSV,
                session_id=session.id,
            )
            head.write(b"seg0")
            logical = head.record.logical_sink_id
            head.close()
            cont = allocate_continuation(head.record)
            cont.write(b"seg1")
            cont.close()

            outcomes = HostSupervisor()._schedule_session_finalization(
                session, completion_cause=COMPLETION_SHUTDOWN
            )

            repo = OutputFilesRepository()
            assert len(outcomes) == 1
            assert outcomes[0].completion_cause == COMPLETION_SHUTDOWN
            assert outcomes[0].finalization_scheduled is True
            assert repo.get_head(logical).artifact_state == ARTIFACT_MERGE_PENDING
            assert (
                repo.list_components(logical)[-1].acquisition_state
                == ACQUISITION_COMPLETE
            )


# ---------------------------------------------------------------------------
# Slice 7 — reconcile() / reattach (acceptance #3)
# ---------------------------------------------------------------------------


class TestReconcile:
    def test_reconcile_skips_session_without_runtime_port(self, sup_app):
        """Historical dataflow ids are not startup spawn requests."""
        with sup_app.app_context():
            session = _create_session_config_shape_session(
                name="raw-no-port",
                dataflow_id="df-raw-no-port",
                hardware_id="002",
            )

            fresh_sup = HostSupervisor()
            fresh_sup.reconcile([session])

            assert fresh_sup._children == {}

    def test_adopt_only_reconcile_marks_dead_host_uncertain_without_respawn(
        self, sup_app, session_id, monkeypatch
    ):
        with sup_app.app_context():
            session = db.session.get(Session, session_id)
            ownerships = RuntimeOwnershipRepository()
            ownerships.create_starting(
                runtime_id="rt-restart-dead",
                session_id=session.id,
                dataflow_id=session.dataflow_id,
                manifest_hash=HostSupervisor._build_manifest(session).hash,
                token="restart-token",
            )
            ownerships.mark_running("rt-restart-dead", pid=1234, port=65530)
            session.runtime_port = 65530
            session.runtime_token = "restart-token"
            db.session.commit()

            fresh_sup = HostSupervisor()
            spawn_calls = []
            monkeypatch.setattr(
                fresh_sup,
                "spawn",
                lambda *args, **kwargs: spawn_calls.append((args, kwargs)),
            )
            monkeypatch.setattr(
                fresh_sup,
                "_probe_status",
                lambda port: (_ for _ in ()).throw(ConnectionError("dead host")),
            )

            report = fresh_sup.reconcile([session], adopt_only=True)

            db.session.expire_all()
            ownership = ownerships.get("rt-restart-dead")
            assert spawn_calls == []
            assert fresh_sup._children == {}
            assert ownership.state is RuntimeOwnershipState.UNCERTAIN
            assert ownership.details["reason"] == "restart_adoption_probe_failed"
            assert report["adopted"] == []
            assert report["uncertain"][0]["runtime_id"] == "rt-restart-dead"

    def test_adopt_only_reconcile_adopts_exact_live_identity(
        self, sup_app, session_id, monkeypatch
    ):
        with sup_app.app_context():
            session = db.session.get(Session, session_id)
            manifest = HostSupervisor._build_manifest(session)
            ownerships = RuntimeOwnershipRepository()
            ownerships.create_starting(
                runtime_id="rt-restart-live",
                session_id=session.id,
                dataflow_id=session.dataflow_id,
                manifest_hash=manifest.hash,
                token="restart-token",
            )
            ownerships.mark_running("rt-restart-live", pid=1234, port=62000)
            session.runtime_port = 62000
            session.runtime_token = "restart-token"
            db.session.commit()

            fresh_sup = HostSupervisor()
            monkeypatch.setattr(
                fresh_sup,
                "_probe_status",
                lambda port: {
                    "runtime_id": "rt-restart-live",
                    "dataflow_id": session.dataflow_id,
                    "manifest_hash": manifest.hash,
                },
            )

            report = fresh_sup.reconcile([session], adopt_only=True)

            ownership = ownerships.get("rt-restart-live")
            assert report == {"adopted": [session.dataflow_id], "uncertain": []}
            assert fresh_sup._children[session.dataflow_id].proc is None
            assert ownership.state is RuntimeOwnershipState.ADOPTED


# ---------------------------------------------------------------------------
# Packet 6 — WatchdogProcessDriver (runtime_host supervises a watchdog process)
# ---------------------------------------------------------------------------


class _FakeWatchdogProc:
    """Stand-in for the ``Popen`` handle of a spawned watchdog process child.

    ``exit_code`` starts ``None`` ("still alive"); Unit 8 tests mutate it to
    simulate a crash landing between two ``poll_health()``/``/status`` calls.
    """

    def __init__(self, *, pid: int = 54321, ready: bool = True) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.stdout = iter(["READY\n"] if ready else [])
        self.exit_code: int | None = None

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


def _fake_popen(proc: _FakeWatchdogProc):
    calls: list[tuple[list[str], dict]] = []

    def _popen(args, **kwargs):
        calls.append((list(args), kwargs))
        return proc

    _popen.calls = calls
    return _popen


def _sequential_fake_popen(procs: list[_FakeWatchdogProc]):
    """Like ``_fake_popen``, but returns a NEW proc per call — models a respawn."""
    calls: list[tuple[list[str], dict]] = []
    remaining = list(procs)

    def _popen(args, **kwargs):
        calls.append((list(args), kwargs))
        return remaining.pop(0)

    _popen.calls = calls
    return _popen


def _wpd_manifest(dataflow_id: str = "df-wpd-1") -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id=dataflow_id,
        policy=PolicyMode.RECOMMEND,
        device_flows=(
            DeviceFlow(
                device_id="dev-a",
                name="device-a",
                nickname=None,
                hardware_id="003",
                port="usb-1",
                parameters={},
                sink_type=SinkType.CSV,
                sink_location="/data/dev-a.csv",
            ),
        ),
    )


class TestWatchdogProcessDriver:
    """Unit-level coverage using injected popen/pid_alive seams — no real
    subprocess or Morelia needed (acceptance #1, #4)."""

    def test_start_spawns_watchdog_process_with_fresh_identity_and_token(
        self, tmp_path
    ):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        proc = _FakeWatchdogProc()
        popen = _fake_popen(proc)

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-1",
            ingest_url="http://127.0.0.1:9",
            popen=popen,
        )
        assert driver.phase is RuntimePhase.IDLE

        driver.preflight()
        assert driver.phase is RuntimePhase.PREFLIGHT
        assert driver.watchdog_id is None  # not spawned yet

        driver.start()
        assert driver.phase is RuntimePhase.RUNNING
        assert driver.watchdog_id is not None
        assert driver.watchdog_pid == proc.pid
        assert driver.watchdog_token_hash is not None
        assert driver.watchdog_state is WatchdogProcessState.RUNNING
        assert driver.adopted is False

        args, _kwargs = popen.calls[0]
        assert args[:3] == [sys.executable, "-m", "app.watchdog_process"]
        assert "--watchdog-id" in args
        assert args[args.index("--runtime-id") + 1] == "rt-1"
        assert "--session-id" not in args

        driver.stop()
        assert proc.terminated is True
        assert driver.phase is RuntimePhase.STOPPED
        assert driver.watchdog_state is WatchdogProcessState.STOPPED

    def test_start_uses_authenticated_watchdog_pid_instead_of_launcher_pid(
        self, tmp_path
    ):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        proc = _FakeWatchdogProc(pid=100)
        proc.stdout = iter(["READY:43210\n"])
        popen = _fake_popen(proc)

        class _ControlClient:
            def __init__(self, **_kwargs):
                pass

            def probe(self):
                args, _kwargs = popen.calls[0]
                return {
                    "watchdog_id": args[args.index("--watchdog-id") + 1],
                    "dataflow_id": manifest.dataflow_id,
                    "manifest_hash": manifest.hash,
                    "pid": 200,
                }

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-launcher",
            ingest_url="http://127.0.0.1:9",
            popen=popen,
            control_client_factory=_ControlClient,
        )

        driver.preflight()
        driver.start()

        assert proc.pid == 100
        assert driver.watchdog_pid == 200

    def test_stop_uses_control_channel_when_launcher_pid_differs(self, tmp_path):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        proc = _FakeWatchdogProc(pid=100)
        proc.stdout = iter(["READY:43210\n"])
        popen = _fake_popen(proc)
        alive = {200}
        stop_requests = []

        class _ControlClient:
            def __init__(self, **_kwargs):
                pass

            def probe(self):
                args, _kwargs = popen.calls[0]
                return {
                    "watchdog_id": args[args.index("--watchdog-id") + 1],
                    "dataflow_id": manifest.dataflow_id,
                    "manifest_hash": manifest.hash,
                    "pid": 200,
                }

            def stop_watchdog(self, **_kwargs):
                stop_requests.append(True)
                alive.discard(200)
                return {"status": "stopping"}

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-launcher-stop",
            ingest_url="http://127.0.0.1:9",
            popen=popen,
            pid_alive=lambda pid: pid in alive,
            control_client_factory=_ControlClient,
        )
        driver.preflight()
        driver.start()

        driver.stop()

        assert stop_requests == [True]
        assert proc.terminated is False
        assert driver.watchdog_state is WatchdogProcessState.STOPPED

    def test_start_without_ingest_url_raises(self, tmp_path):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-1",
            ingest_url=None,
            popen=_fake_popen(_FakeWatchdogProc()),
        )
        driver.preflight()
        with pytest.raises(RuntimeError, match="ingest URL"):
            driver.start()

    def test_adopts_live_pid_without_spawning(self, tmp_path):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        popen = _fake_popen(_FakeWatchdogProc())

        class _ControlClient:
            def __init__(self, **_kwargs):
                pass

            def probe(self):
                return {
                    "watchdog_id": "wd-orphan",
                    "dataflow_id": manifest.dataflow_id,
                    "manifest_hash": manifest.hash,
                    "pid": 424242,
                }

            def adopt(self, **_kwargs):
                return {"status": "adopted"}

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-2",
            ingest_url="http://127.0.0.1:9",
            control_token="control-token",
            adopt_watchdog_id="wd-orphan",
            adopt_watchdog_pid=424242,
            adopt_watchdog_control_port=43210,
            popen=popen,
            pid_alive=lambda pid: True,
            control_client_factory=_ControlClient,
        )
        assert driver.phase is RuntimePhase.RUNNING
        assert driver.adopted is True
        assert driver.watchdog_id == "wd-orphan"
        assert driver.watchdog_pid == 424242
        assert driver.watchdog_state is WatchdogProcessState.ADOPTED
        assert popen.calls == []  # adoption never spawns a new process

    def test_adoption_of_dead_pid_falls_through_to_idle(self, tmp_path):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-3",
            ingest_url="http://127.0.0.1:9",
            adopt_watchdog_id="wd-gone",
            adopt_watchdog_pid=1,
            popen=_fake_popen(_FakeWatchdogProc()),
            pid_alive=lambda pid: False,
        )
        assert driver.phase is RuntimePhase.IDLE
        assert driver.adopted is False
        assert driver.watchdog_id is None
        assert driver.watchdog_state is None

    def test_stop_gracefully_stops_authenticated_adopted_pid(self, tmp_path, monkeypatch):
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))

        killed_pids: list[int] = []
        import app.runtime_host.watchdog_process_driver as wpd_module

        monkeypatch.setattr(wpd_module, "_kill_pid", killed_pids.append)
        alive = {"value": True}

        class _ControlClient:
            def __init__(self, **_kwargs):
                pass

            def probe(self):
                return {
                    "watchdog_id": "wd-orphan",
                    "dataflow_id": manifest.dataflow_id,
                    "manifest_hash": manifest.hash,
                    "pid": 424242,
                }

            def adopt(self, **_kwargs):
                return {"status": "adopted"}

            def stop_watchdog(self, **_kwargs):
                alive["value"] = False
                return {"status": "stopping"}

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-4",
            ingest_url="http://127.0.0.1:9",
            control_token="control-token",
            adopt_watchdog_id="wd-orphan",
            adopt_watchdog_pid=424242,
            adopt_watchdog_control_port=43210,
            popen=_fake_popen(_FakeWatchdogProc()),
            pid_alive=lambda pid: alive["value"],
            control_client_factory=_ControlClient,
        )
        driver.stop()
        assert killed_pids == []
        assert driver.watchdog_state is WatchdogProcessState.STOPPED


class TestStatusExposesWatchdogIdentity:
    """Acceptance #2 — /status includes watchdog_id and watchdog process state."""

    def test_status_includes_watchdog_identity_and_state(self, tmp_path):
        from app.runtime_host.lifecycle import LifecycleSafetyGate
        from app.runtime_host.server import DataflowRuntimeHost

        manifest = _wpd_manifest(dataflow_id="df-status-1")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))

        class _ControlClient:
            def __init__(self, **_kwargs):
                pass

            def probe(self):
                return {
                    "watchdog_id": "wd-orphan",
                    "dataflow_id": manifest.dataflow_id,
                    "manifest_hash": manifest.hash,
                    "pid": os.getpid(),
                }

            def adopt(self, **_kwargs):
                return {"status": "adopted"}

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-status-1",
            ingest_url="http://127.0.0.1:9",
            control_token="control-token",
            adopt_watchdog_id="wd-orphan",
            adopt_watchdog_pid=os.getpid(),  # our own pid is guaranteed alive
            adopt_watchdog_control_port=43210,
            popen=_fake_popen(_FakeWatchdogProc()),
            control_client_factory=_ControlClient,
        )
        gate = LifecycleSafetyGate(manifest=manifest, driver=driver)
        host = DataflowRuntimeHost(
            gate=gate, manifest=manifest, driver=driver, runtime_id="rt-status-1"
        )
        with host:
            status = _get_status(host.port)

        assert status["runtime_id"] == "rt-status-1"
        assert status["dataflow_id"] == "df-status-1"
        assert status["manifest_hash"] == manifest.hash
        assert status["watchdog_id"] == "wd-orphan"
        assert status["watchdog_preflight_ready"] is True
        assert status["watchdog_pid"] == os.getpid()
        assert status["watchdog_state"] == "adopted"
        assert status["watchdog_respawn_count"] == 0
        assert status["watchdog_respawn_exhausted"] is False
        assert status["watchdog_exit_details"] is None


class TestStatusExposesRespawnState:
    """Unit 8 — GET /status detects a crash (via ``poll_health``) and surfaces
    the resulting respawn under the same runtime_id."""

    def test_status_probe_detects_crash_and_respawns_new_identity(self, tmp_path):
        from app.runtime_host.lifecycle import LifecycleSafetyGate
        from app.runtime_host.server import DataflowRuntimeHost

        manifest = _wpd_manifest(dataflow_id="df-respawn-status-1")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        proc1 = _FakeWatchdogProc(pid=1001)
        proc2 = _FakeWatchdogProc(pid=1002)

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-respawn-status-1",
            ingest_url="http://127.0.0.1:9",
            popen=_sequential_fake_popen([proc1, proc2]),
            respawn_max_attempts=3,
        )
        driver.preflight()
        driver.start()
        gate = LifecycleSafetyGate(manifest=manifest, driver=driver)
        host = DataflowRuntimeHost(
            gate=gate, manifest=manifest, driver=driver, runtime_id="rt-respawn-status-1"
        )
        with host:
            first_status = _get_status(host.port)
            original_watchdog_id = first_status["watchdog_id"]
            assert first_status["watchdog_pid"] == 1001

            proc1.exit_code = 1  # simulate the crash between two polls
            second_status = _get_status(host.port)

        assert second_status["watchdog_id"] is not None
        assert second_status["watchdog_id"] != original_watchdog_id
        assert second_status["watchdog_pid"] == 1002
        assert second_status["watchdog_state"] == "running"
        assert second_status["watchdog_respawn_count"] == 1
        assert second_status["watchdog_respawn_exhausted"] is False
        # runtime_host's own supervisory phase survives the watchdog crash.
        assert second_status["phase"] == "running"

    def test_status_probe_reports_respawn_exhausted_after_budget_runs_out(self, tmp_path):
        from app.runtime_host.lifecycle import LifecycleSafetyGate
        from app.runtime_host.server import DataflowRuntimeHost

        manifest = _wpd_manifest(dataflow_id="df-respawn-status-2")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        proc = _FakeWatchdogProc(pid=2001)

        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-respawn-status-2",
            ingest_url="http://127.0.0.1:9",
            popen=_sequential_fake_popen([proc]),
            respawn_max_attempts=0,
        )
        driver.preflight()
        driver.start()
        gate = LifecycleSafetyGate(manifest=manifest, driver=driver)
        host = DataflowRuntimeHost(
            gate=gate, manifest=manifest, driver=driver, runtime_id="rt-respawn-status-2"
        )
        with host:
            proc.exit_code = 1
            status = _get_status(host.port)

        assert status["watchdog_id"] is None
        assert status["watchdog_state"] == "crashed"
        assert status["watchdog_respawn_exhausted"] is True
        assert status["watchdog_exit_details"]["exit_code"] == 1


class TestWatchdogAdoptionAcrossRuntimeHostRestart:
    """Acceptance — a restarted runtime_host adopts a live, identity-matching
    watchdog process instead of abandoning the dataflow as uncertain."""

    def test_reconcile_blocks_when_live_process_has_no_authenticated_control_channel(
        self, sup_app, session_id, auto_supervisor
    ):
        with sup_app.app_context():
            session = db.session.get(Session, session_id)

            # A real, long-lived process stands in for an orphan-survived
            # watchdog process: pid_is_alive() makes a genuine OS call, so a
            # mock PID would not exercise the real liveness check.
            orphan = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"]
            )
            try:
                auto_supervisor._ownerships.create_starting(
                    runtime_id="rt-orphaned",
                    session_id=session.id,
                    dataflow_id="df-sup-1",
                    manifest_hash="irrelevant-hash",
                    token="irrelevant-token",
                )
                auto_supervisor._ownerships.set_watchdog(
                    "rt-orphaned",
                    watchdog_id="wd-orphaned",
                    token_hash="hash",
                    pid=orphan.pid,
                )

                # Dead port: nothing listens here, so reconcile()'s probe
                # raises and takes the "runtime_host unreachable" branch.
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", 0))
                    dead_port = s.getsockname()[1]

                from app.database import transaction

                with transaction():
                    session.runtime_port = dead_port
                    session.runtime_token = "stale-token"

                fresh_sup = HostSupervisor()
                fresh_sup.reconcile([db.session.get(Session, session_id)])

                assert fresh_sup._children.get("df-sup-1") is None
                db.session.expire_all()
                old_row = auto_supervisor._ownerships.get("rt-orphaned")
                assert old_row.state is RuntimeOwnershipState.RECOVERING
                assert old_row.details["recovery"]["phase"] == "retry_wait"
                assert (
                    old_row.details["recovery"]["reason"]
                    == "authenticated_watchdog_control_unavailable"
                )
                assert old_row.details["recovery"]["hardware_access"] == "blocked"
                assert orphan.poll() is None
            finally:
                orphan.terminate()
                orphan.wait(timeout=5)
