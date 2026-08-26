"""Interval poller for runtime-host status rings and link liveness.

The poller is the control-plane-owned backstop for Stage 7 events:
it probes each live runtime host, ingests every report exposed by ``/status``,
and computes the plane-to-host ``LinkStatus`` from its own observations.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

import structlog
from flask import Flask

from app.config import get_config
from app.database import db
from app.domain.enums import (
    CommsStatus,
    HealthState,
    LinkStatus,
    SessionStatus,
    StreamStatus,
    WatchdogProcessState,
)
from app.models.backend_event import BackendEvent
from app.repositories.backend_events import BackendEventRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import DeviceReport, RuntimePhase, RuntimeReport
from app.services import incidents
from app.services.event_ingest import ingest_report
from app.services.health_state import aggregate_streams, derive

_log = structlog.get_logger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_DELAYED_AFTER_SECONDS = 5.0
DEFAULT_UNREACHABLE_AFTER_SECONDS = 15.0

# Freshness windows for the DIRECT watchdog report to control-plane
# "stale" is a soft warning; "overflow" is a gap implying the watchdog's  
# outbox is not draining
DEFAULT_TELEMETRY_STALE_AFTER_SECONDS = 10.0
DEFAULT_TELEMETRY_OVERFLOW_AFTER_SECONDS = 60.0

# Freshness window for the control plane's poll-reconciled view of the
# watchdog process's own heartbeat (RuntimeOwnership.watchdog_last_seen_at) 
DEFAULT_WATCHDOG_STALE_AFTER_SECONDS = 10.0


def telemetry_freshness(
    latest: BackendEvent | None,
    *,
    now: datetime,
    stale_after_seconds: float = DEFAULT_TELEMETRY_STALE_AFTER_SECONDS,
    overflow_after_seconds: float = DEFAULT_TELEMETRY_OVERFLOW_AFTER_SECONDS,
) -> str:
    """Classify direct watchdog-telemetry freshness: "current"/"stale"/
    "overflow"/"unknown" (no direct telemetry observed yet for this session).

    This is the single source of truth for both incident triggers
    (app.services.incidents.evaluate_telemetry_freshness) and operator-facing status
    (app.services.session_status's outbox_health)
    """
    if latest is None or latest.received_at is None:
        return "unknown"
    received_at = latest.received_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    age_seconds = max(0.0, (now - received_at).total_seconds())
    if age_seconds >= overflow_after_seconds:
        return "overflow"
    if age_seconds >= stale_after_seconds:
        return "stale"
    return "current"


@dataclass(frozen=True, slots=True)
class DataflowTarget:
    """One live dataflow host the poller should probe."""

    dataflow_id: str
    port: int


@dataclass(frozen=True, slots=True)
class PollSnapshot:
    """Latest poller-owned liveness observation for a dataflow."""

    dataflow_id: str
    link_status: LinkStatus
    health_state: HealthState
    last_received_at: datetime | None
    age_seconds: float | None
    probe_succeeded: bool
    last_error: str | None = None


class EventPoller:
    """Poll runtime-host ``/status`` rings and compute link liveness."""

    def __init__(
        self,
        *,
        targets: Callable[[], Iterable[DataflowTarget]],
        probe_status: Callable[[int], Mapping[str, Any]],
        interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        delayed_after_seconds: float = DEFAULT_DELAYED_AFTER_SECONDS,
        unreachable_after_seconds: float = DEFAULT_UNREACHABLE_AFTER_SECONDS,
        telemetry_stale_after_seconds: float = DEFAULT_TELEMETRY_STALE_AFTER_SECONDS,
        telemetry_overflow_after_seconds: float = DEFAULT_TELEMETRY_OVERFLOW_AFTER_SECONDS,
        watchdog_stale_after_seconds: float = DEFAULT_WATCHDOG_STALE_AFTER_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        if delayed_after_seconds <= 0:
            raise ValueError("delayed_after_seconds must be greater than zero")
        if unreachable_after_seconds <= delayed_after_seconds:
            raise ValueError(
                "unreachable_after_seconds must be greater than delayed_after_seconds"
            )
        if telemetry_stale_after_seconds <= 0:
            raise ValueError("telemetry_stale_after_seconds must be greater than zero")
        if telemetry_overflow_after_seconds <= telemetry_stale_after_seconds:
            raise ValueError(
                "telemetry_overflow_after_seconds must be greater than telemetry_stale_after_seconds"
            )
        if watchdog_stale_after_seconds <= 0:
            raise ValueError("watchdog_stale_after_seconds must be greater than zero")

        self.interval_seconds = interval_seconds
        self.delayed_after_seconds = delayed_after_seconds
        self.unreachable_after_seconds = unreachable_after_seconds
        self.telemetry_stale_after_seconds = telemetry_stale_after_seconds
        self.telemetry_overflow_after_seconds = telemetry_overflow_after_seconds
        self.watchdog_stale_after_seconds = watchdog_stale_after_seconds
        self._targets = targets
        self._probe_status = probe_status
        self._clock = clock or (lambda: datetime.now(UTC))

        self._snapshots: dict[str, PollSnapshot] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._app: Flask | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self, dataflow_id: str) -> PollSnapshot | None:
        with self._lock:
            return self._snapshots.get(dataflow_id)

    def snapshots(self) -> dict[str, PollSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    def discard(self, dataflow_id: str) -> None:
        """Drop a dataflow's snapshot, e.g. once its runtime host is torn down.

        ``poll_once`` only ever adds/updates entries for currently-live targets
        — it never prunes one that stops appearing in ``targets()`` (a stopped
        dataflow is popped from the supervisor's registry, so it simply stops
        being polled). Without this, the last-observed ``health_state`` (often
        HEALTHY) lingers in ``snapshots()`` forever, so a stopped session would
        keep reporting live health from a process that no longer exists. Call
        this as part of tearing a dataflow down so ``_live_health()`` reports
        ``None`` for it instead of a stale reading.
        """
        with self._lock:
            self._snapshots.pop(dataflow_id, None)

    def poll_once(self) -> list[PollSnapshot]:
        """Probe each current target once and return their snapshots."""

        snapshots = [self._poll_target(target) for target in list(self._targets())]
        with self._lock:
            for snapshot in snapshots:
                self._snapshots[snapshot.dataflow_id] = snapshot
        return snapshots

    def start(self, *, app: Flask | None = None) -> None:
        """Start the daemon loop. Calling ``start`` twice is a no-op."""

        if self.is_running:
            return
        self._app = app
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="event-poller",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop the daemon loop and wait briefly for clean shutdown."""

        if timeout is None:
            timeout = get_config().CONTROL_PLANE_POLLER_STOP_TIMEOUT_SECONDS
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._app = None

    def __enter__(self) -> EventPoller:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def _run_loop(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                if self._app is None:
                    self.poll_once()
                else:
                    with self._app.app_context():
                        self.poll_once()
                if consecutive_failures:
                    _log.info(
                        "poll loop recovered",
                        attempt=consecutive_failures,
                    )
                consecutive_failures = 0
            except Exception:
                # A background poll failure must not kill the daemon-owned loop,
                # but it must not fail invisibly either. Log the first failure
                # of a streak, then once a minute at a 1s interval.
                consecutive_failures += 1
                if consecutive_failures == 1 or consecutive_failures % 60 == 0:
                    _log.warning(
                        "poll loop iteration failed",
                        attempt=consecutive_failures,
                        exc_info=True,
                    )
            self._stop_event.wait(self.interval_seconds)

    def _poll_target(self, target: DataflowTarget) -> PollSnapshot:
        latest_report: RuntimeReport | None = None
        phase = RuntimePhase.IDLE
        probe_succeeded = False
        last_error: str | None = None
        runtime_id_raw: str | None = None
        watchdog_id_raw: str | None = None
        watchdog_state_raw: str | None = None
        respawn_exhausted = False

        try:
            status = self._probe_status(target.port)
            probe_succeeded = True
            if isinstance(status.get("phase"), str):
                phase = RuntimePhase(status["phase"])
            if isinstance(status.get("runtime_id"), str):
                runtime_id_raw = status["runtime_id"]
            if isinstance(status.get("watchdog_id"), str):
                watchdog_id_raw = status["watchdog_id"]
            watchdog_state_raw = status.get("watchdog_state")
            respawn_exhausted = bool(status.get("watchdog_respawn_exhausted"))
            reports = status.get("reports", [])
            if isinstance(reports, list):
                for raw in reports:
                    if not isinstance(raw, Mapping):
                        continue
                    if raw.get("dataflow_id") != target.dataflow_id:
                        continue
                    ingest_report(raw)
                    latest_report = RuntimeReport.from_dict(raw)
        except Exception as exc:
            last_error = type(exc).__name__

        last_received_at = self._last_received_at(target.dataflow_id)
        age_seconds = self._age_seconds(last_received_at)
        link_status = self._link_status(
            probe_succeeded=probe_succeeded,
            age_seconds=age_seconds,
            latest_report=latest_report,
        )
        health_state = self._health_state(
            link_status=link_status,
            direct_telemetry=self._current_direct_telemetry(
                target.dataflow_id,
                runtime_id=runtime_id_raw,
                watchdog_id=watchdog_id_raw,
            ),
            host_report=latest_report,
            phase=phase,
            watchdog_state_raw=watchdog_state_raw,
            respawn_exhausted=respawn_exhausted,
        )
        self._evaluate_incident_signals(
            target.dataflow_id,
            link_status=link_status,
            probe_succeeded=probe_succeeded,
            watchdog_state_raw=watchdog_state_raw,
            respawn_exhausted=respawn_exhausted,
        )
        return PollSnapshot(
            dataflow_id=target.dataflow_id,
            link_status=link_status,
            health_state=health_state,
            last_received_at=last_received_at,
            age_seconds=age_seconds,
            probe_succeeded=probe_succeeded,
            last_error=last_error,
        )

    def _link_status(
        self,
        *,
        probe_succeeded: bool,
        age_seconds: float | None,
        latest_report: RuntimeReport | None,
    ) -> LinkStatus:
        if not probe_succeeded:
            if age_seconds is not None and age_seconds >= self.unreachable_after_seconds:
                return LinkStatus.UNREACHABLE
            return LinkStatus.DELAYED

        if age_seconds is not None and age_seconds >= self.delayed_after_seconds:
            return LinkStatus.DELAYED

        if latest_report is not None and latest_report.comms in (
            CommsStatus.DELAYED,
            CommsStatus.UNREACHABLE,
        ):
            return LinkStatus.DELAYED

        return LinkStatus.REACHABLE

    def _evaluate_incident_signals(
        self,
        dataflow_id: str,
        *,
        link_status: LinkStatus,
        probe_succeeded: bool,
        watchdog_state_raw: str | None,
        respawn_exhausted: bool,
    ) -> None:
        """Run every incident trigger for one poll tick.

        Skips silently if dataflow_id has no session (stale/orphaned target).

        Crash and crash-loop only run when probe_succeeded: they read this
        tick's live /status payload, so a failed probe has nothing fresh to
        check. Stale-process and telemetry-freshness always run as they read
        durable DB state instead.
        """
        session = SessionRepository().get_by_dataflow_id(dataflow_id)
        if session is None:
            return
        if session.status is SessionStatus.STOPPING:
            return
        if session.status in {
            SessionStatus.COMPLETED,
            SessionStatus.CANCELLED,
        }:
            incidents.resolve_terminal_supervision_incidents(session.id, dataflow_id)
            return

        incidents.evaluate_link_status(session.id, dataflow_id, link_status)

        if probe_succeeded:
            incidents.evaluate_watchdog_crash(
                session.id,
                dataflow_id,
                crashed=watchdog_state_raw == WatchdogProcessState.CRASHED.value,
            )
            incidents.evaluate_crash_loop(
                session.id, dataflow_id, respawn_exhausted=respawn_exhausted
            )

        ownership = self._newest_ownership_for_dataflow(session.id, dataflow_id)
        if ownership is not None:
            incidents.evaluate_stale_process(
                session.id,
                dataflow_id,
                stale=self._is_stale(ownership.watchdog_last_seen_at, self.watchdog_stale_after_seconds),
            )

        latest_direct = BackendEventRepository().latest_direct_telemetry_for_session(session.id)
        incidents.evaluate_telemetry_freshness(
            session.id,
            dataflow_id,
            freshness=telemetry_freshness(
                latest_direct,
                now=self._clock(),
                stale_after_seconds=self.telemetry_stale_after_seconds,
                overflow_after_seconds=self.telemetry_overflow_after_seconds,
            ),
        )

    @staticmethod
    def _newest_ownership_for_dataflow(session_id: int, dataflow_id: str):
        """The newest RuntimeOwnership row for a dataflow, in ANY state.
        """
        for row in RuntimeOwnershipRepository().list_for_session(session_id):
            if row.dataflow_id == dataflow_id:
                return row
        return None

    def _current_direct_telemetry(
        self,
        dataflow_id: str,
        *,
        runtime_id: str | None,
        watchdog_id: str | None,
    ) -> BackendEvent | None:
        """Newest fresh direct report for the active watchdog generation.

        Runtime-host probing reconciles a respawned ``watchdog_id`` before this
        method runs in production. Requiring both the active durable identity
        and a running/adopted watchdog prevents the previous generation's last
        report from being presented as current during the hand-off window.
        """
        if runtime_id is None or watchdog_id is None:
            return None
        ownership = RuntimeOwnershipRepository().active_for_dataflow(dataflow_id)
        if (
            ownership is None
            or ownership.runtime_id != runtime_id
            or ownership.watchdog_id != watchdog_id
            or ownership.watchdog_state
            not in {WatchdogProcessState.RUNNING, WatchdogProcessState.ADOPTED}
        ):
            return None
        latest = BackendEventRepository().latest_direct_telemetry_for_identity(
            dataflow_id,
            runtime_id=runtime_id,
            watchdog_id=watchdog_id,
        )
        if (
            telemetry_freshness(
                latest,
                now=self._clock(),
                stale_after_seconds=self.telemetry_stale_after_seconds,
                overflow_after_seconds=self.telemetry_overflow_after_seconds,
            )
            != "current"
        ):
            return None
        return latest

    def _is_stale(self, last_seen_at: datetime | None, threshold_seconds: float) -> bool:
        if last_seen_at is None:
            return False  # nothing seen yet is not evidence of staleness
        age = self._age_seconds(last_seen_at)
        return age is not None and age >= threshold_seconds

    @staticmethod
    def _health_state(
        *,
        link_status: LinkStatus,
        direct_telemetry: BackendEvent | None,
        host_report: RuntimeReport | None,
        phase: RuntimePhase,
        watchdog_state_raw: str | None,
        respawn_exhausted: bool,
    ) -> HealthState:
        # Reachability remains host-probe authority and outranks content. A
        # reachable host whose watchdog exhausted its respawn budget is still a
        # failed acquisition, not a healthy host.
        if link_status is LinkStatus.UNREACHABLE:
            return HealthState.UNREACHABLE
        if phase in (RuntimePhase.STOPPED, RuntimePhase.CLOSED):
            return HealthState.STOPPED
        if respawn_exhausted:
            return HealthState.FAILED

        devices: tuple[DeviceReport, ...] = ()
        recovery_active = False
        has_stream_evidence = False
        if direct_telemetry is not None:
            raw_devices = (direct_telemetry.payload or {}).get("devices")
            if isinstance(raw_devices, list) and raw_devices:
                try:
                    devices = tuple(DeviceReport.from_dict(raw) for raw in raw_devices)
                except (KeyError, TypeError, ValueError):
                    devices = ()
                else:
                    has_stream_evidence = True
            recovery_active = direct_telemetry.recovery_id is not None
        elif host_report is not None and host_report.devices:
            # Compatibility for runtime drivers that still carry device content
            # through the host ring. The watchdog-process driver deliberately
            # emits an empty tuple, which is absence of evidence rather than a
            # vacuously healthy fleet.
            devices = host_report.devices
            has_stream_evidence = True
            recovery_active = host_report.recovery_id is not None

        if not has_stream_evidence:
            if (
                recovery_active
                or watchdog_state_raw == WatchdogProcessState.CRASHED.value
            ):
                return HealthState.RECOVERING
            provisional = derive(
                link_status=link_status,
                stream_agg=StreamStatus.HEALTHY,
                phase=phase,
                op_state=None,
                recovery_active=False,
            )
            return HealthState.UNKNOWN if provisional is HealthState.HEALTHY else provisional

        return derive(
            link_status=link_status,
            stream_agg=aggregate_streams(devices),
            phase=phase,
            op_state=None,
            recovery_active=recovery_active,
        )

    def _age_seconds(self, last_received_at: datetime | None) -> float | None:
        if last_received_at is None:
            return None
        if last_received_at.tzinfo is None:
            last_received_at = last_received_at.replace(tzinfo=UTC)
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return max(0.0, (now - last_received_at).total_seconds())

    @staticmethod
    def _last_received_at(dataflow_id: str) -> datetime | None:
        value = db.session.scalar(
            db.select(db.func.max(BackendEvent.received_at)).where(
                BackendEvent.dataflow_id == dataflow_id
            )
        )
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
