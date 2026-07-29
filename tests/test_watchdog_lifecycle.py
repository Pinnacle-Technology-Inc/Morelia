import threading
from queue import Queue

from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
from Morelia.Stream.shutdown import ShutdownAction, ShutdownOutcome, ShutdownPhase


class FakeEvent:
    def __init__(self, events):
        self.events = events

    def set(self):
        self.events.append("stop_event.set")


class FakeWorker:
    def __init__(self, events, status_queue=None, shutdown_id=None, stream_index=0):
        self.events = events
        self.status_queue = status_queue
        self.shutdown_id = shutdown_id
        self.stream_index = stream_index
        self.alive = True
        self.pid = 123
        self.exitcode = None

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.events.append("worker.join")
        self.emit_shutdown_actions()
        self.alive = False
        self.exitcode = 0

    def emit_shutdown_actions(self):
        if self.status_queue is None:
            return
        for phase, action in (
            (ShutdownPhase.STOP_OBSERVED, "stop_event_observed"),
            (ShutdownPhase.SOURCE_STOPPED, "source_port_closed"),
            (ShutdownPhase.SINKS_FINALIZING, "sink_close_started"),
            (ShutdownPhase.SINKS_FINALIZED, "all_sinks_closed"),
            (ShutdownPhase.WORKER_EXITING, "worker_exit_started"),
        ):
            self.status_queue.put(
                ShutdownAction(
                    shutdown_id=self.shutdown_id,
                    stream_index=self.stream_index,
                    actor="dataflow_worker",
                    actor_pid=self.pid,
                    phase=phase,
                    action=action,
                    outcome=ShutdownOutcome.ACKNOWLEDGED,
                    emitted_at_ns=0,
                )
            )

    def terminate(self):
        self.events.append("worker.terminate")
        self.alive = False

    def close(self):
        self.events.append("worker.close")

    def start(self):
        self.events.append("worker.start")
        self.alive = True


class StuckWorker(FakeWorker):
    def join(self, timeout=None):
        self.events.append("worker.join")


class RaisingJoinWorker(FakeWorker):
    def join(self, timeout=None):
        raise RuntimeError("join failed")


def test_stop_terminates_worker_after_join_timeout_without_cleaning_source():
    events = []
    source = FakeSource("old", events)
    flowgraph = FakeFlowgraph(source, StuckWorker(events), events)
    monitor = DataFlowMonitor(flowgraph=None)
    monitor.flowgraph = flowgraph
    monitor.snapshot_config = [{"source": {"source_dict": {}}}]
    monitor._lifecycle_locks = {0: threading.RLock()}
    monitor._lifecycle_busy = {0: None}
    monitor._lifecycle_states = {0: {"state": "running"}}

    result = monitor.stop_stream(0, join_timeout_sec=0.01)

    assert result["ok"] is False
    assert result["forced_termination"] is True
    assert events.index("worker.join") < events.index("worker.terminate")
    assert "old.cleanup" not in events


class FakeSource:
    def __init__(self, name, events):
        self.name = name
        self.events = events
        self._port = None
        self._use_d2xx = True
        self.port = "COM9"

    def get_dict(self):
        return {"name": self.name, "events": self.events}

    def close_port(self):
        self.events.append(f"{self.name}.close_port")
        self._port = None

    def cleanup(self):
        self.events.append(f"{self.name}.cleanup")


class FakeFlowgraph:
    def __init__(self, source, worker, events):
        self._network = [(source, [])]
        self._workers = [worker]
        self._manual_stop_events = [FakeEvent(events)]


class BarrierWorker(FakeWorker):
    def __init__(self, events, barrier):
        super().__init__(events)
        self.barrier = barrier

    def join(self, timeout=None):
        self.events.append("worker.join")
        self.barrier.wait(timeout=5.0)
        self.emit_shutdown_actions()
        self.alive = False
        self.exitcode = 0


