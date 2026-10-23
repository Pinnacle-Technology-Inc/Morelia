"""Joined device list for operator-facing pool state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from app.discovery.pod_scan import DiscoveredDevice
from app.domain.connections import normalize_connection
from app.domain.enums import DeviceClaimState, DeviceType
from app.models.device_config import DeviceConfig
from app.services import device_configs, device_registrations, device_templates
from app.services.connections import NATIVE_DEVICE_TYPES


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
    connection: dict | None = None
    endpoints: tuple[dict[str, object], ...] = ()
    transport: str | None = None
    selected_transport: str | None = None
    connection_error: str | None = None
    scan_key: str | None = None
    probe_state: str = "complete"

    def as_dict(self) -> dict[str, object | None]:
        return asdict(self)


def build_pool_rows(
    discovered: list[DiscoveredDevice], *, scan_state: str = "complete", warnings=(),
) -> list[dict[str, object | None]]:
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
    matched_devices: set[int] = set()
    failed_providers = {warning.get("transport") for warning in warnings
                        if warning.get("code") in ("enumeration_failed", "backend_unavailable")}

    for config in device_configs.list():
        identity = _identity(DeviceType(config.device_type), config.hardware_id)
        configured_identities.add(identity)
        seen = scan_by_identity.get(identity)
        if seen is None:
            pending = [device for device in discovered
                       if device.hardware_id == config.hardware_id and device.probe_state != "complete"]
            if len(pending) == 1:
                seen = pending[0]
        if seen is not None:
            matched_devices.add(id(seen))
        row = _configured_row(config, seen)
        preference = row.connection["preference"]
        inventory_unknown = bool(failed_providers) if preference == "auto" else preference in failed_providers
        if seen is None and scan_state == "enumerating" and row.connection_error != "claimed":
            row = replace(row, availability="unverified", connection_error=None,
                          probe_state="queued")
        elif inventory_unknown and row.availability == "unavailable" and row.connection_error == "not_found":
            row = replace(row, connection_error="enumeration_failed")
        if scan_state == "failed" and row.connection_error != "claimed" and (seen is None or row.probe_state != "complete"):
            row = replace(row, availability="unavailable", connection_error="scan_failed", probe_state="complete")
        rows.append(row)

    for device in discovered:
        if id(device) in matched_devices:
            continue
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

    if scan_state == "failed":
        rows = [replace(row, availability="unavailable", connection_error="scan_failed", probe_state="complete")
                if row.probe_state != "complete" else row for row in rows]
    return [row.as_dict() for row in rows]


def _configured_row(
    config: DeviceConfig,
    seen: DiscoveredDevice | None,
) -> DevicePoolRow:
    claim_state = DeviceClaimState(config.claim_state)
    connection = normalize_connection(getattr(config, "connection", None))
    availability = seen.availability if seen is not None else "unavailable"
    selected = None
    connection_error = None if seen is not None else "not_found"
    if seen is not None and seen.endpoints:
        preference = connection["preference"]
        selected = next((ep for ep in seen.endpoints if ep["transport"] == preference), None)
        if preference == "auto":
            # The worker owns fallback and reports the actual winning/last attempt.
            selected = next((ep for ep in seen.endpoints if ep["transport"] == seen.transport), None)
        availability = (
            "unavailable"
            if selected is None
            else selected.get("availability", seen.availability)
        )
        connection_error = "not_found" if selected is None else selected.get("error_code")
        if availability == "unverified" and seen.probe_state == "complete":
            availability, connection_error = "unavailable", "not_attempted"
        if selected is None and seen.availability == "unopenable":
            blocked_error = next((ep.get("error_code") for ep in seen.endpoints
                                  if ep.get("availability") == "unopenable" and ep.get("error_code")), None)
            if blocked_error:
                availability, connection_error = "unopenable", blocked_error
        if (
            selected
            and selected["transport"] == "d2xx"
            and DeviceType(config.device_type).value not in NATIVE_DEVICE_TYPES
        ):
            availability = "unopenable"
            connection_error = "transport_unsupported"
    if DeviceType(config.device_type).value not in NATIVE_DEVICE_TYPES:
        availability = "unopenable"
        connection_error = "unsupported_model"
    if seen is not None and seen.probe_state != "complete":
        availability, connection_error = "unverified", None
    if claim_state is not DeviceClaimState.FREE:
        availability, connection_error = "unopenable", "claimed"
    selected_transport = (
        str(selected["transport"])
        if selected
        else (seen.transport if seen and not seen.endpoints else None)
    )
    return DevicePoolRow(
        id=config.id,
        type=DeviceType(config.device_type).value,
        port=str(selected["address"])
        if selected
        else seen.port
        if seen is not None
        else config.port,
        hardware_id=config.hardware_id,
        color=config.color,
        availability=availability,
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
        connection=connection,
        endpoints=seen.endpoints if seen else (),
        transport=selected_transport,
        selected_transport=selected_transport,
        connection_error=connection_error,
        # A configured slot already has a durable identity, including when
        # conflicting profiles exist for one physical device.
        scan_key=f"config:{config.id}",
        probe_state=seen.probe_state if seen and claim_state is DeviceClaimState.FREE else "complete",
    )


def _unconfigured_row(
    device: DiscoveredDevice,
    registration=None,
) -> DevicePoolRow:
    nickname = registration.nickname if registration is not None else None
    supported = device.type.value in NATIVE_DEVICE_TYPES
    selected = next((ep for ep in device.endpoints if ep["transport"] == device.transport), None)
    connection_error = selected.get("error_code") if selected else None
    if not supported:
        connection_error = (
            "unsupported_model"
            if device.type is not DeviceType.UNKNOWN
            else connection_error or next((ep.get("error_code") for ep in device.endpoints if ep.get("error_code")), "unidentified")
        )
    pending = device.probe_state != "complete"
    if pending:
        connection_error = None
    return DevicePoolRow(
        id=None,
        type=device.type.value,
        port=device.port,
        hardware_id=device.hardware_id,
        color=None,
        availability="unverified" if pending else device.availability if supported or device.type is DeviceType.UNKNOWN else "unopenable",
        status="unconfigured",
        owner=None,
        nickname=nickname,
        label=nickname or device.label,
        source_template=None,
        source_template_hash=None,
        configuration_hash=None,
        connection=normalize_connection(
            {"preference": "auto", "baudrate": selected.get("baudrate", 9600) if selected else 9600}
        ),
        endpoints=device.endpoints,
        transport=device.transport,
        selected_transport=device.transport,
        connection_error=connection_error,
        scan_key=device.scan_key or f"device:{device.hardware_id or device.port}",
        probe_state=device.probe_state,
    )


def _identity(device_type: DeviceType, hardware_id: str | None) -> str:
    return f"{device_type.value}:{hardware_id or ''}"
