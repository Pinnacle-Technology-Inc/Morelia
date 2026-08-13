"""Repository access for persisted recovery gap history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_

from app.database import db, transaction
from app.domain.enums import GapConfidence
from app.models.recovery_gap import RecoveryGap


def _confidence_value(confidence: GapConfidence | str) -> str:
    return confidence.value if isinstance(confidence, GapConfidence) else confidence


class RecoveryGapRepository:
    """Database access for recovery output continuity gaps."""

    def create(
        self,
        *,
        session_id: int,
        dataflow_id: str,
        reason: str,
        gap_id: str | None = None,
        incident_id: str | None = None,
        device_id: str | None = None,
        sink_id: str | None = None,
        operation_id: str | None = None,
        recovery_id: str | None = None,
        previous_segment_id: str | None = None,
        next_segment_id: str | None = None,
        boundary_kind: str | None = None,
        boundary_version: int | None = None,
        output_id: str | None = None,
        previous_output_id: str | None = None,
        next_output_id: str | None = None,
        pre_offset: Mapping[str, Any] | None = None,
        post_offset: Mapping[str, Any] | None = None,
        boundary_payload: Mapping[str, Any] | None = None,
        policy: str | None = None,
        confidence: GapConfidence | str = GapConfidence.UNCERTAIN,
        gap_start: Mapping[str, Any] | None = None,
        gap_end: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> RecoveryGap:
        def insert() -> RecoveryGap:
            row = RecoveryGap(
                gap_id=gap_id or uuid4().hex,
                incident_id=incident_id,
                session_id=session_id,
                dataflow_id=dataflow_id,
                device_id=device_id,
                sink_id=sink_id,
                operation_id=operation_id,
                recovery_id=recovery_id,
                previous_segment_id=previous_segment_id,
                next_segment_id=next_segment_id,
                boundary_kind=boundary_kind,
                boundary_version=boundary_version,
                output_id=output_id,
                previous_output_id=previous_output_id,
                next_output_id=next_output_id,
                pre_offset=dict(pre_offset) if pre_offset is not None else None,
                post_offset=dict(post_offset) if post_offset is not None else None,
                boundary_payload=(
                    dict(boundary_payload) if boundary_payload is not None else None
                ),
                reason=reason,
                policy=policy,
                confidence=_confidence_value(confidence),
                gap_start=dict(gap_start) if gap_start is not None else None,
                gap_end=dict(gap_end) if gap_end is not None else None,
                details=dict(details) if details is not None else None,
            )
            db.session.add(row)
            db.session.flush()
            return row

        if commit:
            with transaction():
                return insert()
        return insert()

    def get(self, gap_id: str) -> RecoveryGap | None:
        return db.session.scalars(
            db.select(RecoveryGap).where(RecoveryGap.gap_id == gap_id)
        ).first()

    def list_for_session(self, session_id: int) -> list[RecoveryGap]:
        query = db.select(RecoveryGap).where(RecoveryGap.session_id == session_id)
        return db.session.scalars(query.order_by(RecoveryGap.created_at.desc())).all()

    def list_page(
        self,
        *,
        session_id: int | None = None,
        confidence: GapConfidence | str | None = None,
        page_size: int = 50,
        after: tuple[datetime | None, int] | None = None,
    ) -> tuple[list[RecoveryGap], bool]:
        query = db.select(RecoveryGap)
        if session_id is not None:
            query = query.where(RecoveryGap.session_id == session_id)
        if confidence is not None:
            query = query.where(RecoveryGap.confidence == _confidence_value(confidence))
        if after is not None:
            timestamp, row_id = after
            if timestamp is None:
                query = query.where(RecoveryGap.created_at.is_(None), RecoveryGap.id < row_id)
            else:
                query = query.where(or_(RecoveryGap.created_at < timestamp, and_(RecoveryGap.created_at == timestamp, RecoveryGap.id < row_id), RecoveryGap.created_at.is_(None)))
        query = query.order_by(RecoveryGap.created_at.is_(None), RecoveryGap.created_at.desc(), RecoveryGap.id.desc()).limit(page_size + 1)
        rows = list(db.session.scalars(query).all())
        return rows[:page_size], len(rows) > page_size

    def list_for_incident(self, incident_id: str) -> list[RecoveryGap]:
        query = db.select(RecoveryGap).where(RecoveryGap.incident_id == incident_id)
        return db.session.scalars(query.order_by(RecoveryGap.created_at.desc())).all()

    def find_by_recovery_id(self, recovery_id: str) -> RecoveryGap | None:
        """Return the gap already recorded for one recovery episode, if any.

        One recovery_id yields at most one gap, so this is the dedup guard that
        keeps a repeated post-recovery report from writing the gap twice.
        """
        query = db.select(RecoveryGap).where(RecoveryGap.recovery_id == recovery_id)
        return db.session.scalars(query.order_by(RecoveryGap.created_at.desc())).first()
