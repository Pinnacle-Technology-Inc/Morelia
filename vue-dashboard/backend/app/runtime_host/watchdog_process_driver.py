"""Runtime-host driver that supervises a watchdog child process."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from uuid import uuid4

import structlog
from structlog.contextvars import get_contextvars

from app.config import get_config
from app.domain.enums import CommsStatus, WatchdogProcessState
from app.runtime_child.driver import ReportCallback, RuntimePhase, RuntimeReport
from app.runtime_host.manifest import Manifest
from app.runtime_host.process_exit import wait_for_process_exit
from app.watchdog_process.control import WatchdogControlClient, WatchdogControlError

_log = structlog.get_logger(__name__)

PopenFn = Callable[..., subprocess.Popen]
PidAliveFn = Callable[[int], bool]
ControlClientFactory = Callable[..., WatchdogControlClient]
ProcessExitWaiter = Callable[..., int | None]


class WatchdogStartupError(RuntimeError):
    """Structured failure reported before the watchdog child became ready."""

    def __init__(self, payload: dict[str, object], *, log_path: str) -> None:
        self.error_type = str(payload.get("error_type") or "WatchdogStartupError")[:120]
        self.device_id = payload.get("device_id")
        self.sink_id = payload.get("sink_id")
        self.reason = str(payload.get("message") or "watchdog startup failed")[:500]
        super().__init__(f"{self.error_type}: {self.reason} (child log: {log_path})")


def pid_is_alive(pid: int) -> bool:
    """Best-effort, stdlib-only liveness check that needs no ``Popen`` handle.

    Adoption is the reason this exists: a freshly started runtime_host has no
    ``Popen`` object for a watchdog process it did not spawn itself, only the
    PID a previous runtime_host's ownership row persisted.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_is_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    else:
        return True


def _pid_is_alive_windows(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _kill_pid(pid: int) -> None:
    """Best-effort termination of a watchdog process we adopted (no Popen handle)."""
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            try:
                kernel32.TerminateProcess(handle, 1)
            finally:
                kernel32.CloseHandle(handle)
    else:
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)


