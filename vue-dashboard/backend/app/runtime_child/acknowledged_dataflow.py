"""Dashboard-owned shutdown instrumentation for the unchanged Morelia stream engine.

The adapter deliberately calls the legacy ``get_data`` function instead of
altering Morelia.Stream.  A source proxy and two no-op context-manager sinks
observe the existing teardown boundaries without changing acquisition code.
"""

from __future__ import annotations

import gc
import multiprocessing as mp
import os
import signal
import sys
import time
import uuid

from Morelia.shutdown import (
    ShutdownAction,
    ShutdownActor,
    ShutdownOutcome,
    ShutdownPhase,
    coordinate_shutdown,
)
from Morelia.Stream import source as legacy_source
from Morelia.Stream.data_flow import DataFlow as LegacyDataFlow


class ShutdownReporter:
    """Pickle-compatible worker reporter backed by a parent-owned queue."""

    def __init__(self, status_queue, shutdown_id: str, stream_index: int) -> None:
        self.status_queue = status_queue
        self.shutdown_id = shutdown_id
        self.stream_index = stream_index
        self.actor_pid = os.getpid()

    def emit(
        self,
        phase: ShutdownPhase,
        action: str,
        *,
        outcome: ShutdownOutcome = ShutdownOutcome.ACKNOWLEDGED,
        reason: str | None = None,
        error_type: str | None = None,
        sink_id: str | None = None,
        output_id: str | None = None,
        worker_exitcode: int | None = None,
        actor: ShutdownActor = ShutdownActor.DATAFLOW_WORKER,
        actor_pid: int | None = None,
    ) -> ShutdownAction:
        record = ShutdownAction(
            shutdown_id=self.shutdown_id,
            stream_index=self.stream_index,
            actor=actor,
            actor_pid=self.actor_pid if actor_pid is None else actor_pid,
            phase=phase,
            action=action,
            outcome=outcome,
            emitted_at_ns=time.time_ns(),
            sink_id=sink_id,
            output_id=output_id,
            worker_exitcode=worker_exitcode,
            error_type=error_type,
            reason=reason,
        )
        self.status_queue.put(record)
        return record

    def failed(self, action: str, exc: BaseException) -> ShutdownAction:
        return self.emit(
            ShutdownPhase.PHASE_FAILED,
            action,
            outcome=ShutdownOutcome.FAILED,
            error_type=type(exc).__name__,
            reason=str(exc),
            sink_id=getattr(exc, "sink_id", None),
        )


class _SourceLifecycleProxy:
    """Delegate a legacy pod while observing its existing context boundaries."""

    def __init__(self, source, stop_event, reporter: ShutdownReporter | None) -> None:
        self._source = source
        self._stop_event = stop_event
        self._reporter = reporter
        self._stop_observed = False
        self._source_stopped = False

    def __getattr__(self, name):
        return getattr(self._source, name)

    def __enter__(self):
        self._source.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self._source.__exit__(exc_type, exc, traceback)
        finally:
            if self._reporter is not None and self._stop_event.is_set() and not self._stop_observed:
                self._reporter.emit(ShutdownPhase.STOP_OBSERVED, "stop_event_observed")
                self._stop_observed = True

    def close_port(self):
        result = self._source.close_port()
        if self._reporter is not None and self._stop_event.is_set() and not self._source_stopped:
            self._reporter.emit(ShutdownPhase.SOURCE_STOPPED, "source_port_closed")
            self._source_stopped = True
        return result


class _LifecycleSentinel:
    """A no-op sink that brackets legacy ExitStack teardown in reverse order."""

    observe_on_scheduler = None

    def __init__(self, reporter: ShutdownReporter, *, starts_finalization: bool) -> None:
        self._reporter = reporter
        self._starts_finalization = starts_finalization

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._starts_finalization:
            self._reporter.emit(ShutdownPhase.SINKS_FINALIZING, "sink_close_started")
        elif exc_type is None:
            self._reporter.emit(ShutdownPhase.SINKS_FINALIZED, "all_sinks_closed")
        return False

    def flush(self, *_args, **_kwargs):
        return None


