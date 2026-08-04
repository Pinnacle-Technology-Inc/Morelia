"""Session-config validation plus TOML/JSON import/export.

This module accepts portable session-template entries that reference a device
template by path plus local instantiation details. Persisted
``Session.device_flows`` entries reference runnable ``device_config_id`` rows.
It accepts only the new session-config format, not legacy Morelia experiment
manifests; the legacy shape needs a deliberate migration/import adapter if it
becomes required.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.domain.enums import DeviceType, PolicyMode, SinkCategory
from app.domain.errors import (
    DeviceConfigNotFound,
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    SinkLocationExists,
    UnknownConfigType,
)
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.services import device_configs, device_templates, sink_paths
from app.services.registry import lookup_sink, sink_parameter_schema

_repo = SessionRepository()

# Top-level fields accepted on a raw device-flow entry. ``sinks`` is the
# canonical multi-sink collection; ``sink_type``/``sink_location``/
# ``sink_parameters`` are the retained legacy flattened form (a single sink
# expressed at the top level). Mixing the two forms is rejected (see
# ``_resolve_sinks``).
_ENTRY_FIELDS = {
    "nickname",
    "hardware_id",
    "port",
    "device_config_id",
    "device_template_path",
    "device_template_content_hash",
    "sinks",
    "sink_type",
    "sink_location",
    "sink_parameters",
}
# The legacy flattened sink fields, checked as a group when deciding whether an
# entry mixes the two supported input shapes.
_LEGACY_SINK_FIELDS = {"sink_type", "sink_location", "sink_parameters"}
# Fields accepted inside one canonical ``sinks[]`` object.
_SINK_FIELDS = {"sink_name", "sink_type", "sink_location", "sink_parameters"}
# Parameter keys that look like inline secrets and are rejected outright. Only
# non-secret values and secret *references* (e.g. Influx's ``api_token_env``,
# an environment-variable name) may appear in a sink's parameters. See
# docs/all-sink-support-design-and-gap-audit.md section 4 "Secrets".
_SECRET_PARAM_KEYS = frozenset({"api_token", "token", "password", "secret"})
_SECRET_PARAM_SUFFIXES = ("_token", "_password", "_secret")
_SESSION_FIELDS = {"name", "policy", "device_flows"}
_SLUG_PATTERN = re.compile(r"[^0-9A-Za-z]+")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _normalize_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidSessionEntry(field, "must be a string")
    normalized = value.strip()
    if not normalized:
        raise InvalidSessionEntry(field, "is required")
    return normalized


def _normalize_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise InvalidSessionEntry(field, "must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise InvalidSessionEntry(field, "must be an integer") from None
    if normalized <= 0:
        raise InvalidSessionEntry(field, "must be positive")
    return normalized


def _normalize_index(value: Any, field: str) -> int:
    """Like ``_normalize_int`` but zero-based — positions start at 0, not 1."""
    if isinstance(value, bool):
        raise InvalidSessionEntry(field, "must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise InvalidSessionEntry(field, "must be an integer") from None
    if normalized < 0:
        raise InvalidSessionEntry(field, "must not be negative")
    return normalized


def _policy_value(value: Any) -> PolicyMode:
    if value is None:
        return PolicyMode.RECOMMEND
    if isinstance(value, PolicyMode):
        return value
    try:
        return PolicyMode(str(value))
    except ValueError:
        allowed = ", ".join(policy.value for policy in PolicyMode)
        raise ValueError(f"policy must be one of: {allowed}") from None


def _slug(value: Any, *, fallback: str) -> str:
    if not isinstance(value, str):
        value = ""
    normalized = _SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized or fallback


def _template_content_for_config(config) -> dict[str, Any]:
    return {
        "type": DeviceType(config.device_type).value,
        "parameters": dict(config.parameters or {}),
    }


def _params_hash8(content: Mapping[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def _jsonify(value: Any) -> Any:
    """Return a JSON-native copy of a canonical parameter value.

    The registry stores sequence parameters (e.g. ``channel_names``,
    ``device_preferences``) as tuples so specs stay hashable. Canonical session
    config, by contrast, is persisted and round-tripped as JSON/TOML, where a
    tuple has no representation. Normalizing to plain lists here keeps a sink's
    parameters equal across an import/export round trip regardless of the
    serialization format or a DB reload.
    """
    if isinstance(value, tuple) or isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _jsonify(item) for key, item in value.items()}
    return value


def _reject_secret_params(params: Mapping[str, Any], label: str) -> None:
    """Reject parameter keys that look like inline secrets.

    Runs before any value is read so a rejected secret never reaches an error
    message. ``*_env`` reference keys (e.g. ``api_token_env``) are allowed.
    """
    for key in params:
        lowered = key.lower()
        looks_secret = lowered in _SECRET_PARAM_KEYS or (
            lowered.endswith(_SECRET_PARAM_SUFFIXES) and not lowered.endswith("_env")
        )
        if looks_secret:
            raise InvalidSessionEntry(
                f"{label}.sink_parameters.{key}",
                "looks like an inline secret; sinks accept only non-secret values "
                "(for Influx pass api_token_env, the name of an environment variable)",
            )


def _resolve_one_sink(
    raw_sink: Any,
    *,
    label: str,
    nickname: str | None,
    flow_index: int | None = None,
    sink_index: int | None = None,
) -> dict[str, Any]:
    """Validate and canonicalize one sink object into its stored form."""
    if not isinstance(raw_sink, Mapping):
        raise InvalidSessionEntry(label, "must be a mapping")

    unknown = set(raw_sink) - _SINK_FIELDS
    if unknown:
        raise InvalidSessionEntry(
            label, f"unknown sink field(s): {', '.join(sorted(unknown))}"
        )
    if "sink_type" not in raw_sink:
        raise InvalidSessionEntry(f"{label}.sink_type", "is required")

    sink_type = _normalize_nonempty_string(raw_sink["sink_type"], f"{label}.sink_type").lower()

    raw_params = raw_sink.get("sink_parameters")
    if raw_params is None:
        params: dict[str, Any] = {}
    elif isinstance(raw_params, Mapping):
        params = dict(raw_params)
    else:
        raise InvalidSessionEntry(f"{label}.sink_parameters", "must be a mapping")

    _reject_secret_params(params, label)
    if "file_path" in params:
        raise InvalidSessionEntry(
            f"{label}.sink_parameters",
            "file location must be supplied as sink_location, not a file_path parameter",
        )

    try:
        schema = sink_parameter_schema(sink_type)
    except UnknownConfigType as exc:
        raise InvalidSessionEntry(f"{label}.sink_type", str(exc)) from exc

    location = raw_sink.get("sink_location")
    if location is not None:
        if schema["category"] != SinkCategory.FILE.value:
            raise InvalidSessionEntry(
                f"{label}.sink_location",
                f"sink_location is only valid for file sinks (csv, edf, pvfs); "
                f"{sink_type!r} is a {schema['category']} sink",
            )
        location_str = _normalize_nonempty_string(location, f"{label}.sink_location")

        # Same check manifests.py runs again at start time (a session can sit
        # around a while between create and start, long enough for the
        # filesystem to change) — but catching it here means the operator
        # sees it while they're still typing the config, not minutes later.
        resolved = sink_paths.resolve_sink_location(location_str)
        if sink_paths.path_is_claimed(resolved):
            # No real session id yet (this session doesn't exist until
            # create() commits) — peek_next_id() is a best-effort guess, not
            # a reservation, so the suggestion can occasionally land on the
            # "wrong" id under a concurrent create. That's fine: this only
            # ever shapes a suggested filename string, never a real row.
            suggested = sink_paths.next_available_path(
                Path(resolved), session_id=_repo.peek_next_id()
            )
            raise SinkLocationExists(
                resolved,
                nickname=nickname,
                suggested_location=str(suggested),
                flow_index=flow_index,
                sink_index=sink_index,
            )
        params["file_path"] = location_str

    try:
        sink = lookup_sink(sink_type, params)
    except (UnknownConfigType, ValueError) as exc:
        raise InvalidSessionEntry(f"{label}.sink_type", str(exc)) from exc

    canonical_params = sink.as_dict()
    resolved_location = canonical_params.pop("file_path", None)
    canonical_params = {
        key: _jsonify(value)
        for key, value in canonical_params.items()
        if value is not None
    }

    raw_name = raw_sink.get("sink_name")
    if raw_name is None:
        sink_name = sink.type.value
    else:
        sink_name = _normalize_nonempty_string(raw_name, f"{label}.sink_name")

    canonical: dict[str, Any] = {"sink_name": sink_name, "sink_type": sink.type.value}
    if resolved_location is not None:
        canonical["sink_location"] = resolved_location
    canonical["sink_parameters"] = canonical_params
    return canonical


def _resolve_sink(entry: Mapping[str, Any]) -> dict[str, str]:
    """Resolve a single *flattened* legacy sink into ``{sink_type[, sink_location]}``.

    Interim helper retained unchanged for ``app.services.session_templates``,
    which still stores session-template flows in the flat single-sink shape and
    imports this symbol. The canonical session-config path uses
    :func:`_resolve_sinks` (the ordered ``sinks[]`` collection) instead. Remove
    this once the session-template storage packet migrates that module to
    ``sinks[]``.
    """
    sink_type = _normalize_nonempty_string(entry["sink_type"], "sink_type")
    sink_location = entry.get("sink_location")
    sink_parameters: dict[str, Any] = {}
    if sink_location is not None:
        location = _normalize_nonempty_string(sink_location, "sink_location")

        # Same check manifests.py runs again at start time (a session can sit
        # around a while between create and start, long enough for the
        # filesystem to change) — but catching it here means the operator
        # sees it while they're still typing the config, not minutes later.
        resolved = sink_paths.resolve_sink_location(location)
        if sink_paths.path_is_claimed(resolved):
            # No real session id yet (this session doesn't exist until
            # create() commits) — peek_next_id() is a best-effort guess, not
            # a reservation, so the suggestion can occasionally land on the
            # "wrong" id under a concurrent create. That's fine: this only
            # ever shapes a suggested filename string, never a real row.
            suggested = sink_paths.next_available_path(
                Path(resolved), session_id=_repo.peek_next_id()
            )
            raise SinkLocationExists(
                resolved,
                nickname=entry.get("nickname"),
                suggested_location=str(suggested),
            )

        sink_parameters["file_path"] = location

    try:
        sink = lookup_sink(sink_type, sink_parameters)
    except (UnknownConfigType, ValueError) as exc:
        raise InvalidSessionEntry("sink_type", str(exc)) from exc

    canonical = {"sink_type": sink.type.value}
    if "file_path" in sink.as_dict():
        canonical["sink_location"] = sink.as_dict()["file_path"]
    return canonical


def _resolve_sinks(
    entry: Mapping[str, Any],
    *,
    flow_index: int | None = None,
) -> list[dict[str, Any]]:
    """Resolve an entry's sinks into a non-empty ordered canonical list.

    Accepts two input shapes: the canonical nested ``sinks[]`` list and the
    legacy flattened form (top-level ``sink_type``/``sink_location``/
    ``sink_parameters``, which normalizes to a single named sink). Mixing the
    two forms is rejected. Sink order is preserved; ``sink_name`` must be
    unique within the source.
    """
    has_list = "sinks" in entry
    legacy_present = _LEGACY_SINK_FIELDS & set(entry)

    if has_list and legacy_present:
        raise InvalidSessionEntry(
            "sinks",
            "cannot combine flattened sink fields "
            f"({', '.join(sorted(legacy_present))}) with a sinks[] list; use sinks[] only",
        )

    if has_list:
        raw_sinks = entry["sinks"]
        if not isinstance(raw_sinks, list):
            raise InvalidSessionEntry("sinks", "must be a list")
        if not raw_sinks:
            raise InvalidSessionEntry("sinks", "must contain at least one sink")
        raw_list: list[Any] = list(raw_sinks)
    elif "sink_type" in entry:
        legacy_sink: dict[str, Any] = {"sink_type": entry["sink_type"]}
        if "sink_location" in entry:
            legacy_sink["sink_location"] = entry["sink_location"]
        if "sink_parameters" in entry:
            legacy_sink["sink_parameters"] = entry["sink_parameters"]
        raw_list = [legacy_sink]
    else:
        raise InvalidSessionEntry("sinks", "is required")

    nickname = entry.get("nickname")
    resolved: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw_sink in enumerate(raw_list):
        sink = _resolve_one_sink(
            raw_sink,
            label=f"sinks[{index}]",
            nickname=nickname,
            flow_index=flow_index,
            sink_index=index,
        )
        name = sink["sink_name"]
        if name in seen_names:
            raise InvalidSessionEntry(
                f"sinks[{index}].sink_name",
                f"duplicate sink_name {name!r}; each sink in a source needs a unique name",
            )
        seen_names.add(name)
        resolved.append(sink)
    return resolved


def _template_from_entry(entry: Mapping[str, Any]):
    path = _normalize_nonempty_string(entry.get("device_template_path"), "device_template_path")
    template = device_templates.get_by_path(path)
    if template is None:
        raise DeviceTemplateNotFound(path)
    return template


def _existing_or_create_config(template, entry: Mapping[str, Any]):
    hardware_id = _normalize_nonempty_string(entry["hardware_id"], "hardware_id")
    port = _normalize_nonempty_string(entry["port"], "port")
    device_type = DeviceType(template.content["type"])

    for config in device_configs.find_by_hardware_id(hardware_id):
        if DeviceType(config.device_type) is device_type:
            return config

    return device_configs.create_from_template(
        template,
        hardware_id=hardware_id,
        port=port,
        nickname=entry.get("nickname"),
    )


def _canonical_entry_for_config(
    config,
    entry: Mapping[str, Any],
    sinks: list[dict[str, Any]],
) -> dict[str, Any]:
    nickname = entry.get("nickname") or config.nickname or config.source_template
    if nickname is None:
        nickname = f"{DeviceType(config.device_type).value}-{config.hardware_id}"

    canonical: dict[str, Any] = {
        "device_config_id": config.id,
        "nickname": _normalize_nonempty_string(nickname, "nickname"),
        "sinks": sinks,
    }
    return canonical


def _template_reference_entry(raw_entry: Mapping[str, Any]) -> dict[str, Any]:
    entry = _require_mapping(raw_entry, "session device flow")

    unknown = set(entry) - _ENTRY_FIELDS
    if unknown:
        raise InvalidSessionEntry(
            ",".join(sorted(unknown)),
            f"unknown field(s): {', '.join(sorted(unknown))}",
        )

    template = _template_from_entry(entry)
    sinks = _resolve_sinks(entry)
    canonical = {
        "device_template_path": template.file_path,
        "device_template_content_hash": template.content_hash,
        "nickname": _normalize_nonempty_string(
            entry.get("nickname", template.name),
            "nickname",
        ),
        "sinks": sinks,
    }
    return canonical


def validate_entry(
    raw_entry: Mapping[str, Any],
    *,
    instantiate: bool = True,
    flow_index: int | None = None,
) -> dict[str, Any]:
    """Validate and canonicalize one ``Session.device_flows`` entry.

    ``flow_index`` is carried only so a sink-location collision can report the
    positional coordinates a template-created run submitted; it does not change
    validation.
    """
    entry = _require_mapping(raw_entry, "session device flow")

    unknown = set(entry) - _ENTRY_FIELDS
    if unknown:
        raise InvalidSessionEntry(
            ",".join(sorted(unknown)),
            f"unknown field(s): {', '.join(sorted(unknown))}",
        )

    if not instantiate:
        return _template_reference_entry(entry)

    sinks = _resolve_sinks(entry, flow_index=flow_index)

    if "device_config_id" in entry:
        disallowed = {"device_template_path", "hardware_id", "port"} & set(entry)
        if disallowed:
            raise InvalidSessionEntry(
                ",".join(sorted(disallowed)),
                "device_config_id entries must not include template or physical binding fields",
            )
        config_id = _normalize_int(entry["device_config_id"], "device_config_id")
        config = device_configs.get_by_id(config_id)
        if config is None:
            raise DeviceConfigNotFound(config_id)
        return _canonical_entry_for_config(config, entry, sinks)

    if "hardware_id" not in entry:
        raise InvalidSessionEntry("hardware_id", "is required")
    if "port" not in entry:
        raise InvalidSessionEntry("port", "is required")

    template = _template_from_entry(entry)
    config = _existing_or_create_config(template, entry)
    return _canonical_entry_for_config(config, entry, sinks)


def validate_entries(
    raw_entries: list[Mapping[str, Any]],
    *,
    instantiate: bool = True,
    positional: bool = False,
) -> list[dict[str, Any]]:
    """Validate a flow list and reject duplicate physical identities.

    ``positional`` marks a template-created run, whose flows are addressed by
    index end to end; it only enriches sink-location conflicts with coordinates.
    """
    device_flows = [
        validate_entry(
            entry,
            instantiate=instantiate,
            flow_index=index if positional else None,
        )
        for index, entry in enumerate(raw_entries)
    ]
    if not instantiate:
        return device_flows

    identities: set[tuple[str, str]] = set()
    for flow in device_flows:
        config = device_configs.get_by_id(int(flow["device_config_id"]))
        if config is None:
            raise DeviceConfigNotFound(flow["device_config_id"])
        identity = (DeviceType(config.device_type).value, str(config.hardware_id))
        if identity in identities:
            raise InvalidSessionEntry(
                "device_flows",
                f"physical device {identity[0]}:{identity[1]} appears more than once",
            )
        identities.add(identity)
    return device_flows


def _is_file_sink(sink_type: Any) -> bool:
    """True when a sink type owns an output path the operator can relocate."""
    try:
        schema = sink_parameter_schema(str(sink_type).strip().lower())
    except UnknownConfigType:
        return False
    return schema["category"] == SinkCategory.FILE.value


def _snapshot_flow_device_type(flow: Mapping[str, Any]) -> str:
    """Derive a snapshot flow's required device type.

    Mirrors ``template_assignments._device_type_for_flow`` — path first, then
    the portable name form — so the compatibility check the server enforces
    here matches the plan the operator reviewed in the form.
    """
    path = flow.get("device_template_path")
    if isinstance(path, str) and path.strip():
        template = device_templates.get_by_path(path)
        if template is None:
            template = device_templates.get_by_name(Path(path).stem)
        if template is not None:
            return template.type
    raise DeviceTemplateNotFound(str(path))


def _locations_by_index(
    assignment: Mapping[str, Any],
    *,
    flow_index: int,
    sinks: list[Mapping[str, Any]],
) -> dict[int, str]:
    """Validate one flow's sink_locations against its snapshot sink list.

    Indices address the frozen snapshot positionally, counting every sink
    regardless of category — the operator never sees a sink name — so an index
    outside the list, a repeat, a missing file-sink location, or a location on
    a non-file sink are all structural errors rather than something to repair.
    """
    raw = assignment.get("sink_locations") or []
    if not isinstance(raw, list):
        raise InvalidSessionEntry(
            f"assignments[{flow_index}].sink_locations", "must be a list"
        )

    by_index: dict[int, str] = {}
    for position, item in enumerate(raw):
        label = f"assignments[{flow_index}].sink_locations[{position}]"
        entry = _require_mapping(item, label)
        sink_index = _normalize_index(entry.get("sink_index"), f"{label}.sink_index")
        if not 0 <= sink_index < len(sinks):
            raise InvalidSessionEntry(
                f"{label}.sink_index",
                f"is out of range for a template flow with {len(sinks)} sink(s)",
            )
        if sink_index in by_index:
            raise InvalidSessionEntry(
                f"{label}.sink_index", f"duplicate sink_index {sink_index}"
            )
        if not _is_file_sink(sinks[sink_index].get("sink_type")):
            raise InvalidSessionEntry(
                f"{label}.sink_location",
                "only file sinks have a location",
            )
        by_index[sink_index] = _normalize_nonempty_string(
            entry.get("sink_location"), f"{label}.sink_location"
        )

    for sink_index, sink in enumerate(sinks):
        if _is_file_sink(sink.get("sink_type")) and sink_index not in by_index:
            raise InvalidSessionEntry(
                f"assignments[{flow_index}].sink_locations",
                f"file sink at index {sink_index} needs a location",
            )
    return by_index


def materialize_template_flows(
    snapshot_content: Mapping[str, Any],
    assignments: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Turn a frozen template snapshot plus accepted assignments into run flows.

    The snapshot is authoritative for everything the template owns — sink type,
    parameters, order and count — and the assignment list supplies only what the
    operator reviewed: which configured device runs each flow, and where each
    file sink writes. Nothing here claims a device or reserves a path; both are
    checked for the operator's benefit and acquired only at start.
    """
    snapshot_flows = snapshot_content.get("device_flows") or []
    if not isinstance(assignments, list):
        raise InvalidSessionEntry("assignments", "must be a list")

    seen: set[int] = set()
    by_flow: dict[int, Mapping[str, Any]] = {}
    for position, item in enumerate(assignments):
        assignment = _require_mapping(item, f"assignments[{position}]")
        flow_index = _normalize_index(
            assignment.get("flow_index"), f"assignments[{position}].flow_index"
        )
        if not 0 <= flow_index < len(snapshot_flows):
            raise InvalidSessionEntry(
                f"assignments[{position}].flow_index",
                f"is out of range for a template with {len(snapshot_flows)} flow(s)",
            )
        if flow_index in seen:
            raise InvalidSessionEntry(
                f"assignments[{position}].flow_index",
                f"duplicate flow_index {flow_index}",
            )
        seen.add(flow_index)
        by_flow[flow_index] = assignment

    missing = [index for index in range(len(snapshot_flows)) if index not in by_flow]
    if missing:
        raise InvalidSessionEntry(
            "assignments",
            "every template flow needs exactly one assignment; missing flow_index "
            + ", ".join(str(index) for index in missing),
        )

    entries: list[dict[str, Any]] = []
    for flow_index, snapshot_flow in enumerate(snapshot_flows):
        assignment = by_flow[flow_index]
        snapshot_sinks = list(snapshot_flow.get("sinks") or [])

        config_id = _normalize_int(
            assignment.get("device_config_id"),
            f"assignments[{flow_index}].device_config_id",
        )
        config = device_configs.get_by_id(config_id)
        if config is None:
            raise DeviceConfigNotFound(config_id)

        required_type = _snapshot_flow_device_type(snapshot_flow)
        actual_type = DeviceType(config.device_type).value
        if actual_type != required_type:
            raise InvalidSessionEntry(
                f"assignments[{flow_index}].device_config_id",
                f"device {config_id} is a {actual_type}, but this flow needs a {required_type}",
            )

        locations = _locations_by_index(
            assignment, flow_index=flow_index, sinks=snapshot_sinks
        )
        sinks: list[dict[str, Any]] = []
        for sink_index, snapshot_sink in enumerate(snapshot_sinks):
            sink = dict(snapshot_sink)
            if sink_index in locations:
                sink["sink_location"] = locations[sink_index]
            sinks.append(sink)

        entry: dict[str, Any] = {"device_config_id": config_id, "sinks": sinks}
        if snapshot_flow.get("nickname"):
            entry["nickname"] = snapshot_flow["nickname"]
        entries.append(entry)

    return validate_entries(entries, instantiate=True, positional=True)