class StartBarrierWorker(FakeWorker):
    def __init__(self, events, barrier):
        super().__init__(events)
        self.barrier = barrier
        self.alive = False

    def start(self):
        self.events.append("worker.start")
        self.barrier.wait(timeout=5.0)
        self.alive = True


def make_multi_stream_monitor(stream_count, worker_factory):
    events = []
    flowgraph = FakeFlowgraph(None, None, events)
    flowgraph._network = [
        (FakeSource(f"source-{index}", events), [])
        for index in range(stream_count)
    ]
    flowgraph._workers = [
        worker_factory(index, events)
        for index in range(stream_count)
    ]
    flowgraph._manual_stop_events = [
        FakeEvent(events)
        for _ in range(stream_count)
    ]
    flowgraph._shutdown_status_queues = [Queue() for _ in range(stream_count)]
    flowgraph._shutdown_ids = [f"shutdown-{index}" for index in range(stream_count)]
    for index, worker in enumerate(flowgraph._workers):
        if worker is not None:
            worker.status_queue = flowgraph._shutdown_status_queues[index]
            worker.shutdown_id = flowgraph._shutdown_ids[index]
            worker.stream_index = index

    monitor = DataFlowMonitor(flowgraph=None)
    monitor.flowgraph = flowgraph
    monitor.snapshot_config = [
        {"source": {"source_dict": {}}}
        for _ in range(stream_count)
    ]
    monitor._lifecycle_locks = {
        index: threading.RLock()
        for index in range(stream_count)
    }
    monitor._poll_locks = {
        index: threading.RLock()
        for index in range(stream_count)
    }
    monitor._lifecycle_busy = {
        index: None
        for index in range(stream_count)
    }
    return monitor


def make_monitor(events, old_source, old_worker, replacement_source):
    flowgraph = FakeFlowgraph(old_source, old_worker, events)
    monitor = DataFlowMonitor(flowgraph=None)
    monitor.flowgraph = flowgraph
    monitor.snapshot_config = [{"source": {"source_dict": {}}}]
    monitor._poll_locks = {0: threading.RLock()}
    monitor._lifecycle_locks = {0: threading.RLock()}
    monitor._lifecycle_busy = {0: None}
    monitor._lifecycle_states = {0: {"state": "running"}}
    monitor._reconstruction_hook = lambda index: (
        events.append("replacement.build") or replacement_source,
        [],
    )
    monitor._hw.reset_streaming_device = lambda source: (
        events.append("device.reset") or {"ok": True}
    )
    monitor._make_worker = lambda **kwargs: FakeWorker(events)
    flowgraph._shutdown_status_queues = [Queue()]
    flowgraph._shutdown_ids = ["shutdown-0"]
    old_worker.status_queue = flowgraph._shutdown_status_queues[0]
    old_worker.shutdown_id = flowgraph._shutdown_ids[0]
    return monitor


def test_restart_preserves_old_source_queue_server_until_full_shutdown():
    events = []
    old_source = FakeSource("old", events)
    replacement_source = FakeSource("replacement", events)
    monitor = make_monitor(events, old_source, FakeWorker(events), replacement_source)

    result = monitor.restart_one_stream(0)

    assert result["ok"] is True
    assert events.index("worker.join") < events.index("device.reset")
    assert events.index("device.reset") < events.index("replacement.build")
    assert events.index("replacement.build") < events.index("worker.start")
    assert "old.cleanup" not in events
    assert "resources.wait" not in events


def test_stop_stream_keeps_source_when_worker_slot_is_missing():
    events = []
    source = FakeSource("old", events)
    flowgraph = FakeFlowgraph(source, None, events)
    monitor = DataFlowMonitor(flowgraph=None)
    monitor.flowgraph = flowgraph
    monitor.snapshot_config = [{"source": {"source_dict": {}}}]
    monitor._lifecycle_locks = {0: threading.RLock()}
    monitor._lifecycle_busy = {0: None}
    monitor._lifecycle_states = {0: {"state": "running"}}

    result = monitor.stop_stream(0)

    assert result["ok"] is False
    assert events == ["stop_event.set"]


