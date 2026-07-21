from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from app.cli.main import pinnacle
from app.services import device_configs
from app.services.device_templates import create as create_device_template
from app.services.session_config import import_config

_DEVICE_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": 10, "sample_rate": 2000},
}


class FakeDaemonClient:
    def __init__(self, *, gets=None, posts=None, deletes=None):
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.deletes = list(deletes or [])
        self.calls: list[tuple[str, str, object | None]] = []

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        return self.gets.pop(0)

    def post(self, path: str, payload):
        self.calls.append(("POST", path, payload))
        return self.posts.pop(0)

    def delete(self, path: str):
        self.calls.append(("DELETE", path, None))
        return self.deletes.pop(0)


def _use_app(monkeypatch, app) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "create_app", lambda: app)


def _use_fake_client(monkeypatch, fake: FakeDaemonClient) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)


def _use_session_library_dir(monkeypatch, path: Path) -> None:
    import app.cli.session_cmd as session_cmd

    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(session_cmd, "_session_template_library_dir", lambda: path)


def _create_session(app, *, name: str, sink_location: str | None = None):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)
        sink: dict[str, object] = {"sink_name": "csv", "sink_type": "csv"}
        if sink_location is not None:
            sink["sink_location"] = sink_location
        flow = {
            "device_template_path": template.file_path,
            "hardware_id": "HW001",
            "port": "COM3",
            "nickname": "bench",
            "sinks": [sink],
        }
        session = import_config({"name": name, "device_flows": [flow]})
        return session.id


# --- path targets (no daemon; writes a portable file, name-referencing) ---


def test_export_to_toml_path_writes_a_portable_file(app, monkeypatch, tmp_path):
    _use_app(monkeypatch, app)
    session_id = _create_session(app, name="export-me", sink_location="C:/data/out.csv")
    target = tmp_path / "out.toml"

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "export", str(session_id), str(target)],
        input="generic\n",  # Export binding prompt
    )

    assert result.exit_code == 0, result.output
    assert f"saved session template: {target}" in result.output
    content = target.read_text(encoding="utf-8")
    assert 'name = "export-me"' in content
    assert 'device_template_path = "bench-rig.toml"' in content
    assert 'sink_location = "C:/data/out.csv"' in content


def test_export_to_json_path_infers_format_from_suffix(app, monkeypatch, tmp_path):
    _use_app(monkeypatch, app)
    session_id = _create_session(app, name="export-me-json")
    target = tmp_path / "out.json"

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "export", str(session_id), str(target)],
        input="generic\n",  # Export binding prompt
    )

    assert result.exit_code == 0, result.output
    content = target.read_text(encoding="utf-8")
    assert '"device_template_path":"bench-rig.toml"' in content.replace(" ", "")


def test_export_bare_filename_uses_session_template_library(app, monkeypatch):
    _use_app(monkeypatch, app)
    session_id = _create_session(app, name="library-export")

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "export", str(session_id), "library-export.toml"],
        input="generic\n",  # Export binding prompt
    )

    assert result.exit_code == 0, result.output
    target = Path(app.instance_path) / "session-templates" / "library-export.toml"
    assert f"saved session template: {target}" in result.output
    assert target.exists()
    assert 'name = "library-export"' in target.read_text(encoding="utf-8")


def test_export_to_path_mints_a_new_device_template_for_a_drifted_config(app, monkeypatch, tmp_path):
    with app.app_context():
        template = create_device_template("bench-rig", _DEVICE_CONTENT)
        session = import_config(
            {
                "name": "drifted",
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "hardware_id": "HW001",
                        "port": "COM3",
                        "sinks": [{"sink_name": "csv", "sink_type": "csv"}],
                    }
                ],
            }
        )
        session_id = session.id
        config_id = session.device_flows[0]["device_config_id"]
        device_configs.edit(
            config_id,
            parameters={"preamp_gain": 100, "sample_rate": 2000},
            update_source_template=False,
        )
    _use_app(monkeypatch, app)
    target = tmp_path / "drifted.toml"

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "export", str(session_id), str(target)],
        input="generic\n",  # Export binding prompt
    )

    assert result.exit_code == 0, result.output
    content = target.read_text(encoding="utf-8")
    # The drifted config no longer matches its source template, so export mints
    # a new "_customized" device template rather than re-referencing bench-rig.
    assert 'device_template_path = "bench-rig.toml_customized.toml"' in content
    assert 'device_template_path = "bench-rig.toml"\n' not in content


def test_export_to_path_missing_session_exits_nonzero(app, monkeypatch, tmp_path):
    _use_app(monkeypatch, app)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "export", "999", str(tmp_path / "out.toml")],
        input="generic\n",  # Export binding prompt
    )

    assert result.exit_code != 0
    assert "No session with id 999" in result.output
    assert "Traceback" not in result.output


# --- name targets (through the daemon; persists a stored session template) ---


def test_export_to_name_posts_template_export_route(app, monkeypatch, tmp_path):
    fake = FakeDaemonClient(
        posts=[
            {
                "id": 1,
                "name": "exported-template",
                "content": {
                    "policy": "recommend",
                    "device_flows": [
                        {
                            "device_template_path": "pod-high.toml",
                            "device_template_content_hash": "a" * 64,
                            "sinks": [
                                {
                                    "sink_name": "csv",
                                    "sink_type": "csv",
                                    "sink_location": "C:/data/out.csv",
                                    "sink_parameters": {},
                                }
                            ],
                        }
                    ],
                },
            }
        ]
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "session-templates"
    _use_session_library_dir(monkeypatch, library_dir)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "export", "12", "exported-template"],
        input="generic\n",
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "POST",
            "/api/v1/sessions/12/template-export",
            {"name": "exported-template", "binding_mode": "generic"},
        )
    ]
    assert '"name": "exported-template"' in result.output
    saved = library_dir / "exported-template.toml"
    assert saved.exists()
    saved_content = saved.read_text(encoding="utf-8")
    assert 'device_template_path = "pod-high.toml"' in saved_content
    # The saved portable TOML preserves the sink as a nested sinks[] table.
    assert "[[device_flows.sinks]]" in saved_content
    assert 'sink_name = "csv"' in saved_content
    assert 'sink_location = "C:/data/out.csv"' in saved_content


def test_delete_stored_session_template_by_name(monkeypatch):
    fake = FakeDaemonClient(deletes=[None])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "delete", "--force", "only8206"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("DELETE", "/api/v1/session-templates/only8206", None),
    ]
    assert '"deleted_name": "only8206"' in result.output


def test_delete_local_session_template_by_list_number(app, monkeypatch, tmp_path):
    fake = FakeDaemonClient(
        gets=[[]],
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "session-templates"
    _use_session_library_dir(monkeypatch, library_dir)
    template_path = library_dir / "portable.toml"
    template_path.write_text(
        'policy = "recommend"\n\n[[device_flows]]\nsink_type = "csv"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["session", "template", "delete", "--force", "1"],
    )

    assert result.exit_code == 0, result.output
    assert not template_path.exists()
    assert fake.calls == [("GET", "/api/v1/session-templates", None)]
