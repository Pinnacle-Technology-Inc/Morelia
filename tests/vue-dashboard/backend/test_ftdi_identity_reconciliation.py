"""Backend reconciliation contracts; USB/registry are the substituted boundaries."""

from types import SimpleNamespace

import pytest
from app.discovery import ftdi_transport, native_scan
from app.discovery import windows_ftdi_identity as identity
from app.discovery.pod_scan import PodProbe
from app.services import connections
from app.services.device_list import build_pool_rows


def parent(serial="SERIAL", pid=0x6001, container=None):
    return {"serial": serial, "pid": pid, "container": container}


def child(serial="SERIALA", pid=0x6001, port="COM11", container=None):
    return {"serial": serial, "pid": pid, "port": port, "container": container}


@pytest.mark.parametrize("pid,channels", [(0x6001, "A"), (0x6010, "AB"),
                                        (0x6011, "ABCD"), (0x6014, "A")])
def test_observed_base_and_supported_channels_work_without_container(pid, channels):
    bindings = identity.build_bindings(
        [parent(pid=pid)],
        [child("SERIAL" + channel, pid, f"COM{index + 1}")
         for index, channel in enumerate(channels)],
    )
    assert {binding["channel"] for binding in bindings} == set(channels)
    assert {binding["base_serial"] for binding in bindings} == {"SERIAL"}
    assert {binding["identity_evidence"] for binding in bindings} == {"usb_serial_channel"}
    expected = {"SERIAL"} if len(channels) == 1 else {"SERIAL" + c for c in channels}
    assert {binding["physical_id"] for binding in bindings} == expected
    assert {binding["native_serial"] for binding in bindings} == expected


@pytest.mark.parametrize("base", ["000123", "SERIALA", "SERIALD"])
def test_significant_serial_characters_are_preserved(base):
    bindings = identity.build_bindings([parent(base)], [child(base + "A")])
    assert bindings[0]["native_serial"] == base


@pytest.mark.parametrize("parents,children", [
    ([parent(), parent()], [child()]),
    ([parent()], [child(), child()]),
    ([parent(), parent("SERIALA")], [child()]),
    ([parent(container="one")], [child(container="two")]),
    ([parent()], [child("SERIALB")]),
    ([parent("serial")], [child()]),
    ([parent("")], [child("A")]),
    ([parent()], [child("")]),
])
def test_unproven_or_conflicting_identities_are_not_reconciled(parents, children):
    assert identity.build_bindings(parents, children) == []


def test_container_fallback_does_not_require_conventional_suffix():
    binding, = identity.build_bindings(
        [parent(container="same")], [child("ALIAS", container="SAME")],
    )
    assert binding["identity_evidence"] == "windows_container_id"
    assert binding["native_serial"] == "SERIAL"
    assert binding["hardware_id"] == "ALIAS"


def test_container_fallback_cannot_merge_multiport_channels():
    assert identity.build_bindings(
        [parent(pid=0x6011, container="same")],
        [child("ALIAS", pid=0x6011, container="same")],
    ) == []


@pytest.mark.parametrize("saved_id", ["AB0MZ1AC", "AB0MZ1ACA"])
def test_production_discovery_and_database_join_preserve_saved_identity(app, monkeypatch, tmp_path,
                                                                     saved_id):
    """Replay the pre-change COM11 pair through real grouping, DB, and resolver."""
    from app.domain.enums import DeviceType
    from app.services import device_configs
    from serial.tools import list_ports

    reads = []

    def records():
        reads.append(True)
        return [parent("AB0MZ1AC")], [child("AB0MZ1ACA")]

    monkeypatch.setattr(identity, "_registry_records", records)
    port = SimpleNamespace(serial_number="AB0MZ1ACA", device="COM11", vid=0x0403,
                           pid=0x6001, description="POD")
    monkeypatch.setattr(list_ports, "comports", lambda: [port])
    monkeypatch.setattr(ftdi_transport, "list_d2xx_devices", lambda **_: [
        {"serial": "AB0MZ1AC", "type": 5, "id": 0x04036001},
    ])
    calls = []

    def probe(endpoint, profile):
        calls.append(endpoint["address"])
        return PodProbe(True, True, 48, endpoint["hardware_id"])

    with app.app_context():
        config = device_configs.create(device_type=DeviceType.POD8206HR, hardware_id=saved_id,
                                       port="COM99", parameters={"preamp_gain": 10},
                                       connection={"preference": "auto"})
        rows, warnings = native_scan.scan_endpoints(
            port_lister=list_ports.comports, directory=tmp_path, prober=probe,
            configured={saved_id: config.connection},
        )
        assert len(reads) == 1  # Includes default native provider; no per-endpoint rereads.
        assert warnings == () and calls == ["COM11"]
        assert len(rows) == 1 and rows[0].hardware_id == saved_id
        pool = build_pool_rows(rows)
        assert len(pool) == 1 and pool[0]["id"] == config.id
        resolved = connections.resolve_connection(saved_id, {"preference": "d2xx"}, "pod8206hr")
        assert resolved["hardware_id"] == config.hardware_id == saved_id
        assert resolved["address"] == resolved["physical_id"] == "AB0MZ1AC"
        assert connections.validate_current_connection(resolved) == resolved


