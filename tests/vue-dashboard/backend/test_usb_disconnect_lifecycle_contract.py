import ast
import multiprocessing as mp
from pathlib import Path
import time

import pytest

from app.discovery import managed_pods
from app.discovery.ftdi_transport import D2XXPortIO, VcpPortIO
from app.runtime_child.acknowledged_dataflow import acknowledged_get_data_wrapper
from Morelia.Stream import source
from Morelia.shutdown import coordinate_shutdown


ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / ".audit/usb-disconnect-fix/before/source.py"


class NativeDriverError(Exception):
    pass


class RawHardware:
    def __init__(self, native, broken, close_fails, ownership, progress, ready, restored):
        self.native, self.broken, self.close_fails = native, broken, close_fails
        self.ownership, self.progress, self.ready = ownership, progress, ready
        self.restored = restored
        self.timeout = 0.2
        self.is_open = True
        assert ownership.acquire(timeout=2), "hardware ownership was already held"

    def read(self, count):
        self.ready.set()
        if self.broken and not self.restored.is_set():
            if self.native:
                raise NativeDriverError("IO_ERROR")
            raise PermissionError("device unavailable")
        time.sleep(0.005)
        with self.progress.get_lock():
            self.progress.value += 1
        return b"x" * count

    def write(self, message):
        if message == b"stop" and self.broken and not self.restored.is_set():
            if self.native:
                raise NativeDriverError("IO_ERROR")
            raise PermissionError("device unavailable")
        return len(message)

    def close(self):
        if self.close_fails:
            raise OSError("independent close failure")
        if self.is_open:
            self.ownership.release()
            self.is_open = False

    def setTimeouts(self, *_):
        pass


class HardwareBoundaryPod(managed_pods.Pod8401HR):
    def __init__(self, native, broken, close_fails, ownership, progress, ready, restored):
        managed_pods.Pod.__init__(self, port="oracle-usb", use_d2xx=native, probe=True)
        self._sample_rate = (200,)
        self._raw = RawHardware(native, broken, close_fails, ownership, progress, ready, restored)
        if native:
            port = D2XXPortIO.__new__(D2XXPortIO)
            port._ftd2xx_handle = self._raw
            port._cached_timeouts = None
            port.port, port.read_timeout_ms, port.write_timeout_ms = "oracle-usb", 200, 200
        else:
            port = VcpPortIO.__new__(VcpPortIO)
            port._serial_inst = self._raw
            port.port, port.read_timeout_ms, port.write_timeout_ms = "oracle-usb", 200, 200
        self._port = port

    def write_packet(self, command, value):
        assert command == "STREAM"
        self._port.write(b"start" if value else b"stop")

    def read_pod_packet_streaming(self, **_):
        return self._port.read(1)

    def read_pod_packet(self, **_):
        raise TimeoutError("drain complete")

    def check_write_queue(self):
        pass


class ObservationSink:
    observe_on_scheduler = None

    def __init__(self, pod):
        self.pod = pod

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def flush(self, *_):
        pass


def worker_entry(stop, statuses, shutdown_id, native, broken, close_fails, ownership,
                 progress, ready, restored, baseline, disable_cleanup):
    if disable_cleanup:
        from app.runtime_child.acknowledged_dataflow import _SourceLifecycleProxy
        from Morelia.shutdown import ShutdownPhase

        def exit_without_cleanup(self, *args):
            try:
                return self._source.__exit__(*args)
            finally:
                if self._reporter is not None and self._stop_event.is_set() and not self._stop_observed:
                    self._reporter.emit(ShutdownPhase.STOP_OBSERVED, "stop_event_observed")
                    self._stop_observed = True

        _SourceLifecycleProxy.__exit__ = exit_without_cleanup
    if baseline:
        tree = ast.parse(BASELINE.read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "_stream_from_pod_device")
        module = ast.Module(body=[function], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(BASELINE), "exec"), source.__dict__)
    acknowledged_get_data_wrapper(
        30, stop, HardwareBoundaryPod,
        dict(native=native, broken=broken, close_fails=close_fails,
             ownership=ownership, progress=progress, ready=ready, restored=restored),
        [(ObservationSink, {})], shutdown_queue=statuses, shutdown_id=shutdown_id, stream_index=0,
    )


