"""Discovery policies and real OS lease exclusion, without hardware access."""

from types import SimpleNamespace

import pytest
from app.discovery.native_scan import scan_endpoints
from app.discovery.pod_scan import PodProbe
from app.domain.enums import DeviceType
from app.watchdog_process.hardware_lease import HardwareLeaseSet


@pytest.fixture(autouse=True)
def no_host_registry(monkeypatch):
    from app.discovery import native_scan

    monkeypatch.setattr(native_scan, "annotate_endpoints", lambda endpoints: endpoints)


def port(serial="12345678", address="COM12"):
    return SimpleNamespace(
        serial_number=serial, device=address, vid=0x0403, description="POD"
    )


def native(serial="12345678", **extra):
    return {
        "hardware_id": serial,
        "address": serial,
        "transport": "d2xx",
        "backend": "ftd2xx",
        **extra,
    }


def success(endpoint, connection):
    return PodProbe(True, True, 48, endpoint["hardware_id"])


def test_dual_interfaces_form_one_row_and_one_probe(tmp_path):
    calls = []

    def probe(endpoint, profile):
        calls.append(endpoint["transport"])
        return success(endpoint, profile)

    rows, warnings = scan_endpoints(
        port_lister=lambda: [port()],
        native_lister=lambda: [native()],
        prober=probe,
        directory=tmp_path,
    )
    assert not warnings
    assert len(rows) == 1
    assert rows[0].type is DeviceType.POD8206HR
    assert rows[0].transport == "vcp"
    assert len(rows[0].endpoints) == 2
    assert calls == ["vcp"]


def test_saved_native_profile_selects_one_native_probe(tmp_path):
    calls = []

    def probe(endpoint, profile):
        calls.append((endpoint["transport"], profile["baudrate"]))
        return success(endpoint, profile)

    rows, _ = scan_endpoints(
        port_lister=lambda: [port()],
        native_lister=lambda: [native()],
        prober=probe,
        directory=tmp_path,
        configured={"12345678": {"preference": "d2xx", "baudrate": 115200}},
    )
    assert calls == [("d2xx", 115200)]
    assert rows[0].transport == "d2xx"


def test_native_failure_keeps_vcp_and_returns_warning(tmp_path):
    def broken():
        raise ImportError("native library missing")

    rows, warnings = scan_endpoints(
        port_lister=lambda: [port()],
        native_lister=broken,
        prober=success,
        directory=tmp_path,
    )
    assert rows[0].availability == "available"
    assert warnings[0]["code"] == "backend_unavailable"


def test_vcp_enumeration_failure_still_probes_observed_native_endpoint(tmp_path):
    def broken():
        raise RuntimeError("enumeration failed")

    rows, warnings = scan_endpoints(
        port_lister=broken,
        native_lister=lambda: [native()],
        prober=success,
        directory=tmp_path,
    )
    assert rows[0].availability == "available"
    assert rows[0].transport == "d2xx"
    assert warnings[0]["transport"] == "vcp"


@pytest.mark.parametrize("reason", ["claim", "lease", "driver"])
def test_owned_device_is_not_probed_through_either_interface(tmp_path, reason):
    lease = HardwareLeaseSet.for_devices([("12345678", "COM12")], directory=tmp_path)
    if reason == "lease":
        lease.acquire()
    try:
        rows, _ = scan_endpoints(
            port_lister=lambda: [port()],
            native_lister=lambda: [native(flags=1 if reason == "driver" else 0)],
            prober=lambda *_: pytest.fail("owned physical device was opened"),
            directory=tmp_path,
            claimed=frozenset({"12345678"}) if reason == "claim" else frozenset(),
        )
        assert len(rows) == 1
        assert rows[0].availability == "unopenable"
        assert rows[0].endpoints[0]["error_code"] == (
            "claimed" if reason == "claim" else "busy"
        )
    finally:
        lease.release()


