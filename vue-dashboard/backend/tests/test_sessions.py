"""Contract tests for the reference `sessions` resource.

With test_errors.py, these cover the issue's required status codes:
400 (malformed JSON), 404 (unknown id), 409 (conflict), 422 (validation),
423 (locked) — each asserting the consistent RFC 9457 problem+json `code`.
"""

import json
import logging
import re

import pytest

from app import create_app
from app.domain.enums import DeviceType
from app.models.device_config import DeviceConfig
from app.services.device_configs import create as create_device_config
from app.services import device_templates
from app.database import db

API = "/api/v1/sessions/"


@pytest.fixture
def app(tmp_path):
    """Isolated app so device-template files never touch shared ``instance/``.

    Overrides conftest's shared ``app`` fixture (and, transitively, ``client``)
    with a per-test in-memory DB plus a throwaway ``DEVICE_TEMPLATE_DIR``, so
    the template-resolution tests here never read or write the real
    ``instance/device-templates`` library.
    """
    application = create_app("testing", {"DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates")})
    with application.app_context():
        db.create_all()
    return application


class _FakeManagedSupervisor:
    def __init__(self) -> None:
        self.dispatched = []

    def spawn(self, session, *, manifest=None):
        session.runtime_port = 43210
        session.runtime_token = "fake-runtime-token"
        return session.runtime_port

    def dispatch(self, session, envelope):
        self.dispatched.append(envelope)

    def stop(self, session, *, envelope=None):
        session.runtime_port = None
        session.runtime_token = None


def _valid_flow(client):
    with client.application.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="DEV01",
            port="COM3",
            parameters={"preamp_gain": 10},
        )
        return {
            "device_config_id": config.id,
            "sinks": [{"sink_type": "csv", "sink_location": "C:/data/out.csv"}],
        }


# --- happy paths (the conventions working as intended) ----------------------


def test_create_minimal_autogenerates_name(client):
    """Empty body is a valid Draft; name is auto-generated (decisions A + B)."""
    response = client.post(API, json={})

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "draft"
    assert body["policy"] == "recommend"          # default for an omitted policy
    assert body["name"].startswith("Session ")    # server-generated
    assert body["device_flows"] == []             # empty draft allowed


def test_create_with_name_keeps_it(client):
    response = client.post(API, json={"name": "Calibration run"})

    assert response.status_code == 201
    assert response.get_json()["name"] == "Calibration run"


def test_create_resolves_device_template_flow_to_device_config(client):
    """A device_template_path + physical binding instantiates a config, and the
    stored flow returns only canonical ``sinks[]`` (no flattened sink fields)."""
    with client.application.app_context():
        template = device_templates.create(
            "bench-rig",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10}},
        )
        template_path = template.file_path
    flow = {
        "hardware_id": "DEV01",
        "port": "COM3",
        "device_template_path": template_path,
        "nickname": "bench",
        "sinks": [{"sink_type": "csv", "sink_location": "C:/data/out.csv"}],
    }

    response = client.post(API, json={"name": "Stage 8", "device_flows": [flow]})

    assert response.status_code == 201, response.get_json()
    body_flow = response.get_json()["device_flows"][0]
    assert set(body_flow) == {"device_config_id", "nickname", "sinks"}
    assert body_flow["nickname"] == "bench"
    assert body_flow["sinks"] == [
        {
            "sink_name": "csv",
            "sink_type": "csv",
            "sink_location": "C:/data/out.csv",
            "sink_parameters": {},
        }
    ]


def test_create_accepts_multiple_ordered_sinks_including_repeated_types(client):
    """A single source may own several ordered sinks, incl. repeated types with
    distinct names; the response echoes the canonical ordered ``sinks[]``."""
    with client.application.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="DEV07",
            port="COM7",
            parameters={"preamp_gain": 10},
        )
        config_id = config.id
    flow = {
        "device_config_id": config_id,
        "sinks": [
            {"sink_name": "disk-a", "sink_type": "csv", "sink_location": "C:/data/a.csv"},
            {"sink_name": "disk-b", "sink_type": "csv", "sink_location": "C:/data/b.csv"},
            {
                "sink_name": "quest-live",
                "sink_type": "quest",
                "sink_parameters": {"host": "localhost", "port": 9009, "measurement": "exp_a"},
            },
        ],
    }

    response = client.post(API, json={"device_flows": [flow]})

    assert response.status_code == 201, response.get_json()
    body_flow = response.get_json()["device_flows"][0]
    assert body_flow["sinks"] == [
        {
            "sink_name": "disk-a",
            "sink_type": "csv",
            "sink_location": "C:/data/a.csv",
            "sink_parameters": {},
        },
        {
            "sink_name": "disk-b",
            "sink_type": "csv",
            "sink_location": "C:/data/b.csv",
            "sink_parameters": {},
        },
        {
            "sink_name": "quest-live",
            "sink_type": "quest",
            "sink_parameters": {"host": "localhost", "port": 9009, "measurement": "exp_a"},
        },
    ]


def test_create_normalizes_legacy_flattened_sink_to_sinks_list(client):
    """Legacy flattened sink input is accepted through the compatibility path
    and normalized to a one-element ``sinks[]`` in the response."""
    with client.application.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="DEV08",
            port="COM8",
            parameters={"preamp_gain": 10},
        )
        config_id = config.id

    response = client.post(
        API,
        json={
            "device_flows": [
                {
                    "device_config_id": config_id,
                    "sink_type": "csv",
                    "sink_location": "C:/data/legacy.csv",
                }
            ]
        },
    )

    assert response.status_code == 201, response.get_json()
    body_flow = response.get_json()["device_flows"][0]
    assert body_flow["sinks"] == [
        {
            "sink_name": "csv",
            "sink_type": "csv",
            "sink_location": "C:/data/legacy.csv",
            "sink_parameters": {},
        }
    ]