def test_batch_annotation_reads_one_snapshot_for_many_endpoints(monkeypatch):
    calls = []

    def records():
        calls.append(True)
        return [parent()], [child()]

    monkeypatch.setattr(identity, "_registry_records", records)
    raw = [{"hardware_id": "SERIAL", "address": "SERIAL", "transport": "d2xx",
            "type": 5, "id": 0x04036001}] * 100
    results = identity.annotate_endpoints(raw)
    assert len(calls) == 1
    assert all(row["physical_id"] == "SERIAL" for row in results)
    assert "physical_id" not in raw[0]


def test_conflicting_base_and_alias_cannot_merge_by_raw_serial(monkeypatch, tmp_path):
    """SERA can mean a real base serial or channel A of SER: block both paths."""
    monkeypatch.setattr(identity, "_registry_records", lambda: (
        [parent("SER", container="one"), parent("SERA", container="two")],
        [child("SERA", container="one")],
    ))
    raw_native = [
        {"transport": "d2xx", "hardware_id": serial, "address": serial,
         "type": 5, "id": 0x04036001} for serial in ("SER", "SERA")
    ]
    rows, _ = native_scan.scan_endpoints(
        port_lister=lambda: [SimpleNamespace(serial_number="SERA", device="COM11", vid=0x0403,
                                            pid=0x6001, description="POD")],
        native_lister=lambda: raw_native,
        prober=lambda *_: pytest.fail("conflicting device reached probe"),
        directory=tmp_path,
    )
    assert rows and all(row.availability == "unopenable" for row in rows)
    assert all(ep["error_code"] == "identity_ambiguous" for row in rows for ep in row.endpoints)
    for endpoint in identity.annotate_endpoints(raw_native):
        with pytest.raises(connections.ConnectionResolutionError) as error:
            connections._unique_match([endpoint], endpoint["hardware_id"])
        assert error.value.code == "identity_ambiguous"


def test_registry_reader_keeps_serial_evidence_without_container(monkeypatch):
    """Exercise actual Windows reader traversal with missing registry values."""
    import sys

    usb = r"SYSTEM\CurrentControlSet\Enum\USB\VID_0403&PID_6001"
    bus = r"SYSTEM\CurrentControlSet\Enum\FTDIBUS"
    endpoint = "VID_0403+PID_6001+SERIALA"
    tree = {
        usb: (["SERIAL"], {}), usb + r"\SERIAL": ([], {}),
        bus: ([endpoint], {}), bus + "\\" + endpoint: (["0000"], {}),
        bus + "\\" + endpoint + r"\0000": ([], {}),
        bus + "\\" + endpoint + r"\0000\Device Parameters": ([], {"PortName": "COM11"}),
    }

    class Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def open_key(root, path):
        path = root.path + "\\" + path if isinstance(root, Key) else path
        if path not in tree:
            raise FileNotFoundError(path)
        return Key(path)

    def enum_key(key, index):
        try:
            return tree[key.path][0][index]
        except IndexError:
            error = OSError("no more entries")
            error.winerror = 259
            raise error from None

    def query_value(key, name):
        if name not in tree[key.path][1]:
            raise FileNotFoundError(name)
        return tree[key.path][1][name], 1

    monkeypatch.setattr(identity.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(), OpenKey=open_key, EnumKey=enum_key, QueryValueEx=query_value,
    ))
    bindings = identity.verified_bindings()
    assert len(bindings) == 1
    assert bindings[0]["identity_evidence"] == "usb_serial_channel"
    assert bindings[0]["native_serial"] == "SERIAL"
