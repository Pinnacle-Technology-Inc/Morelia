"""Focused host fences with real SQLite evidence; process launch is a negative spy.

These checks are builder SELF_CHECKED, not the transport-only release gate.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import create_app
from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
from app.database import db
from app.control.supervisor import HostSupervisor
from app.domain.enums import RuntimeOwnershipState, WatchdogProcessState
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.watchdog_process_driver import WatchdogProcessDriver
from app.watchdog_process.outbox import WatchdogOutbox
from app.watchdog_process.process import elapsed_clock


def recording_state(remaining):
    kind, boot, elapsed = elapsed_clock()
    return {"started_at": (datetime.now(UTC) - timedelta(seconds=50)).isoformat(),
        "recording_bounds": [], "clock_anchor": {
            "kind": kind, "boot_id": boot, "deadline_elapsed": elapsed + remaining}}


def driver_with_evidence(tmp_path, events, duration=60):
    manifest = SimpleNamespace(dataflow_id="df", hash="hash", duration_seconds=duration)
    calls = []
    driver = WatchdogProcessDriver(manifest=manifest, manifest_path="unused",
        on_report=lambda _: None, runtime_id="rt", ingest_url="http://localhost",
        popen=lambda *a, **kw: calls.append(a))
    driver._phase = RuntimePhase.RUNNING
    driver._watchdog_id = "old"
    driver._watchdog_pid = 123
    driver._watchdog_state = WatchdogProcessState.RUNNING
    path = tmp_path / "old.sqlite3"
    driver._watchdog_outbox_path = str(path)
    with WatchdogOutbox(path) as outbox:
        for index, (event_type, payload) in enumerate(events):
            outbox.enqueue(WatchdogTelemetryEnvelope(report_id=f"old:{index}",
                dataflow_id="df", runtime_id="rt", watchdog_id="old", manifest_hash="hash",
                event_type=event_type, payload=payload))
            # Delivery must not erase local replacement fences.
            outbox.mark_delivered(f"old:{index}")
    return driver, calls


@pytest.mark.parametrize("events", [
    [],
    [("runtime.recording_started", {"started_at": "2026-01-01T00:00:00+00:00"})],
    [("runtime.stop_requested", {"stop_reason": "user_stop", "command_id": "stop"})],
])
def test_ambiguous_or_stopping_timed_producer_never_respawns(tmp_path, events):
    driver, calls = driver_with_evidence(tmp_path, events)
    driver._handle_crash(1)
    assert calls == []
    assert driver.respawn_exhausted
    assert driver.phase == RuntimePhase.STOPPING
    assert driver.status_snapshot()["predecessor_watchdogs"][0]["watchdog_id"] == "old"


def test_elapsed_deadline_blocks_respawn_even_when_utc_start_is_in_future(tmp_path):
    state = recording_state(-1)
    state["started_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    driver, calls = driver_with_evidence(tmp_path, [("runtime.recording_started", state)])
    driver._handle_crash(1)
    assert calls == []
    assert driver.respawn_exhausted


@pytest.mark.parametrize("event_type", ["runtime.recording_started", "runtime.acquisition_started"])
def test_unexpired_recording_restored_from_delivered_outbox(tmp_path, event_type):
    state = recording_state(30)
    driver, _ = driver_with_evidence(tmp_path, [(event_type, state)])
    driver._read_lifecycle_evidence()
    assert driver._recording_state == state
    assert not driver._replacement_blocked()


def test_unlimited_producer_still_honors_durable_stop(tmp_path):
    driver, calls = driver_with_evidence(tmp_path,
        [("runtime.stop_requested", {"stop_reason": "user_stop"})], duration=None)
    driver._handle_crash(0)
    assert calls == []
    assert driver.respawn_exhausted


def test_replacement_retains_predecessor_before_replacing_and_uncertainty(tmp_path):
    app = create_app("testing", {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'db.sqlite3'}"})
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="test", dataflow_id="df"))
        db.session.commit()
        repo = RuntimeOwnershipRepository()
        repo.create_starting(runtime_id="rt", session_id=1, dataflow_id="df", manifest_hash="hash", token="token")
        repo.set_watchdog("rt", watchdog_id="old", pid=1, outbox_path="old.sqlite3")
        repo.set_watchdog("rt", watchdog_id="new", pid=2, outbox_path="new.sqlite3")
        repo.mark_uncertain("rt", details={"reason": "test"})
        db.session.remove()
        row = repo.get("rt")
        assert row.state == RuntimeOwnershipState.UNCERTAIN
        assert row.watchdog_id == "new"
        assert row.details["predecessor_watchdogs"] == [{"watchdog_id": "old",
            "runtime_id": "rt", "dataflow_id": "df", "manifest_hash": "hash",
            "pid": 1, "outbox_path": "old.sqlite3", "exit_details": None}]
        HostSupervisor()._reconcile_watchdog_status({"runtime_id": "rt",
            "watchdog_id": "old", "watchdog_state": "running", "watchdog_pid": 1})
        assert repo.get("rt").watchdog_id == "new"
        repo.mark_stopped("rt")
        HostSupervisor()._reconcile_watchdog_status({"runtime_id": "rt",
            "watchdog_id": "new", "watchdog_state": "running", "watchdog_pid": 2})
        assert repo.get("rt").watchdog_state == WatchdogProcessState.STOPPED


def test_daemon_replays_retired_recording_after_exit_once_without_reclaiming_owner(tmp_path):
    app = create_app("testing", {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'db.sqlite3'}"})
    with app.app_context():
        db.create_all()
        session = Session(id=1, name="replay", dataflow_id="df", duration_seconds=60)
        db.session.add(session)
        db.session.commit()
        repo = RuntimeOwnershipRepository()
        repo.create_starting(runtime_id="rt", session_id=1, dataflow_id="df", manifest_hash="hash", token="token")
        old_path, new_path = tmp_path / "old.sqlite3", tmp_path / "new.sqlite3"
        repo.set_watchdog("rt", watchdog_id="old", outbox_path=str(old_path))
        repo.set_watchdog("rt", watchdog_id="new", outbox_path=str(new_path))
        state = recording_state(30)
        state["recording_bounds"] = [{"source_id": "device", "sink_id": "file",
            "first_sample_at": state["started_at"], "last_sample_at": state["started_at"]}]
        with WatchdogOutbox(new_path):
            pass
        with WatchdogOutbox(old_path) as outbox:
            outbox.enqueue(WatchdogTelemetryEnvelope(report_id="old:recording", dataflow_id="df",
                runtime_id="rt", watchdog_id="old", manifest_hash="hash",
                event_type="runtime.recording_started", payload=state))
        supervisor = HostSupervisor()
        supervisor.replay_watchdog_outboxes()
        supervisor.replay_watchdog_outboxes()
        db.session.refresh(session)
        assert session.started_at is not None
        assert session.ended_at == session.started_at
        assert repo.get("rt").watchdog_id == "new"
        with WatchdogOutbox(old_path) as outbox:
            assert outbox.count_pending() == 0
