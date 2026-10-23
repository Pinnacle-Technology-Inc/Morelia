"""User policy oracle: one physical lease, VCP then native after confirmed close."""

from threading import get_ident
from types import SimpleNamespace

import pytest
from app.discovery import native_scan
from app.discovery.pod_scan import PodProbe
from app.domain.enums import DeviceClaimState, DeviceType
from app.services import device_list
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet

SERIAL = "FALLBACK1"


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setattr(native_scan, "annotate_endpoints", lambda endpoints: endpoints)


def scan(tmp_path, **kwargs):
    defaults = dict(
        port_lister=lambda: [SimpleNamespace(serial_number=SERIAL, device="COM9", vid=0x0403)],
        native_lister=lambda: [{"hardware_id": SERIAL, "address": SERIAL, "transport": "d2xx"}],
        configured={SERIAL: {"preference": "auto"}}, directory=tmp_path,
    )
    return native_scan.scan_endpoints(**(defaults | kwargs))


def config():
    return SimpleNamespace(id=7, device_type=DeviceType.POD8206HR, hardware_id=SERIAL,
                           port="COM9", color=None, claim_state=DeviceClaimState.FREE,
                           claimed_session_id=None, nickname=None, source_template=None,
                           source_template_hash=None, parameters={"preamp_gain": 10},
                           connection={"preference": "auto"})


def test_real_probe_closes_vcp_before_native_and_keeps_physical_lease(monkeypatch, tmp_path):
    events, workers = [], []

    class Pod:
        def __init__(self, address, **kwargs):
            self.transport = "d2xx" if kwargs["use_d2xx"] else "vcp"
            self._port = None

        def open_port(self):
            if self.transport == "d2xx":
                assert events[-1] == ("close", "vcp")
            self._port = object()
            events.append(("open", self.transport))
            workers.append(get_ident())
            with pytest.raises(HardwareLeaseBusy):
                with HardwareLeaseSet.for_devices([(SERIAL, "OTHER")], directory=tmp_path):
                    pytest.fail("lease released between attempts")

        def write_read(self, *_args, **_kwargs):
            if self.transport == "vcp":
                raise TimeoutError("injected VCP timeout")
            return SimpleNamespace(payload=[48])

        def cleanup(self):
            events.append(("close", self.transport))
            self._port = None

    monkeypatch.setattr(native_scan, "_import_probe_class", lambda: Pod)
    rows, warnings = scan(tmp_path)
    assert not warnings
    assert events == [("open", "vcp"), ("close", "vcp"), ("open", "d2xx"), ("close", "d2xx")]
    assert len(set(workers)) == 1
    assert len(rows) == 1 and rows[0].availability == "available"
    assert rows[0].transport == "d2xx" and rows[0].port == SERIAL
    monkeypatch.setattr(device_list.device_configs, "list", lambda: [config()])
    monkeypatch.setattr(device_list.device_registrations, "list", lambda: [])
    projected, = device_list.build_pool_rows(rows)
    assert projected["selected_transport"] == "d2xx"
    assert projected["availability"] == "available"
    assert projected["connection_error"] is None


@pytest.mark.parametrize("preference,expected", [("auto", ["vcp", "d2xx"]),
                                                ("vcp", ["vcp"]), ("d2xx", ["d2xx"])])
def test_exhausted_candidates_are_unavailable(tmp_path, preference, expected):
    attempts = []

    def fail(endpoint, _profile):
        attempts.append(endpoint["transport"])
        return PodProbe(True, False, None, SERIAL, "probe_failed")

    rows, _ = scan(tmp_path, prober=fail, configured={SERIAL: {"preference": preference}})
    assert attempts == expected
    assert rows[0].availability == "unavailable"
    assert rows[0].probe_state == "complete"


def test_com_inventory_failure_does_not_suppress_observed_native_probe(tmp_path):
    def broken():
        raise OSError("COM enumeration failed")

    rows, warnings = scan(tmp_path, port_lister=broken,
                          prober=lambda ep, _: PodProbe(True, True, 48, SERIAL))
    assert rows[0].availability == "available"
    assert rows[0].transport == "d2xx"
    assert warnings[0]["transport"] == "vcp"


def test_vcp_close_failure_blocks_fallback_and_retains_lease(monkeypatch, tmp_path):
    state = {"close_fails": True}
    opens = []

    class Pod:
        def __init__(self, address, **kwargs):
            self._port = None
            self.transport = "d2xx" if kwargs["use_d2xx"] else "vcp"

        def open_port(self):
            opens.append(self.transport)
            self._port = object()

        def write_read(self, *_args, **_kwargs):
            raise TimeoutError("no response")

        def cleanup(self):
            if state["close_fails"]:
                raise OSError("close failed")
            self._port = None

    monkeypatch.setattr(native_scan, "_import_probe_class", lambda: Pod)
    try:
        rows, warnings = scan(tmp_path)
        assert opens == ["vcp"]
        assert rows[0].availability == "unopenable"
        assert any(w["code"] == "cleanup_pending" for w in warnings)
        with pytest.raises(HardwareLeaseBusy):
            with HardwareLeaseSet.for_devices([(SERIAL, "OTHER")], directory=tmp_path):
                pytest.fail("unclean close released lease")
    finally:
        state["close_fails"] = False
        native_scan._retry_probe_cleanup()
    with HardwareLeaseSet.for_devices([(SERIAL, "OTHER")], directory=tmp_path):
        pass


