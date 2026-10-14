"""Alias decisions require evidence, not serial-string resemblance."""

from app.discovery.windows_ftdi_identity import annotate_endpoint

BINDING = {
    "native_serial": "AB0MZ1AZ", "hardware_id": "AB0MZ1AZA", "physical_id": "AB0MZ1AZ",
    "port": "COM9", "identity_evidence": "windows_container_id",
}
NATIVE = {
    "hardware_id": "AB0MZ1AZ", "address": "AB0MZ1AZ", "transport": "d2xx",
    "type": 5, "id": 0x04036001,
}


def test_proven_single_interface_alias_keeps_native_selector():
    native = annotate_endpoint(NATIVE, bindings=[BINDING])
    vcp = annotate_endpoint({"hardware_id": "AB0MZ1AZA", "address": "COM9", "transport": "vcp"},
                            bindings=[BINDING])
    assert native["hardware_id"] == vcp["hardware_id"] == "AB0MZ1AZA"
    assert native["physical_id"] == vcp["physical_id"] == "AB0MZ1AZ"
    assert native["address"] == "AB0MZ1AZ"
    assert native["aliases"] == ("AB0MZ1AZA", "AB0MZ1AZ")


def test_suffix_resemblance_without_registry_proof_is_not_mapping():
    assert annotate_endpoint(NATIVE, bindings=[]) == NATIVE


def test_multichannel_chip_never_uses_single_interface_mapping():
    endpoint = {**NATIVE, "type": 6}
    assert annotate_endpoint(endpoint, bindings=[BINDING]) == endpoint


def test_ambiguous_registry_proof_is_rejected():
    assert annotate_endpoint(NATIVE, bindings=[BINDING, BINDING]) == NATIVE


def test_vcp_address_or_case_sensitive_serial_mismatch_is_not_mapping():
    for endpoint in [
        {"hardware_id": "AB0MZ1AZA", "address": "COM3", "transport": "vcp"},
        {"hardware_id": "ab0mz1aza", "address": "COM9", "transport": "vcp"},
    ]:
        assert annotate_endpoint(endpoint, bindings=[BINDING]) == endpoint
