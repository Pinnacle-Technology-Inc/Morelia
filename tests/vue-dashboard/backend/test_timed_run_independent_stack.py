"""Acceptance oracle: user-approved first HealthSink arrival starts the run timer.

Only physical serial transport/enumeration are emulated. Tests launch the real API,
database, host, watchdog, workers, managed CSV, shutdown and event reconciliation.
"""
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import hashlib
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[3]
HARNESS = Path(__file__).parent / "timed_serial_harness"

def request(base, path, body=None, *, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=100) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw_error_body": body}

def wait_for(fn, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(.2)
    raise AssertionError(f"Timed out: {last!r}")

@pytest.fixture
def stack(tmp_path):
    provenance = {}
    for source_root in (ROOT / "vue-dashboard/backend/app", ROOT / "src/Morelia"):
        for source in source_root.rglob("*.py"):
            provenance[str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path / "candidate-source-sha256.json").write_text(json.dumps(provenance, sort_keys=True, indent=2))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update({
        "TIMED_SERIAL_HARNESS": str(tmp_path), "TIMED_API_PORT": str(port),
        # Queue-manager endpoints are keyed by serial-port identity. Distinct
        # fictional ports isolate concurrent full stacks at that real boundary.
        "TIMED_SERIAL_PORT_BASE": str(10000 + 2 * port),
        "TIMED_SERIAL_START_DELAY": "2",
        "PYTHONPATH": os.pathsep.join([str(HARNESS), str(ROOT / "vue-dashboard/backend"), str(ROOT / "src")]),
        "MORELIA_SRC": str(ROOT / "src"), "FLASK_CONFIG": "development",
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "stack.sqlite3"),
        "PINNACLE_DAEMON_URL": f"http://127.0.0.1:{port}",
        "INGEST_BASE_URL": f"http://127.0.0.1:{port}", "INGEST_TOKEN": "independent-fixture-token",
        "DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates"),
        "SESSION_TEMPLATE_DIR": str(tmp_path / "session-templates"),
        "OUTPUT_DIR": str(tmp_path / "output"), "DIAGNOSTIC_LOG_DIR": str(tmp_path / "diagnostics"),
        "WATCHDOG_OUTBOX_DIR": str(tmp_path / "outboxes"),
        "WATCHDOG_HARDWARE_LOCK_DIR": str(tmp_path / "locks"),
        "SINK_DELIVERY_OUTBOX_DIR": str(tmp_path / "sink-outboxes"),
        "SESSION_SCHEDULER_ENABLED": "1", "STARTUP_RECONCILIATION_ENABLED": "0",
        "WATCHDOG_FIRST_PACKET_TIMEOUT_SECONDS": "20",
        "WATCHDOG_REPORT_INTERVAL_SECONDS": "0.2",
        "WATCHDOG_PROCESS_LOOP_INTERVAL_SECONDS": "0.1",
        "RUNTIME_HOST_MAIN_LOOP_INTERVAL_SECONDS": "0.1",
        "CONTROL_PLANE_POLL_INTERVAL_SECONDS": "0.2",
        "LOG_LEVEL": "INFO",
    })
    log = (tmp_path / "daemon.log").open("w")
    process = subprocess.Popen([sys.executable, str(HARNESS / "daemon.py")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    process._harness_env = env
    base = f"http://127.0.0.1:{port}"
    try:
        wait_for(lambda: (tmp_path / "fixture.json").exists() and request(base, "/health")[0] == 200, 25)
        yield base, tmp_path, json.loads((tmp_path / "fixture.json").read_text()), process
    finally:
        children = (psutil.Process(process.pid).children(recursive=True) if process.poll() is None else []) + getattr(process, "_harness_orphans", [])
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        log.close()

def test_real_process_duration_and_sample_bounds(stack):
    base, directory, payload, process = stack
    duration = int(os.environ.get("TIMED_ACCEPTANCE_SECONDS", "6"))
    payload.update(idempotency_key="independent-normal", execution={"mode": "immediate", "duration_seconds": duration})
    status, session = request(base, "/api/v1/session-runs", payload)
    (directory / "create-response.json").write_text(json.dumps({"status": status, "body": session}, indent=2))
    assert status == 202, session
    session_id = session["id"]
    def terminal():
        code, body = request(base, f"/api/v1/sessions/{session_id}")
        (directory / "latest-session.json").write_text(json.dumps(body, indent=2))
        return body if body.get("status") == "completed" else None
    final = wait_for(terminal, duration + 20)
    assert final["started_at"] and final["ended_at"], final
    status, detail = request(base, f"/api/v1/sessions/{session_id}/status")
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    files = list(directory.rglob("*.csv"))
    assert files, "Real managed CSV must be readable"
    assert any(path.stat().st_size > 100 for path in files)
    events = [json.loads(line) for path in directory.glob("serial-*.jsonl") for line in path.read_text().splitlines()]
    assert len({event["pid"] for event in events}) >= 2, events
    assert any(event["event"] == "first_sample" for event in events)
    assert any(event["event"] == "command" and event["command"] == 6 and event["payload"] == "00" for event in events)
    first_transport_sample = min(event["utc"] for event in events if event["event"] == "first_sample")
    assert first_transport_sample - .25 <= utc(final["started_at"]) <= first_transport_sample + .25, (
        "First arrival UTC must describe receipt after physical transport produces data",
        first_transport_sample, final["started_at"],
    )
    verify_recording(directory, final, detail, duration)

def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()

def lifecycle(directory):
    events = []
    for path in (directory / "outboxes").glob("*.sqlite3"):
        with sqlite3.connect(path) as connection:
            events.extend((kind, json.loads(payload)) for kind, payload in connection.execute("SELECT event_type, payload FROM outbox_reports WHERE event_type != 'runtime.report'"))
    return events

def verify_recording(directory, final, detail, duration, *, reason="duration_ended"):
    def finalized_rows():
        with (directory / "recorded.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        return rows if rows and abs(int(rows[-1]["time"]) / 1e9 - utc(final["ended_at"])) < .000002 else None
    rows = wait_for(finalized_rows, 25)
    timestamps = [int(row["time"]) / 1e9 for row in rows]
    bounds = final["recording_bounds"]
    assert len(bounds) == 1, bounds
    assert abs(min(timestamps) - utc(bounds[0]["first_sample_at"])) < .000002
    assert abs(max(timestamps) - utc(bounds[0]["last_sample_at"])) < .000002
    assert abs(max(timestamps) - utc(final["ended_at"])) < .000002
    # The legacy source timestamps predate arrival in this delayed transport.
    # Keep an independent distinction so repurposing started_at cannot silently
    # turn receipt-to-last-sample into the recorded sample span.
    assert utc(final["started_at"]) - min(timestamps) > 1, (final, timestamps[:1])
    stops = [op for op in detail["operations"] if (op.get("details") or {}).get("stop_reason")]
    assert len(stops) == 1, stops
    stop = stops[0]
    assert stop["state"] == "succeeded", stop
    proof = stop["details"]
    assert proof["stop_reason"] == reason
    assert proof["teardown_confirmed"] is True
    assert proof["output_integrity_confirmed"] is True
    assert proof["shutdown_result"]["ok"] is True
    streams = proof["shutdown_result"]["stream_results"]
    assert streams and all(row["ok"] and not row["forced_termination"] for row in streams)
    if reason == "duration_ended":
        elapsed = utc(proof["requested_at"]) - utc(final["started_at"])
        assert duration - .1 <= elapsed <= duration + 1, (elapsed, proof)
    starts = [payload for kind, payload in lifecycle(directory) if kind == "runtime.acquisition_started"]
    assert len(starts) == 1
    assert utc(starts[0]["started_at"]) == utc(final["started_at"])
    (directory / "independent-evidence.json").write_text(json.dumps({"sample_count": len(rows), "arrival_utc": utc(final["started_at"]), "first_sample_utc": min(timestamps), "last_sample_utc": max(timestamps), "stop_reason": reason, "stop_requested_utc": utc(proof["requested_at"]), "duration_seconds": duration, "negative_control": os.environ.get("TIMED_NEGATIVE_CONTROL")}, indent=2))

@pytest.mark.parametrize("scenario", ["outage_through_expiry", "early_manual_stop"])
def test_real_process_outage_and_manual_stop(stack, scenario):
    base, directory, payload, process = stack
    duration = 60 if os.environ.get("TIMED_ACCEPTANCE_FULL_MINUTE") else 12
    payload.update(idempotency_key="independent-" + scenario, execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    if scenario == "outage_through_expiry":
        if duration == 60:
            started = request(base, path)[1]["started_at"]
            wait_for(lambda: time.time() >= utc(started) + 45, 50)
        (directory / "disconnect").write_text("Physical transport produces no more packets")
    else:
        code, stopped = request(base, path + "/commands/stop", {})
        assert code == 202, stopped
    final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), duration + 20)
    detail = request(base, path + "/status")[1]
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    verify_recording(directory, final, detail, duration, reason="user_stop" if scenario == "early_manual_stop" else "duration_ended")
    code, repeated = request(base, path + "/commands/stop", {})
    assert code == 202 and repeated["status"] == "completed"

def test_real_process_manual_stop_before_first_recording(stack):
    base, directory, payload, process = stack
    (directory / "disconnect").write_text("No source packets before manual stop")
    payload.update(idempotency_key="independent-before-data", execution={"mode": "immediate", "duration_seconds": 6})
    with ThreadPoolExecutor() as pool:
        creating = pool.submit(request, base, "/api/v1/session-runs", payload)
        sessions = wait_for(lambda: request(base, "/api/v1/sessions/")[1], 10)
        path = f'/api/v1/sessions/{sessions[0]["id"]}'
        # Wait until a real watchdog exists, but duration remains unarmed.
        wait_for(lambda: list((directory / "outboxes").glob("*.sqlite3")), 15)
        before = request(base, path)[1]
        assert before["started_at"] is None and before["recording_bounds"] == [] and before["ended_at"] is None
        began = time.monotonic()
        code, stop = request(base, path + "/commands/stop", {})
        (directory / "stop-response.json").write_text(json.dumps({"status": code, "body": stop, "elapsed": time.monotonic() - began}, indent=2))
        assert code == 202, stop
        assert time.monotonic() - began < 10, "Manual cancellation must interrupt first-arrival wait"
        creating.result(timeout=25)
    final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), 20)
    assert final["started_at"] is None and final["recording_bounds"] == [] and final["ended_at"] is None
    assert not any(kind in {"runtime.acquisition_started", "runtime.recording_started"} for kind, payload in lifecycle(directory))
    stops = [payload for kind, payload in lifecycle(directory) if kind == "runtime.stop_requested"]
    assert len(stops) == 1 and stops[0]["stop_reason"] == "user_stop", stops