def start_worker(ctx, *, native, broken, close_fails=False, baseline=False, disable_cleanup=False):
    stop, ready, restored = ctx.Event(), ctx.Event(), ctx.Event()
    ownership, progress, statuses = ctx.Lock(), ctx.Value("i", 0), ctx.Queue()
    shutdown_id = f"oracle-{native}-{broken}-{close_fails}-{baseline}"
    worker = ctx.Process(target=worker_entry,
        args=(stop, statuses, shutdown_id, native, broken, close_fails, ownership, progress, ready, restored, baseline, disable_cleanup))
    worker.start()
    if not ready.wait(30):
        stop.set()
        worker.join(3)
        if worker.is_alive():
            worker.terminate()
            worker.join(3)
        statuses.close()
        statuses.join_thread()
        pytest.fail(f"worker never reached the hardware boundary: exitcode={worker.exitcode}")
    return dict(worker=worker, stop=stop, statuses=statuses, shutdown_id=shutdown_id,
                ownership=ownership, progress=progress, restored=restored)


def stop_worker(item):
    return coordinate_shutdown(item["worker"], item["stop"], item["statuses"],
                               item["shutdown_id"], 0, 5)


def release_status_queue(item):
    item["stop"].set()
    item["worker"].join(3)
    if item["worker"].is_alive():
        item["worker"].terminate()
        item["worker"].join(3)
    item["statuses"].close()
    item["statuses"].join_thread()


def assert_port_released_with_ordered_proof(item, result):
    acquired = item["ownership"].acquire(timeout=0.2)
    if acquired:
        item["ownership"].release()
    assert acquired, "port ownership leaked when the USB stop command failed"
    phases = [row.phase.value for row in result["transcript"]]
    assert "source_stopped" in phases, phases
    assert phases.index("source_stopped") < phases.index("sinks_finalizing"), phases
    assert "protocol_violation" not in phases, phases
    assert result["ok"], result


@pytest.mark.parametrize("native", [True, False], ids=["d2xx-io-error", "vcp-permission-error"])
def test_disconnect_stop_releases_port_and_does_not_stop_healthy_peer(native):
    ctx = mp.get_context("spawn")
    healthy = start_worker(ctx, native=native, broken=False)
    broken = start_worker(ctx, native=native, broken=True)
    try:
        before = healthy["progress"].value
        result = stop_worker(broken)
        time.sleep(0.08)
        assert healthy["worker"].is_alive()
        assert healthy["progress"].value > before + 2
        assert_port_released_with_ordered_proof(broken, result)
        assert stop_worker(healthy)["ok"]
    finally:
        release_status_queue(broken)
        release_status_queue(healthy)


@pytest.mark.parametrize("native", [True, False], ids=["d2xx", "vcp"])
def test_genuine_close_failure_cannot_certify_source_shutdown(native):
    item = start_worker(mp.get_context("spawn"), native=native, broken=True, close_fails=True)
    try:
        result = stop_worker(item)
        assert not result["ok"]
        assert not item["ownership"].acquire(timeout=0.1), "close failure was incorrectly treated as release"
        assert "source_stopped" not in [row.phase.value for row in result["transcript"]]
    finally:
        release_status_queue(item)


@pytest.mark.parametrize("native", [True, False], ids=["d2xx", "vcp"])
def test_temporary_read_failure_resumes_in_same_live_worker(native):
    item = start_worker(mp.get_context("spawn"), native=native, broken=True)
    try:
        original_pid = item["worker"].pid
        time.sleep(0.15)
        assert item["worker"].is_alive()
        assert item["progress"].value == 0
        item["restored"].set()
        deadline = time.monotonic() + 3
        while item["progress"].value < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert item["progress"].value >= 5
        assert item["worker"].pid == original_pid and item["worker"].is_alive()
        assert_port_released_with_ordered_proof(item, stop_worker(item))
    finally:
        release_status_queue(item)


def test_saved_source_without_finally_is_protected_by_backend_proxy():
    item = start_worker(mp.get_context("spawn"), native=True, broken=True, baseline=True)
    try:
        assert_port_released_with_ordered_proof(item, stop_worker(item))
    finally:
        release_status_queue(item)


def test_bypassing_proxy_cleanup_is_rejected_by_same_shutdown_contract():
    item = start_worker(mp.get_context("spawn"), native=True, broken=True, disable_cleanup=True)
    try:
        result = stop_worker(item)
        with pytest.raises(AssertionError, match="port ownership leaked"):
            assert_port_released_with_ordered_proof(item, result)
        assert "protocol_violation" in [row.phase.value for row in result["transcript"]]
    finally:
        release_status_queue(item)
