"""Independent user-plan scenarios. USB is replaced only at installed DLL boundary.

Real subprocesses exercise the production OS gate. No live USB operation is allowed.
Oracle contract: .audit/direct-open-oracle-freeze.md.
"""

import ctypes
import importlib
import multiprocessing
import os
import threading
import time
from types import SimpleNamespace

import pytest


def _gate_overlap_worker(start, ready, counts, count_lock, output, local_only):
    if local_only in ("inventory", "open_close"):
        return _driver_transaction_worker(start, ready, counts, count_lock, output, local_only)
    if local_only:
        gate = threading.RLock()
    else:
        from app.discovery.native_gate import native_driver_gate

        gate = native_driver_gate(timeout_sec=5)
    ready.put(os.getpid())
    if not start.wait(10):
        output.put("start timeout")
        return
    with gate:
        with count_lock:
            counts[0] += 1
            counts[1] = max(counts[1], counts[0])
        time.sleep(0.2)
        with count_lock:
            counts[0] -= 1
    output.put("ok")


def _driver_transaction_worker(start, ready, counts, count_lock, output, operation):
    """Exercise actual transport wiring with only FTDI DLL functions replaced."""
    from app.discovery import ftdi_transport as transport

    wrapper = importlib.import_module("ftd2xx.ftd2xx")
    native = wrapper._ft

    def observe():
        with count_lock:
            counts[0] += 1
            counts[1] = max(counts[1], counts[0])
        time.sleep(0.12)
        with count_lock:
            counts[0] -= 1

    def inventory(pointer):
        observe()
        ctypes.cast(pointer, ctypes.POINTER(native.DWORD))[0] = native.DWORD(0)
        return 0

    def opened(serial, flags, pointer):
        observe()
        ctypes.cast(pointer, ctypes.POINTER(native.FT_HANDLE))[0] = native.FT_HANDLE(735)
        return 0

    def info(handle, kind, device_id, serial, description, dummy):
        serial.value = b"AB0MZ1AV"
        description.value = b"Independent oracle POD"
        return 0

    def close(handle):
        observe()
        return 0

    native.FT_CreateDeviceInfoList = inventory
    native.FT_OpenEx = opened
    native.FT_GetDeviceInfo = info
    native.FT_Close = close
    for name in ("FT_SetBaudRate", "FT_SetDataCharacteristics", "FT_SetFlowControl",
                 "FT_SetTimeouts", "FT_Purge"):
        setattr(native, name, lambda *args: 0)
    ready.put(os.getpid())
    if not start.wait(10):
        output.put("start timeout")
        return
    if operation == "inventory":
        transport.list_d2xx_devices()
    else:
        port = transport.D2XXPortIO("AB0MZ1AV")
        port.close_serial_port()
    output.put("ok")


def _gate_timeout_worker(output):
    from app.discovery.native_gate import native_driver_gate

    started = time.monotonic()
    try:
        with native_driver_gate(timeout_sec=0.15):
            output.put(("entered", time.monotonic() - started))
    except Exception as exc:
        output.put((type(exc).__name__, time.monotonic() - started))


def _observe_overlap(local_only):
    context = multiprocessing.get_context("spawn")
    start, ready, output = context.Event(), context.Queue(), context.Queue()
    counts, count_lock = context.Array("i", [0, 0]), context.Lock()
    modes = (["inventory", "open_close", "inventory"]
             if local_only == "transport" else [local_only] * 3)
    workers = [context.Process(target=_gate_overlap_worker,
               args=(start, ready, counts, count_lock, output, mode)) for mode in modes]
    try:
        for worker in workers:
            worker.start()
        for _ in workers:
            ready.get(timeout=15)
        start.set()
        assert [output.get(timeout=15) for _ in workers] == ["ok"] * 3
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        return counts[1]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=3)
        ready.close()
        output.close()


def test_production_gate_serializes_independently_spawned_processes():
    assert _observe_overlap(local_only=False) == 1


def test_transport_inventory_open_and_close_share_real_process_gate():
    try:
        importlib.import_module("ftd2xx.ftd2xx")
    except (ImportError, OSError) as exc:
        pytest.skip(f"Installed D2XX wrapper unavailable: {exc}")
    assert _observe_overlap(local_only="transport") == 1


