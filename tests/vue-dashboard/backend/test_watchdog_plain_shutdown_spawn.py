"""Exercise unchanged legacy acquisition through the plain watchdog on real processes."""

import multiprocessing as mp
import sys
import time
from pathlib import Path
from queue import Queue

import pytest
from app.runtime_child.acknowledged_dataflow import AcknowledgedDataFlow
from app.runtime_child.acknowledged_monitor import AcknowledgedDataFlowMonitor

from Morelia.Stream.data_flow import DataFlow
from Morelia.Watchdog.watchdog import Watchdog


class Source:
    sample_rate = 100
    _port = None

    def __init__(self, ready):
        self.ready = ready

    def get_dict(self):
        return {"ready": self.ready}

    def open_port(self):
        self._port = object()

    def close_port(self):
        self._port = None

    def obtain_read_queue(self):
        return Queue()

    def check_write_queue(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read_pod_packet_streaming(self, **_kwargs):
        self.ready.set()
        time.sleep(0.005)
        return 1


class FinalizedSink:
    def __init__(self, finalized, pod=None):
        self.finalized = finalized

    def get_dict(self):
        return {"finalized": self.finalized}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.finalized.set()
        return False

    def flush(self, *_args):
        pass


@pytest.mark.parametrize("dashboard", [False, True], ids=["plain", "dashboard"])
def test_two_stream_recovery_and_stop_finalize_real_workers(dashboard):
    # pytest's importlib names contain directory hyphens; give spawn a stable name.
    module_name = "test_watchdog_plain_shutdown_spawn"
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    sys.modules.setdefault(module_name, sys.modules[__name__])
    Source.__module__ = module_name
    FinalizedSink.__module__ = module_name

    ready = [mp.Event(), mp.Event()]
    finalized = [mp.Event(), mp.Event()]

    def build(index):
        return Source(ready[index]), [FinalizedSink(finalized[index])]

    flow_type = AcknowledgedDataFlow if dashboard else DataFlow
    flow = flow_type([build(0), build(1)])
    watchdog = Watchdog(
        flowgraph=flow,
        reconstruction_hook=build,
        dataflow_monitor_factory=AcknowledgedDataFlowMonitor if dashboard else None,
    )
    monitor = watchdog.dataflow_monitor
    # The only substituted operation is physical hardware reset.
    monitor._hw.reset_streaming_device = lambda source: {"ok": True}
    try:
        flow.collect()
        assert all(event.wait(10) for event in ready)
        assert monitor.start_stream(1)["status"] == "already_running"
        old_pid = flow._workers[1].pid
        result = monitor.restart_one_stream(1)
        assert result["ok"] is True, result
        assert finalized[1].is_set(), "old worker did not finalize its sink"
        assert flow._workers[1].pid != old_pid
        finalized[1].clear()
        ready[1].clear()
        assert ready[1].wait(10)

        stopped = monitor.stop_dataflow(join_timeout_sec=5)
        assert stopped["ok"] is True, stopped
        assert all(event.is_set() for event in finalized)
        assert all(
            result["worker_exitcode"] == 0 for result in stopped["stream_results"]
        )
        if dashboard:
            assert all(
                result["terminal_phase"] == "complete"
                for result in stopped["stream_results"]
            )
            assert all(
                not result["missing_phases"] for result in stopped["stream_results"]
            )
            assert all(result["transcript"] for result in stopped["stream_results"])
            assert flow._shutdown_ids == []
            assert flow._shutdown_status_queues == []
        else:
            assert not hasattr(flow, "_shutdown_ids")
            assert not hasattr(flow, "_shutdown_status_queues")
        assert flow._workers == []
    finally:
        # Clean up only this test's workers; don't terminate unrelated child processes.
        for event in flow._manual_stop_events:
            if event is not None:
                event.set()
        for worker in flow._workers:
            if worker is not None:
                worker.join(timeout=2)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=2)
                worker.close()
        monitor.close()
