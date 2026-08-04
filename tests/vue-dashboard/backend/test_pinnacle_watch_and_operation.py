from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli.daemon_client import DaemonError, DaemonUnavailable
from app.cli.main import pinnacle


class FakeDaemonClient:
    def __init__(
        self,
        *,
        gets=None,
        stream_lines=None,
        error: Exception | None = None,
    ) -> None:
        self.gets = list(gets or [])
        self.posts = []
        self.stream_lines = list(stream_lines or [])
        self.error = error
        self.calls: list[tuple[str, str, object | None]] = []

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        if self.error is not None:
            raise self.error
        return self.gets.pop(0)

    def post(self, path: str, payload: dict[str, object]):
        self.calls.append(("POST", path, payload))
        if self.error is not None:
            raise self.error
        return self.posts.pop(0) if self.posts else {}

    def iter_lines(self, path: str, *, accept: str = "application/json", should_stop=None):
        self.calls.append(("STREAM", f"{path}|{accept}", None))
        if self.error is not None:
            raise self.error
        yield from self.stream_lines


def test_session_watch_passes_initial_cursor(monkeypatch):
    fake = FakeDaemonClient(stream_lines=[])
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(pinnacle, ["session", "watch", "12", "--after", "41"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("STREAM", "/api/v1/sessions/12/events?after=41|text/event-stream", None)]


def test_session_watch_ctrl_c_exits_without_traceback(monkeypatch):
    class InterruptingDaemonClient:
        def iter_lines(self, path: str, *, accept: str = "application/json", should_stop=None):
            raise KeyboardInterrupt
            yield

    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", InterruptingDaemonClient)

    result = CliRunner().invoke(pinnacle, ["session", "watch", "12"])

    assert result.exit_code == 130
    assert "Traceback" not in result.output


def test_session_watch_daemon_down_exits_nonzero_without_traceback(monkeypatch):
    fake = FakeDaemonClient(
        error=DaemonUnavailable("daemon not running at http://127.0.0.1:5000")
    )
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(pinnacle, ["session", "watch", "12"])

    assert result.exit_code != 0
    assert "daemon not running at http://127.0.0.1:5000" in result.output
    assert "Traceback" not in result.output


def test_operation_show_prints_daemon_operation_json(monkeypatch):
    fake = FakeDaemonClient(
        gets=[
            {
                "operation_id": "op-1",
                "state": "succeeded",
                "command": "start",
            }
        ]
    )
    import app.cli.operation_cmd as operation_cmd

    monkeypatch.setattr(operation_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(pinnacle, ["operation", "show", "op-1"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/operations/op-1", None)]
    assert json.loads(result.output) == {
        "operation_id": "op-1",
        "state": "succeeded",
        "command": "start",
    }


def test_operation_list_empty_prints_no_operations(monkeypatch):
    fake = FakeDaemonClient(gets=[[]])
    import app.cli.operation_cmd as operation_cmd

    monkeypatch.setattr(operation_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(pinnacle, ["operation", "list"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/operations/", None)]
    assert result.output == "no operations\n"


def test_operation_resolve_posts_resolution_to_daemon(monkeypatch):
    fake = FakeDaemonClient()
    fake.posts.append(
        {
            "operation_id": "op-1",
            "state": "uncertain",
            "resolved_by": "operator@example.com",
            "resolution_note": "Verified runtime manually.",
        }
    )
    import app.cli.operation_cmd as operation_cmd

    monkeypatch.setattr(operation_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(
        pinnacle,
        [
            "operation",
            "resolve",
            "op-1",
            "--by",
            "operator@example.com",
            "--note",
            "Verified runtime manually.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        (
            "POST",
            "/api/v1/operations/op-1/resolve",
            {
                "resolved_by": "operator@example.com",
                "resolution_note": "Verified runtime manually.",
            },
        )
    ]
    assert json.loads(result.output)["resolved_by"] == "operator@example.com"


def test_operation_show_unknown_id_exits_nonzero_with_daemon_detail(monkeypatch):
    fake = FakeDaemonClient(
        error=DaemonError("Not Found", "No operation with id 'missing'.", status_code=404)
    )
    import app.cli.operation_cmd as operation_cmd

    monkeypatch.setattr(operation_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(pinnacle, ["operation", "show", "missing"])

    assert result.exit_code != 0
    assert "Not Found: No operation with id 'missing'." in result.output
    assert "Traceback" not in result.output


def test_session_stop_force_posts_force_payload(monkeypatch):
    fake = FakeDaemonClient()
    fake.posts.append({"id": 12, "command_id": "op-stop", "status": "ending"})
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)

    result = CliRunner().invoke(pinnacle, ["session", "stop", "12", "--force"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("POST", "/api/v1/sessions/12/commands/stop", {"force": True})
    ]
