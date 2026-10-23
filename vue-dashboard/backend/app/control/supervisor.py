"""
``HostSupervisor`` is the daemon's process manager for different Dataflow Control Host
that manages one watchdog.
It spawns ``python -m app.runtime_host`` child processes, reads back their
bound ports, and persists identity (port + token) to the ``sessions`` table
so the daemon can reconnect after a restart without double-spawning .

Design notes
------------
- ONE host per dataflow.  ``spawn()`` raises ``HostAlreadyRunning`` when
  the supervisor already has a live in-memory entry for the dataflow.
- Token generated with ``secrets.token_hex(32)`` (64 hex chars); persisted
  to DB and passed to the child via ``--token``.
- The manifest is written to a ``mkstemp`` temp file, closed before the
  subprocess starts, and deleted by ``stop()``.  The child reads it once
  at startup (arch doc line 121) and never re-reads from disk.
- Session DB writes go through ``SessionRepository``; callers must be within an
  active Flask application context.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import structlog
from flask import current_app

from app.control.event_poller import DataflowTarget, EventPoller
from app.control.startup_output import startup_output
from app.control.watchdog_recovery import RecoveryAction, WatchdogRecoveryCoordinator
from app.control.orphan_teardown import (
    AdministrativeStopEvidence, assess_containment_teardown, assess_orphan_teardown,
    ownership_teardown_confirmed,
)
from app.database import db, transaction
from app.domain.enums import RuntimeOwnershipState, SessionStatus, WatchdogProcessState
from app.domain.errors import RuntimeNotTracked, RuntimeStartupFailed, StopProofMissing
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.backend_events import BackendEventRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.runtime_host.process_evidence import (
    ProcessState, probe_process, record_process_identity, terminate_recorded_process,
)
from app.services import (
    device_configs,
    manifests,
    output_finalization,
)
from app.services import incidents as runtime_incidents
from app.services.event_ingest import ingest_report
from app.watchdog.adapters import ControlPlaneCommandSender
from app.watchdog.messages import CommandEnvelope, CorrelationEnvelope
from app.watchdog_process.outbox import WatchdogOutbox, default_outbox_path, read_lifecycle_reports

# ``RUNTIME_HOST_STOP_DRAIN_TIMEOUT_SECONDS`` is the upper bound on how long
# stop() waits for the child to flush its terminal report before hard-killing
# it. Its default (20s) covers the watchdog control request (2s), graceful
# stop window (8s), forced-reap window (5s), and final report/sink-close work.
#
# Must comfortably exceed the driver's own worst-case graceful-stop duration,
# not just "feel generous" — MoreliaRuntime.stop() (app/runtime_child/morelia.py)
# emits phase=STOPPED as its LAST step, after `self._watchdog_thread.join(
# timeout=self._timeout_sec + 1.0)` — 6.0s at MoreliaRuntime's default
# timeout_sec=5.0 — plus `watchdog.close()`/sink-close overhead. A 3.0s
# deadline was measured to reliably lose this race: it timed out before the
# thread join alone could finish, so stop() fell through to proc.terminate()
# and killed the child mid-teardown, before phase=STOPPED was ever emitted —
# the terminal backend_events row never appeared even though the stop
# operation itself reported "succeeded". If MoreliaRuntime's timeout_sec is
# ever changed, set the drain timeout with enough additional slack too.
# RuntimePhase values that count as durable proof a driver cleanly stopped.
_TERMINAL_PHASES = {RuntimePhase.STOPPED.value, RuntimePhase.CLOSED.value}


def _status_confirms_terminal(status: dict) -> bool:
    """Return true only for an explicit terminal runtime-host phase."""
    return bool(status) and status.get("phase") in _TERMINAL_PHASES

_log = structlog.get_logger(__name__)


class HostAlreadyRunning(RuntimeError):
    """A live Dataflow Runtime Host is already tracked for this dataflow."""


@dataclass
class _ChildEntry:
    proc: subprocess.Popen | None  # None for hosts adopted by reconcile()
    runtime_id: str
    port: int
    token: str | None
    manifest_path: str  # empty string for adopted hosts (no temp file to clean up)
    log_path: str = ""  # child stderr/stdout log; empty for adopted hosts


def _session_device_config_ids(session: Session) -> list[int]:
    """Deduplicated device_config ids referenced by a session's device_flows.

    Mirrors ``app.services.sessions._device_config_ids`` — kept local so the
    supervisor's shutdown cleanup does not depend on the sessions service.
    """
    ids: list[int] = []
    seen: set[int] = set()
    for flow in session.device_flows or []:
        if not isinstance(flow, dict):
            continue
        raw = flow.get("device_config_id")
        if raw is None:
            continue
        config_id = int(raw)
        if config_id not in seen:
            seen.add(config_id)
            ids.append(config_id)
    return ids


def _manifest_sink_type(manifest: Manifest, sink_id: object) -> str | None:
    if not isinstance(sink_id, str) or not sink_id:
        return None
    for flow in manifest.device_flows:
        for sink in flow.sinks:
            if sink.sink_id == sink_id:
                return sink.type.value
    return None


def _log_identity(session: Session, dataflow_id: str) -> dict[str, str]:
    """Use request correlation until the dataflow crosses its public boundary."""
    request_id = getattr(session, "_pending_request_id", None)
    if session.dataflow_id is None and isinstance(request_id, str) and request_id:
        return {"request_id": request_id}
    return {"dataflow_id": dataflow_id}


class HostSupervisor:
    """Process manager for Dataflow Runtime Host children.

    Must be called within an active Flask application context so that
    ``db.session`` is available for persisting host identity.
    """

    def __init__(self) -> None:
        self._children: dict[str, _ChildEntry] = {}
        self._sessions = SessionRepository()
        self._ownerships = RuntimeOwnershipRepository()
        self._events = BackendEventRepository()
        self._event_poller = EventPoller(
            targets=self.poll_targets,
            probe_status=self._probe_and_reconcile_watchdog,
        )
        self._recovery_coordinator: WatchdogRecoveryCoordinator | None = None
        self._recovery_timers: dict[str, threading.Timer] = {}
        self._recovery_timer_lock = threading.Lock()
        self._quiesced = False

    # -- public API -----------------------------------------------------------

    def _lifecycle_reports(self, ownership: RuntimeOwnership, *, pending_only=False):
        references = list((ownership.details or {}).get("predecessor_watchdogs") or [])
        if ownership.watchdog_id:
            references.append({"watchdog_id": ownership.watchdog_id,
                "outbox_path": ownership.watchdog_outbox_path})
        seen = set()
        for reference in references:
            path = reference.get("outbox_path")
            if not path or path in seen:
                continue
            seen.add(path)
            for report in read_lifecycle_reports(path, pending_only=pending_only):
                event = report.envelope
                if event.runtime_id != ownership.runtime_id:
                    # Adoption rebinds pending rows; the corresponding ownership
                    # row validates that producer independently.
                    continue
                if (event.watchdog_id != reference["watchdog_id"]
                        or event.dataflow_id != ownership.dataflow_id
                        or event.manifest_hash != ownership.manifest_hash):
                    raise ValueError("durable lifecycle producer identity mismatch")
                yield path, report

    def replay_watchdog_outboxes(self) -> None:
        """Replay known producers, including exited hosts; commit before marking delivered."""
        from app.services.event_ingest import ingest_watchdog_report
        for ownership in self._ownerships.list_all():
            try:
                for path, report in self._lifecycle_reports(ownership, pending_only=True):
                    ingest_watchdog_report(report.envelope.to_dict())
                    db.session.commit()
                    with WatchdogOutbox(path) as outbox:
                        outbox.mark_delivered(report.envelope.report_id)
            except Exception as exc:
                db.session.rollback()
                _log.warning("watchdog lifecycle replay deferred", runtime_id=ownership.runtime_id,
                    error=type(exc).__name__, message=str(exc))
        self._deliver_recorded_stop_intents()

    def _deliver_recorded_stop_intents(self) -> None:
        """Session intent follows replacement; stale teardown evidence never does."""
        from app.watchdog_process.control import WatchdogControlClient
        owners = self._ownerships.list_all()
        intents = {owner.session_id: ((owner.details or {}).get("stop_intent") or
                   (owner.details or {}).get("pending_stop_request"))
            for owner in owners if (owner.details or {}).get("stop_intent") or
            (owner.details or {}).get("pending_stop_request")}
        for owner in owners:
            if owner.state == RuntimeOwnershipState.STOPPED:
                continue
            intent = intents.get(owner.session_id)
            if not intent or not owner.watchdog_control_port or not owner.token:
                continue
            if owner.watchdog_state == WatchdogProcessState.STOPPED:
                continue
            try:
                client = WatchdogControlClient(port=owner.watchdog_control_port, token=owner.token)
                evidence = client.probe()
                if (evidence.get("watchdog_id") != owner.watchdog_id
                        or evidence.get("dataflow_id") != owner.dataflow_id
                        or evidence.get("manifest_hash") != owner.manifest_hash
                        or evidence.get("pid") != owner.watchdog_pid):
                    continue
                client.stop_watchdog(recovery_id=str(intent["command_id"]),
                    command_id=str(intent["command_id"]),
                    stop_reason=intent["stop_reason"], requested_at=intent["requested_at"])
            except Exception as exc:
                _log.warning("session stop intent delivery deferred", runtime_id=owner.runtime_id,
                    error=type(exc).__name__)

    def _replacement_recording_state(self, session: Session, manifest: Manifest, *, adopting=False):
        if session.status in (SessionStatus.STOPPING, SessionStatus.COMPLETED):
            raise RuntimeError("session stop intent forbids acquisition replacement")
        duration = getattr(manifest, "duration_seconds", None)
        owners = self._ownerships.list_for_session(session.id)
        if not owners:
            return None
        state = None
        stop_intent = False
        for owner in reversed(owners):
            if owner.manifest_hash != manifest.hash:
                continue
            if (owner.details or {}).get("stop_intent"):
                stop_intent = True
            if (owner.details or {}).get("pending_stop_request"):
                stop_intent = True
            if (owner.details or {}).get("recording_state"):
                state = dict(owner.details["recording_state"])
            try:
                for _, report in self._lifecycle_reports(owner):
                    event = report.envelope
                    if event.event_type in ("runtime.stop_requested", "runtime.stop_finished"):
                        stop_intent = True
                    elif event.event_type in ("runtime.acquisition_started", "runtime.recording_started", "runtime.recording_progress"):
                        state = dict(event.payload)
            except (OSError, ValueError, RuntimeError) as exc:
                if duration is not None and not adopting:
                    raise RuntimeError("missing durable timing forbids replacement") from exc
        if stop_intent:
            raise RuntimeError("durable session stop intent forbids acquisition replacement")
        if duration is not None and not adopting:
            if not state:
                raise RuntimeError("possibly started timed producer has no timing proof")
            from app.watchdog_process.process import remaining_recording_seconds
            if remaining_recording_seconds(state, duration) <= 0:
                raise RuntimeError("recording deadline forbids acquisition replacement")
        return state

    def spawn(
        self,
        session: Session,
        *,
        manifest: Manifest | None = None,
        adopt_watchdog_id: str | None = None,
        adopt_watchdog_pid: int | None = None,
        adopt_watchdog_control_port: int | None = None,
        recovery_token: str | None = None,
    ) -> int:
        """Start a Dataflow Runtime Host for ``session``; return the bound port.
        Parent process will write into runtime_ownership database to establish the relationship
        between parent and its child. Child process (DataFlow Control Host) will receive
        a token to later use to authenticate and know who is the correct parent process. Child
        will refuse to perform high risk action if parent information is not aligned.

        ``adopt_watchdog_id``/``adopt_watchdog_pid`` — passed by ``reconcile()``
        when a previous runtime_host for this dataflow is confirmed dead but
        its watchdog process may have survived (orphan-survivable spawn, see
        ``app.runtime_host.watchdog_process_driver``). The freshly spawned
        runtime_host verifies liveness itself and reports the outcome via
        ``/status``; on success this method persists the adoption onto the
        new runtime_id row via ``adopt_watchdog``. A normal fresh spawn
        passes neither and behaves exactly as before.

        Raises:
            HostAlreadyRunning — an entry for ``session.dataflow_id`` is
                                 already tracked in memory.
            ValueError         — the session has no dataflow_id, or its
                                 device_flows cannot form a valid Manifest.
            RuntimeError       — the child process exited before printing READY.
        """
        dataflow_id = session.dataflow_id or getattr(session, "_pending_dataflow_id", None)
        if not dataflow_id:
            raise ValueError("session has no dataflow_id")
        if dataflow_id in self._children:
            raise HostAlreadyRunning(
                f"a runtime host is already running for dataflow {dataflow_id!r}"
            )

        manifest = manifest or self._build_manifest(session)
        startup_timeout = float(current_app.config["RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS"])
        if not math.isfinite(startup_timeout) or startup_timeout <= 0:
            raise ValueError("RUNTIME_HOST_STARTUP_TIMEOUT_SECONDS must be finite and positive")
        recording_state = self._replacement_recording_state(session, manifest, adopting=adopt_watchdog_id is not None)
        runtime_driver = str(current_app.config.get("RUNTIME_DRIVER", "morelia"))
        # Pass the resolved manifest so readiness is selection-aware: only the
        # sink types this session actually selects are dependency-checked, and a
        # missing one fails here — before any runtime_host/watchdog child is
        # spawned or any hardware lease is taken (gap SINK-13).
        ensure_runtime_driver_ready(runtime_driver, manifest)

        token = recovery_token or secrets.token_hex(32)
        runtime_id = uuid4().hex
        self._ownerships.create_starting(
            runtime_id=runtime_id,
            session_id=session.id,
            dataflow_id=dataflow_id,
            manifest_hash=manifest.hash,
            token=token,
        )
        watchdog_id = adopt_watchdog_id or uuid4().hex
        outbox_dir = current_app.config["WATCHDOG_OUTBOX_DIR"]
        if not adopt_watchdog_id:
            self._ownerships.set_watchdog(runtime_id, watchdog_id=watchdog_id,
                outbox_path=str(default_outbox_path(outbox_dir, watchdog_id)))

        # Write the manifest to a temp file; child reads it once at startup.
        fd, manifest_path = tempfile.mkstemp(suffix=".json", prefix="ged-manifest-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(manifest.to_dict(), fh)
        except Exception:
            os.unlink(manifest_path)
            raise

        ingest_base = current_app.config.get("INGEST_BASE_URL") or current_app.config.get(
            "CONTROL_PLANE_BASE_URL", ""
        )
        ingest_token = current_app.config.get("INGEST_TOKEN") or ""
        ingest_args: list[str] = []
        ingest_args += ["--outbox-dir", str(outbox_dir), "--watchdog-id", watchdog_id]
        if recording_state:
            ingest_args += ["--recording-state", json.dumps(recording_state)]
        if ingest_base:
            # BASE url only — every sender downstream (runtime_host's push,
            # TelemetryClient in the watchdog process) appends
            # /api/v1/internal/events itself (see runtime_host/__main__.py
            # --ingest-url help). Appending it here doubles the path -> 404.
            ingest_args += ["--ingest-url", ingest_base]
        if ingest_token:
            ingest_args += ["--ingest-token", ingest_token]
        hardware_lock_dir = current_app.config.get("WATCHDOG_HARDWARE_LOCK_DIR")
        if hardware_lock_dir:
            ingest_args += ["--hardware-lock-dir", str(hardware_lock_dir)]
        adopt_args: list[str] = []
        if adopt_watchdog_id is not None and adopt_watchdog_pid is not None:
            adopt_args += [
                "--adopt-watchdog-id", adopt_watchdog_id,
                "--adopt-watchdog-pid", str(adopt_watchdog_pid),
            ]
            if adopt_watchdog_control_port is not None:
                adopt_args += [
                    "--adopt-watchdog-control-port",
                    str(adopt_watchdog_control_port),
                ]

        # stderr MUST land somewhere a human can read it. A child that dies with
        # an uncaught exception (e.g. a hardware-driver failure inside a
        # background thread) writes its traceback to stderr; piping it with
        # nothing ever reading the pipe just buffers it into the void (and
        # risks the child blocking once the OS pipe fills).
        log_fd, log_path = tempfile.mkstemp(suffix=".log", prefix="ged-runtime-")
        log_handle = os.fdopen(log_fd, "w", encoding="utf-8")

        startup_deadline = time.monotonic() + startup_timeout
        try:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "app.runtime_host",
                    "--manifest", manifest_path,
                    "--port", "0",
                    "--token", token,
                    "--runtime-id", runtime_id,
                    "--driver", runtime_driver,
                    *ingest_args,
                    *adopt_args,
                ],
                stdout=subprocess.PIPE,
                stderr=log_handle,
                text=True,
                env={**os.environ, "DATABASE_URL": str(current_app.config["SQLALCHEMY_DATABASE_URI"])},
            )
        except Exception:
            log_handle.close()
            with transaction():
                owner = self._ownerships.get(runtime_id)
                owner.details = dict(owner.details or {}) | {"host_launch_failed": True}
                if not adopt_watchdog_id:
                    owner.watchdog_id = None
                    owner.state = RuntimeOwnershipState.STOPPED
                    owner.stopped_at = datetime.now(UTC)
            raise
        log_handle.close()  # child holds its own fd; this process doesn't write to it
        # READY may never arrive. Retain the process identity before reading
        # stdout so a failed startup still has an OS-observable cleanup target.
        with transaction():
            db.session.execute(db.update(RuntimeOwnership).where(
                RuntimeOwnership.runtime_id == runtime_id
            ).values(pid=RuntimeOwnership.pid))
            owner = self._ownerships.get(runtime_id)
            db.session.refresh(owner)
            if (owner.details or {}).get("host_process_identity_source") != "runtime_host":
                owner.pid = proc.pid
                owner.details = {**(owner.details or {}),
                                 "host_process_identity": record_process_identity(proc.pid)}
        _log.info(
            "runtime host spawned",
            **_log_identity(session, dataflow_id),
            action="spawn",
            reason=f"child stderr log: {log_path}",
        )

        port: int | None = None
        ready = False
        startup_error: RuntimeStartupFailed | None = None
        try:
            with startup_output(proc.stdout, deadline=startup_deadline) as lines:
                for line in lines:
                    line = line.strip()
                    if line.startswith("ERROR:"):
                        payload = json.loads(line.split(":", 1)[1])
                        if isinstance(payload, dict):
                            sink_id = payload.get("sink_id")
                            startup_error = RuntimeStartupFailed(
                                error_type=str(
                                    payload.get("error_type") or "RuntimeStartupError"
                                )[:120],
                                message=str(
                                    payload.get("message") or "runtime startup failed"
                                )[:500],
                                device_id=payload.get("device_id"),
                                sink_id=sink_id,
                                sink_type=_manifest_sink_type(manifest, sink_id),
                            )
                        break
                    if line.startswith("PORT:"):
                        port = int(line.split(":", 1)[1])
                    elif line == "READY":
                        ready = True
                    if ready and port is not None:
                        break
        except TimeoutError:
            startup_error = RuntimeStartupFailed(
                error_type="StartupTimeout",
                message=(
                    f"Recording startup did not become ready within {startup_timeout:g} seconds. "
                    "Cleanup was requested; devices remain reserved until shutdown is confirmed."
                ),
            )
            _log.warning(
                "runtime host startup timed out", session_id=session.id,
                dataflow_id=dataflow_id, runtime_id=runtime_id,
                timeout_seconds=startup_timeout,
            )
        except Exception:
            self._cleanup_failed_start(session, runtime_id, proc, manifest_path)
            raise

        if startup_error is not None or not ready or port is None:
            self._cleanup_failed_start(session, runtime_id, proc, manifest_path)
            if startup_error is not None:
                runtime_incidents.evaluate_worker_startup_failure(
                    session_id=session.id,
                    dataflow_id=dataflow_id,
                    device_id=startup_error.details.get("device_id"),
                    sink_id=startup_error.details.get("sink_id"),
                    error_type=startup_error.details["error_type"],
                    message=str(startup_error),
                    sink_type=startup_error.details.get("sink_type"),
                )
                raise startup_error
            raise RuntimeError(
                f"runtime host for dataflow {dataflow_id!r} exited before reporting its port and READY "
                f"(child log: {log_path})"
            )

        db.session.refresh(owner)
        runtime_pid = owner.pid or proc.pid
        status: dict = {}
        try:
            status = self._probe_status(port)
        except Exception as exc:
            _log.warning(
                "spawn: post-spawn status probe failed",
                **_log_identity(session, dataflow_id),
                runtime_id=runtime_id,
                port=port,
                error=type(exc).__name__,
                message=str(exc),
            )
        if status.get("runtime_id") == runtime_id and isinstance(status.get("pid"), int):
            runtime_pid = status["pid"]
            with transaction():
                owner = self._ownerships.get(runtime_id)
                db.session.refresh(owner)
                owner.details = {**(owner.details or {}),
                                 "host_process_identity": record_process_identity(runtime_pid)}
        if adopt_watchdog_id is not None and status:
            if (
                status.get("watchdog_state") == "adopted"
                and status.get("watchdog_id") == adopt_watchdog_id
            ):
                try:
                    self._ownerships.adopt_watchdog(
                        runtime_id,
                        watchdog_id=adopt_watchdog_id,
                        pid=status.get("watchdog_pid"),
                        control_port=status.get("watchdog_control_port"),
                        outbox_path=status.get("watchdog_outbox_path") or str(default_outbox_path(outbox_dir, adopt_watchdog_id)),
                    )
                    _log.info(
                        "spawn: surviving watchdog adopted and persisted",
                        **_log_identity(session, dataflow_id),
                        runtime_id=runtime_id,
                        watchdog_id=adopt_watchdog_id,
                        watchdog_pid=status.get("watchdog_pid"),
                    )
                except Exception as exc:
                    _log.warning(
                        "spawn: host adopted watchdog but persisting the claim failed",
                        **_log_identity(session, dataflow_id),
                        runtime_id=runtime_id,
                        watchdog_id=adopt_watchdog_id,
                        error=type(exc).__name__,
                        message=str(exc),
                    )
            else:
                _log.warning(
                    "spawn: adoption hints passed but host reports watchdog NOT adopted",
                    **_log_identity(session, dataflow_id),
                    runtime_id=runtime_id,
                    watchdog_id=adopt_watchdog_id,
                    watchdog_state=status.get("watchdog_state"),
                    probed_watchdog_id=status.get("watchdog_id"),
                )
                # The candidate can die between the coordinator's probe and
                # child construction. In that case the replacement safely
                # acquires the now-free hardware leases and starts a fresh
                # watchdog. Persist the actual outcome instead of dropping its
                # new identity merely because adoption was attempted.
                reported_id = status.get("watchdog_id")
                if reported_id and reported_id != adopt_watchdog_id:
                    self._ownerships.set_watchdog(
                        runtime_id,
                        watchdog_id=reported_id,
                        token_hash=status.get("watchdog_token_hash"),
                        pid=status.get("watchdog_pid"),
                        control_port=status.get("watchdog_control_port"),
                    )
                    self._ownerships.update_watchdog_seen(
                        runtime_id,
                        watchdog_id=reported_id,
                        pid=status.get("watchdog_pid"),
                        control_port=status.get("watchdog_control_port"),
                        state=WatchdogProcessState.RUNNING,
                    )
        elif status.get("watchdog_id"):
            # The watchdog is already alive because runtime-host READY is now
            # gated on watchdog preflight. Persist that identity before
            # start_managed() constructs its first command envelope; otherwise
            # the envelope targets the session UUID rather than the active
            # child-process UUID and LifecycleSafetyGate rejects it as stale.
            self._ownerships.set_watchdog(
                runtime_id,
                watchdog_id=status["watchdog_id"],
                token_hash=status.get("watchdog_token_hash"),
                pid=status.get("watchdog_pid"),
                control_port=status.get("watchdog_control_port"),
            )
            reported_state = status.get("watchdog_state")
            try:
                watchdog_state = WatchdogProcessState(reported_state or "running")
            except ValueError:
                watchdog_state = WatchdogProcessState.RUNNING
            if watchdog_state in (
                WatchdogProcessState.RUNNING,
                WatchdogProcessState.ADOPTED,
            ):
                self._ownerships.update_watchdog_seen(
                    runtime_id,
                    watchdog_id=status["watchdog_id"],
                    pid=status.get("watchdog_pid"),
                    control_port=status.get("watchdog_control_port"),
                    state=watchdog_state,
                )
        self._ownerships.mark_running(runtime_id, pid=runtime_pid, port=port)
        self._sessions.set_runtime_host_identity(session, port=port, token=token)

        self._children[dataflow_id] = _ChildEntry(
            proc=proc,
            runtime_id=runtime_id,
            port=port,
            token=token,
            manifest_path=manifest_path,
            log_path=log_path,
        )
        self._ensure_event_poller_running()
        return port

    def _cleanup_failed_start(self, session, runtime_id, proc, manifest_path) -> None:
        """Bound host termination and retain ownership until descendant cleanup is proven."""
        wait_timeout = current_app.config["RUNTIME_HOST_PROCESS_WAIT_TIMEOUT_SECONDS"]
        try:
            proc.terminate()
            proc.wait(timeout=wait_timeout)
        except (OSError, subprocess.TimeoutExpired):
            with suppress(OSError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait(timeout=wait_timeout)
        finally:
            with suppress(OSError):
                os.unlink(manifest_path)
            self._retire_failed_start(session, runtime_id)

    def _retire_failed_start(self, session: Session, runtime_id: str) -> None:
        owner = self._ownerships.get(runtime_id)
        if owner is None:
            return
        if owner.watchdog_id:
            try:
                result = self._stop_starting_watchdog(session, owner, None)
                from app.services.sessions import apply_shutdown_result
                apply_shutdown_result(session, result, owner)
                return
            except Exception:
                _log.exception("failed startup producer stop remains uncertain", runtime_id=runtime_id)
        if owner.watchdog_id:
            self._ownerships.mark_uncertain(runtime_id, details={"reason": "startup_teardown_unproven"})
        else:
            self._ownerships.mark_stopped(runtime_id)

    def _get_child(self, dataflow_id: str) -> _ChildEntry:
        try:
            return self._children[dataflow_id]
        except KeyError:
            raise RuntimeNotTracked(dataflow_id) from None

    def _pop_child(self, dataflow_id: str) -> _ChildEntry:
        try:
            return self._children.pop(dataflow_id)
        except KeyError:
            raise RuntimeNotTracked(dataflow_id) from None

    def dispatch(self, session: Session, envelope: CommandEnvelope) -> None:
        """Dispatch a command envelope to the runtime host owned by ``session``.

        Raises:
            RuntimeNotTracked — no in-memory registry entry for this dataflow
                (the runtime may have died, or the daemon restarted before
                reconciling it — see ``reconcile()``).
        """
        dataflow_id = envelope.correlation.dataflow_id
        entry = self._get_child(dataflow_id)
        sender = ControlPlaneCommandSender(
            base_url=f"http://127.0.0.1:{entry.port}",
            token=entry.token,
        )
        sender.dispatch(envelope)

    def stop(self, session: Session, *, envelope: CommandEnvelope | None = None) -> dict | AdministrativeStopEvidence | None:
        """Send stop command, terminate the process, and clear the DB columns.

        Raises:
            RuntimeNotTracked  — no in-memory registry entry for this dataflow.
            StopProofMissing   — the process was torn down but no durable stop
                                  proof was ever observed.
        """
        dataflow_id = session.dataflow_id or getattr(session, "_pending_dataflow_id", None)
        self._cancel_recovery_retry(dataflow_id)
        if dataflow_id not in self._children:
            owner = self._ownerships.unresolved_for_dataflow(dataflow_id)
            if owner is None:
                owners = self._ownerships.list_for_session(session.id)
                owner = owners[0] if owners and owners[0].dataflow_id == dataflow_id else None
            if owner is not None:
                if (owner.details or {}).get("host_launch_failed") is True and not owner.watchdog_id:
                    raise RuntimeNotTracked(dataflow_id)
                result = self._stop_starting_watchdog(session, owner, envelope)
                self._schedule_multi_owner_projection(session)
                return result
        entry = self._pop_child(dataflow_id)
        self._ownerships.mark_stopping(entry.runtime_id)

        # Evict the poller's live-health snapshot for this dataflow now, up
        # front — not after teardown finishes. `entry` is already popped, so
        # poll_targets() will never refresh this snapshot again regardless of
        # what happens below; if we waited until the end and something later
        # in this method raised (e.g. proc.wait() timing out), the stale
        # snapshot (often HEALTHY) would linger and _live_health() would keep
        # reporting live health for a dataflow that's mid-teardown or gone.
        self._event_poller.discard(dataflow_id)

        # Best-effort HTTP stop — the sender speaks the wire protocol including
        # the per-host token.  If the process is already dead we just terminate.
        try:
            sender = ControlPlaneCommandSender(
                base_url=f"http://127.0.0.1:{entry.port}",
                token=entry.token,
            )
            if envelope is not None:
                stop_envelope = envelope
            else:
                # No caller-supplied envelope (e.g. daemon-shutdown's stop_all()):
                # target the runtime's actual actively-tracked watchdog process
                # identity when one is known, not session.watchdog_id — a
                # WatchdogProcessDriver-backed host 400-rejects a command naming
                # the wrong identity (see sessions._active_watchdog_id).
                ownership = self._ownerships.get(entry.runtime_id)
                active_watchdog_id = (
                    ownership.watchdog_id if ownership is not None else None
                ) or session.watchdog_id or "supervisor"
                stop_envelope = CommandEnvelope(
                    command="stop",
                    stop_reason="application_shutdown",
                    correlation=CorrelationEnvelope(
                        request_id=uuid4().hex,
                        dataflow_id=dataflow_id,
                        command_id=uuid4().hex,
                        watchdog_id=active_watchdog_id,
                        recovery_id=None,
                    ),
                    target_device_id=None,
                )
            self._record_stop_intent(session, self._ownerships.get(entry.runtime_id), stop_envelope)
            sender.dispatch(stop_envelope)
        except Exception as exc:
            _log.warning(
                "stop: dispatching stop command to host failed — "
                "falling through to drain/terminate",
                **_log_identity(session, dataflow_id),
                runtime_id=entry.runtime_id,
                port=entry.port,
                error=type(exc).__name__,
                message=str(exc),
            )

        # The child applies `stop` on a background thread and ACKs before it
        # runs (server._execute_command), so the terminal phase=STOPPED report
        # is still in flight right now. Pull it and persist it BEFORE we kill
        # the process — otherwise the newest backend_events row stays frozen at
        # "running" forever. Best-effort: on timeout/unreachable we fall through
        # to terminate exactly as before.
        terminal_report_seen = False
        last_status: dict = {}
        try:
            terminal_report_seen, last_status = self._drain_terminal_report(entry)
        except Exception as exc:
            _log.warning(
                "stop: draining terminal report failed — proceeding to terminate "
                "without phase evidence",
                **_log_identity(session, dataflow_id),
                runtime_id=entry.runtime_id,
                port=entry.port,
                error=type(exc).__name__,
                message=str(exc),
            )

        watchdog_clean_exit = (
            last_status.get("watchdog_state") == WatchdogProcessState.STOPPED.value
        )

        # Proof tier 3: the host's own last-observed phase, captured before
        # terminate()/kill(), was explicitly terminal. In-progress and unknown
        # phases (including STOPPING) are not evidence that streams are gone.
        host_confirms_terminal = _status_confirms_terminal(last_status)

        if entry.proc is not None:
            entry.proc.terminate()
            try:
                entry.proc.wait(
                    timeout=current_app.config["RUNTIME_HOST_PROCESS_WAIT_TIMEOUT_SECONDS"]
                )
            except subprocess.TimeoutExpired:
                entry.proc.kill()
                with suppress(Exception):
                    entry.proc.wait(
                        timeout=current_app.config["RUNTIME_HOST_PROCESS_WAIT_TIMEOUT_SECONDS"]
                    )

        if entry.manifest_path:
            with suppress(OSError):
                os.unlink(entry.manifest_path)

        durable_terminal_report = False
        if not terminal_report_seen:
            try:
                latest = self._events.latest_report_for_session(session.id)
                durable_terminal_report = (
                    latest is not None and latest.phase in _TERMINAL_PHASES
                )
            except Exception as exc:
                _log.warning(
                    "stop: could not read durable terminal report from backend_events",
                    **_log_identity(session, dataflow_id),
                    runtime_id=entry.runtime_id,
                    error=type(exc).__name__,
                    message=str(exc),
                )

        stop_result = last_status.get("stop_result")
        ownership = self._ownerships.get(entry.runtime_id)
        if ownership is not None:
            try:
                for _, report in self._lifecycle_reports(ownership):
                    if (report.envelope.watchdog_id == ownership.watchdog_id
                            and report.envelope.event_type == "runtime.stop_finished"):
                        stop_result = dict(report.envelope.payload)
            except Exception:
                _log.exception("stop outcome outbox read failed", runtime_id=entry.runtime_id)
        stop_proven = (
            terminal_report_seen
            or durable_terminal_report
            or watchdog_clean_exit
            or host_confirms_terminal
        )
        if (getattr(session, "duration_seconds", None) is not None or stop_result is not None
                or (ownership is not None and (ownership.watchdog_id or ownership.watchdog_pid))):
            stop_proven = bool(stop_result and stop_result.get("teardown_confirmed"))

        if not self._children:
            self.stop_event_poller()

        if not stop_proven:
            if ownership is not None:
                recovered = self._administrative_stop_evidence(session, ownership, terminate_host=True)
                if recovered is not None:
                    self._schedule_multi_owner_projection(session)
                    return recovered
            self._ownerships.mark_uncertain(
                entry.runtime_id,
                details={"reason": "stop_proof_missing", "last_status": last_status or None},
            )
            if ownership is not None:
                self._retry_teardown(session, ownership)
            raise StopProofMissing(dataflow_id, runtime_id=entry.runtime_id)

        self._ownerships.mark_stopped(entry.runtime_id)
        self._sessions.clear_runtime_host_identity(session)
        self._schedule_multi_owner_projection(session)
        return stop_result

    def _schedule_multi_owner_projection(self, session):
        # A successful individual Stop may still leave historical producers to
        # reconcile. Complete their projection without requiring another click.
        if len(self._ownerships.list_for_session(session.id)) > 1:
            self._schedule_recovery_retry(session_id=session.id, dataflow_id=session.dataflow_id,
                                          delay_seconds=1)

    def _stop_starting_watchdog(self, session, owner, envelope):
        """Cancel a registered producer while host READY is still pending."""
        from app.watchdog_process.control import WatchdogControlClient
        self._record_stop_intent(session, owner, envelope)
        # Startup can fail and persist teardown before the control socket closes.
        # Read identity-validated durable evidence before requiring a live peer;
        # otherwise an already-exited producer leaves Stop stuck indefinitely.
        try:
            reports = list(self._lifecycle_reports(owner))
        except Exception:
            reports = []
        for _, report in reports:
            if (report.envelope.watchdog_id == owner.watchdog_id
                    and report.envelope.event_type == "runtime.stop_finished"
                    and report.envelope.payload.get("teardown_confirmed") is True):
                return dict(report.envelope.payload)
        recovered = self._administrative_stop_evidence(session, owner)
        if recovered is not None:
            return recovered
        self._ownerships.mark_stopping(owner.runtime_id)
        if not owner.watchdog_control_port or not owner.token:
            return self._finish_orphan_stop(session, owner)
        client = WatchdogControlClient(port=owner.watchdog_control_port, token=owner.token)
        try:
            evidence = client.probe()
        except Exception:
            return self._finish_orphan_stop(session, owner)
        if (evidence.get("watchdog_id") != owner.watchdog_id
                or evidence.get("runtime_id") != owner.runtime_id
                or evidence.get("manifest_hash") != owner.manifest_hash
                or evidence.get("dataflow_id") != owner.dataflow_id
                or evidence.get("pid") != owner.watchdog_pid):
            self._retry_teardown(session, owner)
            raise StopProofMissing(owner.dataflow_id, runtime_id=owner.runtime_id)
        intent = ((owner.details or {}).get("stop_intent") or
                  (owner.details or {}).get("pending_stop_request") or {}) if session is not None else {}
        command_id = intent.get("command_id") or (envelope.correlation.command_id if envelope else uuid4().hex)
        try:
            client.stop_watchdog(recovery_id=command_id, command_id=command_id,
                stop_reason=intent.get("stop_reason") or ("user_stop" if envelope else "application_shutdown"),
                requested_at=intent.get("requested_at"))
        except Exception:
            return self._finish_orphan_stop(session, owner)
        deadline = time.monotonic() + current_app.config["RUNTIME_HOST_STOP_DRAIN_TIMEOUT_SECONDS"]
        while time.monotonic() < deadline:
            try:
                reports = list(self._lifecycle_reports(owner))
            except Exception:
                break
            for _, report in reports:
                if (report.envelope.watchdog_id == owner.watchdog_id
                        and report.envelope.event_type == "runtime.stop_finished"):
                    result = dict(report.envelope.payload)
                    if result.get("teardown_confirmed"):
                        return result
                    # A historical negative receipt does not terminate a fresh
                    # attempt: a later sequence can carry stronger exit proof.
            time.sleep(0.1)
        return self._finish_orphan_stop(session, owner)

    def _record_stop_intent(self, session, owner, envelope=None):
        """Retain Stop authorization even when every child reporting channel fails."""
        if owner is None or session is None:
            return
        intent = next((value for row in self._ownerships.list_for_session(session.id)
                       for value in [(row.details or {}).get("pending_stop_request") or
                                     (row.details or {}).get("stop_intent")]
                       if value and all(value.get(key) for key in (
                           "command_id", "requested_at", "stop_reason"))), None)
        intent = intent or {
            "command_id": envelope.correlation.command_id if envelope else uuid4().hex,
            "stop_reason": (envelope.stop_reason if envelope else None) or "application_shutdown",
            "requested_at": datetime.now(UTC).isoformat(),
        }
        with transaction():
            db.session.refresh(owner)
            owner.details = {**(owner.details or {}), "pending_stop_request": intent}
            if owner.state != RuntimeOwnershipState.STOPPED:
                owner.state = RuntimeOwnershipState.STOPPING
            if session.status != SessionStatus.COMPLETED:
                session.status = SessionStatus.STOPPING

    def _finish_orphan_stop(self, session, owner):
        """Escalate a failed graceful stop to independently observed process cleanup."""
        recovered = self._administrative_stop_evidence(session, owner, terminate_host=True)
        if recovered is not None:
            return recovered
        self._retry_teardown(session, owner)
        raise StopProofMissing(owner.dataflow_id, runtime_id=owner.runtime_id)

    def _administrative_stop_evidence(self, session, owner, *, terminate_host=False):
        """Finish orphan cleanup using OS containment when shutdown reports are missing."""
        if session is None:
            return None
        from app.watchdog_process.hardware_lease import HardwareLeaseSet
        from app.models.runtime_manifest import RuntimeManifest
        try:
            observed_host_pid = owner.pid
            identity = (owner.details or {}).get("host_process_identity")
            host = probe_process(observed_host_pid)
            # A live host could start another watchdog after we enumerate its generations.
            if (host.state is not ProcessState.DEAD and terminate_host and identity
                    and identity.get("pid") == observed_host_pid):
                host = terminate_recorded_process(identity, timeout=current_app.config.get(
                    "RUNTIME_HOST_PROCESS_WAIT_TIMEOUT_SECONDS", 5.0))
            if host.state is not ProcessState.DEAD:
                return None
            db.session.refresh(owner)
            if (owner.pid != observed_host_pid
                    or (owner.details or {}).get("host_process_identity") != identity):
                return None
            frozen = db.session.scalar(db.select(RuntimeManifest).where(
                RuntimeManifest.hash == owner.manifest_hash))
            manifest = (Manifest.from_dict(frozen.content) if frozen is not None else
                        self._manifest_for_reconcile(session, owner.dataflow_id))
            if manifest.hash != owner.manifest_hash:
                return None
            try:
                reports = [r.envelope for _, r in self._lifecycle_reports(owner)
                           if r.envelope.event_type == "runtime.stop_finished"]
            except Exception:
                # A broken report channel must not prevent independent process cleanup.
                reports = []
            receipts = {r.watchdog_id: dict(r.payload) for r in reports}
            # Receipt ingestion may have already archived the original outbox.
            if owner.watchdog_id not in receipts and owner.watchdog_exit_details:
                receipts[owner.watchdog_id] = dict(owner.watchdog_exit_details)
            receipt = receipts.get(owner.watchdog_id)
            predecessors = (owner.details or {}).get("predecessor_watchdogs") or []
            intent = receipt or ((owner.details or {}).get("stop_intent") or
                                 (owner.details or {}).get("pending_stop_request"))
            if not intent or not all(intent.get(key) for key in (
                    "command_id", "requested_at", "stop_reason")):
                intent = next((value for row in self._ownerships.list_for_session(session.id)
                               for value in [(row.details or {}).get("pending_stop_request") or
                                             (row.details or {}).get("stop_intent")]
                               if value and all(value.get(key) for key in (
                                   "command_id", "requested_at", "stop_reason"))), None)
            cleanup = self._cleanup_contained_watchdogs(owner, predecessors, receipts) if intent else None
            generations = cleanup if cleanup and all(
                item.get("released") is True for item in cleanup.values()) else None
            legacy_compatible = cleanup is not None and all(
                item.get("released") is True or item.get("reason") in (
                    "containment_marker_missing", "unsupported_platform")
                for item in cleanup.values())
            watchdog = probe_process(owner.watchdog_pid)
            legacy_proven = bool(legacy_compatible and receipt and watchdog.state is ProcessState.DEAD and all(
                (receipts.get(p.get("watchdog_id")) or p.get("exit_details") or {}).get(
                    "teardown_confirmed") is True for p in predecessors
                if p.get("watchdog_id") != owner.watchdog_id))
            if generations is None and not legacy_proven:
                return None
            leases = HardwareLeaseSet(manifest, directory=current_app.config.get(
                "WATCHDOG_HARDWARE_LOCK_DIR", "watchdog-hardware-locks"))
            with leases:
                proof = None
                if generations is not None:
                    proof = assess_containment_teardown(runtime_id=owner.runtime_id,
                        watchdog_id=owner.watchdog_id, dataflow_id=owner.dataflow_id,
                        manifest_hash=owner.manifest_hash, stop_intent=intent,
                        receipt=receipt, host=host, generations=generations,
                        expected_watchdogs={owner.watchdog_id, *(p["watchdog_id"] for p in predecessors)},
                        hardware_leases_free=True)
                if proof is None and legacy_proven:
                    proof = assess_orphan_teardown(runtime_id=owner.runtime_id,
                        watchdog_id=owner.watchdog_id, dataflow_id=owner.dataflow_id,
                        manifest_hash=owner.manifest_hash, receipt=receipt,
                        expected_streams=len(manifest.device_flows), host=host, watchdog=watchdog,
                        hardware_leases_free=True, predecessors_confirmed=True)
                if proof is not None:
                    # Keep the physical lease fence through durable projection.
                    from app.services.sessions import apply_administrative_stop_evidence
                    apply_administrative_stop_evidence(session, proof, owner)
                return proof
        except Exception as exc:
            _log.warning("administrative teardown evidence unavailable", runtime_id=owner.runtime_id,
                         error=type(exc).__name__)
            return None

    def _cleanup_contained_watchdogs(self, owner, predecessors, receipts):
        """Terminate every enrolled watchdog generation, including its silent writers."""
        from app.watchdog_process.process_tree import cleanup_owned_process_tree
        references = [*predecessors, {"watchdog_id": owner.watchdog_id,
                                      "outbox_path": owner.watchdog_outbox_path}]
        deadline = time.monotonic() + current_app.config.get("WATCHDOG_PROCESS_REAP_TIMEOUT_SECONDS", 5.0)
        results = {}
        for reference in references:
            watchdog_id = reference.get("watchdog_id")
            if (not watchdog_id or reference.get("dataflow_id", owner.dataflow_id) != owner.dataflow_id
                    or reference.get("manifest_hash", owner.manifest_hash) != owner.manifest_hash):
                return None
            if watchdog_id in results:
                continue
            path = reference.get("outbox_path") or default_outbox_path(
                current_app.config.get("WATCHDOG_OUTBOX_DIR", "watchdog-outbox"), watchdog_id)
            result = cleanup_owned_process_tree(path, watchdog_id=watchdog_id,
                dataflow_id=owner.dataflow_id, manifest_hash=owner.manifest_hash, deadline=deadline)
            observed = result.to_dict()
            # Pre-upgrade generations may already have a complete durable exit receipt.
            previous = receipts.get(watchdog_id) or reference.get("exit_details") or {}
            if (not result.released and result.reason == "containment_marker_missing"
                    and watchdog_id != owner.watchdog_id and previous.get("teardown_confirmed") is True):
                observed = {"released": True, "reason": "durable_predecessor_teardown"}
            results[watchdog_id] = observed
        with transaction():
            db.session.refresh(owner)
            owner.details = {**(owner.details or {}), "process_tree_cleanup": results}
        return results

    def _retry_teardown(self, session, owner):
        """Back off cleanup attempts; the retry budget never releases ownership."""
        if session is None:
            return
        details = dict(owner.details or {})
        attempt = int((details.get("cleanup_retry") or {}).get("attempt", 0)) + 1
        delays = current_app.config.get("WATCHDOG_RECOVERY_RETRY_DELAYS_SECONDS", (1, 3, 10))
        maximum = current_app.config.get("WATCHDOG_RECOVERY_MAX_ATTEMPTS", 0)
        exhausted = bool(maximum and attempt > maximum)
        delay = delays[min(attempt - 1, len(delays) - 1)] if delays else 10
        with transaction():
            db.session.refresh(owner)
            db.session.refresh(session)
            if ((owner.state == RuntimeOwnershipState.STOPPED and ownership_teardown_confirmed(owner))
                    or session.status == SessionStatus.COMPLETED):
                return
            details = dict(owner.details or {})
            details["cleanup_retry"] = {"attempt": attempt, "exhausted": exhausted,
                "next_retry_at": None if exhausted else
                (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()}
            owner.details = details
            owner.state = RuntimeOwnershipState.UNCERTAIN
        if not exhausted:
            self._schedule_recovery_retry(session_id=session.id, dataflow_id=owner.dataflow_id,
                                          delay_seconds=delay)

    def reconcile_teardown(self, session, owner):
        """Retry the accepted shutdown for an unresolved owner, including no-port startup."""
        from app.services.sessions import (
            apply_shutdown_result, replay_shutdown_result, stop_managed,
        )
        from structlog.contextvars import bound_contextvars
        if session.dataflow_id != owner.dataflow_id:
            return None
        retry_owner = owner
        try:
            # stop_managed owns the durable request and terminal projection.
            with bound_contextvars(request_id=uuid4().hex):
                stop_managed(session.id, self)
            owners = self._ownerships.list_for_session(session.id)
            latest = owners[0] if owners else None
            if session.status == SessionStatus.STOPPING and latest is not None:
                # A newer producer can finish before an older generation. Its
                # positive receipt must not prevent the older owner being
                # reconciled, including historically misleading STOPPED rows.
                pending = next((item for item in owners[1:]
                                if not ownership_teardown_confirmed(item)), None)
                if pending is not None and pending.runtime_id != owner.runtime_id:
                    retry_owner = pending
                    result = self._stop_starting_watchdog(session, pending, None)
                    apply_shutdown_result(session, result, pending)
                replay_shutdown_result(session, latest)
                remaining = next((item for item in self._ownerships.list_for_session(session.id)
                                  if not ownership_teardown_confirmed(item)), None)
                if session.status == SessionStatus.STOPPING and remaining is not None:
                    self._retry_teardown(session, remaining)
            return self._ownerships.get(owner.runtime_id)
        except Exception as exc:
            self._retry_teardown(session, retry_owner)
            _log.warning("cleanup reconciliation deferred", runtime_id=owner.runtime_id,
                         error=type(exc).__name__)
            return None


    def _drain_terminal_report(self, entry: _ChildEntry) -> tuple[bool, dict]:
        """Wait for the child (DataflowHost) to reach phase=STOPPED, persisting its final reports.

        Repeatedly probes ``GET /status`` on the child and ingests every report it exposes
        (via ``ingest_report``), so the terminal ``phase="stopped"`` report becomes
        a durable ``backend_events`` row before the process dies.

        Returns ``(terminal_seen, last_status)``: ``terminal_seen`` is True once
        the child reports a stopped/closed phase (its terminal report is now
        persisted), False on timeout or if the child is unreachable and the
        parent has to perform a hard terminate. ``last_status`` is the last
        successfully probed ``/status`` payload (empty if the very first probe
        raised), so callers can inspect other proof signals (e.g.
        ``watchdog_state``) even when the phase itself never went terminal.
        """
        deadline = time.monotonic() + current_app.config[
            "RUNTIME_HOST_STOP_DRAIN_TIMEOUT_SECONDS"
        ]
        last_status: dict = {}
        while True:
            status = self._probe_status(entry.port)  # probe status from child
            last_status = status

            # Keep ingesting it to backend_events database. No duplication will be made
            # due to the mechanism set by the given function in ingest_report
            for raw in status.get("reports", []) or []:
                if isinstance(raw, dict):
                    try:
                        ingest_report(raw)
                    except Exception as exc:
                        _log.warning(
                            "drain: ingesting a child report failed — report dropped",
                            runtime_id=entry.runtime_id,
                            port=entry.port,
                            report_id=raw.get("report_id"),
                            error=type(exc).__name__,
                            message=str(exc),
                        )

            # Driver refused the stop — no terminal report is coming. Bail now so
            # stop() hard-terminates rather than spinning to the deadline.
            if status.get("last_command_error") is not None:
                err = status.get("last_command_error") or {}
                _log.warning(
                    "drain: child reports its last command failed — "
                    "no terminal report is coming",
                    runtime_id=entry.runtime_id,
                    port=entry.port,
                    command=err.get("command"),
                    command_id=err.get("command_id"),
                    error=err.get("error"),
                    message=err.get("message"),
                )
                return False, last_status

            if status.get("phase") in _TERMINAL_PHASES:
                return True, last_status

            if time.monotonic() >= deadline:
                return False, last_status
            time.sleep(
                current_app.config["RUNTIME_HOST_STOP_DRAIN_POLL_INTERVAL_SECONDS"]
            )

    def stop_all(self, *, force: bool = False) -> dict[str, object]:
        """Stop every runtime host currently tracked by this daemon.

        Two categories, both must be resolved: (1) hosts this daemon actually
        spawned or adopted, tracked in ``self._children``; (2) DB rows left
        ``RECOVERING`` by a deferred ``_defer_recovery`` retry that never
        reached ``spawn()`` and so never got a ``_children`` entry. Without
        phase 2, those rows outlive shutdown and reappear on the next
        ``start``. Session completion waits until every producer is proven stopped.
        """
        from app.services.sessions import apply_shutdown_result, replay_shutdown_result

        with self._recovery_timer_lock:
            recovery_timers = list(self._recovery_timers.values())
            self._recovery_timers.clear()
        for timer in recovery_timers:
            timer.cancel()
        dataflow_ids = list(self._children)
        stopped: list[str] = []
        failed: list[dict[str, str]] = []
        for dataflow_id in dataflow_ids:
            session = self._sessions.get_by_dataflow_id(dataflow_id)
            if session is None:
                failed.append(
                    {
                        "dataflow_id": dataflow_id,
                        "error": "session_not_found",
                    }
                )
                continue
            try:
                # Capture the producer before stop changes its state or removes
                # its child entry. The latest owner need not be this producer.
                owner = self._ownerships.get(self._children[dataflow_id].runtime_id)
                with transaction():
                    session.status = SessionStatus.STOPPING
                result = self.stop(session)
                apply_shutdown_result(session, result, owner, stop_reason="application_shutdown")
                if owner is not None and not ownership_teardown_confirmed(owner):
                    raise StopProofMissing(dataflow_id, runtime_id=owner.runtime_id if owner else None)
                stopped.append(dataflow_id)
            except Exception as exc:  # noqa: BLE001 - aggregate teardown failures
                failed.append(
                    {
                        "dataflow_id": dataflow_id,
                        "error": type(exc).__name__,
                    }
                )
                if not force:
                    break
        if failed and not force:
            raise RuntimeError(f"runtime host teardown failed: {failed[0]}")

        orphans = [
            row
            for row in self._ownerships.list_active()
            if row.dataflow_id not in self._children
        ]
        for ownership in orphans:
            session = self._sessions.get(ownership.session_id)
            if session is None:
                failed.append(
                    {
                        "dataflow_id": ownership.dataflow_id,
                        "error": "session_not_found",
                    }
                )
                continue
            try:
                with transaction():
                    session.status = SessionStatus.STOPPING
                if ownership.watchdog_id:
                    # Stop this exact owner; stop(session) could select a
                    # different unresolved generation of the same dataflow.
                    result = self._stop_starting_watchdog(session, ownership, None)
                else:
                    # Missing identity is not proof of teardown. Keep the row
                    # unresolved so reconciliation can retry it.
                    raise StopProofMissing(ownership.dataflow_id, runtime_id=ownership.runtime_id)
                apply_shutdown_result(session, result, ownership, stop_reason="application_shutdown")
                if not ownership_teardown_confirmed(ownership):
                    raise StopProofMissing(ownership.dataflow_id, runtime_id=ownership.runtime_id)
                stopped.append(ownership.dataflow_id)
            except Exception as exc:  # noqa: BLE001 - aggregate teardown failures
                failed.append(
                    {
                        "dataflow_id": ownership.dataflow_id,
                        "error": type(exc).__name__,
                    }
                )
                if not force:
                    break
        if failed and not force:
            raise RuntimeError(f"runtime host teardown failed: {failed[0]}")

        # A newer producer may finish before an older orphan. Reconsider its
        # durable proof only after every available producer has been attempted.
        for dataflow_id in dict.fromkeys(stopped):
            session = self._sessions.get_by_dataflow_id(dataflow_id)
            try:
                owners = self._ownerships.list_for_session(session.id)
                if owners and session.status != SessionStatus.COMPLETED:
                    replay_shutdown_result(session, owners[0])
                if session.status != SessionStatus.COMPLETED:
                    raise StopProofMissing(dataflow_id)
            except Exception as exc:
                stopped = [item for item in stopped if item != dataflow_id]
                failed.append({"dataflow_id": dataflow_id, "error": type(exc).__name__})
        if failed and not force:
            raise RuntimeError(f"runtime host teardown failed: {failed[0]}")

        return {
            "running_count": len(dataflow_ids) + len(orphans),
            "stopped_count": len(stopped),
            "failed_count": len(failed),
            "failures": failed,
            "forced": force,
        }

    def quiesce(self) -> dict[str, int]:
        """Stop control-plane background activity without touching runtime hosts."""
        self._quiesced = True
        self.stop_event_poller()
        with self._recovery_timer_lock:
            recovery_timers = list(self._recovery_timers.values())
            self._recovery_timers.clear()
        for timer in recovery_timers:
            timer.cancel()
        for timer in recovery_timers:
            if timer is not threading.current_thread() and timer.is_alive():
                timer.join(timeout=current_app.config["RUNTIME_HOST_PROCESS_WAIT_TIMEOUT_SECONDS"])
        return {"tracked_runtime_count": len(self._children)}

    def _schedule_session_finalization(
        self,
        session: Session,
        *,
        completion_cause: str,
        termination_reason: str = output_finalization.TERMINATION_CLEAN,
    ) -> list:
        """Complete + enqueue finalization for a terminalized session's outputs.

        Best-effort: a scheduling failure must never abort daemon shutdown or
        recovery abandonment or trap the hardware. ``termination_reason`` keeps
        clean shutdown evidence distinct from an unclean watchdog crash. The
        outputs stay completed and schedulable on a later finalizer/reconciler
        pass. Returns the per-output completion outcomes.
        """
        try:
            return output_finalization.complete_session_acquisitions(
                session.id,
                completion_cause=completion_cause,
                termination_reason=termination_reason,
            )
        except Exception as exc:  # noqa: BLE001 - must not abort teardown
            _log.warning(
                "shutdown: scheduling output finalization failed — outputs "
                "remain completed and retryable",
                session_id=session.id,
                dataflow_id=session.dataflow_id,
                error=type(exc).__name__,
                message=str(exc),
            )
            return []

    def _complete_shutdown_session(self, session: Session) -> None:
        """Close a session's lifecycle after its runtime host is torn down for good.

        ``stop()`` only tears down the *process* and clears the runtime columns;
        it is the low-level primitive shared by every stop path. Finishing the
        *session* — marking it COMPLETED and releasing its device-config claims
        — is an additional step required whenever a host is torn down without
        an operator-initiated stop of that specific session: daemon
        ``shutdown``, and ``_abandon_recovery`` giving up on a runtime that
        will never come back. Without this the session lingers ACTIVE with no
        runtime host, and its devices stay CLAIMED — so the next session that
        needs one of them fails with DeviceConfigNotFree.
        """
        with transaction():
            session.status = SessionStatus.COMPLETED
            session.command_in_flight = False
            session.runtime_port = None
            session.runtime_token = None
        from app.services.sessions import _release_session_device_configs
        _release_session_device_configs(session)

    def reconcile(
        self, sessions: list[Session], *, adopt_only: bool = False
    ) -> dict[str, list]:
        """Reattach to live hosts or spawn fresh on daemon boot.

        Called once at daemon startup.  For each session whose DB row still
        holds a ``runtime_port``, probe ``GET /status``.  If the host answers
        and its identity matches the session, adopt it in memory without
        spawning — the double-spawn guard.  If the probe fails or the identity
        does not match, spawn a fresh host.

        Dataflows already tracked in the in-memory registry are skipped.
        """
        from app.services.reconciliation import teardown_reconciliation_due
        report: dict[str, list] = {"adopted": [], "uncertain": []}
        self.replay_watchdog_outboxes()
        for session in sessions:
            if session.status == SessionStatus.COMPLETED:
                continue
            dataflow_id = session.dataflow_id
            ownership = self._ownerships.unresolved_for_dataflow(dataflow_id) if dataflow_id else None
            if ownership is not None and teardown_reconciliation_due(session, ownership):
                self.reconcile_teardown(session, ownership)
                if session.status != SessionStatus.COMPLETED:
                    report["uncertain"].append({"dataflow_id": dataflow_id,
                        "runtime_id": ownership.runtime_id, "reason": "teardown_unproven"})
                continue
            if not dataflow_id or dataflow_id in self._children:
                if dataflow_id:
                    _log.info(
                        "reconcile: skipped",
                        dataflow_id=dataflow_id,
                        reason="already_tracked_in_memory",
                    )
                continue

            port = session.runtime_port
            token = session.runtime_token
            # UNCERTAIN is not operational, but it is still authoritative
            # recovery evidence. Dropping it here bypasses the recovery
            # coordinator and turns a bounded restart into an unguarded spawn.
            ownership = self._ownerships.unresolved_for_dataflow(dataflow_id)

            if port is None:
                _log.info(
                    "reconcile: skipped",
                    dataflow_id=dataflow_id,
                    reason="session_has_no_runtime_port",
                    active_ownership=ownership.runtime_id if ownership else None,
                )
                continue

            if port is not None:
                try:
                    expected_manifest = self._manifest_for_reconcile(session, dataflow_id)
                    status = self._probe_status(port)
                    expected_hash = expected_manifest.hash

                    if adopt_only and ownership is None:
                        report["uncertain"].append(
                            {
                                "dataflow_id": dataflow_id,
                                "runtime_id": status.get("runtime_id"),
                                "reason": "restart_ownership_missing",
                            }
                        )
                        continue

                    live = (
                        status.get("dataflow_id") == dataflow_id
                        and status.get("manifest_hash") == expected_hash
                        and (
                            ownership is None
                            or status.get("runtime_id") == ownership.runtime_id
                        )
                    )
                    if live:
                        runtime_id = (
                            ownership.runtime_id
                            if ownership is not None
                            else str(status.get("runtime_id") or uuid4().hex)
                        )
                        if ownership is not None:
                            self._ownerships.mark_adopted(runtime_id, port=port)
                        self._children[dataflow_id] = _ChildEntry(
                            proc=None,
                            runtime_id=runtime_id,
                            port=port,
                            token=token,
                            manifest_path="",
                        )
                        self._ensure_event_poller_running()
                        _log.info(
                            "reconcile: adopted live runtime host",
                            dataflow_id=dataflow_id,
                            runtime_id=runtime_id,
                            port=port,
                        )
                        report["adopted"].append(dataflow_id)
                        continue
                    if ownership is not None:
                        self._ownerships.mark_uncertain(
                            ownership.runtime_id,
                            details={"status": status},
                        )
                        _log.warning(
                            "reconcile: no action — probe answered but identity mismatched",
                            dataflow_id=dataflow_id,
                            runtime_id=ownership.runtime_id,
                            port=port,
                            probed_runtime_id=status.get("runtime_id"),
                            probed_dataflow_id=status.get("dataflow_id"),
                        )
                        report["uncertain"].append(
                            {
                                "dataflow_id": dataflow_id,
                                "runtime_id": ownership.runtime_id,
                                "reason": "restart_identity_mismatch",
                            }
                        )
                    if adopt_only:
                        continue
                except Exception as exc:
                    if adopt_only:
                        runtime_id = ownership.runtime_id if ownership is not None else None
                        if ownership is not None:
                            self._ownerships.mark_uncertain(
                                ownership.runtime_id,
                                details={
                                    "reason": "restart_adoption_probe_failed",
                                    "error": type(exc).__name__,
                                },
                            )
                        report["uncertain"].append(
                            {
                                "dataflow_id": dataflow_id,
                                "runtime_id": runtime_id,
                                "reason": "restart_adoption_probe_failed",
                            }
                        )
                        continue
                    if ownership is not None:
                        self._recover_dead_runtime(
                            session,
                            ownership,
                            probe_error=exc,
                        )
                        continue
                    _log.info(
                        "reconcile: probe failed with no active ownership — "
                        "falling through to fresh spawn",
                        dataflow_id=dataflow_id,
                        port=port,
                        error=type(exc).__name__,
                    )

            try:
                replacement_manifest = self._manifest_for_reconcile(session, dataflow_id)
            except Exception as exc:
                if ownership is not None:
                    self._ownerships.mark_uncertain(
                        ownership.runtime_id,
                        details={
                            "reason": "manifest_resolution_failed",
                            "error": type(exc).__name__,
                        },
                    )
                _log.warning(
                    "reconcile: no action — manifest resolution failed",
                    dataflow_id=dataflow_id,
                    runtime_id=ownership.runtime_id if ownership else None,
                    error=type(exc).__name__,
                )
                if adopt_only:
                    report["uncertain"].append(
                        {
                            "dataflow_id": dataflow_id,
                            "runtime_id": ownership.runtime_id if ownership else None,
                            "reason": "restart_manifest_resolution_failed",
                        }
                    )
                continue
            if adopt_only:
                report["uncertain"].append(
                    {
                        "dataflow_id": dataflow_id,
                        "runtime_id": ownership.runtime_id if ownership else None,
                        "reason": "restart_adoption_not_proven",
                    }
                )
                continue
            try:
                self.spawn(session, manifest=replacement_manifest)
            except Exception as exc:  # noqa: BLE001 - keep the control plane available
                _log.error(
                    "reconcile: replacement start failed without recoverable ownership",
                    dataflow_id=dataflow_id,
                    error=type(exc).__name__,
                    message=str(exc),
                )
                report["uncertain"].append(
                    {
                        "dataflow_id": dataflow_id,
                        "runtime_id": None,
                        "reason": "replacement_start_failed",
                        "error": type(exc).__name__,
                    }
                )
        return report

    def poll_targets(self) -> list[DataflowTarget]:
        """Return the live dataflow host ports currently owned by this supervisor."""
        self.replay_watchdog_outboxes()
        return [
            DataflowTarget(dataflow_id=dataflow_id, port=entry.port)
            for dataflow_id, entry in self._children.items()
        ]

    def runtime_log_path(self, dataflow_id: str) -> str:
        """Path to the runtime host child's stderr/stdout log for this dataflow.

        Empty string for a dataflow adopted via ``reconcile()`` (no temp file
        was created for it in this process). Diagnostic-only: read it to see
        what a runtime host actually raised, e.g. after a start command that
        never produced a report.
        """
        return self._get_child(dataflow_id).log_path

    @property
    def event_poller(self) -> EventPoller:
        """The supervisor-owned event poller."""
        return self._event_poller

    def start_event_poller(
        self,
        *,
        interval_seconds: float | None = None,
        delayed_after_seconds: float | None = None,
        unreachable_after_seconds: float | None = None,
    ) -> None:
        """Start the background poll loop for this supervisor's live hosts."""
        config = current_app.config
        if interval_seconds is None:
            interval_seconds = config["CONTROL_PLANE_POLL_INTERVAL_SECONDS"]
        if delayed_after_seconds is None:
            delayed_after_seconds = config["CONTROL_PLANE_DELAYED_AFTER_SECONDS"]
        if unreachable_after_seconds is None:
            unreachable_after_seconds = config["CONTROL_PLANE_UNREACHABLE_AFTER_SECONDS"]
        if (
            self._event_poller.interval_seconds != interval_seconds
            or self._event_poller.delayed_after_seconds != delayed_after_seconds
            or self._event_poller.unreachable_after_seconds != unreachable_after_seconds
            or self._event_poller.telemetry_stale_after_seconds
            != config["WATCHDOG_TELEMETRY_STALE_AFTER_SECONDS"]
            or self._event_poller.telemetry_overflow_after_seconds
            != config["WATCHDOG_TELEMETRY_OVERFLOW_AFTER_SECONDS"]
            or self._event_poller.watchdog_stale_after_seconds
            != config["WATCHDOG_STALE_AFTER_SECONDS"]
        ):
            if self._event_poller.is_running:
                raise RuntimeError("cannot reconfigure a running event poller")
            self._event_poller = EventPoller(
                targets=self.poll_targets,
                probe_status=self._probe_and_reconcile_watchdog,
                interval_seconds=interval_seconds,
                delayed_after_seconds=delayed_after_seconds,
                unreachable_after_seconds=unreachable_after_seconds,
                telemetry_stale_after_seconds=config[
                    "WATCHDOG_TELEMETRY_STALE_AFTER_SECONDS"
                ],
                telemetry_overflow_after_seconds=config[
                    "WATCHDOG_TELEMETRY_OVERFLOW_AFTER_SECONDS"
                ],
                watchdog_stale_after_seconds=config[
                    "WATCHDOG_STALE_AFTER_SECONDS"
                ],
            )
        self._event_poller.start(app=current_app._get_current_object())

    def stop_event_poller(self) -> None:
        """Stop the background poll loop."""
        self._event_poller.stop()

    def _ensure_event_poller_running(self) -> None:
        if current_app.testing or self._quiesced:
            return
        if (
            current_app.debug
            and os.environ.get("FLASK_RUN_FROM_CLI") == "true"
            and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
        ):
            return
        self.start_event_poller()

    @staticmethod
    def _probe_status(port: int) -> dict:
        """Probe ``GET /status`` on a loopback port; return the parsed JSON.

        Raises any network or HTTP exception on failure so callers can treat
        any exception as "not live". Does not contain reconcilation because it's handled
        by other function.
        """
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/status",
            method="GET",
        )
        with urllib.request.urlopen(
            req,
            timeout=current_app.config["RUNTIME_HOST_STATUS_PROBE_TIMEOUT_SECONDS"],
        ) as resp:
            return json.loads(resp.read())

    def _probe_and_reconcile_watchdog(self, port: int) -> dict:
        """``EventPoller``'s probe callback: probe, then reconcile watchdog state.
        """
        status = self._probe_status(port)
        try:
            self._reconcile_watchdog_status(status)
        except Exception as exc:
            _log.warning(
                "poll: reconciling watchdog state into DB failed",
                runtime_id=status.get("runtime_id"),
                watchdog_id=status.get("watchdog_id"),
                watchdog_state=status.get("watchdog_state"),
                error=type(exc).__name__,
                message=str(exc),
            )
        return status

    def _reconcile_watchdog_status(self, status: dict) -> None:
        """Mirror one runtime_host's watchdog-supervision state into the DB.

        Handles, in order:
          1. A new ``watchdog_id`` (respawned by runtime_host after a crash)
             and register new identity to DB with set_watchdog()
          2. The crashed identity has no replacement (``watchdog_id`` is now
             None): record the crash, and if the respawn budget is
             exhausted, escalate the whole runtime ownership row to
             UNCERTAIN.
          3. Same identity, new lifecycle state (running/stopped/etc.): sync as normal
        """
        runtime_id = status.get("runtime_id")
        if not runtime_id:
            return
        ownership = self._ownerships.get(runtime_id)
        if ownership is None:
            return

        self._ownerships.retain_predecessors(runtime_id, status.get("predecessor_watchdogs") or [])

        reported_id = status.get("watchdog_id")
        reported_state_raw = status.get("watchdog_state")
        exit_details = status.get("watchdog_exit_details")
        respawn_exhausted = bool(status.get("watchdog_respawn_exhausted"))
        active_id = ownership.watchdog_id

        if ownership.state == RuntimeOwnershipState.STOPPED:
            return
        if reported_id != active_id and any(
            item.get("watchdog_id") == reported_id
            for item in (ownership.details or {}).get("predecessor_watchdogs", [])
        ):
            return  # stale status cannot reclaim a retired producer identity

        if reported_id is not None and reported_id != active_id:
            self._ownerships.set_watchdog(
                runtime_id,
                watchdog_id=reported_id,
                token_hash=status.get("watchdog_token_hash"),
                pid=status.get("watchdog_pid"),
                control_port=status.get("watchdog_control_port"),
                outbox_path=status.get("watchdog_outbox_path"),
            )
            return

        if reported_id is None and active_id is not None and reported_state_raw == "crashed":
            self._ownerships.mark_watchdog_crashed(
                runtime_id, watchdog_id=active_id, details=exit_details
            )
            if respawn_exhausted:
                self._ownerships.mark_uncertain(
                    runtime_id,
                    details={
                        "reason": "watchdog_respawn_exhausted",
                        "watchdog_exit_details": exit_details,
                    },
                )
            return

        if reported_id is not None and reported_id == active_id and reported_state_raw:
            self._sync_watchdog_state(ownership, reported_state_raw, status)

    def _sync_watchdog_state(
        self, ownership: RuntimeOwnership, reported_state_raw: str, status: dict
    ) -> None:
        try:
            state = WatchdogProcessState(reported_state_raw)
        except ValueError:
            return
        runtime_id = ownership.runtime_id
        watchdog_id = ownership.watchdog_id
        if state is WatchdogProcessState.CRASHED:
            self._ownerships.mark_watchdog_crashed(
                runtime_id,
                watchdog_id=watchdog_id,
                details=status.get("watchdog_exit_details"),
            )
        elif state is WatchdogProcessState.STOPPED:
            self._ownerships.mark_watchdog_stopped(
                runtime_id,
                watchdog_id=watchdog_id,
                details=status.get("watchdog_exit_details"),
            )
        elif state in (WatchdogProcessState.RUNNING, WatchdogProcessState.ADOPTED):
            if ownership.watchdog_state in (WatchdogProcessState.STOPPED, WatchdogProcessState.STOPPING):
                return
            self._ownerships.update_watchdog_seen(
                runtime_id,
                watchdog_id=watchdog_id,
                pid=status.get("watchdog_pid"),
                control_port=status.get("watchdog_control_port"),
                state=state,
            )
        # STARTING/STOPPING/UNCERTAIN: transient or already-terminal from the
        # control plane's own escalation ladder (packet 07) — nothing for
        # this per-cycle sync to do.

    def _recovery_manager(self) -> WatchdogRecoveryCoordinator:
        if self._recovery_coordinator is None:
            self._recovery_coordinator = WatchdogRecoveryCoordinator(
                hardware_lock_dir=current_app.config.get(
                    "WATCHDOG_HARDWARE_LOCK_DIR", "watchdog-hardware-locks"
                )
            )
        return self._recovery_coordinator

    def _recover_dead_runtime(
        self,
        session: Session,
        ownership: RuntimeOwnership,
        *,
        probe_error: Exception,
    ) -> None:
        try:
            manifest = self._manifest_for_reconcile(session, ownership.dataflow_id)
        except Exception as exc:
            self._defer_recovery(
                session,
                ownership,
                reason="replacement_manifest_failed",
                evidence={
                    "probe_error": type(probe_error).__name__,
                    "manifest_error": type(exc).__name__,
                },
            )
            return

        coordinator = self._recovery_manager()
        assessment = coordinator.assess(ownership, manifest)
        if assessment.action is RecoveryAction.START_FRESH:
            try:
                self._replacement_recording_state(session, manifest)
            except Exception as exc:
                self._ownerships.mark_uncertain(ownership.runtime_id, details={
                    "reason": "replacement_timing_or_stop_fence", "error": str(exc),
                })
                self._cancel_recovery_retry(ownership.dataflow_id)
                return
        if assessment.action is RecoveryAction.RETRY:
            self._defer_recovery(
                session,
                ownership,
                reason=assessment.reason,
                evidence=assessment.evidence,
            )
            return

        verified_pid = assessment.evidence.get("verified_pid")
        if (
            assessment.action is RecoveryAction.ADOPT
            and isinstance(verified_pid, int)
            and not isinstance(verified_pid, bool)
            and verified_pid != ownership.watchdog_pid
        ):
            self._ownerships.update_watchdog_seen(
                ownership.runtime_id,
                watchdog_id=ownership.watchdog_id,
                pid=verified_pid,
                control_port=ownership.watchdog_control_port,
                state=WatchdogProcessState.RUNNING,
            )
            ownership = self._ownerships.get(ownership.runtime_id) or ownership

        attempt = self._recovery_attempt(ownership)
        self._ownerships.mark_recovering(
            ownership.runtime_id,
            phase="adopting" if assessment.action is RecoveryAction.ADOPT else "starting_fresh",
            reason=assessment.reason,
            attempt=attempt,
            next_retry_at=None,
            evidence=assessment.evidence,
        )

        if assessment.action is RecoveryAction.START_FRESH:
            try:
                self.spawn(session, manifest=manifest)
            except Exception as exc:
                self._defer_recovery(
                    session,
                    ownership,
                    reason="fresh_watchdog_start_failed",
                    evidence={**assessment.evidence, "error": type(exc).__name__},
                    attempt=attempt,
                )
                return
            self._ownerships.mark_stopped(ownership.runtime_id)
            return

        try:
            self.spawn(
                session,
                manifest=manifest,
                adopt_watchdog_id=ownership.watchdog_id,
                adopt_watchdog_pid=ownership.watchdog_pid,
                adopt_watchdog_control_port=ownership.watchdog_control_port,
                recovery_token=ownership.token,
            )
        except Exception as adoption_exc:
            recovery_id = uuid4().hex
            self._ownerships.mark_recovering(
                ownership.runtime_id,
                phase="stopping_orphan",
                reason="watchdog_adoption_failed",
                attempt=attempt,
                next_retry_at=None,
                evidence={
                    **assessment.evidence,
                    "adoption_error": type(adoption_exc).__name__,
                },
            )
            stopped = coordinator.stop_exact_watchdog(
                ownership,
                manifest,
                recovery_id=recovery_id,
            )
            if not stopped:
                self._defer_recovery(
                    session,
                    ownership,
                    reason="watchdog_stop_or_hardware_release_unverified",
                    evidence=assessment.evidence,
                    attempt=attempt,
                )
                return
            try:
                self.spawn(session, manifest=manifest)
            except Exception as fresh_exc:
                self._defer_recovery(
                    session,
                    ownership,
                    reason="post_stop_fresh_start_failed",
                    evidence={
                        **assessment.evidence,
                        "error": type(fresh_exc).__name__,
                    },
                    attempt=attempt,
                )
                return
        self._ownerships.mark_stopped(ownership.runtime_id)

    @staticmethod
    def _recovery_attempt(ownership: RuntimeOwnership) -> int:
        recovery = (ownership.details or {}).get("recovery") or {}
        try:
            return max(1, int(recovery.get("attempt", 0)) + 1)
        except (TypeError, ValueError):
            return 1

    def _defer_recovery(
        self,
        session: Session,
        ownership: RuntimeOwnership,
        *,
        reason: str,
        evidence: dict[str, object],
        attempt: int | None = None,
    ) -> None:
        attempt = self._recovery_attempt(ownership) if attempt is None else attempt
        max_attempts = current_app.config["WATCHDOG_RECOVERY_MAX_ATTEMPTS"]
        if max_attempts and attempt > max_attempts:
            self._abandon_recovery(
                session, ownership, reason=reason, evidence=evidence, attempt=attempt
            )
            return
        delays = current_app.config["WATCHDOG_RECOVERY_RETRY_DELAYS_SECONDS"]
        if not delays:
            raise RuntimeError("WATCHDOG_RECOVERY_RETRY_DELAYS_SECONDS cannot be empty")
        delay = delays[min(attempt - 1, len(delays) - 1)]
        next_retry = datetime.now(UTC) + timedelta(seconds=delay)
        self._ownerships.mark_recovering(
            ownership.runtime_id,
            phase="retry_wait",
            reason=reason,
            attempt=attempt,
            next_retry_at=next_retry.isoformat(),
            evidence=evidence,
        )
        _log.warning(
            "runtime recovery deferred; hardware remains blocked",
            dataflow_id=ownership.dataflow_id,
            runtime_id=ownership.runtime_id,
            reason=reason,
            attempt=attempt,
            retry_in_seconds=delay,
        )
        self._schedule_recovery_retry(
            session_id=session.id,
            dataflow_id=ownership.dataflow_id,
            delay_seconds=delay,
        )

    def _abandon_recovery(
        self,
        session: Session,
        ownership: RuntimeOwnership,
        *,
        reason: str,
        evidence: dict[str, object],
        attempt: int,
    ) -> None:
        """Give up on a runtime that has exhausted its recovery retry budget.

        Reached only when every retry produced RETRY again — evidence that
        never resolved to START_FRESH/ADOPT (e.g. a watchdog control port
        that keeps failing to answer). Retrying forever at the last backoff
        interval is a wedge, not progress: this closes the row out instead,
        so it drops out of ``runtime list`` and a subsequent ``shutdown``
        doesn't have to rediscover it as an orphan.
        """
        self._cancel_recovery_retry(ownership.dataflow_id)
        if ownership.watchdog_id:
            # Exhausted retries are not proof that a possibly live process has
            # stopped or that its sinks drained. Preserve identity and claims.
            self._ownerships.mark_uncertain(ownership.runtime_id, details={
                "reason": f"{reason}_retries_exhausted", "attempt": attempt,
                "evidence": evidence,
            })
            with transaction():
                session.status = SessionStatus.STOPPING
                session.command_in_flight = False
            return
        self._ownerships.mark_recovering(
            ownership.runtime_id,
            phase="abandoned",
            reason=f"{reason}_retries_exhausted",
            attempt=attempt,
            next_retry_at=None,
            evidence=evidence,
        )
        self._ownerships.mark_stopped(ownership.runtime_id)
        self._complete_shutdown_session(session)
        self._schedule_session_finalization(
            session,
            completion_cause=output_finalization.COMPLETION_RECONCILIATION,
            termination_reason="watchdog_crash",
        )
        _log.error(
            "runtime recovery abandoned after exhausting retry budget — marked stopped",
            dataflow_id=ownership.dataflow_id,
            runtime_id=ownership.runtime_id,
            reason=reason,
            attempts=attempt,
        )

    def _schedule_recovery_retry(
        self, *, session_id: int, dataflow_id: str, delay_seconds: float
    ) -> None:
        if current_app.testing or self._quiesced:
            return
        app = current_app._get_current_object()
        with self._recovery_timer_lock:
            if self._quiesced:
                return
            existing = self._recovery_timers.get(dataflow_id)
            if existing is not None and existing.is_alive():
                return

            def _retry() -> None:
                # Remove the firing timer before reconcile so another
                # ambiguous result can schedule the next backoff interval.
                with self._recovery_timer_lock:
                    self._recovery_timers.pop(dataflow_id, None)
                if self._quiesced:
                    return
                with app.app_context():
                    session = self._sessions.get(session_id)
                    if session is not None:
                        self.reconcile([session])

            timer = threading.Timer(delay_seconds, _retry)
            timer.daemon = True
            self._recovery_timers[dataflow_id] = timer
            timer.start()

    def _cancel_recovery_retry(self, dataflow_id: str) -> None:
        with self._recovery_timer_lock:
            timer = self._recovery_timers.pop(dataflow_id, None)
        if timer is not None:
            timer.cancel()

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _build_manifest(session: Session) -> Manifest:
        """Build a Manifest from the session's device_flows JSON.

        Expects each entry in the new DeviceFlow wire format (packet 3.4+).
        The resolver (packet 3.5) is responsible for populating this format
        on the session before the supervisor is called.
        """
        raw_flows = session.device_flows or []
        return Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id=session.dataflow_id,
            policy=session.policy,
            device_flows=tuple(DeviceFlow.from_dict(df) for df in raw_flows),
        )

    def _manifest_for_reconcile(self, session: Session, dataflow_id: str) -> Manifest:
        """Resolve current session-config flows, with legacy manifest-shape fallback.

        validate_sink_locations=False: reconcile() runs against sessions that
        already believe they're active — either adopting a still-live host
        (whose output files already exist, by design) or building a
        replacement to respawn a dead one for the same dataflow_id. Neither
        case is a fresh, operator-initiated start; treating the session's own
        already-claimed path as a collision would block daemon startup.
        """
        try:
            return manifests.resolve(
                session.id, dataflow_id=dataflow_id, validate_sink_locations=False
            )
        except Exception as exc:
            _log.info(
                "reconcile: manifest resolver failed — "
                "falling back to legacy session device_flows",
                dataflow_id=dataflow_id,
                session_id=session.id,
                error=type(exc).__name__,
                message=str(exc),
            )
            return self._build_manifest(session)


