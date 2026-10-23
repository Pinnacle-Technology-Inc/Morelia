"""SELF_CHECKED real spawn/recovery test with synthetic physical source and sink."""
import multiprocessing as mp
from pathlib import Path
import sys
import threading

import pytest

from app.runtime_child.acknowledged_dataflow import AcknowledgedDataFlow
from app.runtime_child.acknowledged_monitor import AcknowledgedDataFlowMonitor
from Morelia.Watchdog.watchdog import Watchdog


class FailingFinalizer:
    def __init__(self, finalized, pod=None):
        self.finalized = finalized

    def get_dict(self):
        return {"finalized": self.finalized}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.finalized.set()
        raise RuntimeError("intentional sink finalization failure")

    def flush(self, *_args):
        pass


@pytest.mark.parametrize("disable_gate", [False, True], ids=["fenced", "negative-control"])
def test_cancellation_during_rebuild_prevents_replacement(disable_gate):
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    # Reuse pytest's collected module when present; a second import would give
    # spawn different class objects under the same qualified name.
    existing = next((module for module in tuple(sys.modules.values())
                     if str(getattr(module, "__file__", "")).endswith("test_watchdog_plain_shutdown_spawn.py")), None)
    if existing is not None:
        sys.modules["test_watchdog_plain_shutdown_spawn"] = existing
    from test_watchdog_plain_shutdown_spawn import Source, FinalizedSink
    Source.__module__ = "test_watchdog_plain_shutdown_spawn"
    FinalizedSink.__module__ = "test_watchdog_plain_shutdown_spawn"

    ready, finalized = mp.Event(), mp.Event()
    rebuilding, resume, cancelled = threading.Event(), threading.Event(), threading.Event()
    flow = AcknowledgedDataFlow([(Source(ready), [FinalizedSink(finalized)])])

    def guard():
        if cancelled.is_set():
            raise RuntimeError("acquisition cancelled")

    flow._acquisition_guard = guard

    def rebuild(_):
        rebuilding.set()
        assert resume.wait(10)
        return Source(ready), [FinalizedSink(finalized)]

    watchdog = Watchdog(flowgraph=flow, reconstruction_hook=rebuild,
                        dataflow_monitor_factory=AcknowledgedDataFlowMonitor)
    monitor = watchdog.dataflow_monitor
    monitor._hw.reset_streaming_device = lambda _: {"ok": True}
    result = []
    worker_thread = None
    try:
        flow.collect()
        assert ready.wait(10)
        worker_thread = threading.Thread(target=lambda: result.append(monitor.restart_one_stream(0)))
        worker_thread.start()
        assert rebuilding.wait(10)
        cancelled.set()
        if disable_gate:
            flow._acquisition_guard = None
        resume.set()
        worker_thread.join(10)
        assert not worker_thread.is_alive()
        if disable_gate:
            assert result[0]["ok"] is True, "negative control must actually restart"
            assert flow._workers[0].is_alive()
        else:
            assert result[0]["ok"] is False
            assert "cancelled" in result[0]["error"]
            assert flow._workers[0] is None
    finally:
        resume.set()
        if worker_thread is not None:
            worker_thread.join(10)
        for event in flow._manual_stop_events:
            if event is not None:
                event.set()
        monitor.stop_dataflow(join_timeout_sec=5)
        monitor.close()