def test_negative_control_process_local_locks_expose_overlap():
    assert _observe_overlap(local_only=True) > 1


def test_gate_is_nested_and_has_bounded_cross_process_timeout():
    from app.discovery.native_gate import native_driver_gate

    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    worker = context.Process(target=_gate_timeout_worker, args=(output,))
    try:
        with native_driver_gate(timeout_sec=1):
            with native_driver_gate(timeout_sec=0.1):
                worker.start()
                status, elapsed = output.get(timeout=15)
                assert status == "TimeoutError"
                assert 0.08 <= elapsed < 3
        worker.join(timeout=5)
        assert worker.exitcode == 0
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=3)
        output.close()


@pytest.fixture
def usb(monkeypatch):
    from app.discovery import ftdi_transport as transport

    try:
        wrapper = importlib.import_module("ftd2xx.ftd2xx")
    except (ImportError, OSError) as exc:
        pytest.skip(f"Installed D2XX wrapper unavailable: {exc}")
    native = wrapper._ft
    state = SimpleNamespace(events=[], serial=b"AB0MZ1AV", setup_error=False,
                            close_error=False, open_error=False, wrapper=wrapper,
                            transport=transport)

    def opened(serial, flags, pointer):
        state.events.append(("open", serial, flags.value))
        if state.open_error:
            return wrapper.defines.Status.DEVICE_NOT_FOUND
        ctypes.cast(pointer, ctypes.POINTER(native.FT_HANDLE))[0] = native.FT_HANDLE(734)
        return 0

    def info(handle, kind, device_id, serial, description, dummy):
        state.events.append(("identity", handle.value))
        serial.value = state.serial
        description.value = b"Independent oracle POD"
        return 0

    def close(handle):
        state.events.append(("close", handle.value))
        return wrapper.defines.Status.IO_ERROR if state.close_error else 0

    def setup(*args):
        state.events.append(("setup",))
        return wrapper.defines.Status.IO_ERROR if state.setup_error else 0

    def forbidden_inventory(*args):
        pytest.fail("Frozen-native construction touched global inventory")

    monkeypatch.setattr(native, "FT_OpenEx", opened)
    monkeypatch.setattr(native, "FT_GetDeviceInfo", info)
    monkeypatch.setattr(native, "FT_Close", close)
    monkeypatch.setattr(native, "FT_CreateDeviceInfoList", forbidden_inventory)
    monkeypatch.setattr(native, "FT_GetDeviceInfoDetail", forbidden_inventory)
    for name in ("FT_SetBaudRate", "FT_SetDataCharacteristics", "FT_SetFlowControl",
                 "FT_SetTimeouts", "FT_Purge"):
        monkeypatch.setattr(native, name, setup)
    monkeypatch.setattr(transport, "_native_wrapper", wrapper)
    yield state
    state.close_error = False
    retry = getattr(transport, "retry_pending_cleanup", None)
    if retry:
        retry("AB0MZ1AV")


def test_exact_native_constructor_never_refreshes_inventory(usb):
    port = usb.transport.D2XXPortIO("AB0MZ1AV")
    try:
        assert usb.events[0] == ("open", b"AB0MZ1AV", 1)
        assert any(event[0] == "identity" for event in usb.events)
        assert port.get_port_name() == "AB0MZ1AV"
    finally:
        port.close_serial_port()
    assert [event for event in usb.events if event[0] == "close"] == [("close", 734)]


def test_failed_native_open_does_not_close_an_unacquired_handle(usb):
    usb.open_error = True
    with pytest.raises(usb.wrapper.DeviceError, match="DEVICE_NOT_FOUND"):
        usb.transport.D2XXPortIO("AB0MZ1AV")
    assert usb.events == [("open", b"AB0MZ1AV", 1)]


def test_wrong_opened_identity_is_rejected_before_configuration(usb):
    usb.serial = b"AB0MZ1AVA"
    with pytest.raises(ValueError):
        usb.transport.D2XXPortIO("AB0MZ1AV")
    assert not any(event[0] == "setup" for event in usb.events)
    assert [event for event in usb.events if event[0] == "close"] == [("close", 734)]


