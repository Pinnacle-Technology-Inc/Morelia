from datetime import UTC, datetime

from app.database import db
from app.domain.enums import OperationScope, OperationState


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


class Operation(db.Model):
    """Durable ledger row for one state-changing runtime operation."""

    __tablename__ = "operations"
    __table_args__ = (
        db.UniqueConstraint(
            "dataflow_id",
            "request_key",
            name="uq_operations_dataflow_request_key",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    request_key = db.Column(db.String(128), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    dataflow_id = db.Column(db.String(64), nullable=False, index=True)
    scope = db.Column(
        db.Enum(OperationScope, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    target_device_id = db.Column(db.String(255), nullable=True, index=True)
    command = db.Column(db.String(64), nullable=False)
    request_id = db.Column(db.String(64), nullable=True)
    command_id = db.Column(db.String(64), nullable=False, index=True)
    watchdog_id = db.Column(db.String(64), nullable=True)
    recovery_id = db.Column(db.String(64), nullable=True, index=True)
    runtime_id = db.Column(db.String(64), nullable=True, index=True)
    manifest_hash = db.Column(db.String(64), nullable=True)
    state = db.Column(
        db.Enum(OperationState, values_callable=_enum_values),
        nullable=False,
        default=OperationState.QUEUED,
        index=True,
    )
    queued_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
    claimed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dispatched_at = db.Column(db.DateTime(timezone=True), nullable=True)
    running_at = db.Column(db.DateTime(timezone=True), nullable=True)
    verifying_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.String(1024), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    resolved_by = db.Column(db.String(255), nullable=True)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolution_note = db.Column(db.String(1024), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
