from contextlib import contextmanager
import importlib
import json
from types import SimpleNamespace

import pytest

from Morelia.Watchdog.watchdog import StreamWatcher
from app.services.session_status import _latest_report_device
from .test_watchdog_lifecycle import FakeWorker, make_multi_stream_monitor


class Monitor:
    def __init__(self, shutdown):
        self.shutdown = shutdown
        self.state = {"state": "running"}
        self.present = True
        self.openable = True
        self.stop_calls = self.restart_calls = self.probe_calls = 0
        self.worker_status = "dead"
        self.restart_error = None

    def get_lifecycle_state(self, _index):
        return self.state

    def set_lifecycle_state(self, _index, state, **details):
        self.state = {"state": state, **details}
        return self.state

    @contextmanager
    def stream_lifecycle_guard(self, _index, **_kwargs):
        yield None

    def get_stream_status(self, _index):
        return {"worker_status": self.worker_status, "worker_exitcode": -15}

    def get_stream_heartbeat(self, *_args):
        return {"state": "stale", "packet_count": 100}

    def is_stream_port_present(self, _index):
        return self.present

    def is_stream_port_openable(self, _index):
        self.probe_calls += 1
        return self.openable

    def stop_stream(self, _index):
        self.stop_calls += 1
        if isinstance(self.shutdown, Exception):
            raise self.shutdown
        return self.shutdown

    def restart_one_stream(self, _index):
        self.restart_calls += 1
        return {"ok": self.restart_error is None, "error": self.restart_error}

    def poll_stream_queue_roundtrip(self, **_kwargs):
        return {"ok": True}


def watcher(monitor):
    return StreamWatcher(0, monitor, failure_threshold=1, max_heartbeat_age_sec=10,
                         interval_sec=1, timeout_sec=1, recovery_policy="automate",
                         publish=lambda *_args: None)


@pytest.mark.parametrize("entry", ["worker_failure", "disconnect", "heartbeat_grace", "cold_open"])
@pytest.mark.parametrize("shutdown", [
    {"ok": False, "teardown_confirmed": False, "worker_exited": False},
    {"ok": False, "worker_exited": False},
    RuntimeError("shutdown deadline expired"),
    {"ok": False, "teardown_confirmed": False, "transcript": (
        SimpleNamespace(phase="phase_failed", outcome="failed", reason="writer still running",
                        error_type="TimeoutError"),
    )},
])
def test_cleanup_failure_stops_recovery_and_remains_visible(entry, shutdown):
    monitor = Monitor(shutdown)
    subject = watcher(monitor)
    if entry == "worker_failure":
        result = subject._watch_stream()
    elif entry == "disconnect":
        monitor.present = False
        subject._port_absent_since = 0
        subject._port_absent_packet_count = 100
        result = subject._observe_physical_port({})
    elif entry == "heartbeat_grace":
        monitor.worker_status = "alive"
        subject._response_grace = {"remaining": 1, "max_attempts": 1, "results": [],
                                   "restart_result": {"ok": True}, "verify_result": {"ok": False}}
        result = subject._advance_response_grace({})
    else:
        result = subject._back_off_worker_cold_open({}, {}, {}, {})

    assert result["action"] == "needs_action"
    assert result["initiating_failure_reason"] == "cleanup_failed"
    assert "Stop the session" in result["error"]
    for present in [False, True, False, True]:
        monitor.present = present
        repeated = subject._watch_stream()
        assert repeated["action"] == "needs_action"
        assert repeated["error"] == result["error"]
        assert repeated["shutdown_result"] == result["shutdown_result"]
        assert repeated["recommended_commands"] == []
        report = subject._build_verbose_stream_report(0, repeated)
        assert report["summary"] == result["error"]
        assert report["stream_health"] == "unhealthy"
        json.dumps(report)
    assert monitor.stop_calls == 1
    assert monitor.probe_calls == monitor.restart_calls == 0


