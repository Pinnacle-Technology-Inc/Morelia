"""Contract tests for the named session-template library (Flow 2 source).

Session templates reference device-template files by path + canonical content
hash and store the full canonical multi-sink collection (``sinks[]``) so a
template round-trips every source's sink selection through import, store, and
export.
"""

import pytest

from app import create_app
from app.database import db
from app.domain.errors import (
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    SessionTemplateNameExists,
    SessionTemplateNotFound,
)
from app.services import device_configs
from app.services.device_templates import create as create_device_template
from app.services.session_config import import_config as import_session
from app.services.session_templates import (
    create,
    create_from_session,
    delete,
    get_by_id,
    get_by_name,
    import_config,
)
from app.services.session_templates import (
    list as list_session_templates,
)

_DEVICE_CONTENT = {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}}


@pytest.fixture
def app(tmp_path):
    """Isolated app: template files land in tmp_path, never shared ``instance/``.

    Mirrors the local fixture in ``tests/test_session_config.py`` so device
    templates created here cannot collide with the tracked fixture library by
    canonical content hash.
    """
    application = create_app("testing", {"DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates")})
    with application.app_context():
        db.create_all()
    return application


# ---------------------------------------------------------------------------
# Canonical multi-sink template fixture (HANDOFF to packets 04 and 05)
#
# One source, three sinks: a file sink (csv, with a location), a service sink
# (quest, non-secret parameters), and a plot sink (nested list + scalar
# parameters). Repeated types and secret-bearing parameters are exercised by
# dedicated tests below; this fixture is the shared "happy path" collection.
# ---------------------------------------------------------------------------

_MULTI_SINKS_INPUT = [
    {
        "sink_name": "disk",
        "sink_type": "csv",
        "sink_location": "C:/data/a.csv",
    },
    {
        "sink_name": "quest-live",
        "sink_type": "quest",
        "sink_parameters": {"host": "localhost", "port": 9009, "measurement": "exp_a"},
    },
    {
        "sink_name": "browser-plot",
        "sink_type": "plot",
        "sink_parameters": {"channel_names": ["ch1", "ch2"], "chunk_samples": 128},
    },
]

# The canonical stored shape the fixture normalizes to.
EXPECTED_MULTI_SINKS = [
    {
        "sink_name": "disk",
        "sink_type": "csv",
        "sink_location": "C:/data/a.csv",
        "sink_parameters": {},
    },
    {
        "sink_name": "quest-live",
        "sink_type": "quest",
        "sink_parameters": {"host": "localhost", "port": 9009, "measurement": "exp_a"},
    },
    {
        "sink_name": "browser-plot",
        "sink_type": "plot",
        "sink_parameters": {"channel_names": ["ch1", "ch2"], "chunk_samples": 128},
    },
]


def multi_sink_template_source(template, *, nickname="bench"):
    """Return a raw session-template source dict with one multi-sink flow.

    Handoff helper for packets 04 and 05: builds a template creation payload
    referencing ``template`` by path that stores :data:`EXPECTED_MULTI_SINKS`.
    """
    flow = {
        "device_template_path": template.file_path,
        "sinks": [dict(sink) for sink in _MULTI_SINKS_INPUT],
    }
    if nickname is not None:
        flow["nickname"] = nickname
    return {"policy": "recommend", "device_flows": [flow]}


# ---------------------------------------------------------------------------
# Multi-sink storage and round trips
# ---------------------------------------------------------------------------


