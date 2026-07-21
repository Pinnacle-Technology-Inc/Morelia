"""Managed Plot sink: bounded live browser presentation, not durable recording.

Purpose (gaps SINK-09/SINK-10; design doc section 6 "Plot")
-----------------------------------------------------------
Plot is the producer half of a *browser* live view. Morelia's own ``PlotSink`` is
GUI-oriented — ``PlotDisplay`` needs a Qt event loop in an interactive main
process, which this backend never has (Morelia runs inside a supervised
background watchdog). So this managed sink deliberately starts **no Qt**: it
decimates and batches samples in the collection worker and publishes bounded
batches to a browser data channel (a :class:`PlotTransport`), whence
``app/api/plot_stream.py`` fans them out over authenticated SSE.

Bounded, drop-oldest, never blocking
------------------------------------
The producer-side buffer never exceeds ``chunk_samples`` (it flushes when full),
and emission is throttled to ``max_display_rate`` batches/second — samples beyond
that rate are *dropped* (with an explicit counter), because this is a live view,
not a recording. A missing or disconnected transport is a **dropped consumer**,
not an error: publishing simply increments the drop counter and acquisition keeps
running. Disconnect/backpressure therefore surfaces as *this sink's own* per-sink
state (buffered / dropped), never as source or sibling-sink health.

Lifecycle protocol (open -> write_row/flush -> get_dict -> close)
----------------------------------------------------------------
Construction is side-effect free (SINK-21): ``__init__`` connects no transport and
starts no thread, so the parent watchdog can build/rebuild the descriptor safely.
The live transport is resolved **worker-side** at :meth:`open` — either an injected
live handle (in-process) or, across the DataFlow worker boundary, a *picklable*
``transport_factory`` the worker calls to reconnect. ``get_dict()`` returns the
reconstruction kwargs and — unlike Morelia's ``PlotSink.get_dict()``, which always
re-emits the default rate (SINK-10) — preserves the **configured**
``max_display_rate``. Plot carries no credential, so nothing is redacted.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

import structlog

_log = structlog.get_logger(__name__)

#: Wire schema version stamped on every published batch (kept in lockstep with
#: ``app.api.plot_stream.PLOT_SCHEMA_VERSION``; duplicated here so the worker-side
#: sink never imports the Flask endpoint module).
PLOT_SCHEMA_VERSION = "plot.samples.v1"

# Defaults mirror Morelia's PlotSink where it has a sensible one; kept local so
# this module imports no Morelia at construction time.
DEFAULT_CHUNK_SAMPLES = 100
DEFAULT_MAX_DISPLAY_RATE = 30.0

# Candidate packet channel attributes for the Morelia ``flush(timestamp, packet)``
# path (mirrors the CSV/Quest per-channel layout). Missing attributes are skipped
# so one map serves both Pod8206HR and Pod8401HR without a device import.
_PACKET_CHANNELS: tuple[str, ...] = (
    "ch0",
    "ch1",
    "ch2",
    "ch3",
    "ext0",
    "ext1",
    "ttl1",
    "ttl2",
    "ttl3",
    "ttl4",
)


@runtime_checkable
class PlotTransport(Protocol):
    """Minimal duck-typed publish surface a plot sink needs.

    Any object with a ``publish(batch: dict) -> object`` method qualifies (e.g.
    :class:`app.api.plot_stream.InProcessPlotTransport`). Keeping this a Protocol
    lets the sink stay free of any Flask/broker import.
    """

    def publish(self, batch: dict[str, Any]) -> Any:  # pragma: no cover - protocol
        ...


class PlotSinkError(Exception):
    """Base error for the managed plot sink; carries the offending ``sink_id``."""

    def __init__(self, sink_id: str | None, message: str) -> None:
        self.sink_id = sink_id
        super().__init__(message)


class ManagedPlotSink:
    """Bounded live-plot producer publishing decimated batches to a browser channel.

    Invariants:
    - Construction connects nothing and starts no thread (SINK-21).
    - Producer memory is bounded to ``chunk_samples``; emission is throttled to
      ``max_display_rate`` and excess is dropped with an explicit counter.
    - A missing/disconnected/failing transport is a dropped consumer, never an
      error, and never blocks acquisition.
    - ``get_dict()`` preserves the configured ``max_display_rate`` (SINK-10) and
      exposes no credential (Plot has none).
    """

    def __init__(
        self,
        *,
        dataflow_id: str,
        device_id: str | None = None,
        sink_id: str | None = None,
        session_id: int | None = None,
        schema_hash: str | None = None,
        chunk_samples: int | None = None,
        max_display_rate: float | None = None,
        channel_names: Sequence[str] | None = None,
        observe_on_scheduler: str | None = None,
        pod: object = None,
        transport: PlotTransport | None = None,
        transport_factory: Callable[[], PlotTransport | None] | None = None,
    ) -> None:
        # -- descriptor identity ----------------------------------------------
        self._dataflow_id = dataflow_id
        self._device_id = device_id
        self._sink_id = sink_id
        self._session_id = session_id
        self._schema_hash = schema_hash

        # -- presentation config (preserved verbatim for reconstruction) ------
        self._chunk_samples = (
            int(chunk_samples) if chunk_samples is not None else DEFAULT_CHUNK_SAMPLES
        )
        if self._chunk_samples < 1:
            raise PlotSinkError(sink_id, "chunk_samples must be a positive integer")
        self._max_display_rate = (
            float(max_display_rate)
            if max_display_rate is not None
            else DEFAULT_MAX_DISPLAY_RATE
        )
        if self._max_display_rate <= 0:
            raise PlotSinkError(sink_id, "max_display_rate must be a positive number")
        self._channel_names = list(channel_names) if channel_names else None
        self.observe_on_scheduler = observe_on_scheduler
        self._pod = pod

        # -- injected transport boundaries ------------------------------------
        self._transport = transport
        self._transport_factory = transport_factory

        # -- live state (populated by open) -----------------------------------
        self._buffer: list[list[float]] = []
        self._opened = False
        self._closed = False
        self._presentation_connected = False
        self._seq = 0
        self._emitted_batches = 0
        self._dropped_batches = 0
        self._last_emit_monotonic = 0.0

    # -- identity ----------------------------------------------------------

    @property
    def sink_id(self) -> str | None:
        return self._sink_id

    @property
    def opened(self) -> bool:
        return self._opened

    @property
    def _min_emit_interval(self) -> float:
        # Throttle to at most ``max_display_rate`` batches per second.
        return 1.0 / self._max_display_rate

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> ManagedPlotSink:
        """Resolve the transport worker-side; idempotent.

        A live ``transport`` wins; otherwise a picklable ``transport_factory`` (the
        cross-process reconnect path) is called. If neither yields a transport the
        sink opens anyway in *no-consumer* mode — every emit is a bounded drop, and
        acquisition is never blocked.
        """
        if self._opened:
            return self
        if self._closed:
            raise PlotSinkError(self._sink_id, "cannot reopen a closed ManagedPlotSink")

        if self._transport is None and self._transport_factory is not None:
            try:
                self._transport = self._transport_factory()
            except Exception as exc:  # noqa: BLE001 - a dead transport is a drop, not a failure
                self._transport = None
                _log.warning(
                    "plot transport factory failed — running with no live consumer",
                    component="managed_plot_sink",
                    sink_id=self._sink_id,
                    error_type=type(exc).__name__,
                )

        self._presentation_connected = self._transport is not None
        self._opened = True
        return self

    def __enter__(self) -> ManagedPlotSink:
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Flush a best-effort final batch and detach the transport. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._opened and self._buffer:
            self._emit_current()
        self._transport = None
        self._presentation_connected = False
        self._opened = False

    # -- writes ------------------------------------------------------------

    def write_row(self, row: Mapping[str, Any]) -> None:
        """Buffer one ``{channel: value}`` sample; emit a batch when full."""
        if not self._opened:
            self.open()
        channels = self._resolve_channels(row)
        sample = [_as_float(row.get(name)) for name in channels]
        self._append_sample(sample)

    def flush(self, *args: object) -> None:
        """No-arg: emit the partial buffer. ``(timestamp, packet)``: Morelia stream."""
        if not args:
            if self._opened and self._buffer:
                self._emit_current()
            return
        if len(args) != 2:
            raise TypeError("flush() expects no args or (timestamp, packet)")
        if not self._opened:
            self.open()
        _timestamp, packet = args
        channels = self._resolve_channels_from_packet(packet)
        sample = [_as_float(getattr(packet, name, None)) for name in channels]
        self._append_sample(sample)

    # -- batching / emission ----------------------------------------------

    def _append_sample(self, sample: list[float]) -> None:
        self._buffer.append(sample)
        if len(self._buffer) >= self._chunk_samples:
            self._emit_current()

    def _emit_current(self) -> None:
        """Emit the buffered chunk as one batch, throttled to the display rate.

        The buffer is always cleared (bounded memory). If the last emit was too
        recent for ``max_display_rate``, the chunk is dropped instead of published
        — the live view keeps only the freshest data, with an explicit counter.
        """
        if not self._buffer:
            return
        samples = self._buffer
        self._buffer = []

        now = time.monotonic()
        if self._emitted_batches and (now - self._last_emit_monotonic) < self._min_emit_interval:
            # Decimation: too soon for another frame at max_display_rate.
            self._dropped_batches += 1
            return

        batch = {
            "schema": PLOT_SCHEMA_VERSION,
            "session_id": self._session_id,
            "sink_id": self._sink_id,
            "device_id": self._device_id,
            "seq": self._seq,
            "timestamp": time.time(),
            "sample_rate": self._max_display_rate,
            "channels": list(self._channel_names or self._derive_channel_labels(samples)),
            "samples": samples,
        }
        if self._publish(batch):
            self._seq += 1
            self._emitted_batches += 1
            self._last_emit_monotonic = now
        else:
            self._dropped_batches += 1

    def _publish(self, batch: dict[str, Any]) -> bool:
        """Publish one batch; a missing/failing transport is a bounded drop."""
        transport = self._transport
        if transport is None:
            self._presentation_connected = False
            return False
        try:
            transport.publish(batch)
            self._presentation_connected = True
            return True
        except Exception as exc:  # noqa: BLE001 - disconnected consumer, not a source error
            self._presentation_connected = False
            _log.warning(
                "plot transport publish failed — dropping batch (live view only)",
                component="managed_plot_sink",
                sink_id=self._sink_id,
                error_type=type(exc).__name__,
            )
            return False

    # -- introspection (per-sink presentation state; never source health) --

    @property
    def presentation_connected(self) -> bool:
        return self._presentation_connected

    @property
    def dropped_batches(self) -> int:
        """Batches dropped by rate-decimation or a disconnected consumer."""
        return self._dropped_batches

    @property
    def emitted_batches(self) -> int:
        return self._emitted_batches

    @property
    def is_degraded(self) -> bool:
        """True while presentation is disconnected/backpressured (never source health).

        After :meth:`open`, ``presentation_connected`` reflects whether a live
        transport exists (and stays truthful as publishes succeed/fail); a missing
        or dropped consumer is degraded *presentation*, never source failure.
        """
        return self._opened and not self._presentation_connected

    def pending_count(self) -> int:
        """Samples buffered but not yet emitted (bounded by ``chunk_samples``)."""
        return len(self._buffer)

    def get_state(self) -> dict[str, Any]:
        """Per-sink presentation state for a :class:`SinkReport` (buffered/loss).

        This is *this sink's own* health axis — a disconnected browser shows up
        here as ``connected=False`` / ``dropped>0``, never as source failure.
        """
        return {
            "sink_id": self._sink_id,
            "sink_class": "plot",
            "connected": self._presentation_connected,
            "buffered": len(self._buffer),
            "dropped": self._dropped_batches,
            "emitted": self._emitted_batches,
        }

    def get_dict(self) -> dict[str, Any]:
        """Reconstruction kwargs.

        SINK-10 fix: emits the **configured** ``max_display_rate`` (Morelia's
        ``PlotSink.get_dict()`` always re-emits the default). Plot carries no
        credential, so nothing is redacted. The live transport handle is
        intentionally omitted — it is re-resolved worker-side at ``open()``.
        """
        return {
            "dataflow_id": self._dataflow_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "session_id": self._session_id,
            "schema_hash": self._schema_hash,
            "chunk_samples": self._chunk_samples,
            "max_display_rate": self._max_display_rate,
            "channel_names": list(self._channel_names) if self._channel_names else None,
            "observe_on_scheduler": self.observe_on_scheduler,
        }

    # -- internals ---------------------------------------------------------

    def _resolve_channels(self, row: Mapping[str, Any]) -> list[str]:
        if self._channel_names:
            return self._channel_names
        return [
            key
            for key in row.keys()
            if key not in ("time", "timestamp") and _is_number(row[key])
        ]

    def _resolve_channels_from_packet(self, packet: object) -> list[str]:
        if self._channel_names:
            return self._channel_names
        return [name for name in _PACKET_CHANNELS if _is_number(getattr(packet, name, None))]

    @staticmethod
    def _derive_channel_labels(samples: list[list[float]]) -> list[str]:
        width = len(samples[0]) if samples else 0
        return [f"ch{i}" for i in range(width)]


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_float(value: object) -> float:
    return float(value) if _is_number(value) else 0.0


__all__ = [
    "DEFAULT_CHUNK_SAMPLES",
    "DEFAULT_MAX_DISPLAY_RATE",
    "PLOT_SCHEMA_VERSION",
    "ManagedPlotSink",
    "PlotSinkError",
    "PlotTransport",
]
