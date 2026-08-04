from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from app.cli.main import pinnacle


class FakeDaemonClient:
    def __init__(self, *, gets=None):
        self.gets = dict(gets or {})

    def get(self, path: str):
        return self.gets[path]


def _use_app(monkeypatch, app) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "create_app", lambda: app)


def _use_fake_client(monkeypatch, fake: FakeDaemonClient) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)


def test_session_template_list_includes_stored_and_local_library_templates(app, monkeypatch):
    _use_app(monkeypatch, app)
    _use_fake_client(
        monkeypatch,
        FakeDaemonClient(
            gets={
                "/api/v1/session-templates": [
                    {
                        "id": 1,
                        "name": "stored-template",
                        "content": {
                            "policy": "recommend",
                            "device_flows": [{"device_template_id": 5, "sink_type": "csv"}],
                        },
                        "content_hash": "stored-hash",
                    }
                ]
            }
        ),
    )
    library_dir = Path(app.instance_path) / "session-templates"
    library_dir.mkdir(parents=True, exist_ok=True)
    local_path = library_dir / "portable-template.toml"
    local_path.write_text(
        "\n".join(
            [
                'policy = "recommend"',
                "",
                "[[device_flows]]",
                'device_template = "bench-rig"',
                'sink_type = "csv"',
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(pinnacle, ["session", "template", "list"])

    assert result.exit_code == 0, result.output
    assert "stored-template" in result.output
    assert "portable-template" in result.output
    assert "source" not in result.output
    assert "id" not in result.output
    assert "number" not in result.output
    assert str(local_path) in result.output
