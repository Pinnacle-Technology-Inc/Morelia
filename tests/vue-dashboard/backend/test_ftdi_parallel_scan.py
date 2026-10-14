"""Independent requirement-derived concurrency checks; no hardware is opened."""

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, get_ident
from types import SimpleNamespace

import pytest
from app.discovery import native_scan
from app.discovery.pod_scan import PodProbe
from app.services.discovery import FtdiPodProvider
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet


def port(identity, number):
    return SimpleNamespace(
        serial_number=identity,
        device=f"COM{number}",
        vid=0x0403,
        description="Independent oracle POD",
    )


def native(identity, **extra):
    return {
        "hardware_id": identity,
        "address": identity,
        "transport": "d2xx",
        "backend": "ftd2xx",
        **extra,
    }


def success(endpoint):
    return PodProbe(True, True, 48, endpoint["hardware_id"])


@pytest.fixture(autouse=True)
def controlled_registry(monkeypatch):
    monkeypatch.setattr(native_scan, "annotate_endpoints", lambda endpoints: endpoints)


def test_provider_probes_four_devices_on_workers_with_stable_order(tmp_path):
    identities = [f"ORACLE{i:02}" for i in range(9)]
    counts = Counter()
    mutex = Lock()
    caller_thread = get_ident()
    active = 0
    maximum = 0
    entered = []
    first_wave = Barrier(4)

    def vcp_inventory():
        counts["vcp"] += 1
        return [
            port(identity, 9000 + index) for index, identity in enumerate(identities)
        ]

    def native_inventory():
        counts["native"] += 1
        return [native(identity) for identity in identities]

    def probe(endpoint, _profile):
        nonlocal active, maximum
        assert counts == {"vcp": 1, "native": 1}, "inventory must finish before probes"
        assert get_ident() != caller_thread
        with mutex:
            entered.append(endpoint["hardware_id"])
            active += 1
            maximum = max(maximum, active)
        try:
            if identities.index(endpoint["hardware_id"]) < 4:
                first_wave.wait(timeout=5)
            # Unequal completions must not reorder the returned inventory.
            time.sleep((8 - identities.index(endpoint["hardware_id"])) * 0.002)
            return success(endpoint)
        finally:
            with mutex:
                active -= 1

    provider = FtdiPodProvider(
        directory=tmp_path,
        port_lister=vcp_inventory,
        native_lister=native_inventory,
        prober=probe,
        configurations=lambda: ({}, frozenset()),
    )
    rows = provider.scan()
    assert maximum == 4
    assert counts == {"vcp": 1, "native": 1}
    assert Counter(entered) == Counter(identities), (
        "aliases must not become separate probe jobs"
    )
    assert [row.hardware_id for row in rows] == identities
    assert all(
        row.availability == "available" and len(row.endpoints) == 2 for row in rows
    )


def test_native_retry_keeps_same_lease_and_does_not_probe_alias(tmp_path, monkeypatch):
    identity = "EXACT001"
    alias = "EXACT001A"
    physical = "container-independent-001"
    calls = []

    def annotate(endpoint):
        return {
            **endpoint,
            "hardware_id": identity,
            "physical_id": physical,
            "aliases": [identity, alias],
        }

    monkeypatch.setattr(native_scan, "annotate_endpoints", lambda endpoints: [annotate(ep) for ep in endpoints])

    def probe(endpoint, profile):
        calls.append((endpoint["transport"], profile["baudrate"]))
        for key in (identity, alias, physical):
            with pytest.raises(HardwareLeaseBusy):
                with HardwareLeaseSet.for_devices([(key, "OTHER")], directory=tmp_path):
                    pytest.fail("physical lease was absent during probe/retry")
        if len(calls) == 1:
            return PodProbe(True, False, None, identity, "probe_timeout")
        return success(endpoint)

    provider = FtdiPodProvider(
        directory=tmp_path,
        port_lister=lambda: [],
        native_lister=lambda: [native(alias)],
        prober=probe,
        configurations=lambda: ({}, frozenset()),
    )
    rows = provider.scan()
    assert calls == [("d2xx", 9600), ("d2xx", 115200)]
    assert len(rows) == 1 and rows[0].availability == "available"
    with HardwareLeaseSet.for_devices(
        [(key, "OTHER") for key in (identity, alias, physical)], directory=tmp_path
    ) as lease:
        assert lease.acquired


def test_exclusions_and_failure_are_isolated_and_all_leases_release(tmp_path):
    identities = [
        "CLAIM001",
        "BUSY0001",
        "AMBIG001",
        "LOCK0001",
        "FAIL0001",
        "GOOD0001",
    ]
    calls = []
    vcp = [port(identity, 9100 + index) for index, identity in enumerate(identities)]
    vcp.append(port("AMBIG001", 9200))

    def probe(endpoint, _profile):
        calls.append(endpoint["hardware_id"])
        if endpoint["hardware_id"] == "FAIL0001":
            raise OSError("independent injected endpoint failure")
        return success(endpoint)

    provider = FtdiPodProvider(
        directory=tmp_path,
        port_lister=lambda: vcp,
        native_lister=lambda: [
            native(identity, flags=1 if identity == "BUSY0001" else 0)
            for identity in identities
        ],
        prober=probe,
        configurations=lambda: ({}, frozenset({"CLAIM001"})),
    )
    with HardwareLeaseSet.for_devices([("LOCK0001", "OTHER")], directory=tmp_path):
        rows = provider.scan()
    assert set(calls) == {"FAIL0001", "GOOD0001"}
    assert [row.hardware_id for row in rows] == identities
    assert [row.availability for row in rows] == ["unopenable"] * 4 + ["unavailable", "available"]
    with HardwareLeaseSet.for_devices(
        [(identity, "OTHER") for identity in identities], directory=tmp_path
    ) as lease:
        assert lease.acquired


def test_concurrent_native_inventory_reads_one_consistent_snapshot(monkeypatch):
    from app.discovery import ftdi_transport as d2xx_helpers

    state = {"generation": 0, "pending_details": 0, "overlap": False, "refreshes": 0}
    gate = Lock()

    class DriverBoundary:
        def createDeviceInfoList(self):
            with gate:
                if state["pending_details"]:
                    state["overlap"] = True
                state["generation"] += 1
                state["refreshes"] += 1
                state["pending_details"] = 4
            time.sleep(0.005)
            return 4

        def getDeviceInfoDetail(self, index, update=True):
            assert update is False, "detail reads must not refresh the native snapshot"
            time.sleep(0.005)
            with gate:
                generation = state["generation"]
                state["pending_details"] -= 1
            return {"serial": f"GEN{generation:02}I{index}", "description": "Oracle"}

    monkeypatch.setattr(d2xx_helpers, "ftd", DriverBoundary())
    start = Event()

    def read():
        assert start.wait(5)
        return d2xx_helpers.list_d2xx_devices(native_only=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        start.set()
        snapshots = [future.result(timeout=10) for future in futures]
    assert not state["overlap"], (
        "native global inventory refreshed during another snapshot read"
    )
    assert state["refreshes"] == 8
    assert all(
        len({row["serial"][:5] for row in snapshot}) == 1 for snapshot in snapshots
    )
    assert len({snapshot[0]["serial"][:5] for snapshot in snapshots}) == 8
