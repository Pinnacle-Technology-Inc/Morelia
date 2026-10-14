"""Runtime connection invariants independent of native hardware availability."""

from types import SimpleNamespace

import pytest
from app.domain.connections import ConnectionError
from app.runtime_child.device_connection import (
    apply_or_defer_parameters,
    constructor_connection_kwargs,
    current_connection_address,
    current_connection_present,
)


def flow(transport="d2xx"):
    binding = {
        "transport": transport,
        "backend": "ftd2xx" if transport == "d2xx" else "pyserial",
        "hardware_id": "001AbC",
        "address": "001AbC" if transport == "d2xx" else "COM7",
        "baudrate": 115200,
        "flow_control": "rts_cts" if transport == "d2xx" else "none",
        "read_timeout_ms": 250,
        "write_timeout_ms": 500,
        "selection_reason": "explicit_preference",
    }
    return SimpleNamespace(connection=binding, hardware_id="001AbC", port=binding["address"],
                           parameters={"sample_rate": 2000})


def test_native_constructor_uses_frozen_settings_over_legacy_defaults():
    kwargs = constructor_connection_kwargs(flow(), legacy_baudrate=9600, legacy_use_d2xx=False)
    assert kwargs == {
        "baudrate": 115200, "use_d2xx": True, "d2xx_serial_only": True,
        "flow_control": "rts_cts", "read_timeout_ms": 250, "write_timeout_ms": 500,
    }


def test_mismatched_binding_identity_never_reaches_constructor():
    candidate = flow()
    candidate.connection["hardware_id"] = "OTHER"
    with pytest.raises(ConnectionError, match="identity"):
        constructor_connection_kwargs(candidate)


def test_native_setters_are_not_called_before_worker_open():
    class Pod:
        @property
        def lowpass_ch0(self):
            raise AssertionError("must not invoke hardware getter during construction")

        @lowpass_ch0.setter
        def lowpass_ch0(self, value):
            raise AssertionError("must not invoke hardware setter before owned open")

    pod = Pod()
    apply_or_defer_parameters(pod, {"lowpass_ch0": 100}, flow())
    assert pod._startup_parameters == {"lowpass_ch0": 100, "sample_rate": 2000}


def test_unknown_pending_setting_rejected_before_worker():
    with pytest.raises(ValueError, match="unsupported"):
        apply_or_defer_parameters(SimpleNamespace(), {"bad": 1}, flow())


def test_recovery_does_not_reenter_auto(monkeypatch):
    from app.services import connections
    candidate = flow()
    def resolve(*args):
        pytest.fail("Native address selection must not enumerate or resolve again")

    monkeypatch.setattr(connections, "resolve_connection", resolve)
    assert current_connection_address(candidate, "pod8206hr") == "001AbC"
    assert candidate.connection["selection_reason"] == "explicit_preference"


def test_recovery_refreshes_vcp_address_without_mutating_run(monkeypatch):
    from app.services import connections
    candidate = flow("vcp")
    monkeypatch.setattr(connections, "resolve_connection", lambda *_: {
        **candidate.connection, "address": "COM22",
    })
    assert current_connection_address(candidate, "pod8206hr") == "COM22"
    assert candidate.connection["address"] == "COM7"


def test_legacy_constructor_keyword_shape_is_preserved():
    old = SimpleNamespace(parameters={}, port="COM7")
    assert constructor_connection_kwargs(old) == {"baudrate": 9600, "use_d2xx": False}


def test_recovery_rejects_changed_physical_alias_mapping(monkeypatch):
    from app.services import connections
    candidate = flow()
    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [{
        **candidate.connection, "physical_id": "OTHER",
    }])
    with pytest.raises(connections.ConnectionResolutionError):
        current_connection_present(candidate, "pod8206hr")


def test_legacy_native_serial_still_requires_live_presence(monkeypatch):
    from app.services import connections
    candidate = SimpleNamespace(port="RAW001", hardware_id="RAW001A",
                                parameters={"use_d2xx": True})
    monkeypatch.setattr(connections, "list_native_endpoints", list)
    assert current_connection_address(candidate, "pod8206hr") == "RAW001"
    assert current_connection_present(candidate, "pod8206hr") is False
    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [{
        "address": "RAW001", "hardware_id": "RAW001", "backend": "ftd2xx"}])
    assert current_connection_present(candidate, "pod8206hr") is True
