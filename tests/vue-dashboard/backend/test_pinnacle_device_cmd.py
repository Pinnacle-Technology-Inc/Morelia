from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli.daemon_client import DaemonUnavailable
from app.cli.main import pinnacle
from app.services.device_templates import content_hash as device_template_content_hash


class FakeDaemonClient:
    def __init__(
        self,
        *,
        gets=None,
        posts=None,
        deletes=None,
        puts=None,
        error: Exception | None = None,
    ) -> None:
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.deletes = list(deletes or [])
        self.puts = list(puts or [])
        self.error = error
        self.calls: list[tuple[str, str, object | None]] = []

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        if self.error is not None:
            raise self.error
        return self.gets.pop(0)

    def post(self, path: str, payload):
        self.calls.append(("POST", path, payload))
        if self.error is not None:
            raise self.error
        return self.posts.pop(0)

    def delete(self, path: str):
        self.calls.append(("DELETE", path, None))
        if self.error is not None:
            raise self.error
        return self.deletes.pop(0)

    def _request(self, method: str, path: str, payload):
        self.calls.append((method, path, payload))
        if self.error is not None:
            raise self.error
        if method in {"PUT", "PATCH"}:
            return self.puts.pop(0)
        raise AssertionError(f"unexpected request method: {method}")


def _use_fake_client(monkeypatch, fake: FakeDaemonClient) -> None:
    import app.cli.device_cmd as device_cmd

    monkeypatch.setattr(device_cmd, "DaemonClient", lambda: fake)


def _use_app(monkeypatch, app) -> None:
    import app.cli.device_cmd as device_cmd

    monkeypatch.setattr(device_cmd, "create_app", lambda: app)


def _use_template_library_dir(monkeypatch, path: Path) -> None:
    import app.cli.device_cmd as device_cmd

    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(device_cmd, "_device_template_library_dir", lambda: path)


def _json_after_warning(output: str):
    lines = output.splitlines()
    assert lines[0].startswith("warning:")
    return json.loads("\n".join(lines[1:]))


def test_device_config_accepts_a_pre_registered_nickname(monkeypatch):
    saved = {
        "id": 8,
        "type": "pod8206hr",
        "hardware_id": "A1B2C",
        "port": "COM3",
        "parameters": {"preamp_gain": 10},
        "nickname": "left-pod",
    }
    fake = FakeDaemonClient(
        gets=[
            [
                {
                    "id": 3,
                    "type": "pod8206hr",
                    "hardware_id": "A1B2C",
                    "nickname": "left-pod",
                    "device_config_id": None,
                }
            ],
            {
                "devices": [
                    {
                        "id": None,
                        "type": "pod8206hr",
                        "port": "COM3",
                        "hardware_id": "A1B2C",
                        "availability": "available",
                        "status": "unconfigured",
                        "owner": None,
                    }
                ]
            },
        ],
        posts=[saved],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        [
            "device",
            "config",
            "left-pod",
            "--parameters",
            '{"preamp_gain":10}',
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-registrations", None),
        ("GET", "/api/v1/devices/pool", None),
        (
            "POST",
            "/api/v1/device-configs",
            {
                "type": "pod8206hr",
                "hardware_id": "A1B2C",
                "port": "COM3",
                "parameters": {"preamp_gain": 10},
                "nickname": "left-pod",
            },
        ),
    ]
    assert json.loads(result.output) == saved


def test_device_name_posts_alias_by_hardware_id_and_type(monkeypatch):
    renamed = {"id": 7, "hardware_id": "A1B2C", "nickname": "Tom"}
    fake = FakeDaemonClient(posts=[renamed])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "name", "A1B2C", "--type", "8206", "Tom"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "POST",
            "/api/v1/device-configs/name",
            {"type": "pod8206hr", "hardware_id": "A1B2C", "nickname": "Tom"},
        )
    ]
    assert json.loads(result.output) == renamed


