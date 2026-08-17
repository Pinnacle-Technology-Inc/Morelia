"""Derive the operator-facing overall health state — the at-a-glance badge.

This module holds the **only cross-axis, whole-system status rollup** in the
pipeline (see ``docs/stage7/packet-7.5-health-state-classifier.md``). Every other
status summary upstream is a single, orthogonal axis computed at the layer that
owns the information:

- ``RuntimePhase`` — the runtime driver's lifecycle (idle→preflight→running→…)
- ``CommsStatus`` on the wire — the host↔watchdog-driver link
- ``LinkStatus`` — the control-plane↔host reachability, computed by the poller (7.4)

``derive`` fuses reachability (``link_status``), content (``stream_agg``), and
lifecycle/intent (``phase`` / ``op_state`` / ``recovery_active``) into one
``HealthState`` via a fixed precedence ladder. It is pure and total: every input
combination returns a defined state and it never raises.

Reachability is taken ONLY from ``link_status``, never from a report's
``CommsStatus``. They are different axes (plane↔host vs host↔watchdog) that
disagree precisely when the host is alive but unreachable from the plane, and an
unreachable host cannot self-report its own unreachability — so sourcing
reachability from a report would be both redundant and wrong.

``derive`` returns ONLY the rolled-up ``overall`` value. The rollup is lossy by
design (a single enum cannot show two axes at once), so the composing status API
surfaces this badge alongside the raw axes (``link_status``, ``stream_agg``,
``phase``) rather than forcing consumers to reconstruct them.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.domain.enums import (
    HealthState,
    HealthStatus,
    LinkStatus,
    OperationState,
    StreamStatus,
)
from app.runtime_child.driver import DeviceReport, RuntimePhase

# Worst-of ordering for the per-device stream rollup. Higher = worse.
_STREAM_RANK: dict[StreamStatus, int] = {
    StreamStatus.HEALTHY: 0,
    StreamStatus.SUSPECT: 1,
    StreamStatus.UNHEALTHY: 2,
}


def aggregate_streams(devices: Iterable[DeviceReport]) -> StreamStatus:
    """Collapse N per-device stream statuses into one session-level value.

    Worst-of rollup: a single ``unhealthy`` device surfaces rather than hiding
    behind healthy peers — the safety-first choice for a data-collection system
    where losing one device's recording matters. An empty set is vacuously
    ``healthy`` (no bad streams). The per-device detail is NOT discarded here;
    it persists in the event payload (7.2) for drill-down and per-stream
    recovery.
    """
    worst = StreamStatus.HEALTHY
    for device in devices:
        if _STREAM_RANK[device.stream_status] > _STREAM_RANK[worst]:
            worst = device.stream_status
    return worst


def derive(
    *,
    link_status: LinkStatus,
    stream_agg: StreamStatus,
    phase: RuntimePhase,
    op_state: OperationState | None,
    recovery_active: bool,
) -> HealthState:
    """Roll the three status axes into one operator-facing ``HealthState``.

    Precedence ladder (first match wins). Governing principle: reachability
    gates content (an unreachable host's last report is stale and
    untrustworthy); within reachable, a durable operation failure outranks a
    live recovery, which outranks mild staleness.

    1. unreachable link                          -> UNREACHABLE
    2. failed operation                          -> FAILED
    3. stopped/closed phase                      -> STOPPED
    4. recovery in flight                        -> RECOVERING
    5. confirmed-unhealthy stream                -> FAILED
    6. delayed link                              -> DELAYED
    7. reachable + running + healthy/suspect     -> HEALTHY
    8. anything else (idle/preflight/stopping)   -> UNKNOWN

    ``op_state == uncertain`` deliberately does NOT drive the badge: it is an
    operation-resolution concern (surfaced via the operations API; blocks risky
    commands) and letting it set the badge would make health flap on every
    interrupted command. ``suspect`` folds into ``healthy`` — an in-window
    suspect report is not operator-facing (architecture plan lines 75-77).
    """
    if link_status is LinkStatus.UNREACHABLE:
        return HealthState.UNREACHABLE
    if op_state is OperationState.FAILED:
        return HealthState.FAILED
    if phase in (RuntimePhase.STOPPED, RuntimePhase.CLOSED):
        return HealthState.STOPPED
    if recovery_active:
        return HealthState.RECOVERING
    if stream_agg is StreamStatus.UNHEALTHY:
        return HealthState.FAILED
    if link_status is LinkStatus.DELAYED:
        return HealthState.DELAYED
    if (
        link_status is LinkStatus.REACHABLE
        and phase is RuntimePhase.RUNNING
        and stream_agg in (StreamStatus.HEALTHY, StreamStatus.SUSPECT)
    ):
        return HealthState.HEALTHY
    return HealthState.UNKNOWN


# The lossy fold from the 7-state backend rollup to the 4-bucket dashboard
# disposition. A dict (not a function body) so the totality test catches any
# future HealthState value that is added without a mapping.
_DISPOSITION: dict[HealthState, HealthStatus] = {
    HealthState.HEALTHY: HealthStatus.HEALTHY,
    HealthState.STOPPED: HealthStatus.HEALTHY,  # clean halt — nothing to act on
    HealthState.RECOVERING: HealthStatus.RECOVERING,
    HealthState.DELAYED: HealthStatus.NEEDS_ACTION,  # surface staleness (derive() rung 6)
    HealthState.UNREACHABLE: HealthStatus.NEEDS_ACTION,
    HealthState.FAILED: HealthStatus.NEEDS_ACTION,
    HealthState.UNKNOWN: HealthStatus.UNKNOWN,
}


def to_disposition(health_state: HealthState) -> HealthStatus:
    """Project the backend ``HealthState`` onto the dashboard's 4 buckets.

    The single, tested place the two health vocabularies are bridged, so they
    cannot drift. The fold is deliberately lossy: ``delayed`` / ``unreachable`` /
    ``failed`` all collapse to ``needs_action`` (operator should worry), and a
    clean ``stopped`` collapses to ``healthy`` (no concern). Consumers that need
    the lost detail read the un-projected ``HealthState`` (and the raw axes)
    surfaced alongside it.

    ``delayed -> needs_action`` (rather than ``healthy``) keeps this consistent
    with derive()'s comms-first choice to surface staleness instead of hiding it.
    """
    return _DISPOSITION[health_state]
