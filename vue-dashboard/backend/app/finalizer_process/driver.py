"""Control-plane ownership and supervision of the output-finalizer child."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from uuid import uuid4

import structlog

_log = structlog.get_logger(__name__)


class FinalizerProcessDriver:
    """Own exactly one finalizer child and replace it after an unexpected exit."""

    def __init__(
        self,
        *,
        config_name: str | None = None,
        ready_timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 1.0,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        start_monitor: bool = True,
    ) -> None:
        self._config_name = config_name
        self._ready_timeout = ready_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._popen = popen
        self._start_monitor = start_monitor
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._process: subprocess.Popen | None = None
        self._monitor: threading.Thread | None = None

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            self._spawn_locked()
            if self._start_monitor and self._monitor is None:
                self._monitor = threading.Thread(
                    target=self._monitor_loop,
                    name="output-finalizer-supervisor",
                    daemon=True,
                )
                self._monitor.start()

    def check_and_restart(self) -> bool:
        """Replace an exited child; return whether a restart occurred."""
        with self._lock:
            if self._stop_event.is_set():
                return False
            if self._process is None or self._process.poll() is not None:
                self._spawn_locked()
                return True
            return False

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        monitor = self._monitor
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join(timeout=self._poll_interval + 1.0)

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            try:
                self.check_and_restart()
            except Exception:
                _log.exception("failed to restart output finalizer")

    def _spawn_locked(self) -> None:
        args = [
            sys.executable,
            "-m",
            "app.finalizer_process",
            "--worker-id",
            uuid4().hex,
        ]
        if self._config_name:
            args.extend(["--config", self._config_name])
        process = self._popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        ready: queue.Queue[str] = queue.Queue(maxsize=1)
        threading.Thread(
            target=lambda: ready.put(process.stdout.readline()),
            name="output-finalizer-ready",
            daemon=True,
        ).start()
        try:
            line = ready.get(timeout=self._ready_timeout).strip()
        except queue.Empty as exc:
            process.terminate()
            raise RuntimeError("output finalizer did not become ready") from exc
        if line != "READY":
            process.terminate()
            raise RuntimeError(f"output finalizer exited before READY: {line!r}")
        self._process = process
        _log.info("output finalizer started", pid=getattr(process, "pid", None))


__all__ = ["FinalizerProcessDriver"]
