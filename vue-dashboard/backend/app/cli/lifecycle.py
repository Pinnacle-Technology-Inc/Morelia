"""Lifecycle commands for the local Pinnacle control-plane daemon."""

from __future__ import annotations

import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse

import click

from app import create_app
from app.cli.daemon_client import DaemonClient
from app.cli.output import echo_json, exit_with_error
from app.config import get_config

PID_FILE_NAME = "pinnacle-daemon.pid"
LOG_FILE_NAME = "pinnacle-daemon.log"


@click.command(name="start")
@click.option("--debug", is_flag=True, help="Run attached with DEBUG logs.")
def start_command(debug: bool) -> None:
    """Start the control-plane daemon."""
    existing_pid = read_pid_file()
    if existing_pid is not None and _is_pid_running(existing_pid):
        exit_with_error(f"daemon already running (pid {existing_pid})")

    # Orphan guard: Refuse to spawn a duplicate when the port is already served;
    # Werkzeug's allow_reuse_address would otherwise let a second daemon bind
    # the same port, and only the newest would be tracked.
    if _daemon_is_serving():
        exit_with_error(
            f"daemon already serving at {_control_plane_base_url()} but not tracked by "
            f"{pid_file()}; stop the process on that port before starting a new one"
        )

    remove_pid_file()

    if debug:
        write_pid_file(os.getpid())
        try:
            run_daemon(debug=True)
        except KeyboardInterrupt:
            # run_daemon's finally already tore down the runtime hosts in-process.
            raise click.exceptions.Exit(130) from None
        finally:
            remove_pid_file()
        return

    process = _spawn_detached_daemon()
    if process.poll() is not None:
        remove_pid_file()
        exit_with_error(f"daemon failed to start; see log {log_file()}")

    write_pid_file(process.pid)
    click.echo(f"started daemon (pid {process.pid}) at {_control_plane_base_url()}")


@click.command(name="shutdown")
@click.option(
    "--force",
    is_flag=True,
    help="Terminate the control plane even if runtime-host teardown cannot be verified.",
)
def shutdown_command(force: bool) -> None:
    """Shut down the background control-plane daemon."""
    pid = read_pid_file()
    if pid is None or not _is_pid_running(pid):
        remove_pid_file()
        if _daemon_is_serving():
            _shutdown_untracked_serving_daemon(force=force)
            return
        exit_with_error("daemon not running")

    try:
        running_count = _running_runtime_host_count()
        if running_count and not force:
            click.confirm(
                f"This will stop {running_count} running runtime hosts and shut down "
                "the control plane. Continue?",
                abort=True,
            )
        _cascade_shutdown_runtime_hosts(force=force)
    except Exception as exc:
        if not force:
            exit_with_error(exc)
        click.echo(f"forced shutdown: runtime host teardown was not verified ({exc})")

    _terminate_pid(pid)
    remove_pid_file()
    click.echo(f"shut down daemon (pid {pid})")


@click.command(name="restart")
def restart_command() -> None:
    """Restart only the control plane and adopt live runtime hosts."""
    old_pid = read_pid_file()
    if old_pid is None or not _is_pid_running(old_pid):
        remove_pid_file()
        exit_with_error("daemon not running")

    _request_control_plane_restart()
    if not _wait_for_pid_exit(old_pid):
        exit_with_error(
            f"control plane pid {old_pid} did not exit; refusing to start a replacement"
        )

    remove_pid_file()
    process = _spawn_detached_daemon(adopt_only=True)
    if process.poll() is not None:
        exit_with_error(f"replacement daemon failed to start; see log {log_file()}")
    write_pid_file(process.pid)
    if not _wait_for_daemon_serving(process):
        exit_with_error(
            f"replacement daemon pid {process.pid} did not become ready; see log {log_file()}"
        )

    echo_json(
        {
            "previous_pid": old_pid,
            "pid": process.pid,
            "reconciliation": _restart_reconciliation_report(),
        }
    )


@click.command(name="status")
def status_command() -> None:
    """Show daemon status."""
    pid = read_pid_file()
    running = pid is not None and _is_pid_running(pid)
    if not running:
        remove_pid_file()
    echo_json(
        {
            "pid": pid if running else None,
            "pid_file": str(pid_file()),
            "running": running,
            # ``serving`` reveals an untracked daemon: serving True while running
            # False means a live daemon holds the port without a valid pid file.
            "serving": _daemon_is_serving(),
            "url": _control_plane_base_url(),
        }
    )