def test_lease_released_when_probe_raises(tmp_path):
    def broken(*_):
        raise RuntimeError("bad probe")

    rows, _ = scan_endpoints(
        port_lister=lambda: [],
        native_lister=lambda: [native()],
        prober=broken,
        directory=tmp_path,
    )
    assert rows[0].availability == "unavailable"
    with HardwareLeaseSet.for_devices(
        [("12345678", "COM99")], directory=tmp_path
    ) as lease:
        assert lease.acquired


def test_duplicate_serial_does_not_open_any_candidate(tmp_path):
    rows, _ = scan_endpoints(
        port_lister=lambda: [port(), port(address="COM13")],
        native_lister=lambda: [native()],
        prober=lambda *_: pytest.fail("ambiguous device opened"),
        directory=tmp_path,
    )
    assert len(rows) == 1
    assert all(ep["error_code"] == "identity_ambiguous" for ep in rows[0].endpoints)


def test_missing_serial_is_visible_warning_and_never_opened(tmp_path):
    rows, warnings = scan_endpoints(
        port_lister=lambda: [port(serial=None)],
        native_lister=lambda: [native("")],
        prober=lambda *_: pytest.fail("identity missing"),
        directory=tmp_path,
    )
    assert len(rows) == 2
    assert all(
        row.hardware_id is None and row.availability == "unopenable" for row in rows
    )
    assert len(warnings) == 2
    assert all(warning["code"] == "identity_missing" for warning in warnings)


def test_bytes_serial_preserves_numeric_identity(tmp_path):
    rows, _ = scan_endpoints(
        port_lister=lambda: [port()],
        native_lister=lambda: [native(b"12345678")],
        prober=success,
        directory=tmp_path,
    )
    assert len(rows) == 1
    assert rows[0].endpoints[1]["address"] == "12345678"


@pytest.mark.parametrize("flags,expected", [(0, "identity_missing"), (1, "busy_identity_unavailable"),
                                           (3, "busy_identity_unavailable")])
def test_blank_native_serial_distinguishes_opened_handle_without_guessing(tmp_path, flags, expected):
    rows, warnings = scan_endpoints(
        port_lister=list,
        native_lister=lambda: [native("", flags=flags, index=7, id=0, location=0)],
        prober=lambda *_: pytest.fail("unidentified native device opened"),
        configured={"KNOWN001": {"preference": "d2xx"}},
        directory=tmp_path,
    )
    assert len(rows) == 1 and rows[0].hardware_id is None
    assert rows[0].availability == "unopenable"
    assert rows[0].endpoints[0]["error_code"] == warnings[0]["code"] == expected
    if flags:
        assert "already open" in warnings[0]["message"]
        assert "rescan" in warnings[0]["message"]


def test_identity_becomes_available_on_next_scan_after_handle_release(tmp_path):
    inventory = [native("", flags=1)]

    def scan():
        return scan_endpoints(
            port_lister=list, native_lister=lambda: inventory,
            prober=success, directory=tmp_path,
        )
    assert scan()[0][0].hardware_id is None
    inventory[:] = [native("KNOWN001", flags=0)]
    rows, warnings = scan()
    assert warnings == ()
    assert rows[0].hardware_id == "KNOWN001" and rows[0].availability == "available"


def test_native_bootstrap_second_rate_closes_first_handle(monkeypatch, tmp_path):
    """Drive the real probe lifecycle using an independent fake protocol endpoint."""

    from app.discovery import native_scan

    events = []

    class Pod:
        def __init__(self, address, **kwargs):
            self.baudrate = kwargs["baudrate"]
            self._port = None
            assert kwargs["d2xx_serial_only"] is True
            events.append(("construct", self.baudrate))

        def open_port(self):
            self._port = object()
            events.append(("open", self.baudrate))

        def write_read(self, command, timeout_sec):
            assert command == "TYPE"
            if self.baudrate == 9600:
                raise TimeoutError("no TYPE response")
            return SimpleNamespace(payload=[48])

        def cleanup(self):
            self._port = None
            events.append(("close", self.baudrate))

    monkeypatch.setattr(
        native_scan, "_import_probe_class", lambda: Pod
    )
    rows, _ = scan_endpoints(
        port_lister=lambda: [], native_lister=lambda: [native()], directory=tmp_path
    )
    assert rows[0].availability == "available"
    assert rows[0].endpoints[0]["baudrate"] == 115200
    assert events == [
        ("construct", 9600),
        ("open", 9600),
        ("close", 9600),
        ("construct", 115200),
        ("open", 115200),
        ("close", 115200),
    ]


