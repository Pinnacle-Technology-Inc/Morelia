"""Independent oracle for the user's progressive physical-device scan contract.

Authority: native snapshot then COM snapshot once; reconcile physical aliases
before dispatch; at most four concurrent physical probes; publish completed
devices without waiting for a slow earlier device; allocate scan IDs before
enumeration; join active scans; retain leases through retry and cleanup.

Real boundaries: executor, identity reconciliation, Windows leases, scanner,
service, Flask API, SQLite persistence. Only inventory and POD protocol are
replaced. This does not certify FTDI DLL concurrency or USB behavior.

Negative control: set PROGRESSIVE_ORACLE_SERIAL_CONTROL=1 and run the
four_overlap test. Its four-worker overlap assertion must fail.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from app.database import db
from app.discovery import native_scan, windows_ftdi_identity
from app.discovery.ftdi_transport import NativeHandleCleanupError
from app.discovery.pod_scan import PodProbe
from app.models.device_seen import DeviceSeen
from app.services.discovery import DeviceDiscoveryService, FtdiPodProvider
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet


def inventory(monkeypatch, count, *, paired=True, events=None):
    events = events if events is not None else []
    parents = [{"serial": f"P{i:03}", "pid": 0x6001} for i in range(count)]
    children = [{"serial": f"P{i:03}A", "pid": 0x6001, "port": f"COM{i + 20}"}
                for i in range(count)]

    def registry():
        events.append("registry")
        return deepcopy(parents), deepcopy(children)

    monkeypatch.setattr(windows_ftdi_identity, "_registry_records", registry)

    def native():
        events.append("native")
        return [{"hardware_id": row["serial"], "address": row["serial"],
                 "transport": "d2xx", "backend": "ftd2xx", "flags": 0,
                 "id": 0x04036001, "type": 5, "label": row["serial"]}
                for row in parents]

    def com():
        events.append("com")
        return [SimpleNamespace(serial_number=row["serial"], device=row["port"],
                                vid=0x0403, pid=0x6001, description="POD")
                for row in children] if paired else []

    return native, com


def assert_lease_held(directory, identity):
    with pytest.raises(HardwareLeaseBusy):
        with HardwareLeaseSet.for_devices([(identity, "different-address")], directory=directory):
            pass


def assert_lease_free(directory, identity):
    with HardwareLeaseSet.for_devices([(identity, "different-address")], directory=directory):
        pass


def test_four_overlap_after_single_inventory_and_physical_grouping(monkeypatch, tmp_path):
    events, entered, progress = [], [], []
    native, com = inventory(monkeypatch, 9, events=events)
    release, four_entered, fifth_entered = Event(), Event(), Event()
    lock = Lock()
    active = 0
    peak = 0

    def probe(endpoint, settings):
        nonlocal active, peak
        with lock:
            events.append("probe")
            entered.append((endpoint["hardware_id"], endpoint["transport"]))
            active += 1
            peak = max(peak, active)
            if len(entered) == 4:
                four_entered.set()
            if len(entered) == 5:
                fifth_entered.set()
        try:
            assert release.wait(6), "test failed to release blocked probes"
            return PodProbe(True, True, 48, endpoint["hardware_id"])
        finally:
            with lock:
                active -= 1

    worker_count = 1 if os.getenv("PROGRESSIVE_ORACLE_SERIAL_CONTROL") else 99
    with ThreadPoolExecutor(max_workers=1) as runner:
        result = runner.submit(native_scan.scan_endpoints, native_lister=native,
                               port_lister=com, prober=probe, directory=tmp_path,
                               configured={"P000A": {"preference": "d2xx"}},
                               max_workers=worker_count, on_progress=progress.append)
        try:
            assert four_entered.wait(2), "four independent physical probes did not overlap"
            assert not fifth_entered.wait(0.1), "more than four probes entered before release"
            assert events[:3] == ["native", "com", "registry"]
            assert len(progress[0].devices) == 9
            assert all(row.probe_state == "queued" for row in progress[0].devices)
            assert all(len(row.endpoints) == 2 for row in progress[0].devices)
        finally:
            release.set()
        devices, warnings = result.result(timeout=5)

    assert peak == 4
    assert len(entered) == len(set(identity for identity, _ in entered)) == 9
    assert dict(entered)["P000A"] == "d2xx"
    assert all(transport == "vcp" for identity, transport in entered if identity != "P000A")
    assert events.count("native") == events.count("com") == events.count("registry") == 1
    assert not warnings
    assert all(row.availability == "available" for row in devices)
    assert [row.scan_key for row in progress[0].devices] == [row.scan_key for row in devices]
    assert progress[-1].completed == progress[-1].total == 9
    assert all(row.probe_state == "queued" for row in progress[0].devices), "old snapshot mutated"
    for i in range(9):
        assert_lease_free(tmp_path, f"P{i:03}")
        assert_lease_free(tmp_path, f"P{i:03}A")


def test_fast_result_visible_while_first_protocol_cleanup_is_blocked(monkeypatch, tmp_path):
    native, com = inventory(monkeypatch, 2, paired=False)
    cleanup_started, cleanup_release, fast_visible = Event(), Event(), Event()
    progress = []

    class ProtocolPod:
        def __init__(self, address, **_):
            self.address, self._port = address, None

        def open_port(self):
            self._port = object()

        def write_read(self, command, **_):
            assert command == "TYPE"
            return SimpleNamespace(payload=(48,))

        def cleanup(self):
            if self.address == "P000":
                cleanup_started.set()
                assert cleanup_release.wait(6)
            else:
                assert cleanup_started.wait(2)
            self._port = None

    monkeypatch.setattr(native_scan, "_import_probe_class", lambda: ProtocolPod)

    def publish(update):
        progress.append(update)
        if any(row.hardware_id == "P001A" and row.availability == "available"
               for row in update.devices):
            fast_visible.set()

    with ThreadPoolExecutor(max_workers=1) as runner:
        result = runner.submit(native_scan.scan_endpoints, native_lister=native,
                               port_lister=com, directory=tmp_path, on_progress=publish)
        try:
            assert cleanup_started.wait(2)
            assert fast_visible.wait(2), "fast completion was held behind slow first device"
            slow = next(row for row in progress[-1].devices if row.hardware_id == "P000A")
            assert slow.availability == "unverified"
            assert slow.probe_state == "probing"
            assert progress[-1].completed == 1
            assert_lease_held(tmp_path, "P000")
            assert_lease_held(tmp_path, "P000A")
        finally:
            cleanup_release.set()
        devices, warnings = result.result(timeout=5)
    assert not warnings
    assert all(row.availability == "available" for row in devices)
    assert [row.scan_key for row in devices] == [row.scan_key for row in progress[0].devices]
    assert_lease_free(tmp_path, "P000")
    assert_lease_free(tmp_path, "P000A")


def test_retry_and_failed_close_retain_all_physical_leases(monkeypatch, tmp_path):
    native, com = inventory(monkeypatch, 1, paired=False)
    attempts, observed_locks = [], []
    close_allowed = Event()

    def native_close():
        if not close_allowed.is_set():
            raise OSError("close still pending")

    owner = NativeHandleCleanupError(RuntimeError("probe setup"), OSError("close"),
                                     native_close, serial="P000")

    def probe(endpoint, settings):
        attempts.append(settings["baudrate"])
        # Record assertions because the production scanner isolates exceptions.
        for identity in ("P000", "P000A"):
            try:
                assert_lease_held(tmp_path, identity)
                observed_locks.append(identity)
            except AssertionError:
                pass
        if len(attempts) == 1:
            return PodProbe(True, False, None, endpoint["hardware_id"], "probe_timeout")
        raise owner

    try:
        devices, warnings = native_scan.scan_endpoints(native_lister=native, port_lister=com,
                                                       prober=probe, directory=tmp_path)
        assert attempts == [9600, 115200]
        assert observed_locks == ["P000", "P000A", "P000", "P000A"]
        assert devices[0].availability == "unopenable"
        assert devices[0].endpoints[0]["error_code"] == "cleanup_pending"
        assert any(warning["code"] == "cleanup_pending" for warning in warnings)
        for identity in ("P000", "P000A"):
            assert_lease_held(tmp_path, identity)
        with pytest.raises(NativeHandleCleanupError):
            owner.retry_close()
        assert_lease_held(tmp_path, "P000")
    finally:
        close_allowed.set()
        owner.retry_close()
    assert_lease_free(tmp_path, "P000")
    assert_lease_free(tmp_path, "P000A")


def test_api_snapshot_is_read_only_joined_and_persisted_once(app, monkeypatch, tmp_path):
    events = []
    native, com = inventory(monkeypatch, 2, paired=False, events=events)
    enumeration_entered, enumerate_release = Event(), Event()
    slow_entered, slow_release, fast_visible = Event(), Event(), Event()
    ids_during_enumeration = []
    service = None

    def enumerator():
        # Public API reentry proves identity allocation before first inventory.
        ids_during_enumeration.append(service.start().scan_id)
        enumeration_entered.set()
        assert enumerate_release.wait(6)
        return native()

    def probe(endpoint, _settings):
        if endpoint["address"] == "P000":
            slow_entered.set()
            assert slow_release.wait(6)
        else:
            assert slow_entered.wait(2)
        return PodProbe(True, True, 48, endpoint["hardware_id"])

    provider = FtdiPodProvider(directory=tmp_path / "leases", native_lister=enumerator,
                               port_lister=com, prober=probe)
    service = DeviceDiscoveryService(provider, context_factory=app.app_context)
    app.extensions["device_discovery_service"] = service
    client = app.test_client()
    try:
        response = client.post("/api/v1/devices/scans")
        assert response.status_code == 202
        initial = response.get_json()
        scan_id = initial["scan_id"]
        assert enumeration_entered.wait(2)
        assert ids_during_enumeration == [scan_id]
        assert initial["state"] == "enumerating"
        with ThreadPoolExecutor(max_workers=6) as callers:
            joined = list(callers.map(lambda _: service.start().scan_id, range(12)))
        assert joined == [scan_id] * 12
        for _ in range(5):
            snapshot_response = client.get(f"/api/v1/devices/scans/{scan_id}")
            assert snapshot_response.status_code == 200
            assert snapshot_response.get_json()["scan_id"] == scan_id
        assert events == []
        enumerate_release.set()
        assert slow_entered.wait(2)

        # Wait on the real coordinator's publication, without another scan.
        for _ in range(100):
            partial = client.get(f"/api/v1/devices/scans/{scan_id}").get_json()
            if partial["completed"] == 1:
                fast_visible.set()
                break
            fast_visible.wait(0.01)
        assert fast_visible.is_set()
        assert partial["state"] == "probing"
        assert partial["total"] == 2
        assert sorted(row["availability"] for row in partial["devices"]) == ["available", "unverified"]
        assert len({row["scan_key"] for row in partial["devices"]}) == 2
        partial_keys = [row["scan_key"] for row in partial["devices"]]
        with app.app_context():
            assert db.session.query(DeviceSeen).count() == 0
        escaped = service.snapshot(scan_id)
        escaped.devices[0].endpoints[0]["address"] = "CORRUPTED"
        assert service.snapshot(scan_id).devices[0].endpoints[0]["address"] != "CORRUPTED"

        with ThreadPoolExecutor(max_workers=1) as waiter:
            joined_result = waiter.submit(service.scan)
            try:
                assert not joined_result.done()
            finally:
                slow_release.set()
            assert joined_result.result(timeout=5).scan_id == scan_id
        final = client.get(f"/api/v1/devices/scans/{scan_id}").get_json()
        assert final["state"] == "complete"
        assert final["completed"] == final["total"] == 2
        assert final["revision"] > partial["revision"]
        assert [row["scan_key"] for row in final["devices"]] == partial_keys
        assert all(row["availability"] == "available" for row in final["devices"])
        for _ in range(4):
            assert client.get(f"/api/v1/devices/scans/{scan_id}").get_json() == final
        assert events == ["native", "com", "registry"]
        assert client.get("/api/v1/devices/scans/missing").status_code == 404
        with app.app_context():
            persisted = db.session.query(DeviceSeen).all()
            assert len(persisted) == 2
            assert {row.scan_id for row in persisted} == {scan_id}
    finally:
        enumerate_release.set()
        slow_release.set()
        if service._active is not None:
            assert service._active.done.wait(5)
