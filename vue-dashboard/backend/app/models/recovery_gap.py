from datetime import UTC, datetime

from app.database import db
from app.domain.enums import GapConfidence


class RecoveryGap(db.Model):
    """Persisted output continuity gap around a recovery boundary."""

    __tablename__ = "recovery_gaps"

    id = db.Column(db.Integer, primary_key=True)
    gap_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    incident_id = db.Column(
        db.String(64),
        db.ForeignKey("incidents.incident_id"),
        nullable=True,
        index=True,
    )
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    dataflow_id = db.Column(db.String(64), nullable=False, index=True)
    device_id = db.Column(db.String(255), nullable=True, index=True)
    sink_id = db.Column(db.String(255), nullable=True)
    operation_id = db.Column(db.String(64), nullable=True)
    recovery_id = db.Column(db.String(64), nullable=True, index=True)
    previous_segment_id = db.Column(db.String(128), nullable=True)
    next_segment_id = db.Column(db.String(128), nullable=True)
    # Versioned boundary payload. Replaces the practice of overloading
    # previous_segment_id / next_segment_id with undocumented offset-only JSON.
    # The legacy offset columns above are retained for the 4.3 record_boundary
    # path; new callers describe the boundary through these typed columns.
    #
    # boundary_kind identifies which shape the payload takes:
    #   - "same_file": one output_id plus pre/post byte+row offsets;
    #   - "segmented": previous_output_id + next_output_id link two components;
    #   - "remote":    destination identity + last-confirmed/first-resumed marks;
    #   - "plot":      presentation disconnect/reconnect marks.
    boundary_kind = db.Column(db.String(32), nullable=True, index=True)
    boundary_version = db.Column(db.Integer, nullable=True)
    output_id = db.Column(db.String(36), nullable=True, index=True)
    previous_output_id = db.Column(db.String(36), nullable=True)
    next_output_id = db.Column(db.String(36), nullable=True)
    pre_offset = db.Column(db.JSON, nullable=True)
    post_offset = db.Column(db.JSON, nullable=True)
    boundary_payload = db.Column(db.JSON, nullable=True)
    reason = db.Column(db.String(255), nullable=False)
    policy = db.Column(db.String(32), nullable=True)
    confidence = db.Column(
        db.String(32),
        nullable=False,
        default=GapConfidence.UNCERTAIN.value,
        index=True,
    )
    gap_start = db.Column(db.JSON, nullable=True)
    gap_end = db.Column(db.JSON, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