def test_create_secret_bearing_sink_returns_422_without_leaking_value(client):
    """An inline secret parameter is rejected as a stable client error and the
    rejected VALUE never appears in the problem response (acceptance crit. 3)."""
    with client.application.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="DEV09",
            port="COM9",
            parameters={"preamp_gain": 10},
        )
        config_id = config.id

    response = client.post(
        API,
        json={
            "device_flows": [
                {
                    "device_config_id": config_id,
                    "sinks": [{"sink_type": "quest", "sink_parameters": {"token": "sk-secret"}}],
                }
            ]
        },
    )

    assert response.status_code == 422, response.get_json()
    body = response.get_json()
    assert body["code"] == "invalid_session_entry"
    assert body["field"] == "sinks[0].sink_parameters.token"
    # The rejected credential value must not leak anywhere in the problem body.
    assert "sk-secret" not in json.dumps(body)


# --- error contract: one test per required status code ----------------------


def test_invalid_policy_returns_422(client):
    response = client.post(API, json={"policy": "turbo"})

    assert response.status_code == 422
    body = response.get_json(force=True)
    assert body["code"] == "validation_error"
    assert "errors" in body  # per-field detail for the client to surface


def test_scheduled_without_start_at_returns_422(client):
    """Conditional validation (decision C): a scheduled session needs start_at."""
    response = client.post(API, json={"schedule": {"mode": "daily"}})

    assert response.status_code == 422
    assert response.get_json(force=True)["code"] == "validation_error"


def test_malformed_json_returns_400(client):
    response = client.post(API, data="this is not json", content_type="application/json")

    assert response.status_code == 400
    assert response.get_json(force=True)["code"] == "bad_request"


def test_unknown_session_returns_404(client):
    response = client.get(API + "9999")

    assert response.status_code == 404
    assert response.get_json(force=True)["code"] == "session_not_found"


def test_delete_started_session_returns_409(client):
    created = client.post(API, json={"device_flows": [_valid_flow(client)]}).get_json()
    client.post(f"{API}{created['id']}/commands/start")

    response = client.delete(f"{API}{created['id']}")

    assert response.status_code == 409
    assert response.get_json(force=True)["code"] == "invalid_transition"


def test_start_twice_is_locked_423(client):
    """Only one state-changing command per dataflow at a time -> 423 Locked."""
    created = client.post(API, json={"device_flows": [_valid_flow(client)]}).get_json()

    first = client.post(f"{API}{created['id']}/commands/start")
    assert first.status_code == 202

    second = client.post(f"{API}{created['id']}/commands/start")
    assert second.status_code == 423
    assert second.get_json(force=True)["code"] == "command_in_flight"


def test_start_device_claim_conflict_returns_typed_problem_and_force_steals(client, app):
    app.config["SESSION_RUNTIME_HOST_ENABLED"] = True
    app.extensions["host_supervisor"] = _FakeManagedSupervisor()

    with app.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="DEV02",
            port="COM4",
            parameters={"preamp_gain": 10},
        )
        config_id = config.id

    first = client.post(
        API,
        json={
            "device_flows": [
                {
                    "device_config_id": config_id,
                    "sink_type": "csv",
                    "sink_location": "C:/data/claim-first.csv",
                }
            ]
        },
    ).get_json()
    second = client.post(
        API,
        json={
            "device_flows": [
                {
                    "device_config_id": config_id,
                    "sink_type": "csv",
                    "sink_location": "C:/data/claim-second.csv",
                }
            ]
        },
    ).get_json()

    started_first = client.post(f"{API}{first['id']}/commands/start")
    conflict = client.post(f"{API}{second['id']}/commands/start")
    forced = client.post(f"{API}{second['id']}/commands/start", json={"force": True})

    with app.app_context():
        owner = db.session.get(DeviceConfig, config_id).claimed_session_id

    assert started_first.status_code == 202
    assert conflict.status_code == 409
    conflict_body = conflict.get_json(force=True)
    assert conflict_body["code"] == "device_claim_conflict"
    assert conflict_body["device_config_id"] == config_id
    assert conflict_body["claimed_session_id"] == int(first["id"])
    assert forced.status_code == 202
    assert owner == int(second["id"])


def test_start_command_logs_correlated_request_session_and_command_ids(client, caplog):
    created = client.post(API, json={"device_flows": [_valid_flow(client)]}).get_json()
    caplog.clear()
    caplog.set_level(logging.INFO)

    response = client.post(
        f"{API}{created['id']}/commands/start",
        headers={"X-Request-ID": "start-request"},
    )

    command_event = next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "command_started"
    )
    completed_event = next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "http_request_completed"
    )

    assert response.status_code == 202
    assert command_event["request_id"] == "start-request"
    # session_id now comes from the request route (request_logging middleware),
    # not the command envelope — it is the int view-arg, not the wire string.
    assert command_event["session_id"] == int(created["id"])
    assert re.fullmatch(r"[0-9a-f]{32}", command_event["command_id"])
    assert command_event["command"] == "start"
    assert completed_event["command_id"] == command_event["command_id"]
