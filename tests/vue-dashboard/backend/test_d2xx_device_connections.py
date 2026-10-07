import pytest

from app.domain.connections import ConnectionError, normalize_resolved_connection


def _resolved():
    return {
        "transport": "d2xx",
        "backend": "ftd2xx",
        "address": "001a",
        "hardware_id": "001a",
        "baudrate": 9600,
        "flow_control": "rts_cts",
        "read_timeout_ms": 5000,
        "write_timeout_ms": 5000,
        "selection_reason": "explicit",
    }


def test_resolved_binding_preserves_exact_identity():
    assert normalize_resolved_connection(_resolved(), hardware_id="001a") == _resolved()
    with pytest.raises(ConnectionError):
        normalize_resolved_connection(_resolved(), hardware_id="001A")


def test_verified_alias_binding_preserves_logical_and_physical_identity():
    binding = {
        **_resolved(),
        "hardware_id": "AB0MZ1AZA",
        "physical_id": "AB0MZ1AZ",
        "address": "AB0MZ1AZ",
    }
    assert normalize_resolved_connection(binding, hardware_id="AB0MZ1AZA") == binding
    del binding["physical_id"]
    with pytest.raises(ConnectionError):
        normalize_resolved_connection(binding, hardware_id="AB0MZ1AZA")
