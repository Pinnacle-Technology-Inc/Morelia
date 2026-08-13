"""The runtime boundary: one interface, many drivers.

A *driver* is the thing that actually runs one owned dataflow. The concrete
implementation is ``MoreliaRuntime`` (app/runtime_child/morelia.py), which wraps
the real Watchdog.

The Dataflow Runtime Host (Stage 2.2) holds a ``RuntimeControlDriver`` and never
imports the concrete class directly. That is the whole point of an interface:
the host's lifecycle code (preflight -> start -> stop -> close) is identical
regardless of the driver behind it. Swap the driver, keep the host.

Reports flow the *other* way. A driver does not return its observations from
``start()``; collection is long-lived, so there is nothing to return yet. Instead
the driver pushes a ``RuntimeReport`` to a callback whenever something happens.
That callback is supplied when the driver is constructed — the "report callback"
half of the 2.1 contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol

from app.domain.enums import CommsStatus, StreamStatus


class RuntimePhase(StrEnum):
    """Where a Dataflow is in its lifecycle 
    (idle -> preflight -> running -> stopped -> closed).
    """

    IDLE = "idle"  # constructed, nothing started yet
    PREFLIGHT = "preflight"  # devices/sinks validated, not yet collecting
    RUNNING = "running"  # collecting
    STOPPED = "stopped"  # collection halted cleanly, resources still open
    CLOSED = "closed"  # resources released; terminal


@dataclass(frozen=True, slots=True)
class DeviceReport:
    """One device's stream health within a dataflow.

    A dataflow owns many device->sink relationships, each driven on its own
    watchdog thread, so a single dataflow report carries *many* of these.
    """

    device_id: str
    stream_status: StreamStatus

    _ALLOWED: ClassVar[frozenset[str]] = frozenset({"device_id", "stream_status"})

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id:
            raise ValueError("device_id must be a non-empty string")
        # Coerce/validate the wire value into the enum so callers cannot smuggle
        # an unknown status string past the boundary.
        if not isinstance(self.stream_status, StreamStatus):
            raise ValueError("stream_status must be a StreamStatus")

    def to_dict(self) -> dict[str, str]:
        return {"device_id": self.device_id, "stream_status": self.stream_status.value}

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> DeviceReport:
        unknown = set(values) - cls._ALLOWED
        if unknown:
            raise ValueError(f"unknown device report fields: {', '.join(sorted(unknown))}")
        return cls(
            device_id=values["device_id"],  # type: ignore[arg-type]
            stream_status=StreamStatus(values["stream_status"]),
        )


# Bounds on the redacted diagnostic strings a sink report may carry. A report
# is durable telemetry, not a log: it must stay small and never smuggle raw
# samples or secret/config values across the process boundary.
_MAX_SINK_MESSAGE_CHARS = 500
_MAX_SINK_LABEL_CHARS = 120


class SinkHealth(StrEnum):
    """Per-sink health — a SEPARATE axis from source/stream health.

    Keyed by ``(source_id, sink_id)``, never derived from the device stream.
    A ``FAILED`` sink never implies its source stream is ``UNHEALTHY``, and a
    ``HEALTHY`` stream never overrides a ``DEGRADED`` sink. This separation is
    the whole point of gaps SINK-08/SINK-19/SINK-23: silent output loss must
    stay visible even while acquisition looks healthy, and one failing sink
    must never restart or obscure a healthy sibling.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


class SinkDeliveryState(StrEnum):
    """How far this sink's output has progressed toward its destination.

    Packet 10's delivery vocabulary. Independent of ``SinkHealth``: a sink can
    be ``DEGRADED`` health while still ``DELIVERING`` buffered samples, or
    ``HEALTHY`` health having just ``DELIVERED`` a replayed backlog.
    """

    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    DEGRADED = "degraded"
    FAILED = "failed"


class SinkFinalization(StrEnum):
    """File-sink finalization stage (EDF/PVFS segment merge and publish).

    ``NONE`` for sinks with no finalization concept (e.g. service/plot sinks),
    so the field is meaningful for every sink type rather than absent.
    """

    NONE = "none"
    PENDING = "pending"
    FINALIZING = "finalizing"
    MERGED = "merged"
    FAILED = "failed"


