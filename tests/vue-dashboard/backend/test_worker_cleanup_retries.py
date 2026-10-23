"""Builder self-checks; teardown authority is the original OS Process object.

Real multiprocessing processes, coordinator, adapters, watchdog orchestration,
and temporary outbox. Only the hardware runtime driver is replaced in watchdog
tests. No production database, service, or USB device is used.
"""

import multiprocessing as mp
import os
import threading
from queue import Queue

import pytest

from app.domain.enums import PolicyMode, SinkType
from app.output.managed_pvfs_sink import ManagedPvfsSink
from Morelia.shutdown import REQUIRED_SHUTDOWN_PHASES, ShutdownAction, ShutdownPhase
from app.runtime_child.acknowledged_dataflow import AcknowledgedDataFlow
from app.runtime_child.acknowledged_monitor import AcknowledgedDataFlowMonitor
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.watchdog_process.outbox import WatchdogOutbox
from app.watchdog_process.process import WatchdogIdentity, WatchdogProcess
from app.watchdog_process.telemetry_client import TelemetryClient


def _flow_monitor(workers, events=None):
    flow = AcknowledgedDataFlow([(object(), []) for _ in workers])
    flow._workers = list(workers)
    flow._manual_stop_events = events or [mp.Event() for _ in workers]
    flow._shutdown_status_queues = [mp.Queue() for _ in workers]
    flow._shutdown_ids = [f"worker-{index}" for index in range(len(workers))]
    monitor = AcknowledgedDataFlowMonitor()
    monitor.flowgraph = flow
    monitor.snapshot_config = [{} for _ in workers]
    return flow, monitor


@pytest.mark.parametrize("exitcode", [0, 1])
def test_unacknowledged_exit_releases_exact_worker_without_claiming_output(exitcode):
    worker = mp.Process(target=os._exit, args=(exitcode,))
    worker.start()
    worker.join(timeout=10)
    assert worker.exitcode == exitcode and not worker.is_alive()
    flow, monitor = _flow_monitor([worker])
    try:
        result = monitor._stop_worker(worker, flow._manual_stop_events[0], 0, 0.1)
        assert result["teardown_confirmed"] is True
        assert result["worker_exited"] is True
        assert result["worker_exitcode"] == exitcode
        assert result["ok"] is False
        assert "sinks_finalized" in result["missing_phases"]
        assert result["forced_termination"] is False
        # A repeated Stop must reuse the receipt, not read a closed queue.
        assert monitor._stop_worker(worker, None, 0, 0.1) == result
    finally:
        worker.close()


@pytest.mark.parametrize("use_monitor", [False, True])
def test_never_started_worker_does_not_block_launched_sibling_cleanup(use_monitor):
    unstarted = mp.Process(target=os._exit, args=(0,))
    release = mp.Event()
    launched = mp.Process(target=release.wait)
    launched.start()
    assert launched.pid is not None
    flow, monitor = _flow_monitor([unstarted, launched], [mp.Event(), release])
    result = (monitor.stop_dataflow(join_timeout_sec=3) if use_monitor
              else flow.stop_collection(join_timeout_sec=3))
    assert result["teardown_confirmed"] is True
    assert result["ok"] is False  # The launched sibling supplied no output acknowledgements.
    assert len(result["stream_results"]) == 2
    assert result["stream_results"][0]["worker_started"] is False
    assert result["stream_results"][0]["worker_exited"] is False
    assert result["stream_results"][1]["worker_exitcode"] == 0
    assert flow._workers == []


def test_live_worker_keeps_queue_and_original_reference_while_stop_waits():
    release = mp.Event()
    worker = mp.Process(target=release.wait)
    worker.start()
    flow, monitor = _flow_monitor([worker])
    status_queue = flow._shutdown_status_queues[0]
    results = []
    thread = threading.Thread(target=lambda: results.append(
        monitor._stop_worker(worker, None, 0, 5)))
    thread.start()
    try:
        assert worker.is_alive() and worker.exitcode is None
        assert flow._workers[0] is worker
        assert flow._shutdown_status_queues[0] is status_queue
        assert not status_queue._closed
        assert not results
    finally:
        release.set()
        thread.join(timeout=10)
        worker.join(timeout=10)
        worker.close()
    assert results[0]["teardown_confirmed"] is True
    assert results[0]["ok"] is False


