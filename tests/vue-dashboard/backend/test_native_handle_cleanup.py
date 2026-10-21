"""Real installed ftd2xx wrapper, with all native operations replaced at the DLL boundary."""

import ctypes
from contextlib import contextmanager
import importlib
from types import SimpleNamespace

import pytest
from app.discovery import ftdi_transport as transport


@pytest.fixture
def dll(monkeypatch):
    try:
        wrapper = importlib.import_module("ftd2xx.ftd2xx")
    except (ImportError, OSError) as exc:
        pytest.skip(f"Installed native wrapper unavailable: {exc}")
    state = SimpleNamespace(
        events=[], info_error=False, setup_error=False, close_error=False,
        open_error=False, serial=b"000123A", wrapper=wrapper,
    )
    native = wrapper._ft

    def opened(serial, flags, pointer):
        state.events.append(("open", serial, flags.value))
        if state.open_error:
            return wrapper.defines.Status.DEVICE_NOT_FOUND
        ctypes.cast(pointer, ctypes.POINTER(native.FT_HANDLE))[0] = native.FT_HANDLE(0x1234)
        return 0

    def closed(handle):
        state.events.append(("close", handle.value))
        return wrapper.defines.Status.IO_ERROR if state.close_error else 0

    def info(handle, kind, device_id, serial, description, dummy):
        state.events.append(("info", handle.value))
        if state.info_error:
            return wrapper.defines.Status.IO_ERROR
        serial.value = state.serial
        description.value = b"POD"
        return 0

    def timeouts(handle, read, write):
        state.events.append(("timeouts", read.value, write.value))
        return wrapper.defines.Status.IO_ERROR if state.setup_error else 0

    def unexpected_refresh(*args):
        pytest.fail("Opening must not refresh the process-global inventory")

    monkeypatch.setattr(native, "FT_OpenEx", opened)
    monkeypatch.setattr(native, "FT_Close", closed)
    monkeypatch.setattr(native, "FT_GetDeviceInfo", info)
    monkeypatch.setattr(native, "FT_CreateDeviceInfoList", unexpected_refresh)
    monkeypatch.setattr(native, "FT_SetTimeouts", timeouts)
    def configured(name):
        def call(*args):
            state.events.append(("configure", name))
            return 0
        return call

    for name in ("FT_SetBaudRate", "FT_SetDataCharacteristics", "FT_SetFlowControl", "FT_Purge"):
        monkeypatch.setattr(native, name, configured(name))
    monkeypatch.setattr(transport, "_native_wrapper", wrapper)
    monkeypatch.setattr(transport, "list_d2xx_devices", unexpected_refresh)
    yield state
    # Keep cleanup owners from one fault-injection case out of subsequent tests.
    state.close_error = False
    transport.retry_pending_cleanup("000123A")


def close_events(dll):
    return [event for event in dll.events if event[0] == "close"]


def test_raw_native_handle_closed_when_real_wrapper_constructor_fails(dll):
    dll.info_error = True
    with pytest.raises(dll.wrapper.DeviceError, match="IO_ERROR"):
        transport._open_native_serial("000123A")
    assert dll.events == [("open", b"000123A", 1), ("info", 0x1234), ("close", 0x1234)]


def test_negative_control_installed_openex_has_no_constructor_failure_cleanup(dll):
    """The same DLL failure exposes the defect if the safe adapter is removed."""
    dll.info_error = True
    with pytest.raises(dll.wrapper.DeviceError, match="IO_ERROR"):
        dll.wrapper.openEx(b"000123A", flags=1, update=False)
    assert dll.events == [("open", b"000123A", 1), ("info", 0x1234)]


def test_failed_native_open_does_not_close_an_unacquired_handle(dll):
    dll.open_error = True
    with pytest.raises(dll.wrapper.DeviceError, match="DEVICE_NOT_FOUND"):
        transport._open_native_serial("000123A")
    assert close_events(dll) == []


def test_success_transfers_handle_ownership_and_preserves_exact_selector(dll):
    port = transport.D2XXPortIO("000123A", flow_control="none")
    assert isinstance(port._ftd2xx_handle, dll.wrapper.FTD2XX)
    assert dll.events[0] == ("open", b"000123A", 1)
    assert close_events(dll) == []
    port.close_serial_port()
    port.close_serial_port()
    assert close_events(dll) == [("close", 0x1234)]
    assert not port.is_serial_open()
    assert port._cached_timeouts is None


