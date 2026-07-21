from datetime import UTC, datetime

from app.database import db
from app.domain.enums import RuntimeOwnershipState, WatchdogProcessState


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


class RuntimeOwnership(db.Model):
    """
    Durable identity and supervision record for one runtime host and watchdog process.
    """

    __tablename__ = "runtime_ownerships"

    id = db.Column(db.Integer, primary_key=True) #number ID
    #runtime_host control info
    runtime_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    dataflow_id = db.Column(db.String(64), nullable=False, index=True)
    manifest_hash = db.Column(db.String(64), nullable=False, index=True)
    pid = db.Column(db.Integer, nullable=True)
    port = db.Column(db.Integer, nullable=True, index=True)
    token = db.Column(db.String(128), nullable=True)
    state = db.Column(
        db.Enum(RuntimeOwnershipState, values_callable=_enum_values),
        nullable=False,
        default=RuntimeOwnershipState.STARTING,
        index=True,
    )
    started_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    adopted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    stopped_at = db.Column(db.DateTime(timezone=True), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    #watchdog control info
    watchdog_id = db.Column(db.String(64), nullable=True, index=True)
    watchdog_token_hash = db.Column(db.String(128), nullable=True)
    watchdog_pid = db.Column(db.Integer, nullable=True)
    watchdog_control_port = db.Column(db.Integer, nullable=True)
    watchdog_state = db.Column(
        db.Enum(WatchdogProcessState, values_callable=_enum_values),
        nullable=True,
        index=True,
    )
    watchdog_outbox_path = db.Column(db.String(255), nullable=True)
    watchdog_last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    watchdog_adopted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    watchdog_exit_details = db.Column(db.JSON, nullable=True)
