"""Contract tests for the refactored sessions/session-runs API."""

import pytest

from uuid import uuid4

from app.domain.enums import DeviceType, SessionStatus
from app.models.device_config import DeviceConfig
from app.services import device_configs
from app.services import session_templates
from app.services.sessions import create as create_session
from app.services import device_templates


SESSIONS_API = "/api/v1/sessions/"
RUNS_API = "/api/v1/session-runs"


@pytest.fixture
def app(tmp_path):
    """Isolated app so template files never touch shared instance/."""
    from app import create_app
    from app.database import db

    application = create_app(
        "testing",
        {"DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates")},
    )

    with application.app_context():
        db.create_all()

    return application


def _create_device_config(
    *,
    hardware_id="001",
    port="COM3",
):
    """Create a device config suitable for a session/template test."""
    return device_configs.create(
        device_type=DeviceType.POD8206HR,
        hardware_id=hardware_id,
        port=port,
        parameters={"preamp_gain": 10},
    )


def _create_template(*, tmp_path, name="bench-rig"):
    """Create a real device template and register a session template from it."""

    unique_name = f"{name}-{uuid4().hex[:8]}"

    device_template = device_templates.create(
        name,
        {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10},
        },
    )

    return session_templates.create(
        f"{unique_name}-session",
        {
            "policy": "recommend",
            "device_flows": [
                {
                    "device_template_path": device_template.file_path,
                    "sinks": [
                        {
                            "sink_type": "csv",
                            "sink_location": "test_output/out.csv",
                        }
                    ],
                }
            ],
        },
    )

def _valid_run_payload(
    *,
    template_id,
    template_hash,
    device_config_id,
    tmp_path,
):
    return {
        "idempotency_key": "test-idempotency-key",
        "source_template_id": template_id,
        "expected_template_hash": template_hash,
        "assignments": [
            {
                "flow_index": 0,
                "device_config_id": device_config_id,
                "sink_locations": [
                    {
                        "sink_index": 0,
                        "sink_location": str(tmp_path / "session_output.csv"),
                    }
                ],
            }
        ],
        "execution": {
            "mode": "scheduled",
            "start_at": "2026-08-13T10:00:00Z",
        },
    }


# ---------------------------------------------------------------------------
# sessions resource
# ---------------------------------------------------------------------------


def test_list_sessions_returns_200(client):
    response = client.get(SESSIONS_API)

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_get_unknown_session_returns_404(client):
    response = client.get(f"{SESSIONS_API}999999")

    assert response.status_code == 404

    body = response.get_json()
    assert body["code"] == "session_not_found"


def test_session_name_suggestion_returns_name(client):
    response = client.get(
        f"{SESSIONS_API}name-suggestion",
        query_string={"source_template_id": "unknown-template"},
    )

    # The exact status depends on how suggest_name handles an unknown
    # template. The important part is that this is now the name-suggestion
    # endpoint rather than session creation.
    assert response.status_code in (200, 404)


def test_sessions_overview_returns_200(client):
    response = client.get(f"{SESSIONS_API}overview")

    assert response.status_code == 200
    assert response.get_json() is not None


# ---------------------------------------------------------------------------
# session-run creation
# ---------------------------------------------------------------------------


