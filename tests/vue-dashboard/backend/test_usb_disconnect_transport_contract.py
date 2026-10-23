import ast
from pathlib import Path
import uuid

import pytest
from ftd2xx import ftd2xx
from ftd2xx.defines import Status

from Morelia.Stream.data_flow import DataFlow
from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
from Morelia.Watchdog.watchdog import StreamWatcher
from app.discovery import ftdi_transport, native_gate
from app.discovery.managed_pods import Pod


class NativeHandle:
    def __init__(self, serial, *, read_status=None, write_status=None, close_status=None):
        self.serial = serial
        self.read_status = read_status
        self.write_status = write_status
        self.close_status = close_status
        self.close_calls = 0

    def getDeviceInfo(self):
        return {"serial": self.serial.encode()}

    def setBaudRate(self, *_args):
        pass

    def setDataCharacteristics(self, *_args):
        pass

    def setFlowControl(self, *_args):
        pass

    def setTimeouts(self, *_args):
        pass

    def purge(self, *_args):
        pass

    def read(self, _count):
        if self.read_status is not None:
            ftd2xx.call_ft(lambda: self.read_status)
        return b""

    def write(self, data):
        if self.write_status is not None:
            ftd2xx.call_ft(lambda: self.write_status)
        return len(data)

    def close(self):
        self.close_calls += 1
        if self.close_status is not None:
            ftd2xx.call_ft(lambda: self.close_status)


@pytest.fixture
def transport_setup(monkeypatch):
    serial = "ORACLE_" + uuid.uuid4().hex
    monkeypatch.setattr(native_gate, "_MUTEX_NAME", "Local\\Morelia.Oracle." + uuid.uuid4().hex)
    handles = []

    def open_handle(_serial):
        handle = NativeHandle(serial)
        handles.append(handle)
        return handle

    monkeypatch.setattr(ftdi_transport, "_open_native_serial", open_handle)
    yield serial, handles
    for handle in handles:
        handle.close_status = None
    ftdi_transport.retry_pending_cleanup(serial)


def real_monitor(serial):
    source = Pod(serial, use_d2xx=True, probe=True)
    flow = DataFlow([(source, [])])
    flow._workers = [None]
    flow._manual_stop_events = [None]
    monitor = DataFlowMonitor(port_resolver=lambda _index: serial, port_presence_checker=lambda _index: True)
    monitor.flowgraph = flow
    monitor.snapshot_config = monitor._capture_dataflow_info(flow)
    monitor.set_lifecycle_state(0, "running")
    return monitor, source


def real_watcher(monitor):
    return StreamWatcher(0, monitor, failure_threshold=3, max_heartbeat_age_sec=10,
                         interval_sec=.01, timeout_sec=.01, recovery_policy="automate",
                         max_auto_restart_attempts=3, publish=lambda *_args: None)


@pytest.mark.parametrize("status", [Status.IO_ERROR, Status.DEVICE_NOT_FOUND, Status.DEVICE_NOT_OPENED])
def test_real_ftd2xx_read_exception_survives_transport_wrapper(transport_setup, status):
    serial, handles = transport_setup
    port = ftdi_transport.D2XXPortIO(serial)
    handles[-1].read_status = status
    try:
        with pytest.raises(OSError) as caught:
            port.read(1, timeout_sec=.2)
        assert isinstance(caught.value.__cause__, ftd2xx.DeviceError)
        assert str(caught.value.__cause__) == status.name
        assert StreamWatcher._is_port_lock_error(f"{type(caught.value).__name__}: {caught.value}")
    finally:
        port.close_serial_port()


@pytest.mark.parametrize("status", [Status.IO_ERROR, Status.DEVICE_NOT_FOUND, Status.DEVICE_NOT_OPENED])
def test_real_reset_write_error_reaches_watcher_without_budget_cost(transport_setup, monkeypatch, status):
    serial, handles = transport_setup

    def open_handle(_serial):
        handle = NativeHandle(serial, write_status=status)
        handles.append(handle)
        return handle

    monkeypatch.setattr(ftdi_transport, "_open_native_serial", open_handle)
    monitor, source = real_monitor(serial)
    watcher = real_watcher(monitor)
    try:
        for _attempt in range(4):
            result = watcher._try_reconnect()
            assert result["action"] == "waiting_for_port_release", result
            assert watcher._recovery_attempt_count == 0
            assert status.name in result["restart_result"]["error"]
        assert source._port is None
    finally:
        source.close_port()


