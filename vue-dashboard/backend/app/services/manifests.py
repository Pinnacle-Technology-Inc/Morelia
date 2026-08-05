"""Resolver: session config to immutable, hashed runtime manifest.

Reads each runnable ``device_flows`` entry from the session, looks up the
referenced device config by id, snapshots its parameters and port into the
manifest, then builds and persists one RuntimeManifest row. No host spawn
happens here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.database import db, transaction
from app.domain.enums import PolicyMode, SinkType
from app.domain.errors import (
    DeviceConfigNotFound,
    EmptySession,
    SessionNotFound,
    SinkLocationExists,
    SinkParentUnavailable,
    UnresolvableSession,
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

_repo = SessionRepository()

# Only these sink categories own an on-disk output location, so only they take
# part in file-path allocation / conflict handling. Service (Influx/Quest) and
# Plot sinks never receive a fabricated file path (see acceptance criterion 2
# and design doc section 3 "Sink categories").
_FILE_SINK_TYPES = frozenset({SinkType.CSV, SinkType.EDF, SinkType.PVFS})


def _path_segment(value: str) -> str:
    """Make a source/sink identity safe to use as a single path segment."""
    return value.replace(":", "-").replace("/", "-").replace("\\", "-")


def _run_file_stem(value: str) -> str:
    """Turn a session display name into one hyphen-delimited filename stem."""
    words = "".join(char if char.isalnum() else " " for char in value).split()
    return "-".join(words).lower()


def _device_file_stem(
    device_type: str,
    device_name: str | None,
    device_config_id: int,
) -> str:
    """Return the mandatory ``<device-code>-<device-name>`` file suffix."""
    match = re.search(r"\d+", device_type)
    code = match.group(0) if match else (_run_file_stem(device_type) or "device")
    name = _run_file_stem(device_name or "") or f"config-{device_config_id}"
    return f"{code}-{name}"


def conflict_label(source_nickname: str | None, sink_name: str) -> str:
    """Identify a file sink by its source nickname plus sink name.

    A source can now own several file sinks, so the source nickname alone no
    longer pinpoints which sink's location collided — the label carries both.

    Public because it is a wire contract: a SinkLocationExists conflict
    reports this label as its ``nickname`` so a client can say which sink's
    location collided. It is outbound only — the fix comes back positionally
    via ``services.session_config.apply_sink_locations``, not keyed by label.
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
    """Assign a default output path for a file sink that omitted sink_location.

    A template run uses its hyphenated session display name plus the mandatory
    device code and name as the filename. An unnamed device uses its stable
    config id. A later same-format output for that device receives an ordinal.

    Unlike an explicit, user-supplied sink_location (which raises
    SinkLocationExists instead — see _build_sink — because the operator
    named that file on purpose), an allocated path lives entirely inside our
    own OUTPUT_DIR namespace: a leftover file at the candidate path (a
    retried spawn, a reused OUTPUT_DIR) is deduplicated rather than failing
    the whole session start. ``create_dir`` is False for build_for_preview(),
    which must stay side-effect-free.

    ``validate=False`` (stop/reconcile re-resolving an already-running
    session — see resolve()) skips the collision check entirely and returns
    the deterministic candidate path as-is. Without this, re-resolving an
    ACTIVE session's manifest would find its own already-open output file
    "claimed" and silently dedupe to a different (-2) path than the one the
    runtime host is actually writing to.
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
    """Resolve one canonical ``sinks[]`` entry into a native ``SinkConfig``.

    Preserves the source-local sink identity (``sink_name``) and order. File
    sinks (CSV/EDF/PVFS) get a resolved absolute ``file_path`` in their
    parameters — either the operator's explicit sink_location (whose parent is
    created if absent, and which is validated for conflicts) or an allocated
    one. Service/Plot sinks carry no fabricated file path and never enter
    filename conflict handling.

    Both branches now guarantee the same thing to the worker: by the time a
    ``file_path`` leaves here, its parent directory exists and is writable.
    """
    sink_type = SinkType(sink_entry["sink_type"])
    sink_name = str(sink_entry["sink_name"])
    parameters = dict(sink_entry.get("sink_parameters") or {})

    if sink_type in _FILE_SINK_TYPES:
        raw_location = sink_entry.get("sink_location")
        if raw_location:
            sink_location = sink_paths.resolve_sink_location(str(raw_location))
            # Parent first: an operator-named destination is created here if it
            # is merely missing, because the worker cannot create it later —
            # output.managed_file.create() only asserts, and it asserts from
            # inside the worker process where the error dies with the exit
            # code. ``create_dir`` is the same side-effect gate the allocated
            # branch uses, so build_for_preview() still touches no filesystem.
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
        # PVFS writer isolation is a runtime safety invariant, not a
        # user-configurable session option. Normalizing it here also upgrades
        # manifests resolved from older stored configurations.
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
    """Resolve a session's device_flows into an immutable hashed Manifest.

    For each entry in device_flows: looks up the referenced device config by
    id, snapshots its parameters into a DeviceFlow value object. After all
    entries resolve successfully the Manifest is built and one RuntimeManifest
    row is persisted.

    Idempotent on hash: re-resolving identical inputs returns the same
    Manifest without writing a duplicate row.

    ``validate_sink_locations=False`` skips the sink_location collision
    check (SinkLocationExists / dedup — see _build_manifest). Pass this when
    re-resolving a session that's already ACTIVE (stop_managed, reconcile):
    the session's own output file legitimately exists by then — it's the
    file the running host is writing to, not a collision to reject. Leave it
    True (the default) for a fresh start, which is the only time this
    resolve is actually deciding whether a NEW file may be created.

    Raises:
        SessionNotFound:      no session with that id.
        EmptySession:         session has no device_flows.
        UnresolvableSession:  a referenced device config is missing or deleted.
    """
    session = _repo.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)

    flows = session.device_flows or []
    if not flows:
        raise EmptySession(session_id)

    manifest = _build_manifest(
        dataflow_id=dataflow_id or session.dataflow_id or str(session_id),
        session_name=session.name,
        policy=session.policy,
        flows=flows,
        session_id_for_errors=session_id,
        validate_sink_locations=validate_sink_locations,
    )

    # Skip insert if this hash is already persisted (idempotent on same inputs).
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
    """Build a runtime manifest from a session-config source without persisting it."""
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
) -> Manifest:
    # Resolve all entries before touching the DB: fail-loud, no partial writes.
    device_flows: list[DeviceFlow] = []
    allocated_counts: dict[tuple[int, SinkType], int] = {}
    for entry in flows:
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
        device_id = f"{device_type}:{hardware_id}"
        device_name = str(config.nickname).strip() if config.nickname else None
        source_nickname = entry.get("nickname")

        # Canonical entries (packet 02) always carry a non-empty ``sinks[]``
        # collection. Guard defensively so a malformed raw entry fails loud
        # rather than producing a DeviceFlow with zero sinks.
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
                parameters=dict(config.parameters or {}),
                sinks=sinks,
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
        # ``session_id_for_errors`` is the persisted session's id for a real
        # resolve() and None for a side-effect-free preview — exactly the
        # populate/None rule for the manifest's durable session identity.
        session_id=session_id_for_errors,
    )
