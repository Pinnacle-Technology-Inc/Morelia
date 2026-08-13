"""When a data-path condition stops being a record and starts needing a person.

Incidents and gaps are two different kinds of thing here, and this module owns
the line between them:

  - A *gap* is a fact. Data is missing between two points. It is written on the
    healing edge (``app.services.gaps``), it never clears, and nobody has to do
    anything about it. An operator looks gaps up when they want to know whether
    a recording is trustworthy.
  - An *incident* is a request for attention. It exists only while something is
    waiting on a human.

So a disconnect that automatic recovery handles on its own leaves a gap and
NOTHING else — no incident opens on the way down and auto-resolves on the way
back up. An incident is opened only when one of these holds:

  1. **Restarting the stream's WORKER stopped working.** Each stream has its own
     ``StreamWatcher`` thread supervising one worker process — the process that
     actually opens the COM port and reads the device. After
     ``max_auto_restart_attempts`` failed restarts against a port that is present
     and openable, that watcher publishes ``action == "needs_action"``
     (``Watchdog._transition_to_needs_action``). This is the authoritative signal:
     the watcher is the only component that knows both the restart budget and the
     policy, so the control plane must not re-derive it.

     NOT to be confused with the watchdog PROCESS crashing. That is a different
     layer with its own separate budget (``WATCHDOG_RESPAWN_MAX_ATTEMPTS``, spent
     in ``app.runtime_host.watchdog_process_driver``) and its own reasons
     (``watchdog process crash`` / ``watchdog crash loop``) on the control-plane
     axis. Both budgets default to 3, which makes them easy to mix up:

         watchdog PROCESS  — supervises every stream; dying stops all supervision
           └─ StreamWatcher thread (per stream)
               └─ WORKER process  — reads one device; dying stops one stream

     A worker that will not come back is lost data for ONE device and belongs
     here. A watchdog process that will not come back means nothing is being
     supervised at all, and belongs on the control plane.
  2. **The policy is RECOMMEND.** Nothing will act without an operator, so a
     stream that is down is by definition waiting on one.
  3. **The real-data heartbeat maximum was crossed.** The watchdog publishes
     ``heartbeat_age_exceeded`` at that boundary. This opens an incident
     immediately while automatic recovery continues trying to preserve data.
  4. **A legacy/incomplete report shows the port absent too long.** Under AUTOMATE the watchdog
     deliberately re-arms out of ``needs_action`` and polls for the replug
     forever rather than holding a terminal state
     (``Watchdog._maybe_rearm_from_needs_action``: "Port absent -> a physical
     disconnect. Prioritize self-recovery"). That is correct for a quick
     unplug/replug and wrong for a device unplugged at 2 AM that never comes
     back — which would otherwise surface NOWHERE: never escalated, and never a
     gap either, because a gap needs a healed episode.

Duration in (4) is derived, never stored. The watchdog publishes a per-device
``consecutive_nonhealthy_ticks`` streak and its own ``report_interval_seconds``
in the same diagnostics blob, so elapsed time is their product — no new wire
field, no control-plane bookkeeping, and nothing to reconcile after a restart.

Pure functions only: no DB, no Flask. Callers supply the report and the policy.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.enums import PolicyMode, StreamStatus
from app.runtime_child.driver import RuntimeReport, SinkHealth, SinkReport

# The watchdog's terminal signal — restarts spent against a live, openable port.
NEEDS_ACTION = "needs_action"

# Legacy/fallback actions used when an explicit heartbeat-boundary report was
# missed or came from an older runtime. Elapsed time prevents an unbounded wait
# from remaining invisible.
PORT_ABSENT_ACTIONS = frozenset(
    {"waiting_for_port", "waiting_for_port_release"}
)
HEARTBEAT_AGE_EXCEEDED = "heartbeat_age_exceeded"

# Fallback when a report omits the watchdog block. Mirrors both
# ``Config.WATCHDOG_REPORT_INTERVAL_SECONDS`` and ``MoreliaDriver``'s own
# default, so a diagnostics-less report degrades to the real cadence rather
# than to zero (which would make every streak look instantaneous).
DEFAULT_REPORT_INTERVAL_SECONDS = 3.0

# Secondary port-absence fallback when no heartbeat-boundary action is available,
# mirroring ``Config.STREAM_PORT_ABSENT_ESCALATION_SECONDS``.
DEFAULT_PORT_ABSENT_LIMIT_SECONDS = 30.0

# Why this became an operator's problem. Recorded in incident ``details`` so the
# cause never has to be re-derived from a later report that no longer shows it.
CAUSE_WATCHDOG_EXHAUSTED = "watchdog_auto_recovery_exhausted"
CAUSE_RECOMMEND_POLICY = "recommend_policy_awaits_operator"
CAUSE_PORT_ABSENT = "port_absent_beyond_threshold"
CAUSE_SINK_MISSED_RECOVERY = "sink_did_not_recover_with_source"


def diagnostics_by_device(report: RuntimeReport) -> dict[str, Mapping[str, object]]:
    """Index a report's per-stream diagnostics by ``device_id``.

    The typed ``DeviceReport`` carries only ``device_id`` + ``stream_status``
    (its ``_ALLOWED`` set rejects anything else), so every richer signal —
    ``action``, ``consecutive_nonhealthy_ticks``, the recovery block — travels
    in the free-form ``diagnostics`` mapping instead. Missing or malformed
    diagnostics yield an empty index rather than raising: a report that cannot
    justify an escalation simply does not produce one.
    """
    diagnostics = report.diagnostics
    if not isinstance(diagnostics, Mapping):
        return {}
    streams = diagnostics.get("streams")
    if not isinstance(streams, (list, tuple)):
        return {}
    indexed: dict[str, Mapping[str, object]] = {}
    for stream in streams:
        if not isinstance(stream, Mapping):
            continue
        device_id = stream.get("device_id")
        if isinstance(device_id, str) and device_id:
            indexed[device_id] = stream
    return indexed


def report_interval_seconds(report: RuntimeReport) -> float:
    """The watchdog's own reporting cadence, for turning tick streaks into time."""
    diagnostics = report.diagnostics
    if isinstance(diagnostics, Mapping):
        watchdog = diagnostics.get("watchdog")
        if isinstance(watchdog, Mapping):
            interval = watchdog.get("report_interval_seconds")
            if isinstance(interval, (int, float)) and not isinstance(interval, bool):
                if interval > 0:
                    return float(interval)
    return DEFAULT_REPORT_INTERVAL_SECONDS


