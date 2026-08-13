"""Repository access for durable, operator-facing session Activity."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import db, transaction
from app.models.session_activity_entry import SessionActivityEntry


class SessionActivityEntryRepository:
    """Persist and page the human-readable projection of session events."""

    def create(
        self,
        *,
        session_id: int,
        dataflow_id: str | None,
        kind: str,
        category: str,
        severity: str,
        title: str,
        summary: str,
        source_type: str,
        source_id: str,
        activity_id: str | None = None,
        operation_id: str | None = None,
        incident_id: str | None = None,
        gap_id: str | None = None,
        command_id: str | None = None,
        recovery_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
        commit: bool = True,
    ) -> SessionActivityEntry:
        """Insert one fact or return the existing fact for the same source.

        Runtime and watchdog reports may be replayed after reconnects. The
        session/source/kind identity therefore owns idempotency; a replay must
        not replace the original operator-facing wording or emit another live
        notification.
        """
        source_identity = (
            SessionActivityEntry.session_id == session_id,
            SessionActivityEntry.source_type == source_type,
            SessionActivityEntry.source_id == source_id,
            SessionActivityEntry.kind == kind,
        )

        def insert() -> None:
            statement = (
                sqlite_insert(SessionActivityEntry)
                .values(
                    activity_id=activity_id or uuid4().hex,
                    session_id=session_id,
                    dataflow_id=dataflow_id,
                    kind=kind,
                    category=category,
                    severity=severity,
                    title=title,
                    summary=summary,
                    source_type=source_type,
                    source_id=source_id,
                    operation_id=operation_id,
                    incident_id=incident_id,
                    gap_id=gap_id,
                    command_id=command_id,
                    recovery_id=recovery_id,
                    details=dict(details) if details is not None else None,
                    occurred_at=occurred_at or datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    index_elements=["session_id", "source_type", "source_id", "kind"]
                )
            )
            db.session.execute(statement)
            db.session.flush()

        if commit:
            with transaction():
                insert()
        else:
            insert()

        row = db.session.scalars(db.select(SessionActivityEntry).where(*source_identity)).first()
        if row is None:
            raise RuntimeError(
                "session activity row missing after insert-or-noop for "
                f"session_id={session_id!r}, source_type={source_type!r}, "
                f"source_id={source_id!r}, kind={kind!r}"
            )
        return row

    def list_for_session(self, session_id: int) -> list[SessionActivityEntry]:
        query = (
            db.select(SessionActivityEntry)
            .where(SessionActivityEntry.session_id == session_id)
            .order_by(
                SessionActivityEntry.occurred_at.desc(),
                SessionActivityEntry.id.desc(),
            )
        )
        return list(db.session.scalars(query).all())

    def list_page(
        self,
        *,
        session_id: int,
        page_size: int = 50,
        after: tuple[datetime, int] | None = None,
    ) -> tuple[list[SessionActivityEntry], bool]:
        query = db.select(SessionActivityEntry).where(SessionActivityEntry.session_id == session_id)
        if after is not None:
            timestamp, row_id = after
            query = query.where(
                or_(
                    SessionActivityEntry.occurred_at < timestamp,
                    and_(
                        SessionActivityEntry.occurred_at == timestamp,
                        SessionActivityEntry.id < row_id,
                    ),
                )
            )
        query = query.order_by(
            SessionActivityEntry.occurred_at.desc(),
            SessionActivityEntry.id.desc(),
        ).limit(page_size + 1)
        rows = list(db.session.scalars(query).all())
        return rows[:page_size], len(rows) > page_size
