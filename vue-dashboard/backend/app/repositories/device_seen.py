from __future__ import annotations

from app.database import db, transaction
from app.discovery.pod_scan import DiscoveredDevice
from app.models.device_seen import DeviceSeen


class DeviceSeenRepository:
    """Database access for per-scan device discovery evidence."""

    def record_scan(self, scan_id: str, devices: list[DiscoveredDevice]) -> None:
        """Persist one ``DeviceSeen`` row per discovered device for *scan_id*."""
        rows = [
            DeviceSeen(
                physical_device_id=_physical_device_id(device),
                scan_id=scan_id,
                port=device.port,
                availability=device.availability,
                display_label=device.label,
                warnings_json=None,
                raw_json=None,
            )
            for device in devices
        ]
        if not rows:
            return

        with transaction():
            db.session.add_all(rows)


def _physical_device_id(device: DiscoveredDevice) -> str:
    """Derive the synthetic physical-device identity for one discovered device.

    Equals a device config's identity (``"{device_type}:{hardware_id}"``) when
    the device reported a hardware id; otherwise degrades to
    ``"unknown:<serial-or-empty>"`` since identity cannot be established.
    """
    if device.hardware_id:
        return f"{device.type.value}:{device.hardware_id}"
    return f"unknown:{device.hardware_id or ''}"
