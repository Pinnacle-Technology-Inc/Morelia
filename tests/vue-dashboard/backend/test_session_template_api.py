"""HTTP round-trip tests for the session-template resource.

Templates reference device templates by path + content hash and carry the full
canonical ``sinks[]`` collection through the API create/list/get/export routes.
"""

import pytest

from app import create_app
from app.database import db

API = "/api/v1/session-templates"
DEVICE_TEMPLATES_API = "/api/v1/device-templates"
SESSIONS_API = "/api/v1/sessions/"

_DEVICE_CONTENT = {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}}

_MULTI_SINKS_INPUT = [
    {"sink_name": "disk", "sink_type": "csv", "sink_location": "C:/data/a.csv"},
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

_EXPECTED_MULTI_SINKS = [
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


@pytest.fixture
def app(tmp_path):
    """Isolated app so device-template files never touch shared ``instance/``."""
    application = create_app("testing", {"DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates")})
    with application.app_context():
        db.create_all()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _create_device_template(client, name="bench-rig"):
    response = client.post(DEVICE_TEMPLATES_API, json={"name": name, **_DEVICE_CONTENT})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_post_creates_multi_sink_template_and_get_routes_return_it(client):
    template = _create_device_template(client)

    created = client.post(
        API,
        json={
            "name": "bench-session",
            "device_flows": [
                {
                    "device_template_path": template["file_path"],
                    "nickname": "bench",
                    "sinks": _MULTI_SINKS_INPUT,
                }
            ],
        },
    )

    assert created.status_code == 201, created.get_json()
    body = created.get_json()
    assert body["name"] == "bench-session"
    assert body["content"]["policy"] == "recommend"
    flow = body["content"]["device_flows"][0]
    assert flow["device_template_path"] == template["file_path"]
    assert flow["device_template_content_hash"] == template["content_hash"]
    assert flow["sinks"] == _EXPECTED_MULTI_SINKS

    listed = client.get(API)
    assert listed.status_code == 200
    assert [row["name"] for row in listed.get_json()] == ["bench-session"]

    shown = client.get(f"{API}/bench-session")
    assert shown.status_code == 200
    assert shown.get_json()["content"] == body["content"]


def test_post_legacy_flattened_sink_normalizes_to_sinks_list(client):
    template = _create_device_template(client)

    created = client.post(
        API,
        json={
            "name": "legacy",
            "device_flows": [
                {
                    "device_template_path": template["file_path"],
                    "sink_type": "csv",
                    "sink_location": "C:/data/out.csv",
                }
            ],
        },
    )

    assert created.status_code == 201, created.get_json()
    flow = created.get_json()["content"]["device_flows"][0]
    assert flow["sinks"] == [
        {
            "sink_name": "csv",
            "sink_type": "csv",
            "sink_location": "C:/data/out.csv",
            "sink_parameters": {},
        }
    ]


def test_post_secret_bearing_sink_returns_422(client):
    template = _create_device_template(client)

    response = client.post(
        API,
        json={
            "name": "leaky",
            "device_flows": [
                {
                    "device_template_path": template["file_path"],
                    "sinks": [{"sink_type": "quest", "sink_parameters": {"token": "sk-secret"}}],
                }
            ],
        },
    )

    assert response.status_code == 422, response.get_json()
    assert response.get_json()["code"] == "invalid_session_template"
    # Rejected before persistence.
    assert client.get(f"{API}/leaky").status_code == 404


def test_get_unknown_session_template_returns_404_problem_json(client):
    response = client.get(f"{API}/missing")

    assert response.status_code == 404
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "session_template_not_found"


def test_post_duplicate_name_returns_409_problem_json(client):
    template = _create_device_template(client)
    first = client.post(
        API,
        json={
            "name": "dup",
            "device_flows": [
                {"device_template_path": template["file_path"], "sinks": [{"sink_type": "csv"}]}
            ],
        },
    )
    assert first.status_code == 201, first.get_json()

    # Same name, different content conflicts (an identical body is idempotent).
    second = client.post(
        API,
        json={
            "name": "dup",
            "device_flows": [
                {
                    "device_template_path": template["file_path"],
                    "sinks": [{"sink_type": "csv", "sink_location": "C:/data/other.csv"}],
                }
            ],
        },
    )

    assert second.status_code == 409
    assert second.get_json()["code"] == "session_template_name_exists"


def test_post_unknown_device_template_path_returns_404_problem_json(client):
    response = client.post(
        API,
        json={
            "name": "bad-ref",
            "device_flows": [
                {"device_template_path": "device-templates/ghost.toml", "sinks": [{"sink_type": "csv"}]}
            ],
        },
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "device_template_not_found"


def test_delete_removes_session_template(client):
    template = _create_device_template(client)
    client.post(
        API,
        json={
            "name": "gone-soon",
            "device_flows": [
                {"device_template_path": template["file_path"], "sinks": [{"sink_type": "csv"}]}
            ],
        },
    )

    deleted = client.delete(f"{API}/gone-soon")
    assert deleted.status_code == 204

    assert client.get(f"{API}/gone-soon").status_code == 404


def test_session_template_export_route_snapshot_copies_multi_sink_session(client):
    _create_device_template(client)
    session = client.post(
        SESSIONS_API,
        json={
            "name": "export-me",
            "device_flows": [
                {
                    "device_template_path": "bench-rig.toml",
                    "hardware_id": "8206A",
                    "port": "COM3",
                    "nickname": "bench",
                    "sinks": _MULTI_SINKS_INPUT,
                }
            ],
        },
    )
    assert session.status_code == 201, session.get_json()
    session_id = session.get_json()["id"]

    exported = client.post(
        f"{SESSIONS_API}{session_id}/template-export",
        json={"name": "exported-template"},
    )

    assert exported.status_code == 201, exported.get_json()
    body = exported.get_json()
    assert body["name"] == "exported-template"
    [flow] = body["content"]["device_flows"]
    assert flow["nickname"] == "bench"
    assert flow["sinks"] == _EXPECTED_MULTI_SINKS

    shown = client.get(f"{API}/exported-template")
    assert shown.status_code == 200
    assert shown.get_json()["content"]["device_flows"][0]["sinks"] == _EXPECTED_MULTI_SINKS
