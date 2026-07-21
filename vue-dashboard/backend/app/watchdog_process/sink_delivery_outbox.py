"""Local SQLite delivery outbox for raw service-sink (Influx/Quest) samples.

This is a *separate* store from ``app.watchdog_process.outbox.WatchdogOutbox``
and must never be conflated with it. ``WatchdogOutbox`` persists bounded
``WatchdogTelemetryEnvelope`` reports (device status/diagnostics) that the
control plane ingests; it holds no raw measurement payloads and repository
logging rules forbid raw samples in it. A service sink whose destination
(InfluxDB / QuestDB) is unavailable after start must instead buffer its
*raw, replayable* write payloads somewhere durable so a later reconnect can
drain them in order. That is what this module is for.

Why a distinct outbox (see gap SINK-27 / the "Requested remote-sample
recovery" contradiction in ``docs/all-sink-support-design-and-gap-audit.md``):
mixing raw samples into the telemetry outbox would blend retention, replay,
privacy, and loss semantics, and telemetry rows still cannot reconstruct an
Influx/Quest write. Samples still present in *this* outbox are delayed, not
lost, and are replayed after reconnect. Samples evicted from it (by the age
bound, the per-sink byte bound, or the global disk cap) are **permanently
lost** and must never be described as retrievable — the durable loss counters
here are the only surviving evidence of them.

Durability / identity model:
- Records are keyed by a stable *acquisition/sink key* (see
  ``sink_delivery_key``): one durable service sink on one source. Records for
  a key replay in insertion order (``id ASC``).
- ``idempotency_key`` is UNIQUE. Enqueuing the same key twice is a no-op
  (returns ``False``) so a retried enqueue after a crash mid-write does not
  duplicate a still-pending record.
- ``ack`` removes a record only after the destination has accepted it, so a
  flush loop can crash between "sent" and "acked" and at worst redeliver.
- Bounds (age, per-sink bytes, global disk cap) evict the *oldest* records and
  atomically fold their exact bytes/samples/time-range into durable per-sink
  loss counters. Eviction never blocks a new enqueue — acquisition is never
  silently stalled; the cost of overflow is permanent, visible loss.

Like ``WatchdogOutbox`` this is deliberately independent of the Flask app's
SQLAlchemy engine: the watchdog process is not a Flask process. It opens its
own plain ``sqlite3`` connection against a file local to the watchdog instance
and never touches ``app.database``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from uuid import uuid4
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.config import get_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sink_delivery_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sink_key TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload BLOB NOT NULL,
    byte_size INTEGER NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    record_time REAL NOT NULL,
    enqueued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_sink_delivery_records_sink
    ON sink_delivery_records (sink_key, id);

CREATE TABLE IF NOT EXISTS sink_delivery_loss (
    sink_key TEXT PRIMARY KEY,
    lost_records INTEGER NOT NULL DEFAULT 0,
    lost_bytes INTEGER NOT NULL DEFAULT 0,
    lost_samples INTEGER NOT NULL DEFAULT 0,
    lost_time_start REAL,
    lost_time_end REAL,
    updated_at TEXT
);
"""


@dataclass(frozen=True, slots=True)
class SinkDeliveryRecord:
    """One buffered raw service-sink write, decoded from the outbox.

    ``record_id`` is the outbox's own local autoincrement key (insertion
    order). ``idempotency_key`` is the caller-supplied cross-retry key the
    outbox de-duplicates on.
    """

    record_id: int
    sink_key: str
    idempotency_key: str
    payload: bytes
    byte_size: int
    sample_count: int
    record_time: float
    enqueued_at: str


@dataclass(frozen=True, slots=True)
class SinkLossReport:
    """Durable, permanent-loss evidence for one sink key.

    A non-zero ``lost_records`` is the durable *degraded*/permanent-loss
    signal. ``lost_time_start``/``lost_time_end`` bound the wall-clock range of
    the evicted (permanently lost) samples; both are ``None`` when nothing has
    been lost.
    """

    sink_key: str
    lost_records: int
    lost_bytes: int
    lost_samples: int
    lost_time_start: float | None
    lost_time_end: float | None

    @property
    def degraded(self) -> bool:
        return self.lost_records > 0


