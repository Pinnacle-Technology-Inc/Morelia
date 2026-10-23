"""Watchdog process orchestration: manifest -> driver -> outbox -> direct ingest.

Wires one ``MoreliaRuntime`` instance for one dataflow. Every
``RuntimeReport`` the driver emits is enqueued to the local SQLite outbox
*before* any delivery attempt (packet 04's durability boundary — see
``app.watchdog_process.outbox``), then flushed directly to the control
plane. A fatal ingest response (409 stale, 401 unauthorized — see
``app.watchdog_process.telemetry_client.DeliveryOutcome``) means the control
plane no longer accepts this ``watchdog_id`` as active, so this process
stops itself rather than keep reporting.

One deliberate exception: a 409 BEFORE this watchdog has ever been accepted
is treated as the identity-registration race, not as fencing. The first
report leaves the driver the instant ``start()`` completes, but the control
plane only learns the new ``watchdog_id`` when the supervisor's poller next
reads the host's ``/status`` (~1-2s later) — so report ``:0`` reliably
arrives fenced. Such a 409 leaves the report pending for the next flush,
up to ``STALE_GRACE_ATTEMPTS`` consecutive rejections; only a 409 after at
least one acceptance (a real supersession) is immediately fatal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
import math
import sys
import threading
from threading import Event
import time
import uuid
from time import monotonic
from typing import TYPE_CHECKING

import structlog

from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
from app.domain.duration import validate_duration_seconds
from app.runtime_child.driver import RuntimePhase, RuntimeReport
from app.runtime_host.manifest import Manifest
from app.watchdog_process.outbox import WatchdogOutbox
from app.watchdog_process.telemetry_client import DeliveryOutcome, DeliveryResult, TelemetryClient

if TYPE_CHECKING:
    from app.runtime_child.morelia import MoreliaRuntime

_log = structlog.get_logger(__name__)

# Phases from which MoreliaRuntime.stop() accepts being called; mirrors
# runtime_host/__main__.py's _STOPPABLE_PHASES.
_STOPPABLE_PHASES = (RuntimePhase.PREFLIGHT, RuntimePhase.RUNNING)

DriverFactory = Callable[..., "MoreliaRuntime"]

# How many consecutive 409s a never-yet-accepted watchdog tolerates before
# giving up anyway. At the driver's report cadence this is well past any
# plausible poller registration delay, but bounded — a watchdog that truly
# was superseded before its first acceptance must still exit rather than
# hold hardware (COM ports) forever.
STALE_GRACE_ATTEMPTS = 20


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("recording timestamp must be an ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("recording timestamps must have a timezone")
    return parsed.astimezone(UTC)


def elapsed_clock():
    """System-wide suspend-inclusive clock plus OS-provided boot identity."""
    if sys.platform == "win32":
        import ctypes
        class BootInfo(ctypes.Structure):
            _fields_ = [("identifier", ctypes.c_ubyte * 16), ("firmware", ctypes.c_uint),
                        ("flags", ctypes.c_ulonglong)]
        info = BootInfo()
        status = ctypes.windll.ntdll.NtQuerySystemInformation(90, ctypes.byref(info), ctypes.sizeof(info), None)
        if status != 0:
            raise RuntimeError("cannot establish Windows boot identity")
        tick = ctypes.windll.kernel32.GetTickCount64
        tick.restype = ctypes.c_ulonglong
        return "windows_tick_count64", bytes(info.identifier).hex(), tick() / 1000.0
    if hasattr(time, "CLOCK_BOOTTIME"):
        from pathlib import Path
        return "linux_boottime", Path("/proc/sys/kernel/random/boot_id").read_text().strip(), time.clock_gettime(time.CLOCK_BOOTTIME)
    raise RuntimeError("no qualified suspend-inclusive elapsed clock")


def remaining_recording_seconds(recording_state, duration_seconds):
    if duration_seconds is None or not recording_state:
        return None
    return _remaining_recording_seconds(recording_state, duration_seconds, elapsed_clock())


def _remaining_recording_seconds(recording_state, duration_seconds, clock_sample):
    started = _utc(recording_state["started_at"])
    validate_duration_seconds(duration_seconds, start_at=started)
    anchor = recording_state["clock_anchor"]
    kind, boot, now = clock_sample
    if not isinstance(anchor.get("boot_id"), str) or not anchor["boot_id"]:
        raise ValueError("missing recording boot identity")
    deadline = anchor.get("deadline_elapsed")
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("invalid elapsed recording deadline")
    if anchor.get("kind") != kind:
        raise ValueError("incompatible recording elapsed clock")
    if anchor["boot_id"] == boot:
        return deadline - now
    # A different OS-provided boot identifier is affirmative reboot evidence.
    return (started + timedelta(seconds=duration_seconds) - datetime.now(UTC)).total_seconds()


def _json_evidence(value):
    if is_dataclass(value):
        return _json_evidence(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_evidence(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_evidence(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class WatchdogIdentity:
    """Who is running the manifest, as reported to the control plane.

    Distinct from the manifest (what to run): the same manifest/dataflow can
    be picked up by a respawned watchdog process with a fresh ``watchdog_id``
    (see ``StaleWatchdogReport`` fencing in ``app.services.event_ingest``).
    """

    runtime_id: str
    watchdog_id: str

    def __post_init__(self) -> None:
        for field_name in ("runtime_id", "watchdog_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")


class WatchdogProcess:
    """Owns the runtime driver, the outbox, and the direct-ingest flush path."""

    def __init__(
        self,
        *,
        manifest: Manifest,
        identity: WatchdogIdentity,
        outbox: WatchdogOutbox,
        telemetry_client: TelemetryClient,
        build_driver: DriverFactory,
        stale_grace_attempts: int = STALE_GRACE_ATTEMPTS,
    ) -> None:
        self._manifest = manifest
        self._identity = identity
        self._outbox = outbox
        self._client = telemetry_client
        self._stopped = False
        self._stop_reason: str | None = None
        self._stale_grace_attempts = stale_grace_attempts
        self._delivered_once = False
        self._stale_streak = 0
        self._decision_lock = threading.RLock()
        self._shutdown_lock = threading.Lock()
        self._cancel = Event()
        self._timer_closed = Event()
        self._timing: dict = {}
        self._bounds: dict = {}
        self._intent: dict | None = None
        self._pending_stop_requests: list[dict] = []
        self._result: dict | None = None
        self._evidence_errors: list[str] = []
        self._event_sequence = 0
        self._last_progress = 0.0
        self._deadline_elapsed: float | None = None
        self.driver: MoreliaRuntime = build_driver(
            manifest=manifest,
            on_report=self._on_report,
        )
        bind = getattr(self.driver, "bind_lifecycle", None)
        if callable(bind):
            bind(on_recording=self.recording_acknowledged, cancelled=self._cancel.is_set,
                 on_first_data=self.first_data_received,
                 on_failure=lambda: self.request_stop("runtime_failure"))
        self._timer = threading.Thread(target=self._deadline_loop, name="recording-deadline", daemon=True)
        if manifest.duration_seconds is not None:
            self._timer.start()

    @property
    def timing_evidence(self):
        with self._decision_lock:
            last = max((_utc(bound["last_sample_at"]) for bound in self._bounds.values()), default=None)
            return {**self._timing, "recording_bounds": list(self._bounds.values()),
                    "ended_at": last.isoformat() if last else None} if self._timing else {}

    @property
    def stop_intent(self):
        with self._decision_lock:
            return dict(self._intent) if self._intent else None

    @property
    def stop_result(self):
        return self._result

    @property
    def stopping(self):
        return self._cancel.is_set()

    def restore_timing(self, evidence):
        with self._decision_lock:
            if self._timing:
                raise ValueError("recording start already established")
            duration = self._manifest.duration_seconds
            clock_sample = elapsed_clock() if duration is not None else None
            remaining = (
                _remaining_recording_seconds(evidence, duration, clock_sample)
                if clock_sample is not None else None
            )
            self._timing = {"started_at": evidence["started_at"],
                            "clock_anchor": dict(evidence["clock_anchor"])}
            self._bounds = {(b["source_id"], b["sink_id"]): dict(b) for b in evidence.get("recording_bounds", [])}
            if remaining is not None:
                kind, boot, elapsed = clock_sample
                anchor = self._timing["clock_anchor"]
                if anchor["boot_id"] == boot:
                    # Keep the exact saved deadline, without adding time spent
                    # validating evidence or reading a second clock sample.
                    self._deadline_elapsed = anchor["deadline_elapsed"]
                else:
                    self._deadline_elapsed = elapsed + remaining
                    self._timing["clock_anchor"] = {
                        "kind": kind, "boot_id": boot,
                        "deadline_elapsed": self._deadline_elapsed,
                    }
                    # Commit the new boot's elapsed reference before returning
                    # to preflight. A subsequent replacement must not consult
                    # adjustable UTC again within this boot. Persistence failure
                    # takes the existing cancellation/runtime-failure path.
                    self._persist_event(self._timing_event_type(), self.timing_evidence)
                    self._last_progress = monotonic()
                if remaining <= 0:
                    self.request_stop("duration_ended")

    def _timing_event_type(self):
        return "runtime.recording_progress" if self._bounds else "runtime.acquisition_started"

    def first_data_received(self, arrived_at):
        """Persist one receipt-time deadline; recovery and sink writes cannot reset it."""
        first = _utc(arrived_at)
        with self._decision_lock:
            if self._timing or self._intent is not None:
                return
            kind, boot, elapsed = elapsed_clock()
            duration = self._manifest.duration_seconds
            if duration is not None:
                validate_duration_seconds(duration, start_at=first)
            remaining = (first + timedelta(seconds=duration or 0) - datetime.now(UTC)).total_seconds()
            self._timing = {"started_at": first.isoformat(),
                            "clock_anchor": {"kind": kind, "boot_id": boot,
                                             "deadline_elapsed": elapsed + remaining}}
            if duration is not None:
                self._deadline_elapsed = elapsed + remaining
            self._persist_event("runtime.acquisition_started", self.timing_evidence)
            self._last_progress = monotonic()

    def recording_acknowledged(self, bounds):
        first, last = _utc(bounds["first_sample_at"]), _utc(bounds["last_sample_at"])
        if last < first:
            raise ValueError("recording bounds are reversed")
        with self._decision_lock:
            first_recording = not self._bounds
            key = (bounds["source_id"], bounds["sink_id"])
            old = self._bounds.get(key)
            self._bounds[key] = {**bounds,
                "first_sample_at": min(first, _utc(old["first_sample_at"]) if old else first).isoformat(),
                "last_sample_at": max(last, _utc(old["last_sample_at"]) if old else last).isoformat()}
            if self._timing and (first_recording or monotonic() - self._last_progress >= 1):
                self._persist_event("runtime.recording_started" if first_recording else "runtime.recording_progress", self.timing_evidence)
                self._last_progress = monotonic()

    def _deadline_loop(self):
        try:
            while not self._timer_closed.wait(.05):
                deadline = self._deadline_elapsed
                if deadline is not None and elapsed_clock()[2] >= deadline:
                    self.request_stop("duration_ended")
                    return
        except Exception as exc:
            self._evidence_errors.append(f"deadline_clock: {type(exc).__name__}: {exc}")
            self.request_stop("runtime_failure")

    def request_stop(self, reason="user_stop", requested_at=None, command_id=None):
        if reason not in {"user_stop", "duration_ended", "application_shutdown", "runtime_failure"}:
            raise ValueError("invalid stop reason")
        request = {"command_id": command_id or str(uuid.uuid5(uuid.NAMESPACE_URL,
            f"{self._manifest.dataflow_id}:{reason}")), "stop_reason": reason,
            "requested_at": _utc(requested_at).isoformat() if requested_at else datetime.now(UTC).isoformat()}
        # Publish availability and cancel before contending with a checkpoint.
        # Neither disk I/O nor a recovery lifecycle lock may delay cancellation.
        if self._intent is None:
            self._pending_stop_requests.append(request)
        self._cancel.set()
        signal_stop = getattr(self.driver, "request_cancel", None)
        if callable(signal_stop):
            signal_stop()
        with self._decision_lock:
            if self._intent is None:
                priorities = {"user_stop": 0, "duration_ended": 1,
                              "application_shutdown": 2, "runtime_failure": 2}
                self._intent = min(self._pending_stop_requests,
                                   key=lambda item: priorities[item["stop_reason"]])
                self._pending_stop_requests.clear()
                self._persist_event("runtime.stop_requested", self._intent)
            return self._result or dict(self._intent)

    def _persist_event(self, event_type, payload):
        self._event_sequence += 1
        try:
            self._outbox.enqueue(WatchdogTelemetryEnvelope(
                report_id=f"{self.identity.watchdog_id}:lifecycle:{self._event_sequence}",
                dataflow_id=self.manifest.dataflow_id, runtime_id=self.identity.runtime_id,
                watchdog_id=self.identity.watchdog_id, manifest_hash=self.manifest.hash,
                event_type=event_type, payload=_json_evidence(payload)))
        except Exception as exc:
            self._evidence_errors.append(f"{event_type}: {type(exc).__name__}: {exc}")
            _log.error("lifecycle evidence persistence failed", event_type=event_type, exc_info=True)
            # Failure to durably establish a start cannot permit a fresh timer.
            self._cancel.set()
            signal_stop = getattr(self.driver, "request_cancel", None)
            if callable(signal_stop):
                signal_stop()
            if self._intent is None:
                self.request_stop("runtime_failure")

    @property
    def outbox(self) -> WatchdogOutbox:
        return self._outbox

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    @property
    def identity(self) -> WatchdogIdentity:
        return self._identity

    def rebind_runtime(self, runtime_id: str) -> None:
        """Bind future telemetry to the replacement runtime host identity."""
        self._outbox.rebind_pending_runtime(
            watchdog_id=self._identity.watchdog_id,
            runtime_id=runtime_id,
        )
        self._identity = WatchdogIdentity(
            runtime_id=runtime_id,
            watchdog_id=self._identity.watchdog_id,
        )

    def recover(self, recovery_id: str, device_id: str) -> None:
        """Run one explicit operator-approved stream restart."""
        if self.stopping:
            raise RuntimeError("runtime is stopping")
        self.driver.recover(recovery_id, device_id)

    @property
    def stopped(self) -> bool:
        """True once a fatal ingest response has stopped this process."""
        return self._stopped

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def _on_report(self, report: RuntimeReport) -> None:
        """Driver report callback: outbox first, then attempt delivery.

        Enqueuing before any network attempt is the whole point of the
        outbox — a report that made it here is durable on disk even if every
        subsequent flush attempt fails.
        """
        envelope = self.to_envelope(report)
        self._outbox.enqueue(envelope)
        self.flush()

    def to_envelope(self, report: RuntimeReport) -> WatchdogTelemetryEnvelope:
        """Bind a driver-local ``RuntimeReport`` to this process's cross-process identity.

        ``report_id`` combines ``watchdog_id`` (unique per watchdog-process
        instance) with the driver's own monotonic ``sequence`` — stable and
        unique across retries/redeliveries of the *same* report, and never
        reused by a respawned watchdog process (which gets a fresh
        ``watchdog_id``, see ``WatchdogIdentity``).
        """
        payload: dict[str, object] = {
            "devices": [device.to_dict() for device in report.devices],
        }
        if report.diagnostics is not None:
            payload["diagnostics"] = dict(report.diagnostics)
        if report.recovery_id is not None:
            payload["recovery_id"] = report.recovery_id
        # Per-sink state crosses the boundary under its OWN payload key, kept
        # strictly separate from ``devices`` (source/stream health): a sink
        # failure never rides in as source health (gaps SINK-08/SINK-19/SINK-23).
        # Omitted when empty so an all-source report keeps its prior wire shape.
        if report.sinks:
            payload["sinks"] = [sink.to_dict() for sink in report.sinks]
        return WatchdogTelemetryEnvelope(
            report_id=f"{self._identity.watchdog_id}:{report.sequence}",
            dataflow_id=report.dataflow_id,
            runtime_id=self._identity.runtime_id,
            watchdog_id=self._identity.watchdog_id,
            manifest_hash=self._manifest.hash,
            event_type="runtime.report",
            payload=payload,
        )

    def flush(self) -> None:
        """Deliver pending outbox rows in order; stop at the first non-delivered one.

        Mirrors ``DataflowRuntimeHost._flush_ring``'s "stop at first failure"
        rule so per-dataflow ordering is preserved: a report never reaches
        the control plane ahead of one enqueued before it. A fatal outcome
        additionally stops this whole watchdog process (see ``_handle_fatal``).
        """
        if self._stopped:
            return
        for row in self._outbox.pending():
            result = self._client.send(row.envelope)
            if result.outcome is DeliveryOutcome.DELIVERED:
                self._delivered_once = True
                self._stale_streak = 0
                self._outbox.mark_delivered(row.envelope.report_id)
                continue
            if result.outcome is DeliveryOutcome.STALE and not self._delivered_once:
                # Identity-registration race (see module docstring): the plane
                # has not yet learned this watchdog_id from the host's /status.
                # Leave the report pending and retry on the next flush.
                self._stale_streak += 1
                if self._stale_streak < self._stale_grace_attempts:
                    _log.warning(
                        "report fenced before first acceptance — retrying "
                        "(identity likely not yet registered)",
                        watchdog_id=self._identity.watchdog_id,
                        attempt=self._stale_streak,
                        reason=result.message,
                    )
                    break
            if result.is_fatal:
                self._handle_fatal(result)
            break

    def _handle_fatal(self, result: DeliveryResult) -> None:
        """Flag this process as stopped. Deliberately does NOT call ``shutdown()``.

        ``_on_report`` (and therefore this) runs on whatever thread the
        driver emits reports from — for ``MoreliaRuntime`` that is its own
        watchdog thread (``_run_watchdog``). ``MoreliaRuntime.stop()`` joins
        that same thread, and a thread cannot join itself
        (``RuntimeError: cannot join current thread``). Calling
        ``shutdown()`` from here would therefore risk exactly that deadlock
        the moment a real driver is wired in. Instead this only sets the
        flag; the entrypoint's main loop (running on the main thread, see
        ``app.watchdog_process.__main__.main``) observes ``stopped`` and
        calls ``shutdown()`` itself shortly after, off the driver's thread.
        """
        _log.error(
            "watchdog ingest rejected — stopping process",
            outcome=result.outcome.value,
            status_code=result.status_code,
            reason=result.message,
        )
        self._stopped = True
        self._stop_reason = result.message or result.outcome.value
        self.request_stop("runtime_failure")

    def shutdown(self):
        """Cache acknowledged teardown evidence; CLOSED alone is never proof."""
        self.request_stop("application_shutdown")
        with self._shutdown_lock:
            if self._result is not None and self._result.get("teardown_confirmed") is True:
                return self._result
            previous = self._result
            errors = list(dict.fromkeys([
                *(previous.get("errors", []) if previous else []), *self._evidence_errors]))
            try:
                if previous is not None or self.driver.phase in _STOPPABLE_PHASES:
                    self.driver.stop()
            except Exception as exc:
                errors.append(f"stop: {type(exc).__name__}: {exc}")
            try:
                self.driver.close()
            except Exception as exc:
                errors.append(f"close: {type(exc).__name__}: {exc}")
            result = getattr(self.driver, "shutdown_result", None)
            result = _json_evidence(result) if result is not None else {"ok": False, "error": "missing_shutdown_evidence"}
            result.setdefault("previous_stream_results", [])
            inventory_complete = result.get("worker_inventory_complete") is True
            resources_released = result.get("resources_teardown_confirmed") is True
            stream_results = [*result.get("stream_results", []), *result.get("previous_stream_results", [])]
            clean = (result.get("ok") is True and not errors
                     and all(row.get("ok") is True and not row.get("forced_termination")
                             for row in stream_results)
                     and (previous is None or previous.get("output_integrity_confirmed") is True))
            streams_released = all(
                row.get("teardown_confirmed") is True if "teardown_confirmed" in row
                else row.get("ok") is True for row in stream_results)
            teardown = (result.get("teardown_confirmed") is True and streams_released
                        if "teardown_confirmed" in result else bool(stream_results) and streams_released)
            teardown = teardown and inventory_complete and resources_released
            if previous is not None:
                result["previous_shutdown_result"] = previous["shutdown_result"].get(
                    "previous_shutdown_result", previous["shutdown_result"])
                if not clean:
                    result["ok"] = False
            self._result = {**self._intent, **self.timing_evidence, "shutdown_result": result,
                "recording_bounds": list(self._bounds.values()),
                "teardown_confirmed": teardown,
                "worker_inventory_complete": inventory_complete,
                "resources_teardown_confirmed": resources_released,
                "previous_stream_results": result["previous_stream_results"],
                "output_integrity_confirmed": clean and teardown,
                "errors": errors, "finished_at": datetime.now(UTC).isoformat()}
            if self._timing:
                self._persist_event(self._timing_event_type(), self.timing_evidence)
            self._result["errors"] = list(dict.fromkeys([*errors, *self._evidence_errors]))
            if self._evidence_errors:
                self._result["output_integrity_confirmed"] = False
            self._persist_event("runtime.stop_finished", self._result)
            self._result["errors"] = list(dict.fromkeys([*errors, *self._evidence_errors]))
            if self._evidence_errors:
                self._result["output_integrity_confirmed"] = False
            self._timer_closed.set()
            # HTTP delivery is after cancellation and complete teardown.
            try:
                self.flush()
            except Exception:
                _log.warning("terminal evidence remains pending", exc_info=True)
            return self._result


__all__ = ["WatchdogIdentity", "WatchdogProcess"]