def test_device_edit_patches_config_by_id(monkeypatch):
    updated = {"id": 7, "parameters": {"preamp_gain": 100}}
    fake = FakeDaemonClient(puts=[updated])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        [
            "device",
            "edit",
            "7",
            "--parameters",
            '{"preamp_gain":100}',
            "--writeback-template",
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "PATCH",
            "/api/v1/device-configs/7",
            {"parameters": {"preamp_gain": 100}, "update_source_template": True},
        )
    ]
    assert json.loads(result.output) == updated


def test_device_delete_deletes_config_by_id(monkeypatch):
    fake = FakeDaemonClient(deletes=[{"deleted_id": 7}])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["device", "delete", "--force", "7"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("DELETE", "/api/v1/device-configs/7", None)]
    assert json.loads(result.output) == {"deleted_id": 7}


def test_device_edit_accepts_config_nickname(monkeypatch):
    updated = {"id": 7, "nickname": "left-pod", "parameters": {"preamp_gain": 100}}
    fake = FakeDaemonClient(
        gets=[
            [
                {"id": 7, "nickname": "left-pod"},
            ]
        ],
        puts=[updated],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        [
            "device",
            "edit",
            "left-pod",
            "--parameters",
            '{"preamp_gain":100}',
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-configs", None),
        (
            "PATCH",
            "/api/v1/device-configs/7",
            {"parameters": {"preamp_gain": 100}, "update_source_template": False},
        ),
    ]
    assert json.loads(result.output) == updated


def test_device_delete_accepts_config_nickname(monkeypatch):
    fake = FakeDaemonClient(
        gets=[
            [
                {"id": 7, "nickname": "left-pod"},
            ]
        ],
        deletes=[{"deleted_id": 7}],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "delete", "--force", "left-pod"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-configs", None),
        ("DELETE", "/api/v1/device-configs/7", None),
    ]
    assert json.loads(result.output) == {"deleted_id": 7}


def test_device_template_import_copies_file_and_prints_saved_template(
    app, monkeypatch, tmp_path
):
    saved = {
        "id": 1,
        "name": "pod-high",
        "file_path": "device-template.toml",
        "type": "pod8206hr",
        "content": {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}},
    }
    fake = FakeDaemonClient(gets=[[], [saved]])
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "device-templates"
    _use_template_library_dir(monkeypatch, library_dir)
    config_path = tmp_path / "device-template.toml"
    config_path.write_text(
        "\n".join(
            [
                'name = "pod-high"',
                'type = "pod8206hr"',
                "",
                "[parameters]",
                "preamp_gain = 10",
                "sample_rate = 2000",
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "import", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert (library_dir / "device-template.toml").read_text(encoding="utf-8") == config_path.read_text(
        encoding="utf-8"
    )
    assert fake.calls == [
        ("GET", "/api/v1/device-templates", None),
        ("GET", "/api/v1/device-templates", None),
    ]
    assert json.loads(result.output) == saved


def test_device_template_list_prints_no_templates(app, monkeypatch, tmp_path):
    fake = FakeDaemonClient(gets=[[]])
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    _use_template_library_dir(monkeypatch, tmp_path / "device-templates")

    result = CliRunner().invoke(pinnacle, ["device", "template", "list"])

    assert result.exit_code == 0, result.output
    assert result.output == "no device templates\n"


def test_device_template_show_prints_daemon_template(monkeypatch, tmp_path):
    template = {
        "id": 1,
        "name": "pod-high",
        "type": "pod8206hr",
        "content": {"type": "pod8206hr", "parameters": {"preamp_gain": 10}},
    }
    fake = FakeDaemonClient(gets=[template])
    _use_fake_client(monkeypatch, fake)
    _use_template_library_dir(monkeypatch, tmp_path / "device-templates")

    result = CliRunner().invoke(pinnacle, ["device", "template", "show", "pod-high"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/device-templates/pod-high", None)]
    assert json.loads(result.output) == template


def test_device_template_import_copies_source_file_to_library(app, monkeypatch, tmp_path):
    source = tmp_path / "custom-file.toml"
    source.write_text(
        "\n".join(['name = "custom-name"', 'type = "pod8206hr"', "", "[parameters]", "preamp_gain = 10", "sample_rate = 2000"]),
        encoding="utf-8",
    )
    artifact = {
        "name": "custom-name",
        "type": "pod8206hr",
        "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2000},
    }
    library_dir = tmp_path / "device-templates"
    imported = {
        "name": "custom-name",
        "file_path": "custom-file.toml",
        "type": "pod8206hr",
        "content": {"type": "pod8206hr", "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2000,
            }},
        "content_hash": device_template_content_hash(artifact),
    }
    fake = FakeDaemonClient(gets=[[], [imported]])
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    _use_template_library_dir(monkeypatch, library_dir)

    result = CliRunner().invoke(pinnacle, ["device", "template", "import", str(source)])

    assert result.exit_code == 0, result.output
    assert (library_dir / "custom-file.toml").read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert fake.calls == [
        ("GET", "/api/v1/device-templates", None),
        ("GET", "/api/v1/device-templates", None),
    ]
    assert json.loads(result.output) == imported


def test_device_template_import_name_renames_file_and_toml_name(app, monkeypatch, tmp_path):
    source = tmp_path / "original.toml"
    source.write_text(
        "\n".join(['name = "original"', 'type = "pod8206hr"', "", "[parameters]", "preamp_gain = 10", "sample_rate = 2000"]),
        encoding="utf-8",
    )
    artifact = {"name": "renamed", "type": "pod8206hr", "parameters": {
        "preamp_gain": 10,
        "sample_rate": 2000,
        }}
    imported = {
        "name": "renamed",
        "file_path": "renamed.toml",
        "type": "pod8206hr",
        "content": {"type": "pod8206hr", "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2000,
            }},
        "content_hash": device_template_content_hash(artifact),
    }
    library_dir = tmp_path / "device-templates"
    fake = FakeDaemonClient(gets=[[], [imported]])
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    _use_template_library_dir(monkeypatch, library_dir)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "import", "--name", "renamed", str(source)],
    )

    assert result.exit_code == 0, result.output
    saved = library_dir / "renamed.toml"
    assert saved.exists()
    assert not (library_dir / "original.toml").exists()
    assert 'name = "renamed"' in saved.read_text(encoding="utf-8")
    assert json.loads(result.output) == imported


def test_device_template_import_duplicate_hash_prompts_and_aborts(app, monkeypatch, tmp_path):
    source = tmp_path / "copy.toml"
    source.write_text(
        "\n".join(['name = "copy"', 'type = "pod8206hr"', "", "[parameters]", "preamp_gain = 10", "sample_rate = 2000"]),
        encoding="utf-8",
    )
    artifact = {"name": "copy", "type": "pod8206hr", "parameters": {
        "preamp_gain": 10,
        "sample_rate": 2000,
        }}
    library_dir = tmp_path / "device-templates"
    fake = FakeDaemonClient(
        gets=[
            [
                {
                    "name": "existing",
                    "file_path": "existing.toml",
                    "type": "pod8206hr",
                    "content_hash": device_template_content_hash(artifact),
                }
            ]
        ]
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    _use_template_library_dir(monkeypatch, library_dir)

    result = CliRunner().invoke(pinnacle, ["device", "template", "import", str(source)], input="n\n")

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "existing.toml" in result.output
    assert not (library_dir / "copy.toml").exists()
    assert fake.calls == [("GET", "/api/v1/device-templates", None)]


def test_device_template_import_duplicate_hash_continues_when_confirmed(app, monkeypatch, tmp_path):
    source = tmp_path / "copy.toml"
    source.write_text(
        "\n".join(['name = "copy"', 'type = "pod8206hr"', "", "[parameters]", "preamp_gain = 10", "sample_rate = 2000"]),
        encoding="utf-8",
    )
    artifact = {"name": "copy", "type": "pod8206hr", "parameters": {
        "preamp_gain": 10,
        "sample_rate": 2000,
        }}
    imported = {
        "name": "copy",
        "file_path": "copy.toml",
        "type": "pod8206hr",
        "content_hash": device_template_content_hash(artifact),
    }
    library_dir = tmp_path / "device-templates"
    fake = FakeDaemonClient(
        gets=[
            [
                {
                    "name": "existing",
                    "file_path": "existing.toml",
                    "type": "pod8206hr",
                    "content_hash": device_template_content_hash(artifact),
                }
            ],
            [imported],
        ]
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    _use_template_library_dir(monkeypatch, library_dir)

    result = CliRunner().invoke(pinnacle, ["device", "template", "import", str(source)], input="y\n")

    assert result.exit_code == 0, result.output
    assert (library_dir / "copy.toml").exists()
    assert json.loads(result.output[result.output.index("{") :]) == imported


def test_device_template_show_reads_local_library_template(app, monkeypatch, tmp_path):
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "device-templates"
    _use_template_library_dir(monkeypatch, library_dir)
    local_path = library_dir / "portable-template.toml"
    local_path.write_text(
        "\n".join(
            [
                'name = "portable-template"',
                'type = "pod8206hr"',
                "",
                "[parameters]",
                "preamp_gain = 10",
                "sample_rate = 2000",
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "show", "portable-template"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "name": "portable-template",
        "type": "pod8206hr",
        "parameters": {"preamp_gain": 10, "sample_rate": 2000},
    }


def test_device_template_edit_puts_content_payload(monkeypatch, tmp_path):
    updated = {
        "id": 1,
        "name": "pod-high",
        "type": "pod8206hr",
        "content": {
            "type": "pod8206hr",
            "parameters": {"sample_rate": 2500, "lowpass_ch0": 50},
        },
    }
    fake = FakeDaemonClient(puts=[updated])
    _use_fake_client(monkeypatch, fake)
    config_path = tmp_path / "edited-template.toml"
    config_path.write_text(
        "\n".join(
            [
                'name = "ignored-file-name"',
                'type = "pod8206hr"',
                "",
                "[parameters]",
                "sample_rate = 2500",
                "lowpass_ch0 = 50",
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "edit", "pod-high", str(config_path)],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "PUT",
            "/api/v1/device-templates/pod-high",
            {
                "type": "pod8206hr",
                "parameters": {"sample_rate": 2500, "lowpass_ch0": 50},
            },
        )
    ]
    assert json.loads(result.output) == updated


def test_device_template_edit_interactive_prompts_and_updates_changed_value(monkeypatch):
    current = {
        "id": 1,
        "name": "pod-high",
        "type": "pod8206hr",
        "content": {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10, "sample_rate": 2000},
        },
    }
    updated = {
        "id": 1,
        "name": "pod-high",
        "type": "pod8206hr",
        "content": {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 100, "sample_rate": 2000},
        },
    }
    fake = FakeDaemonClient(gets=[current], puts=[updated])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "edit", "pod-high"],
        # preamp_gain -> "100" (changed), sample_rate -> "" (kept), rest optional -> "" (skipped)
        input="100\n\n\n\n\n\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "preamp_gain" in result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-templates/pod-high", None),
        (
            "PUT",
            "/api/v1/device-templates/pod-high",
            {
                "type": "pod8206hr",
                "parameters": {"preamp_gain": 100, "sample_rate": 2000},
            },
        ),
    ]
    json_start = result.output.index("{")
    assert json.loads(result.output[json_start:]) == updated


