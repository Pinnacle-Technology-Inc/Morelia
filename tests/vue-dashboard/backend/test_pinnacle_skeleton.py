import importlib
import json
import tomllib
from pathlib import Path

import click
from click.testing import CliRunner

from app.cli.main import pinnacle
from app.cli.output import echo_json, echo_table


def test_pinnacle_help_runs_without_daemon() -> None:
    result = CliRunner().invoke(pinnacle, ["--help"])

    assert result.exit_code == 0
    assert "Usage: pinnacle" in result.output


def test_echo_json_uses_sorted_indented_json() -> None:
    @click.command()
    def command() -> None:
        echo_json({"z": 1, "a": {"b": 2}})

    result = CliRunner().invoke(command)

    assert result.exit_code == 0
    assert result.output == json.dumps({"z": 1, "a": {"b": 2}}, indent=2, sort_keys=True) + "\n"


def test_echo_table_renders_aligned_columns() -> None:
    rows = [
        {"operation_id": "op-1", "state": "pending"},
        {"operation_id": "op-2", "state": None},
    ]

    @click.command()
    def command() -> None:
        echo_table(rows, ["operation_id", "state"])

    result = CliRunner().invoke(command)

    assert result.exit_code == 0
    assert result.output == "operation_id    state\nop-1            pending\nop-2            -\n"


def test_control_plane_base_url_defaults_to_local_daemon(monkeypatch) -> None:
    monkeypatch.delenv("PINNACLE_DAEMON_URL", raising=False)

    config = importlib.reload(importlib.import_module("app.config"))

    assert config.Config.CONTROL_PLANE_BASE_URL == "http://127.0.0.1:5000"


def test_control_plane_base_url_reads_ged_daemon_url(monkeypatch) -> None:
    monkeypatch.setenv("PINNACLE_DAEMON_URL", "http://daemon.example:9000")

    config = importlib.reload(importlib.import_module("app.config"))
    try:
        assert config.Config.CONTROL_PLANE_BASE_URL == "http://daemon.example:9000"
    finally:
        monkeypatch.delenv("PINNACLE_DAEMON_URL", raising=False)
        importlib.reload(config)
