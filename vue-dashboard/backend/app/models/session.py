from datetime import UTC, datetime

from app.database import db
from app.domain.enums import PolicyMode, SessionStatus


class Session(db.Model):
    "Database model for each session"
    __tablename__="sessions"

    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(255), nullable=False)
    status          = db.Column(db.Enum(SessionStatus), nullable=False, default=SessionStatus.PREPARING)
    policy          = db.Column(db.Enum(PolicyMode))
    experiment_id   = db.Column(
        db.String(64),
        db.ForeignKey("experiments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    notes             = db.Column(db.Text, nullable=True)
    duration_seconds  = db.Column(db.Integer, nullable=True)
    # First real sample received by HealthSink; anchors the session countdown.
    started_at        = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_at          = db.Column(db.DateTime(timezone=True), nullable=True)
    schedule          = db.Column(db.JSON, nullable=True)
    scheduled_for     = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    schedule_claim_token = db.Column(db.String(64), nullable=True)
    schedule_claim_expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    cancellation_details = db.Column(db.JSON, nullable=True)
    cancelled_at      = db.Column(db.DateTime(timezone=True), nullable=True)
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
    creation_request_key = db.Column(db.String(128), nullable=True, unique=True, index=True)
    creation_request_fingerprint = db.Column(db.String(64), nullable=True)
    created_at      = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))

    _runtime_ownerships = db.relationship("RuntimeOwnership", lazy="selectin", viewonly=True)

    @property
    def recording_bounds(self):
        """Recorded sample timestamps, combined across runtime replacements."""
        merged = {}
        for owner in self._runtime_ownerships:
            state = (owner.details or {}).get("recording_state") or {}
            for bound in state.get("recording_bounds", []):
                key = (bound["source_id"], bound["sink_id"])
                if key not in merged:
                    merged[key] = dict(bound)
                else:
                    for field, select in (("first_sample_at", min), ("last_sample_at", max)):
                        merged[key][field] = select(
                            merged[key][field], bound[field], key=datetime.fromisoformat,
                        )
        return list(merged.values())

    __table_args__ = (
        db.Index(
            "ix_sessions_source_template_history",
            "source_template_id",
            "created_at",
            "id",
        ),
        db.Index("ix_sessions_status_scheduled_for", "status", "scheduled_for"),
    )
