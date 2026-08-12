from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli.daemon_client import DaemonError, DaemonUnavailable
from app.cli.main import pinnacle


class FakeDaemonClient:
    def __init__(
        self,
        *,
        posts=None,
        gets=None,
        stream_lines=None,
        error: Exception | None = None,
    ):
        self.posts = list(posts or [])
        self.gets = list(gets or [])
        self.stream_lines = list(stream_lines or [])
        self.error = error
        self.calls: list[tuple[str, str, object | None]] = []

    def post(self, path: str, payload):
        self.calls.append(("POST", path, payload))
        if self.error is not None:
            raise self.error
        return self.posts.pop(0)

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        if self.error is not None:
            raise self.error
        return self.gets.pop(0)

    def iter_lines(self, path: str, *, accept: str = "application/json", should_stop=None):
        self.calls.append(("STREAM", f"{path}|{accept}", None))
        if self.error is not None:
            raise self.error
        yield from self.stream_lines


def _use_fake_client(monkeypatch, fake: FakeDaemonClient) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)
    monkeypatch.setattr(session_cmd, "sleep", lambda _seconds: None)


def _first_json_object(output: str) -> tuple[dict[str, object], str]:
    decoder = json.JSONDecoder()
    parsed, end = decoder.raw_decode(output)
    return parsed, output[end:].lstrip()


def test_session_stop_posts_command_route(monkeypatch):
    fake = FakeDaemonClient(posts=[{"id": "12", "status": "ending", "command_id": "op-stop-1"}])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "stop", "12"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("POST", "/api/v1/sessions/12/commands/stop", {})]
    assert json.loads(result.output)["status"] == "ending"


def test_session_stop_wait_failed_operation_exits_nonzero(monkeypatch):
    fake = FakeDaemonClient(
        posts=[{"id": "12", "status": "ending", "command_id": "op-stop-1"}],
        gets=[
            {
                "operation_id": "op-stop-1",
                "state": "failed",
                "error_message": "watchdog refused stop",
            }
        ],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "stop", "12", "--wait"])

    assert result.exit_code != 0
    assert "operation op-stop-1 failed" in result.output
    assert "watchdog refused stop" in result.output
    assert "Traceback" not in result.output


def test_session_command_daemon_error_exits_nonzero_without_traceback(monkeypatch):
    fake = FakeDaemonClient(
        error=DaemonError("Conflict", "Session already has a command in flight.", status_code=423)
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "stop", "12"])

    assert result.exit_code != 0
    assert "Conflict: Session already has a command in flight." in result.output
    assert "Traceback" not in result.output


def _status_snapshot_with_sinks() -> dict[str, object]:
    """A status snapshot: healthy running source with a mix of sink conditions.

    Covers every axis packet 22A must distinguish independently of source health:
    a healthy finalizing file sink, a degraded buffering/losing service sink with
    a sink-scoped incident and redacted diagnostics, a stale file sink carrying
    only durable output evidence, and an unknown-freshness sink.
    """
    return {
        "session": {"id": 12, "name": "bench-run", "status": "active"},
        "health": "healthy",
        "phase": "running",
        "latest_report": {
            "sequence": 42,
            "comms": "current",
            "received_at": "2026-07-20T00:05:00",
            "devices": [{"device_id": "pod-1", "stream_status": "healthy"}],
        },
        "runtimes": [],
        "operations": [],
        "incidents": [],
        "gaps": [],
        "sinks": [
            {
                "source_id": "pod-1",
                "sink_id": "csv",
                "sink_class": "file",
                "status": "current",
                "last_update": "2026-07-20T00:05:00",
                "health": "healthy",
                "delivery": "delivered",
                "finalization": "finalizing",
                "component": None,
                "buffered_samples": 0,
                "buffered_bytes": 0,
                "sample_loss": 0,
                "byte_loss": 0,
                "sink_sequence": 100,
                "diagnostics": None,
                "open_incidents": [],
                "output": {
                    "logical_sink_id": "ls-1",
                    "artifact_state": "merging",
                    "delivery_state": "delivered",
                    "sample_loss": 0,
                    "byte_loss": 0,
                },
            },
            {
                "source_id": "pod-1",
                "sink_id": "influx",
                "sink_class": "service",
                "status": "current",
                "last_update": "2026-07-20T00:05:00",
                "health": "degraded",
                "delivery": "delivering",
                "finalization": "none",
                "component": "influx-writer",
                "buffered_samples": 250,
                "buffered_bytes": 8192,
                "sample_loss": 12,
                "byte_loss": 480,
                "sink_sequence": 98,
                "diagnostics": {
                    "failure_kind": "connection_timeout",
                    "exception_type": "TimeoutError",
                    "message": "connect timed out",
                    "last_success_seq": 97,
                    "api_token": "SUPER_SECRET_TOKEN_VALUE",
                },
                "open_incidents": [
                    {
                        "incident_id": "inc-5",
                        "status": "open",
                        "reason": "delivery stalled",
                    }
                ],
                "output": None,
            },
            {
                "source_id": "pod-2",
                "sink_id": "csv",
                "sink_class": "file",
                "status": "stale",
                "last_update": None,
                "health": None,
                "delivery": None,
                "finalization": None,
                "component": None,
                "buffered_samples": None,
                "buffered_bytes": None,
                "sample_loss": None,
                "byte_loss": None,
                "sink_sequence": None,
                "diagnostics": None,
                "open_incidents": [],
                "output": {
                    "logical_sink_id": "ls-2",
                    "artifact_state": "merged",
                    "delivery_state": "delivered",
                    "sample_loss": 0,
                    "byte_loss": 0,
                },
            },
            {
                "source_id": "pod-2",
                "sink_id": "quest",
                "sink_class": "service",
                "status": "unknown",
                "last_update": None,
                "health": None,
                "delivery": None,
                "finalization": None,
                "component": None,
                "buffered_samples": None,
                "buffered_bytes": None,
                "sample_loss": None,
                "byte_loss": None,
                "sink_sequence": None,
                "diagnostics": None,
                "open_incidents": [],
                "output": None,
            },
        ],
    }