@pytest.mark.parametrize("unclean", [False, True], ids=["clean", "failed-finalizer"])
def test_final_stop_preserves_receipt_for_worker_already_stopped_during_outage(unclean):
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    existing = next((module for module in tuple(sys.modules.values())
                     if str(getattr(module, "__file__", "")).endswith("test_watchdog_plain_shutdown_spawn.py")), None)
    if existing is not None:
        sys.modules["test_watchdog_plain_shutdown_spawn"] = existing
    from test_watchdog_plain_shutdown_spawn import Source, FinalizedSink
    Source.__module__ = "test_watchdog_plain_shutdown_spawn"
    FinalizedSink.__module__ = "test_watchdog_plain_shutdown_spawn"
    sys.modules["test_timed_watchdog_recovery_spawn"] = sys.modules[__name__]
    FailingFinalizer.__module__ = "test_timed_watchdog_recovery_spawn"

    ready, finalized = mp.Event(), mp.Event()
    sink_type = FailingFinalizer if unclean else FinalizedSink
    flow = AcknowledgedDataFlow([(Source(ready), [sink_type(finalized)])])
    watchdog = Watchdog(flowgraph=flow, dataflow_monitor_factory=AcknowledgedDataFlowMonitor)
    monitor = watchdog.dataflow_monitor
    try:
        flow.collect()
        assert ready.wait(10)
        earlier = monitor.stop_stream(0, join_timeout_sec=5)
        assert earlier["ok"] is (not unclean), earlier
        assert earlier["transcript"]
        assert flow._workers[0] is None
        final = monitor.stop_dataflow(join_timeout_sec=5)
        assert final["ok"] is (not unclean), final
        retained = final["stream_results"][0]
        assert retained["shutdown_id"] == earlier["shutdown_id"]
        assert retained["transcript"] == earlier["transcript"]
        # The worker exited and this sink owns no descendant process. Failed
        # finalization still makes ok false; it does not keep hardware owned.
        assert retained["teardown_confirmed"] is True
        assert retained["descendants_teardown_confirmed"] is True
        assert retained["missing_phases"] == earlier["missing_phases"]
        assert finalized.is_set()
    finally:
        monitor.stop_dataflow(join_timeout_sec=5)
        monitor.close()


@pytest.mark.parametrize("whole_flow", [False, True], ids=["one-stream", "whole-flow"])
def test_clean_replacement_preserves_prior_failed_generation(whole_flow):
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    existing = next((module for module in tuple(sys.modules.values())
                     if str(getattr(module, "__file__", "")).endswith("test_watchdog_plain_shutdown_spawn.py")), None)
    if existing is not None:
        sys.modules["test_watchdog_plain_shutdown_spawn"] = existing
    from test_watchdog_plain_shutdown_spawn import Source, FinalizedSink
    Source.__module__ = "test_watchdog_plain_shutdown_spawn"
    FinalizedSink.__module__ = "test_watchdog_plain_shutdown_spawn"
    sys.modules["test_timed_watchdog_recovery_spawn"] = sys.modules[__name__]
    FailingFinalizer.__module__ = "test_timed_watchdog_recovery_spawn"

    ready, finalized = mp.Event(), mp.Event()
    recording_queue = mp.Queue()
    flow = AcknowledgedDataFlow(
        [(Source(ready), [FailingFinalizer(finalized)])], recording_queue=recording_queue)
    guard = lambda: None
    flow._acquisition_guard = guard
    watchdog = Watchdog(
        flowgraph=flow,
        reconstruction_hook=lambda _: (Source(ready), [FinalizedSink(finalized)]),
        dataflow_monitor_factory=AcknowledgedDataFlowMonitor)
    monitor = watchdog.dataflow_monitor
    monitor._hw.reset_streaming_device = lambda _: {"ok": True}
    try:
        flow.collect()
        assert ready.wait(10)
        earlier_id = flow._shutdown_ids[0]
        ready.clear()
        restarted = monitor.restart_all_stream() if whole_flow else monitor.restart_one_stream(0)
        assert restarted["ok"] is True, restarted
        assert ready.wait(10)
        current = monitor.flowgraph
        assert current._recording_queue is recording_queue
        assert current._acquisition_guard is guard
        assert current._registered_stop_events is flow._registered_stop_events
        assert current._shutdown_ids[0] != earlier_id
        # The original runtime registry must still cancel a rebuilt flow.
        for event in flow._registered_stop_events:
            event.set()
        result = monitor.stop_dataflow(join_timeout_sec=5)
        assert result["ok"] is False, result
        assert result["error"] == "prior_stream_shutdown_unclean"
        earlier = result["previous_stream_results"]
        assert len(earlier) == 1
        assert earlier[0]["shutdown_id"] == earlier_id
        assert earlier[0]["ok"] is False
        assert earlier[0]["transcript"]
        assert result["stream_results"][0]["ok"] is True
        assert result["stream_results"][0]["teardown_confirmed"] is True
    finally:
        monitor.stop_dataflow(join_timeout_sec=5)
        monitor.close()
        recording_queue.close()
        recording_queue.join_thread()
