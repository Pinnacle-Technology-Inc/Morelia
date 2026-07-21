import json
import subprocess
import sys

import click
import pytest
from click.testing import CliRunner

from app.cli.main import pinnacle


class FakeProcess:
    pid = 4321

    def poll(self) -> None:
        return None


def test_start_background_spawns_detached_child_and_writes_pid_file(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: False)
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: False)
    popen_calls = []

    def fake_popen(args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = CliRunner().invoke(pinnacle, ["start"])

    assert result.exit_code == 0
    assert "started daemon (pid 4321)" in result.output
    assert lifecycle.pid_file().read_text() == "4321\n"
    assert popen_calls[0][0] == [sys.executable, "-m", "app.cli.lifecycle", "serve"]
    assert popen_calls[0][1]["stdin"] == subprocess.DEVNULL
    assert popen_calls[0][1]["stderr"] == subprocess.STDOUT
    assert popen_calls[0][1]["stdout"].name == str(lifecycle.log_file())
    assert popen_calls[0][1]["stdout"].closed is False


def test_pid_running_detects_live_child_process() -> None:
    from app.cli import lifecycle

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert lifecycle._is_pid_running(process.pid) is True
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_start_refuses_existing_live_pid(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)

    result = CliRunner().invoke(pinnacle, ["start"])

    assert result.exit_code != 0
    assert "daemon already running (pid 1234)" in result.output


def test_start_debug_refuses_existing_live_pid(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)
    daemon_calls = []
    monkeypatch.setattr(lifecycle, "run_daemon", lambda *, debug: daemon_calls.append(debug))

    result = CliRunner().invoke(pinnacle, ["start", "--debug"])

    assert result.exit_code != 0
    assert "daemon already running (pid 1234)" in result.output
    assert daemon_calls == []


def test_start_debug_tracks_current_process_while_attached(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: False)
    observed_pid_files = []

    def fake_run_daemon(*, debug):
        observed_pid_files.append(lifecycle.pid_file().read_text())
        assert debug is True

    monkeypatch.setattr(lifecycle, "run_daemon", fake_run_daemon)

    result = CliRunner().invoke(pinnacle, ["start", "--debug"])

    assert result.exit_code == 0
    assert observed_pid_files == [f"{lifecycle.os.getpid()}\n"]
    assert not lifecycle.pid_file().exists()


def test_start_debug_ctrl_c_exits_130_and_clears_pid(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: False)

    def interrupting_run_daemon(*, debug):
        assert debug is True
        assert lifecycle.pid_file().exists()
        # run_daemon owns runtime-host teardown in its finally; the CLI wrapper's
        # only job on Ctrl+C is to exit 130 and clear the pid file.
        raise KeyboardInterrupt

    monkeypatch.setattr(lifecycle, "run_daemon", interrupting_run_daemon)

    result = CliRunner().invoke(pinnacle, ["start", "--debug"])

    assert result.exit_code == 130
    assert not lifecycle.pid_file().exists()


def test_run_daemon_tears_down_runtime_hosts_when_serving_stops(monkeypatch) -> None:
    """Ctrl+C (or any exit from the serving loop) must stop the child hosts
    in-process via the supervisor — NOT via the HTTP shutdown endpoint, which is
    already unreachable once app.run() stops serving. force=True is used so one
    wedged child cannot leave the rest running.
    """
    from flask import Flask

    from app.cli import lifecycle

    stop_all_calls = []

    class FakeSupervisor:
        def stop_all(self, *, force=False):
            stop_all_calls.append(force)
            return {
                "running_count": 0,
                "stopped_count": 0,
                "failed_count": 0,
                "failures": [],
                "forced": force,
            }

    app = Flask(__name__)
    app.config["CONTROL_PLANE_BASE_URL"] = "http://127.0.0.1:5000"
    app.extensions["host_supervisor"] = FakeSupervisor()

    def interrupting_run(**kwargs):
        raise KeyboardInterrupt

    app.run = interrupting_run
    monkeypatch.setattr(lifecycle, "create_app", lambda: app)
    monkeypatch.setattr(lifecycle, "_install_termination_signal_handler", lambda: None)

    with pytest.raises(KeyboardInterrupt):
        lifecycle.run_daemon(debug=False)

    assert stop_all_calls == [True]


def test_run_daemon_preserves_runtime_hosts_after_restart_quiesce(monkeypatch) -> None:
    from flask import Flask

    from app.cli import lifecycle
    from app.control.control_plane_state import ControlPlaneState

    stop_all_calls = []

    class FakeSupervisor:
        def stop_all(self, *, force=False):
            stop_all_calls.append(force)

    app = Flask(__name__)
    app.config["CONTROL_PLANE_BASE_URL"] = "http://127.0.0.1:5000"
    app.extensions["host_supervisor"] = FakeSupervisor()
    state = ControlPlaneState()
    state.begin_restart()
    app.extensions["control_plane_state"] = state
    app.run = lambda **kwargs: None
    monkeypatch.setattr(lifecycle, "create_app", lambda *args, **kwargs: app)
    monkeypatch.setattr(lifecycle, "_install_termination_signal_handler", lambda: None)

    lifecycle.run_daemon(debug=False)

    assert stop_all_calls == []


def test_run_daemon_starts_and_stops_finalizer_after_runtime_teardown(monkeypatch) -> None:
    from flask import Flask

    from app.cli import lifecycle

    events = []
    app = Flask(__name__)
    app.config["CONTROL_PLANE_BASE_URL"] = "http://127.0.0.1:5000"
    app.run = lambda **kwargs: events.append("served")

    class Finalizer:
        def stop(self):
            events.append("finalizer-stopped")

    monkeypatch.setattr(lifecycle, "create_app", lambda: app)
    monkeypatch.setattr(lifecycle, "_install_termination_signal_handler", lambda: None)
    monkeypatch.setattr(
        lifecycle,
        "_start_finalizer_process",
        lambda _app: events.append("finalizer-started") or Finalizer(),
    )
    monkeypatch.setattr(
        lifecycle, "_teardown_runtime_hosts", lambda _app: events.append("hosts-stopped")
    )

    lifecycle.run_daemon(debug=False)

    assert events == [
        "finalizer-started",
        "served",
        "hosts-stopped",
        "finalizer-stopped",
    ]


def test_restart_waits_for_old_pid_then_starts_adopt_only_daemon(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: pid == 1234)
    calls = []
    monkeypatch.setattr(
        lifecycle,
        "_request_control_plane_restart",
        lambda: calls.append(("quiesce", 1234)) or {"quiesced": True},
    )
    monkeypatch.setattr(
        lifecycle,
        "_wait_for_pid_exit",
        lambda pid, timeout_seconds=10.0: calls.append(("wait-dead", pid)) or True,
    )

    class FakeProcess:
        pid = 5678

        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(
        lifecycle,
        "_spawn_detached_daemon",
        lambda *, adopt_only=False: calls.append(("spawn", adopt_only)) or FakeProcess(),
    )
    monkeypatch.setattr(
        lifecycle,
        "_wait_for_daemon_serving",
        lambda process, timeout_seconds=10.0: calls.append(("wait-serving", process.pid)) or True,
    )
    monkeypatch.setattr(
        lifecycle,
        "_restart_reconciliation_report",
        lambda: {"adopted": ["df-1"], "uncertain": []},
    )

    result = CliRunner().invoke(pinnacle, ["restart"])

    assert result.exit_code == 0
    assert calls == [
        ("quiesce", 1234),
        ("wait-dead", 1234),
        ("spawn", True),
        ("wait-serving", 5678),
    ]
    assert lifecycle.pid_file().read_text() == "5678\n"
    assert json.loads(result.output)["reconciliation"]["adopted"] == ["df-1"]


def test_restart_refuses_replacement_while_old_pid_is_alive(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)
    monkeypatch.setattr(lifecycle, "_request_control_plane_restart", lambda: {"quiesced": True})
    monkeypatch.setattr(lifecycle, "_wait_for_pid_exit", lambda pid: False)
    spawn_calls = []
    monkeypatch.setattr(
        lifecycle,
        "_spawn_detached_daemon",
        lambda **kwargs: spawn_calls.append(kwargs),
    )

    result = CliRunner().invoke(pinnacle, ["restart"])

    assert result.exit_code != 0
    assert "refusing to start a replacement" in result.output
    assert spawn_calls == []
    assert lifecycle.pid_file().read_text() == "1234\n"


def test_shutdown_terminates_recorded_pid_and_removes_pid_file(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)
    terminated = []
    cascade_calls = []
    monkeypatch.setattr(lifecycle, "_terminate_pid", terminated.append)
    monkeypatch.setattr(lifecycle, "_running_runtime_host_count", lambda: 0)
    monkeypatch.setattr(
        lifecycle,
        "_cascade_shutdown_runtime_hosts",
        lambda *, force: cascade_calls.append(force),
    )

    result = CliRunner().invoke(pinnacle, ["shutdown"])

    assert result.exit_code == 0
    assert result.output == "shut down daemon (pid 1234)\n"
    assert cascade_calls == [False]
    assert terminated == [1234]
    assert not lifecycle.pid_file().exists()


def test_shutdown_cascades_runtime_hosts_before_terminating_daemon(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)
    calls = []
    monkeypatch.setattr(lifecycle, "_terminate_pid", lambda pid: calls.append(("terminate", pid)))
    monkeypatch.setattr(lifecycle, "_running_runtime_host_count", lambda: 2)
    monkeypatch.setattr(
        lifecycle,
        "_cascade_shutdown_runtime_hosts",
        lambda *, force: calls.append(("cascade", force)) or {},
    )
    monkeypatch.setattr(
        lifecycle.click,
        "confirm",
        lambda prompt, abort: calls.append(("confirm", prompt)),
    )

    result = CliRunner().invoke(pinnacle, ["shutdown"])

    assert result.exit_code == 0
    assert calls[0][0] == "confirm"
    assert "2 running runtime hosts" in calls[0][1]
    assert calls[1] == ("cascade", False)
    assert calls[2] == ("terminate", 1234)
    assert not lifecycle.pid_file().exists()


def test_shutdown_decline_keeps_daemon_and_pid_file(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)
    terminated = []
    cascade_calls = []
    monkeypatch.setattr(lifecycle, "_terminate_pid", terminated.append)
    monkeypatch.setattr(lifecycle, "_running_runtime_host_count", lambda: 1)
    monkeypatch.setattr(
        lifecycle,
        "_cascade_shutdown_runtime_hosts",
        lambda *, force: cascade_calls.append(force),
    )
    monkeypatch.setattr(
        lifecycle.click,
        "confirm",
        lambda prompt, abort: (_ for _ in ()).throw(click.Abort()),
    )

    result = CliRunner().invoke(pinnacle, ["shutdown"])

    assert result.exit_code != 0
    assert cascade_calls == []
    assert terminated == []
    assert lifecycle.pid_file().exists()


def test_shutdown_force_terminates_daemon_when_cascade_fails(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: True)
    terminated = []
    monkeypatch.setattr(lifecycle, "_terminate_pid", terminated.append)
    monkeypatch.setattr(lifecycle, "_running_runtime_host_count", lambda: 1)

    def fail_cascade(*, force):
        raise RuntimeError("runtime host is wedged")

    monkeypatch.setattr(lifecycle, "_cascade_shutdown_runtime_hosts", fail_cascade)

    result = CliRunner().invoke(pinnacle, ["shutdown", "--force"])

    assert result.exit_code == 0
    assert "runtime host is wedged" in result.output
    assert "forced shutdown" in result.output
    assert terminated == [1234]
    assert not lifecycle.pid_file().exists()


def test_shutdown_without_pid_file_fails_with_not_running(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: False)

    result = CliRunner().invoke(pinnacle, ["shutdown"])

    assert result.exit_code != 0
    assert "daemon not running" in result.output


def test_shutdown_without_pid_but_serving_asks_daemon_to_stop_itself(
    tmp_path,
    monkeypatch,
) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: True)
    calls = []
    monkeypatch.setattr(lifecycle, "_running_runtime_host_count", lambda: 0)
    monkeypatch.setattr(
        lifecycle,
        "_self_shutdown_control_plane",
        lambda *, force: calls.append(("self-shutdown", force)),
    )

    result = CliRunner().invoke(pinnacle, ["shutdown"])

    assert result.exit_code == 0
    assert calls == [("self-shutdown", False)]
    assert "shut down untracked daemon" in result.output


