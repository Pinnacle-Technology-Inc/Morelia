from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli.daemon_client import DaemonUnavailable
from app.cli.main import pinnacle


class FakeDaemonClient:
    def __init__(self, *, gets=None, posts=None, error: Exception | None = None) -> None:
        self.gets = list(gets or [])
        self.posts = list(posts or [])
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


def _use_fake_client(monkeypatch, fake: FakeDaemonClient) -> None:
    import app.cli.runtime_cmd as runtime_cmd

    monkeypatch.setattr(runtime_cmd, "DaemonClient", lambda: fake)


def test_runtime_list_renders_ownership_rows(monkeypatch):
    fake = FakeDaemonClient(
        gets=[
            [
                {
                    "runtime_id": "rt-active",
                    "session_id": 7,
                    "dataflow_id": "df-active",
                    "state": "running",
                    "pid": 1234,
                    "port": 8206,
                    "last_seen_at": "2026-06-30T12:00:00",
                }
            ]
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["runtime", "list"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/runtimes/", None)]
    assert result.output == (
        "runtime_id\tsession_id\tdataflow_id\tstate\tpid\tport\tlast_seen_at\n"
        "rt-active\t7\tdf-active\trunning\t1234\t8206\t2026-06-30T12:00:00\n"
    )


def test_runtime_list_empty_prints_clear_message(monkeypatch):
    fake = FakeDaemonClient(gets=[[]])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["runtime", "list"])

    assert result.exit_code == 0, result.output
    assert result.output == "no runtimes\n"


def test_runtime_reconcile_prints_summary_json(monkeypatch):
    summary = {
        "succeeded_operations": 1,
        "failed_operations": 2,
        "uncertain_operations": 3,
        "adopted_runtimes": 4,
        "stopped_runtimes": 5,
        "uncertain_runtimes": 6,
    }
    fake = FakeDaemonClient(posts=[summary])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["runtime", "reconcile"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("POST", "/api/v1/runtimes/reconcile", {})]
    assert json.loads(result.output) == summary


def test_runtime_command_daemon_down_exits_nonzero_without_traceback(monkeypatch):
    fake = FakeDaemonClient(
        error=DaemonUnavailable("daemon not running at http://127.0.0.1:5000")
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["runtime", "list"])

    assert result.exit_code != 0
    assert "daemon not running at http://127.0.0.1:5000" in result.output
    assert "Traceback" not in result.output
