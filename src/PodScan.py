"""Scan serial ports for POD devices.

This module can be imported as library code via :func:`scan_pods`, or run
directly to print discovered POD devices.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Iterable
from typing import Any

from Morelia.Devices.BasicPodProtocol import Pod


TYPE_MAP = {
    48: "Pod8206HR",
    52: "Pod8229",
    46: "Pod8274D",
    49: "Pod8401HR",
    50: "Pod8480SC",
}


def _clean_port_name(port: str) -> str:
    """Return the serial device path/name from a pyserial display string."""
    return port.split(" - ", 1)[0].split(" ", 1)[0]


def _none_if_empty(value: Any) -> Any | None:
    if value in (None, "", "n/a", "N/A"):
        return None
    return value


def _port_info_dict(port_info: Any) -> dict[str, Any]:
    """Normalize a pyserial port object, dict, or string into a dictionary."""
    if isinstance(port_info, dict):
        info = dict(port_info)
        info["port"] = _clean_port_name(str(info.get("port") or info.get("device")))
        return {key: value for key, value in info.items() if _none_if_empty(value) is not None}

    if isinstance(port_info, str):
        return {"port": _clean_port_name(port_info)}

    info = {
        "port": getattr(port_info, "device", None) or str(port_info),
        "description": getattr(port_info, "description", None),
        "serial_hwid": getattr(port_info, "hwid", None),
        "serial_number": getattr(port_info, "serial_number", None),
        "vid": getattr(port_info, "vid", None),
        "pid": getattr(port_info, "pid", None),
        "manufacturer": getattr(port_info, "manufacturer", None),
        "product": getattr(port_info, "product", None),
        "interface": getattr(port_info, "interface", None),
        "location": getattr(port_info, "location", None),
    }
    return {key: value for key, value in info.items() if _none_if_empty(value) is not None}


def list_serial_ports() -> list[dict[str, Any]]:
    """Return serial port metadata dictionaries for the current platform."""
    try:
        from serial.tools.list_ports import comports
    except ImportError:
        if platform.system() == "Linux" and os.path.isdir("/dev"):
            return [{"port": f"/dev/{name}"} for name in os.listdir("/dev") if name.startswith("ttyUSB")]
        return []

    return [_port_info_dict(port_info) for port_info in comports()]


def _payload_value(pod: Pod, command: str, timeout_sec: int | float = 5) -> Any:
    response = pod.write_read(command, timeout_sec=timeout_sec)
    if not response.payload:
        return None
    if len(response.payload) == 1:
        return response.payload[0]
    return response.payload


def _format_firmware_version(payload: Any) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, tuple):
        return ".".join(str(part) for part in payload)
    return str(payload)


def scan_pods(
    ports: Iterable[str | dict[str, Any] | Any] | None = None,
    pod_cls: type[Pod] = Pod,
    baudrate: int = 9600,
    timeout_sec: int | float = 5,
    include_errors: bool = False,
) -> list[dict[str, Any]]:
    """Scan serial ports and return discovered POD device information.

    Each returned dictionary includes:
    - ``hardware_id``: value returned by the POD ``ID`` command
    - ``port``: serial port path/name used to connect
    - ``device_type``: friendly POD class name when the type code is known
    - ``type_number``: raw numeric POD ``TYPE`` response
    - ``extra_info``: serial descriptor metadata plus optional firmware version
    """
    port_infos = [_port_info_dict(port_info) for port_info in (ports if ports is not None else list_serial_ports())]
    pod_devices = []

    for port_info in port_infos:
        port = port_info["port"]
        pod = None
        try:
            pod = pod_cls(port, baudrate=baudrate)
            if not pod.test_connection():
                continue

            device_type = _payload_value(pod, "TYPE", timeout_sec=timeout_sec)
            hardware_id = _payload_value(pod, "ID", timeout_sec=timeout_sec)
            extra_info = {key: value for key, value in port_info.items() if key != "port"}

            try:
                firmware_version = _format_firmware_version(
                    _payload_value(pod, "FIRMWARE VERSION", timeout_sec=timeout_sec)
                )
            except Exception:
                firmware_version = None
            if firmware_version:
                extra_info["firmware_version"] = firmware_version

            pod_devices.append(
                {
                    "port": port,
                    "hardware_id": hardware_id,
                    "type_number": device_type,
                    "device_type": TYPE_MAP.get(device_type, "Unknown Pod Device"),
                    "extra_info": extra_info,
                }
            )
        except Exception as exc:
            if include_errors:
                pod_devices.append(
                    {
                        "port": port,
                        "hardware_id": None,
                        "type_number": None,
                        "device_type": "Unavailable",
                        "extra_info": {
                            "error": str(exc),
                        },
                    }
                )
        finally:
            if pod is not None:
                cleanup = getattr(pod, "cleanup", None)
                if callable(cleanup):
                    cleanup()
                else:
                    pod.close_port()

    return pod_devices


def print_pod_devices(pod_devices: Iterable[dict[str, Any]]) -> None:
    """Print scanner results in a readable, stable format."""
    for pod_device in pod_devices:
        print(
            "Pod Device found on "
            + str(pod_device["port"])
            + " with type "
            + str(pod_device["type_number"])
            + " ("
            + str(pod_device["device_type"])
            + ") and hardware ID "
            + str(pod_device["hardware_id"])
        )
        for key, value in pod_device.get("extra_info", {}).items():
            print(f"  {key}: {value}")


def main() -> None:
    pod_devices = scan_pods()
    if not pod_devices:
        print("No POD devices found.")
        return
    print_pod_devices(pod_devices)


if __name__ == "__main__":
    main()