def test_simultaneous_guarded_stream_stops_do_not_deadlock():
    barrier = threading.Barrier(2)
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, events: BarrierWorker(events, barrier),
    )
    results = {}
    errors = []

    def stop_guarded(stream_index):
        try:
            with monitor.stream_lifecycle_guard(
                stream_index,
                command="auto_recovery",
                requested_by="test",
                blocking=False,
            ) as busy:
                assert busy is None
                results[stream_index] = monitor.stop_stream(
                    stream_index,
                    join_timeout_sec=0.01,
                )
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=stop_guarded, args=(index,), daemon=True)
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert set(results) == {0, 1}
    assert all(result["ok"] for result in results.values())
    assert monitor.dataflow_status == "failed"


def test_all_stream_status_uses_unlocked_reader_after_acquiring_all_locks():
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, events: FakeWorker(events),
    )

    def fail_if_public_reader_is_called(_stream_index):
        raise AssertionError("public stream reader re-acquired a lifecycle lock")

    monitor.get_stream_status = fail_if_public_reader_is_called

    statuses = monitor.get_all_stream_status()

    assert [status["stream_index"] for status in statuses] == [0, 1]
    assert all(status["worker_status"] == "alive" for status in statuses)


def test_simultaneous_guarded_stream_starts_do_not_deadlock():
    barrier = threading.Barrier(2)
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, _events: None,
    )
    monitor._rebuild_dataflow = lambda index: (
        FakeSource(f"replacement-{index}", []),
        [],
    )
    monitor._make_worker = lambda **_kwargs: StartBarrierWorker([], barrier)
    results = {}
    errors = []

    def start_guarded(stream_index):
        try:
            with monitor.stream_lifecycle_guard(
                stream_index,
                command="auto_recovery",
                requested_by="test",
                blocking=False,
            ) as busy:
                assert busy is None
                results[stream_index] = monitor.start_stream(stream_index)
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=start_guarded, args=(index,), daemon=True)
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert set(results) == {0, 1}
    assert all(result["ok"] for result in results.values())
    assert monitor.dataflow_status == "running"


def test_targeted_stops_report_degraded_then_failed_aggregate_status():
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, events: FakeWorker(events),
    )

    first_result = monitor.stop_stream(0)
    second_result = monitor.stop_stream(1)

    assert first_result["dataflow_status"] == "degraded"
    assert second_result["dataflow_status"] == "failed"


def test_dataflow_command_releases_partial_reservation_when_stream_is_busy():
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, events: FakeWorker(events),
    )
    stream_one_reserved = threading.Event()
    release_stream_one = threading.Event()
    holder_errors = []

    def hold_stream_one():
        try:
            with monitor.stream_lifecycle_guard(
                1,
                command="auto_recovery",
                requested_by="watchdog",
                blocking=False,
            ) as stream_busy:
                assert stream_busy is None
                stream_one_reserved.set()
                assert release_stream_one.wait(timeout=5.0)
        except BaseException as error:
            holder_errors.append(error)

    holder = threading.Thread(target=hold_stream_one)
    holder.start()
    assert stream_one_reserved.wait(timeout=5.0)

    try:
        with monitor.dataflow_lifecycle_guard(
            command="stop",
            requested_by="test",
            blocking=False,
        ) as dataflow_busy:
            assert dataflow_busy["status"] == "busy"
            assert dataflow_busy["busy_stream_index"] == 1

        stream_zero_busy = []

        def probe_stream_zero():
            with monitor.stream_lifecycle_guard(
                0,
                command="restart_stream",
                requested_by="test",
                blocking=False,
            ) as released_stream_busy:
                stream_zero_busy.append(released_stream_busy)

        probe = threading.Thread(target=probe_stream_zero)
        probe.start()
        probe.join(timeout=5.0)
        assert not probe.is_alive()
        assert stream_zero_busy == [None]
    finally:
        release_stream_one.set()
        holder.join(timeout=5.0)

    assert not holder.is_alive()
    assert not holder_errors


