"""Cross-platform POD serial-port discovery with active device identification.

Importing this module does not import pyserial, Morelia, or touch hardware. The
real serial-port lister and the POD prober are imported only when
``detect_pod_devices`` is called without injected collaborators.

Discovery now has two phases:

1. *Enumeration* — list visible serial ports (``port_lister``).
2. *Identification* — open each candidate port and ask the device what it is via
   the POD ``TYPE`` command (``prober``). Identity comes from the FTDI serial
   number exposed by pyserial's port descriptor.

Both collaborators are injectable so tests run with zero real hardware.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from app.domain.enums import DeviceType

PortLister = Callable[[], Iterable[object]]
PodProber = Callable[[str], "PodProbe"]
CandidateFilter = Callable[[object], bool]

# Set as the default value for FTDI used on all pod devices.
_POD_USB_VENDOR_IDS = frozenset({0x0403})

# Numeric POD -> Sring DeviceType.
TYPE_MAP: dict[int, DeviceType] = {
    46: DeviceType.POD8274D,
    48: DeviceType.POD8206HR,
    49: DeviceType.POD8401HR,
    50: DeviceType.POD8480SC,
    52: DeviceType.POD8229,
}


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """Normalized descriptor for one discovered POD serial device."""

    type: DeviceType
    port: str
    hardware_id: str | None
    label: str
    availability: str


@dataclass(frozen=True, slots=True)
class PodProbe:
    """Raw result of trying to talk to one serial port as a POD device.

    ``opened`` — the serial port could be opened at all (False ⇒ busy/in use).
    ``pinged`` — the device answered the POD protocol probe.
    ``type_number`` — the raw numeric ``TYPE`` response, or ``None``.
    ``hardware_id`` — the FTDI serial number from port enumeration, or ``None``.
    """

    opened: bool
    pinged: bool
    type_number: int | None
    hardware_id: str | None


def detect_pod_devices(
    *,
    port_lister: PortLister | None = None,
    prober: PodProber | None = None,
    candidate_filter: CandidateFilter | None = None,
    max_workers: int = 4,
) -> list[DiscoveredDevice]:
    """Return descriptors for serial ports that identify as supported POD devices.
    """
    lister = port_lister or _import_comports()
    probe = prober or _live_prober
    is_candidate = candidate_filter or _is_probe_candidate

    candidates: list[tuple[int, object, str]] = []
    for index, port_info in enumerate(lister()):
        if not is_candidate(port_info):
            continue
        port = _port_name(port_info)
        candidates.append((index, port_info, port))

    if not candidates:
        return []

    worker_count = max(1, min(max_workers, len(candidates)))
    devices_by_index: list[tuple[int, DiscoveredDevice]] = []

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_candidate = {
            executor.submit(probe, port): (index, port_info, port)
            for index, port_info, port in candidates
        }
        for future in as_completed(future_to_candidate):
            index, port_info, port = future_to_candidate[future]
            try:
                result = future.result()
            except Exception:
                continue
            device = _classify(port_info=port_info, port=port, probe=result)
            if device is not None:
                devices_by_index.append((index, device))

    return [device for _, device in sorted(devices_by_index, key=lambda item: item[0])]


def _is_probe_candidate(port_info: object) -> bool:
    """Decide whether *port_info* is an FTDI port worth opening as a possible POD."""
    vid = _attribute(port_info, "vid")
    if vid is not None:
        return _parse_usb_vid(vid) in _POD_USB_VENDOR_IDS

    descriptor_vid = _vid_from_hwid(_attribute(port_info, "hwid"))
    if descriptor_vid is not None:
        return descriptor_vid in _POD_USB_VENDOR_IDS

    # Keep raw string ports injectable for tests/manual probes, but avoid
    # opening arbitrary OS device descriptors when USB metadata says nothing.
    return isinstance(port_info, str)


def _parse_usb_vid(value: object) -> int | None:
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        base = 16 if text.startswith("0x") or len(text) == 4 else 10
        return int(text, base)
    except ValueError:
        return None


def _vid_from_hwid(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).lower()
    marker = "vid:pid="
    if marker not in text:
        return None
    fragment = text.split(marker, 1)[1].split()[0]
    vid = fragment.split(":", 1)[0]
    return _parse_usb_vid(vid)


def _classify(
    *,
    port_info: object,
    port: str,
    probe: PodProbe,
) -> DiscoveredDevice | None:
    """Decide what (if anything) to emit for one probed serial port.

      1. A FTDI candidate that won't open (``not probe.opened``) is reported as
         an unknown, unopenable row with its FTDI serial number.
      2. A port that opens but never answers TYPE is dropped: not a POD.
      3. A port that answers TYPE with a model not in ``TYPE_MAP`` is dropped.
      4. A clean supported POD (``TYPE_MAP`` hit, pinged) is ``available``.
    """
    hardware_id = _optional_text(probe.hardware_id) or _optional_text(
        _attribute(port_info, "serial_number", "serial", "hardware_id", "hwid")
    )

    if not probe.opened:
        return DiscoveredDevice(
            type=DeviceType.UNKNOWN,
            port=port,
            hardware_id=hardware_id,
            label=_label(port_info, port),
            availability="unopenable",
        )

    # A port that opens but cannot answer a POD TYPE request is not a POD.
    if not probe.pinged:
        return None

    # The device answered. Resolve its numeric TYPE to a DeviceType we model.
    # Morelia would label an unrecognized code "Unknown Pod Device", but our
    # schema's `type` is a non-nullable DeviceType. Unknown codes cannot be
    # represented and are dropped.
    device_type = TYPE_MAP.get(probe.type_number) if probe.type_number is not None else None
    if device_type is None:
        return None

    # A modeled POD that responded. Hardware identity comes from the FTDI serial
    # number reported by pyserial, not the POD ``ID`` command.
    return DiscoveredDevice(
        type=device_type,
        port=port,
        hardware_id=hardware_id,
        label=_label(port_info, port),
        availability="available",
    )


# -- live collaborators (imported lazily; never at module import) -------------


def _import_comports() -> PortLister:
    from serial.tools.list_ports import comports

    return comports


def _import_devices_module() -> Any:
    """Import Morelia's device module lazily, honoring ``MORELIA_SRC`` like morelia.py."""
    import importlib

    morelia_src = os.environ.get("MORELIA_SRC")
    if morelia_src and morelia_src not in sys.path:
        sys.path.insert(0, morelia_src)

    return importlib.import_module("Morelia.Devices")