@pytest.mark.parametrize("failure", ["wrong_serial", "configuration"])
def test_postconstruction_failure_closes_once(dll, failure):
    if failure == "wrong_serial":
        dll.serial = b"000123a"
    else:
        dll.setup_error = True
    with pytest.raises((ValueError, dll.wrapper.DeviceError)):
        transport.D2XXPortIO("000123A")
    assert close_events(dll) == [("close", 0x1234)]
    if failure == "wrong_serial":
        assert not any(event[0] == "configure" for event in dll.events)


def test_explicit_close_failure_keeps_handle_for_retry(dll):
    port = transport.D2XXPortIO("000123A")
    handle = port._ftd2xx_handle
    dll.close_error = True
    with pytest.raises(transport.NativeHandleCleanupError) as caught:
        port.close_serial_port()
    assert transport.pending_cleanup("000123A") is caught.value
    assert port._ftd2xx_handle is handle
    assert port.is_serial_open()
    dll.close_error = False
    port.close_serial_port()
    assert not port.is_serial_open()
    assert len(close_events(dll)) == 2


@pytest.mark.parametrize("failure", ["wrapper_constructor", "configuration"])
def test_failed_setup_and_failed_close_preserve_both_errors_and_retry(dll, failure):
    dll.info_error = failure == "wrapper_constructor"
    dll.setup_error = failure == "configuration"
    dll.close_error = True
    with pytest.raises(transport.NativeHandleCleanupError) as caught:
        transport.D2XXPortIO("000123A")
    error = caught.value
    assert error.serial == "000123A"
    assert transport.pending_cleanup("000123A") is error
    assert isinstance(error.operation_error, dll.wrapper.DeviceError)
    assert isinstance(error.cleanup_error, dll.wrapper.DeviceError)
    assert close_events(dll) == [("close", 0x1234)]
    dll.close_error = False
    error.retry_close()
    error.retry_close()
    assert close_events(dll) == [("close", 0x1234), ("close", 0x1234)]
    assert transport.pending_cleanup("000123A") is None


@pytest.mark.parametrize("failure", ["wrapper_constructor", "configuration", "explicit_close"])
def test_pending_cleanup_fences_same_serial_and_releases_lease_after_success(dll, failure):
    if failure == "explicit_close":
        port = transport.D2XXPortIO("000123A")
        operation = port.close_serial_port
    else:
        dll.info_error = failure == "wrapper_constructor"
        dll.setup_error = failure == "configuration"
        operation = lambda: transport.D2XXPortIO("000123A")
    dll.close_error = True
    with pytest.raises(transport.NativeHandleCleanupError) as caught:
        operation()
    owner = caught.value
    released = []
    owner.add_release_callback(lambda: released.append("released"))
    initial_opens = sum(event[0] == "open" for event in dll.events)
    for _ in range(2):
        with pytest.raises(transport.NativeHandleCleanupError) as retry:
            transport.D2XXPortIO("000123A")
        assert retry.value is owner
    assert sum(event[0] == "open" for event in dll.events) == initial_opens
    assert released == []
    assert transport.pending_cleanup("000123a") is None
    dll.info_error = dll.setup_error = dll.close_error = False
    reopened = transport.D2XXPortIO("000123A")
    assert released == ["released"]
    assert transport.pending_cleanup("000123A") is None
    owner.retry_close()
    assert released == ["released"]
    reopened.close_serial_port()


def test_close_gate_timeout_retains_existing_cleanup_owner_and_callback(dll, monkeypatch):
    port = transport.D2XXPortIO("000123A")
    dll.close_error = True
    with pytest.raises(transport.NativeHandleCleanupError) as caught:
        port.close_serial_port()
    owner = caught.value
    released = []
    owner.add_release_callback(lambda: released.append(True))

    @contextmanager
    def timed_out_gate():
        raise TimeoutError("native gate busy")
        yield

    with monkeypatch.context() as patch:
        patch.setattr(transport, "native_driver_gate", timed_out_gate)
        with pytest.raises(transport.NativeHandleCleanupError) as retry:
            port.close_serial_port()
        assert retry.value is owner
        assert released == []
    dll.close_error = False
    owner.retry_close()
    assert released == [True]
