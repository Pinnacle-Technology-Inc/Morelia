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

_PARAMS = {"preamp_gain": 10}


def test_create_accepts_valid_five_char_alphanumeric_hardware_id(app):
    with app.app_context():
        cfg = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="a1B2c",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )

        assert cfg.id is not None
        assert cfg.hardware_id == "a1B2c"
        assert len(cfg.color) == 7
        assert cfg.color.startswith("#")


@pytest.mark.parametrize(
    "bad_hardware_id",
    [
        "a1B",         # too short (3 characters)
        "a1B2c3D4E",   # too long (9 characters)
        "a1B2!",       # non-alphanumeric
        "a1 B2",       # contains a space
        "a1_B2",       # contains an underscore
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


def test_create_hardware_id_comparison_is_case_sensitive_not_folded(app):
    # Only DeviceType.POD8206HR has a pinned parameter schema in the registry
    # today (app/services/registry.py), so both configs use that type here;
    # what's under test is that "aBcDe" and "abcde" are stored/compared as
    # distinct values rather than being case-folded into a collision.
    with app.app_context():
        upper_mixed = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="aBcDe",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )
        lower = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="abcde",
            port="/dev/ttyUSB1",
            parameters=_PARAMS,
        )

        assert upper_mixed.hardware_id == "aBcDe"
        assert lower.hardware_id == "abcde"
        assert upper_mixed.id != lower.id


def test_create_exact_duplicate_identity_still_raises_device_config_exists(app):
    with app.app_context():
        create(
            device_type=DeviceType.POD8206HR,
            hardware_id="a1B2c",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )

        with pytest.raises(DeviceConfigExists):
            create(
                device_type=DeviceType.POD8206HR,
                hardware_id="a1B2c",
                port="/dev/ttyUSB1",
                parameters=_PARAMS,
            )


def test_rename_assigns_alias_by_device_identity(app):
    with app.app_context():
        config = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="NAM01",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )

        renamed = rename(
            device_type=DeviceType.POD8206HR,
            hardware_id="NAM01",
            nickname="Tom",
        )

        assert renamed.id == config.id
        assert renamed.nickname == "Tom"


def test_claim_conflict_is_typed_and_force_steals_existing_claim(app):
    with app.app_context():
        cfg = create(
            device_type=DeviceType.POD8206HR,
            hardware_id="CLM01",
            port="/dev/ttyUSB0",
            parameters=_PARAMS,
        )
        first_session = session_service.create({"name": "first holder"})
        second_session = session_service.create({"name": "second holder"})

        first = claim(cfg.id, first_session.id)
        same_session = claim(cfg.id, first_session.id)
        with pytest.raises(DeviceClaimConflict) as exc_info:
            claim(cfg.id, second_session.id)

        stolen = claim(cfg.id, second_session.id, force=True)

        assert same_session.id == first.id
        assert exc_info.value.config_id == cfg.id
        assert exc_info.value.claimed_session_id == first_session.id
        assert exc_info.value.details == {
            "device_config_id": cfg.id,
            "claimed_session_id": first_session.id,
        }
        assert stolen.claimed_session_id == second_session.id
