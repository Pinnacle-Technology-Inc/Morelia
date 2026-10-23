"""Build runtime settings from session, device, and sink configs.

resolve() saves the manifest. build_for_preview() does not. Neither starts a process.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.services.device_ports import PortResolutionError, refresh_port

from app.database import db, transaction
from app.domain.enums import DeviceType, PolicyMode, SinkType
from app.domain.errors import (
    DeviceConfigNotFound,
    EmptySession,
    InvalidSessionEntry,
    SessionNotFound,
    SinkLocationExists,
    SinkParentUnavailable,
    UnknownConfigType,
    UnresolvableSession,
    UnsupportedDeviceType,
)
from app.models.runtime_manifest import RuntimeManifest
from app.repositories.sessions import SessionRepository
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)
from app.services import device_configs as _device_configs
from app.services import session_config as _session_config
from app.services import sink_paths
from app.services.registry import lookup_device

_repo = SessionRepository()

# Only file sinks need an output path and file-conflict checks.
_FILE_SINK_TYPES = frozenset({SinkType.CSV, SinkType.EDF, SinkType.PVFS})


def _path_segment(value: str) -> str:
    """Replace colons and slashes in a path segment."""
    return value.replace(":", "-").replace("/", "-").replace("\\", "-")


def _run_file_stem(value: str) -> str:
    """Turn a display name into lowercase words joined by hyphens."""
    words = "".join(char if char.isalnum() else " " for char in value).split()
    return "-".join(words).lower()


def _device_file_stem(
    device_type: str,
    device_name: str | None,
    device_config_id: int,
) -> str:
    """Build the device-code/name suffix. Use the config ID if unnamed."""
    match = re.search(r"\d+", device_type)
    code = match.group(0) if match else (_run_file_stem(device_type) or "device")
    name = _run_file_stem(device_name or "") or f"config-{device_config_id}"
    return f"{code}-{name}"


def conflict_label(source_nickname: str | None, sink_name: str) -> str:
    """Label a file conflict as source:sink, or just sink if the source is unnamed.

    Used for display, not as an ID when submitting a fix.
    """
    if source_nickname:
        return f"{source_nickname}:{sink_name}"
    return sink_name


# Retained so existing internal callers/tests keep working.
_conflict_label = conflict_label


def _allocate_sink_location(
    *,
    dataflow_id: str,
    session_name: str | None,
    device_id: str,
    device_type: str,
    device_name: str | None,
    device_config_id: int,
    sink_name: str,
    sink_type: SinkType,
    create_dir: bool,
    file_ordinal: int = 1,
    validate: bool = True,
) -> str:
    """Choose an output path when the user did not supply one.

    - Name it from the session and device, or the device and sink IDs.
    - Number extra outputs of the same format for one device.
    - Choose a free filename unless validate=False.
    - Create the directory only when create_dir=True.
    """
    safe_session_name = _run_file_stem(session_name) if session_name else ""
    if safe_session_name:
        safe_session_name = (
            f"{safe_session_name}-"
            f"{_device_file_stem(device_type, device_name, device_config_id)}"
        )
    safe_device_id = _path_segment(device_id)
    safe_sink_name = _path_segment(sink_name)
    identity = f"{safe_device_id}-{safe_sink_name}"
    if safe_session_name and file_ordinal > 1:
        safe_session_name = f"{safe_session_name}-{file_ordinal}"
    filename = (
        f"{safe_session_name}.{sink_type.value}"
        if safe_session_name
        else f"{identity}.{sink_type.value}"
    )
    relative = Path(dataflow_id) / filename
    if create_dir:
        (sink_paths.output_root() / dataflow_id).mkdir(parents=True, exist_ok=True)
    resolved = sink_paths.resolve_sink_location(str(relative))
    if not validate:
        return resolved
    candidate = sink_paths.next_available_path(Path(resolved))
    return str(candidate)


def _build_sink(
    sink_entry: Mapping[str, Any],
    *,
    dataflow_id: str,
    session_name: str | None,
    device_id: str,
    device_type: str,
    device_name: str | None,
    device_config_id: int,
    source_nickname: str | None,
    session_id_for_errors: int | None,
    validate_sink_locations: bool,
    create_dir: bool,
    default_file_ordinal: int = 1,
) -> SinkConfig:
    """Build one sink's runtime settings.

    - File sinks: resolve the supplied path or choose a default.
    - Reject claimed user paths when validation is enabled.
    - Other sinks: keep their settings without adding a file path.
    """
    sink_type = SinkType(sink_entry["sink_type"])
    sink_name = str(sink_entry["sink_name"])
    parameters = dict(sink_entry.get("sink_parameters") or {})

    if sink_type in _FILE_SINK_TYPES:
        raw_location = sink_entry.get("sink_location")
        if raw_location:
            sink_location = sink_paths.resolve_sink_location(str(raw_location))
            # Prepare the parent directory before the worker starts. Skip for previews.
            if create_dir:
                parent_issue = sink_paths.ensure_sink_parent(sink_location)
                if parent_issue is not None:
                    directory, reason = parent_issue
                    raise SinkParentUnavailable(
                        sink_location,
                        directory=directory,
                        reason=reason,
                        nickname=_conflict_label(source_nickname, sink_name),
                    )
            if validate_sink_locations and sink_paths.path_is_claimed(sink_location):
                suggested = sink_paths.next_available_path(
                    Path(sink_location), session_id=session_id_for_errors
                )
                raise SinkLocationExists(
                    sink_location,
                    nickname=_conflict_label(source_nickname, sink_name),
                    suggested_location=str(suggested),
                )
        else:
            sink_location = _allocate_sink_location(
                dataflow_id=dataflow_id,
                session_name=session_name,
                device_id=device_id,
                device_type=device_type,
                device_name=device_name,
                device_config_id=device_config_id,
                sink_name=sink_name,
                sink_type=sink_type,
                create_dir=create_dir,
                file_ordinal=default_file_ordinal,
                validate=validate_sink_locations,
            )
        parameters["file_path"] = sink_location

    if sink_type is SinkType.PVFS:
        # Always run PVFS writing in a separate process, including for older configs.
        parameters["use_writer_process"] = True

    return SinkConfig(
        sink_id=f"{device_id}:{sink_name}",
        name=sink_name,
        type=sink_type,
        parameters=parameters,
    )


def resolve(
    session_id: int,
    *,
    dataflow_id: str | None = None,
    validate_sink_locations: bool = True,
) -> Manifest:
    """Build and save a session's runtime manifest.

    - Validate file paths for a new run.
    - For stop/reconcile, pass validate_sink_locations=False to reuse saved settings.
    - Save only when the manifest hash is new.
    - Raise an error for a missing session, empty session, or invalid config.
    """
    session = _repo.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)

    resolved_dataflow_id = dataflow_id or session.dataflow_id or str(session_id)
    if not validate_sink_locations:
        # Stop/reconcile must keep the running process's manifest, even if ports changed.
        persisted = db.session.scalars(
            db.select(RuntimeManifest)
            .where(
                RuntimeManifest.session_id == session_id,
                RuntimeManifest.content["dataflow_id"].as_string() == resolved_dataflow_id,
            )
            .order_by(RuntimeManifest.id.desc())
        ).first()
        if persisted is not None:
            saved = Manifest.from_dict(persisted.content)
            if saved.duration_seconds != session.duration_seconds:
                raise InvalidSessionEntry("duration_seconds", "does not match the immutable runtime manifest")
            return saved

    flows = session.device_flows or []
    if not flows:
        raise EmptySession(session_id)

    manifest = _build_manifest(
        dataflow_id=resolved_dataflow_id,
        session_name=session.name,
        policy=session.policy,
        flows=flows,
        session_id_for_errors=session_id,
        validate_sink_locations=validate_sink_locations,
        duration_seconds=session.duration_seconds,
    )

    # Avoid saving the same manifest twice.
    existing = db.session.scalars(
        db.select(RuntimeManifest).where(RuntimeManifest.hash == manifest.hash)
    ).first()
    if existing is None:
        with transaction():
            db.session.add(
                RuntimeManifest(
                    hash=manifest.hash,
                    schema_version=manifest.schema_version,
                    session_id=session_id,
                    content=manifest.to_dict(),
                )
            )

    return manifest


def build_for_preview(
    session_config_source: str | Mapping[str, Any],
    *,
    format: str | None = None,
) -> Manifest:
    """Preview runtime settings without saving them, creating directories, or probing devices."""
    data = _session_config._parse_source(session_config_source, format=format)
    canonical = _session_config._canonicalize(data)
    return _build_manifest(
        dataflow_id=str(canonical.get("name") or "preview"),
        session_name=str(canonical.get("name") or "preview"),
        policy=canonical["policy"],
        flows=canonical["device_flows"],
        session_id_for_errors=None,
    )


def _build_manifest(
    *,
    dataflow_id: str,
    session_name: str | None,
    policy: PolicyMode | str | None,
    flows: list[Mapping[str, Any]],
    session_id_for_errors: int | None,
    validate_sink_locations: bool = True,
    duration_seconds: int | None = None,
) -> Manifest:
    """Load device configs and build their runtime sink settings."""
    device_flows: list[DeviceFlow] = []
    allocated_counts: dict[tuple[int, SinkType], int] = {}
    for flow_index, entry in enumerate(flows):
        config_id = entry.get("device_config_id")
        if config_id is None:
            if session_id_for_errors is None:
                raise DeviceConfigNotFound(0)
            raise UnresolvableSession(
                session_id_for_errors,
                "missing device_config_id",
            )

        try:
            normalized_config_id = int(config_id)
        except (TypeError, ValueError):
            if session_id_for_errors is None:
                raise DeviceConfigNotFound(0) from None
            raise UnresolvableSession(session_id_for_errors, str(config_id)) from None

        config = _device_configs.get_by_id(normalized_config_id)
        if config is None:
            if session_id_for_errors is None:
                raise DeviceConfigNotFound(normalized_config_id)
            raise UnresolvableSession(session_id_for_errors, str(normalized_config_id))

        hardware_id = str(config.hardware_id)
        port = str(config.port)
        device_type = str(
            config.device_type.value
            if hasattr(config.device_type, "value")
            else config.device_type
        )
        raw_parameters = config.parameters or {}
        try:
            if not isinstance(raw_parameters, Mapping):
                raise ValueError("parameters must be a mapping")
            device_spec = lookup_device(device_type, raw_parameters)
        except (UnknownConfigType, UnsupportedDeviceType, ValueError) as exc:
            raise InvalidSessionEntry(
                f"device_flows[{flow_index}].device_config_id",
                f"persisted device config {normalized_config_id!r} ({device_type!r}) "
                f"is invalid: {exc}",
            ) from exc
        connection = None
        # Explicit connection preferences resolve once, without opening hardware.
        # Configs without connection preferences keep their existing port resolution.
        if session_id_for_errors is not None and validate_sink_locations and getattr(config, "connection", None):
            from app.services.connections import resolve_connection
            try:
                connection = resolve_connection(hardware_id, config.connection, device_type)
                port = str(connection["address"])
                if config.port != port:
                    with transaction():
                        config.port = port
            except PortResolutionError as exc:
                raise InvalidSessionEntry(f"device_flows[{flow_index}].device_config_id", str(exc)) from exc
        if (
            session_id_for_errors is not None
            and validate_sink_locations
            and not getattr(config, "connection", None)
            and not raw_parameters.get("use_d2xx", False)
        ):
            try:
                port = refresh_port(DeviceType(device_type), config.hardware_id)
            except PortResolutionError as exc:
                raise InvalidSessionEntry(
                    f"device_flows[{flow_index}].device_config_id", str(exc)
                ) from exc
        device_id = f"{device_type}:{hardware_id}"
        device_name = str(config.nickname).strip() if config.nickname else None
        source_nickname = entry.get("nickname")

        # Each device must have at least one sink.
        raw_sinks = entry.get("sinks")
        if not isinstance(raw_sinks, (list, tuple)) or not raw_sinks:
            if session_id_for_errors is None:
                raise DeviceConfigNotFound(normalized_config_id)
            raise UnresolvableSession(
                session_id_for_errors,
                f"device flow for config {normalized_config_id} has no sinks",
            )

        built_sinks: list[SinkConfig] = []
        for sink_entry in raw_sinks:
            sink_type = SinkType(sink_entry["sink_type"])
            ordinal = 1
            if sink_type in _FILE_SINK_TYPES and not sink_entry.get("sink_location"):
                allocation_key = (normalized_config_id, sink_type)
                ordinal = allocated_counts.get(allocation_key, 0) + 1
                allocated_counts[allocation_key] = ordinal
            built_sinks.append(
                _build_sink(
                    sink_entry,
                    dataflow_id=dataflow_id,
                    session_name=session_name,
                    device_id=device_id,
                    device_type=device_type,
                    device_name=device_name,
                    device_config_id=normalized_config_id,
                    source_nickname=source_nickname,  # type: ignore[arg-type]
                    session_id_for_errors=session_id_for_errors,
                    validate_sink_locations=validate_sink_locations,
                    create_dir=session_id_for_errors is not None,
                    default_file_ordinal=ordinal,
                )
            )
        sinks = tuple(built_sinks)

        device_flows.append(
            DeviceFlow(
                device_id=device_id,
                name=str(config.source_template or device_type),
                nickname=source_nickname,  # type: ignore[arg-type]
                hardware_id=hardware_id,
                port=port,
                parameters=device_spec.as_dict(),
                sinks=sinks,
                connection=connection,
            )
        )

    resolved_policy = policy or PolicyMode.RECOMMEND
    if not isinstance(resolved_policy, PolicyMode):
        resolved_policy = PolicyMode(str(resolved_policy))

    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id=dataflow_id,
        policy=resolved_policy,
        device_flows=tuple(device_flows),
        # Previews have no saved session ID.
        session_id=session_id_for_errors,
        duration_seconds=duration_seconds,
    )
