from __future__ import annotations

from collections.abc import Mapping

from app.database import db, transaction
from app.domain.enums import DeviceClaimState, DeviceType
from app.models.device_config import DeviceConfig


class DeviceConfigRepository:
    """Database access for persisted physical device configs."""

    def create(
        self,
        *,
        device_type: DeviceType,
        hardware_id: str,
        port: str,
        parameters: Mapping[str, object] | None = None,
        nickname: str | None = None,
        source_template: str | None = None,
        source_template_hash: str | None = None,
    ) -> DeviceConfig:
        with transaction():
            row = DeviceConfig(
                device_type=device_type,
                hardware_id=hardware_id,
                port=port,
                parameters=dict(parameters or {}),
                nickname=nickname,
                source_template=source_template,
                source_template_hash=source_template_hash,
                claim_state=DeviceClaimState.FREE,
            )
            db.session.add(row)
            db.session.flush()
        return row

    def get(self, device_config_id: int) -> DeviceConfig | None:
        return db.session.get(DeviceConfig, device_config_id)

    def get_by_identity(
        self, device_type: DeviceType, hardware_id: str
    ) -> DeviceConfig | None:
        """Return the config for the unique ``device_type + hardware_id`` identity."""
        return db.session.scalars(
            db.select(DeviceConfig).where(
                DeviceConfig.device_type == device_type,
                DeviceConfig.hardware_id == hardware_id,
            )
        ).one_or_none()

    def delete(self, row: DeviceConfig) -> None:
        with transaction():
            db.session.delete(row)

    def list(self) -> list[DeviceConfig]:
        return db.session.scalars(
            db.select(DeviceConfig).order_by(DeviceConfig.device_type, DeviceConfig.hardware_id)
        ).all()

    def find_by_hardware_id(self, hardware_id: str) -> list[DeviceConfig]:
        return db.session.scalars(
            db.select(DeviceConfig)
            .where(DeviceConfig.hardware_id == hardware_id)
            .order_by(DeviceConfig.device_type, DeviceConfig.id)
        ).all()

    def device_type_by_hardware_id(self) -> dict[str, DeviceType]:
        """Return serial-to-type mappings that are unambiguous in the registry."""
        rows = self.list()
        grouped: dict[str, set[DeviceType]] = {}
        for row in rows:
            try:
                device_type = DeviceType(row.device_type)
            except ValueError:
                continue
            if device_type is DeviceType.UNKNOWN:
                continue
            grouped.setdefault(row.hardware_id, set()).add(device_type)

        return {
            hardware_id: next(iter(device_types))
            for hardware_id, device_types in grouped.items()
            if len(device_types) == 1
        }
