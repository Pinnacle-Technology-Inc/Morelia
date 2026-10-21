from types import SimpleNamespace

import pytest

from app.discovery.pod_scan import DiscoveredDevice
from app.domain.enums import DeviceClaimState, DeviceType
from app.services import device_list


def configured(monkeypatch, preference):
    config = SimpleNamespace(
        id=7, device_type=DeviceType.POD8206HR, hardware_id="SERIAL", port="COM1",
        color=None, claim_state=DeviceClaimState.FREE, claimed_session_id=None,
        nickname=None, source_template=None, source_template_hash=None,
        parameters={"preamp_gain": 10}, connection={"preference": preference},
    )
    monkeypatch.setattr(device_list.device_configs, "list", lambda: [config])
    monkeypatch.setattr(device_list.device_registrations, "list", lambda: [])


@pytest.mark.parametrize("preference,observed", [("vcp", "d2xx"), ("d2xx", "vcp")])
def test_other_alias_does_not_prove_preferred_transport_absent_when_enumeration_failed(
    monkeypatch, preference, observed,
):
    configured(monkeypatch, preference)
    seen = DiscoveredDevice(DeviceType.POD8206HR, "OTHER", "SERIAL", "POD", "unopenable",
                            ({"transport": observed, "address": "OTHER", "availability": "unverified"},))
    warning = {"transport": preference, "code": "enumeration_failed", "message": "injected"}
    row, = device_list.build_pool_rows([seen], warnings=(warning,))
    assert row["availability"] == "unavailable"
    assert row["connection_error"] == "enumeration_failed"


def test_successful_selected_endpoint_stays_available_when_other_inventory_fails(monkeypatch):
    configured(monkeypatch, "vcp")
    seen = DiscoveredDevice(DeviceType.POD8206HR, "COM1", "SERIAL", "POD", "available",
                            ({"transport": "vcp", "address": "COM1", "availability": "available"},), "vcp")
    row, = device_list.build_pool_rows([seen], warnings=({"transport": "d2xx", "code": "enumeration_failed"},))
    assert row["availability"] == "available"


def test_configured_row_keeps_key_from_enumeration_through_identification(monkeypatch):
    configured(monkeypatch, "vcp")
    initial, = device_list.build_pool_rows([], scan_state="enumerating")
    queued = DiscoveredDevice(DeviceType.UNKNOWN, "COM1", "SERIAL", "POD", "unverified",
                              ({"transport": "vcp", "address": "COM1", "availability": "unverified"},),
                              "vcp", "device:SERIAL", "queued")
    pending, = device_list.build_pool_rows([queued], scan_state="probing")
    assert initial["scan_key"] == pending["scan_key"] == "config:7"
    assert pending["id"] == 7
    assert pending["availability"] == "unverified"
    assert pending["connection_error"] is None
    assert pending["probe_state"] == "queued"
