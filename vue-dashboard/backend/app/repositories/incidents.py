"""Repository access for operator-facing incidents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_

from app.database import db, transaction
from app.domain.enums import IncidentStatus
from app.models.incident import Incident
from app.services import session_activity


def _status_value(status: IncidentStatus | str) -> str:
    return status.value if isinstance(status, IncidentStatus) else status


class IncidentRepository:
    """Database access for incident history."""

    def create(
        self,
        *,
        session_id: int,
        dataflow_id: str,
        reason: str,
        incident_id: str | None = None,
        device_id: str | None = None,
        sink_id: str | None = None,
        runtime_id: str | None = None,
        operation_id: str | None = None,
        recovery_id: str | None = None,
        status: IncidentStatus | str = IncidentStatus.OPEN,
        policy: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> Incident:
        with transaction():
            row = Incident(
                incident_id=incident_id or uuid4().hex,
                session_id=session_id,
                dataflow_id=dataflow_id,
                device_id=device_id,
                sink_id=sink_id,
                runtime_id=runtime_id,
                operation_id=operation_id,
                recovery_id=recovery_id,
                status=_status_value(status),
                reason=reason,
                policy=policy,
                details=dict(details) if details is not None else None,
            )
            db.session.add(row)
            db.session.flush()
            session_activity.record(
                session_id=row.session_id,
                dataflow_id=row.dataflow_id,
                kind="issue.opened",
                category="issues",
                severity="error",
                title="Issue opened",
                summary=row.reason,
                source_type="incident",
                source_id=row.incident_id,
                incident_id=row.incident_id,
                operation_id=row.operation_id,
                recovery_id=row.recovery_id,
                details={
                    "device_id": row.device_id,
                    "sink_id": row.sink_id,
                    "policy": row.policy,
                },
                occurred_at=row.opened_at,
                commit=False,
            )
        return row

    def get(self, incident_id: str) -> Incident | None:
        return db.session.scalars(
            db.select(Incident).where(Incident.incident_id == incident_id)
        ).first()

    def list_for_session(
        self,
        session_id: int,
        *,
        status: IncidentStatus | str | None = None,
    ) -> list[Incident]:
        query = db.select(Incident).where(Incident.session_id == session_id)
        if status is not None:
            query = query.where(Incident.status == _status_value(status))
        return db.session.scalars(query.order_by(Incident.opened_at.desc())).all()

    def list_page(
        self,
        *,
        session_id: int | None = None,
        status: IncidentStatus | str | None = None,
        page_size: int = 50,
        after: tuple[datetime | None, int] | None = None,
    ) -> tuple[list[Incident], bool]:
        query = db.select(Incident)
        if session_id is not None:
            query = query.where(Incident.session_id == session_id)
        if status is not None:
            query = query.where(Incident.status == _status_value(status))
        if after is not None:
            timestamp, row_id = after
            if timestamp is None:
                query = query.where(Incident.opened_at.is_(None), Incident.id < row_id)
            else:
                query = query.where(
                    or_(
                        Incident.opened_at < timestamp,
                        and_(Incident.opened_at == timestamp, Incident.id < row_id),
                        Incident.opened_at.is_(None),
                    )
                )
        query = query.order_by(
            Incident.opened_at.is_(None), Incident.opened_at.desc(), Incident.id.desc()
        ).limit(page_size + 1)
        rows = list(db.session.scalars(query).all())
        return rows[:page_size], len(rows) > page_size

    def find_open_for_device(
        self,
        session_id: int,
        dataflow_id: str,
        device_id: str | None,
        *,
        reason: str | None = None,
    ) -> Incident | None:
        """Return the newest still-unresolved incident for one device stream.

        "Unresolved" = OPEN or ACKNOWLEDGED. Used to dedup: while an incident for
        this (session, dataflow, device) is still unresolved, a fresh trigger of
        the SAME kind must not open a second one.

        ``device_id`` alone is not always a unique dedup key: dataflow-scope
        triggers (host-unreachable, a failed dataflow-scope operation) both use
        ``device_id=None``, and would otherwise collide — a poller detecting
        UNREACHABLE could accidentally "resolve" an unrelated failed-start
        incident just because the link came back. Passing ``reason`` narrows the
        lookup to incidents opened by the SAME category of problem.
        """
        query = db.select(Incident).where(
            Incident.session_id == session_id,
            Incident.dataflow_id == dataflow_id,
            Incident.device_id == device_id,
            Incident.status.in_(
                (IncidentStatus.OPEN.value, IncidentStatus.ACKNOWLEDGED.value)
            ),
        )
        if reason is not None:
            query = query.where(Incident.reason == reason)
        return db.session.scalars(query.order_by(Incident.opened_at.desc())).first()

    def acknowledge(
        self,
        incident_id: str,
        *,
        acknowledged_by: str | None = None,
        note: str | None = None,
    ) -> Incident:
        with transaction():
            row = self.get(incident_id)
            if row is None:
                raise KeyError(f"incident not found: {incident_id}")
            row.status = IncidentStatus.ACKNOWLEDGED.value
            row.acknowledged_at = datetime.now(UTC)
            row.acknowledged_by = acknowledged_by
            row.acknowledgement_note = note
            db.session.flush()
            session_activity.record(
                session_id=row.session_id,
                dataflow_id=row.dataflow_id,
                kind="issue.acknowledged",
                category="issues",
                severity="info",
                title="Issue acknowledged",
                summary=note or f"Acknowledged by {acknowledged_by or 'operator'}.",
                source_type="incident",
                source_id=row.incident_id,
                incident_id=row.incident_id,
                operation_id=row.operation_id,
                recovery_id=row.recovery_id,
                occurred_at=row.acknowledged_at,
                commit=False,
            )
        return row

    def resolve(self, incident_id: str, *, resolution: str) -> Incident:
        with transaction():
            row = self.get(incident_id)
            if row is None:
                raise KeyError(f"incident not found: {incident_id}")
            row.status = IncidentStatus.RESOLVED.value
            row.resolved_at = datetime.now(UTC)
            row.resolution = resolution
            db.session.flush()
            session_activity.record(
                session_id=row.session_id,
                dataflow_id=row.dataflow_id,
                kind="issue.resolved",
                category="issues",
                severity="success",
                title="Issue resolved",
                summary=resolution,
                source_type="incident",
                source_id=row.incident_id,
                incident_id=row.incident_id,
                operation_id=row.operation_id,
                recovery_id=row.recovery_id,
                occurred_at=row.resolved_at,
                commit=False,
            )
        return row
