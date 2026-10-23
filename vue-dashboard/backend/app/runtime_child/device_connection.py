"""Adapt frozen run connections to Morelia without re-running Auto policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.connections import normalize_resolved_connection

if TYPE_CHECKING:
    from app.services.connections import EndpointInventoryCache


def constructor_connection_kwargs(
    device_flow, *, legacy_baudrate: int = 9600, legacy_use_d2xx: bool = False,
) -> dict:
    """Keep legacy constructor shape; new bindings explicitly select native I/O."""
    binding = getattr(device_flow, "connection", None)
    if binding is None:
        return {"baudrate": legacy_baudrate, "use_d2xx": legacy_use_d2xx}
    binding = normalize_resolved_connection(binding, hardware_id=device_flow.hardware_id)
    return {
        "baudrate": binding["baudrate"],
        "use_d2xx": binding["transport"] == "d2xx",
        "d2xx_serial_only": binding["transport"] == "d2xx",
        "flow_control": binding["flow_control"],
        "read_timeout_ms": binding["read_timeout_ms"],
        "write_timeout_ms": binding["write_timeout_ms"],
    }


def apply_or_defer_parameters(pod, parameters: dict, device_flow) -> None:
    """Native constructors defer open; apply hardware setters in the worker.

    Inspect descriptors without invoking their getters. The concrete source's
    get_dict transports pending settings to spawned workers and recovery.
    """
    import inspect

    for key in parameters:
        descriptor = inspect.getattr_static(pod, key, None)
        if descriptor is None or (isinstance(descriptor, property) and descriptor.fset is None):
            raise ValueError(f"unsupported {type(pod).__name__} parameter: {key!r}")
    binding = getattr(device_flow, "connection", None)
    if getattr(pod, "_backend_managed", False) or (
        binding is not None and binding["transport"] == "d2xx"
    ):
        pending = dict(parameters)
        if device_flow.parameters.get("sample_rate") is not None:
            pending["sample_rate"] = device_flow.parameters["sample_rate"]
        pod._startup_parameters = pending
        return
    for key, value in parameters.items():
        setattr(pod, key, value)


def current_connection_address(
    device_flow, device_type, *, inventory: EndpointInventoryCache | None = None,
) -> str:
    """Select an address from the run contract; this is not a presence check.

    Native selectors are immutable. VCP addresses may move on replug and still
    need a current identity-based lookup. Native opening verifies handle identity.
    """
    binding = getattr(device_flow, "connection", None)
    if binding is None:
        if device_flow.parameters.get("use_d2xx", False):
            return device_flow.port
        from app.services.device_ports import refresh_port
        return refresh_port(device_type, device_flow.hardware_id)

    binding = normalize_resolved_connection(binding, hardware_id=device_flow.hardware_id)
    if binding["transport"] == "d2xx":
        return str(binding["address"])
    from app.services.connections import resolve_connection
    resolved = resolve_connection(
        device_flow.hardware_id,
        {
            "preference": binding["transport"],
            **{key: binding[key] for key in (
                "baudrate", "flow_control", "read_timeout_ms", "write_timeout_ms",
            )},
        },
        device_type,
        **({"inventory": inventory} if inventory is not None else {}),
    )
    if resolved["backend"] != binding["backend"]:
        raise ValueError("Recovery cannot change the frozen connection backend")
    if resolved.get("physical_id", resolved["hardware_id"]) != binding.get(
        "physical_id", binding["hardware_id"],
    ):
        raise ValueError("Recovery cannot change the frozen physical identity")
    return str(resolved["address"])


def current_connection_present(
    device_flow, device_type, *, inventory: EndpointInventoryCache | None = None,
) -> bool:
    """Observe availability separately; unknown inventory raises, never True."""
    binding = getattr(device_flow, "connection", None)
    if binding is None and device_flow.parameters.get("use_d2xx", False):
        # Older native manifests have no resolved connection object. Their
        # explicit serial still needs a live observation, not bool(saved_port).
        from app.domain.connections import normalize_connection
        profile = normalize_connection({"preference": "d2xx"})
        profile.pop("preference")
        binding = {**profile, "transport": "d2xx", "backend": "ftd2xx",
                   "flow_control": "rts_cts",
                   "address": device_flow.port, "hardware_id": device_flow.hardware_id,
                   "physical_id": device_flow.port, "selection_reason": "legacy_explicit"}
    if binding is not None:
        binding = normalize_resolved_connection(binding, hardware_id=device_flow.hardware_id)
        if binding["transport"] == "d2xx":
            from app.services.connections import native_connection_present
            return native_connection_present(
                binding, **({"inventory": inventory} if inventory is not None else {}),
            )
    from app.services.connections import ConnectionResolutionError
    try:
        return bool(current_connection_address(
            device_flow, device_type,
            **({"inventory": inventory} if inventory is not None else {}),
        ))
    except ConnectionResolutionError as exc:
        if exc.code == "not_found":
            return False
        raise


def routing_key(address: str, *, native: bool = False) -> str:
    """Native serials are case-sensitive; OS COM paths keep legacy folding."""
    return address if native else address.lower()
