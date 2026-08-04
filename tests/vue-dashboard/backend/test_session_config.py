"""Contract tests for session-config import/export and entry validation."""

import json
import tomllib

import pytest

from app import create_app
from app.database import db
from app.domain.enums import DeviceType
from app.domain.errors import DeviceTemplateNotFound, InvalidSessionEntry
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.services import device_templates
from app.services.device_configs import create as create_device_config
from app.services.device_configs import get_by_id as get_device_config_by_id
from app.services.device_templates import create as create_device_template
from app.services.session_config import (
    export,
    import_config,
    validate_entry,
)

_DEVICE_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": 10, "sample_rate": "2000"},
}


@pytest.fixture
def app(tmp_path):
    """Override conftest's shared ``app`` fixture with an isolated template dir.

    Without this, device-template creation/lookup here shares the real
    ``instance/device-templates`` library, which can collide with tracked
    fixture templates by canonical content hash (see ``bench-rig.toml``).
    """
    application = create_app("testing", {"DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates")})
    with application.app_context():
        db.create_all()
    return application


def _create_device_templates() -> None:
    create_device_template("pod-high", _DEVICE_CONTENT)
    create_device_template(
        "pod-low",
        {"type": "pod8206hr", "parameters": {"preamp_gain": 100}},
    )


# ---------------------------------------------------------------------------
# Device-template resolution (unchanged binding behavior, new sinks[] shape)
# ---------------------------------------------------------------------------


def test_import_session_template_resolves_device_template_path_to_device_config(app):
    with app.app_context():
        template = create_device_template("pod-high", _DEVICE_CONTENT)

        session = import_config(
            {
                "name": "Path reference",
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "hardware_id": "8206A",
                        "port": "COM3",
                        "sink_type": "csv",
                        "sink_location": "C:/data/high.csv",
                    }
                ],
            }
        )

        assert set(session.device_flows[0]) == {
            "device_config_id",
            "nickname",
            "sinks",
        }
        assert session.device_flows[0]["sinks"] == [
            {
                "sink_name": "csv",
                "sink_type": "csv",
                "sink_location": "C:/data/high.csv",
                "sink_parameters": {},
            }
        ]
        config = get_device_config_by_id(session.device_flows[0]["device_config_id"])
        assert config is not None
        assert config.hardware_id == "8206A"
        assert config.port == "COM3"
        assert config.source_template == template.file_path