def ensure_runtime_driver_ready(driver: str, manifest: Manifest | None = None) -> None:
    """Validate the configured runtime driver before spawning a host.

    When ``manifest`` is supplied (the ``spawn`` path), additionally verify the
    dependency requirements of ONLY the sink types that manifest selects
    (gap SINK-13) — not all six. ``manifest`` is ``None`` for the
    environment-level ``pinnacle doctor`` probe, which reports general driver
    readiness without a specific session's sink selection and must not fail on
    an unselected/unavailable optional sink.
    """
    if driver == "morelia":
        _ensure_morelia_ready(manifest)
        return
    raise ValueError("RUNTIME_DRIVER must be 'morelia'")


def _ensure_morelia_ready(manifest: Manifest | None = None) -> None:
    """Validate the morelia driver can actually be assembled before spawning.

    MORELIA_SRC (set directly or via .env) is the conventional way to point at
    an unpacked Morelia checkout, but it's not the only way Morelia can end up
    importable — it may already be pip-installed, or already on sys.path some
    other way. So MORELIA_SRC being unset is not itself a failure: the real
    test is whether `_import_morelia()` succeeds. If MORELIA_SRC *is* set, we
    still fail fast on an obviously-wrong path before attempting the import.

    When ``manifest`` is provided, the base-driver import check is followed by a
    selection-aware sink dependency preflight (gap SINK-13): rather than
    claiming all sink types are available merely because the base driver
    imported, only the sink types the session selects are dependency-checked. A
    missing optional/native dependency raises the sink-addressed, redacted
    ``SinkDependencyMissing`` here — before any child process is spawned or any
    hardware lease is taken — while an unselected optional sink can never block
    a CSV-only start.
    """
    morelia_src = os.environ.get("MORELIA_SRC")
    if morelia_src:
        source_path = Path(morelia_src)
        if not source_path.is_dir():
            raise RuntimeError(f"MORELIA_SRC does not point to a directory: {source_path}")

    try:
        from app.runtime_child.morelia import _import_morelia

        _import_morelia()
    except Exception as exc:  # noqa: BLE001 - preserve import failure as readiness detail
        hint = (
            f"MORELIA_SRC={morelia_src!r}"
            if morelia_src
            else "MORELIA_SRC is unset and Morelia is not importable from the "
            "active environment — set MORELIA_SRC (see .env.example) or pip "
            "install Morelia"
        )
        raise RuntimeError(f"Morelia import failed ({hint}): {exc}") from exc

    if manifest is not None:
        # Selection-aware: probe dependencies for only the sink types this
        # session selects; the typed SinkDependencyMissing it raises names the
        # exact sink + pip extra and is safe to surface (no secret/path leaks).
        from app.runtime_child.morelia import preflight_sink_dependencies

        preflight_sink_dependencies(manifest)