def test_create_persists_canonical_multi_sink_flow(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        row = create("bench-session", multi_sink_template_source(template))

        assert row.name == "bench-session"
        assert row.content["policy"] == "recommend"
        [flow] = row.content["device_flows"]
        assert flow["device_template_path"] == template.file_path
        assert flow["device_template_content_hash"] == template.content_hash
        assert flow["nickname"] == "bench"
        # Order, names, types, locations, and public parameters all preserved.
        assert flow["sinks"] == EXPECTED_MULTI_SINKS


def test_repeated_sink_types_with_unique_names_round_trip(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        row = create(
            "twin-csv",
            {
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "sinks": [
                            {"sink_name": "primary", "sink_type": "csv", "sink_location": "C:/data/p.csv"},
                            {"sink_name": "backup", "sink_type": "csv", "sink_location": "C:/data/b.csv"},
                        ],
                    }
                ]
            },
        )

        [flow] = row.content["device_flows"]
        assert [s["sink_name"] for s in flow["sinks"]] == ["primary", "backup"]
        assert [s["sink_type"] for s in flow["sinks"]] == ["csv", "csv"]
        assert flow["sinks"][0]["sink_location"] == "C:/data/p.csv"
        assert flow["sinks"][1]["sink_location"] == "C:/data/b.csv"


def test_legacy_flattened_sink_normalizes_to_sinks_list(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        row = create(
            "legacy-flat",
            {
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "nickname": "bench",
                        "sink_type": "csv",
                        "sink_location": "C:/data/out.csv",
                    }
                ]
            },
        )

        [flow] = row.content["device_flows"]
        assert "sink_type" not in flow
        assert "sink_location" not in flow
        assert flow["sinks"] == [
            {
                "sink_name": "csv",
                "sink_type": "csv",
                "sink_location": "C:/data/out.csv",
                "sink_parameters": {},
            }
        ]


def test_template_sinks_reload_into_session_creation_contract(app):
    """Loading a template yields the same ``sinks[]`` session creation accepts."""
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)
        row = create("reusable", multi_sink_template_source(template))
        [stored_flow] = row.content["device_flows"]

        session = import_session(
            {
                "name": "from-template",
                "device_flows": [
                    {
                        "device_template_path": stored_flow["device_template_path"],
                        "hardware_id": "001",
                        "port": "COM3",
                        "nickname": stored_flow["nickname"],
                        "sinks": stored_flow["sinks"],
                    }
                ],
            }
        )

        assert session.device_flows[0]["sinks"] == EXPECTED_MULTI_SINKS


# ---------------------------------------------------------------------------
# Validation: field-addressable failures before persistence
# ---------------------------------------------------------------------------