class WatchdogProcessDriver:
    """Supervise one watchdog process on behalf of a runtime host."""

    def __init__(
        self,
        *,
        manifest: Manifest,
        manifest_path: str,
        on_report: ReportCallback,
        runtime_id: str,
        ingest_url: str | None,
        ingest_token: str | None = None,
        outbox_dir: str | None = None,
        hardware_lock_dir: str | None = None,
        control_token: str | None = None,
        driver_name: str = "morelia",
        adopt_watchdog_id: str | None = None,
        adopt_watchdog_pid: int | None = None,
        adopt_watchdog_control_port: int | None = None,
        respawn_max_attempts: int | None = None,
        respawn_retry_seconds: float | None = None,
        popen: PopenFn = subprocess.Popen,
        pid_alive: PidAliveFn = pid_is_alive,
        control_client_factory: ControlClientFactory = WatchdogControlClient,
        process_exit_waiter: ProcessExitWaiter = wait_for_process_exit,
    ) -> None:
        self._manifest = manifest
        self._manifest_path = manifest_path
        self._on_report = on_report
        self._runtime_id = runtime_id
        self._ingest_url = ingest_url or None
        self._ingest_token = ingest_token or None
        self._outbox_dir = outbox_dir or None
        self._hardware_lock_dir = hardware_lock_dir or None
        self._control_token = control_token or None
        self._driver_name = driver_name
        self._popen = popen
        self._pid_alive = pid_alive
        self._control_client_factory = control_client_factory
        self._process_exit_waiter = process_exit_waiter
        # reads WATCHDOG_OUTBOX_DIR directly.
        self._respawn_max_attempts = (
            respawn_max_attempts
            if respawn_max_attempts is not None
            else get_config().WATCHDOG_RESPAWN_MAX_ATTEMPTS
        )
        self._respawn_retry_seconds = (
            respawn_retry_seconds
            if respawn_retry_seconds is not None
            else get_config().WATCHDOG_RESPAWN_RETRY_DELAY_SECONDS
        )
        if self._respawn_max_attempts < 0:
            raise ValueError("respawn_max_attempts must be non-negative")
        if self._respawn_retry_seconds < 0:
            raise ValueError("respawn_retry_seconds must be non-negative")

        self._phase = RuntimePhase.IDLE
        self._sequence = 0
        self._proc: subprocess.Popen | None = None
        self._log_path: str | None = None
        self._watchdog_id: str | None = None
        self._watchdog_pid: int | None = None
        self._watchdog_token_hash: str | None = None
        self._watchdog_control_token: str | None = None
        self._watchdog_control_port: int | None = None
        self._watchdog_state: WatchdogProcessState | None = None
        self._watchdog_exit_details: dict[str, object] | None = None
        self._adopted = False
        self._adoption_authenticated = False
        self._respawn_count = 0
        self._respawn_exhausted = False
        # Crash retirement and replacement publication are one fenced state
        # transition. Holding this lock through spawn prevents stop() from
        # crossing an unpublished child and leaving that child orphaned.
        self._state_lock = threading.RLock()
        self._supervision_stop = threading.Event()
        self._supervision_thread: threading.Thread | None = None

        if adopt_watchdog_id is not None and adopt_watchdog_pid is not None:
            self._try_adopt(
                adopt_watchdog_id,
                adopt_watchdog_pid,
                adopt_watchdog_control_port,
            )
            if self._watchdog_id is not None:
                self._ensure_supervision_started()

    # -- lifecycle -----------------------------------------------------------

    @property
    def phase(self) -> RuntimePhase:
        return self._phase

    def preflight(self) -> None:
        self._require(RuntimePhase.IDLE)
        self._phase = RuntimePhase.PREFLIGHT
        self._emit_all(phase=RuntimePhase.PREFLIGHT)

    def ensure_preflight_ready(self) -> None:
        """Complete the child watchdog barrier before the host says READY."""
        if self._phase is not RuntimePhase.PREFLIGHT:
            raise RuntimeError("watchdog preflight readiness requires PREFLIGHT phase")
        if self._proc is None and self._watchdog_id is None:
            self._spawn_watchdog_process()
        self._ensure_supervision_started()

    def start(self) -> None:
        self._require(RuntimePhase.PREFLIGHT)
        if self._proc is None and self._watchdog_id is None:
            self._spawn_watchdog_process()
        self._ensure_supervision_started()
        self._phase = RuntimePhase.RUNNING
        self._emit_all(phase=RuntimePhase.RUNNING)

    @property
    def watchdog_preflight_ready(self) -> bool:
        return self._watchdog_id is not None and self._watchdog_state in (
            WatchdogProcessState.RUNNING,
            WatchdogProcessState.ADOPTED,
        )

    def stop(self) -> None:
        self._require(RuntimePhase.PREFLIGHT, RuntimePhase.RUNNING, RuntimePhase.STOPPED)
        if self._phase is RuntimePhase.STOPPED:
            return
        with self._state_lock:
            self._phase = RuntimePhase.STOPPING
            if self._watchdog_id is not None:
                self._watchdog_state = WatchdogProcessState.STOPPING
            self._supervision_stop.set()
        self._emit_all(phase=RuntimePhase.STOPPING)
        try:
            self._terminate_watchdog_process()
        finally:
            self._join_supervision_thread()
        with self._state_lock:
            self._phase = RuntimePhase.STOPPED
            if self._watchdog_id is not None:
                self._watchdog_state = WatchdogProcessState.STOPPED
        self._emit_all(phase=RuntimePhase.STOPPED, comms=CommsStatus.STOPPED)

    def close(self) -> None:
        if self._phase not in (RuntimePhase.STOPPED, RuntimePhase.CLOSED):
            try:
                self.stop()
            except Exception:
                _log.error(
                    "stop during close failed — forcing phase to CLOSED",
                    runtime_id=self._runtime_id,
                    phase=self._phase.value,
                    exc_info=True,
                )
        self._supervision_stop.set()
        self._join_supervision_thread()
        self._phase = RuntimePhase.CLOSED

    def recover(self, recovery_id: str, device_id: str) -> None:
        self._require(RuntimePhase.RUNNING)
        with self._state_lock:
            port = self._watchdog_control_port
            token = self._watchdog_control_token
            state = self._watchdog_state
        if port is None or token is None or state is not WatchdogProcessState.RUNNING:
            raise RuntimeError("watchdog recovery control is unavailable")
        client = self._control_client_factory(port=port, token=token)
        client.recover(recovery_id=recovery_id, device_id=device_id)

    # -- watchdog identity, surfaced by server.py's GET /status --------------

    @property
    def watchdog_id(self) -> str | None:
        return self._watchdog_id

    @property
    def watchdog_pid(self) -> int | None:
        return self._watchdog_pid

    @property
    def watchdog_token_hash(self) -> str | None:
        return self._watchdog_token_hash

    @property
    def watchdog_control_port(self) -> int | None:
        return self._watchdog_control_port

    @property
    def watchdog_state(self) -> WatchdogProcessState | None:
        return self._watchdog_state

    @property
    def adopted(self) -> bool:
        return self._adopted

    @property
    def log_path(self) -> str | None:
        """Path to the watchdog process child's stderr log, if we spawned one."""
        return self._log_path

    @property
    def watchdog_exit_details(self) -> dict[str, object] | None:
        """Provenance for the most recent crash, e.g. ``{"exit_code": 1}``."""
        return self._watchdog_exit_details

    @property
    def respawn_count(self) -> int:
        """How many times a crashed watchdog process has been replaced so far."""
        return self._respawn_count

    @property
    def respawn_exhausted(self) -> bool:
        """True once a crash was observed with no respawn attempts left.

        A one-way trap (see ``_handle_crash``): once set, this driver will
        not attempt another respawn under this ``runtime_id`` — the control
        plane must escalate instead of the crash/respawn loop running
        forever.
        """
        return self._respawn_exhausted

    def status_snapshot(self) -> dict[str, object]:
        """Return one generation-consistent, serializable supervision snapshot."""
        with self._state_lock:
            return {
                "phase": self._phase.value,
                "watchdog_id": self._watchdog_id,
                "watchdog_pid": self._watchdog_pid,
                "watchdog_token_hash": self._watchdog_token_hash,
                "watchdog_control_port": self._watchdog_control_port,
                "watchdog_state": (
                    self._watchdog_state.value if self._watchdog_state is not None else None
                ),
                "watchdog_preflight_ready": self.watchdog_preflight_ready,
                "watchdog_respawn_count": self._respawn_count,
                "watchdog_respawn_exhausted": self._respawn_exhausted,
                "watchdog_exit_details": (
                    dict(self._watchdog_exit_details)
                    if self._watchdog_exit_details is not None
                    else None
                ),
            }

    # -- crash detection + respawn --------------------------------------------

    def _ensure_supervision_started(self) -> None:
        """Start one daemon thread that blocks until the owned process exits."""
        with self._state_lock:
            if self._supervision_stop.is_set():
                return
            if self._supervision_thread is not None and self._supervision_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._supervise_watchdog_process,
                name=f"watchdog-supervisor-{self._runtime_id}",
                daemon=True,
            )
            self._supervision_thread = thread
            thread.start()

    def _supervise_watchdog_process(self) -> None:
        """Wait for child exits and perform bounded local respawn without HTTP polling."""
        while not self._supervision_stop.is_set():
            with self._state_lock:
                process = self._proc
                process_id = self._watchdog_pid
                watchdog_id = self._watchdog_id
                retry_needed = (
                    process_id is None
                    and self._watchdog_state is WatchdogProcessState.CRASHED
                    and not self._respawn_exhausted
                    and self._phase in (RuntimePhase.PREFLIGHT, RuntimePhase.RUNNING)
                )

            if process_id is None:
                if not retry_needed:
                    return
                if self._supervision_stop.wait(self._respawn_retry_seconds):
                    return
                with self._state_lock:
                    if (
                        not self._supervision_stop.is_set()
                        and self._watchdog_id is None
                        and not self._respawn_exhausted
                    ):
                        self._attempt_respawn()
                continue

            try:
                exit_code = self._process_exit_waiter(process, process_id=process_id)
            except Exception as exc:
                _log.error(
                    "watchdog process exit wait failed",
                    runtime_id=self._runtime_id,
                    watchdog_id=watchdog_id,
                    pid=process_id,
                    error=type(exc).__name__,
                    exc_info=True,
                )
                if self._supervision_stop.wait(self._respawn_retry_seconds):
                    return
                continue

            if self._supervision_stop.is_set():
                return
            with self._state_lock:
                if (
                    self._watchdog_id != watchdog_id
                    or self._watchdog_pid != process_id
                    or self._phase not in (RuntimePhase.PREFLIGHT, RuntimePhase.RUNNING)
                ):
                    continue
                self._handle_crash(exit_code)

    def _join_supervision_thread(self) -> None:
        with self._state_lock:
            thread = self._supervision_thread
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout=get_config().WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS)
        if thread.is_alive():
            _log.warning(
                "watchdog supervision thread did not exit before deadline",
                runtime_id=self._runtime_id,
                thread=thread.name,
            )
            return
        with self._state_lock:
            if self._supervision_thread is thread:
                self._supervision_thread = None

    def _handle_crash(self, exit_code: int | None) -> None:
        """Retire the dead identity, then respawn a replacement if budget allows.

        Clears the crashed identity BEFORE attempting a replacement so any concurrent command
        will be marked as stale immediately.
        The replacement keeps this driver's runtime_id``/manifest/dataflow
        unchanged and gets a fresh watchdog_id + token
        """
        stale_watchdog_id = self._watchdog_id
        _log.error(
            "watchdog process crashed",
            runtime_id=self._runtime_id,
            watchdog_id=stale_watchdog_id,
            exit_code=exit_code,
        )
        self._proc = None
        self._adopted = False
        self._adoption_authenticated = False
        self._watchdog_id = None
        self._watchdog_pid = None
        self._watchdog_token_hash = None
        self._watchdog_control_token = None
        self._watchdog_control_port = None
        self._watchdog_state = WatchdogProcessState.CRASHED
        self._watchdog_exit_details = {
            "exit_code": exit_code,
            "watchdog_id": stale_watchdog_id,
        }

        self._attempt_respawn()

    def _attempt_respawn(self) -> None:
        """Spawn a replacement watchdog if the budget allows.

        Called after an observed crash and by the supervisor loop when a previous
        attempt failed before READY. Each failed attempt consumes budget so a
        permanent startup failure cannot create an infinite process loop.
        """
        if self._respawn_count >= self._respawn_max_attempts:
            self._respawn_exhausted = True
            _log.error(
                "watchdog respawn budget exhausted",
                runtime_id=self._runtime_id,
                attempts=self._respawn_count,
            )
            return

        self._respawn_count += 1
        self._watchdog_state = WatchdogProcessState.STARTING
        try:
            self._spawn_watchdog_process()
        except Exception:
            _log.error(
                "watchdog respawn attempt failed",
                runtime_id=self._runtime_id,
                attempt=self._respawn_count,
                exc_info=True,
            )
            self._watchdog_state = WatchdogProcessState.CRASHED

    # -- adoption -------------------------------------------------------------

    def _try_adopt(self, watchdog_id: str, pid: int, control_port: int | None) -> None:
        """Adopt a pre-existing watchdog process instead of spawning a fresh one.

        Deliberately does not emit a report: this runs from ``__init__``,
        before the caller has had a chance to patch ``on_report`` to the real
        host callback (see ``app/runtime_host/__main__.py``), so any report
        emitted here would be silently lost. ``/status`` reads
        ``watchdog_id``/``watchdog_state`` directly from this driver, not from
        the report ring, so that is not a problem for visibility.
        """
        if not self._pid_alive(pid):
            _log.info(
                "watchdog adoption skipped — pid not alive",
                runtime_id=self._runtime_id,
                watchdog_id=watchdog_id,
                pid=pid,
            )
            return
        if control_port is None or self._control_token is None:
            _log.warning(
                "watchdog adoption deferred — authenticated control evidence unavailable",
                runtime_id=self._runtime_id,
                watchdog_id=watchdog_id,
                pid=pid,
            )
            return
        client = self._control_client_factory(port=control_port, token=self._control_token)
        try:
            evidence = client.probe()
        except WatchdogControlError as exc:
            _log.warning(
                "watchdog adoption probe failed",
                runtime_id=self._runtime_id,
                watchdog_id=watchdog_id,
                pid=pid,
                error=type(exc).__name__,
            )
            return
        expected = {
            "watchdog_id": watchdog_id,
            "dataflow_id": self._manifest.dataflow_id,
            "manifest_hash": self._manifest.hash,
            "pid": pid,
        }
        if any(evidence.get(key) != value for key, value in expected.items()):
            _log.warning(
                "watchdog adoption rejected — authenticated identity mismatch",
                runtime_id=self._runtime_id,
                watchdog_id=watchdog_id,
                pid=pid,
            )
            return
        try:
            client.adopt(new_runtime_id=self._runtime_id, recovery_id=uuid4().hex)
        except WatchdogControlError as exc:
            _log.warning(
                "watchdog adoption command failed",
                runtime_id=self._runtime_id,
                watchdog_id=watchdog_id,
                error=type(exc).__name__,
            )
            return
        self._watchdog_id = watchdog_id
        self._watchdog_pid = pid
        self._watchdog_control_token = self._control_token
        self._watchdog_control_port = control_port
        self._watchdog_state = WatchdogProcessState.ADOPTED
        self._adopted = True
        self._adoption_authenticated = True
        self._phase = RuntimePhase.RUNNING
        _log.info(
            "watchdog process adopted",
            runtime_id=self._runtime_id,
            watchdog_id=watchdog_id,
            pid=pid,
        )

    # -- process management ---------------------------------------------------

    def _spawn_watchdog_process(self) -> None:
        if self._ingest_url is None:
            raise RuntimeError(
                "cannot spawn a watchdog process without an ingest URL "
                "(INGEST_BASE_URL is unset)"
            )
        watchdog_id = uuid4().hex
        token = self._control_token or secrets.token_hex(32)

        args = [
            sys.executable, "-m", "app.watchdog_process",
            "--manifest", self._manifest_path,
            "--runtime-id", self._runtime_id,
            "--watchdog-id", watchdog_id,
            "--ingest-url", self._ingest_url,
            "--driver", self._driver_name,
        ]
        if self._ingest_token:
            args += ["--ingest-token", self._ingest_token]
        if self._outbox_dir:
            args += ["--outbox-dir", self._outbox_dir]
        if self._hardware_lock_dir:
            args += ["--hardware-lock-dir", self._hardware_lock_dir]
        args += ["--control-token", token]

        # stderr MUST land somewhere a human can read it — see the identical
        # rationale in HostSupervisor.spawn().
        log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="ged-watchdog-")
        log_handle = os.fdopen(log_fd, "w", encoding="utf-8")

        popen_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = self._popen(
            args,
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            **popen_kwargs,
        )
        log_handle.close()  # child holds its own fd; this process doesn't write to it

        ready = False
        control_port: int | None = None
        startup_error: WatchdogStartupError | None = None
        try:
            for line in proc.stdout:
                value = line.strip()
                if value.startswith("ERROR:"):
                    payload = json.loads(value.split(":", 1)[1])
                    if isinstance(payload, dict):
                        startup_error = WatchdogStartupError(payload, log_path=log_path)
                    break
                if value == "READY":
                    ready = True
                    break
                if value.startswith("READY:"):
                    control_port = int(value.split(":", 1)[1])
                    ready = True
                    break
        except Exception as exc:
            _log.warning(
                "reading watchdog READY handshake failed",
                runtime_id=self._runtime_id,
                watchdog_id=watchdog_id,
                error=type(exc).__name__,
                message=str(exc),
            )

        if not ready:
            proc.terminate()
            with suppress(Exception):
                proc.wait(timeout=get_config().WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS)
            if startup_error is not None:
                raise startup_error
            raise RuntimeError(
                f"watchdog process for runtime {self._runtime_id!r} exited before "
                f"READY (child log: {log_path})"
            )

        watchdog_pid = proc.pid
        if control_port is not None:
            client = self._control_client_factory(port=control_port, token=token)
            try:
                evidence = client.probe()
            except WatchdogControlError as exc:
                proc.terminate()
                with suppress(Exception):
                    proc.wait(timeout=get_config().WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS)
                raise RuntimeError(
                    "watchdog authenticated post-spawn probe failed "
                    f"(child log: {log_path})"
                ) from exc
            expected = {
                "watchdog_id": watchdog_id,
                "dataflow_id": self._manifest.dataflow_id,
                "manifest_hash": self._manifest.hash,
            }
            probed_pid = evidence.get("pid")
            if (
                any(evidence.get(key) != value for key, value in expected.items())
                or not isinstance(probed_pid, int)
                or isinstance(probed_pid, bool)
                or probed_pid <= 0
            ):
                proc.terminate()
                with suppress(Exception):
                    proc.wait(timeout=get_config().WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS)
                raise RuntimeError(
                    "watchdog authenticated post-spawn identity mismatch "
                    f"(child log: {log_path})"
                )
            watchdog_pid = probed_pid

        self._proc = proc
        self._log_path = log_path
        self._watchdog_id = watchdog_id
        self._watchdog_pid = watchdog_pid
        self._watchdog_control_token = token
        self._watchdog_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._watchdog_control_port = control_port
        self._watchdog_state = WatchdogProcessState.RUNNING
        _log.info(
            "watchdog process spawned",
            runtime_id=self._runtime_id,
            watchdog_id=watchdog_id,
            pid=watchdog_pid,
            launcher_pid=proc.pid,
            reason=f"child stderr log: {log_path}",
        )

    def _terminate_watchdog_process(self) -> None:
        can_control = (
            self._watchdog_id is not None
            and self._watchdog_pid is not None
            and self._watchdog_control_port is not None
            and self._watchdog_control_token is not None
            and (self._proc is not None or self._adoption_authenticated)
        )
        if can_control:
            client = self._control_client_factory(
                port=self._watchdog_control_port,
                token=self._watchdog_control_token,
            )
            correlation = get_contextvars()
            shutdown_id = str(
                correlation.get("recovery_id")
                or correlation.get("command_id")
                or uuid4().hex
            )
            with suppress(WatchdogControlError):
                client.stop_watchdog(
                    recovery_id=shutdown_id,
                    command_id=correlation.get("command_id"),
                    request_id=correlation.get("request_id"),
                )
            config = get_config()
            deadline = time.monotonic() + config.WATCHDOG_PROCESS_STOP_TIMEOUT_SECONDS
            while self._pid_alive(self._watchdog_pid) and time.monotonic() < deadline:
                time.sleep(config.WATCHDOG_PROCESS_STOP_POLL_INTERVAL_SECONDS)
            if self._pid_alive(self._watchdog_pid):
                if self._proc is not None:
                    # A spawned Popen handle is stronger identity evidence than
                    # a fresh control probe: it names the exact child this host
                    # launched. Do not leave it alive merely because the child
                    # has stopped answering its own control socket.
                    _log.warning(
                        "watchdog graceful stop timed out — force killing spawned process",
                        runtime_id=self._runtime_id,
                        watchdog_id=self._watchdog_id,
                        pid=self._watchdog_pid,
                        action="force_kill",
                    )
                    with suppress(ProcessLookupError, PermissionError):
                        self._proc.kill()
                else:
                    # An adopted watchdog has no owned Popen handle. Re-authenticate
                    # immediately before PID-based termination so a reused PID is
                    # never killed on stale identity evidence.
                    try:
                        evidence = client.probe()
                    except WatchdogControlError:
                        evidence = {}
                    if (
                        evidence.get("pid") == self._watchdog_pid
                        and evidence.get("watchdog_id") == self._watchdog_id
                        and evidence.get("dataflow_id") == self._manifest.dataflow_id
                        and evidence.get("manifest_hash") == self._manifest.hash
                    ):
                        _kill_pid(self._watchdog_pid)

                reap_deadline = time.monotonic() + config.WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS
                while self._pid_alive(self._watchdog_pid) and time.monotonic() < reap_deadline:
                    time.sleep(config.WATCHDOG_PROCESS_STOP_POLL_INTERVAL_SECONDS)
            if self._pid_alive(self._watchdog_pid):
                raise RuntimeError(
                    f"authenticated watchdog {self._watchdog_id!r} did not stop"
                )
            if self._proc is not None:
                try:
                    self._proc.wait(timeout=get_config().WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS)
                except Exception:
                    # The authenticated watchdog is already dead; only its
                    # launcher/redirector remains, so it is safe to reap it.
                    with suppress(Exception):
                        self._proc.terminate()
                        self._proc.wait(timeout=get_config().WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS)
                    if self._proc.poll() is None:
                        with suppress(Exception):
                            self._proc.kill()
                self._proc = None
        elif self._proc is not None:
            # Legacy watchdog without a control endpoint: the Popen handle is
            # the only available process evidence.
            self._proc.terminate()
            try:
                self._proc.wait(
                    timeout=get_config().WATCHDOG_PROCESS_LEGACY_STOP_TIMEOUT_SECONDS
                )
            except Exception as exc:
                _log.warning(
                    "watchdog did not exit after terminate — killing",
                    runtime_id=self._runtime_id,
                    watchdog_id=self._watchdog_id,
                    pid=self._watchdog_pid,
                    error=type(exc).__name__,
                )
                with suppress(Exception):
                    self._proc.kill()
            self._proc = None
        if self._watchdog_id is not None:
            self._watchdog_state = WatchdogProcessState.STOPPED

    # -- reports ---------------------------------------------------------------

    def _emit_all(self, *, phase: RuntimePhase, comms: CommsStatus = CommsStatus.CURRENT) -> None:
        """Emit one supervision-lifecycle report.

        Unlike ``MoreliaRuntime``, this driver has no channel to the watchdog
        process's own per-device telemetry — that reports directly to the
        control plane (packet 05) — so ``devices`` is always empty. This
        report ring is now purely about runtime_host's own supervisory phase,
        not device health.
        """
        self._on_report(
            RuntimeReport(
                dataflow_id=self._manifest.dataflow_id,
                phase=phase,
                comms=comms,
                devices=(),
                sequence=self._sequence,
            )
        )
        self._sequence += 1

    def _require(self, *allowed: RuntimePhase) -> None:
        if self._phase not in allowed:
            allowed_names = ", ".join(phase.value for phase in allowed)
            raise RuntimeError(
                f"cannot do this from phase {self._phase.value!r}; "
                f"expected one of: {allowed_names}"
            )


__all__ = ["WatchdogProcessDriver", "pid_is_alive"]