def test_start_debug_runs_attached_without_spawning_reloader(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: False)
    daemon_calls = []
    monkeypatch.setattr(lifecycle, "run_daemon", lambda *, debug: daemon_calls.append(debug))

    result = CliRunner().invoke(pinnacle, ["start", "--debug"])

    assert result.exit_code == 0
    assert daemon_calls == [True]


def test_start_refuses_when_port_already_serving_without_pid_file(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    # No pid file, but a live daemon holds the port — the orphan guard must fire.
    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: True)
    spawned = []
    monkeypatch.setattr(lifecycle, "_spawn_detached_daemon", lambda: spawned.append(True))

    result = CliRunner().invoke(pinnacle, ["start"])

    assert result.exit_code != 0
    assert "already serving" in result.output
    assert spawned == []


def test_status_reports_serving_when_pid_file_is_stale(tmp_path, monkeypatch) -> None:
    from app.cli import lifecycle

    # Recorded pid is dead, but a daemon is still serving the port (untracked).
    monkeypatch.setenv("PINNACLE_STATE_DIR", str(tmp_path))
    lifecycle.write_pid_file(1234)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: False)
    monkeypatch.setattr(lifecycle, "_daemon_is_serving", lambda: True)

    result = CliRunner().invoke(pinnacle, ["status"])

    assert result.exit_code == 0
    assert '"running": false' in result.output
    assert '"serving": true' in result.output


def test_run_daemon_binds_configured_url_without_reloader(monkeypatch) -> None:
    from app.cli import lifecycle

    run_calls = []

    class FakeApp:
        config = {"CONTROL_PLANE_BASE_URL": "http://127.0.0.1:5999"}

        def run(self, **kwargs) -> None:
            run_calls.append(kwargs)

    monkeypatch.setattr(lifecycle, "create_app", lambda: FakeApp())

    lifecycle.run_daemon(debug=True)

    assert run_calls == [
        {
            "host": "127.0.0.1",
            "port": 5999,
            "debug": True,
            "use_reloader": False,
        }
    ]