def test_prior_generation_release_is_required_by_monitor_aggregate():
    worker = mp.Process(target=os._exit, args=(0,))
    worker.start()
    worker.join(timeout=10)
    flow, monitor = _flow_monitor([worker])
    flow._prior_shutdown_results = [{
        "shutdown_id": "previous-worker", "ok": False,
        "teardown_confirmed": False, "forced_termination": True,
    }]
    result = monitor.stop_dataflow(join_timeout_sec=0.1)
    assert result["stream_results"][0]["teardown_confirmed"] is True
    assert result["teardown_confirmed"] is False
    assert result["ok"] is False and result["forced_termination"] is True
    assert result["previous_stream_results"][0]["shutdown_id"] == "previous-worker"


class _LaterExitDriver:
    """Driver fixture delays cleanup receipt until an actual child exits."""

    phase = RuntimePhase.RUNNING
    shutdown_result = None

    def __init__(self, worker, flow, monitor, *, reports_clean=False):
        self.worker, self.flow, self.monitor = worker, flow, monitor
        self.reports_clean = reports_clean
        self.stop_calls = self.close_calls = 0

    def stop(self):
        self.stop_calls += 1
        if self.worker.is_alive():
            self.shutdown_result = {
                "ok": False, "teardown_confirmed": False,
                "error": "worker_still_alive", "stream_results": [],
            }
            return
        row = self.monitor._stop_worker(self.worker, None, 0, 0.1)
        self.shutdown_result = {"ok": row["ok"],
                                "teardown_confirmed": row["teardown_confirmed"],
                                "stream_results": [row], "worker_inventory_complete": True}
        if self.reports_clean:
            # Deliberately optimistic driver receipt: watchdog must preserve
            # its own previous failure even if a later driver says clean.
            self.shutdown_result = {"ok": True, "teardown_confirmed": True,
                                    "worker_inventory_complete": True}

    def close(self):
        self.close_calls += 1
        self.phase = RuntimePhase.CLOSED
        self.shutdown_result["resources_teardown_confirmed"] = True


def _watchdog(tmp_path, driver):
    outbox = WatchdogOutbox(tmp_path / "outbox.sqlite3")
    process = WatchdogProcess(
        manifest=Manifest(schema_version=MANIFEST_SCHEMA_VERSION,
                          dataflow_id="cleanup", policy=PolicyMode.RECOMMEND,
                          device_flows=(DeviceFlow(
                              device_id="device", name="device", nickname=None,
                              hardware_id="hardware", port="unused", parameters={},
                              sink_type=SinkType.CSV, sink_location="unused.csv",
                          ),)),
        identity=WatchdogIdentity(runtime_id="runtime", watchdog_id="watchdog"),
        outbox=outbox,
        telemetry_client=TelemetryClient(base_url="http://unused.invalid"),
        build_driver=lambda **kwargs: driver,
    )
    # Fatal-stop shutdown skips delivery; assertions inspect the real outbox.
    process._stopped = True
    return process, outbox


