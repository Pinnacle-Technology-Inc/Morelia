"""Loopback HTTP server — thin transport in front of LifecycleSafetyGate.

The ``DataflowRuntimeHost`` binds ``127.0.0.1`` on a free port and serves the
watchdog command contract (``docs/watchdog-http-v1.md``). It does NO business
logic — every command is handed to the gate, and every gate exception is mapped
to exactly one HTTP status code:

    CommandInFlight → 423  (another command is already running)
    ValueError      → 400  (malformed envelope, bad recovery target, etc.)
    RuntimeError    → 409  (driver refused the phase transition)

The ``GET /status`` endpoint surfaces the driver's current phase, the manifest
hash, and a bounded ring of recent reports so the control plane can inspect
host state without sending a command.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import urllib.request
from collections import deque
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic

import structlog

from app.config import get_config
from app.runtime_child.driver import RuntimeControlDriver, RuntimeReport
from app.runtime_host.lifecycle import CommandInFlight, LifecycleSafetyGate
from app.runtime_host.manifest import Manifest
from app.watchdog.messages import WATCHDOG_COMMAND_PATH, CommandEnvelope
from app.watchdog_process.telemetry_client import DIRECT_INGEST_PATH

_log = structlog.get_logger(__name__)

MAX_REQUEST_BYTES = 65_536
MAX_REPORT_RING = 64

# (entry_dict) -> True on 202, False on any error.
PushFn = Callable[[dict], bool]
NowFn = Callable[[], float]


class _LoopbackRuntimeHTTPServer(ThreadingHTTPServer):
    """Keep expected loopback disconnects out of the runtime failure signal."""

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            _log.debug(
                "loopback runtime client disconnected",
                component="runtime_host_http",
                error_type=type(error).__name__,
            )
            return
        super().handle_error(request, client_address)


class RuntimeHostLease:
    """Daemon liveness lease renewed by control-plane contact."""

    def __init__(self, *, timeout_seconds: float, now: NowFn = monotonic) -> None:
        if timeout_seconds <= 0:
            raise ValueError("lease timeout must be greater than zero")
        self._timeout_seconds = timeout_seconds
        self._now = now
        self._deadline = now() + timeout_seconds
        self._lock = threading.Lock()

    def renew(self) -> None:
        with self._lock:
            self._deadline = self._now() + self._timeout_seconds

    def expired(self) -> bool:
        with self._lock:
            return self._now() > self._deadline


class _RequestHandler(BaseHTTPRequestHandler):
    """Route requests to the owning DataflowRuntimeHost.

    Attributes are set on the *class* by ``DataflowRuntimeHost._make_handler``
    so every request instance can reach the gate and report ring without globals.
    """

    gate: LifecycleSafetyGate
    manifest: Manifest
    driver: RuntimeControlDriver
    report_ring: deque[dict]
    lease: RuntimeHostLease | None
    token: str | None
    runtime_id: str
    # Run the deferred driver work off the request thread so the command ACK
    # returns before — potentially slow — preflight/start finishes.
    execute: Callable[[CommandEnvelope, Callable[[], None]], None]
    # Live getter for the last asynchronous command failure (surfaced in /status).
    last_command_error: Callable[[], dict | None]

    # Silence per-request stderr logging from BaseHTTPRequestHandler.
    def log_message(self, format, *args):  # noqa: A002
        pass

    # -- routing --------------------------------------------------------------

    def do_POST(self):
        if self.path != WATCHDOG_COMMAND_PATH:
            self._send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return

        if not self._check_loopback():
            return
        if not self._check_token():
            return

        body = self._read_bounded_body()
        if body is None:
            return

        try:
            raw = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
            return

        if not isinstance(raw, dict):
            self._send_error(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
            return

        # accept() does all synchronous validation and takes the scope lock, so
        # malformed envelopes (400) and conflicts (423) still fail before the
        # ACK. The driver work itself runs on a background thread: preflight/
        # start can take many seconds against real hardware, and the control
        # plane's command client deadline is far shorter than that. A driver
        # error therefore happens *after* the 202 and is surfaced via /status +
        # the host log rather than as an HTTP status (see DataflowRuntimeHost).
        try:
            envelope, run = self.gate.accept(raw)
        except CommandInFlight as exc:
            self._send_error(HTTPStatus.LOCKED, str(exc))
            return
        except ValueError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        self.execute(envelope, run)
        self._send_json(HTTPStatus.ACCEPTED, self.gate.acknowledgement(envelope).to_dict())

    def do_GET(self):
        if self.path != "/status":
            self._send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return

        if not self._check_loopback():
            return
        if self.lease is not None:
            self.lease.renew()

        # a WatchdogProcessDriver checks its child's liveness here
        poll_health = getattr(self.driver, "poll_health", None)
        if poll_health is not None:
            poll_health()

        watchdog_state = getattr(self.driver, "watchdog_state", None)
        payload = {
            "runtime_id": self.runtime_id,
            "pid": os.getpid(),
            "phase": self.driver.phase.value,
            "dataflow_id": self.manifest.dataflow_id,
            "manifest_hash": self.manifest.hash,
            # These are only meaningful for a WatchdogProcessDriver (packet
            # 06/08); getattr defaults keep this endpoint shape-compatible
            # with any driver that doesn't supervise a watchdog process.
            "watchdog_id": getattr(self.driver, "watchdog_id", None),
            "watchdog_pid": getattr(self.driver, "watchdog_pid", None),
            "watchdog_token_hash": getattr(self.driver, "watchdog_token_hash", None),
            "watchdog_control_port": getattr(self.driver, "watchdog_control_port", None),
            "watchdog_state": watchdog_state.value if watchdog_state is not None else None,
            "watchdog_preflight_ready": bool(
                getattr(self.driver, "watchdog_preflight_ready", False)
            ),
            "watchdog_respawn_count": getattr(self.driver, "respawn_count", 0),
            "watchdog_respawn_exhausted": getattr(self.driver, "respawn_exhausted", False),
            "watchdog_exit_details": getattr(self.driver, "watchdog_exit_details", None),
            "reports": list(self.report_ring),
        }
        last_error = self.last_command_error()
        if last_error is not None:
            payload["last_command_error"] = last_error
        self._send_json(HTTPStatus.OK, payload)

    # -- guards ---------------------------------------------------------------

    def _check_loopback(self) -> bool:
        client_ip = self.client_address[0]
        if client_ip not in ("127.0.0.1", "::1"):
            self._send_error(HTTPStatus.FORBIDDEN, "loopback only")
            return False
        return True

    def _check_token(self) -> bool:
        if self.token is None:
            return True
        header = self.headers.get("X-Agent-Token")
        if header != self.token:
            self._send_error(HTTPStatus.UNAUTHORIZED, "invalid or missing token")
            return False
        return True

    def _read_bounded_body(self) -> bytes | None:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._send_error(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            return None
        try:
            length = int(length_header)
        except ValueError:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        if length > MAX_REQUEST_BYTES:
            self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
            return None
        if length < 0:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        return self.rfile.read(length)

    # -- response helpers -----------------------------------------------------

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message})


class DataflowRuntimeHost:
    """Loopback-only HTTP server fronting one LifecycleSafetyGate.

    Bind port 0 to let the OS pick a free port; read it back via ``.port``
    after ``start()``. The host buffers the last N reports in a ring so
    ``GET /status`` can surface recent history to the control plane.
    """

    def __init__(
        self,
        *,
        gate: LifecycleSafetyGate,
        manifest: Manifest,
        driver: RuntimeControlDriver,
        port: int = 0,
        token: str | None = None,
        runtime_id: str = "in-process",
        ingest_url: str | None = None,
        ingest_token: str | None = None,
        _push_fn: PushFn | None = None,
        lease: RuntimeHostLease | None = None,
    ) -> None:
        self._gate = gate
        self._manifest = manifest
        self._driver = driver
        self._token = token
        self._runtime_id = runtime_id
        self._report_ring: deque[dict] = deque(maxlen=MAX_REPORT_RING)

        self._ingest_url = ingest_url or None
        self._ingest_token = ingest_token or None
        self._lease = lease
        # _push_fn is a testing seam; production uses the stdlib urllib path.
        self._push: PushFn = _push_fn if _push_fn is not None else self._http_push
        self._acked: set[int] = set()
        self._push_lock = threading.Lock()

        # Last failure from an asynchronously-executed command, surfaced in
        # /status. None until a command fails; cleared when a later command
        # succeeds so the field reflects only currently-true failures.
        self._last_command_error: dict | None = None
        self._error_lock = threading.Lock()

        # Most-recent command worker thread, so callers can wait for an
        # in-flight command's driver work to drain (see wait_for_idle).
        self._command_thread: threading.Thread | None = None
        self._command_thread_lock = threading.Lock()

        handler_cls = self._make_handler()
        self._server = _LoopbackRuntimeHTTPServer(("127.0.0.1", port), handler_cls)
        self._thread: threading.Thread | None = None

    def _make_handler(self) -> type[_RequestHandler]:
        """Build a handler subclass with references to our instance state."""

        class Handler(_RequestHandler):
            gate = self._gate
            manifest = self._manifest
            driver = self._driver
            report_ring = self._report_ring
            lease = self._lease
            token = self._token
            runtime_id = self._runtime_id
            execute = self._execute_command
            last_command_error = self._get_last_command_error

        return Handler

    # -- asynchronous command execution ---------------------------------------

    def _execute_command(
        self, envelope: CommandEnvelope, run: Callable[[], None]
    ) -> None:
        """Run one accepted command's driver work on a daemon thread.

        The scope lock is held by ``run`` for the whole call (it releases in a
        finally), so a concurrent command on the same conflict domain is
        rejected with 423 until this finishes — exactly as it was synchronously.
        A failure is recorded, not re-raised: nobody is waiting on the response
        anymore, so the only honest place for it is /status and the host log.
        """

        def _worker() -> None:
            try:
                run()
            except Exception as exc:  # noqa: BLE001 - surfaced via /status + log
                self._record_command_error(envelope, exc)
            else:
                self._clear_command_error()

        thread = threading.Thread(
            target=_worker,
            name=f"runtime-command-{envelope.command}",
            daemon=True,
        )
        with self._command_thread_lock:
            self._command_thread = thread
        thread.start()

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        """Block until the most-recent command's driver work finishes.

        Returns True if no command is in flight or it drained within
        ``timeout``. Deterministic seam for callers (and tests) that need the
        asynchronous driver work applied before they act — without it, a
        follow-up command can race the scope lock and be rejected 423.
        """
        with self._command_thread_lock:
            thread = self._command_thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def _record_command_error(self, envelope: CommandEnvelope, exc: Exception) -> None:
        entry = {
            "command": envelope.command,
            "command_id": envelope.correlation.command_id,
            "error": type(exc).__name__,
            "message": str(exc),
        }
        with self._error_lock:
            self._last_command_error = entry
        # Called from within the worker's except block, so format_exc() still
        # reflects this exception. Lands in the child stderr log the supervisor
        # points operators at (HostSupervisor.runtime_log_path).
        _log.error("runtime command failed", **entry, traceback=traceback.format_exc())

    def _clear_command_error(self) -> None:
        with self._error_lock:
            self._last_command_error = None

    def _get_last_command_error(self) -> dict | None:
        with self._error_lock:
            if self._last_command_error is None:
                return None
            return dict(self._last_command_error)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def report_ring(self) -> deque[dict]:
        return self._report_ring

    @property
    def lease(self) -> RuntimeHostLease | None:
        return self._lease

    def collect_report(self, report: RuntimeReport) -> None:
        """Append a report to the ring buffer and attempt northbound push.

        Always writes to the ring (so GET /status and the poll backstop stay
        current). If an ingest URL is configured, also tries to flush all
        unacked ring entries to the control plane.
        """
        self._report_ring.append(report.to_dict())
        if self._ingest_url:
            self._flush_ring()

    def _flush_ring(self) -> None:
        """Push all unacked ring entries to the plane in sequence order.

        Stops at the first failure so ordering is preserved. Prunes _acked of
        sequences that have since been evicted from the bounded ring.
        """
        if not self._push_lock.acquire(blocking=False):
            return  # another flush is already in progress
        try:
            ring_seqs = {e.get("sequence") for e in self._report_ring}
            self._acked &= ring_seqs  # drop acks for evicted entries
            for entry in list(self._report_ring):
                seq = entry.get("sequence")
                if seq in self._acked:
                    continue
                if self._push(entry):
                    self._acked.add(seq)
                else:
                    break  # plane unreachable; retry on next collect_report
        finally:
            self._push_lock.release()

    def _http_push(self, entry: dict) -> bool:
        """POST one ring entry to the plane's ingest endpoint via urllib. Returns True on 202.

        ``self._ingest_url`` is the plane's BASE url (the same value forwarded
        verbatim to the watchdog process's ``--ingest-url``); the events path
        is appended here, mirroring ``TelemetryClient``.
        """
        body = json.dumps(
            {"protocol_version": "1", "report": entry}, separators=(",", ":")
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if self._ingest_token:
            headers["X-Agent-Token"] = self._ingest_token
        try:
            req = urllib.request.Request(
                self._ingest_url.rstrip("/") + DIRECT_INGEST_PATH,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(
                req,
                timeout=get_config().RUNTIME_HOST_SERVER_PUSH_TIMEOUT_SECONDS,
            ) as resp:
                return resp.status == 202
        except Exception as exc:
            _log.warning(
                "direct ingest push failed — report stays in ring",
                report_id=entry.get("report_id") if isinstance(entry, dict) else None,
                error=type(exc).__name__,
                message=str(exc),
            )
            return False

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(
                timeout=get_config().RUNTIME_HOST_SERVER_STOP_TIMEOUT_SECONDS
            )
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