def test_session_status_renders_sinks_separately_from_source_health(monkeypatch):
    fake = FakeDaemonClient(gets=[_status_snapshot_with_sinks()])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "status", "12"])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("GET", "/api/v1/sessions/12/status", None)]
    out = result.output

    # Source axis is unchanged and never derived from sinks: the source stays
    # healthy even though a sibling sink is degraded/failing.
    assert "health:    healthy" in out
    assert "phase:     running" in out

    # A clearly labeled, source-grouped per-sink section.
    assert "\nsinks:" in out
    assert "  source pod-1:" in out
    assert "  source pod-2:" in out

    # Healthy finalizing file sink: freshness is its own vocabulary; durable
    # output evidence renders even alongside the live axes.
    assert "sink csv (file) status=current" in out
    assert "finalization=finalizing" in out
    assert "output: logical=ls-1 artifact=merging delivery=delivered loss=0/0" in out

    # Degraded service sink: buffering, permanent loss, active component, and a
    # sink-scoped incident all attributable to THIS sink.
    assert "sink influx (service) status=current" in out
    assert "health=degraded" in out
    assert "component=influx-writer" in out
    assert "buffered=250 samples / 8192 bytes" in out
    assert "loss=12 samples / 480 bytes" in out
    assert "inc-5 open delivery stalled" in out

    # Diagnostics are redacted to the allowlist: the secret token never prints.
    assert "failure_kind=connection_timeout" in out
    assert "SUPER_SECRET_TOKEN_VALUE" not in out
    assert "api_token" not in out


def test_session_status_marks_stale_and_unknown_sinks_without_live_axes(monkeypatch):
    fake = FakeDaemonClient(gets=[_status_snapshot_with_sinks()])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "status", "12"])

    assert result.exit_code == 0, result.output
    out = result.output
    # A sink with no live report is never rendered as healthy: freshness reads
    # stale/unknown and every live axis shows '-'.
    assert "sink csv (file) status=stale" in out
    assert "sink quest (service) status=unknown" in out
    assert "health=- delivery=- finalization=- component=-" in out
    # Durable output evidence still surfaces for the stale sink.
    assert "output: logical=ls-2 artifact=merged delivery=delivered loss=0/0" in out


def test_session_status_legacy_snapshot_without_sinks_stays_readable(monkeypatch):
    snapshot = _status_snapshot_with_sinks()
    del snapshot["sinks"]  # legacy daemon predating the per-sink contract
    fake = FakeDaemonClient(gets=[snapshot])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "status", "12"])

    assert result.exit_code == 0, result.output
    out = result.output
    # Source-only status still renders; the sinks section is simply omitted.
    assert "health:    healthy" in out
    assert "\nsinks:" not in out


def test_session_status_empty_sink_list_renders_none(monkeypatch):
    snapshot = _status_snapshot_with_sinks()
    snapshot["sinks"] = []
    fake = FakeDaemonClient(gets=[snapshot])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "status", "12"])

    assert result.exit_code == 0, result.output
    assert "\nsinks:\nnone" in result.output


def test_session_status_json_flag_passes_sinks_through_untouched(monkeypatch):
    snapshot = _status_snapshot_with_sinks()
    fake = FakeDaemonClient(gets=[snapshot])
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "status", "12", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [s["sink_id"] for s in payload["sinks"]] == ["csv", "influx", "csv", "quest"]


def test_session_watch_renders_per_sink_status_line_redacted(monkeypatch):
    report = {
        "phase": "running",
        "sequence": 7,
        "sinks": [
            {
                "source_id": "pod-1",
                "sink_id": "influx",
                "sink_class": "service",
                "status": "current",
                "health": "failed",
                "delivery": "failed",
                "finalization": "none",
                "component": "influx-writer",
                "buffered_samples": 500,
                "buffered_bytes": 16384,
                "sample_loss": 3,
                "byte_loss": 120,
                "sink_sequence": 41,
                "diagnostics": {
                    "failure_kind": "connection_refused",
                    "exception_type": "ConnectionError",
                    "message": "refused",
                    "last_success_seq": 40,
                    "api_token": "SUPER_SECRET_TOKEN_VALUE",
                },
                "output": {"artifact_state": "merge_pending", "delivery_state": "failed"},
            }
        ],
    }
    fake = FakeDaemonClient(
        stream_lines=[
            "id: 1",
            "event: runtime.report",
            f"data: {json.dumps(report)}",
            "",
        ]
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "watch", "12"])

    assert result.exit_code == 0, result.output
    out = result.output
    # The source/session line still renders, and a SEPARATE per-sink line makes
    # the failing sink attributable to its own identity, not to the source.
    assert "sink status" in out
    assert "sink_id=influx" in out
    assert "source_id=pod-1" in out
    assert "sink_health=failed" in out
    # Redaction holds on the live channel too.
    assert "failure_kind=connection_refused" in out
    assert "SUPER_SECRET_TOKEN_VALUE" not in out