def run_daemon(*, debug: bool = False, adopt_only: bool = False) -> None:
    """Run the Flask daemon in the current process.

    Runtime-host teardown lives in the ``finally`` so it runs on EVERY exit from
    the serving loop — a clean return, Ctrl+C (KeyboardInterrupt), or a SIGTERM
    turned into an unwind by the handler below. It stops the child processes
    in-process through the supervisor, so it does not depend on the HTTP server
    still accepting connections (it has already stopped serving by this point).
    """
    if debug:
        os.environ["LOG_LEVEL"] = "DEBUG"
        get_config().LOG_LEVEL = "DEBUG"

    app = (
        create_app(config_overrides={"STARTUP_RECONCILIATION_ADOPT_ONLY": True})
        if adopt_only
        else create_app()
    )
    parsed_url = urlparse(app.config["CONTROL_PLANE_BASE_URL"])
    _install_termination_signal_handler()
    finalizer = _start_finalizer_process(app)
    scheduled_runs = _start_scheduled_run_coordinator(app)
    try:
        app.run(
            host=parsed_url.hostname or "127.0.0.1",
            port=parsed_url.port or 5000,
            debug=debug,
            use_reloader=False,
        )
    finally:
        if scheduled_runs is not None:
            scheduled_runs.stop()
        _teardown_runtime_hosts(app)
        if finalizer is not None:
            finalizer.stop()


def _start_finalizer_process(app):
    """Start the daemon-owned finalizer when enabled for this profile."""
    if not app.config.get("FINALIZER_PROCESS_ENABLED", False):
        return None
    from app.finalizer_process.driver import FinalizerProcessDriver

    driver = FinalizerProcessDriver(config_name=os.environ.get("FLASK_CONFIG", "development"))
    driver.start()
    app.extensions["finalizer_process_driver"] = driver
    return driver


def _start_scheduled_run_coordinator(app):
    """Start the single coordinator owned by the Pinnacle daemon process."""
    if not app.config.get("SESSION_SCHEDULER_ENABLED", False):
        return None
    from app.control.scheduled_runs import ScheduledRunCoordinator

    coordinator = ScheduledRunCoordinator(
        app,
        interval_seconds=app.config["SESSION_SCHEDULER_INTERVAL_SECONDS"],
    )
    coordinator.start()
    app.extensions["scheduled_run_coordinator"] = coordinator
    return coordinator


def pid_file() -> Path:
    return _state_dir() / PID_FILE_NAME


def log_file() -> Path:
    return _state_dir() / LOG_FILE_NAME


def _control_plane_base_url() -> str:
    return get_config().CONTROL_PLANE_BASE_URL


def _cascade_shutdown_runtime_hosts(*, force: bool) -> dict[str, object]:
    client = DaemonClient()
    response = client.post("/api/v1/runtimes/shutdown", {"force": force})
    if not isinstance(response, dict):
        raise ValueError("daemon runtime shutdown response must be an object")
    return response


def _self_shutdown_control_plane(*, force: bool) -> dict[str, object]:
    response = DaemonClient().post(
        "/api/v1/runtimes/control-plane-shutdown",
        {"force": force},
    )
    if not isinstance(response, dict):
        raise ValueError("daemon control-plane shutdown response must be an object")
    return response


def _request_control_plane_restart() -> dict[str, object]:
    response = DaemonClient().post("/api/v1/runtimes/control-plane-restart", {})
    if not isinstance(response, dict) or not response.get("quiesced"):
        raise ValueError("daemon restart response did not confirm quiescence")
    return response


def _restart_reconciliation_report() -> dict[str, object]:
    response = DaemonClient().get("/api/v1/runtimes/restart-report")
    if not isinstance(response, dict):
        raise ValueError("daemon restart reconciliation report must be an object")
    return response


def _shutdown_untracked_serving_daemon(*, force: bool) -> None:
    try:
        running_count = _running_runtime_host_count()
        if running_count and not force:
            click.confirm(
                f"This will stop {running_count} running runtime hosts and shut down "
                "the untracked control plane. Continue?",
                abort=True,
            )
        _self_shutdown_control_plane(force=force)
    except Exception as exc:
        if not force:
            exit_with_error(exc)
        click.echo(f"forced shutdown: daemon self-shutdown was not verified ({exc})")
    remove_pid_file()
    click.echo(f"shut down untracked daemon at {_control_plane_base_url()}")


