from datetime import UTC, datetime

from app.database import db
from app.domain.enums import DeviceType


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


class DeviceRegistration(db.Model):
    """Operator name registered before a physical device is configured."""

    __tablename__ = "device_registrations"
    __table_args__ = (
        db.UniqueConstraint(
            "device_type",
            "hardware_id",
            name="uq_device_registrations_device_type_hardware_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    device_type = db.Column(
        db.Enum(DeviceType, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    hardware_id = db.Column(db.String(255), nullable=False, index=True)
    nickname = db.Column(db.String(255), nullable=False, unique=True, index=True)
    device_config_id = db.Column(
        db.Integer,
        db.ForeignKey("device_configs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
