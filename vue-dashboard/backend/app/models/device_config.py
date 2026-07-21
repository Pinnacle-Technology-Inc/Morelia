from datetime import UTC, datetime
from secrets import token_hex

from app.database import db
from app.domain.enums import DeviceClaimState, DeviceType


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def _random_color() -> str:
    return f"#{token_hex(3)}"


class DeviceConfig(db.Model):
    """Persisted, port-bound configuration for one physical device."""

    __tablename__ = "device_configs"
    __table_args__ = (
        db.UniqueConstraint(
            "device_type",
            "hardware_id",
            name="uq_device_configs_device_type_hardware_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    device_type = db.Column(
        db.Enum(DeviceType, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    hardware_id = db.Column(db.String(255), nullable=False, index=True)
    port = db.Column(db.String(255), nullable=False)
    parameters = db.Column(db.JSON, nullable=False, default=dict)
    color = db.Column(db.String(7), nullable=False, default=_random_color)
    nickname = db.Column(db.String(255), nullable=True)
    source_template = db.Column(db.String(1024), nullable=True)
    source_template_hash = db.Column(db.String(64), nullable=True)
    source_template_history = db.Column(db.String(1024), nullable=True)
    claim_state = db.Column(
        db.Enum(DeviceClaimState, values_callable=_enum_values),
        nullable=False,
        default=DeviceClaimState.FREE,
        index=True,
    )
    claimed_session_id = db.Column(
        db.Integer,
        db.ForeignKey("sessions.id"),
        nullable=True,
        index=True,
    )
    claim_expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
