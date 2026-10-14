"""Driver-contract tests; synthetic FTDI never certifies physical hardware."""
import importlib
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

driver = importlib.import_module("app.discovery.ftdi_transport")
helpers = importlib.import_module("app.discovery.ftdi_transport")


@pytest.fixture
def native(monkeypatch):
    handle = Mock()
    handle.getDeviceInfo.return_value = {"serial": b"000123A"}
    handle.read.return_value = b""
    ftd = Mock()
    ftd.createDeviceInfoList.return_value = 1
    ftd.getDeviceInfoDetail.return_value = {"serial": b"000123A", "description": b"POD", "flags": 2}
    ftd.openEx.return_value = handle
    monkeypatch.setattr(driver, "ftd", ftd)
    monkeypatch.setattr(driver, "_open_native_serial", lambda serial: ftd.openEx(serial.encode(), flags=1, update=False), raising=False)
    monkeypatch.setattr(driver.time, "sleep", lambda _: None)
    return ftd, handle


def test_exact_native_selector_profile_and_rx_constant(native):
    ftd, handle = native
    io = driver.D2XXPortIO("000123A", d2xx_serial_only=True, flow_control="none",
                           read_timeout_ms=250, write_timeout_ms=700)
    ftd.openEx.assert_called_once_with(b"000123A", flags=1, update=False)
    ftd.createDeviceInfoList.assert_not_called()
    ftd.getDeviceInfoDetail.assert_not_called()
    ftd.open.assert_not_called()
    handle.setFlowControl.assert_called_once_with(0, 0x11, 0x13)
    handle.setTimeouts.assert_called_once_with(250, 700)
    assert io.read(8) is None
    handle.read.side_effect = OSError("USB removed")
    with pytest.raises(OSError, match="USB removed"):
        io.read(8)
    io.purge_rx()
    assert handle.purge.call_args.args == (1,)
    io.close_serial_port()
    handle.close.assert_called_once()


@pytest.mark.parametrize("selector", ["3", "COM3", "POD", "000123a", "000123"])
def test_exact_selector_never_becomes_index_or_alias(native, selector):
    ftd, handle = native
    with pytest.raises(ValueError, match="differs from requested serial"):
        driver.D2XXPortIO(selector, d2xx_serial_only=True)
    ftd.open.assert_not_called()
    ftd.openEx.assert_called_once_with(selector.encode(), flags=1, update=False)
    handle.close.assert_called_once_with()
    handle.setBaudRate.assert_not_called()
    handle.purge.assert_not_called()


def test_legacy_numeric_string_does_not_become_index(native):
    ftd, _ = native
    with pytest.raises(ValueError):
        driver.D2XXPortIO("0")
    ftd.open.assert_not_called()


def test_direct_open_does_not_depend_on_inventory(native, monkeypatch):
    ftd, _ = native
    monkeypatch.setattr(driver, "list_d2xx_devices", Mock(side_effect=AssertionError("inventory forbidden")))
    ftd.createDeviceInfoList.side_effect = AssertionError("inventory forbidden")
    port = driver.D2XXPortIO("000123A", d2xx_serial_only=True)
    port.close_serial_port()
    ftd.openEx.assert_called_once()


@pytest.mark.parametrize("failure", ["identity", "configuration"])
def test_partial_open_failure_releases_handle(native, failure):
    _, handle = native
    if failure == "identity":
        handle.getDeviceInfo.return_value = {"serial": b"OTHER"}
    else:
        handle.setTimeouts.side_effect = OSError("configure failed")
    with pytest.raises((ValueError, OSError)):
        driver.D2XXPortIO("000123A", d2xx_serial_only=True)
    handle.close.assert_called_once()


def test_native_enumeration_preserves_exact_identity(native):
    row, = helpers.list_d2xx_devices(native_only=True)
    assert row["serial"] == "000123A"
    assert row["backend"] == "ftd2xx"
    assert row["flags"] == 2