@pytest.mark.parametrize("shutdown", [
    {"ok": False, "teardown_confirmed": True},
    {"ok": False, "teardown_confirmed": False, "worker_exited": True},
])
def test_confirmed_worker_exit_can_recover_despite_unclean_recording_receipt(shutdown):
    monitor = Monitor(shutdown)
    subject = watcher(monitor)
    assert subject._watch_stream()["action"] == "stopped_stream_waiting_for_reconnect"
    assert subject._watch_stream()["action"] == "connection_restored"


@pytest.mark.parametrize("path", ["probe", "restart", "cold_open"])
def test_port_release_retry_has_deadline_and_requires_explicit_retry(monkeypatch, path):
    clock = [100.0]
    module = importlib.import_module("Morelia.Watchdog.watchdog")
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monitor = Monitor({"ok": True, "teardown_confirmed": True})
    subject = watcher(monitor)
    subject._disconnected = True
    monitor.openable = path != "probe"
    monitor.restart_error = "PermissionError: Access is denied" if path == "restart" else None
    if path == "cold_open":
        result = subject._back_off_worker_cold_open({}, {}, {}, {})
    else:
        result = subject._watch_stream()
    assert result["action"] == "waiting_for_port_release"
    clock[0] += 14.9
    if path != "cold_open":
        assert subject._watch_stream()["action"] == "waiting_for_port_release"
    clock[0] += .1
    before = (monitor.probe_calls, monitor.restart_calls, monitor.stop_calls)
    result = subject._watch_stream()
    assert result["action"] == "needs_action"
    assert result["initiating_failure_reason"] == "port_release_timeout"
    assert "15 seconds" in result["error"]
    for present in [False, True]:
        monitor.present = present
        assert subject._watch_stream()["error"] == result["error"]
    assert (monitor.probe_calls, monitor.restart_calls, monitor.stop_calls) == before
    subject.clear_recovery_state()
    monitor.set_lifecycle_state(0, "running")
    monitor.restart_error = None
    monitor.openable = True
    subject._disconnected = True
    assert subject._watch_stream()["action"] == "connection_restored"


@pytest.mark.parametrize("operation", ["stop_stream", "restart_one_stream"])
def test_dashboard_shutdown_default_is_15_seconds_and_leaves_peer_running(monkeypatch, operation):
    monitor = make_multi_stream_monitor(2, lambda _index, events: FakeWorker(events))
    allowances = []
    original = monitor._stop_worker

    def record_allowance(worker, event, index, allowance, **kwargs):
        allowances.append(allowance)
        return original(worker, event, index, allowance, **kwargs)

    monkeypatch.setattr(monitor, "_stop_worker", record_allowance)
    monkeypatch.setattr(monitor, "reset_stream_device", lambda _index: {"ok": True})
    monkeypatch.setattr(monitor, "_clear_stream_heartbeat_unlocked", lambda _index: {})
    monkeypatch.setattr(monitor, "_start_stream_unlocked", lambda _index: {"ok": True})
    result = getattr(monitor, operation)(0)
    assert result["ok"] is True
    assert allowances == [15.0]
    assert monitor.flowgraph._workers[1].is_alive()


@pytest.mark.parametrize("reason", ["cleanup_failed", "port_release_timeout"])
@pytest.mark.parametrize("present", [False, True])
def test_dashboard_preserves_recovery_error_over_worker_fault(reason, present):
    row = _latest_report_device(
        {"device_id": "pod", "stream_status": "unhealthy"},
        {"action": "needs_action", "initiating_failure_reason": reason,
         "recovery": {"hardware_present": present, "policy": "automate"},
         "worker": {"fault": {"reason": "protocol_violation"}}},
        interval_seconds=1,
        controls_current=True,
    )
    assert row["reason"] == reason
    assert row["pending_recovery"] is False
    assert row["recovery_state"] == "exhausted"
    assert row["allowed_recovery_actions"] == (["restart"] if present and reason == "port_release_timeout" else [])
    assert row["worker_fault"]["reason"] == "protocol_violation"