def test_device_template_edit_interactive_no_changes_skips_put(monkeypatch):
    current = {
        "id": 1,
        "name": "pod-high",
        "type": "pod8206hr",
        "content": {
            "type": "pod8206hr",
            "parameters": {
                "preamp_gain": 10,
                "sample_rate": 2000,
                },
        },
    }
    fake = FakeDaemonClient(gets=[current])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "edit", "pod-high"],
        input="\n\n\n\n\n\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "no changes made" in result.output
    assert fake.calls == [("GET", "/api/v1/device-templates/pod-high", None)]


def test_device_template_rename_prints_reference_warning(monkeypatch):
    response = {
        "device_template": {"id": 1, "name": "pod-renamed", "type": "pod8206hr"},
        "referencing_sessions": [{"id": "7", "name": "Run A"}],
        "warning": "referencing_sessions",
    }
    fake = FakeDaemonClient(posts=[response])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "rename", "--force", "pod-high", "pod-renamed"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "POST",
            "/api/v1/device-templates/pod-high/rename",
            {"new_name": "pod-renamed"},
        )
    ]
    assert "warning: 1 session template references this template: Run A (7)" in result.output
    assert _json_after_warning(result.output) == response


def test_device_template_delete_prints_reference_warning(monkeypatch):
    response = {
        "deleted_name": "pod-high",
        "referencing_sessions": [{"id": "7", "name": "Run A"}],
        "warning": "referencing_sessions",
    }
    fake = FakeDaemonClient(deletes=[response])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "delete", "--force", "pod-high"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [("DELETE", "/api/v1/device-templates/pod-high", None)]
    assert "warning: 1 session template references this template: Run A (7)" in result.output
    assert _json_after_warning(result.output) == response


