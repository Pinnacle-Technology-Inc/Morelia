"""Device discovery service and providers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.discovery.pod_scan import DiscoveredDevice, PodProber, detect_pod_devices
from app.domain.enums import DeviceType
from app.repositories.device_configs import DeviceConfigRepository
from app.repositories.device_seen import DeviceSeenRepository

logger = logging.getLogger(__name__)

AVAILABILITY_VALUES = frozenset(
    {"available", "unopenable", "not_found"}
)
PortLister = Callable[[], Iterable[object]]
ConfiguredDeviceTypesProvider = Callable[[], Mapping[str, DeviceType]]


class DiscoveryProvider(Protocol):
    """Short-lived device discovery provider."""

    def scan(self) -> list[DiscoveredDevice]:
        """Return discovered device rows without retaining hardware handles."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    scan_id: str
    scanned_at: datetime
    devices: list[DiscoveredDevice]


class FakeDiscoveryProvider:
    """Deterministic discovery provider for tests and local CI."""

    def __init__(self, devices: Iterable[DiscoveredDevice] | None = None) -> None:
        self._devices = list(devices) if devices is not None else [_fake_pod()]

    def scan(self) -> list[DiscoveredDevice]:
        return list(self._devices)


class SerialPodProvider:
    """USB-serial POD discovery provider.

    This is one provider for the transport. Per-model differentiation belongs in
    POD identification and the config registry, not in separate provider classes.
    """

    def __init__(
        self,
        *,
        port_lister: PortLister | None = None,
        prober: PodProber | None = None,
    ) -> None:
        self._port_lister = port_lister or _live_port_lister
        self._prober = prober

    def scan(self) -> list[DiscoveredDevice]:
        return detect_pod_devices(port_lister=self._port_lister, prober=self._prober)


class DeviceDiscoveryService:
    def __init__(
        self,
        provider: DiscoveryProvider,
        configured_device_types: ConfiguredDeviceTypesProvider | None = None,
        device_seen_repository: DeviceSeenRepository | None = None,
    ) -> None:
        self._provider = provider
        self._configured_device_types = configured_device_types
        self._device_seen_repository = device_seen_repository or DeviceSeenRepository()

    def scan(self) -> ScanResult:
        devices = self._provider.scan()
        if self._configured_device_types is not None:
            devices = _apply_configured_device_types(
                devices,
                self._configured_device_types(),
            )

        scan_id = uuid4().hex
        self._record_scan(scan_id, devices)

        return ScanResult(
            scan_id=scan_id,
            scanned_at=datetime.now(UTC),
            devices=devices,
        )

    def _record_scan(self, scan_id: str, devices: list[DiscoveredDevice]) -> None:
        """Persist discovery evidence. Never blocks or fails a scan.

        Device List rendering is read-first and must not depend on this write
        succeeding, so a database problem here is logged and swallowed exactly
        like ``configured_device_types_from_db`` does elsewhere in this module.
        """
        try:
            self._device_seen_repository.record_scan(scan_id, devices)
        except (RuntimeError, SQLAlchemyError):
            logger.warning(
                "Skipping device_seen persistence because the database is unavailable.",
                exc_info=True,
            )


def _live_port_lister() -> Iterable[object]:
    from serial.tools.list_ports import comports

    return comports()


def _fake_pod() -> DiscoveredDevice:
    return DiscoveredDevice(
        type=DeviceType.POD8206HR,
        port="FAKE-POD-8206HR",
        hardware_id="fake-pod-8206hr",
        label="Fake POD 8206HR",
        availability="available",
    )


def configured_device_types_from_db() -> dict[str, DeviceType]:
    """Map registered FTDI serial numbers to persisted physical device types."""
    try:
        return DeviceConfigRepository().device_type_by_hardware_id()
    except SQLAlchemyError:
        logger.info(
            "Skipping device-config discovery enrichment because the database is unavailable.",
            exc_info=True,
        )
        return {}


def _apply_configured_device_types(
    devices: list[DiscoveredDevice],
    configured_types: Mapping[str, DeviceType],
) -> list[DiscoveredDevice]:
    enriched = []
    for device in devices:
        configured_type = (
            configured_types.get(device.hardware_id)
            if device.type is DeviceType.UNKNOWN
            and device.availability == "unopenable"
            and device.hardware_id
            else None
        )
        if configured_type is None:
            enriched.append(device)
            continue

        enriched.append(replace(device, type=configured_type))
    return enriched
