"""Local SQLite outbox for one watchdog-process instance.

A watchdog process buffers ``WatchdogTelemetryEnvelope`` reports here before
attempting direct HTTP ingest to the control plane (that flush loop is a
later packet). The outbox is deliberately independent of the Flask app's
SQLAlchemy engine/session (``app.database``): the watchdog process is not a
Flask process and must be able to durably buffer telemetry with no Flask app
context at all, so it opens its own plain ``sqlite3`` connection against a
file that is local to this watchdog-process instance.

Durability/idempotency model:
- ``report_id`` (from the direct-ingest envelope, see
  ``app.contracts.watchdog_process_protocol``) is the natural key. Enqueuing
  the same ``report_id`` twice is a no-op — the row already made it to disk,
  so a retried enqueue (e.g. after a crash mid-write) must not duplicate it.
- Rows flush in insertion order (``id ASC``) so the control plane always
  observes a report_id's causal predecessors before it, matching how
  ``BackendEventRepository`` treats ``backend_events.id`` as an ordered
  cursor.
- ``mark_delivered`` is a separate step from ``enqueue`` so a flush loop can
  crash between "sent" and "marked" without losing the row — at worst it is
  redelivered, and the control-plane ingest contract is idempotent on
  ``report_id`` too (see ``ingest_watchdog_report``).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.config import get_config
from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL UNIQUE,
    dataflow_id TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    watchdog_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    enqueued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    delivered_at TEXT
);
"""


@dataclass(frozen=True, slots=True)
class OutboxReport:
    """One outbox row, decoded back into its telemetry envelope.

    ``outbox_id`` is the outbox's own local autoincrement key (insertion
    order) — distinct from ``envelope.report_id``, which is the cross-
    process idempotency key the control plane fences on.
    """

    outbox_id: int
    envelope: WatchdogTelemetryEnvelope
    enqueued_at: str


def default_outbox_path(outbox_dir: str | Path, watchdog_id: str) -> Path:
    """Compute the per-watchdog-process outbox file path under ``outbox_dir``.

    Naming the file by ``watchdog_id`` (rather than e.g. ``runtime_id``)
    means a respawned watchdog process never reopens — and never mixes rows
    into — the outbox file of the watchdog process instance it replaced.
    Pure path arithmetic; does not touch the filesystem or require a Flask
    app context, so it is safe to call before ``WatchdogOutbox`` exists.
    """
    return Path(outbox_dir) / f"{watchdog_id}.sqlite3"


class WatchdogOutbox:
    """Durable local outbox for one watchdog-process instance.

    Opens (creating if needed) a SQLite file at ``path`` on construction.
    Safe to use with no Flask app context and independent of
    ``app.database.db`` — callers manage their own lifecycle via ``close()``
    or the context-manager protocol.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + an explicit lock: a flush loop may run on
        # a different thread than the one enqueuing reports.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute(
                f"PRAGMA busy_timeout = {get_config().WATCHDOG_OUTBOX_BUSY_TIMEOUT_MILLISECONDS}"
            )
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> WatchdogOutbox:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def enqueue(self, envelope: WatchdogTelemetryEnvelope) -> bool:
        """Durably persist one telemetry envelope.

        Returns ``True`` if this call inserted a new row, ``False`` if
        ``envelope.report_id`` was already in the outbox (idempotent no-op)
        — either way the row is guaranteed to be on disk when this returns.
        """
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO outbox_reports "
                    "(report_id, dataflow_id, runtime_id, watchdog_id, "
                    " manifest_hash, event_type, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        envelope.report_id,
                        envelope.dataflow_id,
                        envelope.runtime_id,
                        envelope.watchdog_id,
                        envelope.manifest_hash,
                        envelope.event_type,
                        json.dumps(dict(envelope.payload)),
                    ),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                self._conn.rollback()
                return False

    def pending(self, limit: int | None = None) -> list[OutboxReport]:
        """Undelivered rows, oldest first (insertion order)."""
        sql = (
            "SELECT id, report_id, dataflow_id, runtime_id, watchdog_id, "
            "manifest_hash, event_type, payload, enqueued_at "
            "FROM outbox_reports WHERE delivered_at IS NULL ORDER BY id ASC"
        )
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_report(row) for row in rows]

    def mark_delivered(self, report_id: str) -> None:
        """Mark one report as flushed to the control plane.

        A no-op if ``report_id`` is unknown or already delivered, so a
        retried/duplicate delivery confirmation cannot raise.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE outbox_reports SET delivered_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE report_id = ? AND delivered_at IS NULL",
                (report_id,),
            )
            self._conn.commit()

    def mark_delivered_many(self, report_ids: Iterable[str]) -> None:
        """Mark several reports delivered in one transaction."""
        with self._lock:
            self._conn.executemany(
                "UPDATE outbox_reports SET delivered_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE report_id = ? AND delivered_at IS NULL",
                [(report_id,) for report_id in report_ids],
            )
            self._conn.commit()

    def count_pending(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM outbox_reports WHERE delivered_at IS NULL"
            ).fetchone()
        return int(row[0])

    def rebind_pending_runtime(self, *, watchdog_id: str, runtime_id: str) -> None:
        """Move undelivered telemetry to an authenticated replacement host.

        Delivered rows remain immutable history. Pending rows retain their
        report ids and ordering but must name the newly adopted runtime, or the
        ingest fence would reject them after the old ownership row is stopped.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE outbox_reports SET runtime_id = ? "
                "WHERE watchdog_id = ? AND delivered_at IS NULL",
                (runtime_id, watchdog_id),
            )
            self._conn.commit()


def _row_to_report(row: sqlite3.Row | tuple) -> OutboxReport:
    (
        outbox_id,
        report_id,
        dataflow_id,
        runtime_id,
        watchdog_id,
        manifest_hash,
        event_type,
        payload,
        enqueued_at,
    ) = row
    envelope = WatchdogTelemetryEnvelope(
        report_id=report_id,
        dataflow_id=dataflow_id,
        runtime_id=runtime_id,
        watchdog_id=watchdog_id,
        manifest_hash=manifest_hash,
        event_type=event_type,
        payload=json.loads(payload),
    )
    return OutboxReport(outbox_id=outbox_id, envelope=envelope, enqueued_at=enqueued_at)


__all__ = ["OutboxReport", "WatchdogOutbox", "default_outbox_path"]
