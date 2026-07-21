import pytest

from app.domain.enums import DeviceType
from app.domain.errors import InvalidSessionEntry
from app.services import device_configs, session_config


def test_session_config_rejects_same_physical_device_twice(app):
    with app.app_context():
        config = device_configs.create(
            device_type=DeviceType.POD8206HR,
            hardware_id="A1B2C",
            port="COM1",
            parameters={"preamp_gain": 10},
        )
        source = {
            "device_flows": [
                {"device_config_id": config.id, "sink_type": "csv"},
                {"device_config_id": config.id, "sink_type": "csv"},
            ]
        }

        with pytest.raises(InvalidSessionEntry, match="appears more than once"):
            session_config._canonicalize(source)
