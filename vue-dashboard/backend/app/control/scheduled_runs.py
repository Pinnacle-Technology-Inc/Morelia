"""Single-owner background coordinator for due scheduled session runs."""

from __future__ import annotations

from threading import Event, Thread

import structlog

from app.services.sessions import execute_due_scheduled

_log = structlog.get_logger(__name__)


class ScheduledRunCoordinator:
    def __init__(self, app, *, interval_seconds: float = 1.0) -> None:
        self._app = app
        self._interval_seconds = max(float(interval_seconds), 0.1)
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(
            target=self._loop,
            name="scheduled-session-runs",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._interval_seconds * 2, 1.0))

    def run_once(self):
        with self._app.app_context():
            supervisor = self._app.extensions.get("host_supervisor")
            discovery = self._app.extensions.get("device_discovery_service")
            if supervisor is None or discovery is None:
                return []
            return execute_due_scheduled(
                supervisor=supervisor,
                discovery_service=discovery,
            )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                _log.exception("scheduled run coordinator pass failed")
            self._stop.wait(self._interval_seconds)