def test_real_watchdog_replacement_preserves_deadline_and_reaps_old_workers(stack):
    base, directory, payload, process = stack
    duration = 24
    payload.update(idempotency_key="independent-replacement", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    started = wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    wait_for(lambda: time.time() >= utc(started) + 8, 15)
    watchdogs = [child for child in psutil.Process(process.pid).children(recursive=True) if "app.watchdog_process" in child.cmdline()]
    watchdogs = [child for child in watchdogs if not any(other.ppid() == child.pid for other in watchdogs)]
    assert len(watchdogs) == 1
    original = watchdogs[0]
    descendants = original.children(recursive=True)
    process._harness_orphans = descendants
    (directory / "killed-watchdog.json").write_text(json.dumps({"pid": original.pid, "children": [child.pid for child in descendants], "started_at": started, "killed_utc": time.time()}))
    original.kill()
    wait_for(lambda: len(list((directory / "outboxes").glob("*.sqlite3"))) >= 2, 18)
    deadline = utc(started) + duration
    wait_for(lambda: time.time() >= deadline + 1.5, duration)
    stop_requests = [payload for kind, payload in lifecycle(directory) if kind == "runtime.stop_requested"]
    (directory / "replacement-stops.json").write_text(json.dumps(stop_requests, indent=2))
    assert any(row["stop_reason"] == "duration_ended" and abs(utc(row["requested_at"]) - deadline) <= 1 for row in stop_requests), stop_requests
    assert request(base, path)[1]["started_at"] == started
    survivors = [child.pid for child in descendants if child.is_running()]
    (directory / "surviving-predecessor-children.json").write_text(json.dumps(survivors))
    assert not survivors, f"Old worker/queue processes outlived watchdog replacement and deadline: {survivors}"

@pytest.mark.parametrize("drop_host", [False, True])
def test_real_watchdog_expires_without_control_plane_and_reconciles(stack, drop_host):
    base, directory, payload, process = stack
    duration = 12
    payload.update(idempotency_key="independent-offline", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    started = wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    children = psutil.Process(process.pid).children(recursive=True)
    process._harness_orphans = children
    if drop_host:
        hosts = [child for child in children if "app.runtime_host" in child.cmdline()]
        hosts = [child for child in hosts if not any(other.ppid() == child.pid for other in hosts)]
        assert len(hosts) == 1
        hosts[0].kill()
    daemons = [child for child in children if str(HARNESS / "daemon.py") in child.cmdline()]
    for daemon in daemons:
        daemon.kill()
    process.wait(timeout=10)
    wait_for(lambda: any(kind == "runtime.stop_finished" for kind, payload in lifecycle(directory)), duration + 20)
    local_stops = [payload for kind, payload in lifecycle(directory) if kind == "runtime.stop_requested"]
    assert len(local_stops) == 1 and local_stops[0]["stop_reason"] == "duration_ended"
    assert abs(utc(local_stops[0]["requested_at"]) - utc(started) - duration) <= 1
    env = {**process._harness_env, "STARTUP_RECONCILIATION_ENABLED": "1"}
    with (directory / "restarted-daemon.log").open("w") as log:
        restored = subprocess.Popen([sys.executable, str(HARNESS / "daemon.py")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_for(lambda: request(base, "/health")[0] == 200, 25)
            final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), 25)
            detail = request(base, path + "/status")[1]
            (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
            verify_recording(directory, final, detail, duration)
        finally:
            for child in psutil.Process(restored.pid).children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            restored.kill()
            restored.wait(timeout=10)

def test_real_host_never_respawns_after_established_deadline(stack):
    base, directory, payload, process = stack
    duration = 10
    payload.update(idempotency_key="independent-expired-crash", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    started = wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    watchdogs = [child for child in psutil.Process(process.pid).children(recursive=True) if "app.watchdog_process" in child.cmdline()]
    watchdogs = [child for child in watchdogs if not any(other.ppid() == child.pid for other in watchdogs)]
    assert len(watchdogs) == 1
    original = watchdogs[0]
    process._harness_orphans = original.children(recursive=True)
    original.suspend()
    wait_for(lambda: time.time() > utc(started) + duration + .5, duration + 2)
    original.kill()
    # Real host supervisor must observe expired durable evidence before spawning.
    until = time.monotonic() + 10
    while time.monotonic() < until:
        outboxes = list((directory / "outboxes").glob("*.sqlite3"))
        assert len(outboxes) == 1, f"Post-deadline watchdog spawn created {outboxes}"
        time.sleep(.2)
    detail = request(base, path + "/status")[1]
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    assert detail["session"]["started_at"] == started

@pytest.mark.parametrize("offset", [-.2, .5])
def test_manual_expiry_race_and_repeated_terminal_replay(stack, offset):
    base, directory, payload, process = stack
    duration = 8
    payload.update(idempotency_key="independent-expiry-race", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    started = wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    wait_for(lambda: time.time() >= utc(started) + duration + offset, duration + 3)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(request, base, path + "/commands/stop", {}) for _ in range(4)]
        responses = [future.result(timeout=30) for future in futures]
    (directory / "concurrent-stop-responses.json").write_text(json.dumps(responses, indent=2))
    assert all(code == 202 for code, body in responses), responses
    final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), 25)
    before = request(base, path + "/status")[1]
    stop_ops = [op for op in before["operations"] if (op.get("details") or {}).get("stop_reason")]
    assert len(stop_ops) == 1, stop_ops
    reason = stop_ops[0]["details"]["stop_reason"]
    assert reason in {"user_stop", "duration_ended"}
    if offset > 0:
        assert reason == "duration_ended"
    verify_recording(directory, final, before, duration, reason=reason)
    envelopes = []
    for outbox in (directory / "outboxes").glob("*.sqlite3"):
        with sqlite3.connect(outbox) as connection:
            connection.row_factory = sqlite3.Row
            for row in connection.execute("SELECT report_id,dataflow_id,runtime_id,watchdog_id,manifest_hash,event_type,payload FROM outbox_reports WHERE event_type LIKE 'runtime.stop_%'"):
                envelope = dict(row)
                envelope["payload"] = json.loads(envelope["payload"])
                envelopes.append(envelope)
    for _ in range(2):
        for envelope in reversed(envelopes):
            code, result = request(base, "/api/v1/internal/events", envelope, headers={"X-Agent-Token": "independent-fixture-token"})
            assert code == 202, result
    after = request(base, path + "/status")[1]
    assert after["session"] == before["session"]
    assert len(after["operations"]) == len(before["operations"])
    after_stops = [op for op in after["operations"] if (op.get("details") or {}).get("stop_reason")]
    assert after_stops[0]["details"]["stop_reason"] == reason
    original_terminal = next(envelope for envelope in envelopes if envelope["event_type"] == "runtime.stop_finished")
    corrupted = json.loads(json.dumps(original_terminal))
    false_end = (datetime.fromisoformat(corrupted["payload"]["ended_at"]) + timedelta(minutes=10)).isoformat()
    corrupted["payload"]["ended_at"] = false_end
    corrupted["payload"]["recording_bounds"][0]["last_sample_at"] = false_end
    code, response = request(base, "/api/v1/internal/events", corrupted, headers={"X-Agent-Token": "independent-fixture-token"})
    assert code in {400, 409}, (code, response)
    assert request(base, path)[1] == final, "Conflicting duplicate event mutated accepted sample evidence"
    (directory / "final-status.json").write_text(json.dumps(after, indent=2))

@pytest.mark.parametrize("cancel_offset", [None, -.1, .1])
def test_scheduled_manual_stop_prevents_real_dispatch(stack, cancel_offset):
    base, directory, payload, process = stack
    start_at = datetime.now(timezone.utc) + timedelta(seconds=6)
    payload.update(idempotency_key="independent-scheduled-stop", execution={"mode": "scheduled", "start_at": start_at.isoformat()})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202 and session["status"] == "scheduled", session
    path = f'/api/v1/sessions/{session["id"]}'
    if cancel_offset is not None:
        wait_for(lambda: datetime.now(timezone.utc) >= start_at + timedelta(seconds=cancel_offset), 10)
    code, stopped = request(base, path + "/commands/stop", {})
    assert code == 202, stopped
    stopped = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), 20)
    assert stopped["started_at"] is None and stopped["ended_at"] is None
    wait_for(lambda: datetime.now(timezone.utc) > start_at + timedelta(seconds=2), 10)
    detail = request(base, path + "/status")[1]
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    assert detail["session"]["status"] == "completed"
    stops = [op for op in detail["operations"] if (op.get("details") or {}).get("stop_reason")]
    assert len(stops) == 1 and stops[0]["details"]["stop_reason"] == "user_stop"
    if cancel_offset is None:
        assert not list((directory / "outboxes").glob("*.sqlite3")), "Cancelled schedule launched hardware"