def test_claimed_device_never_opens_either_transport(tmp_path):
    rows, _ = scan(tmp_path, claimed=frozenset({SERIAL}),
                   prober=lambda *_: pytest.fail("claimed device opened"))
    assert rows[0].availability == "unopenable"
    assert rows[0].endpoints[0]["error_code"] == "claimed"


def test_final_inventory_failure_is_unavailable_with_reason(monkeypatch):
    monkeypatch.setattr(device_list.device_configs, "list", lambda: [config()])
    monkeypatch.setattr(device_list.device_registrations, "list", lambda: [])
    row, = device_list.build_pool_rows([], warnings=({"transport": "vcp", "code": "enumeration_failed"},))
    assert row["availability"] == "unavailable"
    assert row["connection_error"] == "enumeration_failed"


def test_pyserial_wrapped_access_denied_does_not_fall_back(monkeypatch, tmp_path):
    from serial import SerialException

    opens = []

    class Pod:
        def __init__(self, address, **kwargs):
            self._port = None

        def open_port(self):
            opens.append("vcp")
            raise SerialException(f"could not open port 'COM9': {PermissionError(13, 'Access is denied')!r}")

        def cleanup(self):
            pass

    monkeypatch.setattr(native_scan, "_import_probe_class", lambda: Pod)
    rows, _ = scan(tmp_path)
    assert opens == ["vcp"]
    assert rows[0].availability == "unopenable"
    assert rows[0].endpoints[0]["error_code"] == "permission_denied"


def test_aborted_scan_converts_unfinished_rows_to_terminal_unavailable(monkeypatch):
    from app.discovery.pod_scan import DiscoveredDevice

    monkeypatch.setattr(device_list.device_configs, "list", lambda: [config()])
    monkeypatch.setattr(device_list.device_registrations, "list", lambda: [])
    pending = DiscoveredDevice(DeviceType.UNKNOWN, "COM9", SERIAL, "POD", "unverified",
                               scan_key=f"device:{SERIAL}", probe_state="probing")
    row, = device_list.build_pool_rows([pending], scan_state="failed")
    assert row["availability"] == "unavailable"
    assert row["probe_state"] == "complete"
    assert row["connection_error"] == "scan_failed"


@pytest.mark.parametrize("state", ["enumerating", "failed"])
def test_known_claim_remains_blocked_even_without_inventory(monkeypatch, state):
    claimed = config()
    claimed.claim_state = DeviceClaimState.CLAIMED
    monkeypatch.setattr(device_list.device_configs, "list", lambda: [claimed])
    monkeypatch.setattr(device_list.device_registrations, "list", lambda: [])
    row, = device_list.build_pool_rows([], scan_state=state)
    assert row["availability"] == "unopenable"
    assert row["probe_state"] == "complete"
    assert row["connection_error"] == "claimed"


def test_managed_pod_and_both_driver_adapters_execute_fallback(monkeypatch, tmp_path):
    """Only serial/USB handles are simulated; real framing, cleanup and gates run."""
    import serial
    from app.discovery import ftdi_transport

    from tests.mocks.packet.MockControlPacket import MockControlPacket

    events = []

    class SerialHandle:
        def __init__(self, **settings):
            self.timeout = settings["timeout"]
            self.is_open = True
            events.append("vcp_open")

        def write(self, message):
            assert int(message[1:5], 16) == 8
            return len(message)

        def read(self, size):
            return b""  # VCP never answers TYPE.

        def close(self):
            self.is_open = False
            events.append("vcp_close")

    class NativeHandle:
        def __init__(self):
            assert events[-1] == "vcp_close"
            events.append("native_open")
            self.pending = b""
            with pytest.raises(HardwareLeaseBusy):
                with HardwareLeaseSet.for_devices([(SERIAL, "OTHER")], directory=tmp_path):
                    pytest.fail("lease was released before native fallback")

        def getDeviceInfo(self):
            return {"serial": SERIAL.encode()}

        def setBaudRate(self, *_):
            pass

        def setDataCharacteristics(self, *_):
            pass

        def setFlowControl(self, *_):
            pass

        def setTimeouts(self, *_):
            pass

        def purge(self, *_):
            self.pending = b""

        def write(self, message):
            assert int(message[1:5], 16) == 8
            self.pending += MockControlPacket(8, b"30").to_bytes()
            return len(message)

        def read(self, size):
            result, self.pending = self.pending[:size], self.pending[size:]
            return result

        def close(self):
            events.append("native_close")

    monkeypatch.setattr(serial, "Serial", SerialHandle)
    monkeypatch.setattr(ftdi_transport, "_open_native_serial", lambda identity: NativeHandle())
    rows, warnings = scan(tmp_path, configured={SERIAL: {"preference": "auto", "read_timeout_ms": 20}})
    assert not warnings
    assert events == ["vcp_open", "vcp_close", "native_open", "native_close"]
    assert rows[0].type is DeviceType.POD8206HR
    assert rows[0].availability == "available" and rows[0].transport == "d2xx"