def sink_delivery_key(*, acquisition_id: str, logical_sink_id: str) -> str:
    """Build the stable per-acquisition/per-sink key for a delivery outbox.

    One durable service sink (``logical_sink_id``, the identity minted by the
    output-lifecycle allocator) writing for one source acquisition
    (``acquisition_id``). The pair is the delivery bound unit — bytes and age
    are enforced per key, and loss counters accrue per key. Pure string
    arithmetic; safe with no Flask app context.
    """
    return f"{acquisition_id}::{logical_sink_id}"


def default_sink_delivery_outbox_path(outbox_dir: str | Path, dataflow_id: str) -> Path:
    """Compute the stable per-dataflow sink-delivery outbox file path.

    Named by ``watchdog_id`` (and suffixed ``-sink-delivery``) so a respawned
    watchdog process never reopens the delivery buffer of the instance it
    replaced, and so it can never collide with that instance's telemetry
    outbox file (``{dataflow_id}-sink-delivery.sqlite3``). Pure path arithmetic — no
    filesystem access and no Flask app context required.
    """
    return Path(outbox_dir) / f"{dataflow_id}-sink-delivery.sqlite3"


class SinkDeliveryOutbox:
    """Durable, bounded buffer of raw service-sink writes for one watchdog.

    Opens (creating if needed) a SQLite file at ``path`` on construction. The
    three bounds default to the ``SINK_DELIVERY_OUTBOX_*`` config knobs but may
    be overridden per-instance (mainly for tests): an age window
    (``max_age_seconds``), a per-sink byte cap (``max_bytes_per_sink``), and a
    global disk cap across all sinks (``max_total_bytes``). Safe to use with no
    Flask app context; callers manage lifecycle via ``close()`` or the
    context-manager protocol.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_age_seconds: float | None = None,
        max_bytes_per_sink: int | None = None,
        max_total_bytes: int | None = None,
        busy_timeout_ms: int | None = None,
    ):
        cfg = get_config()
        self.path = Path(path)
        self.max_age_seconds = float(
            max_age_seconds
            if max_age_seconds is not None
            else cfg.SINK_DELIVERY_OUTBOX_MAX_AGE_SECONDS
        )
        self.max_bytes_per_sink = int(
            max_bytes_per_sink
            if max_bytes_per_sink is not None
            else cfg.SINK_DELIVERY_OUTBOX_MAX_BYTES_PER_SINK
        )
        self.max_total_bytes = int(
            max_total_bytes
            if max_total_bytes is not None
            else cfg.SINK_DELIVERY_OUTBOX_MAX_TOTAL_BYTES
        )
        busy = (
            busy_timeout_ms
            if busy_timeout_ms is not None
            else cfg.SINK_DELIVERY_OUTBOX_BUSY_TIMEOUT_MILLISECONDS
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + an explicit lock: a flush/replay loop may
        # run on a different thread than the one enqueuing samples.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute(f"PRAGMA busy_timeout = {int(busy)}")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SinkDeliveryOutbox:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ── enqueue ────────────────────────────────────────────────────────────

    def enqueue(
        self,
        sink_key: str,
        payload: bytes | str,
        *,
        idempotency_key: str,
        sample_count: int = 1,
        record_time: float | None = None,
        now: float | None = None,
    ) -> bool:
        """Durably buffer one raw service-sink write.

        Returns ``True`` if a new record was inserted, ``False`` if
        ``idempotency_key`` was already present (idempotent no-op). Either way
        the write is on disk when this returns. Enforces all bounds in the same
        transaction, so a newly inserted record may itself be evicted (and
        counted as loss) if it falls outside the age window or overflows a cap;
        acquisition is never blocked by a full outbox.

        ``record_time`` (epoch seconds) is the sample's wall-clock time used
        for the age bound and loss ranges; ``now`` (epoch seconds) is the
        reference clock for age eviction. Both default to ``time.time()``.
        """
        payload_bytes = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        stamp = time.time()
        ts = float(record_time) if record_time is not None else stamp
        ref_now = float(now) if now is not None else stamp
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO sink_delivery_records "
                    "(sink_key, idempotency_key, payload, byte_size, "
                    " sample_count, record_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        sink_key,
                        idempotency_key,
                        payload_bytes,
                        len(payload_bytes),
                        int(sample_count),
                        ts,
                    ),
                )
            except sqlite3.IntegrityError:
                self._conn.rollback()
                return False
            self._enforce_bounds(ref_now)
            self._conn.commit()
            return True

    def enqueue_new(
        self,
        sink_key: str,
        payload: bytes | str,
        *,
        sample_count: int = 1,
        record_time: float | None = None,
        now: float | None = None,
    ) -> SinkDeliveryRecord | None:
        """Persist a new write with an identity safe across reconstruction.

        ``None`` means the new record was immediately evicted by a configured
        bound; durable loss accounting has already been updated.
        """
        idempotency_key = f"{sink_key}#{uuid4().hex}"
        self.enqueue(
            sink_key,
            payload,
            idempotency_key=idempotency_key,
            sample_count=sample_count,
            record_time=record_time,
            now=now,
        )
        with self._lock:
            row = self._conn.execute(
                "SELECT id, sink_key, idempotency_key, payload, byte_size, "
                "sample_count, record_time, enqueued_at FROM sink_delivery_records "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else _row_to_record(row)

    # ── replay / ack ───────────────────────────────────────────────────────

    def pending(self, sink_key: str | None = None, limit: int | None = None) -> list[SinkDeliveryRecord]:
        """Undelivered records, oldest first. Filter to one ``sink_key``."""
        sql = (
            "SELECT id, sink_key, idempotency_key, payload, byte_size, "
            "sample_count, record_time, enqueued_at FROM sink_delivery_records"
        )
        params: list[object] = []
        if sink_key is not None:
            sql += " WHERE sink_key = ?"
            params.append(sink_key)
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def ack(self, idempotency_key: str) -> None:
        """Drop one delivered record. No-op if unknown/already acked."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM sink_delivery_records WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            self._conn.commit()

    def ack_many(self, idempotency_keys: Iterable[str]) -> None:
        """Drop several delivered records in one transaction."""
        with self._lock:
            self._conn.executemany(
                "DELETE FROM sink_delivery_records WHERE idempotency_key = ?",
                [(key,) for key in idempotency_keys],
            )
            self._conn.commit()

    # ── bounds / eviction ──────────────────────────────────────────────────

    def evict(self, now: float | None = None) -> int:
        """Enforce all bounds now; return the number of records evicted.

        Callable independently of ``enqueue`` (e.g. a periodic sweep so the age
        bound applies even while no new samples arrive). Evicted records fold
        into durable per-sink loss counters atomically.
        """
        ref_now = float(now) if now is not None else time.time()
        with self._lock:
            evicted = self._enforce_bounds(ref_now)
            self._conn.commit()
        return evicted

    def _enforce_bounds(self, now: float) -> int:
        """Age, then per-sink bytes, then global cap. Caller holds the lock and
        commits. Returns total records evicted."""
        evicted = 0
        evicted += self._evict_expired(now)
        evicted += self._evict_per_sink_bytes()
        evicted += self._evict_global_bytes()
        return evicted

    def _evict_expired(self, now: float) -> int:
        cutoff = now - self.max_age_seconds
        rows = self._conn.execute(
            "SELECT id, sink_key, byte_size, sample_count, record_time "
            "FROM sink_delivery_records WHERE record_time < ? ORDER BY id ASC",
            (cutoff,),
        ).fetchall()
        return self._drop(rows)

    def _evict_per_sink_bytes(self) -> int:
        over = self._conn.execute(
            "SELECT sink_key FROM sink_delivery_records GROUP BY sink_key "
            "HAVING SUM(byte_size) > ?",
            (self.max_bytes_per_sink,),
        ).fetchall()
        dropped = 0
        for (sink_key,) in over:
            rows = self._conn.execute(
                "SELECT id, sink_key, byte_size, sample_count, record_time "
                "FROM sink_delivery_records WHERE sink_key = ? ORDER BY id ASC",
                (sink_key,),
            ).fetchall()
            total = sum(row[2] for row in rows)
            to_drop = []
            for row in rows:
                if total <= self.max_bytes_per_sink:
                    break
                to_drop.append(row)
                total -= row[2]
            dropped += self._drop(to_drop)
        return dropped

    def _evict_global_bytes(self) -> int:
        total = self._conn.execute(
            "SELECT COALESCE(SUM(byte_size), 0) FROM sink_delivery_records"
        ).fetchone()[0]
        if total <= self.max_total_bytes:
            return 0
        rows = self._conn.execute(
            "SELECT id, sink_key, byte_size, sample_count, record_time "
            "FROM sink_delivery_records ORDER BY id ASC"
        ).fetchall()
        to_drop = []
        for row in rows:
            if total <= self.max_total_bytes:
                break
            to_drop.append(row)
            total -= row[2]
        return self._drop(to_drop)

    def _drop(self, rows: list[tuple]) -> int:
        """Delete rows and fold their bytes/samples/time-range into durable
        per-sink loss counters, in the current (uncommitted) transaction."""
        if not rows:
            return 0
        per_sink: dict[str, list] = {}
        for _id, sink_key, byte_size, sample_count, record_time in rows:
            agg = per_sink.setdefault(sink_key, [0, 0, 0, None, None])
            agg[0] += 1
            agg[1] += byte_size
            agg[2] += sample_count
            agg[3] = record_time if agg[3] is None else min(agg[3], record_time)
            agg[4] = record_time if agg[4] is None else max(agg[4], record_time)
        self._conn.executemany(
            "DELETE FROM sink_delivery_records WHERE id = ?",
            [(row[0],) for row in rows],
        )
        for sink_key, (n, b, s, t_start, t_end) in per_sink.items():
            self._conn.execute(
                "INSERT INTO sink_delivery_loss "
                "(sink_key, lost_records, lost_bytes, lost_samples, "
                " lost_time_start, lost_time_end, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
                "ON CONFLICT(sink_key) DO UPDATE SET "
                "  lost_records = lost_records + excluded.lost_records, "
                "  lost_bytes = lost_bytes + excluded.lost_bytes, "
                "  lost_samples = lost_samples + excluded.lost_samples, "
                "  lost_time_start = MIN("
                "      COALESCE(lost_time_start, excluded.lost_time_start),"
                "      excluded.lost_time_start), "
                "  lost_time_end = MAX("
                "      COALESCE(lost_time_end, excluded.lost_time_end),"
                "      excluded.lost_time_end), "
                "  updated_at = excluded.updated_at",
                (sink_key, n, b, s, t_start, t_end),
            )
        return len(rows)

    # ── introspection ──────────────────────────────────────────────────────

    def count_pending(self, sink_key: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM sink_delivery_records"
        params: tuple = ()
        if sink_key is not None:
            sql += " WHERE sink_key = ?"
            params = (sink_key,)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return int(row[0])

    def total_bytes(self, sink_key: str | None = None) -> int:
        sql = "SELECT COALESCE(SUM(byte_size), 0) FROM sink_delivery_records"
        params: tuple = ()
        if sink_key is not None:
            sql += " WHERE sink_key = ?"
            params = (sink_key,)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return int(row[0])

    def loss_report(self, sink_key: str) -> SinkLossReport:
        """Durable permanent-loss evidence for ``sink_key`` (zeros if none)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT lost_records, lost_bytes, lost_samples, "
                "lost_time_start, lost_time_end FROM sink_delivery_loss "
                "WHERE sink_key = ?",
                (sink_key,),
            ).fetchone()
        if row is None:
            return SinkLossReport(sink_key, 0, 0, 0, None, None)
        return SinkLossReport(
            sink_key=sink_key,
            lost_records=int(row[0]),
            lost_bytes=int(row[1]),
            lost_samples=int(row[2]),
            lost_time_start=row[3],
            lost_time_end=row[4],
        )

    def is_degraded(self, sink_key: str) -> bool:
        """True once any record for ``sink_key`` has been permanently lost."""
        return self.loss_report(sink_key).degraded


def _row_to_record(row: sqlite3.Row | tuple) -> SinkDeliveryRecord:
    (
        record_id,
        sink_key,
        idempotency_key,
        payload,
        byte_size,
        sample_count,
        record_time,
        enqueued_at,
    ) = row
    return SinkDeliveryRecord(
        record_id=record_id,
        sink_key=sink_key,
        idempotency_key=idempotency_key,
        payload=bytes(payload),
        byte_size=int(byte_size),
        sample_count=int(sample_count),
        record_time=float(record_time),
        enqueued_at=enqueued_at,
    )


__all__ = [
    "SinkDeliveryOutbox",
    "SinkDeliveryRecord",
    "SinkLossReport",
    "default_sink_delivery_outbox_path",
    "sink_delivery_key",
]
