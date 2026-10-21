"""Plain workers need process cleanup; dashboard workers also need evidence."""

import threading
from queue import Queue

import pytest
from app.runtime_child.acknowledged_dataflow import AcknowledgedDataFlow
from app.runtime_child.acknowledged_monitor import AcknowledgedDataFlowMonitor
from app.runtime_child.morelia import _import_morelia

from Morelia.shutdown import REQUIRED_SHUTDOWN_PHASES, ShutdownAction
from Morelia.Stream.data_flow import DataFlow
from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
from Morelia.Watchdog.watchdog import Watchdog


class Worker:
    pid = 123

    def __init__(self, *, exitcode=0, stuck=False):
        self.exitcode = None
        self.final_exitcode = exitcode
        self.alive = True
        self.stuck = stuck
        self.closed = False
        self.terminated = False
        self.join_timeouts = []

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)
        if not self.stuck:
            self.alive = False
            self.exitcode = self.final_exitcode

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exitcode = -15

    def close(self):
        assert not self.alive
        self.closed = True


def monitor_for(flow_type=DataFlow, workers=None, monitor_type=DataFlowMonitor):
    workers = workers if workers is not None else [Worker(), Worker()]
    flow = flow_type([(object(), []) for _ in workers])
    flow._workers = workers.copy()
    flow._manual_stop_events = [threading.Event() for _ in workers]
    monitor = monitor_type()
    monitor.flowgraph = flow
    monitor.snapshot_config = [{} for _ in workers]
    return monitor


def test_plain_noop_start_then_stop_other_stream_needs_no_shutdown_metadata():
    monitor = monitor_for()
    worker = monitor.flowgraph._workers[0]

    assert monitor.start_stream(1)["status"] == "already_running"
    result = monitor.stop_stream(0)

    assert result["ok"] is True
    assert worker.closed
    assert monitor.flowgraph._manual_stop_events[0].is_set()
    assert not hasattr(monitor.flowgraph, "_shutdown_ids")
    assert not hasattr(monitor.flowgraph, "_shutdown_status_queues")
    assert "shutdown_id" not in result


def test_plain_restart_second_stream_then_stop_all(monkeypatch):
    monitor = monitor_for()
    worker_kwargs = []
    monkeypatch.setattr("Morelia.Watchdog.dataflowMonitor.mp.Event", threading.Event)
    monitor.reset_stream_device = lambda index: {"ok": True}
    monitor._clear_stream_heartbeat_unlocked = lambda index: None
    monitor._rebuild_dataflow = lambda index: (object(), [])

    def make_worker(**kwargs):
        worker_kwargs.append(kwargs)
        return Worker()

    monitor._make_worker = make_worker

    assert monitor.restart_one_stream(1)["ok"] is True
    assert monitor.stop_dataflow()["ok"] is True
    assert not hasattr(monitor.flowgraph, "_shutdown_ids")
    assert not hasattr(monitor.flowgraph, "_shutdown_status_queues")
    assert "status_queue" not in worker_kwargs[0]
    assert "shutdown_id" not in worker_kwargs[0]


@pytest.mark.parametrize(
    "exitcode,stuck,expected_ok",
    [(0, False, True), (3, False, False), (0, True, False)],
)
def test_plain_stop_reports_process_outcome(exitcode, stuck, expected_ok):
    worker = Worker(exitcode=exitcode, stuck=stuck)
    monitor = monitor_for(workers=[worker])

    result = monitor.stop_stream(0, join_timeout_sec=0.01)

    assert result["ok"] is expected_ok
    assert result["forced_termination"] is stuck
    assert worker.terminated is stuck
    assert worker.closed
    assert worker.join_timeouts[0] == 0.01


def test_plain_whole_flow_stop_shares_timeout_budget(monkeypatch):
    workers = [Worker(), Worker()]
    monitor = monitor_for(workers=workers)
    now = iter([100.0, 102.0, 106.0])
    monkeypatch.setattr(
        "Morelia.Watchdog.dataflowMonitor.time.monotonic", lambda: next(now)
    )

    assert monitor.stop_dataflow(join_timeout_sec=5)["ok"] is True
    assert workers[0].join_timeouts == [3.0]
    assert workers[1].join_timeouts == [0.0]


@pytest.mark.parametrize("emit_acknowledgements", [False, True])
def test_dashboard_monitor_preserves_required_acknowledgements(emit_acknowledgements):
    worker = Worker()
    # Already exited: the real coordinator drains all queued evidence.
    worker.join()
    monitor = monitor_for(AcknowledgedDataFlow, [worker], AcknowledgedDataFlowMonitor)
    queue = Queue()
    monitor.flowgraph._shutdown_status_queues = [queue]
    monitor.flowgraph._shutdown_ids = ["dashboard-shutdown"]
    if emit_acknowledgements:
        for phase in REQUIRED_SHUTDOWN_PHASES[:-1]:
            queue.put(
                ShutdownAction(
                    shutdown_id="dashboard-shutdown",
                    stream_index=0,
                    actor="dataflow_worker",
                    actor_pid=worker.pid,
                    phase=phase,
                    action=phase.value,
                    outcome="acknowledged",
                    emitted_at_ns=1,
                )
            )

    result = monitor.stop_stream(0)

    assert result["ok"] is emit_acknowledgements
    assert result["shutdown_id"] == "dashboard-shutdown"
    assert result["terminal_phase"] == (
        "complete" if emit_acknowledgements else "failed"
    )
    assert bool(result["missing_phases"]) is not emit_acknowledgements
    assert result["transcript"]