def test_duplicate_sink_name_rejected(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        with pytest.raises(InvalidSessionEntry) as exc_info:
            create(
                "dup-sink",
                {
                    "device_flows": [
                        {
                            "device_template_path": template.file_path,
                            "sinks": [
                                {"sink_name": "out", "sink_type": "csv", "sink_location": "C:/data/a.csv"},
                                {"sink_name": "out", "sink_type": "plot"},
                            ],
                        }
                    ]
                },
            )

        assert exc_info.value.field == "sinks[1].sink_name"
        assert get_by_name("dup-sink") is None


def test_secret_bearing_sink_parameter_rejected_before_persist(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        with pytest.raises(InvalidSessionEntry) as exc_info:
            create(
                "leaky",
                {
                    "device_flows": [
                        {
                            "device_template_path": template.file_path,
                            "sinks": [
                                {"sink_type": "quest", "sink_parameters": {"token": "sk-secret"}}
                            ],
                        }
                    ]
                },
            )

        assert exc_info.value.field == "sinks[0].sink_parameters.token"
        # A rejected secret never reaches storage.
        assert get_by_name("leaky") is None


def test_influx_api_token_env_reference_persists(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        row = create(
            "influx-ref",
            {
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "sinks": [
                            {"sink_type": "influx", "sink_parameters": {"api_token_env": "INFLUX_TOKEN"}}
                        ],
                    }
                ]
            },
        )

        [flow] = row.content["device_flows"]
        assert flow["sinks"][0]["sink_parameters"] == {"api_token_env": "INFLUX_TOKEN"}


def test_mixing_flattened_and_sinks_list_rejected(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        with pytest.raises(InvalidSessionEntry) as exc_info:
            create(
                "mixed",
                {
                    "device_flows": [
                        {
                            "device_template_path": template.file_path,
                            "sink_type": "csv",
                            "sinks": [{"sink_type": "csv"}],
                        }
                    ]
                },
            )

        assert exc_info.value.field == "sinks"


def test_create_rejects_flow_without_any_sink(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        with pytest.raises(InvalidSessionEntry) as exc_info:
            create(
                "no-sink",
                {"device_flows": [{"device_template_path": template.file_path}]},
            )

        assert exc_info.value.field == "sinks"


def test_create_rejects_unknown_flow_field(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)

        with pytest.raises(InvalidSessionEntry):
            create(
                "bad-field",
                {
                    "device_flows": [
                        {
                            "device_template_path": template.file_path,
                            "sink_type": "csv",
                            "bogus": "nope",
                        }
                    ]
                },
            )


def test_create_rejects_empty_device_flows(app):
    with app.app_context():
        with pytest.raises(ValueError):
            create("empty", {"device_flows": []})


def test_create_rejects_unknown_device_template_path(app):
    with app.app_context():
        with pytest.raises(DeviceTemplateNotFound):
            create(
                "missing-ref",
                {
                    "device_flows": [
                        {"device_template_path": "device-templates/ghost.toml", "sink_type": "csv"}
                    ]
                },
            )


def test_create_rejects_duplicate_name_with_different_content(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)
        create("dup2", multi_sink_template_source(template))

        # Same name, different content (a single csv sink) conflicts. An
        # identical body is idempotent and returns the existing row instead.
        with pytest.raises(SessionTemplateNameExists):
            create(
                "dup2",
                {
                    "device_flows": [
                        {
                            "device_template_path": template.file_path,
                            "sinks": [{"sink_type": "csv", "sink_location": "C:/data/only.csv"}],
                        }
                    ]
                },
            )


def test_delete_removes_row(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)
        create("gone-soon", multi_sink_template_source(template))

        delete("gone-soon")

        assert get_by_name("gone-soon") is None
        with pytest.raises(SessionTemplateNotFound):
            delete("gone-soon")


def test_import_config_reads_name_from_source(app):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)
        source = multi_sink_template_source(template)
        source["name"] = "imported"

        row = import_config(source)

        assert row.name == "imported"
        assert row.content["device_flows"][0]["sinks"] == EXPECTED_MULTI_SINKS


# ---------------------------------------------------------------------------
# Snapshot-copy from a live session preserves the whole sink collection
# ---------------------------------------------------------------------------


def test_create_from_session_preserves_multi_sink_collection(app):
    with app.app_context():
        create_device_template("bench-rig", _DEVICE_CONTENT)
        session = import_session(
            {
                "name": "live-session",
                "policy": "recommend",
                "device_flows": [
                    {
                        "device_template_path": "bench-rig.toml",
                        "hardware_id": "001",
                        "port": "COM3",
                        "nickname": "bench",
                        "sinks": [dict(sink) for sink in _MULTI_SINKS_INPUT],
                    }
                ],
            }
        )

        row = create_from_session(session, "from-live-session")

        [flow] = row.content["device_flows"]
        assert flow["nickname"] == "bench"
        assert "hardware_id" not in flow
        assert flow["sinks"] == EXPECTED_MULTI_SINKS


def test_create_from_session_include_hardware_id_records_binding(app):
    with app.app_context():
        create_device_template("bench-rig", _DEVICE_CONTENT)
        session = import_session(
            {
                "name": "bound",
                "device_flows": [
                    {
                        "device_template_path": "bench-rig.toml",
                        "hardware_id": "001",
                        "port": "COM3",
                        "sinks": [{"sink_type": "csv", "sink_location": "C:/data/out.csv"}],
                    }
                ],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]
        expected_hardware_id = device_configs.get_by_id(config_id).hardware_id

        row = create_from_session(session, "bound-template", include_hardware_id=True)

        [flow] = row.content["device_flows"]
        assert flow["hardware_id"] == expected_hardware_id
        assert flow["sinks"][0]["sink_name"] == "csv"
