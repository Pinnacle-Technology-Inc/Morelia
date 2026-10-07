"""Validated physical-device connection preferences, separate from templates."""

from collections.abc import Mapping
from typing import Any


class ConnectionError(ValueError):
    """Connection settings cannot be used safely."""


def normalize_connection(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate connection preferences and fill in missing defaults.

    Omitted settings default to VCP, 9600 baud, and 5000 ms timeouts.
    Leave unspecified flow control for the resolver to choose: none for VCP,
    RTS/CTS for D2XX. This function does not select or open a device.
    """
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ConnectionError("connection must be an object")
    allowed = {"preference", "baudrate", "flow_control", "read_timeout_ms", "write_timeout_ms"}
    unknown = set(value) - allowed
    if unknown:
        raise ConnectionError(
            f"unknown connection settings: {', '.join(sorted(map(str, unknown)))}"
        )
    preference = value.get("preference", "vcp")
    if preference not in ("vcp", "d2xx", "auto"):
        raise ConnectionError("connection.preference must be vcp, d2xx, or auto")
    result = {"preference": preference}
    for key, default in (("baudrate", 9600), ("read_timeout_ms", 5000), ("write_timeout_ms", 5000)):
        number = value.get(key, default)
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ConnectionError(f"connection.{key} must be a positive integer")
        result[key] = number
    if "flow_control" in value:
        if value["flow_control"] not in ("none", "rts_cts"):
            raise ConnectionError("connection.flow_control must be none or rts_cts")
        result["flow_control"] = value["flow_control"]
    return result


def validate_device_connection(
    device_type: object, value: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Validate preferences and reject explicit D2XX for unsupported devices.

    Return the settings with defaults applied. An ``auto`` preference remains
    for the resolver to decide when it selects an available endpoint.
    """
    connection = normalize_connection(value)
    type_key = getattr(device_type, "value", device_type)
    if connection["preference"] == "d2xx" and type_key not in ("pod8206hr", "pod8401hr"):
        raise ConnectionError(f"D2XX is not supported for device type {type_key!r}")
    return connection


def normalize_resolved_connection(
    value: Mapping[str, Any],
    *,
    hardware_id: str | None = None,
) -> dict[str, Any]:
    """Check that a selected connection's transport, backend, and identity agree.

    Return a copy without choosing another endpoint or opening hardware.
    When supplied, ``hardware_id`` must match the connection's device identity.
    D2XX addresses must match the USB serial. The resolver may provide that
    serial as ``physical_id`` when the device's hardware ID is an OS alias;
    user preferences cannot set this field.
    """
    if not isinstance(value, Mapping):
        raise ConnectionError("resolved connection must be an object")
    required = {
        "transport",
        "backend",
        "address",
        "hardware_id",
        "baudrate",
        "flow_control",
        "read_timeout_ms",
        "write_timeout_ms",
        "selection_reason",
    }
    if not required.issubset(value) or set(value) - required - {"physical_id"}:
        raise ConnectionError(
            "resolved connection requires: "
            + ", ".join(sorted(required))
            + "; physical_id is the only optional field"
        )
    if (value["transport"], value["backend"]) not in (("vcp", "pyserial"), ("d2xx", "ftd2xx")):
        raise ConnectionError("resolved connection transport/backend pair is unsupported")
    for key in ("address", "hardware_id", "selection_reason"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ConnectionError(f"resolved connection.{key} must be a nonempty string")
    if hardware_id is not None and value["hardware_id"] != hardware_id:
        raise ConnectionError("resolved connection hardware_id differs from device identity")
    physical_id = value.get("physical_id", value["hardware_id"])
    if "physical_id" in value and (not isinstance(physical_id, str) or not physical_id.strip()):
        raise ConnectionError("resolved connection.physical_id must be a nonempty string")
    if value["transport"] == "d2xx" and value["address"] != physical_id:
        raise ConnectionError("D2XX address must exactly match physical_id or hardware_id")
    normalize_connection(
        {
            "preference": value["transport"],
            **{
                key: value[key]
                for key in ("baudrate", "flow_control", "read_timeout_ms", "write_timeout_ms")
            },
        }
    )
    return dict(value)
