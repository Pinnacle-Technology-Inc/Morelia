from datetime import UTC, datetime

from app.database import db
from app.domain.enums import PolicyMode, SessionStatus


class Session(db.Model):
    "Database model for each session"
    __tablename__="sessions"

    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(255), nullable=False)
    status          = db.Column(db.Enum(SessionStatus), nullable=False, default=SessionStatus.DRAFT)
    policy          = db.Column(db.Enum(PolicyMode))
    experiment_id   = db.Column(db.String(255))
    notes             = db.Column(db.Text, nullable=True)
    schedule          = db.Column(db.JSON, nullable=True)
    device_flows      = db.Column(db.JSON, nullable=False, default=list)
    command_in_flight = db.Column(db.Boolean, nullable=False, default=False)
    command_id      = db.Column(db.String(64))
    dataflow_id     = db.Column(db.String(64))
    watchdog_id     = db.Column(db.String(64))
    runtime_port      = db.Column(db.Integer, nullable=True)
    runtime_token     = db.Column(db.String(128), nullable=True)
    source_template_id = db.Column(db.String(64), nullable=True)
    source_template_name = db.Column(db.String(255), nullable=True)
    source_template_ref = db.Column(db.String(1024), nullable=True)
    source_template_hash = db.Column(db.String(64), nullable=True)
    source_template_snapshot = db.Column(db.JSON, nullable=True)
    created_at      = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        db.Index(
            "ix_sessions_source_template_history",
            "source_template_id",
            "created_at",
            "id",
        ),
    )