def test_direct_stream_stop_waits_for_whole_dataflow_command_reservation():
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, events: FakeWorker(events),
    )
    dataflow_reserved = threading.Event()
    release_dataflow = threading.Event()
    direct_started = threading.Event()
    entered_stop = threading.Event()
    errors = []
    original_stop_reserved = monitor._stop_stream_reserved

    def tracked_stop_reserved(stream_index, join_timeout_sec):
        entered_stop.set()
        return original_stop_reserved(stream_index, join_timeout_sec)

    monitor._stop_stream_reserved = tracked_stop_reserved

    def hold_dataflow():
        try:
            with monitor.dataflow_lifecycle_guard(
                command="stop",
                requested_by="test",
                blocking=False,
            ) as busy:
                assert busy is None
                dataflow_reserved.set()
                assert release_dataflow.wait(timeout=5.0)
        except BaseException as error:
            errors.append(error)

    def stop_directly():
        try:
            direct_started.set()
            monitor.stop_stream(0)
        except BaseException as error:
            errors.append(error)

    holder = threading.Thread(target=hold_dataflow)
    direct = threading.Thread(target=stop_directly)
    holder.start()
    assert dataflow_reserved.wait(timeout=5.0)
    direct.start()
    assert direct_started.wait(timeout=5.0)

    assert not entered_stop.wait(timeout=0.1)
    release_dataflow.set()
    assert entered_stop.wait(timeout=5.0)

    holder.join(timeout=5.0)
    direct.join(timeout=5.0)
    assert not holder.is_alive()
    assert not direct.is_alive()
    assert not errors


def test_dataflow_command_releases_reservations_when_acquire_raises():
    monitor = make_multi_stream_monitor(
        2,
        lambda _index, events: FakeWorker(events),
    )

    class RaisingAcquireLock:
        def acquire(self, blocking=True):
            raise RuntimeError("acquire failed")

    monitor._command_locks[1] = RaisingAcquireLock()

    try:
        with monitor.dataflow_lifecycle_guard(
            command="stop",
            requested_by="test",
            blocking=True,
        ):
            raise AssertionError("guard should not yield")
    except RuntimeError as error:
        assert str(error) == "acquire failed"

    acquired_from_other_thread = []

    def acquire_stream_zero():
        lock = monitor._command_locks[0]
        acquired = lock.acquire(blocking=False)
        acquired_from_other_thread.append(acquired)
        if acquired:
            lock.release()

    probe = threading.Thread(target=acquire_stream_zero)
    probe.start()
    probe.join(timeout=5.0)

    assert acquired_from_other_thread == [True]


def test_partial_whole_dataflow_stop_reconciles_each_stream_state():
    monitor = make_multi_stream_monitor(
        2,
        lambda index, events: (
            FakeWorker(events)
            if index == 0
            else RaisingJoinWorker(events)
        ),
    )
    monitor._lifecycle_states = {
        0: {"state": "running"},
        1: {"state": "running"},
    }

    result = monitor.guarded_stop_dataflow(
        requested_by="test",
        blocking=True,
    )

    assert result["ok"] is False
    assert result["result"]["dataflow_status"] == "stop_failed"
    assert monitor.get_lifecycle_state(0)["state"] == "stopped"
    assert monitor.get_lifecycle_state(1)["state"] == "running"


def test_partial_whole_dataflow_start_does_not_mark_missing_stream_running():
    monitor = make_multi_stream_monitor(
        2,
        lambda index, events: FakeWorker(events) if index == 0 else None,
    )
    monitor._lifecycle_states = {
        0: {"state": "stopped"},
        1: {"state": "stopped"},
    }

    result = monitor.guarded_start_dataflow(
        requested_by="test",
        blocking=True,
    )

    assert result["ok"] is False
    assert result["result"]["status"] == "partially_running"
    assert result["result"]["dataflow_status"] == "degraded"
    assert monitor.get_lifecycle_state(0)["state"] == "running"
    assert monitor.get_lifecycle_state(1)["state"] == "stopped"
