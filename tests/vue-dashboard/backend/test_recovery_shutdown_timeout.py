from contextlib import contextmanager
import importlib
import json
import threading
from types import SimpleNamespace

import pytest

from Morelia.Watchdog.watchdog import StreamWatcher
from app.runtime_child.morelia import MoreliaRuntime
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


@pytest.mark.parametrize("present,openable,restart_error,action", [
    (False, True, None, "waiting_for_port"),
    (True, False, None, "waiting_for_port_release"),
    (True, True, "configuration invalid", "restart_failed"),
    (True, True, None, "connection_restored"),
])
def test_reconnect_reports_observed_hardware_presence(present, openable, restart_error, action):
    monitor = Monitor({"ok": True})
    monitor.present = present
    monitor.openable = openable
    monitor.restart_error = restart_error
    subject = watcher(monitor)

    result = subject._try_reconnect()

    assert result["action"] == action
    assert result["hardware_present"] is present


def test_reconnect_presence_error_stays_unknown_after_a_positive_check(monkeypatch):
    monitor = Monitor({"ok": True})
    monitor.openable = False
    subject = watcher(monitor)
    assert subject._try_reconnect()["hardware_present"] is True

    def unavailable(_index):
        raise RuntimeError("Native inventory contains unidentified interfaces")

    monkeypatch.setattr(monitor, "is_stream_port_present", unavailable)
    result = subject._try_reconnect()

    assert result["action"] == "port_check_failed"
    assert result["hardware_present"] is None
    assert "unidentified interfaces" in result["error"]
    assert monitor.restart_calls == 0


@pytest.mark.parametrize("fresh_heartbeat", [False, True])
def test_reconnect_presence_reaches_dashboard_through_heartbeat_grace(monkeypatch, fresh_heartbeat):
    monitor = Monitor({"ok": True})
    monitor.worker_status = "alive"
    monkeypatch.setattr(monitor, "poll_stream_queue_roundtrip", lambda **_kwargs: {"ok": False})
    monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {"state": "missing", "packet_count": 0})
    subject = StreamWatcher(
        0, monitor, failure_threshold=3, max_heartbeat_age_sec=10,
        interval_sec=1, timeout_sec=1, recovery_policy="automate",
        max_auto_restart_attempts=1, publish=lambda *_args: None,
    )
    runtime = MoreliaRuntime(
        manifest=SimpleNamespace(device_flows=[SimpleNamespace(device_id="pod", port="test")]),
        on_report=lambda *_args: None,
    )

    for tick in range(3):
        if tick == 2 and fresh_heartbeat:
            monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {"state": "fresh", "packet_count": 1})
        result = subject._try_reconnect()
        assert result["hardware_present"] is True
        report = subject._build_verbose_stream_report(0, result)
        diagnostic = runtime._watchdog_diagnostics([report])["streams"][0]
        row = _latest_report_device(
            {"device_id": "pod", "stream_status": report["stream_health"]},
            diagnostic, interval_seconds=1, session_policy="automate", controls_current=True,
        )
        assert row["hardware_present"] is True
        if tick < 2:
            assert result["action"] == "waiting_for_heartbeat"
            assert row["recovery_state"] == "recovering"

    assert result["action"] == ("connection_restored" if fresh_heartbeat else "needs_action")
    assert monitor.restart_calls == 1
    assert monitor.probe_calls == 1


def test_recovery_progress_is_published_before_blocked_ping_and_retains_completion(monkeypatch):
    monitor = Monitor({"ok": True, "teardown_confirmed": True})
    reports = []
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {"state": "missing", "packet_count": 0})
    subject = watcher(monitor)
    subject._publish = lambda _index, report: reports.append(report)

    def check_stage(stage):
        assert reports[-1]["recovery_progress"]["stage"] == stage

    def stop(_index):
        check_stage("stopping_stream")
        return {"ok": True}

    def present(_index):
        check_stage("checking_presence")
        return True

    def openable(_index):
        check_stage("checking_port")
        return True

    def restart(_index):
        check_stage("restarting_stream")
        monitor.worker_status = "alive"
        return {"ok": True}

    def ping(**_kwargs):
        check_stage("waiting_for_ping")
        entered.set()
        assert release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(monitor, "stop_stream", stop)
    subject._stop_for_recovery({})
    monkeypatch.setattr(monitor, "is_stream_port_present", present)
    monkeypatch.setattr(monitor, "is_stream_port_openable", openable)
    monkeypatch.setattr(monitor, "restart_one_stream", restart)
    monkeypatch.setattr(monitor, "poll_stream_queue_roundtrip", ping)
    result = []
    thread = threading.Thread(target=lambda: result.append(subject._try_reconnect()))
    thread.start()
    try:
        assert entered.wait(5)
        progress = reports[-1]["recovery_progress"]
        assert progress["stage"] == "waiting_for_ping"
        assert progress["ping_status"] == "pending"
        assert [step["stage"] for step in progress["history"]] == [
            "detected", "stopping_stream", "checking_presence", "checking_port", "restarting_stream", "waiting_for_ping",
        ]
        assert all(report["recovery_event"]["status"] == "pending" for report in reports)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    completed = subject._build_verbose_stream_report(0, result[0])
    assert completed["recovery_progress"]["stage"] == "recovery_verified"
    assert completed["recovery_progress"]["verification"] == "ping"
    assert completed["recovery_progress"]["ping_status"] == "passed"
    assert "waiting for real samples" in completed["summary"]
    assert progress["stage"] == "waiting_for_ping"

    monkeypatch.setattr(monitor, "is_stream_port_present", lambda _index: True)
    monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {"state": "fresh", "packet_count": 1})
    for _ in range(2):
        healthy = subject._build_verbose_stream_report(0, subject._watch_stream())
        assert healthy["recovery_progress"]["stage"] == "streaming"
        assert healthy["recovery_progress"]["verification"] == "data"
        assert healthy["recovery_progress"]["history"][-2]["stage"] == "recovery_verified"