def _bind_sink_callbacks(sinks, on_sink_error, reporter: ShutdownReporter | None) -> None:
    for sink in sinks:
        bind_error = getattr(sink, "bind_error_callback", None)
        if callable(bind_error):
            bind_error(on_sink_error)
        bind_shutdown = getattr(sink, "bind_shutdown_reporter", None)
        if reporter is not None and callable(bind_shutdown):
            bind_shutdown(reporter)


def _database_config_for_worker() -> dict | None:
    """Snapshot the parent app's database settings for the spawn boundary."""
    from flask import current_app, has_app_context

    if not has_app_context():
        return None
    database_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        return None
    return {
        "SQLALCHEMY_DATABASE_URI": database_uri,
        "SQLITE_BUSY_TIMEOUT_MS": current_app.config.get("SQLITE_BUSY_TIMEOUT_MS", 5_000),
    }


def acknowledged_get_data_wrapper(
    duration_sec,
    manual_stop_event,
    source_class,
    source_dict,
    sinks_list,
    on_sink_error=None,
    on_source_error=None,
    shutdown_queue=None,
    shutdown_id=None,
    stream_index=0,
    source_recovery_window_sec=None,
    max_error_message_chars=500,
    source_error_emit_interval_sec=1.0,
    database_config=None,
):
    """Spawn target that instruments unchanged legacy ``get_data`` teardown."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass

    reporter = None
    if shutdown_queue is not None and shutdown_id is not None:
        reporter = ShutdownReporter(shutdown_queue, shutdown_id, stream_index)

    database_context = None
    try:
        if database_config is not None:
            from app.database import create_database_app

            database_context = create_database_app(
                config_overrides=database_config
            ).app_context()
            database_context.push()

        source = source_class(**source_dict)
        # This dashboard-only opt-in keeps heartbeat policy out of the legacy
        # DataFlow API while allowing its source loop to preserve the same sinks.
        if source_recovery_window_sec is not None:
            source._source_recovery_window_sec = source_recovery_window_sec
        sinks = [
            sink_class(**{**sink_dict, "pod": source}) for sink_class, sink_dict in sinks_list
        ]
        _bind_sink_callbacks(sinks, on_sink_error, reporter)
        instrumented_source = _SourceLifecycleProxy(source, manual_stop_event, reporter)
        instrumented_sinks = sinks
        if reporter is not None:
            # ExitStack exits in reverse: the finalization sentinel exits first and
            # the completion sentinel exits only after every real sink has closed.
            instrumented_sinks = [
                _LifecycleSentinel(reporter, starts_finalization=False),
                *sinks,
                _LifecycleSentinel(reporter, starts_finalization=True),
            ]

        get_data_kwargs = {
            "on_sink_error": on_sink_error,
            "on_source_error": on_source_error,
            "max_error_message_chars": max_error_message_chars,
            "source_error_emit_interval_sec": source_error_emit_interval_sec,
        }
        legacy_source.get_data(
            duration_sec,
            manual_stop_event,
            instrumented_source,
            instrumented_sinks,
            **get_data_kwargs,
        )
        if reporter is not None:
            reporter.emit(ShutdownPhase.WORKER_EXITING, "worker_exit_started")
    except BaseException as exc:
        if reporter is not None:
            reporter.failed("worker_shutdown_failed", exc)
        raise
    finally:
        if database_context is not None:
            database_context.pop()


def _create_worker(*, args):
    if sys.platform != "win32":
        try:
            return mp.Process(target=acknowledged_get_data_wrapper, args=args, start_new_session=True)
        except TypeError:
            pass
    return mp.Process(target=acknowledged_get_data_wrapper, args=args)


def _close_queue(status_queue) -> None:
    if status_queue is None:
        return
    close = getattr(status_queue, "close", None)
    if callable(close):
        close()
    join_thread = getattr(status_queue, "join_thread", None)
    if callable(join_thread):
        join_thread()


class AcknowledgedDataFlow(LegacyDataFlow):
    """Dashboard-only DataFlow subclass with worker evidence and strict stop results."""

    supports_source_recovery_window = True

    def __init__(
        self,
        *args,
        source_recovery_window_sec=None,
        max_error_message_chars=500,
        source_error_emit_interval_sec=1.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        if source_recovery_window_sec is not None:
            source_recovery_window_sec = float(source_recovery_window_sec)
            if source_recovery_window_sec <= 0:
                raise ValueError("source_recovery_window_sec must be greater than zero")
        self._source_recovery_window_sec = source_recovery_window_sec
        self._max_error_message_chars = int(max_error_message_chars)
        self._source_error_emit_interval_sec = float(source_error_emit_interval_sec)
        if self._max_error_message_chars <= 0:
            raise ValueError("max_error_message_chars must be greater than zero")
        if self._source_error_emit_interval_sec <= 0:
            raise ValueError("source_error_emit_interval_sec must be greater than zero")
        self._shutdown_status_queues: list[object | None] = []
        self._shutdown_ids: list[str | None] = []

    def make_worker(
        self,
        duration_sec,
        manual_stop_event,
        source,
        sinks,
        *,
        status_queue=None,
        shutdown_id=None,
        stream_index=0,
    ):
        args = (
            duration_sec,
            manual_stop_event,
            type(source),
            source.get_dict(),
            [(type(sink), sink.get_dict()) for sink in sinks],
            self._on_sink_error,
            self._on_source_error,
            status_queue,
            shutdown_id,
            stream_index,
            self._source_recovery_window_sec,
            self._max_error_message_chars,
            self._source_error_emit_interval_sec,
            _database_config_for_worker(),
        )
        return _create_worker(args=args)

    def _start_collecting(self, duration_sec: float = float("inf")) -> None:
        self._manual_stop_events = []
        self._shutdown_status_queues = []
        self._shutdown_ids = []
        self._workers = []
        for stream_index, (source, sinks) in enumerate(self._network):
            stop_event = mp.Event()
            status_queue = mp.Queue()
            shutdown_id = str(uuid.uuid4())
            self._manual_stop_events.append(stop_event)
            self._shutdown_status_queues.append(status_queue)
            self._shutdown_ids.append(shutdown_id)
            if hasattr(source, "_port"):
                source.close_port()
            gc.collect()
            self._workers.append(
                self.make_worker(
                    duration_sec,
                    stop_event,
                    source,
                    sinks,
                    status_queue=status_queue,
                    shutdown_id=shutdown_id,
                    stream_index=stream_index,
                )
            )
        for worker in self._workers:
            worker.start()

    def stop_collection(self, join_timeout_sec: float = 15.0):
        deadline = time.monotonic() + max(0.0, float(join_timeout_sec))
        for event in self._manual_stop_events:
            if event is not None:
                event.set()

        results = []
        for index, worker in enumerate(self._workers):
            status_queue = self._shutdown_status_queues[index] if index < len(self._shutdown_status_queues) else None
            shutdown_id = self._shutdown_ids[index] if index < len(self._shutdown_ids) else str(uuid.uuid4())
            results.append(
                coordinate_shutdown(
                    worker,
                    None,
                    status_queue,
                    shutdown_id,
                    index,
                    join_timeout_sec,
                    deadline=deadline,
                )
            )
            _close_queue(status_queue)
            try:
                worker.close()
            except Exception:
                pass

        self._manual_stop_events = []
        self._shutdown_status_queues = []
        self._shutdown_ids = []
        self._workers = []
        return {"ok": all(result["ok"] for result in results), "stream_results": results}

    def collect_for_seconds(self, duration_sec: float) -> None:
        self._start_collecting(duration_sec)
        for index, worker in enumerate(self._workers):
            worker.join()
            try:
                worker.close()
            except Exception:
                pass
            _close_queue(self._shutdown_status_queues[index])
        self._manual_stop_events = []
        self._shutdown_status_queues = []
        self._shutdown_ids = []
        self._workers = []


__all__ = ["AcknowledgedDataFlow", "ShutdownReporter", "acknowledged_get_data_wrapper"]