def test_dashboard_noop_start_keeps_identity_and_queue():
    monitor = monitor_for(
        AcknowledgedDataFlow, monitor_type=AcknowledgedDataFlowMonitor
    )
    ids = ["dashboard-0", "dashboard-1"]
    queues = [Queue(), Queue()]
    monitor.flowgraph._shutdown_ids = ids.copy()
    monitor.flowgraph._shutdown_status_queues = queues.copy()

    assert monitor.start_stream(1)["status"] == "already_running"
    assert monitor.flowgraph._shutdown_ids == ids
    assert monitor.flowgraph._shutdown_status_queues == queues


def test_production_dashboard_factory_selects_adapter_and_plain_watchdog_does_not():
    dashboard_watchdog, _, _, flow_type, *_ = _import_morelia()
    plain = Watchdog(flowgraph=DataFlow([]))
    dashboard = dashboard_watchdog(flowgraph=flow_type([]))
    try:
        assert type(plain.dataflow_monitor) is DataFlowMonitor
        assert type(dashboard.dataflow_monitor) is AcknowledgedDataFlowMonitor
    finally:
        plain.dataflow_monitor.close()
        dashboard.dataflow_monitor.close()


def test_dashboard_restart_replaces_identity_and_still_requires_evidence(monkeypatch):
    monitor = monitor_for(
        AcknowledgedDataFlow, monitor_type=AcknowledgedDataFlowMonitor
    )
    monitor.flowgraph._shutdown_ids = ["old-0", "old-1"]
    monitor.flowgraph._shutdown_status_queues = [Queue(), Queue()]
    monkeypatch.setattr("Morelia.Watchdog.dataflowMonitor.mp.Event", threading.Event)
    monkeypatch.setattr("app.runtime_child.acknowledged_monitor._create_shutdown_queue", Queue)
    monitor.reset_stream_device = lambda index: {"ok": True}
    monitor._clear_stream_heartbeat_unlocked = lambda index: None
    monitor._rebuild_dataflow = lambda index: (object(), [])
    captured = {}

    def make_worker(*args, **kwargs):
        captured.update(kwargs)
        return Worker()

    monitor.flowgraph.make_worker = make_worker
    result = monitor.restart_one_stream(1)

    assert result["ok"] is True
    assert monitor.flowgraph._shutdown_ids[0] == "old-0"
    assert captured["shutdown_id"] not in {"old-0", "old-1", None, ""}
    assert monitor.flowgraph._shutdown_ids[1] == captured["shutdown_id"]
    assert monitor.flowgraph._shutdown_status_queues[1] is captured["status_queue"]
    assert captured["stream_index"] == 1
    stopped = monitor.stop_dataflow()
    assert (
        stopped["ok"] is False
    )  # Exit code zero alone never certifies dashboard shutdown.
    assert monitor.flowgraph._shutdown_ids == []
    assert monitor.flowgraph._shutdown_status_queues == []


def test_dashboard_failed_start_closes_new_queue_without_publishing_identity(monkeypatch):
    monitor = monitor_for(AcknowledgedDataFlow, monitor_type=AcknowledgedDataFlowMonitor)
    monitor.flowgraph._workers[1] = None
    old_queue = Queue()
    monitor.flowgraph._shutdown_ids = ["old-0", "old-1"]
    monitor.flowgraph._shutdown_status_queues = [Queue(), old_queue]

    class ClosableQueue(Queue):
        closed = False
        joined = False

        def close(self):
            self.closed = True

        def join_thread(self):
            self.joined = True

    class FailedStartWorker(Worker):
        def start(self):
            raise RuntimeError("spawn failed")

    new_queue = ClosableQueue()
    monkeypatch.setattr("Morelia.Watchdog.dataflowMonitor.mp.Event", threading.Event)
    monkeypatch.setattr("app.runtime_child.acknowledged_monitor._create_shutdown_queue", lambda: new_queue)
    monitor._rebuild_dataflow = lambda index: (object(), [])
    monitor.flowgraph.make_worker = lambda *args, **kwargs: FailedStartWorker()

    with pytest.raises(RuntimeError, match="spawn failed"):
        monitor.start_stream(1)

    assert new_queue.closed and new_queue.joined
    assert monitor.flowgraph._shutdown_ids == ["old-0", "old-1"]
    assert monitor.flowgraph._shutdown_status_queues[1] is old_queue
    assert monitor.flowgraph._workers[1] is None
