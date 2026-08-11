"""Joined device list for operator-facing pool state."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.discovery.pod_scan import DiscoveredDevice
from app.domain.enums import DeviceClaimState, DeviceType
from app.models.device_config import DeviceConfig
from app.services import device_configs, device_registrations, device_templates


@dataclass(frozen=True, slots=True)
class DevicePoolRow:
    id: int | None
    type: str
    port: str
    hardware_id: str | None
    color: str | None
    availability: str
    status: str
    owner: int | None
    nickname: str | None
    label: str | None
    source_template: str | None
    source_template_hash: str | None
    configuration_hash: str | None

    def as_dict(self) -> dict[str, object | None]:
        return asdict(self)


def build_pool_rows(discovered: list[DiscoveredDevice]) -> list[dict[str, object | None]]:
    """Return persisted configs unioned with the latest discovery rows."""
    scan_by_identity = {
        _identity(device.type, device.hardware_id): device
        for device in discovered
        if device.hardware_id is not None
    }
    registration_by_identity = {
        _identity(DeviceType(row.device_type), row.hardware_id): row
        for row in device_registrations.list()
    }
    rows: list[DevicePoolRow] = []
    configured_identities: set[str] = set()

    for config in device_configs.list():
        identity = _identity(DeviceType(config.device_type), config.hardware_id)
        configured_identities.add(identity)
        seen = scan_by_identity.get(identity)
        rows.append(_configured_row(config, seen))

    for device in discovered:
        if (
            device.hardware_id is not None
            and _identity(device.type, device.hardware_id) in configured_identities
        ):
            continue
        rows.append(
            _unconfigured_row(
                device,
                registration_by_identity.get(_identity(device.type, device.hardware_id)),
            )
        )

    return [row.as_dict() for row in rows]


def _configured_row(
    config: DeviceConfig,
    seen: DiscoveredDevice | None,
) -> DevicePoolRow:
    claim_state = DeviceClaimState(config.claim_state)
    return DevicePoolRow(
        id=config.id,
        type=DeviceType(config.device_type).value,
        port=seen.port if seen is not None else config.port,
        hardware_id=config.hardware_id,
        color=config.color,
        availability=seen.availability if seen is not None else "not_found",
        status=claim_state.value,
        owner=config.claimed_session_id,
        nickname=config.nickname,
        label=seen.label if seen is not None else config.nickname,
        source_template=config.source_template,
        source_template_hash=config.source_template_hash,
        configuration_hash=device_templates.content_hash(
            {
                "type": DeviceType(config.device_type).value,
                "parameters": dict(config.parameters or {}),
            }
        ),
    )


def _unconfigured_row(
    device: DiscoveredDevice,
    registration=None,
) -> DevicePoolRow:
    nickname = registration.nickname if registration is not None else None
    return DevicePoolRow(
        id=None,
        type=device.type.value,
        port=device.port,
        hardware_id=device.hardware_id,
        color=None,
        availability=device.availability,
        status="unconfigured",
        owner=None,
        nickname=nickname,
        label=nickname or device.label,
        source_template=None,
        source_template_hash=None,
        configuration_hash=None,
    )


def _identity(device_type: DeviceType, hardware_id: str | None) -> str:
    return f"{device_type.value}:{hardware_id or ''}"
