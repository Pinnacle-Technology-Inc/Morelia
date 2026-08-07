"""Managed Influx sink: worker-side secret resolution + bounded delivery replay.

Ownership / safety boundary (gaps SINK-07, SINK-27; design doc section 4 "Secrets",
section 6 "Service sinks / Influx")
-------------------------------------------------------------------------------
Morelia's raw ``InfluxSink`` takes the API token as a constructor argument and
returns it verbatim from ``get_dict()`` — so copying its snapshot into a manifest,
report, or log would leak the credential (gap SINK-07, a release blocker). This
managed wrapper never carries the token value across a process, a serializer, or a
log. It stores only ``api_token_env`` — the *name* of an environment variable —
and resolves the actual token in the worker, immediately before constructing the
client, through the injected ``secret_resolver`` (default: ``os.environ.get``). A
missing/empty variable fails construction with the variable NAME but never its
value, and ``get_dict()`` (plus :func:`redact_mapping`) denylists any field named
``api_token`` / ``token`` / ``password`` / ``secret``.

Delivery / replay model (gap SINK-27; design doc section 6 "Service sinks")
--------------------------------------------------------------------------
* **Initial availability is enforced** at :meth:`open` (start): the client is
  constructed and a non-destructive readiness check runs; a refused destination
  raises :class:`InfluxUnavailableError` so session start fails atomically rather
  than treating availability as unknown-success (design doc: "If the deployment
  cannot perform its configured ... readiness check, start fails").
* **Post-start outage does not stop acquisition.** A write that fails after start
  marks the sink degraded, warns, and buffers the *raw* line-protocol payload to
  the separate bounded :class:`~app.watchdog_process.sink_delivery_outbox.SinkDeliveryOutbox`
  (never the telemetry outbox). Source acquisition and healthy sibling sinks
  continue.
* **Reconnect drains in order.** On a later write (or explicit :meth:`replay`) the
  sink re-checks readiness — rate-limited so retries never busy-loop — and drains
  pending outbox records for its key in insertion order, acknowledging each only
  after the destination accepts it. Direct delivery and replay share one stable
  idempotency identity per logical point, so a retry after an ambiguous outcome
  never writes a duplicate logical point (the outbox de-duplicates on the key and
  never acks before confirmed delivery).
* **Overflow is visible, permanent loss.** The outbox's age/byte bounds evict the
  oldest records into durable per-sink loss counters; :meth:`loss_report` surfaces
  the exact dropped record/byte counts and time range, and :attr:`is_degraded`
  stays true.

Lifecycle protocol (open -> write_row/flush -> get_dict -> close)
----------------------------------------------------------------
Construction is side-effect free (SINK-21): ``__init__`` imports no
``influxdb_client``, opens no socket, resolves no secret, and touches no outbox —
so the parent watchdog can build/rebuild the descriptor safely. The live client,
the resolved token, and the outbox handle exist only after :meth:`open`, which
must run in the DataFlow worker. ``get_dict()`` returns reconstruction kwargs that
carry ``api_token_env`` (the reference) but never the token.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import structlog

from app.watchdog_process.sink_delivery_outbox import (
    SinkDeliveryOutbox,
    SinkLossReport,
    sink_delivery_key,
)

_log = structlog.get_logger(__name__)

# Defaults mirror Morelia's InfluxSink constructor (a real token is never a
# default — ``api_token_env`` is required and resolved worker-side).
DEFAULT_URL = "http://localhost:8086"
DEFAULT_ORG = "default-org"
DEFAULT_BUCKET = "influx_dump"
DEFAULT_MEASUREMENT = "default-measurement"

# Any config/report/log field named one of these must be omitted (SINK-07).
_SECRET_FIELD_NAMES = frozenset({"api_token", "token", "password", "secret"})

# Candidate packet channel attributes for the Morelia ``flush(timestamp, packet)``
# path (mirrors InfluxSink's per-channel line layout). Missing attributes are
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


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *mapping* with any secret-named field omitted (SINK-07).

    Case-insensitive denylist of ``api_token`` / ``token`` / ``password`` /
    ``secret``. Reusable by any report/log serializer that handles an Influx
    config snapshot so a credential can never ride along by accident.
    """
    return {k: v for k, v in mapping.items() if str(k).lower() not in _SECRET_FIELD_NAMES}


class InfluxSinkError(Exception):
    """Base error for the managed Influx sink; carries the offending ``sink_id``."""

    def __init__(self, sink_id: str | None, message: str) -> None:
        self.sink_id = sink_id
        super().__init__(message)


class InfluxCredentialError(InfluxSinkError):
    """The credential environment variable is unset or empty.

    Names the *variable* (``env_var``) so preflight/construction is diagnosable,
    but never carries a resolved value (SINK-07).
    """

    def __init__(self, sink_id: str | None, env_var: str) -> None:
        self.env_var = env_var
        super().__init__(
            sink_id,
            f"Influx sink {sink_id!r}: credential environment variable {env_var!r} "
            "is not set or is empty; set it in the worker environment "
            "(the token value is never stored in config, manifest, logs, or reports)",
        )


