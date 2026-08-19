"""Contract tests for the port-bound device config service.

Focused on plan decision C ("Physical identity", resolved 2026-07-02):
hardware_id must be exactly 5 alphanumeric characters, compared
case-sensitively and exactly (no normalization).
"""

import pytest

from app.domain.enums import DeviceType
from app.domain.errors import DeviceClaimConflict, DeviceConfigExists
from app.services.device_configs import InvalidHardwareId, claim, create, rename
from app.services import sessions as session_service

_PARAMS = {
    "preamp_gain": 10,
    "sample_rate": 2_000,
    }


def test_create_accepts_valid_five_char_alphanumeric_hardware_id(app):
    with app.app_context():
        cfg = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="001",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )

        assert cfg.id is not None
        assert cfg.hardware_id == "001"
        assert len(cfg.color) == 7
        assert cfg.color.startswith("#")


@pytest.mark.parametrize(
    "bad_hardware_id",
    [
        "", # too short
        "0123456789", # too long
        "!123" # special char
    ],
)
def test_create_rejects_hardware_id_not_matching_pattern(app, bad_hardware_id):
    with app.app_context():
        with pytest.raises(InvalidHardwareId) as exc_info:
            create(
                device_type=DeviceType.POD8206HR,
                hardware_id=bad_hardware_id,
                port="/dev/ttyUSB0",
                parameters=_PARAMS,
            )

        assert exc_info.value.hardware_id == bad_hardware_id


def test_create_exact_duplicate_identity_still_raises_device_config_exists(app):
    with app.app_context():
        create(
            device_type=DeviceType.POD8206HR,
            hardware_id="001",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )

        with pytest.raises(DeviceConfigExists):
            create(
                device_type=DeviceType.POD8206HR,
                hardware_id="001",
                port="/dev/ttyUSB1",
                parameters=_PARAMS,
            )


def test_rename_assigns_alias_by_device_identity(app):
    with app.app_context():
        config = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="003",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )

        renamed = rename(
            device_type=DeviceType.POD8206HR,
            hardware_id="003",
            nickname="Tom",
        )

        assert renamed.id == config.id
        assert renamed.nickname == "Tom"
