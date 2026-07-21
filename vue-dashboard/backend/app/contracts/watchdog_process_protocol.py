"""Direct watchdog-process telemetry ingest contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

WATCHDOG_TELEMETRY_PROTOCOL_VERSION = "1"

_STRING_FIELDS: tuple[str, ...] = (
    "report_id",
    "dataflow_id",
    "runtime_id",
    "watchdog_id",
    "manifest_hash",
    "event_type",
)


@dataclass(frozen=True, slots=True)
class WatchdogTelemetryEnvelope:
    """One durable telemetry report sent directly by a watchdog process.

    ``report_id`` is the idempotency key — see ``BackendEventRepository.append``.
    ``payload`` is opaque to this contract; ``event_type`` names its shape for
    downstream consumers, mirroring how ``RuntimeReport``'s ``devices`` are
    flattened into ``BackendEvent.payload`` under a fixed key.
    """

    report_id: str
    dataflow_id: str
    runtime_id: str
    watchdog_id: str
    manifest_hash: str
    event_type: str
    payload: Mapping[str, Any]

    _REQUIRED: ClassVar[frozenset[str]] = frozenset({*_STRING_FIELDS, "payload"})

    def __post_init__(self) -> None:
        for field_name in _STRING_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "dataflow_id": self.dataflow_id,
            "runtime_id": self.runtime_id,
            "watchdog_id": self.watchdog_id,
            "manifest_hash": self.manifest_hash,
            "event_type": self.event_type,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> WatchdogTelemetryEnvelope:
        """Validate and construct a direct-ingest envelope. Strict: no unknown fields."""
        unknown = set(values) - cls._REQUIRED
        if unknown:
            raise ValueError(
                f"unknown watchdog telemetry fields: {', '.join(sorted(unknown))}"
            )
        missing = cls._REQUIRED - set(values)
        if missing:
            raise ValueError(
                f"missing watchdog telemetry fields: {', '.join(sorted(missing))}"
            )

        payload = values["payload"]
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")

        return cls(
            report_id=values["report_id"],  # type: ignore[arg-type]
            dataflow_id=values["dataflow_id"],  # type: ignore[arg-type]
            runtime_id=values["runtime_id"],  # type: ignore[arg-type]
            watchdog_id=values["watchdog_id"],  # type: ignore[arg-type]
            manifest_hash=values["manifest_hash"],  # type: ignore[arg-type]
            event_type=values["event_type"],  # type: ignore[arg-type]
            payload=dict(payload),
        )


__all__ = ["WATCHDOG_TELEMETRY_PROTOCOL_VERSION", "WatchdogTelemetryEnvelope"]
