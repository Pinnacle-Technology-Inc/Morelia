"""Repository for the durable backend_events log."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import db, transaction
from app.models.backend_event import BackendEvent


class BackendEventRepository:
    """Append-only event log; reads are used for SSE replay."""

    def append(
        self,
        *,
        event_type: str,
        session_id: int,
        dataflow_id: str,
        payload: Mapping[str, Any],
        sequence: int | None = None,
        runtime_id: str | None = None,
        watchdog_id: str | None = None,
        report_id: str | None = None,
        recovery_id: str | None = None,
        phase: str | None = None,
        comms: str | None = None,
        commit: bool = True,
    ) -> int:
        """Insert one event row; return its id.

        Different key depends on the caller:
        - If called by watchdog (include``report_id``): the
          conflict target is ``report_id`` alone — a respawned watchdog
          process's reports never collide with rows a prior watchdog process
          left behind.
        - If called by runtime-host (``report_id`` not provided) : ``sequence`` is required.

        """
        if report_id is not None:
            conflict_index = ["report_id"]
            lookup = (BackendEvent.report_id == report_id,)
            missing_row_key = f"report_id={report_id!r}"
        else:
            if sequence is None:
                raise ValueError("sequence is required when report_id is not provided")
            conflict_index = ["dataflow_id", "sequence"]
            lookup = (
                BackendEvent.dataflow_id == dataflow_id,
                BackendEvent.sequence == sequence,
            )
            missing_row_key = f"(dataflow_id={dataflow_id!r}, sequence={sequence!r})"

        def insert() -> None:
            stmt = (
                sqlite_insert(BackendEvent)
                .values(
                    event_type=event_type,
                    session_id=session_id,
                    dataflow_id=dataflow_id,
                    sequence=sequence,
                    payload=dict(payload),
                    runtime_id=runtime_id,
                    watchdog_id=watchdog_id,
                    report_id=report_id,
                    recovery_id=recovery_id,
                    phase=phase,
                    comms=comms,
                )
                .on_conflict_do_nothing(index_elements=conflict_index)
            )
            db.session.execute(stmt)
            db.session.flush()

        if commit:
            with transaction():
                insert()
        else:
            insert()

        row = db.session.scalars(db.select(BackendEvent).where(*lookup)).first()
        if row is None:
            raise RuntimeError(
                f"backend_events row missing after insert-or-noop for {missing_row_key}"
            )
        return row.id

    def latest_for_session(self, session_id: int) -> BackendEvent | None:
        """Return the newest event row for a session, or None if it has none.

        Newest = highest autoincrement id (the same monotonic cursor the SSE
        stream uses), so this is the last report the plane has on record.
        """
        return db.session.scalars(
            db.select(BackendEvent)
            .where(BackendEvent.session_id == session_id)
            .order_by(BackendEvent.id.desc())
            .limit(1)
        ).first()

    def latest_report_for_session(self, session_id: int) -> BackendEvent | None:
        """Return the newest phase-bearing runtime report for a session.

        Activity notifications share this table for SSE replay, so report reads
        must name the runtime-report contract explicitly rather than relying on
        incidental columns alone.
        """
        return db.session.scalars(
            db.select(BackendEvent)
            .where(
                BackendEvent.session_id == session_id,
                BackendEvent.event_type == "runtime.report",
                BackendEvent.phase.is_not(None),
            )
            .order_by(BackendEvent.id.desc())
            .limit(1)
        ).first()

    def latest_runtime_report_for_session(self, session_id: int) -> BackendEvent | None:
        """Return the newest runtime report, including direct watchdog telemetry."""
        return db.session.scalars(
            db.select(BackendEvent)
            .where(
                BackendEvent.session_id == session_id,
                BackendEvent.event_type == "runtime.report",
            )
            .order_by(BackendEvent.id.desc())
            .limit(1)
        ).first()

    def latest_direct_telemetry_for_session(self, session_id: int) -> BackendEvent | None:
        """Return the newest event row from the DIRECT watchdog-process push path.

        ``report_id`` is set only there — never by the runtime-host push path
        (``ingest_report``), which sets ``sequence``/``phase`` instead.
        """
        return db.session.scalars(
            db.select(BackendEvent)
            .where(
                BackendEvent.session_id == session_id,
                BackendEvent.event_type == "runtime.report",
                BackendEvent.report_id.is_not(None),
            )
            .order_by(BackendEvent.id.desc())
            .limit(1)
        ).first()

    def since(self, session_id: int, after_id: int, limit: int) -> list[BackendEvent]:
        """Return events for a session with id > after_id, ascending by id."""
        return list(
            db.session.scalars(
                db.select(BackendEvent)
                .where(BackendEvent.session_id == session_id)
                .where(BackendEvent.id > after_id)
                .order_by(BackendEvent.id)
                .limit(limit)
            ).all()
        )
