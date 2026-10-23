from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
from app.database import db
from app.domain.enums import DeviceClaimState, DeviceType, PolicyMode, SinkType
from app.models.device_config import DeviceConfig
from app.repositories.sessions import SessionRepository
from app.runtime_child.morelia import MoreliaRuntime
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest, SinkConfig
from app.services.device_ports import PortResolutionError, refresh_port, resolve_serial_port


def enumerate_ports(monkeypatch, ports):
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [
        SimpleNamespace(serial_number=serial, device=port) for serial, port in ports
    ])


@pytest.mark.parametrize("port", ["/dev/ttyUSB5", "COM7"])
def test_serial_resolves_current_address(monkeypatch, port):
    enumerate_ports(monkeypatch, [("other", "COM3"), ("target", port)])
    assert resolve_serial_port("target") == port


@pytest.mark.parametrize("serial", ["17200A", "00172A", "17200", "AB0MZ1ADA"])
@pytest.mark.parametrize("opened", [True, False])
def test_discovery_identity_resolves_verbatim(monkeypatch, serial, opened):
    from app.discovery.pod_scan import PodProbe, detect_pod_devices

    port = SimpleNamespace(device="COM19", serial_number=serial, vid=0x0403)
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [port])
    devices = detect_pod_devices(
        port_lister=lambda: [port],
        prober=lambda _: PodProbe(
            opened=opened, pinged=opened, type_number=48, hardware_id=None,
        ),
    )
    assert devices[0].hardware_id == serial
    assert resolve_serial_port(devices[0].hardware_id) == "COM19"


def test_windows_channel_identities_remain_distinct(monkeypatch):
    from app.discovery.pod_scan import PodProbe, detect_pod_devices

    ports = [
        SimpleNamespace(device="COM19", serial_number="17200A", vid=0x0403),
        SimpleNamespace(device="COM20", serial_number="17200B", vid=0x0403),
    ]
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: ports)
    devices = detect_pod_devices(
        port_lister=lambda: ports,
        prober=lambda _: PodProbe(opened=True, pinged=True, type_number=48, hardware_id=None),
    )
    assert [(d.hardware_id, resolve_serial_port(d.hardware_id)) for d in devices] == [
        ("17200A", "COM19"), ("17200B", "COM20"),
    ]
    with pytest.raises(PortResolutionError, match="No serial port"):
        resolve_serial_port("17200")


@pytest.mark.parametrize("serial,ports,message", [
    (None, [], "hardware_id is missing"),
    ("", [], "hardware_id is missing"),
    ("target", [(None, "COM3")], "No serial port"),
    ("target", [("other", "COM3")], "No serial port"),
    ("target", [("TARGET", "COM3")], "No serial port"),
    ("target", [("target", "COM3"), ("target", "COM7")], "Ambiguous"),
])
def test_invalid_serial_fails_closed(monkeypatch, serial, ports, message):
    enumerate_ports(monkeypatch, ports)
    with pytest.raises(PortResolutionError, match=message):
        resolve_serial_port(serial)


