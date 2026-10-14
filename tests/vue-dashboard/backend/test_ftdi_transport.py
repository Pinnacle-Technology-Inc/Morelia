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
