from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from app import create_app
from app.cli.main import pinnacle
from app.database import db
from app.models.runtime_manifest import RuntimeManifest
from app.repositories.sessions import SessionRepository
from app.runtime_host.manifest import Manifest
from app.services import device_templates, manifests, session_config

_DEVICE_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": 10, "sample_rate": 2000},
}


@pytest.fixture
def app(tmp_path):
    """Override conftest's shared ``app`` fixture with an isolated template dir.

    Without this, device-template creation/lookup here shares the real
    ``instance/device-templates`` library, so ``preview-pod.toml`` left there
    by other runs would make the "missing device template" case resolve.
    """
    application = create_app(
        "testing", {"DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates")}
    )
    with application.app_context():
        db.create_all()
    return application


def _write_session_config(tmp_path, *, name: str = "preview-session"):
    config_path = tmp_path / "session.toml"
    config_path.write_text(
        "\n".join(
            [
                f'name = "{name}"',
                'policy = "recommend"',
                "",
                "[[device_flows]]",
                'nickname = "preview-pod"',
                'hardware_id = "HW001"',
                'port = "/dev/ttyUSB0"',
                'device_template_path = "preview-pod.toml"',
                'sink_type = "csv"',
                'sink_location = "/data/preview.csv"',
            ],
        ),
        encoding="utf-8",
    )
    return config_path


def _write_multi_sink_session_config(tmp_path, *, name: str = "multi-preview"):
    """A source that owns two ordered file sinks with distinct names/locations."""
    config_path = tmp_path / "multi-session.toml"
    config_path.write_text(
        "\n".join(
            [
                f'name = "{name}"',
                'policy = "recommend"',
                "",
                "[[device_flows]]",
                'nickname = "preview-pod"',
                'hardware_id = "HW001"',
                'port = "/dev/ttyUSB0"',
                'device_template_path = "preview-pod.toml"',
                "",
                "[[device_flows.sinks]]",
                'sink_name = "primary"',
                'sink_type = "csv"',
                'sink_location = "/data/primary.csv"',
                "",
                "[[device_flows.sinks]]",
                'sink_name = "backup"',
                'sink_type = "csv"',
                'sink_location = "/data/backup.csv"',
            ],
        ),
        encoding="utf-8",
    )
    return config_path


def _runtime_manifest_count() -> int:
    return db.session.scalars(
        db.select(db.func.count()).select_from(RuntimeManifest)
    ).one()


def test_session_preview_prints_manifest_json_and_persists_nothing(app, monkeypatch, tmp_path):
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "create_app", lambda: app)
    config_path = _write_session_config(tmp_path)

    with app.app_context():
        device_templates.create("preview-pod", _DEVICE_CONTENT)
        count_before = _runtime_manifest_count()

    result = CliRunner().invoke(pinnacle, ["session", "preview", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # v2 manifest wire form carries the nullable session identity; a preview
    # leaves it null (see manifests.build_for_preview).
    assert set(payload) == {
        "schema_version",
        "dataflow_id",
        "policy",
        "device_flows",
        "session_id",
        "hash",
    }
    assert payload["schema_version"] == "2"
    assert payload["session_id"] is None
    assert payload["dataflow_id"] == "preview-session"
    assert payload["policy"] == "recommend"
    assert payload["device_flows"][0]["parameters"] == {
        "preamp_gain": 10,
        "sample_rate": 2000,
    }
    # Ordered v2 sink collection with a source-local identity and a resolved
    # absolute file_path for the CSV (file) sink.
    sinks = payload["device_flows"][0]["sinks"]
    assert len(sinks) == 1
    assert sinks[0]["name"] == "csv"
    assert sinks[0]["type"] == "csv"
    assert sinks[0]["parameters"]["file_path"] == "/data/preview.csv"
    assert Manifest.from_dict(payload).hash == payload["hash"]

    with app.app_context():
        assert _runtime_manifest_count() == count_before


def test_build_for_preview_matches_persisted_resolve_except_session_identity(app, tmp_path):
    """Preview and persisted resolution are reproducible and differ only in the
    documented persistence identity (session_id) and its derived hash."""
    config_path = _write_session_config(tmp_path, name="same-dataflow")

    with app.app_context():
        device_templates.create("preview-pod", _DEVICE_CONTENT)
        preview = manifests.build_for_preview(
            config_path.read_text(encoding="utf-8"),
            format="toml",
        )
        session = session_config.import_config(
            config_path.read_text(encoding="utf-8"),
            format="toml",
        )
        session.dataflow_id = "same-dataflow"
        db.session.commit()
        session_id = session.id

        persisted = manifests.resolve(session_id)

    # session_id is populated on the persisted manifest, null on the preview.
    assert preview.session_id is None
    assert persisted.session_id == session_id
    # Because the hash now covers session_id, the two differ by design.
    assert preview.hash != persisted.hash

    # Everything else — dataflow id, policy, and the full ordered sink
    # collection — is identical: resolution is otherwise pure/reproducible.
    preview_doc = preview.to_dict()
    persisted_doc = persisted.to_dict()
    for doc in (preview_doc, persisted_doc):
        del doc["session_id"]
        del doc["hash"]
    assert preview_doc == persisted_doc


def test_session_preview_shows_canonical_config_for_every_sink(app, monkeypatch, tmp_path):
    """Preview surfaces canonical, non-secret config for every selected sink, and
    each file sink is identifiable by source nickname plus sink name — the
    coordinates a file-location conflict is reported against."""
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "create_app", lambda: app)
    config_path = _write_multi_sink_session_config(tmp_path)

    with app.app_context():
        device_templates.create("preview-pod", _DEVICE_CONTENT)

    result = CliRunner().invoke(pinnacle, ["session", "preview", str(config_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    flow = payload["device_flows"][0]
    # The source nickname is preserved — half of a file-conflict target's identity.
    assert flow["nickname"] == "preview-pod"

    sinks = flow["sinks"]
    assert [sink["name"] for sink in sinks] == ["primary", "backup"]
    assert [sink["type"] for sink in sinks] == ["csv", "csv"]
    # Every selected sink carries its own canonical resolved configuration; the
    # ordered pair (nickname, sink_name) uniquely addresses each file target.
    assert sinks[0]["parameters"]["file_path"] == "/data/primary.csv"
    assert sinks[1]["parameters"]["file_path"] == "/data/backup.csv"
    assert Manifest.from_dict(payload).hash == payload["hash"]


def test_session_preview_missing_device_template_exits_nonzero(app, monkeypatch, tmp_path):
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "create_app", lambda: app)
    config_path = _write_session_config(tmp_path)

    with app.app_context():
        session = SessionRepository().create({"name": "empty"})
        assert session.id is not None

    result = CliRunner().invoke(pinnacle, ["session", "preview", str(config_path)])

    assert result.exit_code != 0
    assert "Device template not found" in result.output
    assert "preview-pod" in result.output
    assert "Traceback" not in result.output