def apply_sink_locations(
    device_flows: list[Mapping[str, Any]],
    locations: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Relocate file-sink outputs on a Draft that has never started.

    Addresses the stored effective flows with the same positional coordinates
    the create request used, so a client can replay a ``sink_location_exists``
    conflict straight back as a fix. Only locations move: device bindings, sink
    type, parameters, order and count are untouched.
    """
    if not isinstance(locations, list) or not locations:
        raise InvalidSessionEntry("locations", "must contain at least one location")

    flows = [dict(flow) for flow in device_flows]
    for flow in flows:
        flow["sinks"] = [dict(sink) for sink in (flow.get("sinks") or [])]

    seen: set[tuple[int, int]] = set()
    for position, item in enumerate(locations):
        label = f"locations[{position}]"
        entry = _require_mapping(item, label)
        flow_index = _normalize_index(entry.get("flow_index"), f"{label}.flow_index")
        if not 0 <= flow_index < len(flows):
            raise InvalidSessionEntry(
                f"{label}.flow_index",
                f"is out of range for a session with {len(flows)} flow(s)",
            )
        sinks = flows[flow_index]["sinks"]
        sink_index = _normalize_index(entry.get("sink_index"), f"{label}.sink_index")
        if not 0 <= sink_index < len(sinks):
            raise InvalidSessionEntry(
                f"{label}.sink_index",
                f"is out of range for a flow with {len(sinks)} sink(s)",
            )
        if (flow_index, sink_index) in seen:
            raise InvalidSessionEntry(
                f"{label}", f"duplicate location for flow {flow_index} sink {sink_index}"
            )
        seen.add((flow_index, sink_index))
        if not _is_file_sink(sinks[sink_index].get("sink_type")):
            raise InvalidSessionEntry(
                f"{label}.sink_location", "only file sinks have a location"
            )
        sinks[sink_index]["sink_location"] = _normalize_nonempty_string(
            entry.get("sink_location"), f"{label}.sink_location"
        )

    entries = [
        {
            "device_config_id": flow["device_config_id"],
            "nickname": flow.get("nickname"),
            "sinks": flow["sinks"],
        }
        for flow in flows
    ]
    for entry in entries:
        if entry["nickname"] is None:
            del entry["nickname"]
    return validate_entries(entries, instantiate=True, positional=True)


def _parse_source(
    source: str | Mapping[str, Any],
    *,
    format: str | None,
) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    if not isinstance(source, str):
        raise ValueError("session config source must be a mapping or string")

    if format == "json":
        data = json.loads(source)
    elif format == "toml":
        data = tomllib.loads(source)
    elif format is None:
        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            data = tomllib.loads(source)
    else:
        raise ValueError(f"unsupported format: {format!r}")
    return _require_mapping(data, "session config source")


def _canonicalize(raw_config: Mapping[str, Any], *, instantiate: bool = True) -> dict[str, Any]:
    config = _require_mapping(raw_config, "session config")

    unknown = set(config) - _SESSION_FIELDS
    if unknown:
        raise ValueError(f"unknown session config fields: {', '.join(sorted(unknown))}")

    raw_flows = config.get("device_flows")
    if not isinstance(raw_flows, list):
        raise ValueError("session config device_flows must be a list")
    if not raw_flows:
        raise ValueError("session config device_flows must not be empty")

    device_flows = validate_entries(raw_flows, instantiate=instantiate)

    return {
        "name": config.get("name") or "",
        "policy": _policy_value(config.get("policy")),
        "device_flows": device_flows,
    }


def import_config(
    source: str | Mapping[str, Any],
    *,
    format: str | None = None,
) -> Session:
    """Import a session config and persist it as a draft ``Session`` row."""
    data = _parse_source(source, format=format)
    canonical = _canonicalize(data)
    return _repo.create(canonical)


def _session_policy(session: Session) -> str:
    policy = session.policy or PolicyMode.RECOMMEND
    if isinstance(policy, PolicyMode):
        return policy.value
    return str(policy)


def _source_template_for_export(config):
    content = _template_content_for_config(config)
    content_hash = device_templates.content_hash(content)

    # Preserve a valid source-template reference when its canonical content is
    # still the same. Comparing hashes avoids treating equivalent serialized
    # values (for example, "2000" and 2000) as a drift.
    if config.source_template:
        template = device_templates.get_by_path(config.source_template)
        if template is not None and template.content_hash == content_hash:
            return template

    if config.source_template_hash:
        template = device_templates.get_by_content_hash(config.source_template_hash)
        if template is not None and template.content_hash == content_hash:
            return template

    # Directly-created configs have no provenance fields. Reuse an existing
    # library template with identical canonical content instead of minting a
    # duplicate session/hash-named template during export.
    return device_templates.get_by_content_hash(content_hash)


def _default_template_name(session: Session, entry: Mapping[str, Any], ordinal: int, config) -> str:
    history_name = getattr(config, "source_template_history", None)
    if history_name:
        return f"{history_name}_customized"
    content = _template_content_for_config(config)
    device_type = DeviceType(config.device_type).value
    session_slug = _slug(session.name, fallback=f"session-{session.id or 'new'}")
    flow_label = _slug(entry.get("nickname"), fallback=f"flow-{ordinal:02d}")
    return f"{device_type}-{session_slug}-{flow_label}-{_params_hash8(content)}"


def _template_for_export(session: Session, entry: Mapping[str, Any], ordinal: int):
    if "device_config_id" in entry:
        config_id = _normalize_int(entry["device_config_id"], "device_config_id")
        config = device_configs.get_by_id(config_id)
        if config is None:
            raise DeviceConfigNotFound(config_id)

        template = _source_template_for_export(config)
        if template is not None:
            return template

        return device_templates.create(
            _default_template_name(session, entry, ordinal, config),
            _template_content_for_config(config),
        )

    if "device_template_path" in entry:
        template_path = _normalize_nonempty_string(entry["device_template_path"], "device_template_path")
        template = device_templates.get_by_path(template_path)
        if template is None:
            raise DeviceTemplateNotFound(template_path)
        return template

    raise InvalidSessionEntry(
        "device_config_id",
        "session flow must reference device_config_id or device template",
    )


def _artifact_entry(
    session: Session,
    entry: Mapping[str, Any],
    ordinal: int,
    *,
    include_hardware_id: bool,
) -> dict[str, Any]:
    template = _template_for_export(session, entry, ordinal)
    sinks = _resolve_sinks(entry)
    nickname = entry.get("nickname")
    canonical = {
        "device_template_path": template.file_path,
        "device_template_content_hash": template.content_hash,
        "sinks": sinks,
    }
    if nickname is not None:
        canonical["nickname"] = _normalize_nonempty_string(nickname, "nickname")
    if include_hardware_id:
        if entry.get("device_config_id") is not None:
            config = device_configs.get_by_id(int(entry["device_config_id"]))
            if config is None:
                raise DeviceConfigNotFound(int(entry["device_config_id"]))
            canonical["hardware_id"] = config.hardware_id
        elif entry.get("hardware_id") is not None:
            canonical["hardware_id"] = _normalize_nonempty_string(
                entry["hardware_id"], "hardware_id"
            )
    return canonical


def _artifact(session: Session, *, include_hardware_id: bool) -> dict[str, Any]:
    return {
        "name": session.name,
        "policy": _session_policy(session),
        "device_flows": [
            _artifact_entry(
                session,
                entry,
                index,
                include_hardware_id=include_hardware_id,
            )
            for index, entry in enumerate(session.device_flows or [], start=1)
        ],
    }


def export(
    session: Session,
    *,
    format: str = "toml",
    include_hardware_id: bool = False,
) -> str:
    """Export a session config as stable TOML or canonical JSON."""
    artifact = _artifact(session, include_hardware_id=include_hardware_id)

    if format == "json":
        return json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    if format != "toml":
        raise ValueError(f"unsupported format: {format!r}")

    lines = [
        f"name = {_toml_value(artifact['name'])}",
        f"policy = {_toml_value(artifact['policy'])}",
        "",
    ]
    for entry in artifact["device_flows"]:
        lines.append("[[device_flows]]")
        # Flow scalars first: once a [[device_flows.sinks]] sub-table opens, no
        # further keys can attach to the parent flow table.
        for key in ("nickname", "device_template_path", "device_template_content_hash", "hardware_id"):
            if key in entry:
                lines.append(f"{key} = {_toml_value(entry[key])}")
        lines.append("")
        for sink in entry["sinks"]:
            lines.append("[[device_flows.sinks]]")
            lines.append(f"sink_name = {_toml_value(sink['sink_name'])}")
            lines.append(f"sink_type = {_toml_value(sink['sink_type'])}")
            if "sink_location" in sink:
                lines.append(f"sink_location = {_toml_value(sink['sink_location'])}")
            params = sink.get("sink_parameters") or {}
            if params:
                lines.append(f"sink_parameters = {_toml_value(params)}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _toml_value(value: Any) -> str:
    """Serialize a JSON-native scalar/collection to a TOML value literal.

    Handles the value shapes canonical sink parameters can take: strings,
    booleans, integers, floats, inline arrays, and inline tables (e.g. PVFS
    ``device_preferences``). ``None`` never reaches here — null-valued
    parameters are dropped during canonicalization, since TOML has no null.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Mapping):
        body = ", ".join(f"{key} = {_toml_value(item)}" for key, item in value.items())
        return "{" + body + "}"
    if isinstance(value, (list, tuple)):
        body = ", ".join(_toml_value(item) for item in value)
        return "[" + body + "]"
    raise ValueError(f"cannot serialize {value!r} to TOML")