def test_native_enumeration_refreshes_inventory_only_once(native):
    ftd, _ = native
    ftd.createDeviceInfoList.return_value = 3

    def cached_detail(index, *, update=True):
        assert update is False, "Detail lookup would refresh the full USB list again"
        return {"serial": f"DEVICE{index}".encode(), "description": b"POD"}

    ftd.getDeviceInfoDetail.side_effect = cached_detail
    rows = helpers.list_d2xx_devices(native_only=True)
    assert [row["serial"] for row in rows] == ["DEVICE0", "DEVICE1", "DEVICE2"]
    ftd.createDeviceInfoList.assert_called_once_with()
    assert ftd.getDeviceInfoDetail.call_count == 3


def test_native_enumeration_preserves_location_metadata(native):
    ftd, _ = native
    ftd.getDeviceInfoDetail.return_value["location"] = 12345
    assert helpers.list_d2xx_devices(native_only=True)[0]["location"] == 12345


def test_native_driver_status_is_an_io_failure_not_a_timeout(native):
    _, handle = native
    handle.read.side_effect = Exception("FT_IO_ERROR")
    port = driver.D2XXPortIO("000123A")
    try:
        with pytest.raises(OSError, match="FT_IO_ERROR"):
            port.read(1)
    finally:
        port.close_serial_port()


@pytest.mark.parametrize("operation", ["read", "write"])
def test_stream_io_does_not_hold_native_transaction_gate(native, operation):
    _, handle = native
    port = driver.D2XXPortIO("000123A")
    entered, release = threading.Event(), threading.Event()
    failures = []

    def blocking_io(value):
        entered.set()
        assert release.wait(timeout=2)
        return b"x" if operation == "read" else len(value)

    getattr(handle, operation).side_effect = blocking_io
    def stream():
        try:
            getattr(port, operation)(1 if operation == "read" else b"x")
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=stream)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        with driver.native_driver_gate(timeout_sec=.1):
            pass
    finally:
        release.set()
        worker.join(timeout=2)
        port.close_serial_port()
    assert not worker.is_alive()
    assert failures == []


def test_partial_reads_update_remaining_timeout_without_global_gate(native, monkeypatch):
    _, handle = native
    port = driver.D2XXPortIO("000123A", read_timeout_ms=5000, write_timeout_ms=700)
    handle.setTimeouts.reset_mock()
    handle.read.side_effect = [b"ab", b"cd", b"ef"]
    ticks = iter([10.0, 10.001, 10.011, 10.026, 10.051])
    with monkeypatch.context() as patch:
        patch.setattr(driver.time, "monotonic", lambda: next(ticks))
        patch.setattr(driver, "native_driver_gate", Mock(side_effect=AssertionError(
            "Per-read timeout changes must not wait for the global driver gate"
        )))
        with port.deadline(.05):
            assert port.read(6, .05) == b"ab"
            assert port.read(4, .05) == b"cd"
            assert port.read(2, .05) == b"ef"
            with pytest.raises(TimeoutError, match="deadline"):
                port.read(1, .05)
        driver.native_driver_gate.assert_not_called()
    read_timeouts = [call.args[0] for call in handle.setTimeouts.call_args_list]
    assert len(read_timeouts) == 3
    assert 0 < read_timeouts[2] < read_timeouts[1] < read_timeouts[0] <= 50
    assert all(call.args[1] == 700 for call in handle.setTimeouts.call_args_list)
    assert handle.read.call_count == 3
    port.close_serial_port()


def strict_monitor(resolver=None):
    from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
    source = SimpleNamespace(port="000123A", _use_d2xx=True, _d2xx_serial_only=True,
                             close_port=Mock())
    monitor = DataFlowMonitor(port_resolver=resolver)
    monitor.flowgraph = SimpleNamespace(_network=[(source, [])])
    monitor.snapshot_config = [{"source": {"source_dict": {
        "port": "000123A", "use_d2xx": True, "d2xx_serial_only": True,
        "flow_control": "none", "read_timeout_ms": 250, "write_timeout_ms": 700,
    }}}]
    monitor._hw.reset_streaming_device = Mock(return_value={"ok": True})
    return monitor