@pytest.mark.parametrize("reports_clean", [False, True])
def test_watchdog_retries_negative_receipt_after_original_process_exits(tmp_path, reports_clean):
    release = mp.Event()
    worker = mp.Process(target=release.wait)
    worker.start()
    flow, monitor = _flow_monitor([worker])
    driver = _LaterExitDriver(worker, flow, monitor, reports_clean=reports_clean)
    watchdog, outbox = _watchdog(tmp_path, driver)
    try:
        first = watchdog.shutdown()
        assert first["teardown_confirmed"] is False
        assert worker.is_alive() and worker.exitcode is None
        release.set()
        worker.join(timeout=10)
        assert worker.exitcode == 0
        second = watchdog.shutdown()
        assert second["teardown_confirmed"] is True
        assert second["output_integrity_confirmed"] is False
        assert second["shutdown_result"]["ok"] is False
        assert second["shutdown_result"]["previous_shutdown_result"]["error"] == "worker_still_alive"
        assert driver.stop_calls == driver.close_calls == 2
        assert watchdog.shutdown() is second
        assert driver.stop_calls == 2
        finished = [row.envelope.payload for row in outbox.pending()
                    if row.envelope.event_type == "runtime.stop_finished"]
        assert [row["teardown_confirmed"] for row in finished] == [False, True]
    finally:
        release.set()
        worker.join(timeout=10)
        worker.close()
        outbox.close()


@pytest.mark.parametrize("previous_released", [False, True])
def test_watchdog_preserves_prior_generation_teardown_and_output(tmp_path, previous_released):
    class Driver:
        phase = RuntimePhase.RUNNING
        shutdown_result = {
            "ok": True, "teardown_confirmed": True,
            "worker_inventory_complete": True, "resources_teardown_confirmed": True,
            "stream_results": [{"ok": True, "teardown_confirmed": True}],
            "previous_stream_results": [{"ok": False, "teardown_confirmed": previous_released}],
        }

        def stop(self):
            pass

        def close(self):
            self.phase = RuntimePhase.CLOSED

    watchdog, outbox = _watchdog(tmp_path, Driver())
    try:
        result = watchdog.shutdown()
        assert result["teardown_confirmed"] is previous_released
        assert result["output_integrity_confirmed"] is False
    finally:
        outbox.close()


@pytest.mark.parametrize("writer_process", [False, True])
def test_crashed_pvfs_worker_requires_descendant_proof_when_writer_configured(writer_process):
    worker = mp.Process(target=os._exit, args=(1,))
    worker.start()
    worker.join(timeout=10)
    flow, monitor = _flow_monitor([worker])
    flow._network[0] = (object(), [ManagedPvfsSink(
        path="unused.pvfs", dataflow_id="cleanup", use_writer_process=writer_process)])
    status_queue = flow._shutdown_status_queues[0]
    try:
        first = monitor.stop_dataflow(join_timeout_sec=0.1)
        row = first["stream_results"][0]
        assert row["worker_exited"] is True and row["worker_exitcode"] == 1
        assert row["descendants_possible"] is writer_process
        assert row["descendants_teardown_confirmed"] is not writer_process
        assert row["teardown_confirmed"] is not writer_process
        assert first["worker_inventory_complete"] is True
        assert first["previous_stream_results"] == []
        if writer_process:
            assert flow._workers[0] is worker
            assert flow._shutdown_status_queues[0] is status_queue
            assert not status_queue._closed
            # Changed descriptors must not downgrade the stopped generation's
            # original possibility of owning a child process.
            flow._network[0] = (object(), [])
            second = monitor.stop_dataflow(join_timeout_sec=0.1)
            assert second["teardown_confirmed"] is False
            assert second["stream_results"][0]["descendants_possible"] is True
    finally:
        if writer_process:
            status_queue.close()
            status_queue.join_thread()
            worker.close()


def test_pvfs_successful_sink_receipt_confirms_descendants():
    worker = mp.Process(target=os._exit, args=(0,))
    worker.start()
    worker.join(timeout=10)
    flow, monitor = _flow_monitor([worker])
    flow._network[0] = (object(), [ManagedPvfsSink(
        path="unused.pvfs", dataflow_id="cleanup", use_writer_process=True)])
    flow._shutdown_status_queues[0].close()
    flow._shutdown_status_queues[0].join_thread()
    queue = Queue()  # Sink-boundary fixture, using the original coordinator.
    flow._shutdown_status_queues[0] = queue
    for phase in REQUIRED_SHUTDOWN_PHASES[:-1]:
        queue.put(ShutdownAction(
            shutdown_id="worker-0", stream_index=0, actor="dataflow_worker",
            actor_pid=worker.pid, phase=phase,
            action="all_sinks_closed" if phase is ShutdownPhase.SINKS_FINALIZED else phase.value,
            outcome="acknowledged", emitted_at_ns=1,
        ))
    result = monitor.stop_dataflow(join_timeout_sec=0.1)
    assert result["ok"] is True and result["teardown_confirmed"] is True
    assert result["stream_results"][0]["descendants_teardown_confirmed"] is True