@pytest.fixture
def configured_device(app):
    with app.app_context():
        session = SessionRepository().create({"name": "Running experiment"})
        row = DeviceConfig(
            device_type=DeviceType.POD8206HR, hardware_id="target", port="COM3",
            nickname="left", parameters={"sample_rate": 1000, "preamp_gain": 100},
            claim_state=DeviceClaimState.CLAIMED, claimed_session_id=session.id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


@pytest.mark.parametrize("port", ["COM7", "/dev/ttyUSB5"])
def test_database_refresh_only_changes_address(app, configured_device, monkeypatch, port):
    enumerate_ports(monkeypatch, [("other", "COM3"), ("target", port)])
    with app.app_context():
        row = db.session.get(DeviceConfig, configured_device)
        original = (row.id, row.nickname, dict(row.parameters), row.claim_state, row.claimed_session_id)
        assert refresh_port(DeviceType.POD8206HR, "target") == port
        db.session.refresh(row)
        assert row.port == port
        assert (row.id, row.nickname, row.parameters, row.claim_state, row.claimed_session_id) == original
        updated_at = row.updated_at
        refresh_port(DeviceType.POD8206HR, "target")
        db.session.refresh(row)
        assert row.updated_at == updated_at  # polling an unchanged address does not write


@pytest.mark.parametrize("ports", [
    [("other", "COM3")], [(None, "COM3")],
    [("target", "COM7"), ("target", "COM9")],
])
def test_failed_refresh_leaves_database_unchanged(app, configured_device, monkeypatch, ports):
    enumerate_ports(monkeypatch, ports)
    with app.app_context():
        with pytest.raises(PortResolutionError):
            refresh_port(DeviceType.POD8206HR, "target")
        assert db.session.get(DeviceConfig, configured_device).port == "COM3"


class LegacyPod:
    """Existing constructor contract: no hardware_id argument or attribute."""

    def __init__(self, port, preamp_gain, baudrate=9600, device_name=None,
                 use_d2xx=False, sample_rate=None):
        self.port = port
        self.preamp_gain = preamp_gain
        self.sample_rate = sample_rate
        self.close_port = Mock()


def runtime_for(monkeypatch, *, d2xx=False):
    flow = DeviceFlow(
        device_id="pod8206hr:target", name="pod8206hr", hardware_id="target", port="COM3",
        parameters={"sample_rate": 2000, "preamp_gain": 10, "use_d2xx": d2xx},
        sinks=(SinkConfig(sink_id="pod8206hr:target:plot", name="plot", type=SinkType.PLOT, parameters={}),),
    )
    manifest = Manifest(schema_version=MANIFEST_SCHEMA_VERSION, dataflow_id="test", policy=PolicyMode.AUTOMATE,
                        device_flows=(flow,))
    flowgraph = Mock(supports_source_recovery_window=True)
    watchdog = Mock()
    runtime = MoreliaRuntime(
        manifest=manifest, on_report=lambda _: None,
        importer=lambda: (watchdog, LegacyPod, object, flowgraph, object, object, object, object),
    )
    runtime._runtime_context = Mock()
    runtime._segment_resume = Mock(return_value={"plot": {"output_id": "old-output"}})
    monkeypatch.setattr("app.runtime_child.morelia.build_sinks", Mock(return_value=["sink"]))
    return runtime, flowgraph, watchdog


@pytest.mark.parametrize("new_port", ["COM7", "/dev/ttyUSB5"])
def test_rebuild_uses_refreshed_address_and_original_run_settings(app, configured_device, monkeypatch, new_port):
    runtime, _, _ = runtime_for(monkeypatch)
    original_manifest = runtime._manifest.to_dict()
    enumerate_ports(monkeypatch, [("other", "COM3"), ("target", new_port)])
    with app.app_context():
        source, sinks = runtime._reconstruct_stream(0)
        assert db.session.get(DeviceConfig, configured_device).port == new_port
    assert source.port == new_port
    assert source.sample_rate == 2000  # DB settings differ; retain experiment settings
    assert source.preamp_gain == 10
    assert not hasattr(source, "hardware_id")
    assert sinks == ["sink"]
    assert runtime._manifest.to_dict() == original_manifest
    assert runtime._device_id_by_port == {new_port.lower(): "pod8206hr:target"}
    runtime._segment_resume.assert_called_once_with(runtime._manifest.device_flows[0])


def test_watchdog_thread_uses_dashboard_database_and_worker_reopen_is_disabled(app, configured_device, monkeypatch):
    runtime, flowgraph, watchdog = runtime_for(monkeypatch)
    with app.app_context():
        runtime._build_stack()
    assert flowgraph.call_args.kwargs["source_recovery_window_sec"] is None
    assert watchdog.call_args.kwargs["port_resolver"] == runtime._resolve_stream_port
    enumerate_ports(monkeypatch, [("target", "COM7")])
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(runtime._resolve_stream_port, 0).result(timeout=10) == "COM7"
    with app.app_context():
        assert db.session.get(DeviceConfig, configured_device).port == "COM7"


def monitor_for(resolver=None):
    monitor = DataFlowMonitor(port_resolver=resolver)
    source = SimpleNamespace(port="COM3", close_port=Mock())
    monitor.flowgraph = SimpleNamespace(_network=[(source, [])])
    monitor.snapshot_config = [{"source": {"source_dict": {"port": "COM3"}}}]
    monitor._hw.reset_streaming_device = Mock(return_value={"ok": True})
    return monitor, source


def test_legacy_port_lookup_needs_no_serial_or_database(monkeypatch):
    enumerate_ports(monkeypatch, [(None, "COM3")])
    monitor, _ = monitor_for()
    assert monitor.get_stream_port(0) == "COM3"
    assert monitor.is_stream_port_present(0)
    monitor.reset_stream_device(0)
    monitor._hw.reset_streaming_device.assert_called_once()


def test_legacy_device_snapshot_roundtrip_has_no_new_constructor_keyword():
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    source = MockPod8206HR(preamp_gain=10, sample_rate=2000)
    snapshot = source.get_dict()
    assert "hardware_id" not in snapshot
    replacement = type(source)(**snapshot)
    assert replacement.sample_rate == source.sample_rate
    assert replacement.preamp_gain == source.preamp_gain


def test_monitor_probes_new_address_and_never_resets_reassigned_port(monkeypatch):
    monitor, source = monitor_for(lambda _: "COM7")
    serial = Mock()
    monkeypatch.setattr("serial.Serial", serial)
    assert monitor.is_stream_port_present(0)
    assert monitor.is_stream_port_openable(0, attempts=1)
    assert serial.call_args.kwargs["port"] == "COM7"
    assert monitor.reset_stream_device(0)["skipped"] == "port_changed"
    monitor._hw.reset_streaming_device.assert_not_called()
    source.close_port.assert_called_once()
    assert monitor.get_stream_port(0) == "COM3"  # status still describes the old source


def test_monitor_missing_serial_never_probes_or_resets_old_port(monkeypatch):
    resolver = Mock(side_effect=PortResolutionError("No serial port for target"))
    monitor, _ = monitor_for(resolver)
    serial = Mock()
    monkeypatch.setattr("serial.Serial", serial)
    with pytest.raises(PortResolutionError):
        monitor.is_stream_port_present(0)
    assert not monitor.is_stream_port_openable(0, attempts=1)
    with pytest.raises(PortResolutionError):
        monitor.reset_stream_device(0)
    serial.assert_not_called()
    monitor._hw.reset_streaming_device.assert_not_called()


def test_d2xx_keeps_driver_lookup_and_skips_database(monkeypatch):
    runtime, _, _ = runtime_for(monkeypatch, d2xx=True)
    refresh = Mock(side_effect=AssertionError("D2XX must not resolve OS ports"))
    monkeypatch.setattr("app.services.device_ports.refresh_port", refresh)
    assert runtime._resolve_stream_port(0) == "COM3"
    monitor, source = monitor_for(refresh)
    source._use_d2xx = True
    monitor.snapshot_config[0]["source"]["source_dict"]["use_d2xx"] = True
    monkeypatch.setattr("Morelia.Devices.SerialPorts.d2xx_helpers.list_d2xx_devices",
                        lambda: [{"serial": "COM3", "index": 0}])
    assert monitor.is_stream_port_present(0)
    monitor.reset_stream_device(0)
    refresh.assert_not_called()


def test_dashboard_host_recreation_resolves_historical_manifest(app, configured_device, monkeypatch):
    from dataclasses import replace
    runtime, flowgraph, _ = runtime_for(monkeypatch)
    enumerate_ports(monkeypatch, [("other", "COM3"), ("target", "COM7")])
    with app.app_context():
        row = db.session.get(DeviceConfig, configured_device)
        runtime._manifest = replace(runtime._manifest, session_id=row.claimed_session_id)
        original = runtime._manifest.to_dict()
        runtime._build_stack()
        assert row.port == "COM7"
    network = flowgraph.call_args.args[0]
    assert network[0][0].port == "COM7"
    assert runtime._manifest.to_dict() == original


def test_two_devices_can_swap_ports_without_losing_status_tracking(app, configured_device, monkeypatch):
    from dataclasses import replace
    runtime, flowgraph, _ = runtime_for(monkeypatch)
    first = runtime._manifest.device_flows[0]
    second = replace(first, device_id="pod8206hr:other", hardware_id="other", port="COM7")
    enumerate_ports(monkeypatch, [("target", "COM7"), ("other", "COM3")])
    with app.app_context():
        row = db.session.get(DeviceConfig, configured_device)
        db.session.add(DeviceConfig(device_type=DeviceType.POD8206HR, hardware_id="other", port="COM7",
                                    parameters={"sample_rate": 2000, "preamp_gain": 10}))
        db.session.commit()
        runtime._manifest = replace(runtime._manifest, session_id=row.claimed_session_id, device_flows=(first, second))
        runtime._device_id_by_port = {"com3": first.device_id, "com7": second.device_id}
        runtime._build_stack()
    assert [source.port for source, _ in flowgraph.call_args.args[0]] == ["COM7", "COM3"]
    assert runtime._device_id_by_port == {"com7": first.device_id, "com3": second.device_id}