def test_failed_cleanup_fences_reopen_and_delays_release_callback(usb):
    usb.setup_error = True
    usb.close_error = True
    with pytest.raises(usb.transport.NativeHandleCleanupError) as caught:
        usb.transport.D2XXPortIO("AB0MZ1AV")
    error = caught.value
    released = []
    error.add_release_callback(lambda: released.append("released"))
    assert usb.transport.pending_cleanup("AB0MZ1AV")
    with pytest.raises(Exception):
        usb.transport.D2XXPortIO("AB0MZ1AV")
    assert len([event for event in usb.events if event[0] == "open"]) == 1
    assert released == []
    usb.close_error = False
    usb.transport.retry_pending_cleanup("AB0MZ1AV")
    assert released == ["released"]
    assert not usb.transport.pending_cleanup("AB0MZ1AV")
    usb.transport.retry_pending_cleanup("AB0MZ1AV")
    assert released == ["released"]


def _frozen_binding():
    return {"transport": "d2xx", "backend": "ftd2xx", "address": "AB0MZ1AV",
            "hardware_id": "AB0MZ1AVA", "physical_id": "AB0MZ1AV", "baudrate": 9600,
            "flow_control": "rts_cts", "read_timeout_ms": 5000,
            "write_timeout_ms": 5000, "selection_reason": "explicit_preference"}


def _native_row(serial, **extra):
    return {"transport": "d2xx", "backend": "ftd2xx", "address": serial,
            "hardware_id": serial, **extra}


def test_saved_native_address_and_current_presence_are_separate(monkeypatch):
    from app.services import connections
    from app.runtime_child.device_connection import current_connection_address

    def forbidden_inventory():
        pytest.fail("Selecting frozen address attempted live discovery")

    monkeypatch.setattr(connections, "list_native_endpoints", forbidden_inventory)
    flow = SimpleNamespace(connection=_frozen_binding(), hardware_id="AB0MZ1AVA")
    assert current_connection_address(flow, "pod8401hr") == "AB0MZ1AV"
    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [])
    assert connections.native_connection_present(flow.connection) is False


def test_live_exact_native_presence_survives_missing_logical_alias(monkeypatch):
    from app.services import connections

    binding = _frozen_binding()
    original = binding.copy()
    monkeypatch.setattr(connections, "list_native_endpoints",
                        lambda: [_native_row("AB0MZ1AV")])
    assert connections.native_connection_present(binding) is True
    assert binding == original


@pytest.mark.parametrize("rows", [
    [_native_row("AB0MZ1AV"), _native_row("AB0MZ1AV")],
    [_native_row("AB0MZ1AV", identity_conflict=True)],
    [_native_row("OTHER", aliases=["AB0MZ1AVA"], physical_id="OTHER")],
    [_native_row("AB0MZ1AV", physical_id="OTHER")],
    [_native_row("AB0MZ1AV", backend="pyserial")],
])
def test_contradictory_live_native_evidence_blocks_recovery(monkeypatch, rows):
    from app.services import connections

    monkeypatch.setattr(connections, "list_native_endpoints", lambda: rows)
    with pytest.raises(connections.ConnectionResolutionError) as caught:
        connections.native_connection_present(_frozen_binding())
    assert caught.value.code == "identity_ambiguous"


@pytest.mark.parametrize("rows", [[], [_native_row("AB0MZ1AVa")]])
def test_complete_inventory_without_exact_native_is_absent(monkeypatch, rows):
    from app.services import connections

    monkeypatch.setattr(connections, "list_native_endpoints", lambda: rows)
    assert connections.native_connection_present(_frozen_binding()) is False


def test_blank_inventory_is_observation_failure_not_saved_presence(monkeypatch):
    from app.services import connections

    monkeypatch.setattr(connections, "list_native_endpoints",
                        lambda: [_native_row("", flags=1)])
    with pytest.raises(connections.ConnectionResolutionError) as caught:
        connections.native_connection_present(_frozen_binding())
    assert caught.value.code == "identity_unavailable"


def test_native_presence_never_falls_back_to_vcp(monkeypatch):
    from app.services import connections

    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [])
    def forbidden_vcp():
        pytest.fail("Frozen native presence switched transport")
    monkeypatch.setattr(connections, "list_vcp_endpoints", forbidden_vcp)
    assert connections.native_connection_present(_frozen_binding()) is False