def test_device_template_delete_accepts_numeric_id(monkeypatch):
    response = {"deleted_name": "pod-high", "referencing_sessions": []}
    fake = FakeDaemonClient(
        gets=[
            [
                {
                    "id": 7,
                    "name": "pod-high",
                    "type": "pod8206hr",
                    "content": {"type": "pod8206hr", "parameters": {"preamp_gain": 10}},
                }
            ]
        ],
        deletes=[response],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "delete", "--force", "7"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-templates", None),
        ("DELETE", "/api/v1/device-templates/pod-high", None),
    ]


def test_device_template_export_name_uses_daemon_template(monkeypatch):
    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "pod-high"],
    )

    assert result.exit_code != 0
    assert "Missing argument 'ARTIFACT_NAME'" in result.output


def test_device_template_export_from_config_prints_importable_toml(monkeypatch):
    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "--from-config", "7"],
    )

    assert result.exit_code != 0
    assert "No such option '--from-config'" in result.output


def test_device_template_export_uses_positional_reference_and_output_name(
    app, monkeypatch, tmp_path
):
    saved = {
        "id": 1,
        "name": "pod-left",
        "type": "pod8206hr",
        "content": {"type": "pod8206hr", "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2000,
            }},
    }
    config = {
        "id": 7,
        "type": "pod8206hr",
        "hardware_id": "A1B2C",
        "parameters": {
            "preamp_gain": "10",
            "sample_rate": "2000",
            },
        "nickname": "left-pod",
    }
    fake = FakeDaemonClient(gets=[[config], config], posts=[saved])
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "device-templates"
    _use_template_library_dir(monkeypatch, library_dir)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "left-pod", "pod-left", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-configs", None),
        ("GET", "/api/v1/device-configs/7", None),
        (
            "POST",
            "/api/v1/device-templates",
            {
                "name": "pod-left",
                "type": "pod8206hr",
                "parameters": {
                    "preamp_gain": "10",
                    "sample_rate": "2000",
                    },
            },
        ),
    ]
    assert "saved template: pod-left" in result.stderr