def test_strict_monitor_never_accepts_case_description_or_index_alias(monkeypatch):
    monitor = strict_monitor()
    listing = Mock(return_value=[{"serial": "000123a", "description": "000123A", "index": 0}])
    from Morelia.Devices.SerialPorts import d2xx_helpers as legacy_helpers
    monkeypatch.setattr(legacy_helpers, "list_d2xx_devices", listing)
    assert not monitor.is_stream_port_present(0)
    listing.assert_called_once_with()
    with pytest.raises(FileNotFoundError):
        monitor.reset_stream_device(0)
    monitor._hw.reset_streaming_device.assert_not_called()


def test_strict_monitor_revalidates_frozen_identity_before_reset(monkeypatch):
    resolver = Mock(side_effect=ValueError("physical identity changed"))
    monitor = strict_monitor(resolver)
    with pytest.raises(ValueError, match="physical identity"):
        monitor.is_stream_port_present(0)
    with pytest.raises(ValueError, match="physical identity"):
        monitor.reset_stream_device(0)
    monitor._hw.reset_streaming_device.assert_not_called()
    resolver.side_effect = None
    resolver.return_value = "000123a"
    with pytest.raises(ValueError, match="exact serial"):
        monitor.reset_stream_device(0)
    monitor._hw.reset_streaming_device.assert_not_called()


def test_strict_monitor_openability_preserves_profile_and_selector(monkeypatch):
    resolver = Mock(return_value="000123A")
    monitor = strict_monitor(resolver)
    source = monitor.flowgraph._network[0][0]
    source.open_port_for_reset = Mock()
    assert monitor.is_stream_port_openable(0, attempts=1)
    source.open_port_for_reset.assert_called_once_with()
    source.close_port.assert_called_once_with()
    resolver.assert_called_once_with(0)



def test_strict_monitor_reset_keeps_cancellation_guard_first():
    resolver = Mock(return_value="000123A")
    monitor = strict_monitor(resolver)
    monitor.flowgraph._acquisition_guard = Mock(side_effect=RuntimeError("cancelled"))
    with pytest.raises(RuntimeError, match="cancelled"):
        monitor.reset_stream_device(0)
    resolver.assert_not_called()
    monitor._hw.reset_streaming_device.assert_not_called()


def test_standalone_native_device_filter_keeps_case_distinct_serials():
    from Morelia.Watchdog.watchdog import Watchdog
    monitor = strict_monitor()
    monitor.get_all_stream_status = lambda: [{"stream_index": 0}]
    watchdog = Watchdog.__new__(Watchdog)
    watchdog.dataflow_monitor = monitor
    same = SimpleNamespace(port="000123A", _d2xx_serial_only=True)
    other = SimpleNamespace(port="000123a", _d2xx_serial_only=True)
    assert watchdog._filter_standalone_devices([same, other]) == [other]


def test_strict_missing_native_never_falls_back_to_libftdi(monkeypatch):
    monkeypatch.setattr(driver, "ftd", None)
    monkeypatch.setattr(driver, "_native_wrapper", None)
    with pytest.raises(ImportError):
        helpers.list_d2xx_devices(native_only=True)
    with pytest.raises(ImportError):
        driver.D2XXPortIO("000123A", d2xx_serial_only=True)


@pytest.mark.parametrize("prefix", [b"", b"\x02" + b"0002"])
def test_continuous_garbage_obeys_one_packet_deadline(monkeypatch, prefix):
    from app.discovery.managed_pods import Pod

    ticks = iter(i / 20 for i in range(200))
    monkeypatch.setattr(driver.time, "monotonic", lambda: next(ticks))
    calls = []
    data = iter(prefix)

    def read(count):
        calls.append(count)
        assert len(calls) < 100, "reader ignored total deadline"
        return bytes([next(data, ord("x"))])

    port = driver.VcpPortIO.__new__(driver.VcpPortIO)
    port.read_timeout_ms = 5000
    port._serial_inst = SimpleNamespace(read=read, timeout=5, close=lambda: None)
    pod = Pod("COM3", probe=True)
    pod._port = port
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            pod.read_pod_packet(timeout_sec=0.5)
        assert len(calls) < 15
    finally:
        pod.cleanup()
