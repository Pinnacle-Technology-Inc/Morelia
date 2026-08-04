from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from click.testing import CliRunner

import app.services.device_templates as device_template_service
from app.cli.main import pinnacle


class _FakeApp:
    @contextmanager
    def app_context(self):
        yield


def _use_fake_app_context(monkeypatch) -> None:
    import app.cli.device_cmd as device_cmd

    monkeypatch.setattr(device_cmd, "create_app", lambda: _FakeApp())
    try:
        import app.cli.session_cmd as session_cmd
    except ModuleNotFoundError:
        return
    monkeypatch.setattr(session_cmd, "create_app", lambda: _FakeApp())


def test_validate_malformed_device_template_reports_field_reason(monkeypatch, tmp_path):
    _use_fake_app_context(monkeypatch)
    config_path = tmp_path / "device.json"
    config_path.write_text(
        """
        {
          "name": "bad-device",
          "type": "anything",
          "parameters": []
        }
        """,
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "validate", str(config_path)],
    )

    assert result.exit_code != 0
    assert "device template parameters must be a mapping" in result.output
    assert "Traceback" not in result.output


def test_device_template_service_export_emits_stable_toml():
    device_template = SimpleNamespace(
        name="bench-rig",
        content={"type": "demo", "parameters": {"gain": 2, "label": "primary"}},
    )

    result = device_template_service.export(device_template, format="toml")

    assert result == (
        'name = "bench-rig"\n'
        'type = "demo"\n'
        "\n"
        "[parameters]\n"
        "gain = 2\n"
        'label = "primary"\n'
    )