class InfluxUnavailableError(InfluxSinkError):
    """The destination failed its readiness check at start (fail-start contract)."""

    def __init__(self, sink_id: str | None, url: str, reason: str) -> None:
        self.url = url
        super().__init__(
            sink_id,
            f"Influx sink {sink_id!r}: destination at {url!r} was not ready at start: {reason}",
        )


class _RealInfluxClient:
    """Thin adapter over ``influxdb_client`` implementing the write-client contract.

    Lazily imports ``influxdb_client`` so the module-level import surface of this
    file stays free of the optional dependency (the factory's packet-08 probe
    already ran). Exposes ``ready`` / ``write`` / ``close`` — the only surface the
    managed sink drives — so tests can substitute a fake with no network.
    """

    def __init__(self, *, url: str, token: str, org: str, bucket: str) -> None:
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.write_api import SYNCHRONOUS

        self._org = org
        self._bucket = bucket
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._writer = self._client.write_api(write_options=SYNCHRONOUS)

    def ready(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def write(self, payload: bytes) -> None:
        # Raises on failure; the managed sink treats any exception as not-delivered.
        self._writer.write(bucket=self._bucket, org=self._org, record=payload)

    def close(self) -> None:
        try:
            self._writer.close()
        finally:
            self._client.close()


def _default_client_factory(
    *, url: str, token: str, org: str, bucket: str, measurement: str
) -> _RealInfluxClient:
    return _RealInfluxClient(url=url, token=token, org=org, bucket=bucket)


class ManagedInfluxSink:
    """Influx sink with worker-side secret resolution and bounded delivery replay.

    Invariants:
    - Construction opens nothing and imports no ``influxdb_client`` (SINK-21).
    - The token value is never stored on the instance, serialized, or logged; only
      ``api_token_env`` (the variable name) is (SINK-07).
    - A refused destination at :meth:`open` fails start; a refused destination
      after start degrades the sink and buffers raw payloads for ordered replay
      (SINK-27), never blocking acquisition.
    - Direct delivery and replay share one stable idempotency key per logical
      point, so retries never duplicate a logical point.
    """

    def __init__(
        self,
        *,
        api_token_env: str,
        dataflow_id: str,
        device_id: str | None = None,
        sink_id: str | None = None,
        logical_sink_id: str | None = None,
        acquisition_id: str | None = None,
        schema_hash: str | None = None,
        session_id: int | None = None,
        url: str = DEFAULT_URL,
        org: str = DEFAULT_ORG,
        bucket: str = DEFAULT_BUCKET,
        measurement: str = DEFAULT_MEASUREMENT,
        observe_on_scheduler: str | None = None,
        buffer_max_age_seconds: float | None = None,
        buffer_max_bytes: int | None = None,
        pod: object = None,
        secret_resolver: Callable[[str], str | None] | None = None,
        client_factory: Callable[..., Any] | None = None,
        delivery_outbox: SinkDeliveryOutbox | None = None,
        outbox_factory: Callable[[], SinkDeliveryOutbox] | None = None,
        on_sink_error: Callable[[dict[str, Any]], None] | None = None,
        reconnect_min_interval_seconds: float = 1.0,
    ) -> None:
        if not api_token_env:
            raise ValueError("Influx sink requires a non-empty api_token_env (variable name)")

        # -- descriptor state (no secret, no live handle) ----------------------
        self._api_token_env = api_token_env
        self._dataflow_id = dataflow_id
        self._device_id = device_id
        self._sink_id = sink_id
        self._logical_sink_id = logical_sink_id
        self._acquisition_id = acquisition_id
        self._schema_hash = schema_hash
        self._session_id = session_id
        self._url = url
        self._org = org
        self._bucket = bucket
        self._measurement = measurement
        self.observe_on_scheduler = observe_on_scheduler
        self._buffer_max_age_seconds = buffer_max_age_seconds
        self._buffer_max_bytes = buffer_max_bytes
        self._pod = pod

        # -- injected boundaries ----------------------------------------------
        self._secret_resolver = secret_resolver
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
        logical = self._logical_sink_id or self._sink_id or "influx"
        return sink_delivery_key(acquisition_id=acquisition, logical_sink_id=logical)

    @property
    def _device_name(self) -> str:
        name = getattr(self._pod, "device_name", None)
        return str(name or self._device_id or self._sink_id or "device")

    # -- lifecycle ---------------------------------------------------------

    @property
    def opened(self) -> bool:
        return self._opened

    def open(self) -> ManagedInfluxSink:
        """Resolve the secret, construct the client, enforce initial availability.

        Worker-side, idempotent. Resolves ``api_token_env`` through the injected
        ``secret_resolver`` (default ``os.environ.get``); a missing/empty value
        raises :class:`InfluxCredentialError` naming the variable but not a value.
        A destination that fails the readiness check raises
        :class:`InfluxUnavailableError` so start fails atomically.
        """
        if self._opened:
            return self
        if self._closed:
            raise InfluxSinkError(self._sink_id, "cannot reopen a closed ManagedInfluxSink")

        token = self._resolve_token()
        # Token lives only in this local + inside the client; never on self.
        self._client = self._client_factory(
            url=self._url,
            token=token,
            org=self._org,
            bucket=self._bucket,
            measurement=self._measurement,
        )
        del token

        self._outbox = self._resolve_outbox()
        self._opened = True

        if not self._client_ready():
            # Fail start atomically: tear down what we built.
            self._teardown_client()
            self._opened = False
            raise InfluxUnavailableError(
                self._sink_id, self._url, "readiness check failed at start"
            )
        self._connected = True
        # A previous incarnation may have left pending records — drain them now.
        self._replay_pending()
        return self

    def __enter__(self) -> ManagedInfluxSink:
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
            "influx delivery degraded — buffering raw samples for replay",
            component="managed_influx_sink",
            sink_id=self._sink_id,
            sink_key=self.sink_key,
            url=self._url,
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

        Never carries samples or secrets. Packet 26 supplies ``on_sink_error`` to
        route this onto the report path; absent that hook it is a no-op.
        """
        if self._on_sink_error is None:
            return
        loss = self.loss_report()
        with _suppress():
            self._on_sink_error(
                {
                    "source_id": self._device_id,
                    "sink_id": self._sink_id,
                    "sink_class": "influx",
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
        """Reconstruction kwargs — carries ``api_token_env`` but never the token.

        Runs the result through :func:`redact_mapping` defensively so a secret can
        never appear even if a field were added by mistake (SINK-07).
        """
        snapshot = {
            "api_token_env": self._api_token_env,
            "dataflow_id": self._dataflow_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "logical_sink_id": self._logical_sink_id,
            "acquisition_id": self._acquisition_id,
            "schema_hash": self._schema_hash,
            "session_id": self._session_id,
            "url": self._url,
            "org": self._org,
            "bucket": self._bucket,
            "measurement": self._measurement,
            "observe_on_scheduler": self.observe_on_scheduler,
            "buffer_max_age_seconds": self._buffer_max_age_seconds,
            "buffer_max_bytes": self._buffer_max_bytes,
            # The descriptor is reconstructed in a spawned DataFlow worker.
            # Preserve the picklable factory; the live SQLite handle remains
            # worker-owned and is deliberately never serialized.
            "outbox_factory": self._outbox_factory,
        }
        return redact_mapping(snapshot)

    # -- internals ---------------------------------------------------------

    def _resolve_token(self) -> str:
        resolver = self._secret_resolver
        if resolver is None:
            import os

            resolver = os.environ.get
        try:
            value = resolver(self._api_token_env)
        except Exception as exc:  # noqa: BLE001 - resolver failure must stay redacted
            raise InfluxCredentialError(self._sink_id, self._api_token_env) from exc
        if not value:
            raise InfluxCredentialError(self._sink_id, self._api_token_env)
        return value

    def _resolve_outbox(self) -> SinkDeliveryOutbox:
        if self._injected_outbox is not None:
            return self._injected_outbox
        if self._outbox_factory is not None:
            self._owns_outbox = True
            return self._outbox_factory()
        raise InfluxSinkError(
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
        """Encode one packet as per-channel InfluxDB line-protocol (Morelia layout).

        One line per channel: ``{measurement},channel={c},name={device} value={v} {ts}``.
        """
        name = self._device_name
        lines = [
            f"{self._measurement},channel={channel},name={name} value={float(value)} {int(timestamp)}"
            for channel, value in fields.items()
            if value is not None
        ]
        return "\n".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


class _suppress:
    """Tiny ``contextlib.suppress(Exception)`` without importing at module top."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, *_rest: object) -> bool:
        return exc_type is not None and issubclass(exc_type, Exception)  # type: ignore[arg-type]


def _redact_message(exc: BaseException) -> str:
    """Bounded exception text for logs/reports; never carries samples or secrets."""
    return f"{type(exc).__name__}: {str(exc)[:400]}"[:500]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _extract_timestamp(row: Mapping[str, Any]) -> int:
    for key in ("timestamp", "time"):
        if key in row and _is_number(row[key]):
            return int(row[key])
    return time.time_ns()


__all__ = [
    "DEFAULT_BUCKET",
    "DEFAULT_MEASUREMENT",
    "DEFAULT_ORG",
    "DEFAULT_URL",
    "InfluxCredentialError",
    "InfluxSinkError",
    "InfluxUnavailableError",
    "ManagedInfluxSink",
    "redact_mapping",
]