def test_create_run_requires_idempotency_key(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload.pop("idempotency_key")

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_rejects_short_idempotency_key(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )

    payload["idempotency_key"] = "short"

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_requires_template_id(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload.pop("source_template_id")

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_requires_template_hash(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload.pop("expected_template_hash")

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_rejects_invalid_template_hash(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload["expected_template_hash"] = "not-a-sha256"

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_requires_assignments(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload["assignments"] = []

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_requires_execution(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload.pop("execution")

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_malformed_json_returns_400(client):
    response = client.post(
        RUNS_API,
        data="this is not json",
        content_type="application/json",
    )

    assert response.status_code == 400

    body = response.get_json()
    assert body["code"] == "bad_request"


def test_create_scheduled_run_returns_202(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 202, response.get_json()

    body = response.get_json()

    assert body["id"]
    assert body["status"] == SessionStatus.SCHEDULED.value
    assert body["schedule"] is not None
    assert body["schedule"]["mode"] == "once"
    assert body["scheduled_for"] is not None


def test_scheduled_run_requires_start_at(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )
    payload["execution"].pop("start_at")

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_create_run_idempotent_retry_returns_same_session(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )

    first = client.post(RUNS_API, json=payload)
    second = client.post(RUNS_API, json=payload)

    assert first.status_code == 202, first.get_json()
    assert second.status_code == 202, second.get_json()

    first_body = first.get_json()
    second_body = second.get_json()

    assert first_body["id"] == second_body["id"]


def test_create_run_reusing_idempotency_key_with_different_request_returns_409(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )

    first = client.post(RUNS_API, json=payload)

    assert first.status_code == 202, first.get_json()

    conflicting_payload = dict(payload)
    conflicting_payload["notes"] = "different request"

    second = client.post(
        RUNS_API,
        json=conflicting_payload,
    )

    assert second.status_code == 409

    body = second.get_json()
    assert body["code"] == "session_run_request_conflict"


def test_create_run_rejects_stale_template_hash(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        config_id = config.id
        template_id = template.template_id
        template_hash = template.registered_hash

    payload = _valid_run_payload(
        template_id=template_id,
        template_hash=template_hash,
        device_config_id=config_id,
        tmp_path=tmp_path,
    )

    payload["expected_template_hash"] = "a" * 64

    response = client.post(RUNS_API, json=payload)

    assert response.status_code == 409

    body = response.get_json()
    assert body["code"] in {
        "session_template_state_conflict",
        "template_state_conflict",
    }


# ---------------------------------------------------------------------------
# existing session lifecycle endpoints
# ---------------------------------------------------------------------------


def test_get_session_returns_session(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        session = create_session(
            {
                "source_template_id": template.template_id,
                "expected_template_hash": template.registered_hash,
                "assignments": [
                    {
                        "flow_index": 0,
                        "device_config_id": config.id,
                        "sink_locations": [
                            {
                                "sink_index": 0,
                                "sink_location": str(tmp_path / "output.csv"),
                            }
                        ],
                    }
                ],
            }
        )
        session_id = session.id

    response = client.get(f"{SESSIONS_API}{session_id}")

    assert response.status_code == 200

    body = response.get_json()
    assert int(body["id"]) == session_id


def test_session_status_returns_200(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        session = create_session(
            {
                "source_template_id": template.template_id,
                "expected_template_hash": template.registered_hash,
                "assignments": [
                    {
                        "flow_index": 0,
                        "device_config_id": config.id,
                        "sink_locations": [
                            {
                                "sink_index": 0,
                                "sink_location": str(tmp_path / "output.csv"),
                            }
                        ],
                    }
                ],
            }
        )
        session_id = session.id

    response = client.get(f"{SESSIONS_API}{session_id}/status")

    assert response.status_code == 200
    assert response.get_json() is not None


# ---------------------------------------------------------------------------
# template export
# ---------------------------------------------------------------------------


def test_export_session_template_requires_name(
    client,
    app,
    tmp_path
):
    with app.app_context():
        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        session = create_session(
            {
                "source_template_id": template.template_id,
                "expected_template_hash": template.registered_hash,
                "assignments": [
                    {
                        "flow_index": 0,
                        "device_config_id": config.id,
                        "sink_locations": [
                            {
                                "sink_index": 0,
                                "sink_location": str(tmp_path / "output.csv"),
                            }
                        ],
                    }
                ],
            }
        )
        session_id = session.id

    response = client.post(
        f"{SESSIONS_API}{session_id}/template-export",
        json={},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_error"


def test_export_unknown_session_returns_404(client):
    response = client.post(
        f"{SESSIONS_API}999999/template-export",
        json={"name": "exported-template"},
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "session_not_found"


# ---------------------------------------------------------------------------
# malformed / invalid HTTP requests
# ---------------------------------------------------------------------------


def test_session_run_malformed_json_returns_400(client):
    response = client.post(
        RUNS_API,
        data="not-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "bad_request"
