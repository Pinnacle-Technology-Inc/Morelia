"""Managed Quest sink: bounded delivery replay over acknowledged QuestDB ILP/HTTP.

Delivery / replay model (gaps SINK-08/SINK-27; design doc section 6 "Service sinks")
------------------------------------------------------------------------------------
QuestDB ingests through the official ``questdb`` Sender in acknowledged HTTP
mode. The managed wrapper mirrors
:class:`~app.output.influx_sink.ManagedInfluxSink`; Quest has no credential or
token in this contract.

* **Initial availability is enforced** at :meth:`open` (start): the client is
  constructed and a non-destructive reachability check runs; a refused
  destination raises :class:`QuestUnavailableError` so session start fails
  atomically rather than treating availability as unknown-success (design doc:
  "If the deployment cannot perform its configured ... readiness check, start
  fails").
* **Post-start outage does not stop acquisition.** A write that fails after
  start marks the sink degraded, warns, and buffers the *raw* line-protocol
  payload to the separate bounded
  :class:`~app.watchdog_process.sink_delivery_outbox.SinkDeliveryOutbox` (never
  the telemetry outbox). Source acquisition and healthy sibling sinks continue.
* **Reconnect drains in order.** On a later write (or explicit :meth:`replay`)
  the sink re-checks reachability — rate-limited so retries never busy-loop —
  and drains pending outbox records for its key in insertion order,
  acknowledging each only after the destination accepts it. Direct delivery and
  replay share one stable idempotency identity per logical point, so a retry
  after an ambiguous outcome never writes a duplicate logical point (the outbox
  de-duplicates on the key and never acks before confirmed delivery).
* **Overflow is visible, permanent loss.** The outbox's age/byte bounds evict
  the oldest records into durable per-sink loss counters; :meth:`loss_report`
  surfaces the exact dropped record/byte counts and time range, and
  :attr:`is_degraded` stays true.

Lifecycle protocol (open -> write_row/flush -> get_dict -> close)
----------------------------------------------------------------
Construction is side-effect free (SINK-21): ``__init__`` imports no client,
opens no connection, and touches no outbox — so the parent watchdog can
build/rebuild the descriptor safely. The live client and the outbox handle exist
only after :meth:`open`, which must run in the DataFlow worker. ``get_dict()``
returns reconstruction kwargs (host/port/measurement/...); Quest carries no
secret, so there is nothing to redact.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from collections.abc import Callable, Mapping
from typing import Any

import structlog

from app.watchdog_process.sink_delivery_outbox import (
    SinkDeliveryOutbox,
    SinkLossReport,
    sink_delivery_key,
)

_log = structlog.get_logger(__name__)

# Defaults mirror Morelia's QuestSink constructor.
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9000
DEFAULT_MEASUREMENT = "default_measurement"

# Candidate packet channel attributes for the Morelia ``flush(timestamp, packet)``
# path (mirrors QuestSink's per-channel line layout). Missing attributes are
# skipped so one map serves both Pod8206HR and Pod8401HR without a device import.
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


class QuestSinkError(Exception):
    """Base error for the managed Quest sink; carries the offending ``sink_id``."""

    def __init__(self, sink_id: str | None, message: str) -> None:
        self.sink_id = sink_id
        super().__init__(message)


class QuestUnavailableError(QuestSinkError):
    """The destination failed its reachability check at start (fail-start contract)."""

    def __init__(self, sink_id: str | None, host: str, port: int, reason: str) -> None:
        self.host = host
        self.port = port
        super().__init__(
            sink_id,
            f"Quest sink {sink_id!r}: destination at {host!r}:{port} was not "
            f"reachable at start: {reason}",
        )


class _RealQuestClient:
    """Official QuestDB sender using acknowledged ILP/HTTP writes."""

    def __init__(self, *, host: str, port: int) -> None:
        from questdb.ingress import Protocol, Sender, TimestampNanos

        self._host = host
        self._port = port
        self._sender = Sender(Protocol.Http, host, port, auto_flush=False)
        self._timestamp_nanos = TimestampNanos
        self._established = False

    def ready(self) -> bool:
        try:
            if not self._established:
                self._sender.establish()
                self._established = True
            return True
        except Exception:
            return False

    def validate_schema(self, table: str) -> None:
        """Create the expected table if absent and reject incompatible metadata."""
        quoted = _quote_identifier(table)
        self._exec(
            f"CREATE TABLE IF NOT EXISTS {quoted} ("
            "timestamp TIMESTAMP, acquisition_id SYMBOL, sink_id SYMBOL, "
            "channel SYMBOL, name SYMBOL, value DOUBLE) "
            "TIMESTAMP(timestamp) PARTITION BY DAY WAL "
            "DEDUP UPSERT KEYS(timestamp, acquisition_id, sink_id, channel)"
        )
        tables = self._exec(
            "SELECT dedup FROM tables() WHERE table_name = " + _quote_literal(table)
        )
        if not tables or tables[0] != [True]:
            raise ValueError(f"Quest table {table!r} must have deduplication enabled")
        columns = self._exec(
            'SELECT "column", designated, upsertKey FROM table_columns('
            + _quote_literal(table)
            + ")"
        )
        designated = {row[0] for row in columns if len(row) >= 3 and row[1] is True}
        upsert = {row[0] for row in columns if len(row) >= 3 and row[2] is True}
        expected = {"timestamp", "acquisition_id", "sink_id", "channel"}
        if designated != {"timestamp"} or upsert != expected:
            raise ValueError(
                f"Quest table {table!r} requires designated timestamp and "
                f"UPSERT keys {sorted(expected)!r}"
            )

    def _exec(self, query: str) -> list[list[Any]]:
        url = f"http://{self._host}:{self._port}/exec?{urlencode({'query': query})}"
        with urlopen(url, timeout=5.0) as response:  # noqa: S310 - configured destination
            body = json.loads(response.read().decode("utf-8"))
        dataset = body.get("dataset", [])
        if not isinstance(dataset, list):
            raise ValueError("Quest metadata response has no dataset")
        return dataset

    def write(self, payload: bytes) -> None:
        rows = json.loads(payload.decode("utf-8"))
        if not isinstance(rows, list) or not rows:
            return
        buffer = self._sender.new_buffer()
        for row in rows:
            buffer.row(
                row["table"],
                symbols=row["symbols"],
                columns={"value": float(row["value"])},
                at=self._timestamp_nanos(int(row["timestamp"])),
            )
        self._sender.flush(buffer, transactional=True)

    def close(self) -> None:
        self._sender.close(flush=False)
        self._established = False


def _default_client_factory(*, host: str, port: int, measurement: str) -> _RealQuestClient:
    return _RealQuestClient(host=host, port=port)


class ManagedQuestSink:
    """Quest (QuestDB ILP) sink with bounded delivery replay.

    Invariants:
    - Construction opens nothing and imports no ``questdb`` client (SINK-21).
    - A refused destination at :meth:`open` fails start; a refused destination
      after start degrades the sink and buffers raw payloads for ordered replay
      (SINK-27), never blocking acquisition.
    - Direct delivery and replay share one stable idempotency key per logical
      point, so retries never duplicate a logical point.
    - Quest carries no credential/token; nothing secret is stored, logged, or
      serialized.
    """

    def __init__(
        self,
        *,
        dataflow_id: str,
        device_id: str | None = None,
        sink_id: str | None = None,
        logical_sink_id: str | None = None,
        acquisition_id: str | None = None,
        schema_hash: str | None = None,
        session_id: int | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        measurement: str = DEFAULT_MEASUREMENT,
        observe_on_scheduler: str | None = None,
        buffer_max_age_seconds: float | None = None,
        buffer_max_bytes: int | None = None,
        pod: object = None,
        client_factory: Callable[..., Any] | None = None,
        delivery_outbox: SinkDeliveryOutbox | None = None,
        outbox_factory: Callable[[], SinkDeliveryOutbox] | None = None,
        on_sink_error: Callable[[dict[str, Any]], None] | None = None,
        reconnect_min_interval_seconds: float = 1.0,
    ) -> None:
        # -- descriptor state (no live handle) --------------------------------
        self._dataflow_id = dataflow_id
        self._device_id = device_id
        self._sink_id = sink_id
        self._logical_sink_id = logical_sink_id
        self._acquisition_id = acquisition_id
        self._schema_hash = schema_hash
        self._session_id = session_id
        self._host = host
        self._port = int(port)
        self._measurement = measurement
        self.observe_on_scheduler = observe_on_scheduler
        self._buffer_max_age_seconds = buffer_max_age_seconds
        self._buffer_max_bytes = buffer_max_bytes
        self._pod = pod

        # -- injected boundaries ----------------------------------------------
        self._client_factory = client_factory or _default_client_factory
        self._injected_outbox = delivery_outbox
        self._outbox_factory = outbox_factory
        self._on_sink_error = on_sink_error
        self._reconnect_min_interval = float(reconnect_min_interval_seconds)

        # -- live state (populated by open) -----------------------------------
        self._client: Any = None
        self._outbox: SinkDeliveryOutbox | None = None
        self._owns_outbox = False
        self._opened = False
        self._closed = False
        self._connected = False
        self._delivery_degraded = False
        self._seq = 0
        self._last_reconnect_attempt = 0.0
        self._last_error: str | None = None

    # -- identity ----------------------------------------------------------

    @property
    def sink_key(self) -> str:
        """Stable per-acquisition/per-sink outbox key (see ``sink_delivery_key``)."""
        acquisition = self._acquisition_id or self._dataflow_id
        logical = self._logical_sink_id or self._sink_id or "quest"
        return sink_delivery_key(acquisition_id=acquisition, logical_sink_id=logical)

    @property
    def _device_name(self) -> str:
        name = getattr(self._pod, "device_name", None)
        return str(name or self._device_id or self._sink_id or "device")

    # -- lifecycle ---------------------------------------------------------

    @property
    def opened(self) -> bool:
        return self._opened

    def open(self) -> ManagedQuestSink:
        """Construct the client and enforce initial availability.

        Worker-side, idempotent. A destination that fails the reachability check
        raises :class:`QuestUnavailableError` so start fails atomically.
        """
        if self._opened:
            return self
        if self._closed:
            raise QuestSinkError(self._sink_id, "cannot reopen a closed ManagedQuestSink")

        self._client = self._client_factory(
            host=self._host,
            port=self._port,
            measurement=self._measurement,
        )

        self._outbox = self._resolve_outbox()
        self._opened = True

        if not self._client_ready():
            # Fail start atomically: tear down what we built.
            self._teardown_client()
            self._opened = False
            raise QuestUnavailableError(
                self._sink_id, self._host, self._port, "reachability check failed at start"
            )
        self._connected = True
        validate_schema = getattr(self._client, "validate_schema", None)
        if callable(validate_schema):
            try:
                validate_schema(self._measurement)
            except Exception as exc:
                self._teardown_client()
                self._opened = False
                raise QuestUnavailableError(
                    self._sink_id,
                    self._host,
                    self._port,
                    f"schema validation failed: {exc}",
                ) from exc
        # A previous incarnation may have left pending records — drain them now.
        self._replay_pending()
        return self

    def __enter__(self) -> ManagedQuestSink:
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Clean stop. Flushes a best-effort replay, then releases the client.

        Idempotent; a never-opened descriptor closes as a no-op. Pending outbox
        records are intentionally retained (delayed, not lost) for a later
        incarnation; an owned outbox handle is closed.
        """
        if self._closed:
            return
        self._closed = True
        if self._opened and self._connected:
            # Best-effort final drain; failures leave records durably queued.
            try:
                self._replay_pending()
            except Exception:  # noqa: BLE001 - close must not raise
                pass
        self._teardown_client()
        if self._owns_outbox and self._outbox is not None:
            with _suppress():
                self._outbox.close()
        self._opened = False

    # -- writes ------------------------------------------------------------

    def write_row(self, row: Mapping[str, Any]) -> None:
        """Deliver one ``{channel: value}`` row (plus optional ``time``/``timestamp``)."""
        if not self._opened:
            self.open()
        timestamp = _extract_timestamp(row)
        fields = {
            k: v
            for k, v in row.items()
            if k not in ("time", "timestamp") and _is_number(v)
        }
        self._deliver(self._encode(timestamp, fields))

    def flush(self, *args: object) -> None:
        """No-arg: attempt a replay drain. ``(timestamp, packet)``: Morelia stream."""
        if not args:
            if self._opened:
                self._replay_pending()
            return
        if len(args) != 2:
            raise TypeError("flush() expects no args or (timestamp, packet)")
        if not self._opened:
            self.open()
        timestamp, packet = args
        fields = {
            channel: getattr(packet, channel)
            for channel in _PACKET_CHANNELS
            if _is_number(getattr(packet, channel, None))
        }
        self._deliver(self._encode(int(timestamp), fields))

    # -- delivery / replay -------------------------------------------------

    def replay(self) -> None:
        """Public hook to attempt reconnect + ordered drain of pending records."""
        if self._opened:
            self._replay_pending()

    def _deliver(self, payload: bytes) -> None:
        """Deliver one raw line-protocol payload with a stable idempotency identity.

        Healthy path: write directly. On failure (or while already degraded) the
        payload is buffered to the outbox under a stable key and an ordered replay
        is attempted; the sink never blocks acquisition and never acks before the
        destination confirms. The outbox age bound uses the buffering wall-clock
        time (its ``record_time`` default), so a sample's own logical acquisition
        timestamp — which may be far in the past — never counts against the buffer
        retention window.
        """
        if not payload:
            return
        self._seq += 1
        assert self._outbox is not None
        record = self._outbox.enqueue_new(
            self.sink_key,
            payload,
            sample_count=max(1, payload.count(b"\n") + 1),
        )
        if record is None:
            self._delivery_degraded = True
            self._report_sink_error(state="degraded")
            return
        self._replay_pending()

    def _replay_pending(self) -> None:
        """Reconnect (rate-limited) and drain pending records for this key in order.

        Records are acked only after the destination accepts them; the first write
        failure stops the drain so ordering and at-least-once (never duplicate-ack)
        semantics hold.
        """
        assert self._outbox is not None
        was_degraded = self._delivery_degraded
        if self._outbox.count_pending(self.sink_key) == 0 and not was_degraded:
            return
        if not self._ensure_connected():
            return

        acked: list[str] = []
        for record in self._outbox.pending(self.sink_key):
            try:
                self._client.write(record.payload)
            except Exception as exc:  # noqa: BLE001
                self._mark_degraded(exc)
                break
            acked.append(record.idempotency_key)
        if acked:
            self._outbox.ack_many(acked)
        if self._outbox.count_pending(self.sink_key) == 0:
            self._delivery_degraded = False
            self._last_error = None
            if was_degraded:
                self._report_sink_error(state="recovered")

    def _ensure_connected(self) -> bool:
        """Return True if connected; otherwise attempt a rate-limited reconnect.

        The reconnect interval floors retry frequency so a persistent outage never
        busy-loops (design doc: "retries must not busy-loop").
        """
        if self._connected and not self._delivery_degraded:
            return True
        now = time.monotonic()
        if now - self._last_reconnect_attempt < self._reconnect_min_interval:
            return False
        self._last_reconnect_attempt = now
        if self._client_ready():
            self._connected = True
            return True
        self._connected = False
        return False

    def _mark_degraded(self, exc: BaseException) -> None:
        self._connected = False
        self._delivery_degraded = True
        self._last_error = _redact_message(exc)
        _log.warning(
            "quest delivery degraded — buffering raw samples for replay",
            component="managed_quest_sink",
            sink_id=self._sink_id,
            sink_key=self.sink_key,
            host=self._host,
            port=self._port,
            error_type=type(exc).__name__,
        )
        self._report_sink_error(state="degraded")

    def bind_error_callback(
        self, callback: Callable[[dict[str, Any]], None] | None
    ) -> None:
        """Bind a worker-local health reporter after Morelia reconstruction."""
        self._on_sink_error = callback

    def _report_sink_error(self, *, state: str) -> None:
        """Emit a packet-23-shaped, redacted destination-failure report if wired.

        Never carries samples. Packet 26 supplies ``on_sink_error`` to route this
        onto the report path; absent that hook it is a no-op.
        """
        if self._on_sink_error is None:
            return
        loss = self.loss_report()
        with _suppress():
            self._on_sink_error(
                {
                    "source_id": self._device_id,
                    "sink_id": self._sink_id,
                    "sink_class": "quest",
                    "failure_kind": "sink_write",
                    "exception_type": None,
                    "message": (self._last_error or "")[:500],
                    "state": state,
                    "last_success_seq": self._seq - 1,
                    "timestamp_ns": time.time_ns(),
                    "buffered_samples": self.pending_count(),
                    "buffered_bytes": (
                        self._outbox.total_bytes(self.sink_key) if self._outbox is not None else 0
                    ),
                    "sample_loss": loss.lost_samples,
                    "byte_loss": loss.lost_bytes,
                }
            )

    # -- introspection -----------------------------------------------------

    @property
    def delivery_degraded(self) -> bool:
        """True while the destination is currently failing (samples buffering)."""
        return self._delivery_degraded

    @property
    def is_degraded(self) -> bool:
        """True on current outage OR any permanent (evicted) loss for this key."""
        if self._delivery_degraded:
            return True
        if self._outbox is None:
            return False
        return self._outbox.is_degraded(self.sink_key)

    def loss_report(self) -> SinkLossReport:
        """Durable permanent-loss evidence for this sink's key (zeros if none)."""
        if self._outbox is None:
            return SinkLossReport(self.sink_key, 0, 0, 0, None, None)
        return self._outbox.loss_report(self.sink_key)

    def pending_count(self) -> int:
        """Records still buffered (delayed, not lost) for this key."""
        if self._outbox is None:
            return 0
        return self._outbox.count_pending(self.sink_key)

    def get_dict(self) -> dict[str, Any]:
        """Reconstruction kwargs. Quest carries no secret, so nothing is redacted."""
        return {
            "dataflow_id": self._dataflow_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "logical_sink_id": self._logical_sink_id,
            "acquisition_id": self._acquisition_id,
            "schema_hash": self._schema_hash,
            "session_id": self._session_id,
            "host": self._host,
            "port": self._port,
            "measurement": self._measurement,
            "observe_on_scheduler": self.observe_on_scheduler,
            "buffer_max_age_seconds": self._buffer_max_age_seconds,
            "buffer_max_bytes": self._buffer_max_bytes,
            # The descriptor is reconstructed in a spawned DataFlow worker.
            # Preserve the picklable factory; the live SQLite handle remains
            # worker-owned and is deliberately never serialized.
            "outbox_factory": self._outbox_factory,
        }

    # -- internals ---------------------------------------------------------

    def _resolve_outbox(self) -> SinkDeliveryOutbox:
        if self._injected_outbox is not None:
            return self._injected_outbox
        if self._outbox_factory is not None:
            self._owns_outbox = True
            return self._outbox_factory()
        raise QuestSinkError(
            self._sink_id,
            "no delivery outbox available: inject delivery_outbox or outbox_factory "
            "(the worker owns the per-dataflow SinkDeliveryOutbox)",
        )

    def _client_ready(self) -> bool:
        ready = getattr(self._client, "ready", None)
        if not callable(ready):
            return True
        try:
            return bool(ready())
        except Exception:  # noqa: BLE001
            return False

    def _teardown_client(self) -> None:
        client = self._client
        self._client = None
        self._connected = False
        if client is not None:
            with _suppress():
                client.close()

    def _encode(self, timestamp: int, fields: Mapping[str, Any]) -> bytes:
        """Encode one packet as per-channel QuestDB line-protocol (Morelia layout).

        One line per channel: ``{measurement},channel={c},name={device} value={v} {ts}``.
        """
        return _encode_quest_payload(
            table=self._measurement,
            acquisition_id=self._acquisition_id or self._dataflow_id,
            sink_id=self._logical_sink_id or self._sink_id or "quest",
            device_name=self._device_name,
            timestamp=timestamp,
            fields=fields,
        )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _encode_quest_payload(
    *,
    table: str,
    acquisition_id: str,
    sink_id: str,
    device_name: str,
    timestamp: int,
    fields: Mapping[str, Any],
) -> bytes:
    rows = [
        {
            "table": table,
            "symbols": {
                "acquisition_id": acquisition_id,
                "sink_id": sink_id,
                "channel": channel,
                "name": device_name,
            },
            "value": float(value),
            "timestamp": int(timestamp),
        }
        for channel, value in fields.items()
        if value is not None
    ]
    return json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class _suppress:
    """Tiny ``contextlib.suppress(Exception)`` without importing at module top."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, *_rest: object) -> bool:
        return exc_type is not None and issubclass(exc_type, Exception)  # type: ignore[arg-type]


def _redact_message(exc: BaseException) -> str:
    """Bounded exception text for logs/reports; never carries samples."""
    return f"{type(exc).__name__}: {str(exc)[:400]}"[:500]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _extract_timestamp(row: Mapping[str, Any]) -> int:
    for key in ("timestamp", "time"):
        if key in row and _is_number(row[key]):
            return int(row[key])
    return time.time_ns()


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MEASUREMENT",
    "DEFAULT_PORT",
    "ManagedQuestSink",
    "QuestSinkError",
    "QuestUnavailableError",
]
