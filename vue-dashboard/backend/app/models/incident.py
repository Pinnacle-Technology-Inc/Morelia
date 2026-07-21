from datetime import UTC, datetime

from app.database import db
from app.domain.enums import IncidentStatus


class Incident(db.Model):
    """Operator-facing failure or recovery event tied to a session/dataflow."""

    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    dataflow_id = db.Column(db.String(64), nullable=False, index=True)
    device_id = db.Column(db.String(255), nullable=True, index=True)
    sink_id = db.Column(db.String(255), nullable=True)
    runtime_id = db.Column(db.String(64), nullable=True)
    operation_id = db.Column(db.String(64), nullable=True)
    recovery_id = db.Column(db.String(64), nullable=True, index=True)
    status = db.Column(
        db.String(32),
        nullable=False,
        default=IncidentStatus.OPEN.value,
        index=True,
    )
    reason = db.Column(db.String(255), nullable=False)
    policy = db.Column(db.String(32), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    opened_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    acknowledged_by = db.Column(db.String(255), nullable=True)
    acknowledgement_note = db.Column(db.Text, nullable=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolution = db.Column(db.String(255), nullable=True)