@pytest.mark.parametrize("missing", ["configured_stream", "prior_generation"])
def test_incomplete_worker_inventory_cannot_confirm_teardown(missing):
    worker = mp.Process(target=os._exit, args=(0,))
    flow, monitor = _flow_monitor([worker])
    if missing == "configured_stream":
        flow._network.append((object(), []))
    else:
        flow._shutdown_generation_ids.add("unaccounted-previous-generation")
    result = monitor.stop_dataflow(join_timeout_sec=0.1)
    assert result["stream_results"][0]["teardown_confirmed"] is True
    assert result["worker_inventory_complete"] is False
    assert result["teardown_confirmed"] is False and result["ok"] is False


def test_clean_previous_generation_remains_in_complete_inventory():
    worker = mp.Process(target=os._exit, args=(0,))
    flow, monitor = _flow_monitor([worker])
    previous = {
        "shutdown_id": "earlier", "stream_index": 0, "ok": True,
        "teardown_confirmed": True, "worker_accounted": True,
        "descendants_teardown_confirmed": True,
    }
    flow.retain_previous_shutdown(previous)
    flow._shutdown_generation_ids.add("earlier")
    result = monitor.stop_dataflow(join_timeout_sec=0.1)
    assert result["previous_stream_results"] == [previous]
    assert result["worker_inventory_complete"] is True
    assert result["teardown_confirmed"] is True and result["ok"] is True


@pytest.mark.parametrize("missing", ["worker_inventory_complete", "resources_teardown_confirmed"])
def test_watchdog_does_not_confirm_partial_cleanup_receipt(tmp_path, missing):
    class Driver:
        phase = RuntimePhase.RUNNING
        shutdown_result = {"ok": True, "teardown_confirmed": True,
                           "worker_inventory_complete": True,
                           "resources_teardown_confirmed": True}

        def stop(self):
            pass

        def close(self):
            pass

    driver = Driver()
    driver.shutdown_result.pop(missing)
    watchdog, outbox = _watchdog(tmp_path, driver)
    try:
        result = watchdog.shutdown()
        assert result["teardown_confirmed"] is False
        assert result["output_integrity_confirmed"] is False
        assert result["previous_stream_results"] == []
    finally:
        outbox.close()


@pytest.mark.parametrize("failure", ["source_close", "make_worker"])
@pytest.mark.parametrize("use_monitor", [False, True])
def test_prepared_slots_are_accounted_and_queues_closed_on_construction_failure(failure, use_monitor):
    class Source:
        _port = None

        def close_port(self):
            if failure == "source_close":
                raise RuntimeError("source close failed")

    flow = AcknowledgedDataFlow([(Source(), []), (Source(), [])])

    def fail_make_worker(*args, **kwargs):
        raise RuntimeError("make worker failed")

    flow.make_worker = fail_make_worker
    with pytest.raises(RuntimeError, match="failed"):
        flow._start_collecting()
    prepared_queue = flow._shutdown_status_queues[0]
    assert prepared_queue is not None and not prepared_queue._closed
    assert flow._workers == [None, None]
    monitor = AcknowledgedDataFlowMonitor()
    monitor.flowgraph = flow
    monitor.snapshot_config = [{}, {}]
    result = (monitor.stop_dataflow(join_timeout_sec=0.1) if use_monitor
              else flow.stop_collection(join_timeout_sec=0.1))
    assert result["worker_inventory_complete"] is True
    assert result["teardown_confirmed"] is True
    assert len(result["stream_results"]) == 2
    assert all(row["worker_started"] is False for row in result["stream_results"])
    assert prepared_queue._closed
    assert flow._workers == []


