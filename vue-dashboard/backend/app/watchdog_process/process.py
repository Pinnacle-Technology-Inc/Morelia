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
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

import structlog

from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
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
        self.driver: MoreliaRuntime = build_driver(
            manifest=manifest,
            on_report=self._on_report,
        )

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

    def shutdown(self) -> None:
        """Best-effort ``stop()`` then ``close()`` of the driver, tolerant of any phase.

        Callers must not invoke this from within the driver's own report
        callback (see ``_handle_fatal``) — only from the entrypoint's main
        thread. Safe to call more than once: ``stop()`` is only attempted
        from a phase that supports it, and the driver's own ``close()`` is
        documented as idempotent.
        """
        started_at = monotonic()
        _log.info(
            "watchdog_shutdown_started",
            terminal_phase=self.driver.phase.value,
            outcome="started",
        )
        if self.driver.phase in _STOPPABLE_PHASES:
            try:
                self.driver.stop()
            except Exception:
                _log.error("driver stop failed during shutdown", exc_info=True)
        try:
            self.driver.close()
        except Exception:
            _log.error("driver close failed during shutdown", exc_info=True)
        _log.info(
            "watchdog_shutdown_confirmed",
            terminal_phase=self.driver.phase.value,
            outcome="completed",
            elapsed_ms=round((monotonic() - started_at) * 1000, 2),
        )


__all__ = ["WatchdogIdentity", "WatchdogProcess"]
