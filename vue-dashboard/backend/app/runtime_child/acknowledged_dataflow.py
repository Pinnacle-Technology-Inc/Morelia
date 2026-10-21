"""Track session start time and confirm that acquisition workers and output sinks shut down."""

from __future__ import annotations

import gc
import multiprocessing as mp
import os
import signal
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess

from Morelia.shutdown import (
    ShutdownAction,
    ShutdownActor,
    ShutdownOutcome,
    ShutdownPhase,
    coordinate_shutdown,
)
from Morelia.Stream import source as legacy_source
from Morelia.Stream.data_flow import DataFlow as LegacyDataFlow
from Morelia.Watchdog.healthSink import HealthSink
from app.runtime_child.queue_diagnostics import DiagnosticQueue, label_queue


class ArrivalHealthSink(HealthSink):
    """Observe the first data arriving at HealthSink so the scheduler can track the session start time."""

    def bind_arrival_callback(self, callback):
        self._arrival_callback = callback
        self._arrival_reported = False

    def flush(self, timestamp, packet):
        super().flush(timestamp, packet)
        callback = getattr(self, "_arrival_callback", None)
        if (callback is not None and not self._arrival_reported
                and not getattr(packet, "is_missing_sample", False)):
            callback({"event_type": "first_data", "arrived_at":
                      datetime.fromtimestamp(self._window_start, UTC).isoformat()})
            self._arrival_reported = True


class ShutdownReporter:
    """Send worker shutdown progress to the parent so it can verify cleanup."""

    def __init__(self, status_queue, shutdown_id: str, stream_index: int, deadline=None) -> None:
        self.status_queue = status_queue
        label_queue(status_queue, stream_index=stream_index, shutdown_id=shutdown_id)
        self.shutdown_id = shutdown_id
        self.stream_index = stream_index
        self.actor_pid = os.getpid()
        self._deadline = deadline

    @property
    def shutdown_deadline(self):
        """Return the parent's absolute monotonic deadline once shutdown starts."""
        value = self._deadline.value if self._deadline is not None else 0.0
        return value if value > 0 else None

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
    """Let shutdown checks confirm that acquisition stopped and the device port closed."""

    def __init__(self, source, stop_event, reporter: ShutdownReporter | None, *, pause_on_read_error=True) -> None:
        self._source = source
        self._stop_event = stop_event
        self._reporter = reporter
        self._pause_on_read_error = pause_on_read_error
        self._stop_observed = False
        self._source_stopped = False
        self._port_closed = False
        self._final_close_error = None

    def __getattr__(self, name):
        value = getattr(self._source, name)
        if (self._pause_on_read_error and callable(value)
                and name in ("read_pod_packet", "read_pod_packet_streaming")):
            def read(*args, **kwargs):
                try:
                    return value(*args, **kwargs)
                except Exception:
                    # Avoid rapid retries after unplugging; Stop interrupts the pause.
                    self._stop_event.wait(0.1)
                    raise
            return read
        return value

    def __enter__(self):
        self._port_closed = False
        self._source_stopped = False
        self._final_close_error = None
        try:
            self._source.__enter__()
        except BaseException:
            # Failed context entry never calls __exit__, even after opening a port.
            self._finish_source()
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self._source.__exit__(exc_type, exc, traceback)
        finally:
            self._finish_source()

    def _finish_source(self):
        try:
            if self._reporter is not None and self._stop_event.is_set() and not self._stop_observed:
                self._reporter.emit(ShutdownPhase.STOP_OBSERVED, "stop_event_observed")
                self._stop_observed = True
        finally:
            # USB stop errors and failed reporting must not skip port cleanup.
            try:
                self.close_port()
            except BaseException as exc:
                self._final_close_error = exc
                raise

    def open_port(self, *args, **kwargs):
        self._port_closed = False
        self._source_stopped = False
        self._final_close_error = None
        return self._source.open_port(*args, **kwargs)

    def close_port(self):
        # Repeated acquisition cleanup must preserve a failed final close.
        if self._final_close_error is not None:
            raise self._final_close_error
        result = None
        if not self._port_closed:
            result = self._source.close_port()
            self._port_closed = True
        if self._reporter is not None and self._stop_event.is_set() and not self._source_stopped:
            self._reporter.emit(ShutdownPhase.SOURCE_STOPPED, "source_port_closed")
            self._source_stopped = True
        return result


class _LifecycleSentinel:
    """Confirm output shutdown only after every sink closes successfully."""

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