@pytest.mark.parametrize("replacement", [False, True])
def test_start_error_after_real_spawn_retains_exact_child_and_queue(monkeypatch, replacement):
    release = mp.Event()
    worker = mp.Process(target=release.wait)
    flow, monitor = _flow_monitor([])
    flow._network = [(object(), [])]
    monitor.snapshot_config = [{}]
    original_start = mp.Process.start

    def start_then_fail(process):
        original_start(process)
        raise RuntimeError("failed after spawn")

    monkeypatch.setattr(mp.Process, "start", start_then_fail)
    flow.make_worker = lambda *args, **kwargs: worker
    try:
        with pytest.raises(RuntimeError, match="failed after spawn"):
            if replacement:
                monitor._start_worker(1, release, object(), [], 0)
            else:
                flow._start_collecting()
        assert worker.pid is not None and worker.is_alive()
        assert flow._workers[0] is worker
        assert flow._ever_started_worker is True
        queue = flow._shutdown_status_queues[0]
        assert not queue._closed
        release.set()
        result = monitor.stop_dataflow(join_timeout_sec=3)
        assert result["worker_inventory_complete"] is True
        assert result["teardown_confirmed"] is True
        assert result["stream_results"][0]["worker_exitcode"] == 0
        assert queue._closed and flow._workers == []
    finally:
        release.set()
        if not worker._closed:
            if worker.is_alive():
                worker.terminate()
            if worker._popen is not None:
                worker.join(timeout=10)
            worker.close()


@pytest.mark.parametrize("use_monitor", [False, True])
def test_preflight_only_stop_accounts_every_configured_unlaunched_slot(use_monitor):
    flow = AcknowledgedDataFlow([(object(), []), (object(), [ManagedPvfsSink(
        path="unused.pvfs", dataflow_id="cleanup", use_writer_process=True)])])
    monitor = AcknowledgedDataFlowMonitor()
    monitor.flowgraph = flow
    monitor.snapshot_config = [{}, {}]
    result = (monitor.stop_dataflow(join_timeout_sec=0.1) if use_monitor
              else flow.stop_collection(join_timeout_sec=0.1))
    assert result["worker_inventory_complete"] is True
    assert result["teardown_confirmed"] is True and result["ok"] is True
    assert result["previous_stream_results"] == []
    assert [row["stream_index"] for row in result["stream_results"]] == [0, 1]
    assert all(row["worker_started"] is False for row in result["stream_results"])
    assert all(row["descendants_teardown_confirmed"] is True for row in result["stream_results"])


def test_prepared_queue_close_failure_retains_none_slot_and_retries(monkeypatch):
    flow = AcknowledgedDataFlow([(object(), [])])
    queue = mp.Queue()
    flow._shutdown_status_queues[0] = queue
    shutdown_id = flow._shutdown_ids[0]
    monitor = AcknowledgedDataFlowMonitor()
    monitor.flowgraph = flow
    monitor.snapshot_config = [{}]
    original_close = type(queue).close
    close_calls = []

    def fail_first_close(candidate):
        if candidate is queue:
            close_calls.append(True)
            if len(close_calls) == 1:
                raise OSError("queue close failed once")
        return original_close(candidate)

    monkeypatch.setattr(type(queue), "close", fail_first_close)
    first = monitor.stop_dataflow(join_timeout_sec=0.1)
    assert first["teardown_confirmed"] is False
    assert flow._workers == [None]
    assert flow._shutdown_status_queues[0] is queue and not queue._closed
    assert flow._shutdown_ids == [shutdown_id]
    assert flow._shutdown_results[0]["teardown_confirmed"] is True
    second = monitor.stop_dataflow(join_timeout_sec=0.1)
    assert second["worker_inventory_complete"] is True
    assert second["teardown_confirmed"] is True
    assert len(close_calls) == 2 and queue._closed
    assert flow._workers == flow._shutdown_status_queues == flow._shutdown_ids == []
