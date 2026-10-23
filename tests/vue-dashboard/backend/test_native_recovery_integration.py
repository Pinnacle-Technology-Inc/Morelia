"""Caller-level recovery and resource retention; no physical USB is opened."""

from types import SimpleNamespace

import pytest

from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
from app.domain.enums import PolicyMode, SinkType
from app.runtime_child.driver import RuntimePhase
from app.runtime_child.morelia import MoreliaRuntime
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest


def monitor_for(*, present=lambda _index: False, worker=None):
    monitor = DataFlowMonitor(port_resolver=lambda _index: "RAW001",
                              port_presence_checker=present)
    source = SimpleNamespace(port="RAW001", _port=None)
    monitor.flowgraph = SimpleNamespace(_network=[(source, [])], _workers=[worker])
    monitor.snapshot_config = [{"source": {"source_dict": {
        "port": "RAW001", "use_d2xx": True, "d2xx_serial_only": True}}}]
    return monitor, source


def test_frozen_address_does_not_make_unplugged_device_present():
    monitor, _ = monitor_for()
    assert monitor.is_stream_port_present(0) is False
    monitor._port_presence_checker = lambda _index: True
    assert monitor.is_stream_port_present(0) is True


def test_unknown_live_observation_is_not_confirmed_presence():
    monitor, _ = monitor_for(present=lambda _index: None)
    with pytest.raises(RuntimeError, match="observation"):
        monitor.is_stream_port_present(0)


@pytest.mark.parametrize("alive", [False, True])
def test_retained_worker_cannot_be_probed_or_reset(alive):
    monitor, source = monitor_for(worker=SimpleNamespace(is_alive=lambda: alive))
    source.open_port_for_reset = lambda: pytest.fail("Opened a second owner")
    assert monitor.is_stream_port_openable(0, attempts=1) is False
    with pytest.raises(RuntimeError):
        monitor.reset_stream_device(0)


def test_direct_start_cannot_replace_dead_retained_worker():
    worker = SimpleNamespace(is_alive=lambda: False)
    monitor, _ = monitor_for(worker=worker)
    monitor.flowgraph._manual_stop_events = [None]
    with pytest.raises(RuntimeError, match="teardown"):
        monitor.start_stream(0)
    assert monitor.start_dataflow()["ok"] is False
    assert monitor.flowgraph._workers == [worker]


@pytest.mark.parametrize("shutdown_raises", [False, True])
def test_manager_reference_survives_unconfirmed_exit(shutdown_raises):
    monitor, _ = monitor_for()
    alive = [True]
    process = SimpleNamespace(is_alive=lambda: alive[0], exitcode=None)

    def shutdown():
        if shutdown_raises and alive[0]:
            raise OSError("Manager shutdown failed")

    manager = SimpleNamespace(shutdown=shutdown, _process=process)
    monitor._status_manager = manager
    with pytest.raises((RuntimeError, OSError)):
        monitor.close(strict=True)
    assert monitor._status_manager is manager
    assert monitor.close() is False
    alive[0], process.exitcode = False, 0
    assert monitor.close(strict=True) is True
    assert monitor._status_manager is None


def runtime_for(tmp_path):
    manifest = Manifest(schema_version=MANIFEST_SCHEMA_VERSION, dataflow_id="df-cleanup-retry",
        policy=PolicyMode.RECOMMEND, device_flows=(DeviceFlow(
            device_id="device-1", name="pod", nickname=None,
            hardware_id="RAW001", port="RAW001", parameters={},
            sink_type=SinkType.CSV, sink_location=str(tmp_path / "out.csv")),))
    runtime = MoreliaRuntime(manifest=manifest, on_report=lambda _report: None)
    runtime._phase = RuntimePhase.RUNNING
    runtime._flowgraph = SimpleNamespace(_ever_started_worker=True)
    calls = []

    def stopped(**kwargs):
        calls.append("workers")
        return {"ok": True, "teardown_confirmed": True,
                "worker_inventory_complete": True,
                "stream_results": [{"ok": True, "teardown_confirmed": True}],
                "previous_stream_results": []}

    runtime._watchdog = SimpleNamespace(stop=lambda: None, close=lambda: None,
        dataflow_monitor=SimpleNamespace(stop_dataflow=stopped))
    return runtime, calls


