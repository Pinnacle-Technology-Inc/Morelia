from datetime import UTC, datetime

from app.database import db


class BackendEvent(db.Model):
    """Durable, ordered event log entry; its autoincrement id is the SSE cursor.

    - The runtime-host push/poll path
    - The direct watchdog-process telemetry path

    ``id`` remains the sole SSE cursor regardless of which path wrote the row.
    """

    __tablename__ = "backend_events"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(64), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    dataflow_id = db.Column(db.String(64), nullable=False, index=True)
    runtime_id = db.Column(db.String(64), nullable=True)
    watchdog_id = db.Column(db.String(64), nullable=True, index=True)
    report_id = db.Column(db.String(64), nullable=True)
    recovery_id = db.Column(db.String(64), nullable=True, index=True)
    sequence = db.Column(db.Integer, nullable=True)
    phase = db.Column(db.String(32), nullable=True)
    comms = db.Column(db.String(32), nullable=True)
    payload = db.Column(db.JSON, nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        db.UniqueConstraint(
            "dataflow_id", "sequence", name="uq_backend_events_dataflow_sequence"
        ),
        db.UniqueConstraint("report_id", name="uq_backend_events_report_id"),
        db.Index("ix_backend_events_session_id_id", "session_id", "id"),
    )
