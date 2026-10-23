"""Startup deadlines use real subprocess pipes and the persisted ownership ledger."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from app.control import supervisor as supervisor_module
from app.control.startup_output import startup_output
from app.control.supervisor import HostSupervisor
from app.database import db
from app.domain.enums import PolicyMode, RuntimeOwnershipState, SessionStatus
from app.domain.errors import RuntimeStartupFailed
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest


@pytest.fixture
def launch(app, tmp_path, monkeypatch):
    app.config.update(
        RUNTIME_DRIVER="morelia",
        RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS=0.4,
        RUNTIME_HOST_PROCESS_WAIT_TIMEOUT_SECONDS=0.2,
        WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS=0.2,
        WATCHDOG_OUTBOX_DIR=str(tmp_path / "outbox"),
        WATCHDOG_HARDWARE_LOCK_DIR=str(tmp_path / "locks"),
    )
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        supervisor_module, "_ensure_morelia_ready", lambda manifest: None
    )
    processes = []

    def run_script(script):
        def popen(args, **kwargs):
            assert args[1:3] == ["-m", "app.runtime_host"]
            process = real_popen([sys.executable, "-u", "-c", script], **kwargs)
            processes.append((process, args[args.index("--manifest") + 1]))
            return process

        monkeypatch.setattr(supervisor_module.subprocess, "Popen", popen)

    with app.app_context():
        flow = DeviceFlow(
            device_id="timeout-device",
            name="timeout-device",
            hardware_id="unused",
            port="unused",
            parameters={},
            sink_type="csv",
            sink_location=str(tmp_path / "unused.csv"),
        )
        manifest = Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="timeout-flow",
            policy=PolicyMode.RECOMMEND,
            device_flows=(flow,),
        )
        session = Session(
            name="startup timeout",
            status=SessionStatus.STARTING,
            policy=manifest.policy,
            dataflow_id=manifest.dataflow_id,
            device_flows=[flow.to_dict()],
        )
        db.session.add(session)
        db.session.commit()
        supervisor = HostSupervisor()
        try:
            yield supervisor, session, manifest, run_script, processes
        finally:
            supervisor.stop_event_poller()
            for process, _ in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize(
    "script",
    [
        "import time; time.sleep(60)",
        "import time; print('PORT:43210', flush=True); time.sleep(60)",
        "import sys,time; sys.stdout.write('PORT:43210'); sys.stdout.flush(); time.sleep(60)",
        "import time\nwhile True:\n print('still starting', flush=True)\n time.sleep(.01)",
    ],
)
def test_unready_child_times_out_without_releasing_unproven_ownership(
    app, launch, script
):
    supervisor, session, manifest, run_script, processes = launch
    run_script(script)
    started = time.monotonic()

    with pytest.raises(RuntimeStartupFailed) as error:
        supervisor.spawn(session, manifest=manifest)

    assert 0.35 <= time.monotonic() - started < 4
    assert error.value.details["error_type"] == "StartupTimeout"
    with app.test_request_context():
        response = app.handle_user_exception(error.value)
        assert response.status_code == 503
        assert response.get_json()["code"] == "runtime_startup_failed"
    assert "0.4 seconds" in str(error.value)
    assert processes[0][0].poll() is not None
    assert not Path(processes[0][1]).exists()
    assert not supervisor._children
    owner = db.session.scalar(db.select(RuntimeOwnership))
    assert owner.state is RuntimeOwnershipState.UNCERTAIN
    assert owner.details["reason"] == "startup_teardown_unproven"
    assert owner.details["host_process_identity"] is not None or sys.platform != "win32"
    assert session.runtime_port is None


def test_port_then_eof_is_not_readiness(app, launch):
    app.config["RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS"] = 5
    supervisor, session, manifest, run_script, _ = launch
    run_script("print('PORT:43210', flush=True)")

    with pytest.raises(RuntimeError, match="before reporting its port and READY"):
        supervisor.spawn(session, manifest=manifest)

    assert not supervisor._children
    assert session.runtime_port is None


def test_explicit_startup_error_is_preserved(app, launch):
    app.config["RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS"] = 5
    supervisor, session, manifest, run_script, _ = launch
    run_script(
        'print(\'ERROR:{"error_type":"DeviceError","message":"device unavailable"}\', flush=True)'
    )

    with pytest.raises(RuntimeStartupFailed, match="device unavailable") as error:
        supervisor.spawn(session, manifest=manifest)

    assert error.value.details["error_type"] == "DeviceError"


def test_cleanup_escalates_when_child_ignores_terminate(launch, monkeypatch):
    supervisor, session, manifest, run_script, processes = launch
    run_script("import time; time.sleep(60)")
    spawn = supervisor_module.subprocess.Popen

    def ignore_terminate(*args, **kwargs):
        process = spawn(*args, **kwargs)
        monkeypatch.setattr(process, "terminate", lambda: None)
        return process

    monkeypatch.setattr(supervisor_module.subprocess, "Popen", ignore_terminate)
    started = time.monotonic()
    with pytest.raises(RuntimeStartupFailed) as error:
        supervisor.spawn(session, manifest=manifest)
    assert time.monotonic() - started < 4
    assert error.value.details["error_type"] == "StartupTimeout"
    assert processes[0][0].poll() is not None


def test_ready_host_is_registered_before_deadline(app, launch):
    app.config["RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS"] = 5
    supervisor, session, manifest, run_script, processes = launch
    run_script(
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  self.send_response(200); self.end_headers(); self.wfile.write(b'{}')\n"
        "server = HTTPServer(('127.0.0.1', 0), Handler)\n"
        "print('PORT:' + str(server.server_port), flush=True)\n"
        "print('READY', flush=True)\n"
        "server.serve_forever()\n"
    )
    port = supervisor.spawn(session, manifest=manifest)
    assert session.runtime_port == port
    assert supervisor._children[manifest.dataflow_id].port == port
    assert (
        db.session.scalar(db.select(RuntimeOwnership)).state
        is RuntimeOwnershipState.RUNNING
    )
    assert processes[0][0].poll() is None


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_deadline_rejected_before_spawn(app, launch, value):
    supervisor, session, manifest, run_script, processes = launch
    app.config["RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS"] = value
    run_script("raise AssertionError('must not launch')")
    with pytest.raises(ValueError, match="finite and positive"):
        supervisor.spawn(session, manifest=manifest)
    assert not processes


def test_ready_child_pipe_keeps_draining_after_handshake():
    script = (
        "import sys\nprint('READY', flush=True)\n"
        "sys.stdout.write('x' * 1000000 + '\\n'); sys.stdout.flush()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        with startup_output(process.stdout, deadline=time.monotonic() + 3) as lines:
            assert next(lines).strip() == "READY"
        assert process.wait(timeout=3) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
