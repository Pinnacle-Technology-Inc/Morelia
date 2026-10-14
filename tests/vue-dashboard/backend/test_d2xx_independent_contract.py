"""Independent transport invariants from the requested VCP/D2XX coexistence contract.

The Windows fixture is the passive FT245R registry relationship observed during
this task. USB inventory is injected; the ownership test uses real OS file locks.
No physical device is opened.
"""

from types import SimpleNamespace

import pytest
from app.cli.device_cmd import _looks_like_hardware_id
from app.discovery import windows_ftdi_identity as identity
from app.runtime_child.device_connection import (
    constructor_connection_kwargs,
    current_connection_address,
    current_connection_present,
)
from app.services import connections
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet

PROOF = {
    "native_serial": "AB0MZ1AZ",
    "physical_id": "AB0MZ1AZ",
    "hardware_id": "AB0MZ1AZA",
    "port": "COM9",
    "identity_evidence": "windows_container_id",
}


def native_endpoint():
    return {
        "transport": "d2xx",
        "backend": "ftd2xx",
        "address": "AB0MZ1AZ",
        "hardware_id": "AB0MZ1AZ",
        "type": 5,
        "id": 0x04036001,
    }


def frozen_binding(*, hardware_id="AB0MZ1AZA"):
    return {
        "transport": "d2xx",
        "backend": "ftd2xx",
        "address": "AB0MZ1AZ",
        "hardware_id": hardware_id,
        "physical_id": "AB0MZ1AZ",
        "baudrate": 115200,
        "flow_control": "rts_cts",
        "read_timeout_ms": 2000,
        "write_timeout_ms": 3000,
        "selection_reason": "explicit_preference",
    }


def test_cli_accepts_observed_windows_ftdi_alias():
    assert _looks_like_hardware_id("AB0MZ1AZA")


def test_similar_serials_are_never_merged_without_registry_proof():
    endpoint = native_endpoint()
    assert identity.annotate_endpoint(endpoint, bindings=[]) == endpoint
    unrelated = {**PROOF, "native_serial": "AB0MZ1A"}
    assert identity.annotate_endpoint(endpoint, bindings=[unrelated]) == endpoint


@pytest.mark.parametrize("patch", [{"type": 6}, {"id": 0x04036010}])
def test_proof_for_single_channel_chip_does_not_alias_other_chips(patch):
    endpoint = {**native_endpoint(), **patch}
    assert identity.annotate_endpoint(endpoint, bindings=[PROOF]) == endpoint


def test_verified_alias_preserves_actual_open_address_and_raw_lock_identity():
    annotated = identity.annotate_endpoint(native_endpoint(), bindings=[PROOF])
    assert annotated["hardware_id"] == "AB0MZ1AZA"
    assert annotated["physical_id"] == "AB0MZ1AZ"
    assert annotated["address"] == "AB0MZ1AZ"
    assert set(annotated["aliases"]) == {"AB0MZ1AZ", "AB0MZ1AZA"}
    vcp = {"transport": "vcp", "hardware_id": "AB0MZ1AZA", "address": "COM8"}
    assert identity.annotate_endpoint(vcp, bindings=[PROOF]) == vcp


def test_recovery_uses_frozen_native_transport_and_exact_raw_serial(monkeypatch):
    endpoint = identity.annotate_endpoint(native_endpoint(), bindings=[PROOF])
    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [endpoint])

    def forbidden_vcp_inventory():
        pytest.fail(
            "Recovery attempted to switch away from the frozen native transport"
        )

    monkeypatch.setattr(connections, "list_vcp_endpoints", forbidden_vcp_inventory)
    flow = SimpleNamespace(hardware_id="AB0MZ1AZA", connection=frozen_binding())
    assert current_connection_address(flow, "pod8401hr") == "AB0MZ1AZ"
    assert constructor_connection_kwargs(flow) == {
        "baudrate": 115200,
        "use_d2xx": True,
        "d2xx_serial_only": True,
        "flow_control": "rts_cts",
        "read_timeout_ms": 2000,
        "write_timeout_ms": 3000,
    }
    monkeypatch.setattr(connections, "list_native_endpoints", list)
    assert current_connection_address(flow, "pod8401hr") == "AB0MZ1AZ"
    assert current_connection_present(flow, "pod8401hr") is False


def test_recovery_rejects_changed_proven_physical_identity(monkeypatch):
    endpoint = {
        **identity.annotate_endpoint(native_endpoint(), bindings=[PROOF]),
        "physical_id": "OTHER123",
        "address": "OTHER123",
    }
    monkeypatch.setattr(connections, "list_native_endpoints", lambda: [endpoint])
    flow = SimpleNamespace(hardware_id="AB0MZ1AZA", connection=frozen_binding())
    with pytest.raises(connections.ConnectionResolutionError):
        current_connection_present(flow, "pod8401hr")


def test_native_runtime_cannot_overlap_legacy_vcp_alias_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "verified_bindings", lambda: [PROOF])
    native = SimpleNamespace(
        device_flows=[
            SimpleNamespace(
                hardware_id="AB0MZ1AZ",
                port="AB0MZ1AZ",
                connection=frozen_binding(hardware_id="AB0MZ1AZ"),
            )
        ]
    )
    # An already-running old process only holds its original alias lock; do
    # not reconstruct its manifest through the upgraded lease implementation.
    legacy = HardwareLeaseSet.for_devices([("AB0MZ1AZA", "COM9")], directory=tmp_path)
    with (
        legacy,
        pytest.raises(HardwareLeaseBusy),
        HardwareLeaseSet(native, directory=tmp_path),
    ):
        pass


def test_alias_lock_negative_control_distinct_names_alone_do_not_conflict(tmp_path):
    """Removing alias expansion must expose the collision this review guards."""
    alias_only = HardwareLeaseSet.for_devices(
        [("AB0MZ1AZA", "COM9")], directory=tmp_path
    )
    raw_only = HardwareLeaseSet.for_devices(
        [("AB0MZ1AZ", "AB0MZ1AZ")], directory=tmp_path
    )
    with alias_only, raw_only:
        assert alias_only.acquired and raw_only.acquired