def _teardown_runtime_hosts(app) -> None:
    """Stop every runtime-host child this daemon owns, in-process.

    Bulletproof teardown for any daemon exit (Ctrl+C, SIGTERM, or a crash that
    unwinds the serving loop): it drives the supervisor directly instead of the
    HTTP shutdown endpoint, which is already unreachable once serving stops.
    ``force=True`` so one wedged child cannot leave the rest running. Because
    ``stop_all`` also completes each session and releases its device claims, an
    interrupted daemon leaves no ACTIVE zombie holding a device behind.
    """
    supervisor = getattr(app, "extensions", {}).get("host_supervisor")
    if supervisor is None:
        return
    state = getattr(app, "extensions", {}).get("control_plane_state")
    if state is not None and state.preserve_runtime_hosts_on_exit:
        return
    try:
        with app.app_context():
            supervisor.stop_all(force=True)
    except Exception as exc:  # noqa: BLE001 - teardown must never mask the original exit
        click.echo(
            f"runtime host teardown during shutdown was not fully verified: {exc}",
            err=True,
        )


def _install_termination_signal_handler() -> None:
    """Turn SIGTERM into a normal unwind so run_daemon's teardown finally runs.

    Best-effort and POSIX-oriented: only the main thread may install handlers,
    and on Windows ``os.kill(pid, SIGTERM)`` hard-terminates without invoking
    this — there the graceful paths are the pre-terminate HTTP shutdown in
    ``shutdown_command`` and Ctrl+C (SIGINT -> KeyboardInterrupt), both covered.
    """

    def _raise_system_exit(signum, frame):  # noqa: ANN001 - signal handler signature
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _raise_system_exit)
    except (ValueError, OSError):
        pass  # not the main thread, or unsupported on this platform


def _running_runtime_host_count() -> int:
    active = DaemonClient().get("/api/v1/runtimes/")
    if not isinstance(active, list):
        raise ValueError("daemon runtime list response must be a list")
    return len(active)


def _daemon_is_serving(timeout_seconds: float = 0.5) -> bool:
    """Return True if something already accepts connections on the daemon port.

    A TCP connect to the configured control-plane address detects a live daemon
    even when the pid file is missing or stale, which is what the ``start``
    orphan guard relies on.
    """
    parsed = urlparse(_control_plane_base_url())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5000
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def read_pid_file() -> int | None:
    path = pid_file()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except ValueError:
        return None


def write_pid_file(pid: int) -> None:
    path = pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n")


def remove_pid_file() -> None:
    pid_file().unlink(missing_ok=True)


def _state_dir() -> Path:
    configured = os.environ.get("PINNACLE_STATE_DIR")
    if configured:
        return Path(configured)
    return _default_state_dir()


def _default_state_dir() -> Path:
    """Per-user state dir that survives OS temp cleanup (unlike %TEMP%).

    A pid file under the system temp dir can be swept by Windows Storage Sense /
    Disk Cleanup while the daemon is still alive, orphaning it. Use a stable
    per-user location instead: %LOCALAPPDATA% on Windows, $XDG_STATE_HOME (or
    ~/.local/state) elsewhere.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state"
        )
    return Path(base) / "pinnacle"


def _spawn_detached_daemon(*, adopt_only: bool = False) -> subprocess.Popen:
    log_path = log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("ab")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW

    try:
        args = [sys.executable, "-m", "app.cli.lifecycle", "serve"]
        if adopt_only:
            args.append("--adopt-only")
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=sys.platform != "win32",
        )
    except Exception:
        log_handle.close()
        raise


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _is_pid_running_windows(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_pid_running_windows(pid: int) -> bool:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, wintypes.LPDWORD)
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _terminate_pid(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _is_pid_running(pid):
            return
        time.sleep(0.05)


def _wait_for_pid_exit(pid: int, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_pid_running(pid):
            return True
        time.sleep(0.05)
    return not _is_pid_running(pid)


def _wait_for_daemon_serving(
    process: subprocess.Popen, timeout_seconds: float = 10.0
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _daemon_is_serving():
            return True
        time.sleep(0.05)
    return False


def main() -> None:
    if sys.argv[1:] in (["serve"], ["serve", "--adopt-only"]):
        adopt_only = "--adopt-only" in sys.argv[1:]
        write_pid_file(os.getpid())
        try:
            run_daemon(debug=False, adopt_only=adopt_only)
        finally:
            remove_pid_file()
        return
    raise SystemExit("usage: python -m app.cli.lifecycle serve")


if __name__ == "__main__":
    main()


__all__ = [
    "log_file",
    "pid_file",
    "read_pid_file",
    "restart_command",
    "run_daemon",
    "shutdown_command",
    "start_command",
    "status_command",
    "write_pid_file",
]