def _bind_sink_callbacks(sinks, on_sink_error, reporter: ShutdownReporter | None, recording_queue=None) -> None:
    for sink in sinks:
        if recording_queue is not None and type(sink) is ArrivalHealthSink:
            sink.bind_arrival_callback(recording_queue.put)
        bind_recording = getattr(sink, "bind_recording_callback", None)
        if recording_queue is not None and callable(bind_recording):
            bind_recording(recording_queue.put)
        bind_error = getattr(sink, "bind_error_callback", None)
        if callable(bind_error):
            bind_error(on_sink_error)
        bind_shutdown = getattr(sink, "bind_shutdown_reporter", None)
        if reporter is not None and callable(bind_shutdown):
            bind_shutdown(reporter)


def _database_config_for_worker() -> dict | None:
    """Give spawned workers the same database settings as the parent app."""
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


def _redirect_worker_stdout_to_log() -> None:
    """Keep logging failures from interrupting output cleanup after a host crash.

    Workers inherit the host's control pipe as stdout, so send their logs to stderr.
    """
    stdout_fd = sys.stdout.fileno()
    os.dup2(sys.stderr.fileno(), stdout_fd)
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        # Update the separate Windows handle so writer processes also inherit the log.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        set_std_handle = kernel32.SetStdHandle
        set_std_handle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
        set_std_handle.restype = wintypes.BOOL
        if not set_std_handle(-11, msvcrt.get_osfhandle(stdout_fd)):
            raise ctypes.WinError(ctypes.get_last_error())


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
    recording_queue=None,
    shutdown_deadline=None,
    predecessor_released=None,
    source_reconnect_config=None,
    descendants_released=None,
    predecessor_worker_exited=None,
):
    """Run acquisition with reports for session timing and output shutdown."""
    if mp.parent_process() is not None:
        _redirect_worker_stdout_to_log()
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass

    reporter = None
    if shutdown_queue is not None and shutdown_id is not None:
        reporter = ShutdownReporter(shutdown_queue, shutdown_id, stream_index, shutdown_deadline)

    database_context = None
    sinks = []
    try:
        if database_config is not None:
            from app.database import create_database_app

            database_context = create_database_app(
                config_overrides=database_config
            ).app_context()
            database_context.push()

        if manual_stop_event.is_set():
            return
        source = source_class(**source_dict)
        sinks = [
            (ArrivalHealthSink if sink_class is HealthSink else sink_class)(
                **{**sink_dict, "pod": source}) for sink_class, sink_dict in sinks_list
        ]
        for sink, released in zip(sinks, predecessor_released or [], strict=False):
            if released is True:
                sink._predecessor_released = True
        for sink, exited in zip(sinks, predecessor_worker_exited or [], strict=False):
            sink._predecessor_worker_exited = exited is True
        # Observe arrival before slow or failed writes affect session timing.
        # Use exact types because isinstance also accepts output sinks with flush().
        sinks.sort(key=lambda sink: type(sink) not in (HealthSink, ArrivalHealthSink))
        def report_sink_error(event):
            if on_sink_error is None:
                return
            event = dict(event)
            if source_reconnect_config is not None:
                event["source_id"] = source_reconnect_config[0].device_id
            for sink in sinks:
                if getattr(sink, "sink_id", None) == event.get("sink_id"):
                    record = getattr(sink, "_record", None)
                    if record is not None:
                        event.setdefault("output_id", record.output_id)
                        event.setdefault("confirmed_samples", getattr(sink, "_samples_written", 0))
                    break
            on_sink_error(event)

        _bind_sink_callbacks(sinks, report_sink_error, reporter, recording_queue)
        instrumented_sinks = sinks
        if reporter is not None:
            # ExitStack closes in reverse order, so confirm completion after all sinks close.
            instrumented_sinks = [
                _LifecycleSentinel(reporter, starts_finalization=False),
                *sinks,
                _LifecycleSentinel(reporter, starts_finalization=True),
            ]

        get_data_kwargs = {
            "on_sink_error": report_sink_error,
            "on_source_error": on_source_error,
            "max_error_message_chars": max_error_message_chars,
            "source_error_emit_interval_sec": source_error_emit_interval_sec,
        }
        get_data = legacy_source.get_data
        if any(any(cls.__module__ == "app.output.managed_pvfs_sink" for cls in type(sink).__mro__)
               for sink in sinks):
            from app.runtime_child.pvfs_acquisition import get_data as managed_get_data

            get_data = managed_get_data
            source._source_recovery_window_sec = source_recovery_window_sec
            get_data_kwargs["reconnect_config"] = source_reconnect_config
        instrumented_source = _SourceLifecycleProxy(
            source, manual_stop_event, reporter,
            pause_on_read_error=get_data is legacy_source.get_data,
        )
        get_data(
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
        if descendants_released is not None:
            owners = [sink for sink in sinks if _sinks_may_own_processes([sink])]
            descendants_released.value = all(
                callable(getattr(sink, "_ownership_released", None))
                and sink._ownership_released() for sink in owners
            )
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


def _create_shutdown_queue():
    """Create a queue that a nested spawn writer can share on every host."""
    return DiagnosticQueue("worker_shutdown", ctx=mp.get_context() if sys.platform == "win32" else mp.get_context("spawn"))


def _sinks_may_own_processes(sinks):
    """Check whether shutdown must also wait for output writer processes."""
    pvfs_types = {
        ("app.output.managed_pvfs_sink", "ManagedPvfsSink"),
        ("Morelia.Stream.sink.pvfs_sink", "PvfsSink"),
    }
    return any(
        getattr(sink, "owns_child_processes", False) is True
        or (any((cls.__module__, cls.__name__) in pvfs_types for cls in type(sink).__mro__)
            and bool(getattr(sink, "_use_writer_process", True)))
        for sink in sinks
    )


def _coordinate_worker_shutdown(worker, stop_event, status_queue, shutdown_id,
                                stream_index, join_timeout_sec, *, deadline=None,
                                previous=None, descendants_possible=False,
                                launch_not_attempted=False, descendants_released=None):
    """Confirm that the worker and its output writers stopped, retaining any output failures."""
    if previous is not None and previous.get("teardown_confirmed") is True:
        return dict(previous)
    # Skip shutdown only when we know the worker never started. Joining it would fail.
    never_started = ((isinstance(worker, BaseProcess)
                      and worker._popen is None and not worker._closed)
                     or (worker is None and launch_not_attempted))
    if never_started:
        if stop_event is not None:
            stop_event.set()
        return {
            "ok": True, "stream_index": stream_index,
            "shutdown_id": shutdown_id, "worker_status": "not_started",
            "worker_started": False, "worker_exited": False,
            "worker_exitcode": None, "teardown_confirmed": True,
            "worker_accounted": True, "descendants_possible": descendants_possible,
            "descendants_teardown_confirmed": True,
            "terminal_phase": "complete", "shutdown_phase": "complete",
            "forced_termination": False, "missing_phases": [],
            "transcript": (), "shutdown_transcript": (),
        }
    result = coordinate_shutdown(
        worker, stop_event, status_queue, shutdown_id, stream_index,
        join_timeout_sec, deadline=deadline,
    )
    exited = (worker is not None and not worker.is_alive()
              and worker.exitcode is not None)
    result["worker_exited"] = exited
    result["worker_accounted"] = worker is not None and (
        isinstance(worker, BaseProcess) or getattr(worker, "pid", None) is not None)
    result["descendants_possible"] = descendants_possible
    sinks_finalized = any(
        record.phase is ShutdownPhase.SINKS_FINALIZED
        and record.action == "all_sinks_closed"
        and record.actor == ShutdownActor.DATAFLOW_WORKER.value
        and record.outcome in (ShutdownOutcome.ACKNOWLEDGED, ShutdownOutcome.COMPLETED)
        for record in result.get("transcript", ())
    )
    release_confirmed = (exited and descendants_released is not None
                         and descendants_released.value == 1)
    descendants_confirmed = (not descendants_possible or sinks_finalized or release_confirmed
                             or (previous is not None and previous.get("descendants_teardown_confirmed") is True))
    result["descendants_teardown_confirmed"] = descendants_confirmed
    result["teardown_confirmed"] = exited and descendants_confirmed
    if not result["teardown_confirmed"]:
        result["ok"] = False
        result["terminal_phase"] = result["shutdown_phase"] = "failed"
        result["worker_status"] = "failed"
    if previous is not None and previous.get("ok") is not True:
        # Keep the earlier failure visible even if the worker has since exited.
        result["previous_shutdown_result"] = previous.get("previous_shutdown_result", dict(previous))
        result["ok"] = False
        result["terminal_phase"] = result["shutdown_phase"] = "failed"
        result["worker_status"] = "failed"
        result["forced_termination"] = bool(result.get("forced_termination") or previous.get("forced_termination"))
    return result


class AcknowledgedDataFlow(LegacyDataFlow):
    """Require shutdown results for every acquisition worker and its output writers."""

    supports_source_recovery_window = True
    supports_identity_reconnect = True
    supports_recording_acknowledgements = True

    def __init__(
        self,
        *args,
        source_recovery_window_sec=None,
        recording_queue=None,
        max_error_message_chars=500,
        source_error_emit_interval_sec=1.0,
        source_reconnect_configs=None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        if source_recovery_window_sec is not None:
            source_recovery_window_sec = float(source_recovery_window_sec)
            if source_recovery_window_sec <= 0:
                raise ValueError("source_recovery_window_sec must be greater than zero")
        self._source_recovery_window_sec = source_recovery_window_sec
        self._source_reconnect_configs = source_reconnect_configs or {}
        self._max_error_message_chars = int(max_error_message_chars)
        self._source_error_emit_interval_sec = float(source_error_emit_interval_sec)
        if self._max_error_message_chars <= 0:
            raise ValueError("max_error_message_chars must be greater than zero")
        if self._source_error_emit_interval_sec <= 0:
            raise ValueError("source_error_emit_interval_sec must be greater than zero")
        self._recording_queue = recording_queue
        self._acquisition_guard = None
        self._registered_stop_events = []
        self._registered_shutdown_deadlines = []
        self._ever_started_worker = False
        # Account for every stream even if the session stops before acquisition starts.
        # These IDs cover that case; each collection attempt gets new IDs for its history.
        self._workers = [None] * len(self._network)
        self._manual_stop_events = [None] * len(self._network)
        self._shutdown_status_queues: list[object | None] = [None] * len(self._network)
        self._shutdown_deadlines = {}
        self._shutdown_deadline_lock = threading.Lock()
        self._descendants_released = {}
        self._shutdown_ids: list[str | None] = [str(uuid.uuid4()) for _ in self._network]
        self._shutdown_results: dict[int, dict] = {}
        self._prior_shutdown_results: list[dict] = []
        self._shutdown_descendants_possible: dict[int, bool] = {}
        self._shutdown_generation_ids: set[str] = set()
        self._worker_start_attempted: dict[int, bool] = {
            index: False for index in range(len(self._network))
        }

    def retain_previous_shutdown(self, result) -> None:
        """Keep earlier output failures visible after a worker is replaced."""
        if not any(previous.get("shutdown_id") == result.get("shutdown_id")
                   for previous in self._prior_shutdown_results):
            self._prior_shutdown_results.append(dict(result))

    def worker_inventory_complete(self, current_results):
        """Require shutdown results for every configured stream and each worker replacement."""
        indexes = [row.get("stream_index") for row in current_results]
        rows = [*current_results, *self._prior_shutdown_results]
        return (
            len(indexes) == len(self._network)
            and set(indexes) == set(range(len(self._network)))
            and all(row.get("worker_accounted") is True for row in rows)
            and self._shutdown_generation_ids <= {row.get("shutdown_id") for row in rows}
        )

    def descendants_possible(self, stream_index):
        if stream_index not in self._shutdown_descendants_possible:
            # Remember whether this worker can own writers across shutdown retries.
            self._shutdown_descendants_possible[stream_index] = _sinks_may_own_processes(
                self._network[stream_index][1])
        return self._shutdown_descendants_possible[stream_index]

    def rebuild_with_network(self, network):
        """Preserve cancellation, reporting, and shutdown history when rebuilding acquisition."""
        replacement = type(self)(
            network, on_sink_error=self._on_sink_error,
            on_source_error=self._on_source_error,
            source_recovery_window_sec=self._source_recovery_window_sec,
            max_error_message_chars=self._max_error_message_chars,
            source_error_emit_interval_sec=self._source_error_emit_interval_sec,
            recording_queue=self._recording_queue,
            source_reconnect_configs=self._source_reconnect_configs,
        )
        replacement._acquisition_guard = self._acquisition_guard
        # The runtime still cancels through the original flow, so share replacement stop events.
        replacement._registered_stop_events = self._registered_stop_events
        replacement._registered_shutdown_deadlines = self._registered_shutdown_deadlines
        replacement._shutdown_deadline_lock = self._shutdown_deadline_lock
        replacement._prior_shutdown_results = list(self._prior_shutdown_results)
        replacement._shutdown_generation_ids = set(self._shutdown_generation_ids)
        for result in self._shutdown_results.values():
            replacement.retain_previous_shutdown(result)
        return replacement

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
        self._registered_stop_events.append(manual_stop_event)
        shutdown_deadline = mp.RawValue("d", 0.0)
        self._shutdown_deadlines[stream_index] = shutdown_deadline
        self._registered_shutdown_deadlines.append(shutdown_deadline)
        descendants_released = mp.RawValue("b", False)
        self._descendants_released[stream_index] = descendants_released
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
            self._recording_queue,
            shutdown_deadline,
            [getattr(sink, "_predecessor_released", False) is True for sink in sinks],
            self._source_reconnect_configs.get(stream_index),
            descendants_released,
            [getattr(sink, "_predecessor_worker_exited", False) is True for sink in sinks],
        )
        return _create_worker(args=args)

    def _start_collecting(self, duration_sec: float = float("inf")) -> None:
        for result in self._shutdown_results.values():
            self.retain_previous_shutdown(result)
        stream_count = len(self._network)
        self._manual_stop_events = [None] * stream_count
        self._shutdown_status_queues = [None] * stream_count
        self._shutdown_ids = [str(uuid.uuid4()) for _ in self._network]
        self._shutdown_generation_ids.update(self._shutdown_ids)
        self._shutdown_results = {}
        self._shutdown_descendants_possible = {
            index: _sinks_may_own_processes(sinks)
            for index, (_source, sinks) in enumerate(self._network)
        }
        self._worker_start_attempted = {index: False for index in range(stream_count)}
        self._workers = [None] * stream_count
        for stream_index, (source, sinks) in enumerate(self._network):
            stop_event = mp.Event()
            self._manual_stop_events[stream_index] = stop_event
            status_queue = _create_shutdown_queue()
            self._shutdown_status_queues[stream_index] = status_queue
            shutdown_id = self._shutdown_ids[stream_index]
            if hasattr(source, "_port"):
                source.close_port()
            gc.collect()
            self._workers[stream_index] = self.make_worker(
                duration_sec,
                stop_event,
                source,
                sinks,
                status_queue=status_queue,
                shutdown_id=shutdown_id,
                stream_index=stream_index,
            )
        for stream_index, worker in enumerate(self._workers):
            if self._acquisition_guard is not None:
                self._acquisition_guard()
            self._worker_start_attempted[stream_index] = True
            try:
                worker.start()
            finally:
                if isinstance(worker, BaseProcess) and worker._popen is not None:
                    self._ever_started_worker = True
            self._ever_started_worker = True

    def publish_shutdown_deadline(self, deadline, stream_index=None):
        """Give native owners the remaining budget before their stop events are set."""
        values = ([*self._shutdown_deadlines.values(), *self._registered_shutdown_deadlines]
                  if stream_index is None
                  else [self._shutdown_deadlines.get(stream_index)])
        for value in values:
            if value is not None:
                with self._shutdown_deadline_lock:
                    value.value = min(value.value, deadline) if value.value > 0 else deadline

    def stop_collection(self, join_timeout_sec: float = 15.0):
        deadline = time.monotonic() + max(0.0, float(join_timeout_sec))
        self.publish_shutdown_deadline(deadline)
        for event in self._manual_stop_events:
            if event is not None:
                event.set()

        results = []
        for index, worker in enumerate(self._workers):
            status_queue = self._shutdown_status_queues[index] if index < len(self._shutdown_status_queues) else None
            shutdown_id = self._shutdown_ids[index] if index < len(self._shutdown_ids) else str(uuid.uuid4())
            previous = self._shutdown_results.get(index)
            result = _coordinate_worker_shutdown(
                worker,
                None,
                status_queue,
                shutdown_id,
                index,
                join_timeout_sec,
                deadline=deadline,
                previous=previous,
                descendants_possible=self.descendants_possible(index),
                launch_not_attempted=self._worker_start_attempted.get(index) is False,
                descendants_released=self._descendants_released.get(index),
            )
            results.append(result)
            self._shutdown_results[index] = dict(result)
            if result.get("teardown_confirmed") is True:
                _close_queue(status_queue)
                if index < len(self._shutdown_status_queues):
                    self._shutdown_status_queues[index] = None
                if worker is not None:
                    try:
                        worker.close()
                    except Exception:
                        pass
                self._workers[index] = None

        previous = self._prior_shutdown_results
        queues_released = not any(queue is not None for queue in self._shutdown_status_queues)
        if not any(worker is not None for worker in self._workers) and queues_released:
            self._manual_stop_events = []
            self._shutdown_status_queues = []
            self._shutdown_ids = []
            self._workers = []
        if not results:
            results = list(self._shutdown_results.values())
        all_results = [*results, *previous]
        inventory_complete = self.worker_inventory_complete(results)
        return {
            "ok": inventory_complete and all(result.get("ok") is True for result in all_results),
            "teardown_confirmed": inventory_complete and queues_released and all(result.get("teardown_confirmed") is True for result in all_results),
            "worker_inventory_complete": inventory_complete,
            "forced_termination": any(result.get("forced_termination") is True for result in all_results),
            "stream_results": results,
            "previous_stream_results": [dict(item) for item in previous],
        }

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
