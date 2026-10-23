"""Check diagnostic failure capture and bounded storage without acquisition hardware."""

import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "diagnose_resources", Path(__file__).with_name("diagnose_resources.py")
)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def snapshot(**changes):
    row = {
        "schema_version": 1,
        "observed_at": time.time(),
        "sample_rate": 2000,
        "session_id": 13,
        "output_id": "segment-1",
        "device_id": "pod:test",
        "producer_pid": os.getpid(),
        "producer_create_time": 1000.0,
        "writer_pid": 99999,
        "writer_create_time": 2000.0,
        "accepted_frames": 4000,
        "consumed_frames_reported": 2000,
        "confirmed_frames": 2000,
        "pending_confirmation_frames": 2000,
        "closed": False,
        "terminal_error": None,
    }
    row.update(changes)
    return row


def test_reused_pid_is_not_attributed_to_original_device(tmp_path):
    (tmp_path / "pvfs-test.json").write_text(json.dumps(snapshot()), encoding="utf-8")
    processes = [{"pid": os.getpid(), "create_time": 1000.0}, {"pid": 99999, "create_time": 3000.0}]
    rows, errors = probe.recording_samples(tmp_path, processes, 13, time.time(), 5)
    assert not errors
    assert rows[0]["producer_state"] == "alive"
    assert rows[0]["writer_state"] == "pid_reused"


@pytest.mark.parametrize(
    "change",
    [
        {"output_id": []},
        {"confirmed_frames": -1},
        {"sample_rate": float("nan")},
        {"pending_confirmation_frames": "huge"},
        {"closed": "false"},
        {"consumed_frames_reported": 8000},
        {"producer_create_time": float("inf")},
    ],
)
def test_invalid_snapshot_is_visible_and_does_not_stop_collection(tmp_path, change):
    (tmp_path / "pvfs-bad.json").write_text(json.dumps(snapshot(**change)), encoding="utf-8")
    rows, errors = probe.recording_samples(tmp_path, [], 13, time.time(), 5)
    assert rows == []
    assert any("pvfs-bad.json: ValueError" in error for error in errors)


def test_rotation_is_bounded_and_first_failure_history_is_preserved(tmp_path):
    output = probe.EvidenceLog(tmp_path, max_bytes=400, backups=2, history_seconds=600)
    try:
        for index in range(20):
            reasons = ["failure"] if index == 5 else []
            output.append({"sequence": index, "triggers": reasons, "padding": "x" * 25}, reasons)
        incident = (tmp_path / "incident.jsonl").read_bytes()
        output.append({"sequence": 20, "triggers": ["second_failure"]}, ["second_failure"])
        assert (tmp_path / "incident.jsonl").read_bytes() == incident
    finally:
        output.close()
    assert len(list(tmp_path.glob("samples*.jsonl"))) == 3
    assert all(path.stat().st_size <= 400 for path in tmp_path.glob("*.jsonl"))
    rows = [json.loads(line) for line in incident.splitlines()]
    assert rows[-1]["sequence"] == 5
    assert len(rows) > 1


def test_log_trigger_handles_partial_lines_and_truncation(tmp_path):
    path = tmp_path / "watchdog.log"
    path.write_bytes(b"old WinError 1450\n")
    tail = probe.LogTail([path])
    assert tail.sample() == ([], [])
    with path.open("ab") as stream:
        stream.write(b"OSError: [WinError 14")
    assert tail.sample() == ([], [])
    with path.open("ab") as stream:
        stream.write(b"50] Insufficient system resources\n")
    matches, errors = tail.sample()
    assert len(matches) == 1 and "1450" in matches[0]["match"] and not errors
    path.write_bytes(b"heartbeat_stale\n")
    assert len(tail.sample()[0]) == 1


def test_healthy_session_13_float_does_not_consume_first_incident(tmp_path):
    path = tmp_path / "watchdog.jsonl"
    path.write_bytes(b"")
    tail = probe.LogTail([path])
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "stream_status": "healthy",
                    "heartbeat_status": "fresh",
                    "heartbeat_age_seconds": 0.12740373611450195,
                }
            )
            + "\n"
        )
    assert tail.sample() == ([], [])


def test_closed_snapshots_do_not_report_dead_workers_as_new_failure():
    row = snapshot(closed=True)
    row.update(stale=True, writer_state="missing", producer_state="missing")
    record = {"system": {}, "log_matches": [], "recordings": [row]}
    assert probe.triggers(record, {}, 10) == []
    row["terminal_error"] = "writer failure"
    assert probe.triggers(record, {}, 10) == ["recording_failed:segment-1"]


def test_disabled_reporter_creates_no_thread_or_file(monkeypatch, tmp_path):
    from app.output.resource_diagnostics import RecordingDiagnostics

    monkeypatch.delenv("MORELIA_DIAGNOSTICS_DIR", raising=False)
    assert RecordingDiagnostics.start(object()) is None
    monkeypatch.setenv("MORELIA_DIAGNOSTICS_DIR", "relative-directory")
    assert RecordingDiagnostics.start(object()) is None
    assert not list(tmp_path.iterdir())


def test_progress_is_reported_as_confirmation_not_queue_depth():
    row = snapshot()
    history = probe.recording_progress([row], {}, 10)
    assert row["pending_sample_seconds"] == 1
    assert row["confirmation_unchanged_seconds"] == 0
    next_row = snapshot(accepted_frames=6000, pending_confirmation_frames=4000)
    probe.recording_progress([next_row], history, 12)
    assert next_row["accepted_frames_per_second"] == 1000
    assert next_row["confirmed_frames_per_second"] == 0
    assert next_row["confirmation_unchanged_seconds"] == 2