def nonhealthy_seconds(
    diagnostic: Mapping[str, object], *, interval_seconds: float
) -> float | None:
    """How long this device has been continuously non-healthy, in seconds.

    ``None`` when the streak is absent — an unknown duration must never satisfy
    a "longer than" test.
    """
    ticks = diagnostic.get("consecutive_nonhealthy_ticks")
    if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks < 0:
        return None
    return ticks * interval_seconds


def effective_policy(
    diagnostic: Mapping[str, object], *, fallback: PolicyMode | None
) -> PolicyMode:
    """The policy the watchdog actually ran under, falling back to the session's.

    The report's value is preferred because it is the one that governed the
    recovery attempts this report describes: a session whose policy was edited
    mid-run would otherwise have its history judged under a rule that was never
    in force. ``RECOMMEND`` is the safe default — it escalates rather than
    staying silent — and matches ``Watchdog._normalize_recovery_policy``.
    """
    recovery = diagnostic.get("recovery")
    raw = recovery.get("policy") if isinstance(recovery, Mapping) else None
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value == PolicyMode.AUTOMATE.value:
            return PolicyMode.AUTOMATE
        if value in {PolicyMode.RECOMMEND.value, "recommended", "manual"}:
            return PolicyMode.RECOMMEND
    return fallback if fallback is not None else PolicyMode.RECOMMEND


def stream_escalation(
    *,
    stream_status: StreamStatus,
    diagnostic: Mapping[str, object],
    policy: PolicyMode,
    interval_seconds: float,
    port_absent_limit_seconds: float,
) -> str | None:
    """The cause requiring an operator for this stream, or ``None`` if none does.

    ``SUSPECT`` never escalates on its own: it is the watchdog's in-window,
    not-yet-settled state, and treating it as operator-facing is what would put
    a row on screen for every transient blip. It can still escalate through the
    ``needs_action`` and port-absence branches, which are about what recovery
    has already tried rather than about the current sample.
    """
    if stream_status is StreamStatus.HEALTHY:
        return None

    # (1) The watchdog's own verdict wins over anything inferred here.
    if diagnostic.get("action") == NEEDS_ACTION:
        return CAUSE_WATCHDOG_EXHAUSTED

    # (2) Under RECOMMEND nothing will act without a person, so a confirmed
    #     failure is already waiting on one.
    if policy is PolicyMode.RECOMMEND and stream_status is StreamStatus.UNHEALTHY:
        return CAUSE_RECOMMEND_POLICY

    # Crossing the configured real-data freshness boundary is immediately an
    # operator-visible incident even though automatic recovery keeps trying.
    if diagnostic.get("action") == HEARTBEAT_AGE_EXCEEDED:
        return CAUSE_PORT_ABSENT

    # (3) An unbounded wait for a port that never comes back.
    if diagnostic.get("action") in PORT_ABSENT_ACTIONS:
        elapsed = nonhealthy_seconds(diagnostic, interval_seconds=interval_seconds)
        if elapsed is not None and elapsed >= port_absent_limit_seconds:
            return CAUSE_PORT_ABSENT

    return None


def sink_escalation(
    sink: SinkReport, *, source_status: StreamStatus | None, policy: PolicyMode
) -> str | None:
    """The cause requiring an operator for this sink, or ``None`` if none does.

    ``DEGRADED`` raises under RECOMMEND (a degrading writer will not fix itself
    and nothing else is going to try) but is recorded only under AUTOMATE.

    ``FAILED`` under AUTOMATE waits for evidence that automatic recovery has
    already had its turn: the owning source back to ``HEALTHY`` while this sink
    is still failed means the recovery episode ran and did not bring the sink
    with it. A sink failed while its source is still down is mid-episode, not
    yet anyone's problem.
    """
    if sink.health is SinkHealth.HEALTHY:
        return None

    if policy is PolicyMode.RECOMMEND:
        return CAUSE_RECOMMEND_POLICY

    if sink.health is SinkHealth.FAILED and source_status is StreamStatus.HEALTHY:
        return CAUSE_SINK_MISSED_RECOVERY

    return None


def source_status_by_device(report: RuntimeReport) -> dict[str, StreamStatus]:
    """Stream status per device, for resolving a sink's owning source."""
    return {device.device_id: device.stream_status for device in report.devices}