def test_import_session_template_resolves_device_template_content_hash(app):
    with app.app_context():
        template = create_device_template("pod-high", _DEVICE_CONTENT)

        session = import_config(
            {
                "name": "Content-hash reference",
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "device_template_content_hash": template.content_hash,
                        "hardware_id": "8206B",
                        "port": "COM4",
                        "sink_type": "csv",
                    }
                ],
            }
        )

        config = get_device_config_by_id(session.device_flows[0]["device_config_id"])
        assert config is not None
        assert config.source_template == template.file_path
        assert session.device_flows[0] == {
            "device_config_id": config.id,
            "nickname": template.file_path,
            "sinks": [{"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}}],
        }


def test_validate_entry_seeds_nickname_and_validates_sink(app):
    with app.app_context():
        _create_device_templates()

        entry = validate_entry(
            {
                "hardware_id": "8206A",
                "port": "COM3",
                "device_template_path": "pod-high.toml",
                "sink_type": "csv",
            }
        )

        config = get_device_config_by_id(entry["device_config_id"])
        assert config is not None
        assert config.hardware_id == "8206A"
        assert entry == {
            "device_config_id": config.id,
            "nickname": "device-templates/pod-high.toml",
            "sinks": [{"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}}],
        }


# ---------------------------------------------------------------------------
# Legacy flattened normalization
# ---------------------------------------------------------------------------


def test_legacy_flattened_normalizes_to_single_named_sink(app):
    with app.app_context():
        _create_device_templates()

        entry = validate_entry(
            {
                "hardware_id": "8206A",
                "port": "COM3",
                "device_template_path": "pod-high.toml",
                "sink_type": "csv",
                "sink_location": "C:/data/x.csv",
            }
        )

        assert entry["sinks"] == [
            {
                "sink_name": "csv",
                "sink_type": "csv",
                "sink_location": "C:/data/x.csv",
                "sink_parameters": {},
            }
        ]


def test_import_toml_persists_session_device_flows(app):
    toml_source = """\
name = "Calibration run"
policy = "automate"

[[device_flows]]
hardware_id = "8206A"
port = "COM3"
device_template_path = "pod-high.toml"
sink_type = "csv"
sink_location = "C:/data/high.csv"

[[device_flows]]
nickname = "left pod"
hardware_id = "8206B"
port = "COM4"
device_template_path = "pod-low.toml"
sink_type = "csv"
"""
    with app.app_context():
        _create_device_templates()

        session = import_config(toml_source, format="toml")

        assert session.name == "Calibration run"
        assert session.policy.value == "automate"
        assert session.device_flows[0]["nickname"] == "device-templates/pod-high.toml"
        assert session.device_flows[0]["sinks"] == [
            {
                "sink_name": "csv",
                "sink_type": "csv",
                "sink_location": "C:/data/high.csv",
                "sink_parameters": {},
            }
        ]
        assert session.device_flows[1]["nickname"] == "left pod"
        assert session.device_flows[1]["sinks"] == [
            {"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}}
        ]
        first = get_device_config_by_id(session.device_flows[0]["device_config_id"])
        second = get_device_config_by_id(session.device_flows[1]["device_config_id"])
        assert first is not None
        assert second is not None
        assert first.hardware_id == "8206A"
        assert first.port == "COM3"
        assert second.hardware_id == "8206B"
        assert second.port == "COM4"


def test_mixing_flattened_and_sinks_list_rejected(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            validate_entry(
                {
                    "hardware_id": "8206A",
                    "port": "COM3",
                    "device_template_path": "pod-high.toml",
                    "sink_type": "csv",
                    "sinks": [{"sink_type": "csv"}],
                }
            )

        assert exc_info.value.field == "sinks"
        assert "cannot combine" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Nested multi-sink round trips
# ---------------------------------------------------------------------------


def _multi_sink_source() -> dict:
    return {
        "name": "Multi",
        "device_flows": [
            {
                "hardware_id": "8206A",
                "port": "COM3",
                "device_template_path": "pod-high.toml",
                "sinks": [
                    {
                        "sink_name": "disk",
                        "sink_type": "csv",
                        "sink_location": "C:/data/a.csv",
                    },
                    {
                        "sink_name": "quest-live",
                        "sink_type": "quest",
                        "sink_parameters": {
                            "host": "localhost",
                            "port": 9009,
                            "measurement": "exp_a",
                        },
                    },
                    {
                        "sink_name": "browser-plot",
                        "sink_type": "plot",
                        "sink_parameters": {
                            "channel_names": ["ch1", "ch2"],
                            "chunk_samples": 128,
                        },
                    },
                ],
            }
        ],
    }


def test_import_multi_sink_preserves_order_and_parameters(app):
    with app.app_context():
        _create_device_templates()

        session = import_config(_multi_sink_source())
        sinks = session.device_flows[0]["sinks"]

        assert [s["sink_name"] for s in sinks] == ["disk", "quest-live", "browser-plot"]
        assert sinks[0] == {
            "sink_name": "disk",
            "sink_type": "csv",
            "sink_location": "C:/data/a.csv",
            "sink_parameters": {},
        }
        assert sinks[1]["sink_type"] == "quest"
        assert sinks[1]["sink_parameters"] == {
            "host": "localhost",
            "port": 9009,
            "measurement": "exp_a",
        }
        assert sinks[2]["sink_parameters"] == {
            "channel_names": ["ch1", "ch2"],
            "chunk_samples": 128,
        }


def test_export_json_multi_sink_round_trips(app):
    with app.app_context():
        _create_device_templates()
        session = import_config(_multi_sink_source())

        artifact = json.loads(export(session, format="json"))
        flow = artifact["device_flows"][0]

        assert [s["sink_name"] for s in flow["sinks"]] == [
            "disk",
            "quest-live",
            "browser-plot",
        ]
        assert flow["sinks"][0]["sink_location"] == "C:/data/a.csv"
        assert flow["sinks"][1]["sink_parameters"] == {
            "host": "localhost",
            "port": 9009,
            "measurement": "exp_a",
        }
        assert flow["sinks"][2]["sink_parameters"] == {
            "channel_names": ["ch1", "ch2"],
            "chunk_samples": 128,
        }


def test_export_toml_multi_sink_round_trips(app):
    with app.app_context():
        _create_device_templates()
        session = import_config(_multi_sink_source())

        toml_text = export(session, format="toml")
        reparsed = tomllib.loads(toml_text)
        flow = reparsed["device_flows"][0]

        assert [s["sink_name"] for s in flow["sinks"]] == [
            "disk",
            "quest-live",
            "browser-plot",
        ]
        assert flow["sinks"][0]["sink_location"] == "C:/data/a.csv"
        assert flow["sinks"][1]["sink_type"] == "quest"
        assert flow["sinks"][1]["sink_parameters"] == {
            "host": "localhost",
            "port": 9009,
            "measurement": "exp_a",
        }
        assert flow["sinks"][2]["sink_parameters"] == {
            "channel_names": ["ch1", "ch2"],
            "chunk_samples": 128,
        }


# ---------------------------------------------------------------------------
# Field-addressable validation failures
# ---------------------------------------------------------------------------


def _flow_with_sinks(app, sinks: list[dict]):
    return validate_entry(
        {
            "hardware_id": "8206A",
            "port": "COM3",
            "device_template_path": "pod-high.toml",
            "sinks": sinks,
        }
    )


def test_empty_sinks_rejected(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(app, [])

        assert exc_info.value.field == "sinks"


def test_duplicate_sink_name_rejected(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(
                app,
                [
                    {"sink_name": "out", "sink_type": "csv"},
                    {"sink_name": "out", "sink_type": "plot"},
                ],
            )

        assert exc_info.value.field == "sinks[1].sink_name"
        assert "duplicate" in str(exc_info.value)


def test_repeated_default_sink_names_rejected(app):
    with app.app_context():
        _create_device_templates()

        # Two csv sinks without explicit names both default to "csv".
        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(app, [{"sink_type": "csv"}, {"sink_type": "csv"}])

        assert exc_info.value.field == "sinks[1].sink_name"


def test_location_on_service_sink_rejected(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(
                app,
                [{"sink_type": "quest", "sink_location": "C:/data/x.csv"}],
            )

        assert exc_info.value.field == "sinks[0].sink_location"
        assert "file sinks" in str(exc_info.value)


def test_unknown_sink_field_rejected(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(app, [{"sink_type": "csv", "bogus": 1}])

        assert exc_info.value.field == "sinks[0]"
        assert "unknown sink field" in str(exc_info.value)


def test_unknown_sink_type_rejected(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(app, [{"sink_type": "parquet"}])

        assert exc_info.value.field == "sinks[0].sink_type"


def test_secret_sink_parameter_rejected_without_exposing_value(app):
    with app.app_context():
        _create_device_templates()

        secret = "s3cr3t-inline-token-value"
        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(
                app,
                [{"sink_type": "quest", "sink_parameters": {"token": secret}}],
            )

        assert exc_info.value.field == "sinks[0].sink_parameters.token"
        assert secret not in str(exc_info.value)


def test_file_path_parameter_rejected_in_favor_of_sink_location(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            _flow_with_sinks(
                app,
                [{"sink_type": "csv", "sink_parameters": {"file_path": "C:/data/y.csv"}}],
            )

        assert exc_info.value.field == "sinks[0].sink_parameters"
        assert "sink_location" in str(exc_info.value)


def test_influx_api_token_env_reference_allowed(app):
    with app.app_context():
        _create_device_templates()

        entry = _flow_with_sinks(
            app,
            [{"sink_type": "influx", "sink_parameters": {"api_token_env": "INFLUX_TOKEN"}}],
        )

        assert entry["sinks"][0]["sink_parameters"] == {"api_token_env": "INFLUX_TOKEN"}


# ---------------------------------------------------------------------------
# Existing import/export guarantees
# ---------------------------------------------------------------------------


def test_import_unknown_device_template_writes_no_session(app):
    with app.app_context():
        with pytest.raises(DeviceTemplateNotFound) as exc_info:
            import_config(
                {
                    "name": "bad reference",
                    "device_flows": [
                        {
                            "hardware_id": "8206A",
                            "port": "COM3",
                            "device_template_path": "missing",
                            "sink_type": "csv",
                        }
                    ],
                }
            )

        assert exc_info.value.name == "missing"
        count = db.session.scalar(db.select(db.func.count()).select_from(Session))
        assert count == 0


def test_import_old_device_config_key_fails_clear_hard_rename(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry) as exc_info:
            import_config(
                {
                    "name": "old key",
                    "device_flows": [
                        {
                            "hardware_id": "8206A",
                            "port": "COM3",
                            "device_config": "pod-high",
                            "sink_type": "csv",
                        }
                    ],
                }
            )

        assert exc_info.value.field == "device_config"
        assert "unknown field" in str(exc_info.value)


def test_import_bad_sink_type_writes_no_session(app):
    with app.app_context():
        _create_device_templates()

        with pytest.raises(InvalidSessionEntry, match="sink_type"):
            import_config(
                {
                    "name": "bad sink",
                    "device_flows": [
                        {
                            "hardware_id": "8206A",
                            "port": "COM3",
                            "device_template_path": "pod-high.toml",
                            "sink_type": "parquet",
                        }
                    ],
                }
            )

        count = db.session.scalar(db.select(db.func.count()).select_from(Session))
        assert count == 0


def test_export_creates_default_named_template_for_custom_device_config(app):
    with app.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="CUST1",
            port="COM9",
            parameters={"preamp_gain": 10, "sample_rate": "2000"},
        )
        session = SessionRepository().create(
            {
                "name": "Morning HR Trial",
                "device_flows": [
                    {
                        "device_config_id": config.id,
                        "nickname": "left arm",
                        "sink_type": "csv",
                    }
                ],
            }
        )

        artifact = json.loads(export(session, format="json"))

        template_path = artifact["device_flows"][0]["device_template_path"]
        template = device_templates.get_by_path(template_path)
        assert template is not None
        assert template.name.startswith("pod8206hr-morning-hr-trial-left-arm-")
        assert artifact["device_flows"][0]["sinks"] == [
            {"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}}
        ]
        assert "device_config_id" not in artifact["device_flows"][0]
        assert "hardware_id" not in artifact["device_flows"][0]
        assert "port" not in artifact["device_flows"][0]

        assert template.content == {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10, "sample_rate": 2000},
        }


def test_export_reuses_matching_stored_template_for_unlinked_device_config(app):
    with app.app_context():
        stored = create_device_template("pod-high", _DEVICE_CONTENT)
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="CUST1",
            port="COM9",
            parameters=_DEVICE_CONTENT["parameters"],
        )
        session = SessionRepository().create(
            {
                "name": "Morning HR Trial",
                "device_flows": [
                    {
                        "device_config_id": config.id,
                        "nickname": "left arm",
                        "sink_type": "csv",
                    }
                ],
            }
        )

        artifact = json.loads(export(session, format="json"))

        assert artifact["device_flows"][0]["device_template_path"] == stored.file_path
        assert device_templates.list() == [stored]


def test_export_reuses_device_template_by_canonical_content_hash(app):
    with app.app_context():
        stored = create_device_template("pod-high", _DEVICE_CONTENT)
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="CUST2",
            port="COM10",
            parameters={"preamp_gain": 10, "sample_rate": 2000},
        )
        session = SessionRepository().create(
            {
                "name": "Canonical Hash Trial",
                "device_flows": [{"device_config_id": config.id, "sink_type": "csv"}],
            }
        )
        before_paths = {template.file_path for template in device_templates.list()}

        artifact = json.loads(export(session, format="json"))
        flow = artifact["device_flows"][0]
        after_templates = device_templates.list()

        assert flow["device_template_path"] in {
            template.file_path
            for template in after_templates
            if template.content_hash == stored.content_hash
        }
        assert flow["device_template_content_hash"] == stored.content_hash
        assert {template.file_path for template in after_templates} == before_paths


def test_import_and_export_json(app):
    with app.app_context():
        _create_device_templates()
        template = device_templates.get_by_name("pod-high")
        session = import_config(
            json.dumps(
                {
                    "name": "JSON run",
                    "device_flows": [
                        {
                            "hardware_id": "8206A",
                            "port": "COM3",
                            "device_template_path": template.file_path,
                            "sink_type": "csv",
                        }
                    ],
                }
            ),
            format="json",
        )

        artifact = json.loads(export(session, format="json"))
        assert artifact["name"] == "JSON run"
        assert artifact["policy"] == "recommend"
        assert artifact["device_flows"] == [
            {
                "nickname": template.file_path,
                "device_template_path": template.file_path,
                "device_template_content_hash": template.content_hash,
                "sinks": [{"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}}],
            }
        ]