def test_device_template_export_from_config_with_name_saves_template(app, monkeypatch, tmp_path):
    saved = {
        "id": 1,
        "name": "pod-left",
        "type": "pod8206hr",
        "content": {
            "type": "pod8206hr",
            "parameters": {
                "preamp_gain": 10,
                "sample_rate": 2000,
                },
        },
    }
    fake = FakeDaemonClient(
        gets=[
            {
                "id": 7,
                "type": "pod8206hr",
                "hardware_id": "A1B2C",
                "port": "COM3",
                "parameters": {
                    "preamp_gain": "10",
                    "sample_rate": "2000",
                    },
                "nickname": "left-pod",
            },
            [],
        ],
        posts=[saved],
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "device-templates"
    _use_template_library_dir(monkeypatch, library_dir)
    saved_path = library_dir / "pod-left.toml"
    saved_path.unlink(missing_ok=True)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "7", "pod-left"],
    )
    saved_toml = saved_path.read_text(encoding="utf-8")

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-configs/7", None),
        ("GET", "/api/v1/device-templates", None),
        (
            "POST",
            "/api/v1/device-templates",
            {
                "name": "pod-left",
                "type": "pod8206hr",
                "parameters": {
                    "preamp_gain": "10",
                    "sample_rate": "2000",
                    },
            },
        ),
    ]
    expected_toml = (
        'name = "pod-left"\n'
        'type = "pod8206hr"\n'
        '\n'
        '[parameters]\n'
        'preamp_gain = 10\n'
        'sample_rate = 2000\n'
    )

    assert expected_toml in result.output
    assert saved_toml == expected_toml
    assert "saved template: pod-left" in result.stderr
    assert "saved TOML:" in result.stderr
    assert str(saved_path) in result.stderr