@pytest.mark.parametrize("error_factory", [
    lambda: ftd2xx.DeviceError(Status.IO_ERROR),
    lambda: ftd2xx.DeviceError(Status.DEVICE_NOT_FOUND),
    lambda: ftd2xx.DeviceError(Status.DEVICE_NOT_OPENED),
    lambda: PermissionError("Access is denied"),
])
def test_reset_open_race_preserves_temporary_error_for_watcher(transport_setup, monkeypatch, error_factory):
    serial, handles = transport_setup
    opens = 0

    def open_handle(_serial):
        nonlocal opens
        opens += 1
        if opens == 1:
            handle = NativeHandle(serial)
            handles.append(handle)
            return handle
        raise error_factory()

    monkeypatch.setattr(ftdi_transport, "_open_native_serial", open_handle)
    monitor, source = real_monitor(serial)
    watcher = real_watcher(monitor)
    try:
        result = watcher._try_reconnect()
        assert result["action"] == "waiting_for_port_release", result
        assert watcher._recovery_attempt_count == 0
    finally:
        source.close_port()


def test_real_unrelated_native_failure_exhausts_restart_budget(transport_setup, monkeypatch):
    serial, handles = transport_setup

    def open_handle(_serial):
        handle = NativeHandle(serial, write_status=Status.INVALID_PARAMETER)
        handles.append(handle)
        return handle

    monkeypatch.setattr(ftdi_transport, "_open_native_serial", open_handle)
    monitor, source = real_monitor(serial)
    watcher = real_watcher(monitor)
    try:
        results = [watcher._try_reconnect() for _ in range(4)]
        assert results[-1]["action"] == "needs_action"
        assert watcher._recovery_attempt_count == 3
    finally:
        source.close_port()


def test_native_close_failure_retains_handle_until_successful_retry(transport_setup):
    serial, handles = transport_setup
    source = Pod(serial, use_d2xx=True, probe=True)
    source.open_port_for_reset()
    handle = handles[-1]
    handle.close_status = Status.IO_ERROR
    with pytest.raises(ftdi_transport.NativeHandleCleanupError) as caught:
        source.close_port()
    assert source._port is not None
    assert source._port._ftd2xx_handle is handle
    assert ftdi_transport.pending_cleanup(serial) is caught.value
    assert not StreamWatcher._is_port_lock_error(f"{type(caught.value).__name__}: {caught.value}")
    released = []
    caught.value.add_release_callback(lambda: released.append(True))
    assert released == []
    handle.close_status = None
    source.close_port()
    assert source._port is None
    assert ftdi_transport.pending_cleanup(serial) is None
    assert released == [True]


def test_old_classifier_negative_control_rejects_actual_native_read_error(transport_setup):
    root = Path(__file__).resolve().parents[3]
    path = root / ".audit/session10-disconnect/source-snapshot/src__Morelia__Watchdog__watchdog.py"
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    watcher_class = next(node for node in parsed.body if isinstance(node, ast.ClassDef) and node.name == "StreamWatcher")
    method = next(node for node in watcher_class.body if isinstance(node, ast.FunctionDef) and node.name == "_is_port_lock_error")
    method.decorator_list = []
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    serial, handles = transport_setup
    port = ftdi_transport.D2XXPortIO(serial)
    handles[-1].read_status = Status.IO_ERROR
    try:
        with pytest.raises(OSError) as caught:
            port.read(1, timeout_sec=.2)
        error_text = f"{type(caught.value).__name__}: {caught.value}"
        assert namespace["_is_port_lock_error"](error_text) is False
        assert StreamWatcher._is_port_lock_error(error_text) is True
    finally:
        port.close_serial_port()
