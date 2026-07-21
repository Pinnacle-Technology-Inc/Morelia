"""Domain enumerations: the controlled vocabularies of the system.

Every state in the spec lives here exactly once, so the API, the database
layer, and the runtime host client all agree on the same set of legal values.
"""

from enum import StrEnum


class SessionStatus(StrEnum):
    """Session lifecycle: draft -> scheduled -> starting -> active -> ending -> completed."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    STARTING = "starting"
    ACTIVE = "active"
    ENDING = "ending"
    COMPLETED = "completed"


class HealthStatus(StrEnum):
    """Action-focused overall status of ``HealthState``.

    This class is to help with dividing session into different bucket on display
    (eg. Group all session that needs user action)
    """

    HEALTHY = "healthy"
    RECOVERING = "recovering"
    NEEDS_ACTION = "needs_action"
    UNKNOWN = "unknown"


class PolicyMode(StrEnum):
    """Recovery policy mode."""

    RECOMMEND = "recommend"
    AUTOMATE = "automate"


class StreamStatus(StrEnum):
    """Runtime host observation of a device stream."""

    HEALTHY = "healthy"
    SUSPECT = "suspect"
    UNHEALTHY = "unhealthy"


class CommsStatus(StrEnum):
    """The dataflow runtime host's OWN view of its link to the watchdog driver.
    """

    CURRENT = "current"
    DELAYED = "delayed"
    UNREACHABLE = "unreachable"
    STOPPED = "stopped"


class LinkStatus(StrEnum):
    """The control-plane's status report on whether it can reach a dataflow host.

    Computed from probe success + age of the newest event.
    """

    REACHABLE = "reachable"
    DELAYED = "delayed"
    UNREACHABLE = "unreachable"


class HealthState(StrEnum):
    """Operator-facing overall session health — the at-a-glance badge.

    The single cross-axis rollup produced by ``app.services.health_state.derive``
    from reachability (``LinkStatus``), content (``StreamStatus``), and
    lifecycle/intent (``RuntimePhase`` / ``OperationState``). Distinct from
    ``HealthStatus`` (the dashboard disposition vocabulary).
    """

    HEALTHY = "healthy"
    DELAYED = "delayed"
    UNREACHABLE = "unreachable"
    STOPPED = "stopped"
    RECOVERING = "recovering"
    FAILED = "failed"
    UNKNOWN = "unknown"


class IncidentStatus(StrEnum):
    """Operator-facing incident lifecycle."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class GapConfidence(StrEnum):
    """How confidently the control plane can describe a recovery gap."""

    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


class DeviceType(StrEnum):
    """Supported hardware device type keys."""

    UNKNOWN = "unknown"
    POD8206HR = "pod8206hr"
    POD8229 = "pod8229"
    POD8274D = "pod8274d"
    POD8401HR = "pod8401hr"
    POD8480SC = "pod8480sc"


class DeviceClaimState(StrEnum):
    """Control-plane pool state for a persisted physical device config."""

    FREE = "free"
    STARTING = "starting"
    CLAIMED = "claimed"


class SinkType(StrEnum):
    """Supported data sink type keys."""

    CSV = "csv"
    EDF = "edf"
    PVFS = "pvfs"
    INFLUX = "influx"
    QUEST = "quest"
    PLOT = "plot"


class SinkCategory(StrEnum):
    """Stable behavioral grouping for a sink type.

    Drives shared contract rules (e.g. which types may resolve a
    ``sink_location``) without each caller re-deriving them from the type.
    """

    FILE = "file"
    SERVICE = "service"
    PLOT = "plot"


class OperationScope(StrEnum):
    """The conflict domain an operation locks while active."""

    DATAFLOW = "dataflow"
    STREAM = "stream"


class OperationState(StrEnum):
    """Durable state machine for state-changing runtime operations."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class RuntimeOwnershipState(StrEnum):
    """Control-plane ownership state for a runtime host process."""

    STARTING = "starting"
    RUNNING = "running"
    ADOPTED = "adopted"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNCERTAIN = "uncertain"


class WatchdogProcessState(StrEnum):
    """Control-plane view of the currently active watchdog process for a
    runtime host. Distinct from ``RuntimeOwnershipState``: a runtime host can
    stay ``running`` across multiple watchdog-process respawns.
    """

    STARTING = "starting"
    RUNNING = "running"
    ADOPTED = "adopted"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"
    UNCERTAIN = "uncertain"


__all__ = [
    "CommsStatus",
    "DeviceClaimState",
    "DeviceType",
    "GapConfidence",
    "HealthState",
    "HealthStatus",
    "IncidentStatus",
    "LinkStatus",
    "OperationScope",
    "OperationState",
    "PolicyMode",
    "RuntimeOwnershipState",
    "SessionStatus",
    "SinkCategory",
    "SinkType",
    "StreamStatus",
    "WatchdogProcessState",
]