def test_progress_does_not_invent_recovery_during_initial_startup(monkeypatch):
    monitor = Monitor({"ok": True})
    monitor.worker_status = "alive"
    subject = watcher(monitor)
    for state, count in [("missing", 0), ("fresh", 1)]:
        monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {
            "state": state, "reason": "no_data_seen_yet" if not count else None,
            "packet_count": count,
        })
        report = subject._build_verbose_stream_report(0, subject._watch_stream())
        assert report["recovery_progress"] is None


def test_progress_history_and_errors_are_bounded_and_new_episode_clears_error():
    subject = watcher(Monitor({"ok": True}))
    for _ in range(20):
        subject._set_recovery_progress("checking_presence")
        subject._set_recovery_progress("presence_check_failed", error="x" * 1000)
    progress = subject._recovery_progress
    assert len(progress["history"]) == 16
    assert len(progress["last_error"]) == 500
    subject._set_recovery_progress("streaming", verification="data", clear_error=True)
    assert subject._recovery_progress["last_error"] is None
    subject._set_recovery_progress("detected")
    assert subject._recovery_progress["verification"] is None
    assert [step["stage"] for step in subject._recovery_progress["history"]] == ["detected"]
    subject._set_recovery_progress("presence_check_failed", error="inventory unavailable")
    subject._set_recovery_progress("detected")
    assert subject._recovery_progress["last_error"] is None


def test_failed_ping_progress_preserves_error_until_data_verifies_recovery(monkeypatch):
    monitor = Monitor({"ok": True})
    monitor.worker_status = "alive"
    subject = watcher(monitor)
    monkeypatch.setattr(monitor, "poll_stream_queue_roundtrip", lambda **_kwargs: {
        "ok": False, "error": "PING response timed out",
    })
    monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {"state": "missing", "packet_count": 0})
    waiting = subject._build_verbose_stream_report(0, subject._try_reconnect())
    assert waiting["recovery_progress"]["stage"] == "waiting_for_data"
    assert waiting["recovery_progress"]["ping_status"] == "failed"
    assert waiting["recovery_progress"]["last_error"] == "PING response timed out"
    monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {"state": "fresh", "packet_count": 1})
    restored = subject._build_verbose_stream_report(0, subject._try_reconnect())
    progress = restored["recovery_progress"]
    assert progress["stage"] == "streaming"
    assert progress["verification"] == "data"
    assert progress["ping_status"] == "failed"
    assert progress["last_error"] is None
    assert [step["stage"] for step in progress["history"]][-3:] == ["waiting_for_data", "recovery_verified", "streaming"]


def test_new_failure_after_ping_success_clears_previous_verification(monkeypatch):
    monitor = Monitor({"ok": True, "teardown_confirmed": True})
    subject = watcher(monitor)
    monkeypatch.setattr(monitor, "get_stream_heartbeat", lambda *_args: {
        "state": "missing", "packet_count": 0,
    })

    def restart(_index):
        monitor.worker_status = "alive"
        return {"ok": True}

    monkeypatch.setattr(monitor, "restart_one_stream", restart)
    subject._watch_stream()
    recovered = subject._build_verbose_stream_report(0, subject._watch_stream())
    assert recovered["recovery_progress"]["verification"] == "ping"
    assert recovered["recovery_progress"]["stage"] == "recovery_verified"

    monitor.worker_status = "dead"
    monkeypatch.setattr(monitor, "poll_stream_queue_roundtrip", lambda **_kwargs: {
        "ok": False, "error": "PING response timed out",
    })
    stopped = subject._build_verbose_stream_report(0, subject._watch_stream())
    assert stopped["recovery_progress"]["verification"] is None
    assert stopped["recovery_progress"]["ping_status"] is None
    waiting = subject._build_verbose_stream_report(0, subject._watch_stream())
    assert waiting["recovery_progress"]["stage"] == "waiting_for_data"
    assert waiting["recovery_progress"]["ping_status"] == "failed"
    assert waiting["recovery_progress"]["verification"] is None


def test_changed_progress_wakes_reporter_without_repeated_identical_ticks():
    from Morelia.Watchdog.watchdog import Watchdog

    subject = Watchdog.__new__(Watchdog)
    subject._results_lock = threading.Lock()
    subject._stream_results = {}
    subject._urgent_report_event = threading.Event()
    subject._on_stream_result = None
    report = {"action": {"taken": "recovery_waiting_for_ping"},
              "recovery_progress": {"stage": "waiting_for_ping"}}
    subject._publish_stream(0, report)
    assert subject._urgent_report_event.is_set()
    subject._urgent_report_event.clear()
    subject._publish_stream(0, dict(report))
    assert not subject._urgent_report_event.is_set()
