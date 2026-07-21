"""Serializable messages shared by Flask and watchdog processes."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from structlog.contextvars import bind_contextvars, clear_contextvars

WATCHDOG_PROTOCOL_VERSION = "1"
WATCHDOG_COMMAND_PATH = "/api/v1/commands"
WATCHDOG_COMMANDS = frozenset(
    {
        "start",
        "stop",
        "restart-all-streams",
        "reconnect",
        "restart",
        "reset-stream",
    }
)


@dataclass(frozen=True, slots=True)
class CorrelationEnvelope:
    """Identifiers required to correlate work across the process boundary.

    ``watchdog_id`` names the watchdog *process instance* the command targets
    (packet 07: command fencing) — it may change under the same
    ``runtime_id`` after a respawn, so a stale value must be rejected rather
    than silently applied (see ``LifecycleSafetyGate.accept``). ``runtime_id``
    is the owning runtime host ownership row; it is optional because the
    legacy single-watchdog dispatch path (no per-dataflow runtime host) has
    no runtime ownership record to attribute it to.

    ``dataflow_id`` is the stable identity of one source→sink combination and
    is the only correlation key that persists across all three layers
    (control plane → runtime host → watchdog). ``session_id`` deliberately
    does NOT appear here: it is a control-plane-only concept (multiple
    sessions may watch the same dataflow), so it never crosses the wire. The
    control plane still tags its own logs with ``session_id`` from the request
    route (see ``app.request_logging``), and maps a report back to a session
    via ``dataflow_id``.
    """

    request_id: str
    dataflow_id: str
    command_id: str
    watchdog_id: str
    recovery_id: str | None = None
    runtime_id: str | None = None

    _REQUIRED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "request_id",
            "dataflow_id",
            "command_id",
            "watchdog_id",
        }
    )
    _OPTIONAL_FIELDS: ClassVar[frozenset[str]] = frozenset({"recovery_id", "runtime_id"})

    def __post_init__(self) -> None:
        for field_name in self._REQUIRED_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")

        if self.recovery_id is not None and (
            not isinstance(self.recovery_id, str) or not self.recovery_id
        ):
            raise ValueError("recovery_id must be a non-empty string when provided")

        if self.runtime_id is not None and (
            not isinstance(self.runtime_id, str) or not self.runtime_id
        ):
            raise ValueError("runtime_id must be a non-empty string when provided")

    def to_dict(self) -> dict[str, str]:
        """Return the wire representation, omitting identifiers that do not apply."""
        values = {
            "request_id": self.request_id,
            "dataflow_id": self.dataflow_id,
            "command_id": self.command_id,
            "watchdog_id": self.watchdog_id,
        }
        if self.recovery_id is not None:
            values["recovery_id"] = self.recovery_id
        if self.runtime_id is not None:
            values["runtime_id"] = self.runtime_id
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "CorrelationEnvelope":
        """Validate and construct correlation data received by a watchdog."""
        allowed_fields = cls._REQUIRED_FIELDS | cls._OPTIONAL_FIELDS
        unknown_fields = set(values) - allowed_fields
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"unknown correlation fields: {names}")

        missing_fields = cls._REQUIRED_FIELDS - set(values)
        if missing_fields:
            names = ", ".join(sorted(missing_fields))
            raise ValueError(f"missing correlation fields: {names}")

        return cls(
            request_id=values["request_id"],  # type: ignore[arg-type]
            dataflow_id=values["dataflow_id"],  # type: ignore[arg-type]
            command_id=values["command_id"],  # type: ignore[arg-type]
            watchdog_id=values["watchdog_id"],  # type: ignore[arg-type]
            recovery_id=values.get("recovery_id"),  # type: ignore[arg-type]
            runtime_id=values.get("runtime_id"),  # type: ignore[arg-type]
        )

    def bind(self) -> None:
        """Replace any stale worker context with this command's identifiers."""
        clear_contextvars()
        bind_contextvars(**self.to_dict())


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    """A guarded watchdog command plus its correlation identifiers.

    ``target_device_id`` names a single device→sink stream within the dataflow.
    Recovery commands (reconnect/restart/reset-stream) act on ONE stream at a
    time (a StreamWatcher per device), so the control plane addresses the
    specific device rather than fanning out across the whole dataflow. It is
    omitted (None) for whole-dataflow commands like start/stop. The envelope
    only checks the field's *shape*; whether a given command requires it — and
    whether the device exists — is the host's business rule (it owns the
    manifest), enforced in LifecycleSafetyGate.
    """

    command: str
    correlation: CorrelationEnvelope
    target_device_id: str | None = None

    def __post_init__(self) -> None:
        if self.command not in WATCHDOG_COMMANDS:
            raise ValueError(f"unsupported watchdog command: {self.command!r}")
        if self.target_device_id is not None and (
            not isinstance(self.target_device_id, str) or not self.target_device_id
        ):
            raise ValueError("target_device_id must be a non-empty string when provided")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable command message."""
        values: dict[str, object] = {
            "protocol_version": WATCHDOG_PROTOCOL_VERSION,
            "command": self.command,
            "correlation": self.correlation.to_dict(),
        }
        if self.target_device_id is not None:
            values["target_device_id"] = self.target_device_id
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "CommandEnvelope":
        """Validate and construct a command received by a watchdog."""
        unknown_fields = set(values) - {
            "protocol_version",
            "command",
            "correlation",
            "target_device_id",
        }
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"unknown command fields: {names}")

        protocol_version = values.get("protocol_version")
        if protocol_version != WATCHDOG_PROTOCOL_VERSION:
            raise ValueError(f"unsupported watchdog protocol version: {protocol_version!r}")

        command = values.get("command")
        correlation = values.get("correlation")
        if not isinstance(command, str):
            raise ValueError("command must be a string")
        if not isinstance(correlation, Mapping):
            raise ValueError("correlation must be an object")

        return cls(
            command=command,
            correlation=CorrelationEnvelope.from_dict(correlation),
            target_device_id=values.get("target_device_id"),  # type: ignore[arg-type]
        )
