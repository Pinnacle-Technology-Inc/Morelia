"""Builder checks: real timer/SQLite, substituted hardware driver and HTTP delivery.

These focused tests do not certify physical cutoff or real sink durability.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import threading
import time

import pytest

from app.runtime_child.driver import RuntimePhase
from app.watchdog_process.outbox import WatchdogOutbox, read_lifecycle_reports
from app.watchdog_process.process import WatchdogIdentity, WatchdogProcess, remaining_recording_seconds
from app.watchdog_process.telemetry_client import TelemetryClient


class Driver:
    def __init__(self, **kwargs):
        self.phase = RuntimePhase.RUNNING
        self.cancel = threading.Event()
        self.stop_calls = 0
        self.shutdown_result = {"ok": True, "stream_results": [{"ok": True, "teardown_confirmed": True}]}

    def bind_lifecycle(self, **kwargs):
        self.lifecycle = kwargs

    def request_cancel(self):
        self.cancel.set()

    def stop(self):
        self.stop_calls += 1
        self.phase = RuntimePhase.STOPPED

    def close(self):
        self.phase = RuntimePhase.CLOSED


@pytest.fixture
def process(tmp_path):
    outbox = WatchdogOutbox(tmp_path / "outbox.sqlite3")
    proc = WatchdogProcess(
        manifest=SimpleNamespace(duration_seconds=1, dataflow_id="timed", hash="hash"),
        identity=WatchdogIdentity("host", "watchdog"), outbox=outbox,
        telemetry_client=TelemetryClient(base_url="http://offline", transport=lambda *_: (503, {})),
        build_driver=Driver)
    yield proc
    proc.shutdown()
    outbox.close()


def bounds(age=0, sink="csv"):
    sample = (datetime.now(UTC) - timedelta(seconds=age)).isoformat()
    return {"source_id": "device", "sink_id": sink, "first_sample_at": sample, "last_sample_at": sample}


def test_start_waits_for_arrival_then_expires_without_recording(process):
    time.sleep(.1)
    assert process.timing_evidence == {}
    assert not process.stopping
    sample = bounds(age=.7)
    process.first_data_received(sample["first_sample_at"])
    assert process.driver.cancel.wait(1)
    assert process.stop_intent["stop_reason"] == "duration_ended"
    assert process.timing_evidence["started_at"] == sample["first_sample_at"]
    assert process.timing_evidence["recording_bounds"] == []
    assert process.timing_evidence["ended_at"] is None


def test_delayed_arrival_event_does_not_grant_fresh_duration(process):
    process.first_data_received(bounds(age=10)["first_sample_at"])
    assert process.driver.cancel.wait(.5)
    assert process.stop_intent["stop_reason"] == "duration_ended"


def test_arrival_rejects_deadline_beyond_python_datetime_before_saving(process):
    with pytest.raises(ValueError, match="Python's datetime maximum"):
        process.first_data_received("9999-12-31T23:59:59.500000+00:00")
    assert process.timing_evidence == {}
    assert process._deadline_elapsed is None


def test_recovery_validates_original_start_even_on_same_boot():
    from app.watchdog_process.process import _remaining_recording_seconds
    evidence = {"started_at": "9999-12-31T23:59:58+00:00",
                "clock_anchor": {"kind": "test", "boot_id": "boot", "deadline_elapsed": 11}}
    assert _remaining_recording_seconds(evidence, 1, ("test", "boot", 10)) == 1
    with pytest.raises(ValueError, match="Python's datetime maximum"):
        _remaining_recording_seconds(evidence, 2, ("test", "boot", 10))


def test_recording_ack_cannot_start_timer_or_replace_arrival_origin(process):
    sample = bounds(age=30)
    process.recording_acknowledged(sample)
    assert process.timing_evidence == {}
    assert process._deadline_elapsed is None
    arrival = bounds()["first_sample_at"]
    process.first_data_received(arrival)
    deadline = process._deadline_elapsed
    process.first_data_received(bounds(age=10)["first_sample_at"])
    process.recording_acknowledged(bounds(sink="other"))
    assert process._deadline_elapsed == deadline
    assert process.timing_evidence["started_at"] == arrival
    assert process.timing_evidence["recording_bounds"][0] == sample


def test_arrival_only_checkpoint_restores_deadline_before_any_saved_sample(process, tmp_path):
    process.first_data_received(bounds()["first_sample_at"])
    evidence = read_lifecycle_reports(process.outbox.path)[0].envelope.payload
    assert evidence["recording_bounds"] == []
    with WatchdogOutbox(tmp_path / "restored.sqlite3") as outbox:
        replacement = WatchdogProcess(manifest=process.manifest,
            identity=WatchdogIdentity("host", "replacement"), outbox=outbox,
            telemetry_client=process._client, build_driver=Driver)
        try:
            replacement.restore_timing(evidence)
            assert replacement._deadline_elapsed == process._deadline_elapsed
            assert replacement.timing_evidence["started_at"] == evidence["started_at"]
            assert replacement.driver.cancel.wait(2)
        finally:
            replacement.shutdown()


def test_manual_request_wins_available_decision_even_after_utc_expiry(process):
    # A past sample time is not itself an accepted automatic stop.
    decision = process.request_stop("user_stop", command_id="manual")
    process.recording_acknowledged(bounds(age=10))
    time.sleep(.1)
    assert process.request_stop("duration_ended")["command_id"] == decision["command_id"]
    assert process.stop_intent["stop_reason"] == "user_stop"


def test_pending_manual_wins_and_cancels_while_checkpoint_holds_decision_lock(process):
    with process._decision_lock:
        expiry = threading.Thread(target=lambda: process.request_stop("duration_ended"))
        expiry.start()
        assert process.driver.cancel.wait(1), "cancellation must not wait for persistence"
        manual = threading.Thread(target=lambda: process.request_stop("user_stop", command_id="manual"))
        manual.start()
        deadline = time.monotonic() + 1
        while not any(item["stop_reason"] == "user_stop" for item in process._pending_stop_requests):
            assert time.monotonic() < deadline
            time.sleep(.005)
    expiry.join(1)
    manual.join(1)
    assert process.stop_intent["command_id"] == "manual"


def test_out_of_order_sink_ack_does_not_reset_start(process):
    first = bounds()
    process.first_data_received(first["first_sample_at"])
    process.recording_acknowledged(first)
    anchor = process.timing_evidence["clock_anchor"]
    process.recording_acknowledged(bounds(age=30, sink="other"))
    assert process.timing_evidence["started_at"] == first["first_sample_at"]
    assert process.timing_evidence["clock_anchor"] == anchor


def test_forced_failure_is_cached_without_claiming_integrity(process):
    process.driver.shutdown_result = {"ok": False, "forced_termination": True,
        "worker_inventory_complete": True, "resources_teardown_confirmed": True,
        "stream_results": [{"ok": False, "forced_termination": True,
                            "worker_exitcode": -9, "teardown_confirmed": True}]}
    process.request_stop("user_stop", command_id="manual")
    result = process.shutdown()
    assert process.shutdown() is result
    assert process.driver.stop_calls == 1
    assert result["teardown_confirmed"]
    assert not result["output_integrity_confirmed"]
    events = read_lifecycle_reports(process.outbox.path)
    assert [e.envelope.event_type for e in events] == ["runtime.stop_requested", "runtime.stop_finished"]
    assert events[-1].envelope.payload["shutdown_result"]["forced_termination"]


def test_outbox_failure_does_not_prevent_cancellation(process, monkeypatch):
    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(process.outbox, "enqueue", fail)
    process.request_stop("user_stop")
    assert process.driver.cancel.is_set()
    assert process.shutdown()["errors"]


def test_same_boot_restoration_uses_saved_elapsed_deadline(process, monkeypatch):
    from app.watchdog_process import process as module
    monkeypatch.setattr(module, "elapsed_clock", lambda: ("test", "boot", 100))
    state = {"started_at": datetime(2090, 1, 1, tzinfo=UTC).isoformat(),
             "clock_anchor": {"kind": "test", "boot_id": "boot", "deadline_elapsed": 99}}
    assert remaining_recording_seconds(state, 60) == -1
    process.restore_timing(state)
    assert process.stop_intent["stop_reason"] == "duration_ended"


def test_missing_clock_evidence_fails_closed(process):
    with pytest.raises((KeyError, ValueError)):
        process.restore_timing({"started_at": datetime.now(UTC).isoformat(), "clock_anchor": {}})
    assert process.timing_evidence == {}


def test_reboot_rebase_is_durable_before_same_boot_replacement_after_clock_rollback(process, monkeypatch, tmp_path):
    from app.watchdog_process import process as module

    start = datetime(2030, 1, 1, tzinfo=UTC)
    wall_time = [start + timedelta(seconds=10)]
    elapsed = [20.0]

    class WallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall_time[0]

    monkeypatch.setattr(module, "datetime", WallClock)
    monkeypatch.setattr(module, "elapsed_clock", lambda: ("test", "boot-B", elapsed[0]))
    process.manifest.duration_seconds = 60
    prior = {"started_at": start.isoformat(), "clock_anchor": {
        "kind": "test", "boot_id": "boot-A", "deadline_elapsed": 900.0}}

    process.restore_timing(prior)
    events = read_lifecycle_reports(process.outbox.path)
    assert len(events) == 1, "reboot mapping must be durable before acquisition resumes"
    assert events[0].envelope.event_type == "runtime.acquisition_started"
    rebased = dict(events[0].envelope.payload)
    assert rebased["started_at"] == prior["started_at"]
    assert rebased["clock_anchor"] == {
        "kind": "test", "boot_id": "boot-B", "deadline_elapsed": 70.0}
    assert prior["clock_anchor"]["boot_id"] == "boot-A"

    # Ten real elapsed seconds pass; a one-hour calendar rollback cannot grant
    # extra time to another producer in boot B.
    elapsed[0] = 30.0
    wall_time[0] = start - timedelta(hours=1)
    with WatchdogOutbox(tmp_path / "replacement.sqlite3") as outbox:
        replacement = WatchdogProcess(
            manifest=process.manifest, identity=WatchdogIdentity("host", "replacement"),
            outbox=outbox, telemetry_client=process._client, build_driver=Driver)
        try:
            replacement.restore_timing(rebased)
            assert replacement._deadline_elapsed == 70.0
            assert remaining_recording_seconds(replacement.timing_evidence, 60) == 40.0
        finally:
            replacement.shutdown()


def test_failed_reboot_anchor_persistence_cancels_before_acquisition(process, monkeypatch):
    from app.watchdog_process import process as module

    monkeypatch.setattr(module, "elapsed_clock", lambda: ("test", "boot-B", 20.0))
    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(process.outbox, "enqueue", fail)
    process.restore_timing({"started_at": datetime.now(UTC).isoformat(), "clock_anchor": {
        "kind": "test", "boot_id": "boot-A", "deadline_elapsed": 900.0}})
    assert process.stopping
    assert process.driver.cancel.is_set()
    assert process.stop_intent["stop_reason"] == "runtime_failure"
