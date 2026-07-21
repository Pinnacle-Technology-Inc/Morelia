from __future__ import annotations

from app.database import db, transaction
from app.domain.enums import DeviceType
from app.models.device_config import DeviceConfig
from app.models.device_registration import DeviceRegistration


class DeviceRegistrationRepository:
    """Database access for pre-configuration device names."""

    def get_by_nickname(self, nickname: str) -> DeviceRegistration | None:
        return db.session.scalars(
            db.select(DeviceRegistration).where(DeviceRegistration.nickname == nickname)
        ).one_or_none()

    def get_by_identity(
        self, device_type: DeviceType, hardware_id: str
    ) -> DeviceRegistration | None:
        return db.session.scalars(
            db.select(DeviceRegistration).where(
                DeviceRegistration.device_type == device_type,
                DeviceRegistration.hardware_id == hardware_id,
            )
        ).one_or_none()

    def list(self) -> list[DeviceRegistration]:
        return db.session.scalars(
            db.select(DeviceRegistration).order_by(DeviceRegistration.nickname)
        ).all()

    def get_config_by_identity(
        self, device_type: DeviceType, hardware_id: str
    ) -> DeviceConfig | None:
        return db.session.scalars(
            db.select(DeviceConfig).where(
                DeviceConfig.device_type == device_type,
                DeviceConfig.hardware_id == hardware_id,
            )
        ).one_or_none()

    def create(
        self,
        *,
        device_type: DeviceType,
        hardware_id: str,
        nickname: str,
        device_config_id: int | None = None,
    ) -> DeviceRegistration:
        with transaction():
            row = DeviceRegistration(
                device_type=device_type,
                hardware_id=hardware_id,
                nickname=nickname,
                device_config_id=device_config_id,
            )
            db.session.add(row)
            db.session.flush()
        return row

__all__ = ["DeviceRegistrationRepository"]
