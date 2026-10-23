"""Resolve USB serial hardware identities to their current OS addresses."""

from serial.tools import list_ports

from app.database import db, transaction
from app.domain.enums import DeviceType
from app.domain.errors import DeviceConfigNotFound
from app.models.device_config import DeviceConfig


class PortResolutionError(RuntimeError):
    """The configured hardware cannot be located safely."""


def resolve_serial_port(hardware_id: str | None) -> str:
    """Return the unique device address for an exact USB serial-number match.

    Addresses are never used as a fallback: an old COM/tty name can belong to
    different hardware after enumeration. This function does not open a port.
    """
    if not isinstance(hardware_id, str) or not hardware_id.strip():
        raise PortResolutionError("Cannot resolve serial port: hardware_id is missing")
    try:
        matches = [p for p in list_ports.comports() if p.serial_number == hardware_id]
    except Exception as exc:
        raise PortResolutionError(f"Cannot enumerate serial ports for {hardware_id!r}: {exc}") from exc
    if not matches:
        raise PortResolutionError(f"No serial port found for hardware_id {hardware_id!r}")
    if len(matches) != 1:
        devices = ", ".join(str(p.device) for p in matches)
        raise PortResolutionError(f"Ambiguous hardware_id {hardware_id!r}: matches multiple ports ({devices})")
    if not matches[0].device:
        raise PortResolutionError(f"Serial port for hardware_id {hardware_id!r} has no device address")
    return matches[0].device


def refresh_port(device_type: DeviceType, hardware_id: str) -> str:
    """Refresh only the address of an existing dashboard device record.

    Discovery is authoritative; the database's last known address is never a
    fallback. Claimed devices may move without changing their claim, settings,
    or identity. Callers keep the running experiment's manifest immutable.
    D2XX callers retain their existing driver discovery and skip this service.
    """
    port = resolve_serial_port(hardware_id)
    row = db.session.execute(
        db.select(DeviceConfig.id, DeviceConfig.port).where(
            DeviceConfig.device_type == device_type,
            DeviceConfig.hardware_id == hardware_id,
        )
    ).first()
    if row is None:
        raise DeviceConfigNotFound(f"{device_type.value}:{hardware_id}")
    if row.port == port:
        return port
    with transaction():
        result = db.session.execute(
            db.update(DeviceConfig)
            .where(DeviceConfig.device_type == device_type,
                   DeviceConfig.hardware_id == hardware_id)
            .values(port=port)
        )
        if result.rowcount != 1:
            raise DeviceConfigNotFound(f"{device_type.value}:{hardware_id}")
    return port