def test_first_recording_timeout_never_becomes_duration_success(stack):
    base, directory, payload, process = stack
    (directory / "disconnect").write_text("No samples available")
    payload.update(idempotency_key="independent-no-data", execution={"mode": "immediate", "duration_seconds": 2})
    began = time.monotonic()
    code, response = request(base, "/api/v1/session-runs", payload)
    assert time.monotonic() - began < 45, response
    sessions = request(base, "/api/v1/sessions/")[1]
    assert all(session["started_at"] is None and session["recording_bounds"] == [] and session["ended_at"] is None for session in sessions)
    requests = [payload for kind, payload in lifecycle(directory) if kind == "runtime.stop_requested"]
    assert requests and all(item["stop_reason"] != "duration_ended" for item in requests)
    (directory / "failure-evidence.json").write_text(json.dumps({"status": code, "body": response, "sessions": sessions, "stop_requests": requests}, indent=2))

def test_multiple_devices_and_sinks_share_one_recorded_window(stack):
    if os.environ.get("TIMED_FIXTURE_DEVICES") != "2" or os.environ.get("TIMED_FIXTURE_SINKS") != "2":
        pytest.skip("Invoke with TIMED_FIXTURE_DEVICES=2 TIMED_FIXTURE_SINKS=2")
    base, directory, payload, process = stack
    duration = 16
    payload.update(idempotency_key="independent-multiple", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), duration + 25)
    detail = request(base, path + "/status")[1]
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    evidence = lifecycle(directory)
    starts = [payload for kind, payload in evidence if kind == "runtime.acquisition_started"]
    assert len(starts) == 1 and utc(final["started_at"]) == utc(starts[0]["started_at"])
    stops = [payload for kind, payload in evidence if kind == "runtime.stop_finished"]
    assert len(stops) == 1 and stops[0]["output_integrity_confirmed"]
    bounds = final["recording_bounds"]
    assert bounds == stops[0]["recording_bounds"]
    assert len(bounds) == 4, bounds
    timestamps = []
    files = list(directory.glob("recorded*.csv"))
    assert len(files) == 4
    for path in files:
        rows = list(csv.DictReader(path.open(newline="")))
        assert len(rows) > 1
        first, last = int(rows[0]["time"]) / 1e9, int(rows[-1]["time"]) / 1e9
        assert any(abs(utc(bound["first_sample_at"]) - first) < .000002 and abs(utc(bound["last_sample_at"]) - last) < .000002 for bound in bounds), (path, bounds)
        timestamps.append(last)
    assert abs(utc(final["ended_at"]) - max(timestamps)) < .000002
    assert abs(utc(stops[0]["requested_at"]) - utc(final["started_at"]) - duration) < 1

