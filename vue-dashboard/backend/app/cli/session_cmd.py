"""Offline session-related CLI commands."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import quote

import click
import structlog
from flask import current_app

from app import create_app
from app.cli.daemon_client import DaemonClient, DaemonError, DaemonUnavailable
from app.cli.device_cmd import (
    _EXPECTED_VALIDATION_ERRORS,
    load_config_file,
    validate_config_source,
)
from app.cli.output import echo_json, echo_table, exit_with_error
from app.domain.enums import SinkCategory, SinkType
from app.domain.errors import (
    DeviceConfigNotFound,
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    SessionNotFound,
    UnknownConfigType,
)
from app.services import manifests, session_config
from app.services import sessions as sessions_service
from app.services.registry import lookup_sink, sink_parameter_schema
from app.services.session_config import _parse_source as _parse_session_source

_TERMINAL_OPERATION_STATES = {"succeeded", "failed", "uncertain"}
_SINK_TYPE_DEFAULT = "csv"
# Menu verbs for the interactive sink-collection editor (guided create Flow 1 and
# the template-instantiation flows). "done" is the default so the common
# single-sink path is one Enter press.
_SINK_ACTIONS = ("done", "add", "edit", "remove", "reorder")
# api_token_env is an environment-variable *name reference*, never the token
# value — the quiz must never prompt for a literal token (design section 4).
_SINK_PARAM_PROMPT_LABELS = {
    "api_token_env": "Influx API token environment variable NAME (not the token value)",
}
_POLICY_CHOICES = ("recommend", "automate")
_SESSION_EXPORT_ERRORS = (
    SessionNotFound,
    DeviceConfigNotFound,
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    ValueError,
)


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def _prompt_sink_location_conflict(exc: DaemonError) -> tuple[str, str] | None:
    """Turn a sink_location_exists DaemonError into an interactive fix-up prompt.

    Returns (nickname, chosen_path) if the operator should be offered a
    retry, or None if this error isn't one (or doesn't carry enough to act
    on) — the caller should then let it propagate as an ordinary failure.
    """
    if exc.code != "sink_location_exists":
        return None
    nickname = exc.extensions.get("nickname")
    suggested = exc.extensions.get("suggested_location")
    if not isinstance(nickname, str) or not isinstance(suggested, str):
        return None

    original = exc.extensions.get("sink_location", "?")
    flow_label = f" (flow {nickname!r})" if nickname else ""
    chosen = click.prompt(
        f"File already exists at {original!r}{flow_label}. "
        f"Press Enter to use {suggested!r} instead, or type a new path",
        default=suggested,
    )
    return nickname, chosen


@click.group(name="session")
def session() -> None:
    """Manage session-related local commands."""


@session.command(name="create")
@click.option(
    "--from",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Session config file to send to the daemon (skips the guided flow).",
)
@click.option(
    "--template",
    "template_ref",
    default=None,
    metavar="<template-name | template-number | file>",
    help=(
        "Guided flow: instantiate a stored/portable session template, "
        "auto-configuring any device flow whose hardware isn't registered yet."
    ),
)
@click.option("--name", "session_name", default=None, help="Session name.")
@click.option(
    "--policy",
    type=click.Choice(_POLICY_CHOICES),
    default=None,
    help="Recovery policy mode.",
)
def create_command(
    config_file: Path | None,
    template_ref: str | None,
    session_name: str | None,
    policy: str | None,
) -> None:
    """Create a Draft session through the daemon.

    Without --from, walks an interactive questionnaire: Flow 1 (default) picks
    from already-configured, free devices; Flow 2 (--template) snapshot-copies
    a stored or portable session template, auto-configuring any device flow
    that references hardware with no device config yet.
    """
    try:
        client = DaemonClient()
        if config_file is not None:
            source = load_config_file(config_file)
            payload = dict(_parse_session_source(source.content, format=source.format))
        elif template_ref is not None:
            payload = _guided_create_from_template(
                client,
                template_ref,
                name=session_name,
                policy=policy,
            )
        else:
            payload = _guided_create_from_configs(client, name=session_name, policy=policy)
        response = _create_session_with_sink_retry(client, payload)
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


def _create_session_with_sink_retry(
    client: DaemonClient,
    payload: dict[str, object],
) -> dict[str, object]:
    """POST a new session, looping the sink_location conflict prompt until it lands.

    The device_flows list is still local to this process at create time (the
    session doesn't exist on the daemon yet), so a chosen replacement path is
    just written back into the payload before retrying — no server-side
    state to reconcile, unlike the start-time conflict (see
    _start_session_with_sink_retry).
    """
    flows = payload.get("device_flows")
    while True:
        try:
            return client.post("/api/v1/sessions/", payload)
        except DaemonError as exc:
            resolution = _prompt_sink_location_conflict(exc)
            if resolution is None or not isinstance(flows, list):
                raise
            nickname, chosen = resolution
            original = exc.extensions.get("sink_location")
            for flow in flows:
                if isinstance(flow, dict) and flow.get("nickname") == nickname:
                    _apply_sink_location_override(flow, original, chosen)
                    break


def _apply_sink_location_override(
    flow: dict[str, object],
    original: object,
    chosen: str,
) -> None:
    """Write a conflict-resolved location back onto the right sink.

    A source now owns an ordered ``sinks[]`` collection, so the replacement
    path targets the specific file sink whose original location conflicted
    (matched by that location, falling back to the first sink). Legacy flat
    flows keep the top-level ``sink_location`` patch.
    """
    sinks = flow.get("sinks")
    if isinstance(sinks, list):
        for sink in sinks:
            if isinstance(sink, dict) and sink.get("sink_location") == original:
                sink["sink_location"] = chosen
                return
        if sinks and isinstance(sinks[0], dict):
            sinks[0]["sink_location"] = chosen
        return
    flow["sink_location"] = chosen


def _prompt_session_name(name: str | None) -> str | None:
    if name is not None:
        return name
    raw = click.prompt("Session name (blank to auto-generate)", default="", show_default=False)
    return raw.strip() or None


def _prompt_policy(policy: str | None) -> str:
    if policy is not None:
        return policy
    return click.prompt("Policy", type=click.Choice(_POLICY_CHOICES), default="recommend")


def _sink_type_choices() -> tuple[str, ...]:
    """Every registered sink type, in enum order — the quiz's type menu."""
    return tuple(sink_type.value for sink_type in SinkType)


def _default_sink_name(sink_type: str, existing: set[str]) -> str:
    """A unique default sink_name for a new sink of *sink_type*.

    Names default to the type (``csv``) and gain a numeric suffix (``csv-2``)
    when the source already owns a sink by that name, so repeated types stay
    addressable by a distinct, stable identity.
    """
    if sink_type not in existing:
        return sink_type
    suffix = 2
    while f"{sink_type}-{suffix}" in existing:
        suffix += 1
    return f"{sink_type}-{suffix}"


def _param_prompt_label(key: str) -> str:
    return _SINK_PARAM_PROMPT_LABELS.get(key, key)


def _prompt_sink_parameters(
    schema: Mapping[str, object],
    defaults: Mapping[str, object],
) -> dict[str, str]:
    """Prompt only this sink type's public parameters.

    Required parameters are always asked (Influx's ``api_token_env`` is the
    only required non-file one). Optional parameters are gated behind a single
    confirm so the common file-sink path stays short. ``file_path`` is never
    prompted here — a file location is collected as ``sink_location`` instead.
    """
    params: dict[str, str] = {}
    for key in schema.get("required", []):
        if key == "file_path":
            continue
        default = defaults.get(key)
        params[key] = click.prompt(
            _param_prompt_label(key),
            default=str(default) if default is not None else None,
        ).strip()

    optional_keys = [key for key in schema.get("optional", []) if key != "file_path"]
    if optional_keys and click.confirm(
        "Configure optional parameters for this sink?", default=False
    ):
        for key in optional_keys:
            default = defaults.get(key)
            value = click.prompt(
                f"{_param_prompt_label(key)} (blank to skip)",
                default=str(default) if default is not None else "",
                show_default=default is not None,
            ).strip()
            if value:
                params[key] = value
    return params


def _validate_sink(sink_type: str, location: str | None, params: Mapping[str, object]) -> None:
    """Registry-validate a sink locally so an error returns to *this* sink.

    Mirrors the daemon's per-sink resolution (file_path carries the location)
    without any I/O, giving the operator immediate feedback while siblings
    already in the collection stay untouched.
    """
    validation_params = dict(params)
    if location:
        validation_params["file_path"] = location
    lookup_sink(sink_type, validation_params)


def _prompt_one_sink(
    *,
    default: Mapping[str, object] | None = None,
    existing_names: set[str],
) -> dict[str, object]:
    """Prompt for one canonical sink, re-prompting on a validation failure."""
    seed: dict[str, object] = dict(default or {})
    while True:
        sink_type = click.prompt(
            "Sink type",
            type=click.Choice(_sink_type_choices()),
            default=str(seed.get("sink_type", _SINK_TYPE_DEFAULT)),
        )
        schema = sink_parameter_schema(sink_type)
        sink_name = click.prompt(
            "Sink name",
            default=str(seed.get("sink_name") or _default_sink_name(sink_type, existing_names)),
        ).strip()

        location: str | None = None
        if schema["category"] == SinkCategory.FILE.value:
            location = (
                click.prompt(
                    "Sink location (blank for a system-assigned path)",
                    default=str(seed.get("sink_location", "")),
                    show_default=False,
                ).strip()
                or None
            )

        params = _prompt_sink_parameters(schema, seed.get("sink_parameters") or {})

        try:
            _validate_sink(sink_type, location, params)
        except (UnknownConfigType, ValueError) as exc:
            click.echo(f"invalid sink: {exc}", err=True)
            seed = {"sink_type": sink_type, "sink_name": sink_name, "sink_parameters": params}
            if location:
                seed["sink_location"] = location
            continue

        sink: dict[str, object] = {"sink_name": sink_name, "sink_type": sink_type}
        if location:
            sink["sink_location"] = location
        sink["sink_parameters"] = params
        return sink


def _echo_sink_collection(sinks: list[dict[str, object]]) -> None:
    click.echo("Configured sinks:")
    for index, sink in enumerate(sinks, start=1):
        parts = [f"  {index}. {sink['sink_name']} ({sink['sink_type']})"]
        if sink.get("sink_location"):
            parts.append(f"-> {sink['sink_location']}")
        params = sink.get("sink_parameters") or {}
        if isinstance(params, Mapping) and params:
            parts.append("[" + ", ".join(f"{k}={v}" for k, v in sorted(params.items())) + "]")
        click.echo(" ".join(parts))


def _prompt_sink_index(sinks: list[dict[str, object]], label: str) -> int:
    while True:
        choice = click.prompt(label, type=int)
        if 1 <= choice <= len(sinks):
            return choice - 1
        click.echo(f"no sink numbered {choice}", err=True)


def _prompt_sinks(initial: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    """Build a source's canonical, ordered ``sinks[]`` collection.

    Starts from *initial* (a template's loaded sinks) or prompts for one sink,
    then loops an add/edit/remove/reorder menu. A source always keeps at least
    one sink: removing the last is refused. Returns the ordered list of
    ``{sink_name, sink_type, sink_location?, sink_parameters}`` objects.
    """
    sinks: list[dict[str, object]] = [dict(sink) for sink in (initial or [])]
    if not sinks:
        sinks.append(_prompt_one_sink(existing_names=set()))

    while True:
        _echo_sink_collection(sinks)
        action = click.prompt(
            "Sink action",
            type=click.Choice(_SINK_ACTIONS),
            default="done",
        )
        if action == "done":
            return sinks
        if action == "add":
            names = {str(sink["sink_name"]) for sink in sinks}
            sinks.append(_prompt_one_sink(existing_names=names))
        elif action == "edit":
            index = _prompt_sink_index(sinks, "Edit which sink")
            names = {str(s["sink_name"]) for i, s in enumerate(sinks) if i != index}
            sinks[index] = _prompt_one_sink(default=sinks[index], existing_names=names)
        elif action == "remove":
            if len(sinks) == 1:
                click.echo(
                    "cannot remove the last sink; each source needs at least one", err=True
                )
                continue
            sinks.pop(_prompt_sink_index(sinks, "Remove which sink"))
        elif action == "reorder":
            source = _prompt_sink_index(sinks, "Move which sink")
            target = _prompt_sink_index(sinks, "To which position")
            sinks.insert(target, sinks.pop(source))


def _template_flow_initial_sinks(flow: Mapping[str, object]) -> list[dict[str, object]]:
    """Seed a template flow's sink editor from its stored sink configuration.

    Accepts the canonical nested ``sinks[]`` shape and the legacy flattened
    ``sink_type``/``sink_location`` form, normalizing either to the editor's
    ``sinks[]`` working shape so every stored sink is loaded for keep/edit/
    remove/supplement.
    """
    raw = flow.get("sinks")
    if isinstance(raw, list) and raw:
        loaded: list[dict[str, object]] = []
        for sink in raw:
            if not isinstance(sink, Mapping):
                continue
            normalized = dict(sink)
            normalized.setdefault("sink_parameters", {})
            loaded.append(normalized)
        return loaded
    sink_type = flow.get("sink_type")
    if isinstance(sink_type, str) and sink_type:
        sink: dict[str, object] = {
            "sink_name": sink_type,
            "sink_type": sink_type,
            "sink_parameters": {},
        }
        location = flow.get("sink_location")
        if isinstance(location, str) and location:
            sink["sink_location"] = location
        return [sink]
    return []


def _free_device_configs(client: DaemonClient) -> list[dict[str, object]]:
    response = client.get("/api/v1/device-configs")
    if not isinstance(response, list):
        raise ValueError("Device config list response must be an array.")
    return [
        dict(config)
        for config in response
        if isinstance(config, Mapping) and config.get("claim_state") == "free"
    ]


def _pool_devices(client: DaemonClient) -> list[dict[str, object]]:
    response = client.get("/api/v1/devices/pool")
    if not isinstance(response, Mapping):
        raise ValueError("Device pool response must be an object.")
    raw_devices = response.get("devices")
    if not isinstance(raw_devices, list):
        raise ValueError("Device pool response must include a devices list.")
    return [dict(device) for device in raw_devices if isinstance(device, Mapping)]


def _unconfigured_pool_devices(client: DaemonClient) -> list[dict[str, object]]:
    return [
        device
        for device in _pool_devices(client)
        if device.get("status") == "unconfigured" and device.get("hardware_id")
    ]


def _device_template_rows(client: DaemonClient) -> list[dict[str, object]]:
    response = client.get("/api/v1/device-templates")
    if not isinstance(response, list):
        raise ValueError("Device template list response must be an array.")
    return [dict(template) for template in response if isinstance(template, Mapping)]


def _find_device_config(rows: list[dict[str, object]], reference: str) -> dict[str, object] | None:
    """Resolve a configured device by numeric id or its stable nickname."""
    for row in rows:
        if str(row.get("id")) == reference or row.get("nickname") == reference:
            return row
    return None


def _device_nickname(config: Mapping[str, object], *, fallback: str) -> str:
    nickname = config.get("nickname")
    return str(nickname) if isinstance(nickname, str) and nickname.strip() else fallback


def _guided_create_from_configs(
    client: DaemonClient,
    *,
    name: str | None,
    policy: str | None,
) -> dict[str, object]:
    """Flow 1: compose a session from already-configured, free devices."""
    configs = _free_device_configs(client)
    if not configs:
        raise ValueError(
            "No free device configs found. Run 'device config' to create one, "
            "or use 'session create --template' to auto-configure a scanned device."
        )

    device_flows: list[dict[str, object]] = []
    while True:
        echo_table(configs, ("id", "type", "hardware_id", "port", "nickname"))
        reference = click.prompt("Device config id or name")
        config = _find_device_config(configs, reference)
        if config is None:
            click.echo(f"no free device config named or numbered {reference!r}", err=True)
            continue

        nickname = _device_nickname(
            config,
            fallback=f"{config.get('type')}-{config.get('hardware_id')}",
        )
        sinks = _prompt_sinks()
        device_flows.append(
            {"device_config_id": config["id"], "nickname": nickname, "sinks": sinks}
        )

        configs = [c for c in configs if c.get("id") != config.get("id")]
        if not configs or not click.confirm("Add another device flow?", default=False):
            break

    return {
        "name": _prompt_session_name(name),
        "policy": _prompt_policy(policy),
        "device_flows": device_flows,
    }


def _session_template_rows(client: DaemonClient) -> list[dict[str, object]]:
    response = client.get("/api/v1/session-templates")
    if not isinstance(response, list):
        raise ValueError("Session template list response must be an array.")
    return [dict(row) for row in response if isinstance(row, Mapping)]


def _resolve_instance_relative_path(path: str, *, base_dir: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else base_dir / candidate


def _session_template_library_dir() -> Path:
    app = create_app()
    with app.app_context():
        configured = current_app.config["SESSION_TEMPLATE_DIR"]
        directory = _resolve_instance_relative_path(
            str(configured),
            base_dir=Path(current_app.instance_path),
        )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _session_template_content_hash(content: Mapping[str, object]) -> str:
    canonical = json.dumps(dict(content), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _library_session_template_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(
        (
            candidate
            for candidate in _session_template_library_dir().iterdir()
            if candidate.is_file() and candidate.suffix.lower() in {".toml", ".json"}
        ),
        key=lambda candidate: (candidate.stem.lower(), candidate.suffix.lower()),
    ):
        content = _load_session_template_file(path)
        rows.append(
            {
                "source": "local",
                "id": "",
                "name": path.stem,
                "content_hash": _session_template_content_hash(content),
                "reference": str(path),
                "content": content,
            }
        )
    return rows


def _session_template_catalog(client: DaemonClient) -> list[dict[str, object]]:
    stored = []
    for row in _session_template_rows(client):
        stored.append(
            {
                "source": "stored",
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "content_hash": row.get("content_hash", ""),
                "reference": row.get("name", ""),
                "content": row.get("content"),
            }
        )
    return [*stored, *_library_session_template_rows()]


def _library_template_path(ref: str) -> Path | None:
    library_dir = _session_template_library_dir()
    candidates = [library_dir / ref]
    if Path(ref).suffix.lower() not in {".toml", ".json"}:
        candidates.extend((library_dir / f"{ref}.toml", library_dir / f"{ref}.json"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _export_target_path(target: Path) -> Path:
    if target.is_absolute() or len(target.parts) > 1:
        return target
    return _session_template_library_dir() / target.name


def _session_template_file_path(name: str) -> Path:
    stem = name.strip()
    for suffix in (".toml", ".json"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)].rstrip()
            break
    invalid = set('<>:"/\\|?*')
    stem = "".join("_" if char in invalid or ord(char) < 32 else char for char in stem)
    stem = stem.strip(" .") or "session-template"
    return _session_template_library_dir() / f"{stem}.toml"


def _resolve_session_id(client: DaemonClient, reference: str) -> int:
    if reference.isdecimal():
        return int(reference)
    response = client.get("/api/v1/sessions/")
    if not isinstance(response, list):
        raise ValueError("Session list response must be an array.")
    matches = [
        row for row in response
        if isinstance(row, Mapping) and row.get("name") == reference
    ]
    if not matches:
        raise ValueError(f"No session found with id or name {reference!r}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple sessions have name {reference!r}.")
    try:
        return int(matches[0]["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Session {reference!r} has no valid id.") from exc


def _device_template_index(
    client: DaemonClient,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    rows = _device_template_rows(client)
    by_path = {row["file_path"]: row for row in rows if isinstance(row.get("file_path"), str)}
    by_name = {row["name"]: row for row in rows if isinstance(row.get("name"), str)}
    return by_path, by_name


def _load_session_template_file(path: Path) -> dict[str, object]:
    source = load_config_file(path)
    parsed = _parse_session_source(source.content, format=source.format)
    if not isinstance(parsed, Mapping):
        raise ValueError("session template file must parse to a mapping")
    raw_flows = parsed.get("device_flows")
    if not isinstance(raw_flows, list) or not raw_flows:
        raise ValueError("session template file device_flows must be a non-empty list")
    return {"policy": parsed.get("policy"), "device_flows": list(raw_flows)}


def _resolve_session_template_content(
    client: DaemonClient,
    ref: str,
) -> tuple[dict[str, object], str]:
    """Resolve --template's <name | number | file> into (content, label)."""
    path = Path(ref)
    if path.is_file():
        return _load_session_template_file(path), str(path)
    library_path = _library_template_path(ref)
    if library_path is not None:
        return _load_session_template_file(library_path), str(library_path)

    try:
        ordinal = int(ref)
    except ValueError:
        ordinal = None

    if ordinal is not None:
        templates = _session_template_catalog(client)
        if not (1 <= ordinal <= len(templates)):
            raise ValueError(
                f"no session template at position {ordinal}; run 'session template list'"
            )
        row = templates[ordinal - 1]
        content = row.get("content")
        if not isinstance(content, Mapping):
            raise ValueError("Session template catalog row must include content.")
        return dict(content), str(row["reference"])

    response = client.get(f"/api/v1/session-templates/{_path_segment(ref)}")
    if not isinstance(response, Mapping):
        raise ValueError("Session template response must be an object.")
    content = response.get("content")
    if not isinstance(content, Mapping):
        raise ValueError("Session template response must include content.")
    return dict(content), ref


def _toml_inline_value(value: object) -> str:
    """Serialize a JSON-native sink-parameter value as a TOML inline literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, Mapping):
        inner = ", ".join(f"{k} = {_toml_inline_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_inline_value(item) for item in value) + "]"
    return json.dumps(str(value))


def _render_session_template_content(content: Mapping[str, object], *, format: str) -> str:
    if format == "json":
        return json.dumps(dict(content), sort_keys=True, indent=2) + "\n"
    lines = [f"policy = {json.dumps(str(content.get('policy') or 'recommend'))}", ""]
    for raw_flow in content.get("device_flows", []):
        if not isinstance(raw_flow, Mapping):
            continue
        lines.append("[[device_flows]]")
        # Flow scalars first: once a [[device_flows.sinks]] sub-table opens, no
        # further keys attach to the parent flow table.
        for key in (
            "device_template_path",
            "device_template_content_hash",
            "hardware_id",
            "nickname",
        ):
            value = raw_flow.get(key)
            if value is not None:
                lines.append(f"{key} = {json.dumps(str(value))}")
        lines.append("")
        for sink in _template_flow_initial_sinks(raw_flow):
            lines.append("[[device_flows.sinks]]")
            lines.append(f"sink_name = {json.dumps(str(sink['sink_name']))}")
            lines.append(f"sink_type = {json.dumps(str(sink['sink_type']))}")
            if sink.get("sink_location") is not None:
                lines.append(f"sink_location = {json.dumps(str(sink['sink_location']))}")
            params = sink.get("sink_parameters") or {}
            if isinstance(params, Mapping) and params:
                lines.append(f"sink_parameters = {_toml_inline_value(dict(params))}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _persist_template_hardware_binding(
    client: DaemonClient,
    template_label: str,
    content: Mapping[str, object],
    raw_flow: Mapping[str, object],
    hardware_id: str,
) -> None:
    if not isinstance(raw_flow, dict):
        raise ValueError("session template flow is not mutable")
    raw_flow["hardware_id"] = hardware_id
    local_path = Path(template_label)
    if not local_path.is_file():
        local_path = _library_template_path(template_label) or local_path
    if local_path.is_file():
        output_format = "json" if local_path.suffix.lower() == ".json" else "toml"
        local_path.write_text(
            _render_session_template_content(content, format=output_format),
            encoding="utf-8",
        )
        click.echo(f"updated session template: {local_path}")
        return

    payload = {
        "name": template_label,
        "policy": content.get("policy"),
        "device_flows": content.get("device_flows", []),
    }
    client.put(f"/api/v1/session-templates/{_path_segment(template_label)}", payload)
    click.echo(f"updated stored session template: {template_label}")


def _normalize_template_flow_ref(
    flow: Mapping[str, object],
    by_path: dict[str, dict[str, object]],
    by_name: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Resolve a flow to a device-template path and current content hash."""
    if "device_template_path" in flow:
        path = flow["device_template_path"]
        template = by_path.get(path) if isinstance(path, str) else None
        if template is None:
            expected_hash = flow.get("device_template_content_hash")
            matches = [
                row for row in by_path.values()
                if isinstance(expected_hash, str) and row.get("content_hash") == expected_hash
            ]
            if len(matches) != 1:
                raise ValueError(f"session template references unknown device template path {path!r}")
            template = matches[0]
            warning = f"device template path {path!r} is missing; using hash match {template['file_path']}"
        else:
            warning = None
        normalized = dict(flow)
        normalized["device_template_path"] = template["file_path"]
        normalized.setdefault("device_template_content_hash", template.get("content_hash"))
        if warning:
            normalized["_device_template_warning"] = warning
        elif (
            isinstance(normalized.get("device_template_content_hash"), str)
            and normalized["device_template_content_hash"] != template.get("content_hash")
        ):
            normalized["_device_template_warning"] = (
                f"device template changed at {template['file_path']}; loading current file"
            )
        return normalized

    if "device_template" in flow:
        template_name = flow["device_template"]
        template = by_name.get(template_name)
        if template is None:
            raise ValueError(
                f"session template references unknown device template {template_name!r}"
            )
        normalized = dict(flow)
        normalized.pop("device_template")
        normalized["device_template_path"] = template["file_path"]
        normalized["device_template_content_hash"] = template.get("content_hash")
        return normalized

    raise ValueError("session template flow must reference device_template_path")


def _template_device_type(template_row: Mapping[str, object]) -> str:
    content = template_row.get("content")
    if isinstance(content, Mapping):
        type_name = content.get("type")
        if isinstance(type_name, str) and type_name:
            return type_name
    type_name = template_row.get("type")
    if isinstance(type_name, str) and type_name:
        return type_name
    raise ValueError("device template response must include content.type")


def _matching_template_pool_devices(
    pool_devices: list[dict[str, object]],
    device_type: str,
) -> list[dict[str, object]]:
    return [
        device
        for device in pool_devices
        if device.get("type") == device_type
        and device.get("status") in {"free", "unconfigured"}
        and device.get("hardware_id")
    ]


def _pool_identity(device: Mapping[str, object]) -> tuple[object, object]:
    return (device.get("type"), device.get("hardware_id"))


def _remaining_pool_devices(
    pool_devices: list[dict[str, object]],
    chosen: Mapping[str, object],
) -> list[dict[str, object]]:
    chosen_identity = _pool_identity(chosen)
    return [device for device in pool_devices if _pool_identity(device) != chosen_identity]


def _pool_device_for_entry(
    entry: Mapping[str, object],
    pool_devices: list[dict[str, object]],
) -> dict[str, object] | None:
    if "device_config_id" in entry:
        return next(
            (
                device
                for device in pool_devices
                if device.get("id") == entry["device_config_id"]
            ),
            None,
        )
    if "hardware_id" in entry and "port" in entry:
        return next(
            (
                device
                for device in pool_devices
                if device.get("hardware_id") == entry["hardware_id"]
                and device.get("port") == entry["port"]
            ),
            None,
        )
    return None


def _echo_pool_devices(label: str, devices: list[dict[str, object]]) -> None:
    click.echo(label)
    if not devices:
        click.echo("none")
        return
    echo_table(devices, ("id", "type", "hardware_id", "port", "status", "nickname"))


def _prompt_template_flow_mode() -> str:
    return click.prompt(
        "Assignment mode",
        type=click.Choice(("pick", "auto")),
        default="auto",
    )


def _unconfigured_note(count: int) -> str:
    noun = "device" if count == 1 else "devices"
    return (
        f"note: {count} matching {noun} unconfigured — "
        "run 'pinnacle device config' first to see them here"
    )


def _manual_template_flow_entry(
    flow: Mapping[str, object],
    *,
    device_type: str,
    default_nickname: str,
    pool_devices: list[dict[str, object]],
) -> dict[str, object]:
    free_devices = [
        device
        for device in pool_devices
        if device.get("status") == "free" and isinstance(device.get("id"), int)
    ]
    unconfigured_count = sum(
        1 for device in pool_devices if device.get("status") == "unconfigured"
    )

    if not free_devices:
        message = f"no configured {device_type} devices are available to pick"
        if unconfigured_count:
            message = (
                f"{message} ({_unconfigured_note(unconfigured_count)}, "
                "or re-run and choose auto mode to auto-configure one)"
            )
        raise ValueError(message)

    click.echo("Matching device configs in the pool:")
    echo_table(free_devices, ("id", "type", "hardware_id", "port", "nickname"))
    if unconfigured_count:
        click.echo(_unconfigured_note(unconfigured_count))

    while True:
        reference = click.prompt("Device config id or name")
        config = _find_device_config(free_devices, reference)
        if config is not None:
            break
        click.echo(f"no free device config named or numbered {reference!r} in this pool", err=True)

    sinks = _prompt_sinks(initial=_template_flow_initial_sinks(flow))
    nickname = _device_nickname(config, fallback=default_nickname)

    return {
        "device_config_id": config["id"],
        "nickname": nickname,
        "sinks": sinks,
    }


def _auto_template_flow_entry(
    flow: Mapping[str, object],
    *,
    template_path: str,
    device_type: str,
    default_nickname: str,
    pool_devices: list[dict[str, object]],
    preferred_devices: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    candidates = preferred_devices if preferred_devices else pool_devices
    free_devices = [
        device
        for device in candidates
        if device.get("status") == "free" and isinstance(device.get("id"), int)
    ]
    unconfigured_devices = [
        device
        for device in candidates
        if device.get("status") == "unconfigured"
        and isinstance(device.get("hardware_id"), str)
        and isinstance(device.get("port"), str)
    ]

    if free_devices:
        chosen = free_devices[0]
        click.echo(
            "Picked 1 free device from the pool: "
            f"config {chosen['id']} ({chosen['type']} {chosen['hardware_id']} on {chosen['port']})"
        )
        _echo_pool_devices(
            "Free devices left in the pool:",
            _remaining_pool_devices(pool_devices, chosen),
        )
        sinks = _prompt_sinks(initial=_template_flow_initial_sinks(flow))
        nickname = _device_nickname(chosen, fallback=default_nickname)
        return {
            "device_config_id": chosen["id"],
            "nickname": nickname,
            "sinks": sinks,
        }

    if unconfigured_devices:
        chosen = unconfigured_devices[0]
        click.echo(
            "Picked 1 unconfigured device from the pool: "
            f"{chosen['type']} {chosen['hardware_id']} on {chosen['port']}"
        )
        _echo_pool_devices(
            "Devices left in the pool:",
            _remaining_pool_devices(pool_devices, chosen),
        )
        sinks = _prompt_sinks(initial=_template_flow_initial_sinks(flow))
        return {
            "device_template_path": template_path,
            "device_template_content_hash": flow.get("device_template_content_hash"),
            "hardware_id": chosen["hardware_id"],
            "port": chosen["port"],
            "nickname": default_nickname,
            "sinks": sinks,
        }

    raise ValueError(f"no free or unconfigured {device_type} devices are available for auto mode")


def _guided_create_from_template(
    client: DaemonClient,
    ref: str,
    *,
    name: str | None,
    policy: str | None,
) -> dict[str, object]:
    """Flow 2: instantiate a stored/portable session template.

    Every flow references a device template, never a device config, so any
    flow whose hardware isn't registered yet gets auto-configured on submit
    (session_config.validate_entry's find-or-create-config resolution).
    """
    content, label = _resolve_session_template_content(client, ref)
    raw_flows = content.get("device_flows")
    if not isinstance(raw_flows, list) or not raw_flows:
        raise ValueError(f"session template {label!r} has no device flows")

    by_path, by_name = _device_template_index(client)
    pool_devices = _pool_devices(client)

    click.echo(f"instantiating session template: {label}")
    device_flows: list[dict[str, object]] = []
    for raw_flow in raw_flows:
        if not isinstance(raw_flow, Mapping):
            raise ValueError("session template device_flows entries must be mappings")
        flow = _normalize_template_flow_ref(raw_flow, by_path, by_name)
        if flow.get("_device_template_warning"):
            click.echo(f"warning: {flow['_device_template_warning']}", err=True)
        template_path = flow["device_template_path"]
        template_row = by_path[template_path]
        device_type = _template_device_type(template_row)
        suggestions = _matching_template_pool_devices(pool_devices, device_type)

        default_nickname = str(flow.get("nickname") or template_row.get("name"))
        click.echo(f"flow '{default_nickname}' (device template: {template_row.get('name')})")
        if not suggestions:
            raise ValueError(
                f"no {device_type} devices found in the pool for flow '{default_nickname}'; "
                "run 'pinnacle device list' to rescan, or 'pinnacle device config' to register one"
            )
        requested_hardware_id = flow.get("hardware_id")
        preferred_devices = [
            device
            for device in suggestions
            if isinstance(requested_hardware_id, str)
            and device.get("hardware_id") == requested_hardware_id
        ]
        used_hardware_preference = len(preferred_devices) == 1
        if used_hardware_preference:
            click.echo(f"using requested hardware ID {requested_hardware_id}")
            entry = _auto_template_flow_entry(
                flow,
                template_path=template_path,
                device_type=device_type,
                default_nickname=default_nickname,
                pool_devices=suggestions,
                preferred_devices=preferred_devices,
            )
        else:
            if requested_hardware_id:
                click.echo(
                    f"warning: requested hardware ID {requested_hardware_id!r} is not uniquely available; "
                    "falling back to normal assignment",
                    err=True,
                )
            mode = _prompt_template_flow_mode()
            if mode == "auto":
                entry = _auto_template_flow_entry(
                    flow,
                    template_path=template_path,
                    device_type=device_type,
                    default_nickname=default_nickname,
                    pool_devices=suggestions,
                )
            else:
                entry = _manual_template_flow_entry(
                    flow,
                    device_type=device_type,
                    default_nickname=default_nickname,
                    pool_devices=suggestions,
                )
        device_flows.append(entry)
        chosen_device = _pool_device_for_entry(entry, pool_devices)
        if chosen_device is not None:
            if (
                not used_hardware_preference
                and isinstance(requested_hardware_id, str)
                and chosen_device.get("hardware_id") != requested_hardware_id
                and click.confirm(
                    f"Update template hardware ID to {chosen_device.get('hardware_id')}?",
                    default=False,
                )
            ):
                _persist_template_hardware_binding(
                    client,
                    label,
                    content,
                    raw_flow,
                    str(chosen_device["hardware_id"]),
                )
            pool_devices = _remaining_pool_devices(pool_devices, chosen_device)

    resolved_policy = policy or content.get("policy")

    return {
        "name": _prompt_session_name(name),
        "policy": _prompt_policy(resolved_policy),
        "device_flows": device_flows,
    }


def _wait_options(command):
    command = click.option(
        "--wait-timeout",
        type=float,
        default=60.0,
        show_default=True,
        help="Maximum seconds to wait for the operation to finish.",
    )(command)
    command = click.option(
        "--wait-interval",
        type=float,
        default=0.5,
        show_default=True,
        help="Seconds between operation status polls.",
    )(command)
    command = click.option(
        "--wait",
        is_flag=True,
        help=(
            "Block until the operation completes (succeeded/failed/uncertain); "
            "sets the exit code."
        ),
    )(command)
    return command


@session.command(name="start")
@click.argument("session_reference")
@click.option(
    "--force",
    is_flag=True,
    help="Steal already-claimed device configs from their current soft reservation holder.",
)
@click.option(
    "--watch",
    "watch",
    type=bool,
    default=True,
    show_default=True,
    help=(
        "Attach to session watch after the start command (type 'exit' or press "
        "Ctrl-C to stop watching); pass --watch=false to opt out."
    ),
)
@_wait_options
def start_command(
    session_reference: str,
    force: bool,
    watch: bool,
    wait: bool,
    wait_interval: float,
    wait_timeout: float,
) -> None:
    """Start a session through the daemon."""
    session_id = _resolve_session_id(DaemonClient(), session_reference)
    _run_command(
        session_id,
        command="start",
        wait=wait,
        wait_interval=wait_interval,
        wait_timeout=wait_timeout,
        watch=watch,
        payload={"force": True} if force else None,
    )


@session.command(name="stop")
@click.argument("session_reference")
@click.option(
    "--force",
    is_flag=True,
    help="Record an unclean stop when the runtime host cannot prove graceful teardown.",
)
@_wait_options
def stop_command(
    session_reference: str,
    force: bool,
    wait: bool,
    wait_interval: float,
    wait_timeout: float,
) -> None:
    """Stop a session through the daemon."""
    session_id = _resolve_session_id(DaemonClient(), session_reference)
    _run_command(
        session_id,
        command="stop",
        wait=wait,
        wait_interval=wait_interval,
        wait_timeout=wait_timeout,
        watch=False,
        payload={"force": True} if force else None,
    )


_RECOVER_ACTIONS = ("reconnect", "restart", "reset-stream")


@session.command(name="recover")
@click.argument("session_reference")
@click.option(
    "--device",
    "device_id",
    required=True,
    help="Target device/stream id (device_id from the manifest) to recover.",
)
@click.option(
    "--action",
    type=click.Choice(_RECOVER_ACTIONS),
    default="reconnect",
    show_default=True,
    help="Recovery intensity: reconnect < restart < reset-stream.",
)
@_wait_options
def recover_command(
    session_reference: str,
    device_id: str,
    action: str,
    wait: bool,
    wait_interval: float,
    wait_timeout: float,
) -> None:
    """Command a targeted per-stream recovery on an active session."""
    session_id = _resolve_session_id(DaemonClient(), session_reference)
    _run_command(
        session_id,
        command="recover",
        wait=wait,
        wait_interval=wait_interval,
        wait_timeout=wait_timeout,
        watch=False,
        payload={"device_id": device_id, "action": action},
    )


def _start_session_with_sink_retry(
    client: DaemonClient,
    session_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    """POST the start command, looping the sink_location conflict prompt until it lands.

    Unlike session create, a session's device_flows are already persisted by
    start time — there's no local payload to patch and resend. Instead each
    operator-confirmed fix is sent as a sink_overrides entry; the daemon
    writes it onto the session (services.sessions._apply_sink_overrides)
    before re-resolving the manifest, so a retry (or a later start) doesn't
    need to re-prompt for the same flow.
    """
    request_payload = dict(payload)
    while True:
        try:
            return client.post(
                f"/api/v1/sessions/{session_id}/commands/start", request_payload
            )
        except DaemonError as exc:
            resolution = _prompt_sink_location_conflict(exc)
            if resolution is None:
                raise
            nickname, chosen = resolution
            overrides = dict(request_payload.get("sink_overrides") or {})
            overrides[nickname] = chosen
            request_payload["sink_overrides"] = overrides


def _run_command(
    session_id: int,
    *,
    command: str,
    wait: bool,
    wait_interval: float,
    wait_timeout: float,
    watch: bool,
    payload: dict[str, object] | None = None,
) -> None:
    try:
        if wait_interval <= 0:
            raise ValueError("--wait-interval must be greater than zero")
        if wait_timeout < 0:
            raise ValueError("--wait-timeout must be greater than or equal to zero")

        client = DaemonClient()
        if command == "start":
            response = _start_session_with_sink_retry(client, session_id, payload or {})
        else:
            response = client.post(
                f"/api/v1/sessions/{session_id}/commands/{command}", payload or {}
            )
        echo_json(response)

        if wait:
            operation_id = _operation_id_from_session_response(response)
            operation = _wait_for_operation(
                client,
                operation_id,
                timeout_seconds=wait_timeout,
                interval_seconds=wait_interval,
            )
            _report_wait_result(operation)
        if command == "start" and watch:
            _watch_session_events(client, session_id)
    except KeyboardInterrupt:
        raise click.exceptions.Exit(130) from None
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        if command == "stop" and isinstance(exc, DaemonError) and exc.code == "stop_proof_missing":
            exit_with_error(
                f"{exc.title}: {exc.detail} Re-run with "
                f"'pinnacle session stop {session_id} --force' to complete the "
                "stop (this records it as unclean and releases claimed devices)."
            )
        exit_with_error(exc)


def _operation_id_from_session_response(response: dict[str, object]) -> str:
    operation_id = response.get("operation_id") or response.get("command_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError("daemon response did not include an operation id")
    return operation_id


def _wait_for_operation(
    client: DaemonClient,
    operation_id: str,
    *,
    timeout_seconds: float,
    interval_seconds: float,
) -> dict[str, object]:
    deadline = monotonic() + timeout_seconds
    while True:
        operation = client.get(f"/api/v1/operations/{operation_id}")
        state = operation.get("state")
        if state in _TERMINAL_OPERATION_STATES:
            return operation
        if monotonic() >= deadline:
            raise ValueError(
                f"operation {operation_id} still pending after {timeout_seconds:.1f}s"
            )
        sleep(interval_seconds)


def _report_wait_result(operation: dict[str, object]) -> None:
    operation_id = operation.get("operation_id")
    state = operation.get("state")
    if state == "succeeded":
        click.echo(f"operation {operation_id} succeeded")
        return

    detail = operation.get("error_message") or operation.get("error_code")
    message = f"operation {operation_id} {state}"
    if detail:
        message = f"{message}: {detail}"
    raise click.ClickException(message)


_FLEET_HEADERS = ("id", "name", "status", "phase", "health")


@session.command(name="list")
def list_command() -> None:
    """Fleet overview: running count + per-session lifecycle/health/phase."""
    try:
        response = DaemonClient().get("/api/v1/sessions/overview")
        if not isinstance(response, Mapping):
            raise ValueError("Session overview response must be an object.")
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    sessions = response.get("sessions") or []
    click.echo(f"running: {response.get('running_count', 0)}/{response.get('total_count', 0)}")
    if not sessions:
        click.echo("no sessions")
        return
    echo_table(sessions, _FLEET_HEADERS)


_STATUS_RUNTIME_HEADERS = ("runtime_id", "state", "pid", "port", "manifest_hash")
_STATUS_OPERATION_HEADERS = ("operation_id", "command", "state", "target_device_id", "created_at")
_STATUS_INCIDENT_HEADERS = ("incident_id", "status", "device_id", "reason", "opened_at")
_STATUS_GAP_HEADERS = ("gap_id", "device_id", "confidence", "reason", "created_at")
_STATUS_DEVICE_HEADERS = ("device_id", "stream_status")
# The only diagnostics keys the CLI will ever print for a sink. Upstream already
# pre-redacts (packet 22), but the CLI enforces the allowlist a second time so a
# stray secret/sample smuggled into the map is dropped rather than echoed, and
# every value is length-bounded (see _echo_sink_diagnostics).
_SINK_DIAGNOSTIC_KEYS = ("failure_kind", "exception_type", "message", "last_success_seq")


def _echo_status_section(label: str, rows: object, headers: tuple[str, ...]) -> None:
    click.echo(f"\n{label}:")
    if not isinstance(rows, list) or not rows:
        click.echo("none")
        return
    echo_table(rows, headers)


def _render_session_status(snapshot: Mapping[str, object]) -> None:
    session = snapshot.get("session")
    session = session if isinstance(session, Mapping) else {}
    click.echo(f"session {session.get('id')}: {session.get('name')}")
    click.echo(f"lifecycle: {session.get('status')}")
    click.echo(f"health:    {snapshot.get('health') or '-'}")
    click.echo(f"phase:     {snapshot.get('phase') or '-'}")

    latest = snapshot.get("latest_report")
    if isinstance(latest, Mapping):
        click.echo(
            f"\nlatest report: seq {latest.get('sequence')} "
            f"(comms {latest.get('comms')}, received {latest.get('received_at')})"
        )
        _echo_status_section("streams", latest.get("devices"), _STATUS_DEVICE_HEADERS)
    else:
        click.echo("\nlatest report: none")

    _echo_status_section("runtimes", snapshot.get("runtimes"), _STATUS_RUNTIME_HEADERS)
    _echo_status_section("operations", snapshot.get("operations"), _STATUS_OPERATION_HEADERS)
    _echo_status_section("incidents", snapshot.get("incidents"), _STATUS_INCIDENT_HEADERS)
    _echo_status_section("gaps", snapshot.get("gaps"), _STATUS_GAP_HEADERS)
    _render_sink_status_section(snapshot.get("sinks"))


def _sink_axis(sink: Mapping[str, object], key: str) -> object:
    """A live per-sink axis value, or ``-`` when null/absent.

    The live axes (health/delivery/finalization/component/…) are null unless the
    sink's freshness ``status`` is ``current`` — so ``-`` reads as "no live value"
    and is never conflated with a real state such as ``healthy`` or ``failed``.
    """
    value = sink.get(key)
    return value if value not in (None, "") else "-"


def _group_sinks_by_source(sinks: list[object]) -> list[tuple[str, list[Mapping[str, object]]]]:
    """Order sinks by ``(source_id, sink_id)`` and group them under their source.

    The status API already sorts, but the CLI re-sorts defensively so grouping is
    correct even if a legacy/out-of-order payload slips through — the contract is
    that every source's sinks appear together, in stable order.
    """
    ordered = sorted(
        (sink for sink in sinks if isinstance(sink, Mapping)),
        key=lambda s: (str(s.get("source_id") or ""), str(s.get("sink_id") or "")),
    )
    groups: list[tuple[str, list[Mapping[str, object]]]] = []
    for sink in ordered:
        source_id = str(sink.get("source_id") or "-")
        if groups and groups[-1][0] == source_id:
            groups[-1][1].append(sink)
        else:
            groups.append((source_id, [sink]))
    return groups


def _render_sink_status_section(sinks: object) -> None:
    """Render the per-sink status axis, grouped beneath each source.

    This axis is deliberately SEPARATE from the source health/phase/latest_report
    block above: a degraded, failed, buffering, or finalizing sink surfaces here
    and is NEVER folded into the session's source health (gaps SINK-08/SINK-23),
    so a healthy source with a failing sibling sink is unmistakable. Legacy
    daemons that predate the per-sink contract omit the ``sinks`` key entirely;
    the section is then skipped so the source-only status stays readable.
    """
    if not isinstance(sinks, list):
        return
    click.echo("\nsinks:")
    if not sinks:
        click.echo("none")
        return
    for source_id, group in _group_sinks_by_source(sinks):
        click.echo(f"  source {source_id}:")
        for sink in group:
            _echo_one_sink(sink)


def _echo_one_sink(sink: Mapping[str, object]) -> None:
    sink_id = sink.get("sink_id") or "-"
    sink_class = sink.get("sink_class") or "-"
    # Freshness (current/stale/unknown) is a SEPARATE vocabulary from health; a
    # missing marker is rendered as ``unknown``, never as healthy.
    status = sink.get("status")
    status = status if isinstance(status, str) and status else "unknown"
    click.echo(f"    sink {sink_id} ({sink_class}) status={status}")
    click.echo(
        f"      health={_sink_axis(sink, 'health')} "
        f"delivery={_sink_axis(sink, 'delivery')} "
        f"finalization={_sink_axis(sink, 'finalization')} "
        f"component={_sink_axis(sink, 'component')}"
    )
    click.echo(
        f"      buffered={_sink_axis(sink, 'buffered_samples')} samples / "
        f"{_sink_axis(sink, 'buffered_bytes')} bytes   "
        f"loss={_sink_axis(sink, 'sample_loss')} samples / "
        f"{_sink_axis(sink, 'byte_loss')} bytes   "
        f"seq={_sink_axis(sink, 'sink_sequence')}"
    )
    last_update = sink.get("last_update")
    if last_update:
        click.echo(f"      updated {last_update}")
    _echo_sink_output(sink.get("output"))
    _echo_sink_diagnostics(sink.get("diagnostics"))
    _echo_sink_incidents(sink.get("open_incidents"))


def _echo_sink_output(output: object) -> None:
    """Render durable output evidence (finalization/delivery) — survives even a
    stale/unknown live status, so a finalized or lost artifact stays visible."""
    if not isinstance(output, Mapping):
        return
    click.echo(
        "      output: "
        f"logical={output.get('logical_sink_id') or '-'} "
        f"artifact={output.get('artifact_state') or '-'} "
        f"delivery={output.get('delivery_state') or '-'} "
        f"loss={_sink_axis(output, 'sample_loss')}/{_sink_axis(output, 'byte_loss')}"
    )


def _echo_sink_diagnostics(diagnostics: object) -> None:
    if not isinstance(diagnostics, Mapping):
        return
    parts: list[str] = []
    for key in _SINK_DIAGNOSTIC_KEYS:
        if key not in diagnostics:
            continue
        value = diagnostics[key]
        if isinstance(value, str):
            value = _bounded_watch_text(value)
        parts.append(f"{key}={value}")
    if parts:
        click.echo("      diagnostics: " + " ".join(parts))


def _echo_sink_incidents(incidents: object) -> None:
    """Render sink-scoped open incidents only (source incidents live above)."""
    if not isinstance(incidents, list) or not incidents:
        return
    click.echo("      incidents:")
    for incident in incidents:
        if not isinstance(incident, Mapping):
            continue
        click.echo(
            f"        {incident.get('incident_id') or '-'} "
            f"{incident.get('status') or '-'} "
            f"{incident.get('reason') or '-'}"
        )


@session.command(name="status")
@click.argument("session_reference")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw aggregate snapshot as JSON.")
def status_command(session_reference: str, as_json: bool) -> None:
    """One-shot detail snapshot for a session (runtime + streams + ops + incidents + gaps)."""
    try:
        client = DaemonClient()
        session_id = _resolve_session_id(client, session_reference)
        response = client.get(f"/api/v1/sessions/{session_id}/status")
        if not isinstance(response, Mapping):
            raise ValueError("Session status response must be an object.")
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    if as_json:
        echo_json(response)
        return
    _render_session_status(response)


@session.command(name="watch")
@click.argument("session_reference")
@click.option(
    "--after",
    type=int,
    default=None,
    help="Initial backend event id cursor; streams events after this id.",
)
def watch_command(session_reference: str, after: int | None) -> None:
    """Stream session events from the daemon until you type 'exit' or press Ctrl-C."""
    try:
        client = DaemonClient()
        session_id = _resolve_session_id(client, session_reference)
        _watch_session_events(client, session_id, after=after)
    except KeyboardInterrupt:
        raise click.exceptions.Exit(130) from None
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)


_EXIT_KEYWORD = "exit"


def _watch_for_exit_keyword(stop_event: threading.Event) -> None:
    """Background stdin reader: set stop_event once the user types 'exit'."""
    try:
        while not stop_event.is_set():
            line = sys.stdin.readline()
            if not line or line.strip().lower() == _EXIT_KEYWORD:
                stop_event.set()
                return
    except Exception:
        # Best-effort convenience on top of Ctrl-C, which remains reliable;
        # any stdin-access failure here should not surface to the user.
        stop_event.set()


def _watch_session_events(
    client: DaemonClient,
    session_id: int,
    *,
    after: int | None = None,
) -> None:
    path = f"/api/v1/sessions/{session_id}/events"
    if after is not None:
        path = f"{path}?after={after}"

    stop_event = threading.Event()
    reader = threading.Thread(
        target=_watch_for_exit_keyword,
        args=(stop_event,),
        daemon=True,
    )
    reader.start()

    lines = client.iter_lines(path, accept="text/event-stream", should_stop=stop_event.is_set)
    for event in _iter_sse_events(lines):
        for rendered in _render_watch_event(event):
            click.echo(rendered)


def _render_watch_event(event: Mapping[str, object]) -> list[str]:
    """Render session SSE events as concise structlog console records.

    The SSE payload stays JSON on the wire. This is only the terminal view used
    by ``pinnacle session start --watch`` and ``pinnacle session watch``: it
    projects the bounded watchdog diagnostics into one readable line per
    stream instead of dumping the entire nested report on every tick.
    """
    event_id = event.get("id")
    event_type = event.get("event")
    data = event.get("data")
    data = data if isinstance(data, Mapping) else {}
    base = {
        "backend_event_id": event_id,
        "event_type": event_type,
        "phase": data.get("phase"),
        "comms": data.get("comms"),
        "sequence": data.get("sequence"),
        "runtime_id": data.get("runtime_id"),
    }

    diagnostics = data.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    streams = diagnostics.get("streams")
    rendered: list[str]
    if isinstance(streams, list):
        watchdog = diagnostics.get("watchdog")
        watchdog = watchdog if isinstance(watchdog, Mapping) else {}
        rendered = [
            _render_structlog_console(
                {
                    "event": "watchdog status report",
                    **base,
                    "stream_count": len(streams),
                    "failure_threshold": watchdog.get("failure_threshold"),
                    "max_heartbeat_age": watchdog.get("max_heartbeat_age_seconds"),
                    "first_packet_timeout": watchdog.get(
                        "first_packet_timeout_seconds"
                    ),
                    "report_interval": watchdog.get("report_interval_seconds"),
                    "stream_interval": watchdog.get("stream_interval_seconds"),
                    "operation_timeout": watchdog.get("operation_timeout_seconds"),
                }
            )
        ]
        for stream in streams:
            if not isinstance(stream, Mapping):
                continue
            failure = stream.get("failure")
            failure = failure if isinstance(failure, Mapping) else {}
            heartbeat = stream.get("heartbeat")
            heartbeat = heartbeat if isinstance(heartbeat, Mapping) else {}
            worker = stream.get("worker")
            worker = worker if isinstance(worker, Mapping) else {}
            recovery = stream.get("recovery")
            recovery = recovery if isinstance(recovery, Mapping) else {}
            source_read = stream.get("source_read")
            source_read = source_read if isinstance(source_read, Mapping) else {}
            startup = stream.get("startup")
            startup = startup if isinstance(startup, Mapping) else {}
            rendered.append(
                _render_structlog_console(
                    {
                        "event": "watchdog stream status",
                        **base,
                        "device_id": stream.get("device_id"),
                        "stream_status": stream.get("health"),
                        "action": stream.get("action"),
                        "rule": stream.get("rule"),
                        "summary": _bounded_watch_text(stream.get("summary"), 320),
                        "failure_reason": stream.get("failure_reason"),
                        "initiating_failure_reason": stream.get(
                            "initiating_failure_reason"
                        ),
                        "heartbeat_reason": heartbeat.get("reason"),
                        "recovery_stage": recovery.get("status"),
                        "policy_mode": recovery.get("policy"),
                        "streak": stream.get("consecutive_nonhealthy_ticks"),
                        "failures": _fraction(failure.get("count"), failure.get("threshold")),
                        "worker": worker.get("status"),
                        "worker_exitcode": worker.get("exitcode"),
                        "heartbeat": heartbeat.get("status"),
                        "heartbeat_age": heartbeat.get("age_sec"),
                        "heartbeat_max_age": heartbeat.get("max_age_sec"),
                        "packet_count": heartbeat.get("packet_count"),
                        "first_packet_remaining": startup.get("remaining_sec"),
                        "first_packet_timeout": startup.get("timeout_sec"),
                        "source_read_state": source_read.get("state"),
                        "source_read_error": source_read.get("exception_type"),
                        "source_read_message": _bounded_watch_text(
                            source_read.get("message"), 500
                        ),
                        "source_read_failures": source_read.get(
                            "consecutive_failures"
                        ),
                        "error": _bounded_watch_text(failure.get("last_error")),
                    },
                    status=stream.get("health"),
                )
            )
    else:
        rendered = [
            _render_structlog_console(
                {
                    "event": "session event",
                    **base,
                    "device_count": len(data.get("devices", []))
                    if isinstance(data.get("devices"), list)
                    else 0,
                }
            )
        ]

    # Per-sink status rides its own top-level ``sinks`` key on the report payload
    # (sibling to diagnostics), on a SEPARATE axis from stream/source health: a
    # failing or finalizing sink surfaces as its own line, never as a source or
    # stream failure. Absent on legacy reports, in which case nothing is added.
    rendered.extend(_render_sink_watch_lines(data.get("sinks"), base))
    return rendered


def _render_sink_watch_lines(sinks: object, base: Mapping[str, object]) -> list[str]:
    """Project each per-sink live snapshot into one bounded, redacted console line.

    Only the diagnostics allowlist (failure_kind/exception_type/message/
    last_success_seq) is surfaced and the free-text message is length-bounded, so
    tokens and raw samples can never reach the terminal. Colored by sink health.
    """
    if not isinstance(sinks, list):
        return []
    lines: list[str] = []
    for sink in sinks:
        if not isinstance(sink, Mapping):
            continue
        diagnostics = sink.get("diagnostics")
        diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
        output = sink.get("output")
        output = output if isinstance(output, Mapping) else {}
        health = sink.get("health")
        lines.append(
            _render_structlog_console(
                {
                    "event": "sink status",
                    **base,
                    "source_id": sink.get("source_id"),
                    "sink_id": sink.get("sink_id"),
                    "sink_class": sink.get("sink_class"),
                    "sink_freshness": sink.get("status"),
                    "sink_health": health,
                    "delivery": sink.get("delivery"),
                    "finalization": sink.get("finalization"),
                    "component": sink.get("component"),
                    "buffered_samples": sink.get("buffered_samples"),
                    "buffered_bytes": sink.get("buffered_bytes"),
                    "sample_loss": sink.get("sample_loss"),
                    "byte_loss": sink.get("byte_loss"),
                    "sink_sequence": sink.get("sink_sequence"),
                    "artifact_state": output.get("artifact_state"),
                    "delivery_state": output.get("delivery_state"),
                    "failure_kind": diagnostics.get("failure_kind"),
                    "exception_type": diagnostics.get("exception_type"),
                    "message": _bounded_watch_text(diagnostics.get("message")),
                    "last_success_seq": diagnostics.get("last_success_seq"),
                },
                status=health,
            )
        )
    return lines


def _render_structlog_console(
    event_dict: dict[str, object], *, status: object | None = None
) -> str:
    """Render all allowlisted diagnostics while color-coding watchdog health."""
    renderer = structlog.dev.ConsoleRenderer(colors=False)
    fields = {key: value for key, value in event_dict.items() if value is not None}
    rendered = renderer(None, "info", fields)
    color = {
        # Stream/watchdog vocabulary (healthy/suspect/unhealthy) plus the sink
        # health vocabulary (healthy/degraded/failed) — both map onto the same
        # green/yellow/red console scale.
        "healthy": "green",
        "suspect": "yellow",
        "degraded": "yellow",
        "unhealthy": "red",
        "failed": "red",
    }.get(status if isinstance(status, str) else "")
    return click.style(rendered, fg=color) if color is not None else rendered


def _fraction(numerator: object, denominator: object) -> str | None:
    if numerator is None and denominator is None:
        return None
    numerator_text = numerator if numerator is not None else "?"
    denominator_text = denominator if denominator is not None else "?"
    return f"{numerator_text}/{denominator_text}"


def _bounded_watch_text(value: object, limit: int = 200) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _iter_sse_events(lines) -> object:
    event: dict[str, object] = {}
    data_lines: list[str] = []

    for line in lines:
        if line == "":
            if event or data_lines:
                yield _build_sse_event(event, data_lines)
                event = {}
                data_lines = []
            continue
        if line.startswith(":"):
            continue

        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "id":
            event["id"] = value
        elif field == "event":
            event["event"] = value
        elif field == "data":
            data_lines.append(value)

    if event or data_lines:
        yield _build_sse_event(event, data_lines)


def _build_sse_event(event: dict[str, object], data_lines: list[str]) -> dict[str, object]:
    raw_data = "\n".join(data_lines)
    try:
        data: object = json.loads(raw_data)
    except json.JSONDecodeError:
        data = raw_data

    return {
        "id": event.get("id"),
        "event": event.get("event", "message"),
        "data": data,
    }


@session.command(name="validate")
@click.argument(
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def validate_command(config_file: Path) -> None:
    """Validate a session-config file without the daemon."""
    try:
        source = load_config_file(config_file)
        with create_app().app_context():
            validate_config_source(source, config_type="session")
    except _EXPECTED_VALIDATION_ERRORS as exc:
        exit_with_error(exc)
    except OSError as exc:
        exit_with_error(exc)

    click.echo(f"valid session config: {source.path}")


@session.command(name="preview")
@click.argument(
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def preview_command(config_file: Path) -> None:
    """Preview the runtime manifest for a session-config file without persisting it."""
    try:
        source = load_config_file(config_file)
        with create_app().app_context():
            manifest = manifests.build_for_preview(source.content, format=source.format)
    except _EXPECTED_VALIDATION_ERRORS as exc:
        exit_with_error(exc)
    except OSError as exc:
        exit_with_error(exc)

    echo_json(manifest.to_dict())


@session.group(name="template")
def session_template() -> None:
    """Manage reusable session templates — Flow 2's snapshot-copy source."""


_SESSION_TEMPLATE_LIST_HEADERS = ("name", "content_hash", "reference")


@session_template.command(name="list")
def list_session_templates_command() -> None:
    """List reusable session templates from the daemon."""
    try:
        templates = _session_template_catalog(DaemonClient())
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    if not templates:
        click.echo("no session templates")
        return
    echo_table(templates, _SESSION_TEMPLATE_LIST_HEADERS)


@session_template.command(name="show")
@click.argument("name")
def show_session_template_command(name: str) -> None:
    """Show a reusable session template from the daemon."""
    try:
        response = DaemonClient().get(f"/api/v1/session-templates/{_path_segment(name)}")
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@session_template.command(name="delete")
@click.option("--force", is_flag=True, help="Skip the confirmation prompt.")
@click.argument("reference")
def delete_session_template_command(reference: str, force: bool) -> None:
    """Delete a stored or local session template by name or list number."""
    try:
        client = DaemonClient()
        source, name, path = _resolve_session_template_delete_target(client, reference)
        if not force:
            click.confirm(f"Delete session template {name!r}?", abort=True)
        if source == "local":
            if path is None:
                raise ValueError(f"Local session template {name!r} has no file path.")
            path.unlink()
            response = {"deleted_name": name, "source": "local"}
        else:
            response = client.delete(f"/api/v1/session-templates/{_path_segment(name)}")
            response = response if isinstance(response, Mapping) else {}
            response = {"deleted_name": name, "source": "stored", **response}
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


def _resolve_session_template_delete_target(
    client: DaemonClient,
    reference: str,
) -> tuple[str, str, Path | None]:
    try:
        ordinal = int(reference)
    except ValueError:
        ordinal = None

    if ordinal is not None:
        templates = _session_template_catalog(client)
        if not 1 <= ordinal <= len(templates):
            raise ValueError(f"no session template at position {ordinal}; run 'session template list'")
        row = templates[ordinal - 1]
        source = str(row.get("source") or "stored")
        name = str(row.get("name") or row.get("reference") or "")
        if source == "local":
            return source, name, Path(str(row["reference"]))
        return source, name, None

    local_path = _library_template_path(reference)
    if local_path is not None:
        return "local", local_path.stem, local_path
    return "stored", reference, None


@session_template.command(name="import")
@click.option(
    "--name",
    "template_name",
    required=True,
    help="Name to save the imported session template as.",
)
@click.argument(
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def import_session_template_command(config_file: Path, template_name: str) -> None:
    """Import a portable session-template file, resolving device-template names to ids."""
    try:
        client = DaemonClient()
        content = _load_session_template_file(config_file)
        by_path, by_name = _device_template_index(client)
        normalized_flows = [
            _normalize_template_flow_ref(flow, by_path, by_name)
            for flow in content["device_flows"]
        ]
        payload: dict[str, object] = {"name": template_name, "device_flows": normalized_flows}
        if content.get("policy") is not None:
            payload["policy"] = content["policy"]
        response = client.post("/api/v1/session-templates", payload)
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@session_template.command(name="export")
@click.argument("session_reference")
@click.argument("export_name_or_path")
def export_session_template_command(session_reference: str, export_name_or_path: str) -> None:
    """Save a reusable session template from an existing session.

    A NAME (no path separator or .toml/.json suffix) persists a new stored
    session template through the daemon and writes the same portable TOML
    content to the session-template library. A PATH writes a portable
    session-template file locally instead (no daemon required).

    Each device flow resolves to a device-template reference; a device config
    with no reusable source template gets one created on export (default name:
    {device_type}-{session_slug}-{flow_label}-{params_hash8}).
    """
    session_id = _resolve_session_id(DaemonClient(), session_reference)
    binding_mode = click.prompt(
        "Export binding",
        type=click.Choice(("generic", "device-hardcoded")),
        default="generic",
    )
    include_hardware_id = binding_mode == "device-hardcoded"
    target = Path(export_name_or_path)
    is_path = target.suffix.lower() in {".toml", ".json"} or len(target.parts) > 1

    if is_path:
        export_format = "json" if target.suffix.lower() == ".json" else "toml"
        target = _export_target_path(target)
        try:
            with create_app().app_context():
                session = sessions_service.get(session_id)
                content = session_config.export(
                    session,
                    format=export_format,
                    include_hardware_id=include_hardware_id,
                )
        except _SESSION_EXPORT_ERRORS as exc:
            exit_with_error(exc)
        target.write_text(content, encoding="utf-8")
        click.echo(f"saved session template: {target}")
        return

    try:
        response = DaemonClient().post(
            f"/api/v1/sessions/{session_id}/template-export",
            {"name": export_name_or_path, "binding_mode": binding_mode},
        )
        if not isinstance(response, Mapping) or not isinstance(response.get("content"), Mapping):
            raise ValueError("Session template export response must include content.")
        saved_path = _session_template_file_path(export_name_or_path)
        saved_path.write_text(
            _render_session_template_content(response["content"], format="toml"),
            encoding="utf-8",
        )
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    click.echo(f"saved session template TOML: {saved_path}", err=True)
    echo_json(response)


__all__ = [
    "create_command",
    "export_session_template_command",
    "import_session_template_command",
    "list_command",
    "list_session_templates_command",
    "preview_command",
    "recover_command",
    "session",
    "session_template",
    "show_session_template_command",
    "start_command",
    "status_command",
    "stop_command",
    "validate_command",
    "watch_command",
]
