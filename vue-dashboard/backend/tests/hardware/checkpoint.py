"""Checkpoint driver — stand up a REAL plane, capture what a REAL watchdog sends.

Run this at a packet checkpoint, with hardware attached, to produce fresh
capture fixtures the replay tests assert against:

    venv\\Scripts\\python.exe -m tests.hardware.checkpoint --session-id 19

What it does, all against reality (no test_client, no fakes):

1. Builds the control-plane app against your REAL database (the development
   profile — the same instance/guarded-experiment.sqlite3 your sessions live
   in) and wraps its WSGI stack in RecordingMiddleware, so every northbound
   POST is teed to a JSONL fixture.
2. Serves that app on a real loopback port with a real threaded WSGI server —
   the child subprocess pushes over real HTTP, which the in-process test_client
   cannot receive.
3. Points ingest at that server, spawns a real runtime host for the session,
   lets it stream, and (optionally, with --faults) walks the fault menu.
4. Writes the capture file under tests/hardware/fixtures/.

Start WITHOUT --faults: get one clean recording of normal traffic first, and
confirm the plumbing works, before injecting failures.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from structlog.contextvars import bind_contextvars
from werkzeug.serving import make_server

from app import create_app
from app.control.supervisor import HostSupervisor
from app.database import db
from app.models.device_config import DeviceConfig
from app.repositories.sessions import SessionRepository
from app.services import sessions as sessions_service
from tests.hardware import fault_menu
from tests.hardware.capture import RecordingMiddleware

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _assert_no_live_daemon() -> None:
    """Abort if a real control-plane daemon is already running.

    The checkpoint IS a control plane. Running it alongside a live
    ``pinnacle start`` daemon collides two ways: they share this database (the
    daemon's reconciliation reaps the checkpoint's in-flight operations,
    especially under ``--debug`` auto-reload), and they fight over the same
    serial ports. Fail loud and early instead of mid-teardown.
    """
    from app.config import get_config

    url = getattr(get_config("development"), "CONTROL_PLANE_BASE_URL", "http://127.0.0.1:5000")
    parsed = urlparse(url)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 5000
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((host, port)) == 0:
            raise SystemExit(
                f"A control-plane daemon appears to be running at {url}.\n"
                "  The checkpoint is its own control plane — you can't run both:\n"
                "  they share this database (its reconciliation will reap the\n"
                "  checkpoint's operations) and the same serial ports.\n"
                "  Stop the daemon (Ctrl+C in the 'pinnacle start' terminal), then re-run."
            )


def _abort_if_orphaned_morelia() -> None:
    """Abort if orphaned Morelia queue_server processes hold the COM ports.

    A previous hard-killed watchdog leaves its per-port ``queue_server.py``
    children alive; the next Morelia then opens the port but streams nothing
    (the recurring 0-reports symptom). PRE-RUN hygiene only — orphans created
    DURING a --kill run are product-domain reality the test must observe.
    """
    if sys.platform != "win32" or os.environ.get("GED_IGNORE_ORPHANS") == "1":
        return
    cmd = [
        "powershell.exe", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*queue_server*' } | "
        "Select-Object -ExpandProperty ProcessId",
    ]
    try:
        pids = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.split()
    except Exception:
        return  # guard is best-effort; never block the run on the probe itself
    if pids:
        raise SystemExit(
            f"Orphaned Morelia queue_server process(es) hold the COM ports: {pids}.\n"
            f"  Kill them first:  powershell \"Stop-Process -Id {','.join(pids)} -Force\"\n"
            "  (or set GED_IGNORE_ORPHANS=1 to run anyway)"
        )


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _hard_kill_pid(pid: int) -> None:
    """Simulate a crash: force-kill ONE process (no /T — children get orphaned,
    exactly like a real crash would leave them)."""
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, text=True)


def _wait_for_new_watchdog(
    supervisor: HostSupervisor, port: int, old_watchdog_id: str, timeout: float = 120.0
) -> dict | None:
    """Poll the host's /status until a NEW live watchdog identity appears.

    Each probe also drives the driver's own ``poll_health()`` (crash detection +
    respawn), so this loop is both the observer and the heartbeat. Returns the
    status dict once ``watchdog_id`` differs from the killed one, or None on
    timeout (respawn failed / budget exhausted — itself a finding).
    """
    deadline = time.monotonic() + timeout
    last_status: dict | None = None
    while time.monotonic() < deadline:
        with suppress(Exception):
            status = supervisor._probe_status(port)  # noqa: SLF001 - harness
            last_status = status
            wid = status.get("watchdog_id")
            if wid and wid != old_watchdog_id and status.get("watchdog_state") in (
                "running", "adopted",
            ):
                return status
        time.sleep(2)
    if last_status is not None:
        print(f"[checkpoint]   last /status before timeout: watchdog_id="
              f"{last_status.get('watchdog_id')!r} state={last_status.get('watchdog_state')!r}")
    return None


def _ownership_snapshot(runtime_id: str | None) -> dict | None:
    """Durable-evidence snapshot of one runtime_ownerships row, JSON-safe.

    The recovery scenarios need the row captured AT ITS MOMENT (e.g. state
    RECOVERING with phase=retry_wait) because the very next reconcile pass
    overwrites it — the judge reads these snapshots from the run metadata.
    """
    if not runtime_id:
        return None
    from app.repositories.runtime_ownership import RuntimeOwnershipRepository

    row = RuntimeOwnershipRepository().get(runtime_id)
    if row is None:
        return None
    return {
        "runtime_id": row.runtime_id,
        "state": getattr(row.state, "value", str(row.state)),
        "watchdog_id": row.watchdog_id,
        "watchdog_pid": row.watchdog_pid,
        "watchdog_state": getattr(row.watchdog_state, "value", None)
        if row.watchdog_state is not None
        else None,
        "details": row.details,
    }


META_FILE = FIXTURES_DIR / "latest_run_meta.json"


def _write_meta(meta: dict) -> None:
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[checkpoint] run metadata -> {META_FILE}")


def _draft_session_from_template(template_path: Path) -> int:
    """Build a fresh DRAFT session from a session-template .toml file.

    Your template lists each device flow by device_template name + sink_type.
    Since the physical devices are already configured (device_configs exist and
    are free), we map each flow to its existing config by device_type — no
    interactive hardware binding needed — and create the session through the
    real ``sessions.create`` path (same validation your CLI uses).
    """
    content = tomllib.loads(template_path.read_text(encoding="utf-8"))
    raw_flows = content.get("device_flows") or []
    if not raw_flows:
        raise SystemExit(f"template {template_path} has no device_flows")

    from app.services import device_templates

    def _resolve_device_type(flow: dict) -> str:
        """Resolve a flow's device template reference to a device type.

        Current format: ``device_template_path`` (a filename under
        instance/device-templates) + ``device_template_content_hash``. The hash
        is the strongest key (survives renames), then the path, then the
        legacy ``device_template`` name, then the old "<type>-..." prefix.
        """
        content_hash = flow.get("device_template_content_hash")
        if content_hash:
            tmpl = device_templates.get_by_content_hash(str(content_hash))
            if tmpl is not None:
                return str(getattr(tmpl.type, "value", tmpl.type))
        ref = str(flow.get("device_template_path") or flow.get("device_template") or "")
        if ref:
            tmpl = device_templates.get_by_path(ref) or device_templates.get_by_name(
                ref.removesuffix(".toml")
            )
            if tmpl is not None:
                return str(getattr(tmpl.type, "value", tmpl.type))
        return ref.split("-", 1)[0]

    configs = list(db.session.scalars(db.select(DeviceConfig)).all())
    used: set[int] = set()
    device_flows: list[dict] = []
    for flow in raw_flows:
        device_type = _resolve_device_type(flow)
        match = next(
            (
                c
                for c in configs
                if c.id not in used
                and getattr(c.device_type, "value", c.device_type) == device_type
                and getattr(c.claim_state, "value", c.claim_state) == "free"
            ),
            None,
        )
        if match is None:
            raise SystemExit(
                f"no free device config of type {device_type!r} for flow "
                f"{flow.get('nickname')!r} — configure or free the device first."
            )
        used.add(match.id)
        entry: dict = {"device_config_id": match.id, "sink_type": flow.get("sink_type", "csv")}
        if flow.get("nickname"):
            entry["nickname"] = flow["nickname"]
        if flow.get("sink_location"):
            entry["sink_location"] = flow["sink_location"]
        device_flows.append(entry)

    data: dict = {"name": content.get("name", template_path.stem), "device_flows": device_flows}
    if content.get("policy") is not None:
        data["policy"] = content["policy"]
    session = sessions_service.create(data)
    print(
        f"[checkpoint] created DRAFT session {session.id} from {template_path.name} "
        f"({len(device_flows)} devices: {[f['device_config_id'] for f in device_flows]})"
    )
    return session.id


def _launch_watchdog(
    *, manifest_path: str, runtime_id: str, watchdog_id: str, session_id: int,
    ingest_base: str, outbox_dir: str, stream_seconds: float, label: str,
) -> None:
    """Run one `python -m app.watchdog_process` for stream_seconds, then stop it."""
    log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="ged-p5-")
    log_handle = os.fdopen(log_fd, "w", encoding="utf-8")
    print(f"[checkpoint] {label}: watchdog_id={watchdog_id[:8]}")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "app.watchdog_process",
            "--manifest", manifest_path,
            "--runtime-id", runtime_id,
            "--watchdog-id", watchdog_id,
            "--session-id", str(session_id),
            "--ingest-url", ingest_base,
            "--outbox-dir", outbox_dir,
            "--driver", "morelia",
        ],
        stdout=subprocess.PIPE,
        stderr=log_handle,  # logs to a file so stdout carries only the READY handshake
        text=True,
    )
    log_handle.close()
    try:
        # Wait for READY (Morelia cold-init ~10s). Only "READY" reaches stdout.
        ready = any(line.strip() == "READY" for line in proc.stdout)  # type: ignore[union-attr]
        if not ready:
            raise SystemExit(f"watchdog process exited before READY (log: {log_path})")
        print(f"[checkpoint] {label} READY; streaming for {stream_seconds:.0f}s...")
        time.sleep(stream_seconds)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def _post_late_report(
    *, ingest_base: str, session_id: int, dataflow_id: str, runtime_id: str,
    stale_watchdog_id: str, manifest_hash: str,
) -> None:
    """Send a report from a now-superseded watchdog — the receiver must fence it (409).

    This is exactly what the fencing defends against: a late/retried report from
    a watchdog that has already been replaced as the active identity. We POST it
    to the real endpoint so the capture records the live 409.
    """
    import urllib.error
    import urllib.request

    envelope = {
        "report_id": f"{stale_watchdog_id}:late",
        "session_id": str(session_id),
        "dataflow_id": dataflow_id,
        "runtime_id": runtime_id,
        "watchdog_id": stale_watchdog_id,
        "manifest_hash": manifest_hash,
        "event_type": "runtime.report",
        "payload": {"devices": []},
    }
    body = json.dumps(envelope).encode("utf-8")
    req = urllib.request.Request(
        ingest_base + "/api/v1/internal/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    print(
        f"[checkpoint]   late report from superseded {stale_watchdog_id[:8]} "
        f"-> HTTP {status} (expect 409 = fenced)"
    )


def _run_watchdog_process(
    *, session_id: int, ingest_base: str, stream_seconds: float, with_faults: bool
) -> None:
    """Launch packet 5's watchdog process directly and let it stream telemetry.

    The DEFAULT checkpoint path goes supervisor -> ``app.runtime_host`` (the OLD
    two-process path, whose envelope has no identity fields). This path instead
    runs ``python -m app.watchdog_process`` — packet 5's real sender — which
    emits the identity-rich ``WatchdogTelemetryEnvelope`` straight to ingest.

    With ``--faults``: after watchdog A streams, register a new watchdog B as the
    active identity (a respawn), send a late report from the now-stale A (the
    receiver fences it, 409), then run B. The capture then holds a real
    stale-vs-active pair for the AC2 fencing assertion.
    """
    from app.repositories.runtime_ownership import RuntimeOwnershipRepository
    from app.services import manifests

    dataflow_id = uuid4().hex
    runtime_id = uuid4().hex
    manifest = manifests.resolve(session_id, dataflow_id=dataflow_id, validate_sink_locations=False)

    fd, manifest_path = tempfile.mkstemp(suffix=".json", prefix="ged-p5-manifest-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(manifest.to_dict(), fh)
    outbox_dir = tempfile.mkdtemp(prefix="ged-p5-outbox-")

    # Register the runtime + its first watchdog as the ACTIVE identity, or the
    # control plane fences every report 409. In the real three-process path this
    # is the runtime_host's job (packet 6); the checkpoint stands in for it.
    ownerships = RuntimeOwnershipRepository()
    ownerships.create_starting(
        runtime_id=runtime_id, session_id=session_id, dataflow_id=dataflow_id,
        manifest_hash=manifest.hash, token=None,
    )
    watchdog_a = uuid4().hex
    ownerships.set_watchdog(runtime_id, watchdog_id=watchdog_a)

    try:
        _launch_watchdog(
            manifest_path=manifest_path, runtime_id=runtime_id, watchdog_id=watchdog_a,
            session_id=session_id, ingest_base=ingest_base, outbox_dir=outbox_dir,
            stream_seconds=stream_seconds, label="watchdog A (active)",
        )
        if with_faults:
            watchdog_b = uuid4().hex
            print("[checkpoint] fault: respawn — watchdog B supersedes A as active")
            ownerships.set_watchdog(runtime_id, watchdog_id=watchdog_b)  # A now stale
            _post_late_report(
                ingest_base=ingest_base, session_id=session_id, dataflow_id=dataflow_id,
                runtime_id=runtime_id, stale_watchdog_id=watchdog_a, manifest_hash=manifest.hash,
            )
            _launch_watchdog(
                manifest_path=manifest_path, runtime_id=runtime_id, watchdog_id=watchdog_b,
                session_id=session_id, ingest_base=ingest_base, outbox_dir=outbox_dir,
                stream_seconds=stream_seconds, label="watchdog B (respawned, active)",
            )
    finally:
        with suppress(OSError):
            os.unlink(manifest_path)
    print("[checkpoint] watchdog process(es) stopped")


def run_checkpoint(
    *,
    session_id: int | None,
    template: Path | None,
    capture_name: str,
    stream_seconds: float,
    with_faults: bool,
    packet5: bool = False,
    kill: str | None = None,
) -> Path:
    # Refuse to run alongside a live daemon — shared DB + shared serial ports.
    _assert_no_live_daemon()
    # Refuse to start with stale Morelia port-owners from a previous kill run.
    _abort_if_orphaned_morelia()

    # Development profile = your real DB. Disable startup reconciliation so app
    # creation doesn't probe/adopt other hosts while we run this checkpoint.
    app = create_app(
        "development",
        config_overrides={"STARTUP_RECONCILIATION_ENABLED": False},
    )

    capture_path = FIXTURES_DIR / capture_name
    # Start each checkpoint from a clean capture so replay judges only this run.
    if capture_path.exists():
        capture_path.unlink()
    app.wsgi_app = RecordingMiddleware(app.wsgi_app, capture_path)

    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    ingest_base = f"http://127.0.0.1:{port}"
    app.config["INGEST_BASE_URL"] = ingest_base

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"[checkpoint] plane listening on {ingest_base}")
    print(f"[checkpoint] capturing to {capture_path}")

    supervisor = HostSupervisor()
    dataflow_id = None
    started = False
    meta: dict = {"mode": kill or ("packet5" if packet5 else "clean"), "capture": capture_name}
    try:
        with app.app_context():
            # --template builds a fresh DRAFT session from your template file;
            # --session-id uses an existing one.
            if template is not None:
                session_id = _draft_session_from_template(template)
            session = SessionRepository().get(session_id)
            if session is None:
                raise SystemExit(f"no session with id {session_id!r} in your database")
            print(f"[checkpoint] session {session_id} status={session.status}")

            if packet5:
                # PACKET 5 PATH: launch app.watchdog_process directly — the new
                # sender that emits the identity-rich envelope. No supervisor,
                # no start_managed, no operations.
                _run_watchdog_process(
                    session_id=session_id,
                    ingest_base=ingest_base,
                    stream_seconds=stream_seconds,
                    with_faults=with_faults,
                )
            else:
                # start_managed expects to run inside an HTTP request, where the
                # request-logging middleware binds a request_id (a correlation tag
                # threaded through logs + the watchdog command). This script has no
                # request, so bind one ourselves — exactly what the middleware does.
                bind_contextvars(request_id=uuid4().hex)

                # THE REAL START PATH: start_managed spawns the host AND dispatches
                # the 'start' command that actually begins collection — exactly what
                # `pinnacle session start` does. So do NOT also run pinnacle: this IS
                # the start. It rejects a non-DRAFT/SCHEDULED session, so use a fresh
                # session (a COMPLETED one cannot be started again).
                print("[checkpoint] starting session on real hardware...")
                session = sessions_service.start_managed(session_id, supervisor)
                started = True
                dataflow_id = session.dataflow_id
                meta.update({"session_id": session_id, "dataflow_id": dataflow_id})
                from app.repositories.runtime_ownership import RuntimeOwnershipRepository

                ownership = RuntimeOwnershipRepository().active_for_dataflow(dataflow_id)
                if ownership is not None:
                    meta["runtime_id"] = ownership.runtime_id
                print(f"[checkpoint] session ACTIVE -> dataflow {dataflow_id}")
                print(f"[checkpoint] streaming for {stream_seconds:.0f}s...")
                time.sleep(stream_seconds)

                if kill == "stop-race":
                    # LAYER 3+2 CRASH DURING STOP (packet 9): kill watchdog AND
                    # host so no stop proof can exist, then attempt a clean stop.
                    # Spec: session stays ACTIVE (retryable), operation FAILED,
                    # device claims retained — never a fake COMPLETED.
                    entry = supervisor._children[dataflow_id]  # noqa: SLF001
                    status = supervisor._probe_status(entry.port)  # noqa: SLF001
                    print("[checkpoint] fault: kill watchdog + host, then request stop")
                    _hard_kill_pid(int(status.get("watchdog_pid") or 0))
                    entry.proc.kill()
                    with suppress(Exception):
                        entry.proc.wait(timeout=5)
                    meta["killed_at"] = _now_iso()
                    bind_contextvars(request_id=uuid4().hex)
                    try:
                        sessions_service.stop_managed(session_id, supervisor)
                        meta["stop_result"] = "completed"  # spec violation if reached
                        print("[checkpoint]   stop reported CLEAN — spec violation, see judge")
                    except Exception as stop_exc:  # noqa: BLE001 - the outcome IS the data
                        meta["stop_result"] = type(stop_exc).__name__
                        print(f"[checkpoint]   stop refused: {type(stop_exc).__name__} (expected StopProofMissing)")
                    started = False  # evidence preserved on purpose — do NOT force-teardown
                    print(
                        "[checkpoint] NOTE: session left ACTIVE with claims held (that's the "
                        "evidence). After judging, recover with:\n"
                        f"  venv\\Scripts\\python.exe -m tests.hardware.checkpoint --recover {session_id}"
                    )
                else:
                    if kill == "watchdog":
                        # LAYER 3 CRASH: kill the watchdog process mid-stream.
                        # Spec (packet 8): host detects, respawns under same
                        # runtime_id with NEW watchdog_id; identity rotated before
                        # new reports accepted; respawned watchdog streams.
                        entry = supervisor._children[dataflow_id]  # noqa: SLF001
                        status = supervisor._probe_status(entry.port)  # noqa: SLF001
                        wd_a = status.get("watchdog_id")
                        meta["watchdog_a"] = wd_a
                        print(f"[checkpoint] fault: hard-kill watchdog {str(wd_a)[:8]} "
                              f"(pid {status.get('watchdog_pid')})")
                        _hard_kill_pid(int(status.get("watchdog_pid") or 0))
                        meta["watchdog_killed_at"] = _now_iso()
                        print("[checkpoint] waiting for packet-8 respawn (poll_health via /status)...")
                        new_status = _wait_for_new_watchdog(supervisor, entry.port, wd_a)
                        meta["watchdog_b"] = (new_status or {}).get("watchdog_id")
                        meta["watchdog_b_state"] = (new_status or {}).get("watchdog_state")
                        if new_status is None:
                            print("[checkpoint]   RESPAWN DID NOT PRODUCE A LIVE WATCHDOG — "
                                  "packet 8 finding; check host log: "
                                  f"{supervisor.runtime_log_path(dataflow_id)}")
                        else:
                            print(f"[checkpoint]   respawned as {meta['watchdog_b'][:8]}; "
                                  f"streaming {stream_seconds:.0f}s more...")
                            time.sleep(stream_seconds)

                    elif kill == "host":
                        # LAYER 2 CRASH: kill runtime_host; watchdog keeps posting
                        # directly. Spec (packet 6): telemetry continues during the
                        # outage; a replacement host ADOPTS the live watchdog.
                        entry = supervisor._children[dataflow_id]  # noqa: SLF001
                        status = supervisor._probe_status(entry.port)  # noqa: SLF001
                        meta["watchdog_before"] = status.get("watchdog_id")
                        print(f"[checkpoint] fault: kill runtime_host (pid {entry.proc.pid}); "
                              "watchdog should keep streaming...")
                        entry.proc.kill()
                        with suppress(Exception):
                            entry.proc.wait(timeout=5)
                        meta["host_killed_at"] = _now_iso()
                        time.sleep(stream_seconds)  # window where ONLY direct ingest can deliver
                        meta["orphan_window_end"] = _now_iso()
                        print("[checkpoint] reconcile: replacement host should ADOPT the live watchdog")
                        supervisor._children.pop(dataflow_id, None)  # noqa: SLF001
                        supervisor.reconcile([session])
                        meta["host_respawned"] = dataflow_id in supervisor._children  # noqa: SLF001
                        if meta["host_respawned"]:
                            with suppress(Exception):
                                st = supervisor._probe_status(  # noqa: SLF001
                                    supervisor._children[dataflow_id].port  # noqa: SLF001
                                )
                                meta["watchdog_after"] = st.get("watchdog_id")
                                meta["watchdog_state_after"] = st.get("watchdog_state")
                        time.sleep(5)

                    elif kill == "plane":
                        # LAYER 1 CRASH: take the control plane DOWN mid-stream.
                        # Spec (packet 4): watchdog spools to its SQLite outbox and,
                        # when the plane returns, flushes every pending report_id
                        # exactly once — no losses, no duplicates.
                        meta["outage_start"] = _now_iso()
                        print(f"[checkpoint] fault: plane DOWN for {stream_seconds:.0f}s "
                              "(watchdog spools to outbox)...")
                        server.shutdown()
                        server_thread.join(timeout=5)
                        time.sleep(stream_seconds)
                        server = make_server("127.0.0.1", port, app, threaded=True)
                        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                        server_thread.start()
                        meta["outage_end"] = _now_iso()
                        print(f"[checkpoint] plane BACK on :{port}; waiting for outbox flush...")
                        time.sleep(stream_seconds)

                    elif kill == "recover-fresh":
                        # RECOVERY ROW 1: host dead + watchdog ABSENT + leases free
                        # -> coordinator must START_FRESH. Hard-killing the watchdog
                        # releases its OS hardware leases (locks die with the pid).
                        entry = supervisor._children[dataflow_id]  # noqa: SLF001
                        st = supervisor._probe_status(entry.port)  # noqa: SLF001
                        meta["watchdog_a"] = st.get("watchdog_id")
                        old_runtime_id = meta.get("runtime_id")
                        print("[checkpoint] fault: kill host AND watchdog (row 1: start fresh)")
                        _hard_kill_pid(int(st.get("watchdog_pid") or 0))
                        entry.proc.kill()
                        with suppress(Exception):
                            entry.proc.wait(timeout=5)
                        meta["killed_at"] = _now_iso()
                        supervisor._children.pop(dataflow_id, None)  # noqa: SLF001
                        time.sleep(2)  # let the OS reap the pid so evidence reads dead
                        print("[checkpoint] reconcile -> expect START_FRESH")
                        supervisor.reconcile([session])
                        meta["old_ownership_after"] = _ownership_snapshot(old_runtime_id)
                        new_own = RuntimeOwnershipRepository().active_for_dataflow(dataflow_id)
                        replacement = (
                            new_own
                            if new_own is not None and new_own.runtime_id != old_runtime_id
                            else None
                        )
                        meta["new_runtime_id"] = replacement.runtime_id if replacement else None
                        if dataflow_id in supervisor._children:  # noqa: SLF001
                            with suppress(Exception):
                                st2 = supervisor._probe_status(  # noqa: SLF001
                                    supervisor._children[dataflow_id].port  # noqa: SLF001
                                )
                                meta["watchdog_b"] = st2.get("watchdog_id")
                            print(f"[checkpoint] fresh watchdog up; streaming {stream_seconds:.0f}s...")
                            time.sleep(stream_seconds)
                        else:
                            meta["watchdog_b"] = None
                            print("[checkpoint]   NO fresh host spawned — recovery deferred; "
                                  "see old_ownership_after in the meta")

                    elif kill == "recover-adopt":
                        # RECOVERY ROW 2: host dead, watchdog alive & authenticates
                        # -> coordinator must ADOPT and rebind it to the new host.
                        entry = supervisor._children[dataflow_id]  # noqa: SLF001
                        st = supervisor._probe_status(entry.port)  # noqa: SLF001
                        meta["watchdog_before"] = st.get("watchdog_id")
                        old_runtime_id = meta.get("runtime_id")
                        print("[checkpoint] fault: kill host only (row 2: adopt + rebind)")
                        entry.proc.kill()
                        with suppress(Exception):
                            entry.proc.wait(timeout=5)
                        meta["host_killed_at"] = _now_iso()
                        window = max(5.0, stream_seconds / 2)
                        time.sleep(window)  # direct ingest must keep landing here
                        meta["orphan_window_end"] = _now_iso()
                        supervisor._children.pop(dataflow_id, None)  # noqa: SLF001
                        print("[checkpoint] reconcile -> expect ADOPT (authenticated control probe)")
                        supervisor.reconcile([session])
                        meta["old_ownership_after"] = _ownership_snapshot(old_runtime_id)
                        new_own = RuntimeOwnershipRepository().active_for_dataflow(dataflow_id)
                        replacement = (
                            new_own
                            if new_own is not None and new_own.runtime_id != old_runtime_id
                            else None
                        )
                        meta["new_runtime_id"] = replacement.runtime_id if replacement else None
                        meta["watchdog_after"] = replacement.watchdog_id if replacement else None
                        if dataflow_id in supervisor._children:  # noqa: SLF001
                            with suppress(Exception):
                                st2 = supervisor._probe_status(  # noqa: SLF001
                                    supervisor._children[dataflow_id].port  # noqa: SLF001
                                )
                                meta["watchdog_state_after"] = st2.get("watchdog_state")
                        print(f"[checkpoint] streaming under the rebound watchdog {stream_seconds:.0f}s...")
                        time.sleep(stream_seconds)

                    elif kill == "recover-adopt-fail":
                        # RECOVERY ROW 3: watchdog authenticates but ADOPTION FAILS
                        # -> gracefully stop that exact watchdog via its control
                        # channel, verify pid death + lease release, start fresh.
                        # The adoption failure is injected at the spawn seam — this
                        # scenario tests the coordinator's RESPONSE to the failure;
                        # adoption itself is covered by recover-adopt.
                        from app.runtime_host.watchdog_process_driver import pid_is_alive

                        entry = supervisor._children[dataflow_id]  # noqa: SLF001
                        st = supervisor._probe_status(entry.port)  # noqa: SLF001
                        meta["watchdog_before"] = st.get("watchdog_id")
                        wd_pid_before = int(st.get("watchdog_pid") or 0)
                        old_runtime_id = meta.get("runtime_id")
                        print("[checkpoint] fault: kill host; adoption will be made to fail (row 3)")
                        entry.proc.kill()
                        with suppress(Exception):
                            entry.proc.wait(timeout=5)
                        supervisor._children.pop(dataflow_id, None)  # noqa: SLF001

                        real_spawn = supervisor.spawn

                        def _spawn_failing_adoption(sess, **kwargs):
                            if kwargs.get("adopt_watchdog_id") is not None:
                                raise RuntimeError("injected_adoption_failure")
                            return real_spawn(sess, **kwargs)

                        supervisor.spawn = _spawn_failing_adoption  # type: ignore[method-assign]
                        try:
                            print("[checkpoint] reconcile -> ADOPT fails -> expect stop-exact + fresh")
                            supervisor.reconcile([session])
                        finally:
                            supervisor.spawn = real_spawn  # type: ignore[method-assign]

                        meta["old_watchdog_pid_alive_after"] = (
                            pid_is_alive(wd_pid_before) if wd_pid_before else None
                        )
                        meta["old_ownership_after"] = _ownership_snapshot(old_runtime_id)
                        new_own = RuntimeOwnershipRepository().active_for_dataflow(dataflow_id)
                        replacement = (
                            new_own
                            if new_own is not None and new_own.runtime_id != old_runtime_id
                            else None
                        )
                        meta["new_runtime_id"] = replacement.runtime_id if replacement else None
                        meta["watchdog_b"] = replacement.watchdog_id if replacement else None
                        if dataflow_id in supervisor._children:  # noqa: SLF001
                            print(f"[checkpoint] fresh watchdog up; streaming {stream_seconds:.0f}s...")
                            time.sleep(stream_seconds)
                        else:
                            print("[checkpoint]   stop-exact or fresh start did not complete — "
                                  "recovery deferred; see old_ownership_after")

                    elif kill == "recover-conflict":
                        # RECOVERY ROW 4: evidence CONFLICTS (control-plane token
                        # record no longer matches the live watchdog) -> stay
                        # RECOVERING, block hardware, back off and re-probe.
                        from app.database import transaction as _txn

                        entry = supervisor._children[dataflow_id]  # noqa: SLF001
                        st = supervisor._probe_status(entry.port)  # noqa: SLF001
                        meta["watchdog_before"] = st.get("watchdog_id")
                        old_runtime_id = meta.get("runtime_id")
                        print("[checkpoint] fault: kill host + corrupt token record (row 4)")
                        entry.proc.kill()
                        with suppress(Exception):
                            entry.proc.wait(timeout=5)
                        meta["host_killed_at"] = _now_iso()
                        supervisor._children.pop(dataflow_id, None)  # noqa: SLF001

                        repo = RuntimeOwnershipRepository()
                        row = repo.get(old_runtime_id)
                        original_token = row.token
                        with _txn():
                            row.token = f"conflict-{uuid4().hex}"
                        meta["conflict_injected_at"] = _now_iso()

                        print("[checkpoint] reconcile -> authenticated probe must FAIL -> RETRY")
                        supervisor.reconcile([session])
                        meta["recovering_snapshot"] = _ownership_snapshot(old_runtime_id)
                        meta["host_respawned_during_conflict"] = (
                            dataflow_id in supervisor._children  # noqa: SLF001
                        )
                        window = max(10.0, stream_seconds / 2)
                        print(f"[checkpoint] conflict window {window:.0f}s — watchdog must keep "
                              "streaming; hardware stays blocked; backoff probes fire...")
                        time.sleep(window)
                        meta["recovering_snapshot_late"] = _ownership_snapshot(old_runtime_id)
                        meta["conflict_window_end"] = _now_iso()

                        print("[checkpoint] repair the token record -> next probe should ADOPT")
                        supervisor._cancel_recovery_retry(dataflow_id)  # noqa: SLF001
                        row2 = repo.get(old_runtime_id)
                        with _txn():
                            row2.token = original_token
                        supervisor.reconcile([session])
                        new_own = RuntimeOwnershipRepository().active_for_dataflow(dataflow_id)
                        replacement = (
                            new_own
                            if new_own is not None and new_own.runtime_id != old_runtime_id
                            else None
                        )
                        meta["new_runtime_id"] = replacement.runtime_id if replacement else None
                        meta["watchdog_after"] = replacement.watchdog_id if replacement else None
                        time.sleep(5)

                    elif with_faults:
                        print("[checkpoint] fault: respawn (identity change)")
                        old, new = fault_menu.respawn(supervisor, session)
                        print(f"[checkpoint]   old watchdog_id={old.watchdog_id!r}")
                        print(f"[checkpoint]   new watchdog_id={new.watchdog_id!r}")
                        time.sleep(stream_seconds)

                    # Each command is its own traceable operation, so it needs its own
                    # request_id — reusing start's key for stop trips RequestKeyConflict.
                    # The real system gets a fresh id per HTTP request; mirror that.
                    bind_contextvars(request_id=uuid4().hex)
                    try:
                        sessions_service.stop_managed(session_id, supervisor)
                        meta["final_stop"] = "clean"
                    except Exception as stop_exc:  # noqa: BLE001 - record, then force
                        meta["final_stop"] = type(stop_exc).__name__
                        print(f"[checkpoint] clean stop failed ({type(stop_exc).__name__}); forcing")
                        bind_contextvars(request_id=uuid4().hex)
                        sessions_service.stop_managed(session_id, supervisor, force=True)
                    started = False
                    print("[checkpoint] session stopped")
    except Exception as exc:
        # Surface the child's own stderr log — that's where a real hardware
        # driver failure actually prints its traceback.
        print(f"[checkpoint] ERROR: {type(exc).__name__}: {exc}")
        if dataflow_id is not None:
            try:
                log_path = supervisor.runtime_log_path(dataflow_id)
                if log_path:
                    print(f"[checkpoint] child log (read this for the real cause): {log_path}")
            except Exception:
                pass
        # Don't leave a real host running if we errored mid-stream.
        if started:
            try:
                with app.app_context():
                    bind_contextvars(request_id=uuid4().hex)
                    sessions_service.stop_managed(session_id, supervisor, force=True)
                print("[checkpoint] host torn down after error")
            except Exception:
                pass
        raise
    finally:
        _write_meta(meta)
        with suppress(Exception):
            server.shutdown()
            server_thread.join(timeout=5)

    lines = capture_path.read_text(encoding="utf-8").count("\n") if capture_path.exists() else 0
    print(f"[checkpoint] done. captured {lines} report(s) -> {capture_path}")
    return capture_path


def recover_session(session_id: int) -> None:
    """Force-stop a session left ACTIVE by a --kill stop-race run (after judging)."""
    app = create_app("development", config_overrides={"STARTUP_RECONCILIATION_ENABLED": False})
    with app.app_context():
        bind_contextvars(request_id=uuid4().hex)
        session = sessions_service.stop_managed(session_id, HostSupervisor(), force=True)
        print(f"[checkpoint] session {session_id} recovered -> {session.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Packet-3 hardware checkpoint")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session-id", type=int, help="Run an existing DRAFT session by id")
    source.add_argument(
        "--template",
        type=Path,
        help="Build a fresh DRAFT session from a session-template .toml, then run it",
    )
    source.add_argument(
        "--recover",
        type=int,
        metavar="SESSION_ID",
        help="Force-stop a session left ACTIVE by a --kill stop-race run, then exit",
    )
    parser.add_argument(
        "--kill",
        choices=(
            "watchdog", "host", "plane", "stop-race",
            "recover-fresh", "recover-adopt", "recover-adopt-fail", "recover-conflict",
        ),
        default=None,
        help="Crash one layer mid-stream and record the recovery: 'watchdog' "
        "(packet-8 respawn), 'host' (packet-6 adoption + direct-ingest continuity), "
        "'plane' (packet-4 outbox exactly-once), 'stop-race' (packet-9 stop proof). "
        "Recovery-matrix rows: 'recover-fresh' (watchdog absent + leases free -> "
        "start fresh), 'recover-adopt' (watchdog authenticates -> adopt + rebind), "
        "'recover-adopt-fail' (adoption fails -> stop exact watchdog, verify, fresh), "
        "'recover-conflict' (evidence conflicts -> RECOVERING + blocked + backoff).",
    )
    parser.add_argument(
        "--capture-name",
        default="latest_capture.jsonl",
        help="Fixture filename under tests/hardware/fixtures/ (the replay reads this)",
    )
    parser.add_argument(
        "--stream-seconds",
        type=float,
        default=30.0,
        help=(
            "How long to let reports flow before (and after) faults. Morelia needs "
            "~10s to cold-init the pods before its first report, so keep this well "
            "above that or you capture nothing."
        ),
    )
    parser.add_argument(
        "--faults",
        action="store_true",
        help="Also walk the fault menu (respawn). Omit for a clean first recording.",
    )
    parser.add_argument(
        "--packet5",
        action="store_true",
        help="Launch app.watchdog_process (packet 5's new sender) instead of the "
        "old supervisor/runtime_host path — captures the identity-rich envelope.",
    )
    args = parser.parse_args()
    if args.recover is not None:
        recover_session(args.recover)
        return
    if args.kill and (args.packet5 or args.faults):
        parser.error("--kill uses the full supervision chain; drop --packet5/--faults")
    run_checkpoint(
        session_id=args.session_id,
        template=args.template,
        capture_name=args.capture_name,
        stream_seconds=args.stream_seconds,
        with_faults=args.faults,
        packet5=args.packet5,
        kill=args.kill,
    )


if __name__ == "__main__":
    main()