def test_real_host_crash_adopts_surviving_watchdog_without_timer_reset(stack):
    base, directory, payload, process = stack
    duration = 35
    payload.update(idempotency_key="independent-host-adoption", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    started = wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    before = request(base, path + "/status")[1]
    children = psutil.Process(process.pid).children(recursive=True)
    process._harness_orphans = children
    hosts = [child for child in children if "app.runtime_host" in child.cmdline()]
    hosts = [child for child in hosts if not any(other.ppid() == child.pid for other in hosts)]
    assert len(hosts) == 1
    hosts[0].kill()
    # Existing recovery is startup reconciliation: restart the daemon while the
    # original watchdog is alive, exercising native authenticated adoption.
    daemons = [child for child in children if str(HARNESS / "daemon.py") in child.cmdline()]
    for daemon in daemons:
        daemon.kill()
    process.wait(timeout=10)
    env = {**process._harness_env, "STARTUP_RECONCILIATION_ENABLED": "1"}
    log = (directory / "restarted-daemon.log").open("w")
    restored = subprocess.Popen([sys.executable, str(HARNESS / "daemon.py")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    # The original fixture tracks exact new process identities for its cleanup.
    process._harness_orphans.append(psutil.Process(restored.pid))
    wait_for(lambda: request(base, "/health")[0] == 200, 25)
    process._harness_orphans.extend(psutil.Process(restored.pid).children(recursive=True))
    # Runtime ownership is public in status; independent of candidate internals.
    def adopted():
        detail = request(base, path + "/status")[1]
        return detail if len(detail.get("runtimes", [])) > len(before.get("runtimes", [])) else None
    after = wait_for(adopted, 20)
    assert after["watchdog_id"] == before["watchdog_id"], "Recovery replaced rather than adopted the live watchdog"
    final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), duration + 20)
    detail = request(base, path + "/status")[1]
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    assert final["started_at"] == started
    assert len(list((directory / "outboxes").glob("*.sqlite3"))) == 1
    verify_recording(directory, final, detail, duration)
    process._harness_orphans.extend(psutil.Process(restored.pid).children(recursive=True))
    log.close()

def test_real_source_outage_recovers_without_pausing_duration(stack):
    base, directory, payload, process = stack
    duration = 60 if os.environ.get("TIMED_ACCEPTANCE_FULL_MINUTE") else 20
    payload.update(idempotency_key="independent-transient-outage", execution={"mode": "immediate", "duration_seconds": duration})
    code, session = request(base, "/api/v1/session-runs", payload)
    assert code == 202, session
    path = f'/api/v1/sessions/{session["id"]}'
    started = wait_for(lambda: request(base, path)[1].get("started_at"), 20)
    if duration == 60:
        wait_for(lambda: time.time() >= utc(started) + 15, 20)
    (directory / "disconnect").write_text("Temporary transport outage")
    resumed_at = 40 if duration == 60 else 8
    wait_for(lambda: time.time() >= utc(started) + resumed_at, 35)
    (directory / "disconnect").unlink()
    final = wait_for(lambda: (body if (body := request(base, path)[1]).get("status") == "completed" else None), duration + 15)
    detail = request(base, path + "/status")[1]
    (directory / "final-status.json").write_text(json.dumps(detail, indent=2))
    verify_recording(directory, final, detail, duration)
    rows = list(csv.DictReader((directory / "recorded.csv").open(newline="")))
    timestamps = [int(row["time"]) / 1e9 for row in rows]
    transport = [json.loads(line) for path in directory.glob("serial-*.jsonl") for line in path.read_text().splitlines()]
    pauses = [row["utc"] for row in transport if row["event"] == "transport_pause"]
    resumes = [row["utc"] for row in transport if row["event"] in {"transport_resume", "first_sample"} and pauses and row["utc"] > min(pauses) + 1]
    assert pauses and resumes and min(resumes) - min(pauses) >= (20 if duration == 60 else 3), "Transport outage not observed"
    assert max(timestamps) > utc(started) + (40 if duration == 60 else 10), "Source never resumed recording"

def test_duration_wire_validation_is_strict_and_creates_no_runs(stack):
    base, directory, payload, process = stack
    invalid = [None, True, False, "60", 1.5, 0, -1, 10**12]
    evidence = []
    for index, duration in enumerate(invalid):
        body = {**payload, "idempotency_key": f"invalid-duration-{index}", "execution": {"mode": "immediate", "duration_seconds": duration}}
        code, response = request(base, "/api/v1/session-runs", body)
        evidence.append({"input": duration, "status": code, "response": response})
        assert code == 422, evidence[-1]
    body = {**payload, "idempotency_key": "invalid-scheduled-duration", "execution": {"mode": "scheduled", "start_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(), "duration_seconds": 60}}
    assert request(base, "/api/v1/session-runs", body)[0] == 422
    assert request(base, "/api/v1/sessions/")[1] == []
    assert not list((directory / "outboxes").glob("*.sqlite3"))
    (directory / "validation-evidence.json").write_text(json.dumps(evidence, indent=2))