def test_device_template_export_from_config_blocks_duplicate_content(monkeypatch):
    artifact = {
        "name": "existing-pod",
        "type": "pod8206hr",
        "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2000,
            },
    }
    fake = FakeDaemonClient(
        gets=[
            {
                "id": 7,
                "type": "pod8206hr",
                "hardware_id": "A1B2C",
                "port": "COM3",
                "parameters": {
                    "preamp_gain": "10",
                    "sample_rate": "2000",
                    },
                "nickname": "left-pod",
            },
            [
                {
                    "id": 1,
                    "name": "existing-pod",
                    "type": "pod8206hr",
                    "content": {
                        "type": "pod8206hr",
                        "parameters": {
                            "preamp_gain": 10,
                            "sample_rate": 2000,
                            },
                    },
                    "content_hash": device_template_content_hash(artifact),
                }
            ],
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["device", "template", "export", "7", "new-pod"],
    )

    assert result.exit_code != 0
    assert "Template content already exists as: existing-pod" in result.output
    assert "pass --force" in result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-configs/7", None),
        ("GET", "/api/v1/device-templates", None),
    ]


def test_device_template_export_from_config_force_allows_duplicate_content(app, monkeypatch, tmp_path):
    artifact = {
        "name": "existing-pod",
        "type": "pod8206hr",
        "parameters": {
            "preamp_gain": 10,
            "sample_rate": 2000,
            },
    }
    saved = {
        "id": 2,
        "name": "new-pod",
        "type": "pod8206hr",
        "content": {
            "type": "pod8206hr",
            "parameters": {
                "preamp_gain": 10,
                "sample_rate": 2000,
                },
        },
    }
    fake = FakeDaemonClient(
        gets=[
            {
                "id": 7,
                "type": "pod8206hr",
                "hardware_id": "A1B2C",
                "port": "COM3",
                "parameters": {
                    "preamp_gain": "10",
                    "sample_rate": "2000",
                    },
                "nickname": "left-pod",
            },
            [
                {
                    "id": 1,
                    "name": "existing-pod",
                    "type": "pod8206hr",
                    "content": {
                        "type": "pod8206hr",
                        "parameters": {
                            "preamp_gain": 10,
                            "sample_rate": 2000,
                            },
                    },
                    "content_hash": device_template_content_hash(artifact),
                }
            ],
        ],
        posts=[saved],
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    library_dir = tmp_path / "device-templates"
    _use_template_library_dir(monkeypatch, library_dir)
    saved_path = library_dir / "new-pod.toml"
    saved_path.unlink(missing_ok=True)

    result = CliRunner().invoke(
        pinnacle,
        [
            "device",
            "template",
            "export",
            "7",
            "new-pod",
            "--force",
        ],
    )
    saved_toml = saved_path.read_text(encoding="utf-8")

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("GET", "/api/v1/device-configs/7", None),
        (
            "POST",
            "/api/v1/device-templates",
            {
                "name": "new-pod",
                "type": "pod8206hr",
                "parameters": {
                    "preamp_gain": "10",
                    "sample_rate": "2000",
                    },
            },
        ),
    ]

    expected_toml = (
        'name = "new-pod"\n'
        'type = "pod8206hr"\n'
        '\n'
        '[parameters]\n'
        'preamp_gain = 10\n'
        'sample_rate = 2000\n'
    )
    
    assert expected_toml in result.output
    assert saved_toml == expected_toml


def test_device_command_daemon_down_exits_nonzero_without_traceback(monkeypatch):
    fake = FakeDaemonClient(
        error=DaemonUnavailable("daemon not running at http://127.0.0.1:5000")
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["device", "list"])

    assert result.exit_code != 0
    assert "daemon not running at http://127.0.0.1:5000" in result.output
    assert "Traceback" not in result.output
