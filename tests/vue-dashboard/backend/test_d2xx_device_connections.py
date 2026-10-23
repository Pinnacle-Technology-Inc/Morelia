"""Connection contracts exercised through domain/service/API; no hardware opens."""

import pytest
from app.database import db
from app.domain.connections import (
    ConnectionError,
    normalize_connection,
    normalize_resolved_connection,
)
from app.domain.enums import DeviceClaimState, DeviceType
from app.domain.errors import DeviceConfigNotFree
from app.services import device_configs, device_templates


def test_legacy_connection_defaults_and_auto_does_not_choose_flow_control():
    assert normalize_connection(None) == {
        "preference": "vcp",
        "baudrate": 9600,
        "read_timeout_ms": 5000,
        "write_timeout_ms": 5000,
    }
    assert "flow_control" not in normalize_connection({"preference": "auto"})


@pytest.mark.parametrize(
    "settings",
    [
        [],
        {"preference": "D2XX"},
        {"baudrate": True},
        {"baudrate": "9600"},
        {"read_timeout_ms": 0},
        {"write_timeout_ms": -1},
        {"flow_control": "xonxoff"},
        {"use_d2xx": True},
        {"physical_id": "AB0MZ1AZ"},
    ],
)
def test_invalid_connection_settings_fail_closed(settings):
    with pytest.raises(ConnectionError):
        normalize_connection(settings)


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


@pytest.mark.parametrize("physical_id", [None, "", "  ", 1, True, [], "001A"])
def test_invalid_or_mismatched_physical_identity_is_rejected(physical_id):
    with pytest.raises(ConnectionError):
        normalize_resolved_connection({**_resolved(), "physical_id": physical_id})


def test_legacy_binding_does_not_gain_optional_physical_identity():
    assert "physical_id" not in normalize_resolved_connection(_resolved())


@pytest.mark.parametrize(
    "patch",
    [
        {"address": "0"},
        {"backend": "pylibftdi"},
        {"transport": "auto"},
        {"extra": 1},
        {"selection_reason": ""},
        {"read_timeout_ms": False},
    ],
)
def test_invalid_frozen_binding_is_rejected(patch):
    with pytest.raises(ConnectionError):
        normalize_resolved_connection({**_resolved(), **patch})


def test_connection_edit_preserves_acquisition_and_template_provenance(app):
    with app.app_context():
        config = device_configs.create(
            device_type=DeviceType.POD8206HR,
            hardware_id="001a",
            port="COM8",
            parameters={"preamp_gain": 10},
            source_template="device-templates/eeg.toml",
            source_template_hash="old-hash",
        )
        original_parameters = dict(config.parameters)
        device_configs.edit(
            config.id, connection={"preference": "d2xx", "baudrate": 115200}
        )
        db.session.expire_all()
        saved = device_configs.get_by_id(config.id)
        assert saved.connection["preference"] == "d2xx"
        assert saved.hardware_id == "001a"
        assert saved.port == "001a"
        assert saved.parameters == original_parameters
        assert saved.source_template == "device-templates/eeg.toml"
        assert saved.source_template_hash == "old-hash"
        assert saved.source_template_history is None


@pytest.mark.parametrize("state", [DeviceClaimState.STARTING, DeviceClaimState.CLAIMED])
def test_claimed_connection_cannot_change(app, state):
    with app.app_context():
        config = device_configs.create(
            device_type=DeviceType.POD8206HR,
            hardware_id="002a",
            parameters={"preamp_gain": 10},
        )
        config.claim_state = state
        db.session.commit()
        with pytest.raises(DeviceConfigNotFree):
            device_configs.edit(config.id, connection={"preference": "d2xx"})
        assert config.connection["preference"] == "vcp"


def test_unsupported_native_model_is_rejected_before_persistence(app):
    with app.app_context(), pytest.raises(ConnectionError):
        device_configs.create(
            device_type=DeviceType.POD8274D,
            hardware_id="003a",
            parameters={"device_serial_number": "001"},
            connection={"preference": "d2xx"},
        )


def test_native_config_can_be_created_and_patched_without_com_port(client):
    response = client.post(
        "/api/v1/device-configs",
        json={
            "type": "pod8206hr",
            "hardware_id": "004a",
            "parameters": {"preamp_gain": 10},
            "connection": {"preference": "d2xx"},
        },
    )
    assert response.status_code == 201, response.get_json()
    config = response.get_json()
    assert config["port"] == "004a"
    assert config["connection"]["preference"] == "d2xx"
    response = client.patch(
        f"/api/v1/device-configs/{config['id']}",
        json={
            "connection": {"preference": "auto"},
        },
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["parameters"] == config["parameters"]
    assert response.get_json()["connection"]["preference"] == "auto"


def test_legacy_api_create_still_defaults_to_vcp(client):
    response = client.post(
        "/api/v1/device-configs",
        json={
            "type": "pod8206hr",
            "hardware_id": "005a",
            "port": "COM9",
            "parameters": {"preamp_gain": 10},
        },
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["connection"]["preference"] == "vcp"


def test_api_cannot_supply_resolver_physical_identity(client):
    response = client.post(
        "/api/v1/device-configs",
        json={
            "type": "pod8206hr",
            "hardware_id": "007a",
            "parameters": {"preamp_gain": 10},
            "connection": {"preference": "d2xx", "physical_id": "AB0MZ1AZ"},
        },
    )
    assert response.status_code == 422, response.get_json()


def test_from_template_keeps_driver_settings_out_of_template(client, app):
    with app.app_context():
        template = device_templates.create(
            "d2xx-eeg", {"type": "pod8206hr", "parameters": {"preamp_gain": 10}}
        )
        template_hash = template.content_hash
        template_source = device_templates.read_source(template.file_path)
    response = client.post(
        "/api/v1/device-configs/from-template",
        json={
            "template_name": "d2xx-eeg",
            "hardware_id": "006a",
            "connection": {"preference": "auto", "baudrate": 115200},
        },
    )
    assert response.status_code == 201, response.get_json()
    created = response.get_json()
    assert created["connection"]["preference"] == "auto"
    response = client.patch(
        f"/api/v1/device-configs/{created['id']}",
        json={"connection": {"preference": "d2xx"}},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["source_template_hash"] == template_hash
    with app.app_context():
        assert device_templates.read_source(template.file_path) == template_source