@pytest.mark.parametrize(
    "code", ["busy", "permission_denied", "open_failed", "probe_failed"]
)
def test_native_bootstrap_never_retries_other_failures(tmp_path, code):
    attempts = []

    def probe(endpoint, connection):
        attempts.append(connection["baudrate"])
        return PodProbe(False, False, None, endpoint["hardware_id"], code)

    rows, _ = scan_endpoints(
        port_lister=lambda: [],
        native_lister=lambda: [native()],
        prober=probe,
        directory=tmp_path,
    )
    assert attempts == [9600]
    assert rows[0].availability == ("unopenable" if code in ("busy", "permission_denied") else "unavailable")


def test_saved_native_profile_timeout_does_not_sweep_rates(tmp_path):
    attempts = []

    def probe(endpoint, connection):
        attempts.append(connection["baudrate"])
        return PodProbe(True, False, None, endpoint["hardware_id"], "probe_timeout")

    scan_endpoints(
        port_lister=lambda: [],
        native_lister=lambda: [native()],
        prober=probe,
        configured={"12345678": {"preference": "d2xx", "baudrate": 57600}},
        directory=tmp_path,
    )
    assert attempts == [57600]


def test_swallowed_protocol_error_does_not_become_bootstrap_timeout(
    monkeypatch, tmp_path
):
    from app.discovery import native_scan

    rates = []

    class Pod:
        def __init__(self, address, **kwargs):
            rates.append(kwargs["baudrate"])
            self._port = None

        def open_port(self):
            self._port = object()

        def read_pod_packet(self):
            raise ValueError("bad checksum")

        def write_read(self, command, timeout_sec):
            try:
                self.read_pod_packet()
            except ValueError:
                pass  # Morelia's command retry loop discards this error.
            raise TimeoutError("no matching TYPE response")

        def cleanup(self):
            self._port = None

    monkeypatch.setattr(
        native_scan, "_import_probe_class", lambda: Pod
    )
    rows, _ = scan_endpoints(
        port_lister=lambda: [], native_lister=lambda: [native()], directory=tmp_path
    )
    assert rates == [9600]
    assert rows[0].endpoints[0]["error_code"] == "probe_failed"


def test_unconfigured_pool_preserves_discovered_native_baud():
    from app.discovery.pod_scan import DiscoveredDevice
    from app.services.device_list import _unconfigured_row

    row = _unconfigured_row(
        DiscoveredDevice(
            DeviceType.POD8206HR,
            "12345678",
            "12345678",
            "POD",
            "available",
            ({**native(), "availability": "available", "baudrate": 115200},),
            "d2xx",
        )
    )
    assert row.connection["preference"] == "auto"
    assert row.connection["baudrate"] == 115200
    assert row.selected_transport == "d2xx"


def test_known_unsupported_native_model_is_not_startable():
    from app.discovery.pod_scan import DiscoveredDevice
    from app.services.device_list import _unconfigured_row

    row = _unconfigured_row(
        DiscoveredDevice(
            DeviceType.POD8274D,
            "12345678",
            "12345678",
            "POD",
            "available",
            ({**native(), "availability": "available"},),
            "d2xx",
        )
    )
    assert row.availability == "unopenable"
    assert row.connection_error == "unsupported_model"


