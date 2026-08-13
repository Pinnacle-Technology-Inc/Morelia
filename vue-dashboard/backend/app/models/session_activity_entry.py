from datetime import UTC, datetime

from app.database import db


class SessionActivityEntry(db.Model):
    """Durable, human-readable history for one session.

    Raw runtime telemetry remains authoritative in ``backend_events``.  This
    table is the operator-facing projection: one concise fact per meaningful
    domain transition, with links back to its technical evidence.
    """

    __tablename__ = "session_activity_entries"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataflow_id = db.Column(db.String(64), nullable=True, index=True)
    kind = db.Column(db.String(64), nullable=False, index=True)
    category = db.Column(db.String(32), nullable=False, index=True)
    severity = db.Column(db.String(16), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    summary = db.Column(db.String(1024), nullable=False)
    source_type = db.Column(db.String(64), nullable=False)
    source_id = db.Column(db.String(128), nullable=False)
    operation_id = db.Column(db.String(64), nullable=True, index=True)
    incident_id = db.Column(db.String(64), nullable=True, index=True)
    gap_id = db.Column(db.String(64), nullable=True, index=True)
    command_id = db.Column(db.String(64), nullable=True, index=True)
    recovery_id = db.Column(db.String(64), nullable=True, index=True)
    details = db.Column(db.JSON, nullable=True)
    occurred_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        db.UniqueConstraint(
            "session_id",
            "source_type",
            "source_id",
            "kind",
            name="uq_session_activity_session_source_kind",
        ),
        db.Index(
            "ix_session_activity_session_occurred",
            "session_id",
            "occurred_at",
            "id",
        ),
    )
