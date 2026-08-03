from pathlib import Path

from app.database import db
from app.models.session_template import SessionTemplate

API = "/api/v1/device-templates"

_VALID_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": "10", "sample_rate": "2000"},
}
_ALTERED_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": 10, "sample_rate": 2500, "lowpass_ch0": 50},
}


def test_post_imports_device_template_and_get_routes_return_it(client):
    created = client.post(API, json={"name": "pod-high", **_VALID_CONTENT})

    assert created.status_code == 201
    body = created.get_json()
    assert body["name"] == "pod-high"
    assert body["file_path"] == "pod-high.toml"
    assert body["type"] == "pod8206hr"
    assert body["content"] == {
        "type": "pod8206hr",
        "parameters": {"preamp_gain": 10, "sample_rate": 2000},
    }
    assert len(body["content_hash"]) == 64

    listed = client.get(API)
    assert listed.status_code == 200
    assert [row["name"] for row in listed.get_json()] == ["pod-high"]

    shown = client.get(f"{API}/pod-high")
    assert shown.status_code == 200
    assert shown.get_json()["content"] == body["content"]


def test_get_unknown_device_template_returns_404_problem_json(client):
    response = client.get(f"{API}/missing")

    assert response.status_code == 404
    body = response.get_json(force=True)
    assert body["code"] == "device_template_not_found"
    assert body["instance"] == f"{API}/missing"


def test_put_edits_device_template_in_place(client, app):
    created = client.post(API, json={"name": "pod-high", **_VALID_CONTENT}).get_json()

    response = client.put(f"{API}/pod-high", json=_ALTERED_CONTENT)

    assert response.status_code == 200
    body = response.get_json()

    assert body["name"] == "pod-high"
    assert body["content"] == {
        "type": "pod8206hr",
        "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2500,
            "lowpass_ch0": 50,
        },
    }
    assert body["content_hash"] != created["content_hash"]
    with app.app_context():
        template_dir = Path(app.config["DEVICE_TEMPLATE_DIR"])
        assert len(list(template_dir.glob("*.toml"))) == 1


def test_rename_reports_referencing_sessions(client, app):
    client.post(API, json={"name": "pod-high", **_VALID_CONTENT})
    with app.app_context():
        referenced = SessionTemplate(
            name="Run A",
            content={"device_flows": [{"device_template_path": "pod-high.toml"}]},
            content_hash="a" * 64,
        )
        db.session.add(referenced)
        db.session.commit()
        referenced_id = referenced.id

    response = client.post(f"{API}/pod-high/rename", json={"new_name": "pod-renamed"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["device_template"]["name"] == "pod-renamed"
    assert [session["id"] for session in body["referencing_sessions"]] == [referenced_id]
    assert body["warning"] == "referencing_sessions"
    assert client.get(f"{API}/pod-high").status_code == 404


def test_duplicate_rename_target_returns_409_problem_json(client):
    client.post(API, json={"name": "pod-high", **_VALID_CONTENT})
    client.post(API, json={"name": "pod-low", **_VALID_CONTENT})

    response = client.post(f"{API}/pod-high/rename", json={"new_name": "pod-low"})

    assert response.status_code == 409
    assert response.get_json(force=True)["code"] == "device_template_name_exists"


def test_delete_reports_referencing_sessions_and_removes_template(client, app):
    client.post(API, json={"name": "pod-high", **_VALID_CONTENT})
    with app.app_context():
        referenced = SessionTemplate(
            name="Run A",
            content={"device_flows": [{"device_template_path": "pod-high.toml"}]},
            content_hash="b" * 64,
        )
        db.session.add(referenced)
        db.session.commit()
        referenced_id = referenced.id

    response = client.delete(f"{API}/pod-high")

    assert response.status_code == 200
    body = response.get_json()
    assert body["deleted_name"] == "pod-high"
    assert body["warning"] == "referencing_sessions"
    assert [session["id"] for session in body["referencing_sessions"]] == [referenced_id]
    assert body["referencing_sessions"][0]["name"] == "Run A"
    assert body["referencing_sessions"][0]["content"] == {
        "device_flows": [{"device_template_path": "pod-high.toml"}]
    }
    assert body["referencing_sessions"][0]["content_hash"] == "b" * 64
    assert client.get(f"{API}/pod-high").status_code == 404
