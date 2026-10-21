"""Selection policy tests use independent endpoint inventories; never open USB."""

import pytest

from app.services import connections
from app.services.connections import (
    ConnectionResolutionError,
    resolve_connection,
    validate_current_connection,
)


def endpoint(transport, serial="12345678", address=None):
    return {
        "hardware_id": serial,
        "transport": transport,
        "backend": "pyserial" if transport == "vcp" else "ftd2xx",
        "address": address or ("COM12" if transport == "vcp" else serial),
    }


@pytest.mark.parametrize(
    "preference,vcp,native,expected",
    [
        ("auto", True, True, "vcp"),
        ("auto", True, False, "vcp"),
        ("auto", False, True, "d2xx"),
        ("vcp", True, True, "vcp"),
        ("d2xx", True, True, "d2xx"),
    ],
)
def test_selection_table(monkeypatch, preference, vcp, native, expected):
    monkeypatch.setattr(
        connections, "list_vcp_endpoints", lambda: [endpoint("vcp")] if vcp else []
    )
    monkeypatch.setattr(
        connections,
        "list_native_endpoints",
        lambda: [endpoint("d2xx")] if native else [],
    )
    result = resolve_connection("12345678", {"preference": preference}, "pod8206hr")
    assert result["transport"] == expected
    assert result["address"] == ("COM12" if expected == "vcp" else "12345678")
    assert result["flow_control"] == ("none" if expected == "vcp" else "rts_cts")


def test_omitted_connection_preserves_vcp_and_does_not_enumerate_native(monkeypatch):
    monkeypatch.setattr(connections, "list_vcp_endpoints", lambda: [endpoint("vcp")])
    monkeypatch.setattr(
        connections, "list_native_endpoints", lambda: pytest.fail("native touched")
    )
    assert resolve_connection("12345678", {}, "pod8206hr")["transport"] == "vcp"


@pytest.mark.parametrize("preference", ["vcp", "d2xx"])
def test_explicit_absent_never_falls_back(monkeypatch, preference):
    monkeypatch.setattr(
        connections,
        "list_vcp_endpoints",
        lambda: [] if preference == "vcp" else [endpoint("vcp")],
    )
    monkeypatch.setattr(
        connections,
        "list_native_endpoints",
        lambda: [] if preference == "d2xx" else [endpoint("d2xx")],
    )
    with pytest.raises(ConnectionResolutionError) as exc:
        resolve_connection("12345678", {"preference": preference}, "pod8206hr")
    assert exc.value.code == "not_found"


def test_auto_does_not_hide_driver_enumeration_error(monkeypatch):
    def broken():
        raise RuntimeError("driver failed")

    monkeypatch.setattr(connections, "list_vcp_endpoints", broken)
    monkeypatch.setattr(
        connections, "list_native_endpoints", lambda: pytest.fail("unsafe fallback")
    )
    with pytest.raises(ConnectionResolutionError, match="driver failed"):
        resolve_connection("12345678", {"preference": "auto"}, "pod8206hr")


@pytest.mark.parametrize("transport", ["vcp", "d2xx"])
def test_duplicate_identity_fails_closed(monkeypatch, transport):
    monkeypatch.setattr(
        connections,
        "list_vcp_endpoints",
        lambda: [endpoint("vcp"), endpoint("vcp", address="COM13")],
    )
    monkeypatch.setattr(
        connections,
        "list_native_endpoints",
        lambda: [endpoint("d2xx"), endpoint("d2xx")],
    )
    with pytest.raises(ConnectionResolutionError) as exc:
        resolve_connection("12345678", {"preference": transport}, "pod8206hr")
    assert exc.value.code == "identity_ambiguous"


def test_channel_suffix_and_case_are_not_normalized(monkeypatch):
    monkeypatch.setattr(
        connections, "list_native_endpoints", lambda: [endpoint("d2xx", "abc1234A")]
    )
    for serial in ("abc1234", "ABC1234A"):
        with pytest.raises(ConnectionResolutionError, match="No d2xx"):
            resolve_connection(serial, {"preference": "d2xx"}, "pod8206hr")


def test_profile_and_frozen_recovery(monkeypatch):
    monkeypatch.setattr(connections, "list_vcp_endpoints", lambda: [endpoint("vcp")])
    result = resolve_connection(
        "12345678",
        {
            "preference": "auto",
            "baudrate": 115200,
            "flow_control": "rts_cts",
            "read_timeout_ms": 2100,
            "write_timeout_ms": 3100,
        },
        "pod8401hr",
    )
    monkeypatch.setattr(
        connections, "list_vcp_endpoints", lambda: [endpoint("vcp", address="COM44")]
    )
    refreshed = validate_current_connection(result)
    assert refreshed == {**result, "address": "COM44"}
    assert result["address"] == "COM12"
    monkeypatch.setattr(connections, "list_vcp_endpoints", lambda: [])
    monkeypatch.setattr(
        connections,
        "list_native_endpoints",
        lambda: pytest.fail("recovery switched transport"),
    )
    with pytest.raises(ConnectionResolutionError):
        validate_current_connection(result)


def test_native_unsupported_model_is_not_opened_or_enumerated(monkeypatch):
    monkeypatch.setattr(
        connections,
        "list_native_endpoints",
        lambda: pytest.fail("unsupported backend touched"),
    )
    with pytest.raises(ConnectionResolutionError) as exc:
        resolve_connection("12345678", {"preference": "d2xx"}, "pod8274d")
    assert exc.value.code == "transport_unsupported"


def test_verified_native_alias_preserves_config_identity_and_opens_raw_serial(
    monkeypatch,
):
    mapped = {
        **endpoint("d2xx", "RAW12345", "RAW12345"),
        "hardware_id": "RAW12345A",
        "aliases": ("RAW12345", "RAW12345A"),
        "physical_id": "RAW12345",
    }
    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [mapped])
    for identity in ("RAW12345", "RAW12345A"):
        resolved = resolve_connection(identity, {"preference": "d2xx"}, "pod8206hr")
        assert resolved["hardware_id"] == identity
        assert resolved["address"] == "RAW12345"
        assert resolved["physical_id"] == "RAW12345"
        assert validate_current_connection(resolved) == resolved


def test_recovery_rejects_changed_physical_identity_evidence(monkeypatch):
    mapped = {**endpoint("vcp"), "physical_id": "RAW12345"}
    monkeypatch.setattr(connections, "list_vcp_endpoints", lambda: [mapped])
    resolved = resolve_connection("12345678", {}, "pod8206hr")
    monkeypatch.setattr(connections, "list_vcp_endpoints", lambda: [endpoint("vcp")])
    with pytest.raises(ConnectionResolutionError, match="identity evidence changed"):
        validate_current_connection(resolved)