def test_late_resource_failure_invalidates_receipt_and_stop_retries(tmp_path):
    runtime, calls = runtime_for(tmp_path)
    cleanup_attempts = []

    def cleanup():
        cleanup_attempts.append(True)
        if len(cleanup_attempts) == 1:
            raise OSError("parent queue close failed")

    pod = SimpleNamespace(_backend_managed=True, close_port=lambda: None, cleanup=cleanup)
    runtime._pods = [pod]
    with pytest.raises(OSError, match="parent queue"):
        runtime.close()
    assert runtime.shutdown_result["teardown_confirmed"] is False
    assert runtime.shutdown_result["resources_teardown_confirmed"] is False
    assert runtime._pods == [pod]
    runtime.close()
    assert calls == ["workers", "workers"]
    assert len(cleanup_attempts) == 2
    assert runtime.shutdown_result["resources_teardown_confirmed"] is True
    assert runtime.phase is RuntimePhase.CLOSED


@pytest.mark.parametrize("failed_index", [0, 1])
def test_pod_queue_cleanup_does_not_skip_failed_queue_on_retry(failed_index):
    from app.discovery.managed_pods import Pod
    pod = Pod("RAW001", use_d2xx=True, probe=True)
    # Probe construction allocates ordinary local queues. Inject closeable
    # owner resources to exercise cleanup without allocating a USB handle.
    pod._owns_queues = True
    calls = [0, 0]

    def close(index):
        calls[index] += 1
        if index == failed_index and calls[index] == 1:
            raise OSError("queue close failed")

    queues = [SimpleNamespace(cancel_join_thread=lambda: None,
                              close=lambda index=index: close(index))
              for index in range(2)]
    pod._write_queue, pod._read_queue = queues
    with pytest.raises(OSError):
        pod.cleanup()
    assert pod._queues_cleaned is False
    pod.cleanup()
    pod.cleanup()
    assert calls[failed_index] == 2
    assert calls[1 - failed_index] == 1
    assert pod._queues_cleaned is True


def test_live_recording_thread_does_not_certify_resource_release(tmp_path):
    runtime, _ = runtime_for(tmp_path)
    alive = [True]
    thread = SimpleNamespace(join=lambda **kwargs: None, is_alive=lambda: alive[0])
    runtime._recording_thread = thread
    with pytest.raises(RuntimeError, match="Recording callback"):
        runtime.close()
    assert runtime._recording_thread is thread
    assert runtime.shutdown_result["resources_teardown_confirmed"] is False
    alive[0] = False
    runtime.close()
    assert runtime.shutdown_result["resources_teardown_confirmed"] is True


def test_live_recovery_watcher_blocks_resource_cleanup_until_exit(tmp_path):
    runtime, calls = runtime_for(tmp_path)
    alive = [True]
    runtime._watchdog._stream_watchers = {0: SimpleNamespace(is_alive=lambda: alive[0])}
    with pytest.raises(RuntimeError, match="cleanup is incomplete"):
        runtime.close()
    assert calls == []
    assert runtime.shutdown_result["resources_teardown_confirmed"] is False
    alive[0] = False
    runtime.close()
    assert calls == ["workers"]
    assert runtime.shutdown_result["resources_teardown_confirmed"] is True


@pytest.mark.parametrize("queue_name", ["_sink_error_queue", "_source_error_queue", "_recording_queue"])
@pytest.mark.parametrize("failure_step", ["close", "join"])
def test_failed_queue_release_retains_owner_until_retry(tmp_path, queue_name, failure_step):
    from queue import Empty
    runtime, _ = runtime_for(tmp_path)
    fail = [True]

    def step(name):
        if fail[0] and name == failure_step:
            raise OSError("queue release failed")

    def empty():
        raise Empty

    owned = SimpleNamespace(close=lambda: step("close"),
                            join_thread=lambda: step("join"), get_nowait=empty)
    setattr(runtime, queue_name, owned)
    with pytest.raises(OSError, match="queue release"):
        runtime.close()
    assert getattr(runtime, queue_name) is owned
    assert runtime.shutdown_result["resources_teardown_confirmed"] is False
    fail[0] = False
    runtime.close()
    assert getattr(runtime, queue_name) is None
    assert runtime.shutdown_result["resources_teardown_confirmed"] is True