# -- control-queue suppression for discovery probes ---------------------------
#
# Constructing a Morelia ``Pod`` normally spawns a ``queue_server.py`` subprocess
# (see ``PacketManager.initialize_control_queue``) plus fixed ``sleep`` waits for
# it to bind. That IPC only matters on the *streaming* path where the port is
# handed to a worker (``self._port is None``). A discovery probe opens the port
# directly and reads ``TYPE`` straight off pyserial, so the subprocess is spawned,
# sits idle, and is torn down again — 1–3s of pure overhead per port.
#
# We neutralize the spawn by replacing ``initialize_control_queue`` with a no-op
# for the duration of Pod construction. Discovery runs probes 4-wide, so this
# must be safe when multiple threads enter and leave the patch concurrently.

_control_queue_lock = threading.Lock()
_control_queue_depth = 0
_original_init_control_queue: Any = None


@contextlib.contextmanager
def _suppress_control_queue_spawn() -> Iterator[None]:
    """Neutralize ``PacketManager.initialize_control_queue`` while a probe builds
    its ``Pod``, so no ``queue_server.py`` subprocess is spawned.

    Thread-safe: the no-op stays installed until the last concurrent probe exits.
    """
    global _control_queue_depth, _original_init_control_queue

    with _control_queue_lock:
        if _control_queue_depth == 0:
            PacketManager = _import_packet_manager()
            _original_init_control_queue = PacketManager.initialize_control_queue
            PacketManager.initialize_control_queue = lambda self: None
        _control_queue_depth += 1

    try:
        yield

    finally:
        with _control_queue_lock:
            _control_queue_depth -= 1
            if _control_queue_depth == 0:
                PacketManager = _import_packet_manager()
                PacketManager.initialize_control_queue = _original_init_control_queue
                _original_init_control_queue = None



def _import_packet_manager() -> type:
    """Import Morelia's ``PacketManager`` lazily (honors ``MORELIA_SRC``)."""
    import importlib

    morelia_src = os.environ.get("MORELIA_SRC")
    if morelia_src and morelia_src not in sys.path:
        sys.path.insert(0, morelia_src)

    module = importlib.import_module("Morelia.Devices.SerialPorts.queue_manager")
    return module.PacketManager


def _live_prober(port: str, *, baudrate: int = 9600, timeout_sec: float = 2.0) -> PodProbe:
    """Open port as a POD device and read its ``TYPE`` with a bounded timeout.

    Always releases the handle — discovery must not retain a port after scanning.
    """
    devices_module = _import_devices_module()
    pod_cls = devices_module.Pod
    try:
        with _suppress_control_queue_spawn():
            pod = pod_cls(port, baudrate=baudrate)
    except Exception:
        return PodProbe(opened=False, pinged=False, type_number=None, hardware_id=None)

    try:
        type_number = _payload_value(pod, "TYPE", timeout_sec)
        if not isinstance(type_number, int) or type_number not in TYPE_MAP:
            return PodProbe(
                opened=True,
                pinged=True,
                type_number=type_number if isinstance(type_number, int) else None,
                hardware_id=None,
            )

        return PodProbe(
            opened=True,
            pinged=True,
            type_number=type_number,
            hardware_id=None,
        )
    except Exception:
        return PodProbe(opened=True, pinged=False, type_number=None, hardware_id=None)
    finally:
        _cleanup_pod(pod)


def _payload_value(pod: Any, command: str, timeout_sec: float) -> Any:
    response = pod.write_read(command, timeout_sec=timeout_sec)
    payload = getattr(response, "payload", None)
    if not payload:
        return None
    if len(payload) == 1:
        return payload[0]
    return payload


def _cleanup_pod(pod: Any) -> None:
    cleanup = getattr(pod, "cleanup", None)
    if callable(cleanup):
        cleanup()
        return
    close = getattr(pod, "close_port", None)
    if callable(close):
        close()


# -- port_info normalization helpers ------------------------------------------


def _port_name(port_info: object) -> str:
    device = _attribute(port_info, "device", "name")
    if device is not None:
        return str(device)
    return str(port_info)


def _label(port_info: object, port: str) -> str:
    description = _optional_text(_attribute(port_info, "description"))
    if description:
        return description
    return port


def _attribute(value: object, *names: str) -> Any | None:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