def _sink_index(value: object, field_name: str) -> int:
    """Validate a non-negative int marker (bool rejected — it is an int subclass)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _sink_label(value: object, field_name: str) -> str:
    """Validate a bounded, non-empty diagnostic label; reject oversized values."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > _MAX_SINK_LABEL_CHARS:
        raise ValueError(f"{field_name} must be <= {_MAX_SINK_LABEL_CHARS} chars")
    return value


@dataclass(frozen=True, slots=True)
class SinkReport:
    """One sink's health and delivery state within a dataflow report.

    A dataflow report carries source/stream health (``DeviceReport``) and, on a
    strictly separate axis, per-sink state (this). Sinks are keyed by stable
    ``(source_id, sink_id)`` identity so a failing sink is attributed to exactly
    one sink and never masquerades as source health (gaps SINK-08/SINK-19/
    SINK-23). ``source_id`` is the owning device/source; ``sink_id`` is the
    manifest ``SinkConfig.sink_id``; ``sink_class`` names the concrete sink
    (e.g. ``"csv"`` / ``"influx"``).

    Six independent axes are kept apart, never collapsed into one status:
      * health        — ``health`` (SinkHealth: healthy/degraded/failed)
      * delivery      — ``delivery`` (SinkDeliveryState: pending..failed)
      * buffering     — ``buffered_samples`` / ``buffered_bytes``
      * loss          — ``sample_loss`` / ``byte_loss`` (durable, monotonic)
      * component     — ``component`` (writer subprocess / service client state)
      * finalization  — ``finalization`` (SinkFinalization: EDF/PVFS merge stage)

    ``sequence`` and ``state_timestamp_ns`` are per-sink monotonic ordering
    markers, independent of the enclosing ``RuntimeReport.sequence``. Diagnostics
    are bounded and redacted: ``message`` <= 500 chars, no secrets, no raw
    samples. Every field is expressible from a Morelia sink-error event
    (packet 23): ``source_id`` / ``sink_id`` / ``sink_class`` / ``failure_kind``
    (vocab ``sink_write``) / ``exception_type`` / ``message`` / ``last_success_seq``,
    with the Morelia ``state`` (terminal/degraded) mapping onto ``health``.
    """

    sink_id: str
    source_id: str
    sink_class: str
    health: SinkHealth
    delivery: SinkDeliveryState
    sequence: int
    state_timestamp_ns: int
    buffered_samples: int = 0
    buffered_bytes: int = 0
    sample_loss: int = 0
    byte_loss: int = 0
    component: str | None = None
    finalization: SinkFinalization | None = None
    failure_kind: str | None = None
    exception_type: str | None = None
    message: str | None = None
    last_success_seq: int | None = None

    _REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {
            "sink_id",
            "source_id",
            "sink_class",
            "health",
            "delivery",
            "sequence",
            "state_timestamp_ns",
        }
    )
    # Counters have a defined default (0) and are always emitted, but are still
    # accepted as optional on decode so a producer may omit a zero counter.
    _OPTIONAL: ClassVar[frozenset[str]] = frozenset(
        {
            "buffered_samples",
            "buffered_bytes",
            "sample_loss",
            "byte_loss",
            "component",
            "finalization",
            "failure_kind",
            "exception_type",
            "message",
            "last_success_seq",
        }
    )

    def __post_init__(self) -> None:
        for field_name in ("sink_id", "source_id", "sink_class"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if len(self.sink_class) > _MAX_SINK_LABEL_CHARS:
            raise ValueError(f"sink_class must be <= {_MAX_SINK_LABEL_CHARS} chars")
        if not isinstance(self.health, SinkHealth):
            raise ValueError("health must be a SinkHealth")
        if not isinstance(self.delivery, SinkDeliveryState):
            raise ValueError("delivery must be a SinkDeliveryState")
        _sink_index(self.sequence, "sequence")
        _sink_index(self.state_timestamp_ns, "state_timestamp_ns")
        for field_name in ("buffered_samples", "buffered_bytes", "sample_loss", "byte_loss"):
            _sink_index(getattr(self, field_name), field_name)
        for field_name in ("component", "failure_kind", "exception_type"):
            value = getattr(self, field_name)
            if value is not None:
                _sink_label(value, field_name)
        if self.finalization is not None and not isinstance(self.finalization, SinkFinalization):
            raise ValueError("finalization must be a SinkFinalization")
        if self.message is not None:
            if not isinstance(self.message, str):
                raise ValueError("message must be a string when provided")
            if len(self.message) > _MAX_SINK_MESSAGE_CHARS:
                raise ValueError(f"message must be <= {_MAX_SINK_MESSAGE_CHARS} chars")
        if self.last_success_seq is not None:
            _sink_index(self.last_success_seq, "last_success_seq")

    def to_dict(self) -> dict[str, object]:
        values: dict[str, object] = {
            "sink_id": self.sink_id,
            "source_id": self.source_id,
            "sink_class": self.sink_class,
            "health": self.health.value,
            "delivery": self.delivery.value,
            "sequence": self.sequence,
            "state_timestamp_ns": self.state_timestamp_ns,
            "buffered_samples": self.buffered_samples,
            "buffered_bytes": self.buffered_bytes,
            "sample_loss": self.sample_loss,
            "byte_loss": self.byte_loss,
        }
        if self.component is not None:
            values["component"] = self.component
        if self.finalization is not None:
            values["finalization"] = self.finalization.value
        if self.failure_kind is not None:
            values["failure_kind"] = self.failure_kind
        if self.exception_type is not None:
            values["exception_type"] = self.exception_type
        if self.message is not None:
            values["message"] = self.message
        if self.last_success_seq is not None:
            values["last_success_seq"] = self.last_success_seq
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> SinkReport:
        unknown = set(values) - (cls._REQUIRED | cls._OPTIONAL)
        if unknown:
            raise ValueError(f"unknown sink report fields: {', '.join(sorted(unknown))}")
        missing = cls._REQUIRED - set(values)
        if missing:
            raise ValueError(f"missing sink report fields: {', '.join(sorted(missing))}")

        finalization = values.get("finalization")
        return cls(
            sink_id=values["sink_id"],  # type: ignore[arg-type]
            source_id=values["source_id"],  # type: ignore[arg-type]
            sink_class=values["sink_class"],  # type: ignore[arg-type]
            health=SinkHealth(values["health"]),
            delivery=SinkDeliveryState(values["delivery"]),
            sequence=values["sequence"],  # type: ignore[arg-type]
            state_timestamp_ns=values["state_timestamp_ns"],  # type: ignore[arg-type]
            buffered_samples=values.get("buffered_samples", 0),  # type: ignore[arg-type]
            buffered_bytes=values.get("buffered_bytes", 0),  # type: ignore[arg-type]
            sample_loss=values.get("sample_loss", 0),  # type: ignore[arg-type]
            byte_loss=values.get("byte_loss", 0),  # type: ignore[arg-type]
            component=values.get("component"),  # type: ignore[arg-type]
            finalization=(
                SinkFinalization(finalization) if finalization is not None else None
            ),
            failure_kind=values.get("failure_kind"),  # type: ignore[arg-type]
            exception_type=values.get("exception_type"),  # type: ignore[arg-type]
            message=values.get("message"),  # type: ignore[arg-type]
            last_success_seq=values.get("last_success_seq"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class RuntimeReport:
    """A Morelia-shaped observation emitted by a driver.

    Deliberately carries ``sequence`` (a monotonic counter) and NOT a wall-clock
    timestamp: a watchdog's clock is process-relative and meaningless across a
    restart. The control plane stamps authoritative UTC when it receives the
    report (architecture doc, Phase 7). ``recovery_id`` is present only on
    reports that belong to a recovery episode, mirroring CorrelationEnvelope's
    "omit instead of send null" rule.
    """

    dataflow_id: str
    phase: RuntimePhase
    comms: CommsStatus
    devices: tuple[DeviceReport, ...]
    sequence: int
    recovery_id: str | None = None
    diagnostics: Mapping[str, object] | None = None
    sinks: tuple[SinkReport, ...] = ()

    _REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"dataflow_id", "phase", "comms", "devices", "sequence"}
    )
    # ``sinks`` is optional and defaults to (): a report predating the per-sink
    # contract decodes cleanly (prior shape translated to zero sinks), while an
    # OLD decoder receiving a report WITH ``sinks`` rejects it as an unknown
    # field — an explicit rejection, never a partial/ambiguous decode.
    _OPTIONAL: ClassVar[frozenset[str]] = frozenset({"recovery_id", "diagnostics", "sinks"})

    def __post_init__(self) -> None:
        if not isinstance(self.dataflow_id, str) or not self.dataflow_id:
            raise ValueError("dataflow_id must be a non-empty string")
        if not isinstance(self.phase, RuntimePhase):
            raise ValueError("phase must be a RuntimePhase")
        if not isinstance(self.comms, CommsStatus):
            raise ValueError("comms must be a CommsStatus")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            raise ValueError("sequence must be an int")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.recovery_id is not None and (
            not isinstance(self.recovery_id, str) or not self.recovery_id
        ):
            raise ValueError("recovery_id must be a non-empty string when provided")
        if self.diagnostics is not None and not isinstance(self.diagnostics, Mapping):
            raise ValueError("diagnostics must be an object when provided")
        seen_sink_identities: set[tuple[str, str]] = set()
        for sink in self.sinks:
            if not isinstance(sink, SinkReport):
                raise ValueError("sinks must be SinkReport instances")
            # Per-sink attribution (SINK-23): identity is unique within a report
            # so one sink's state can never be conflated with a sibling's.
            identity = (sink.source_id, sink.sink_id)
            if identity in seen_sink_identities:
                raise ValueError(
                    f"duplicate sink identity in report: "
                    f"source={sink.source_id!r} sink={sink.sink_id!r}"
                )
            seen_sink_identities.add(identity)

    def to_dict(self) -> dict[str, object]:
        values: dict[str, object] = {
            "dataflow_id": self.dataflow_id,
            "phase": self.phase.value,
            "comms": self.comms.value,
            "devices": [device.to_dict() for device in self.devices],
            "sequence": self.sequence,
        }
        if self.recovery_id is not None:
            values["recovery_id"] = self.recovery_id
        if self.diagnostics is not None:
            values["diagnostics"] = dict(self.diagnostics)
        # Per-sink state rides a SEPARATE key from ``devices`` (source health)
        # and is omitted entirely when there are no sinks — same "omit instead
        # of send null/empty" discipline as ``recovery_id``.
        if self.sinks:
            values["sinks"] = [sink.to_dict() for sink in self.sinks]
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> RuntimeReport:
        unknown = set(values) - (cls._REQUIRED | cls._OPTIONAL)
        if unknown:
            raise ValueError(f"unknown runtime report fields: {', '.join(sorted(unknown))}")
        missing = cls._REQUIRED - set(values)
        if missing:
            raise ValueError(f"missing runtime report fields: {', '.join(sorted(missing))}")

        devices = values["devices"]
        if not isinstance(devices, (list, tuple)):
            raise ValueError("devices must be a list")

        sinks_raw = values.get("sinks", ())
        if not isinstance(sinks_raw, (list, tuple)):
            raise ValueError("sinks must be a list")

        return cls(
            dataflow_id=values["dataflow_id"],  # type: ignore[arg-type]
            phase=RuntimePhase(values["phase"]),
            comms=CommsStatus(values["comms"]),
            devices=tuple(DeviceReport.from_dict(device) for device in devices),
            sequence=values["sequence"],  # type: ignore[arg-type]
            recovery_id=values.get("recovery_id"),  # type: ignore[arg-type]
            diagnostics=values.get("diagnostics"),  # type: ignore[arg-type]
            sinks=tuple(SinkReport.from_dict(sink) for sink in sinks_raw),
        )


# A driver pushes each observation here. The host supplies the callback at
# construction so reports can be forwarded to the control plane.
ReportCallback = Callable[[RuntimeReport], None]


class RuntimeControlDriver(Protocol):
    """The lifecycle every driver must honor: four phase calls + one recovery call.

    Ordering mirrors the real Morelia sequence (architecture doc, lines 70-76):
    preflight validates devices/sinks, start begins collection, stop halts it,
    close releases resources. ``close`` must be safe to call in cleanup even if
    an earlier step failed — it is the host's guaranteed teardown hook.

    ``recover`` is the report-and-wait recovery hook (spec line 122). In the
    target design the watchdog does NOT self-heal: it detects, reports
    suspect/unhealthy, and waits. The control plane then *commands* recovery,
    which lands here. Recovery is per-stream — it names ONE ``device_id`` (one
    StreamWatcher), not the whole dataflow — and carries the ``recovery_id`` that
    rides every report in the episode (spec line 128). The three wire commands
    reconnect / restart / reset-stream are escalating intensities of this one
    verb; the Morelia driver distinguishes them.
    """

    @property
    def phase(self) -> RuntimePhase: ...

    def preflight(self) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def recover(self, recovery_id: str, device_id: str) -> None: ...