def test_pool_honors_explicit_native_preference_when_only_vcp_is_available():
    from app.discovery.pod_scan import DiscoveredDevice
    from app.domain.enums import DeviceClaimState
    from app.services.device_list import _configured_row

    config = SimpleNamespace(
        id=7,
        device_type=DeviceType.POD8206HR,
        hardware_id="12345678",
        port="COM12",
        color=None,
        claimed_session_id=None,
        nickname=None,
        source_template=None,
        source_template_hash=None,
        parameters={"preamp_gain": 10},
        connection={"preference": "d2xx"},
        claim_state=DeviceClaimState.FREE,
    )
    seen = DiscoveredDevice(
        DeviceType.POD8206HR,
        "COM12",
        "12345678",
        "POD",
        "available",
        ({"transport": "vcp", "address": "COM12", "availability": "available"},),
        "vcp",
    )
    row = _configured_row(config, seen)
    assert row.availability == "unavailable"
    assert row.connection_error == "not_found"


@pytest.mark.parametrize("configured_identity", [None, "RAW12345", "RAW12345A"])
def test_verified_aliases_deduplicate_and_preserve_existing_config(
    monkeypatch, tmp_path, configured_identity
):
    from app.discovery import native_scan

    def annotate(endpoint):
        return {
            **endpoint,
            "hardware_id": "RAW12345A",
            "physical_id": "RAW12345",
            "aliases": ("RAW12345", "RAW12345A"),
        }

    monkeypatch.setattr(native_scan, "annotate_endpoints", lambda endpoints: [annotate(ep) for ep in endpoints])
    configured = (
        {}
        if configured_identity is None
        else {configured_identity: {"preference": "d2xx"}}
    )
    rows, _ = scan_endpoints(
        port_lister=lambda: [port("RAW12345A")],
        native_lister=lambda: [native("RAW12345")],
        prober=success,
        configured=configured,
        directory=tmp_path,
    )
    assert len(rows) == 1
    assert rows[0].hardware_id == (configured_identity or "RAW12345A")
    assert rows[0].endpoints[1]["address"] == "RAW12345"


def test_alias_config_conflict_never_opens_hardware(monkeypatch, tmp_path):
    from app.discovery import native_scan

    monkeypatch.setattr(
        native_scan,
        "annotate_endpoints",
        lambda endpoints: [{
            **ep,
            "hardware_id": "RAW12345A",
            "physical_id": "RAW12345",
            "aliases": ("RAW12345", "RAW12345A"),
        } for ep in endpoints],
    )
    rows, _ = scan_endpoints(
        port_lister=lambda: [port("RAW12345A")],
        native_lister=lambda: [native("RAW12345")],
        prober=lambda *_: pytest.fail("conflicting configs opened"),
        configured={"RAW12345": {}, "RAW12345A": {}},
        directory=tmp_path,
    )
    assert rows[0].availability == "unopenable"
    assert all(ep["error_code"] == "identity_ambiguous" for ep in rows[0].endpoints)


def test_manifest_lease_bridges_physical_and_legacy_identity(tmp_path):
    from app.watchdog_process.hardware_lease import HardwareLeaseBusy

    manifest = SimpleNamespace(
        device_flows=[
            SimpleNamespace(
                hardware_id="RAW12345A",
                port="RAW12345",
                connection={"physical_id": "RAW12345"},
            )
        ]
    )
    runtime = HardwareLeaseSet(manifest, directory=tmp_path)
    assert runtime.keys == ("RAW12345A@RAW12345",)
    for old_identity in ("RAW12345", "RAW12345A"):
        with HardwareLeaseSet.for_devices(
            [(old_identity, "COM12")], directory=tmp_path
        ):
            with pytest.raises(HardwareLeaseBusy):
                runtime.acquire()
        assert not runtime.acquired
    with runtime:
        for alias in ("RAW12345", "RAW12345A"):
            with pytest.raises(HardwareLeaseBusy):
                HardwareLeaseSet.for_devices(
                    [(alias, "COM55")], directory=tmp_path
                ).acquire()
