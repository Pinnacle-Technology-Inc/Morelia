from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from click.testing import CliRunner

import app.services.device_templates as device_template_service
import app.services.session_config as session_config
from app.cli.daemon_client import DaemonError
from app.cli.main import pinnacle


class _FakeApp:
    @contextmanager
    def app_context(self):
        yield


class _FakeSinkType:
    value = "null"


class _FakeSink:
    type = _FakeSinkType()

    def as_dict(self):
        return {}


def _use_fake_app_context(monkeypatch) -> None:
    import app.cli.device_cmd as device_cmd

    monkeypatch.setattr(device_cmd, "create_app", lambda: _FakeApp())
    try:
        import app.cli.session_cmd as session_cmd
    except ModuleNotFoundError:
        return
    monkeypatch.setattr(session_cmd, "create_app", lambda: _FakeApp())


def test_validate_valid_session_config_exits_zero(monkeypatch, tmp_path):
    _use_fake_app_context(monkeypatch)
    monkeypatch.setattr(
        session_config,
        "get_by_name",
        lambda name: object() if name == "bench-rig" else None,
    )
    monkeypatch.setattr(session_config, "lookup_sink", lambda sink_type, params: _FakeSink())
    config_path = tmp_path / "session.toml"
    config_path.write_text(
        "\n".join(
            [
                'name = "smoke"',
                "",
                "[[device_flows]]",
                'hardware_id = "dev-1"',
                'port = "COM3"',
                'device_template = "bench-rig"',
                'sink_type = "null"',
            ],
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "validate", "--type", "session", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert f"valid session config: {config_path}" in result.output


def test_validate_missing_session_device_template_cites_name(monkeypatch, tmp_path):
    _use_fake_app_context(monkeypatch)
    monkeypatch.setattr(session_config, "get_by_name", lambda name: None)
    config_path = tmp_path / "session.json"
    config_path.write_text(
        """
        {
          "name": "missing-device",
          "device_flows": [
            {
              "hardware_id": "dev-1",
              "port": "COM3",
              "device_template": "missing-rig",
              "sink_type": "null"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "validate", str(config_path)],
    )

    assert result.exit_code != 0
    assert "Device template not found" in result.output
    assert "missing-rig" in result.output
    assert "Traceback" not in result.output


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


def test_export_device_template_emits_service_toml(monkeypatch):
    import app.cli.device_cmd as device_cmd

    class FakeDaemonClient:
        def get(self, path):
            assert path == "/api/v1/device-templates/bench-rig"
            return {
                "id": 1,
                "name": "bench-rig",
                "type": "pod8206hr",
                "content": {
                    "type": "pod8206hr",
                    "parameters": {"preamp_gain": "10"},
                },
            }

    monkeypatch.setattr(device_cmd, "DaemonClient", FakeDaemonClient)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "bench-rig"],
    )

    assert result.exit_code == 0, result.output
    assert result.output == (
        'name = "bench-rig"\n'
        'type = "pod8206hr"\n'
        "\n"
        "[parameters]\n"
        "preamp_gain = 10\n"
    )


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


def test_export_missing_device_template_exits_nonzero(monkeypatch):
    import app.cli.device_cmd as device_cmd

    class FakeDaemonClient:
        def get(self, path):
            assert path == "/api/v1/device-templates/missing-rig"
            raise DaemonError("Device template not found", "missing-rig", status_code=404)

    monkeypatch.setattr(device_cmd, "DaemonClient", FakeDaemonClient)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "missing-rig"],
    )

    assert result.exit_code != 0
    assert "Device template not found" in result.output
    assert "missing-rig" in result.output
    assert "Traceback" not in result.output


def test_session_validate_valid_config_exits_zero(monkeypatch, tmp_path):
    _use_fake_app_context(monkeypatch)
    monkeypatch.setattr(
        session_config,
        "get_by_name",
        lambda name: object() if name == "bench-rig" else None,
    )
    monkeypatch.setattr(session_config, "lookup_sink", lambda sink_type, params: _FakeSink())
    config_path = tmp_path / "session.toml"
    config_path.write_text(
        "\n".join(
            [
                'name = "smoke"',
                "",
                "[[device_flows]]",
                'hardware_id = "dev-1"',
                'port = "COM3"',
                'device_template = "bench-rig"',
                'sink_type = "null"',
            ],
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["session", "validate", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert f"valid session config: {config_path}" in result.output


def test_session_validate_invalid_config_exits_nonzero(monkeypatch, tmp_path):
    _use_fake_app_context(monkeypatch)
    monkeypatch.setattr(session_config, "get_by_name", lambda name: None)
    config_path = tmp_path / "session.toml"
    config_path.write_text(
        "\n".join(
            [
                'name = "smoke"',
                "",
                "[[device_flows]]",
                'hardware_id = "dev-1"',
                'port = "COM3"',
                'device_template = "missing-rig"',
                'sink_type = "null"',
            ],
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["session", "validate", str(config_path)],
    )

    assert result.exit_code != 0
    assert "Device template not found" in result.output
    assert "missing-rig" in result.output
    assert "Traceback" not in result.output
