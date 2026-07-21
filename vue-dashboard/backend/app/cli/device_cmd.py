"""Offline device-related CLI commands."""

from __future__ import annotations

import json
import shutil
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import click
from flask import current_app

from app import create_app
from app.cli.daemon_client import DaemonClient, DaemonError, DaemonUnavailable
from app.cli.output import echo_json, echo_table, exit_with_error
from app.domain.errors import (
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    UnknownConfigType,
)
from app.services.device_templates import _canonicalize as _canonicalize_device_template
from app.services.device_templates import content_hash as device_template_content_hash
from app.services.device_templates import export_artifact as export_device_template_artifact
from app.services.registry import device_parameter_schema
from app.services.session_config import (
    _canonicalize as _canonicalize_session_config,
)
from app.services.session_config import (
    _parse_source as _parse_session_source,
)

_EXPECTED_VALIDATION_ERRORS = (
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    UnknownConfigType,
    ValueError,
)
_DEVICE_LIST_HEADERS = ("id", "nickname", "type", "hardware_id", "port", "availability", "status","owner","color")
_DEVICE_TEMPLATE_LIST_HEADERS = ("name", "type", "reference", "content_hash")
_DEVICE_TYPE_ALIASES = {
    "8206": "pod8206hr",
    "8206hr": "pod8206hr",
    "pod8206hr": "pod8206hr",
    "8401": "pod8401hr",
    "8401hr": "pod8401hr",
    "pod8401hr": "pod8401hr",
}
_SESSION_SHAPE_FIELDS = {"device_flows", "policy"}


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """Raw config file content plus an optional parser hint from the suffix."""

    path: Path
    content: str
    format: str | None


@click.group(name="device")
def device() -> None:
    """Manage device-related local commands."""


@device.command(name="list")
def list_command() -> None:
    """List discovered devices and daemon pool status."""
    try:
        response = DaemonClient().get("/api/v1/devices/pool")
        devices = _devices_from_pool_response(response)
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    if not devices:
        click.echo("no devices")
        return
    echo_table(devices, _DEVICE_LIST_HEADERS)


@device.command(name="config")
@click.argument("device_reference")
@click.option(
    "--type",
    "-t",
    "device_type",
    type=click.Choice(sorted(_DEVICE_TYPE_ALIASES), case_sensitive=False),
    default=None,
    help="Device type for direct config creation, e.g. 8206 or 8401.",
)
@click.option("--template", "template_name", default=None, help="Device template name to copy.")
@click.option("--port", default=None, help="Serial port override for this physical device.")
@click.option("--parameters", default=None, help="JSON object of device parameters.")
@click.option("--nickname", default=None, help="Optional operator-facing label.")
def config_command(
    device_reference: str,
    device_type: str | None,
    template_name: str | None,
    port: str | None,
    parameters: str,
    nickname: str | None,
) -> None:
    """Create a persisted physical device config."""
    try:
        client = DaemonClient()
        registration = None
        hardware_id = device_reference
        normalized_device_type = (
            _normalize_device_type(device_type) if device_type is not None else None
        )
        # Resolve an exact nickname first. A nickname can itself satisfy the
        # five-character hardware-ID syntax (for example, ``A1B2C``).
        registration = _find_device_registration(client, device_reference)
        if registration is None and not _looks_like_hardware_id(device_reference):
            raise ValueError(
                f"No device registration or hardware ID found for {device_reference!r}."
            )
        if registration is not None:
            hardware_id = _required_string(registration, "hardware_id")
            registration_type = _required_string(registration, "type")
            if (
                normalized_device_type is not None
                and normalized_device_type != registration_type
            ):
                raise ValueError(
                    f"device reference {device_reference!r} is {registration_type!r}, "
                    f"not {normalized_device_type!r}"
                )
            normalized_device_type = registration_type

        if registration is not None and nickname is not None:
            registered_nickname = _required_string(registration, "nickname")
            if nickname != registered_nickname:
                raise ValueError(
                    f"device reference {device_reference!r} is already named "
                    f"{registered_nickname!r}; omit --nickname"
                )

        if registration is not None and isinstance(registration.get("device_config_id"), int):
            response = client.get(
                f"/api/v1/device-configs/{registration['device_config_id']}"
            )
            echo_json(response)
            return

        if template_name is not None:
            if registration is not None:
                template = client.get(f"/api/v1/device-templates/{quote(template_name, safe='')}")
                template_type = _required_string(template, "type")
                if template_type != normalized_device_type:
                    raise ValueError(
                        f"template {template_name!r} is for {template_type!r}, "
                        f"but {device_reference!r} is {normalized_device_type!r}"
                    )
            resolved_port = port or _resolve_device_port(
                client,
                hardware_id=hardware_id,
                device_type=normalized_device_type,
            )
            payload = {
                "template_name": template_name,
                "hardware_id": hardware_id,
                "port": resolved_port,
            }
            if registration is not None:
                payload["nickname"] = _required_string(registration, "nickname")
            elif nickname is not None:
                payload["nickname"] = nickname
            response = client.post("/api/v1/device-configs/from-template", payload)
        else:
            if normalized_device_type is None:
                raise click.UsageError("--type is required unless --template is used.")
            resolved_port = port or _resolve_device_port(
                client,
                hardware_id=hardware_id,
                device_type=normalized_device_type,
            )
            payload = {
                "type": normalized_device_type,
                "hardware_id": hardware_id,
                "port": resolved_port,
                "parameters": _device_parameters_from_cli(
                    normalized_device_type,
                    parameters,
                ),
            }
            if registration is not None:
                payload["nickname"] = _required_string(registration, "nickname")
            elif nickname is not None:
                payload["nickname"] = nickname
            response = client.post("/api/v1/device-configs", payload)
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@device.command(name="name")
@click.argument("hardware_id")
@click.option(
    "--type",
    "device_type",
    required=True,
    type=click.Choice(sorted(_DEVICE_TYPE_ALIASES), case_sensitive=False),
    help="Device type for the physical device, e.g. 8206 or 8401.",
)
@click.argument("nickname")
def name_device_command(hardware_id: str, device_type: str, nickname: str) -> None:
    """Register an operator-facing name before or after configuration."""
    try:
        client = DaemonClient()
        payload = {
            "type": _normalize_device_type(device_type),
            "hardware_id": hardware_id,
            "nickname": nickname,
        }
        try:
            response = client.post("/api/v1/device-configs/name", payload)
        except DaemonError as exc:
            if exc.status_code != 404:
                raise
            response = client.post("/api/v1/device-registrations", payload)
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@device.command(name="edit")
@click.argument("config_reference")
@click.option("--parameters", required=True, help="JSON object of replacement parameters.")
@click.option(
    "--writeback-template",
    is_flag=True,
    help="Also update the linked source template instead of severing provenance.",
)
def edit_config_command(
    config_reference: str,
    parameters: str,
    writeback_template: bool,
) -> None:
    """Edit a device config by numeric id or nickname."""
    try:
        client = DaemonClient()
        config_id = _resolve_device_config_id(client, config_reference)
        payload = {
            "parameters": _parse_json_object(parameters, "parameters"),
            "update_source_template": writeback_template,
        }
        response = _patch_daemon(
            client,
            f"/api/v1/device-configs/{config_id}",
            payload,
        )
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@device.command(name="delete")
@click.option("--force", is_flag=True, help="Skip the confirmation prompt.")
@click.argument("config_reference")
def delete_config_command(config_reference: str, force: bool) -> None:
    """Delete a free device config by numeric id or nickname."""
    if not force:
        click.confirm("Deleting a device config cannot be undone. Continue?", abort=True)
    try:
        client = DaemonClient()
        config_id = _resolve_device_config_id(client, config_reference)
        response = client.delete(f"/api/v1/device-configs/{config_id}")
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@device.group(name="template")
def template() -> None:
    """Validate and inspect device template files."""


@template.command(name="list")
@click.option(
    "--unique",
    "-u",
    is_flag=True,
    help="Collapse templates that share a content hash into a single row.",
)
def list_templates_command(unique: bool) -> None:
    """List reusable device templates from the daemon."""
    try:
        templates = _device_template_catalog(DaemonClient(), unique=unique)
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    if not templates:
        click.echo("no device templates")
        return
    echo_table(templates, _DEVICE_TEMPLATE_LIST_HEADERS)


@template.command(name="show")
@click.argument("name")
def show_template_command(name: str) -> None:
    """Show a reusable device template from the daemon."""
    try:
        library_path = _device_template_library_path(name)
        if library_path is not None:
            response = dict(_parse_device_source(load_config_file(library_path)))
        else:
            response = DaemonClient().get(f"/api/v1/device-templates/{_path_segment(name)}")
            _template_artifact_from_device_template(response)
    except (DaemonUnavailable, DaemonError, ValueError) as exc:
        exit_with_error(exc)
    except OSError as exc:
        exit_with_error(exc)

    echo_json(response)


@template.command(name="import")
@click.argument(
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--name",
    "template_name",
    default=None,
    help="Save the template with this name and matching file name.",
)
def import_command(config_file: Path, template_name: str | None) -> None:
    """Import a device template file into the local template library."""
    try:
        client = DaemonClient()
        source = load_config_file(config_file)
        payload = dict(_parse_device_source(source))
        if template_name is not None:
            normalized_name = template_name.strip()
            if not normalized_name:
                raise ValueError("template name is required when --name is provided")
            payload["name"] = normalized_name
        _confirm_duplicate_template_import(client, payload)
        target_path = _copy_device_template_source(
            config_file,
            artifact=payload,
            template_name=template_name,
        )
        response = _find_imported_device_template(
            client,
            file_name=target_path.name,
            artifact=payload,
        )
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@template.command(name="edit")
@click.argument("name")
@click.argument(
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
    default=None,
)
def edit_command(name: str, config_file: Path | None) -> None:
    """Edit a device template's parameters through the daemon.

    Without CONFIG_FILE, walks through each current parameter interactively
    so you can accept or replace it. With CONFIG_FILE, replaces the template's
    content wholesale from that file (the old non-interactive behavior).
    """
    try:
        client = DaemonClient()
        if config_file is not None:
            source = load_config_file(config_file)
            payload = dict(_parse_device_source(source))
            payload.pop("name", None)
        else:
            payload = _edit_template_interactively(client, name)
            if payload is None:
                click.echo("no changes made", err=True)
                return

        response = _put_daemon(
            client,
            f"/api/v1/device-templates/{_path_segment(name)}",
            payload,
        )
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)

    echo_json(response)


@template.command(name="rename")
@click.option(
    "--force",
    is_flag=True,
    help="Skip the confirmation for a reference-sensitive rename.",
)
@click.argument("old_name")
@click.argument("new_name")
def rename_command(old_name: str, new_name: str, force: bool) -> None:
    """Rename a device template through the daemon."""
    _confirm_reference_sensitive_action(
        force,
        "Renaming a template can affect sessions that reference it. Continue?",
    )
    try:
        response = DaemonClient().post(
            f"/api/v1/device-templates/{_path_segment(old_name)}/rename",
            {"new_name": new_name},
        )
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    _emit_reference_warning(response)
    echo_json(response)


@template.command(name="delete")
@click.option(
    "--force",
    is_flag=True,
    help="Skip the confirmation for a reference-sensitive delete.",
)
@click.argument("name")
def delete_command(name: str, force: bool) -> None:
    """Delete a device template through the daemon."""
    _confirm_reference_sensitive_action(
        force,
        "Deleting a template can affect sessions that reference it. Continue?",
    )
    try:
        client = DaemonClient()
        template_name = _resolve_device_template_delete_name(client, name)
        response = client.delete(f"/api/v1/device-templates/{_path_segment(template_name)}")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    _emit_reference_warning(response)
    echo_json(response)


def _resolve_device_template_delete_name(client: DaemonClient, reference: str) -> str:
    """Resolve a numeric device-template id while preserving direct name deletes."""
    if not reference.isdecimal():
        return reference

    rows = _device_templates_from_response(client.get("/api/v1/device-templates"))
    for row in rows:
        if str(row.get("id")) == reference:
            name = row.get("name")
            if isinstance(name, str) and name.strip():
                return name
    ordinal = int(reference)
    if 1 <= ordinal <= len(rows):
        name = rows[ordinal - 1].get("name")
        if isinstance(name, str) and name.strip():
            return name
    for row in rows:
        if row.get("name") == reference:
            return reference
    raise ValueError(f"No device template found with id or name {reference!r}.")


@template.command(name="validate")
@click.option(
    "--type",
    "config_type",
    type=click.Choice(["device", "session"]),
    default=None,
    help="Validate as device template or session config. Defaults to session, then device.",
)
@click.argument(
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def validate_command(config_file: Path, config_type: str | None) -> None:
    """Validate a device-template or session-config file without the daemon."""
    try:
        source = load_config_file(config_file)
        with create_app().app_context():
            resolved_type = validate_config_source(source, config_type=config_type)
    except _EXPECTED_VALIDATION_ERRORS as exc:
        exit_with_error(exc)
    except OSError as exc:
        exit_with_error(exc)

    click.echo(f"valid {resolved_type} config: {source.path}")


@template.command(name="export")
@click.option(
    "--force",
    is_flag=True,
    help="Allow saving a new template name with content that already exists.",
)
@click.argument("config_reference")
@click.argument("artifact_name")
def export_command(
    config_reference: str,
    artifact_name: str,
    force: bool,
) -> None:
    """Export a device config as a reusable device template."""
    try:
        client = DaemonClient()
        config_id = _resolve_device_config_id(client, config_reference)
        _emit_or_save_config_template_export(
            client,
            client.get(f"/api/v1/device-configs/{config_id}"),
            name=artifact_name,
            force=force,
        )
    except (DaemonUnavailable, DaemonError, OSError, ValueError) as exc:
        exit_with_error(exc)


def load_config_file(config_file: Path) -> ConfigSource:
    """Read a JSON/TOML config file and infer a parser hint from its suffix."""
    suffix = config_file.suffix.lower()
    if suffix == ".json":
        format_hint = "json"
    elif suffix == ".toml":
        format_hint = "toml"
    else:
        format_hint = None

    return ConfigSource(
        path=config_file,
        content=config_file.read_text(encoding="utf-8"),
        format=format_hint,
    )


def validate_config_source(source: ConfigSource, *, config_type: str | None) -> str:
    """Validate *source* and return the resolved config type."""
    if config_type == "session":
        _validate_session_config(source)
        return "session"
    if config_type == "device":
        _validate_device_template(source)
        return "device"

    try:
        _validate_session_config(source)
    except _EXPECTED_VALIDATION_ERRORS as session_error:
        if _looks_like_session_config(source):
            raise session_error
        _validate_device_template(source)
        return "device"
    return "session"


def _validate_session_config(source: ConfigSource) -> None:
    parsed = _parse_session_source(source.content, format=source.format)
    _canonicalize_session_config(parsed, instantiate=False)


def _validate_device_template(source: ConfigSource) -> None:
    parsed = _parse_device_source(source)
    _canonicalize_device_template(parsed)


def _parse_device_source(source: ConfigSource) -> Mapping[str, object]:
    if source.format == "json":
        parsed = json.loads(source.content)
    elif source.format == "toml":
        parsed = tomllib.loads(source.content)
    elif source.format is None:
        try:
            parsed = json.loads(source.content)
        except json.JSONDecodeError:
            parsed = tomllib.loads(source.content)
    else:
        raise ValueError(f"unsupported format: {source.format!r}")

    if not isinstance(parsed, Mapping):
        raise ValueError("device template source must parse to a mapping")
    return parsed


def _looks_like_session_config(source: ConfigSource) -> bool:
    try:
        parsed = _parse_session_source(source.content, format=source.format)
    except ValueError:
        return False
    return any(field in parsed for field in _SESSION_SHAPE_FIELDS)


def _devices_from_pool_response(response: object) -> list[dict[str, object]]:
    if not isinstance(response, Mapping):
        raise ValueError("Device pool response must be an object.")
    raw_devices = response.get("devices")
    if not isinstance(raw_devices, list):
        raise ValueError("Device pool response must include a devices list.")

    devices: list[dict[str, object]] = []
    for raw_device in raw_devices:
        if not isinstance(raw_device, Mapping):
            raise ValueError("Device pool response devices must be objects.")
        device_row = dict(raw_device)
        device_row["id"] = "" if device_row.get("id") is None else device_row["id"]
        device_row["owner"] = "" if device_row.get("owner") is None else device_row["owner"]
        devices.append(device_row)
    return devices


def _device_templates_from_response(response: object) -> list[dict[str, object]]:
    if not isinstance(response, list):
        raise ValueError("Device template list response must be an array.")

    templates: list[dict[str, object]] = []
    for raw_template in response:
        if not isinstance(raw_template, Mapping):
            raise ValueError("Device template list response items must be objects.")
        _template_artifact_from_device_template(raw_template)
        templates.append(dict(raw_template))
    return templates


def _resolve_instance_relative_path(path: str, *, base_dir: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else base_dir / candidate


def _device_template_library_dir() -> Path:
    app = create_app()
    with app.app_context():
        configured = current_app.config["DEVICE_TEMPLATE_DIR"]
        directory = _resolve_instance_relative_path(
            str(configured),
            base_dir=Path(current_app.instance_path),
        )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _device_template_library_path(ref: str) -> Path | None:
    library_dir = _device_template_library_dir()
    normalized_ref = ref.replace("\\", "/")
    if normalized_ref.startswith(f"{library_dir.name}/"):
        normalized_ref = normalized_ref[len(library_dir.name) + 1 :]
    candidates = [library_dir / normalized_ref]
    if Path(normalized_ref).suffix.lower() not in {".toml", ".json"}:
        candidates.extend((library_dir / f"{normalized_ref}.toml", library_dir / f"{normalized_ref}.json"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _device_template_reference_location(row: Mapping[str, object]) -> str:
    file_path = row.get("file_path")
    library_dir = _device_template_library_dir()
    if isinstance(file_path, str) and file_path.strip():
        normalized = file_path.strip().replace("\\", "/")
        if normalized.startswith(f"{library_dir.name}/"):
            normalized = normalized[len(library_dir.name) + 1 :]
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = library_dir / candidate
        return candidate.resolve().parent.as_posix()
    return library_dir.resolve().as_posix()


def _copy_device_template_source(
    config_file: Path,
    *,
    artifact: Mapping[str, object],
    template_name: str | None,
) -> Path:
    target_name = (
        f"{_template_filename_stem(template_name)}.toml"
        if template_name is not None
        else config_file.name
    )
    target = _device_template_library_dir() / target_name
    if template_name is None:
        if config_file.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_file, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            export_device_template_artifact(artifact, format="toml"),
            encoding="utf-8",
        )
    return target


def _confirm_duplicate_template_import(
    client: DaemonClient,
    artifact: Mapping[str, object],
) -> None:
    duplicates = _device_templates_with_content_hash(
        client,
        device_template_content_hash(artifact),
    )
    if not duplicates:
        return

    locations = ", ".join(
        _device_template_duplicate_label(template)
        for template in duplicates
    )
    click.confirm(
        f"This template already exists here: {locations}. Still import it?",
        abort=True,
    )


def _device_templates_with_content_hash(
    client: DaemonClient,
    content_hash: str,
) -> list[dict[str, object]]:
    return [
        template
        for template in _device_templates_from_response(client.get("/api/v1/device-templates"))
        if template.get("content_hash") == content_hash
    ]


def _device_template_duplicate_label(template: Mapping[str, object]) -> str:
    file_path = template.get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        return file_path
    name = template.get("name")
    return str(name) if name else "unknown template"


def _find_imported_device_template(
    client: DaemonClient,
    *,
    file_name: str,
    artifact: Mapping[str, object],
) -> dict[str, object]:
    content_hash = device_template_content_hash(artifact)
    templates = _device_templates_from_response(client.get("/api/v1/device-templates"))
    for template in templates:
        file_path = template.get("file_path")
        if isinstance(file_path, str) and Path(file_path.replace("\\", "/")).name == file_name:
            return template
    for template in templates:
        if template.get("content_hash") == content_hash and template.get("name") == artifact.get("name"):
            return template
    raise ValueError(f"Imported template {file_name!r} was not found in the device template list.")


def _device_template_catalog(
    client: DaemonClient, *, unique: bool = False
) -> list[dict[str, object]]:
    """Build the combined stored-on-DB and /instance/device-templates device template list.
    When used with --unique will only return template with different content
    """
    stored = []
    seen_hashes: set[str] = set()
    hash_to_row: dict[str, dict[str, object]] = {}

    for template in _device_templates_from_response(client.get("/api/v1/device-templates")):
        row = dict(template)
        content_hash = row.get("content_hash")
        is_duplicate = isinstance(content_hash, str) and content_hash in seen_hashes
        if isinstance(content_hash, str):
            hash_to_row.setdefault(content_hash, row)
            seen_hashes.add(content_hash)
        if unique and is_duplicate:
            continue
        row["source"] = "stored"
        row["reference"] = _device_template_reference_location(row)
        stored.append(row)

    # The API already scans the authoritative device-template directory.
    # Listing must never register local files as a side effect.
    return [
        row
        for index, row in enumerate(stored)
        if not unique
        or not isinstance(row.get("content_hash"), str)
        or all(
            row.get("content_hash") != previous.get("content_hash")
            for previous in stored[:index]
        )
    ]

    library_dir = _device_template_library_dir()
    for path in sorted(  # iterate through list of candidate files in /instance/device-templates
        (
            candidate
            for candidate in library_dir.iterdir()
            if candidate.is_file() and candidate.suffix.lower() in {".toml", ".json"}
        ),
        key=lambda candidate: (candidate.stem.lower(), candidate.suffix.lower()),
    ):
        artifact = dict(_parse_device_source(load_config_file(path)))
        content_hash = device_template_content_hash(artifact)
        is_duplicate = content_hash in seen_hashes
        # Render like the daemon's own file_path ("device-templates/name.toml") so every
        # row's reference column stays relative and consistent, instead of falling back
        # to an absolute filesystem path only for duplicates.
        local_reference = f"{library_dir.name}/{path.name}"
        if is_duplicate:
            known_row = hash_to_row[content_hash]
            # A stored template's own backing file lives in this same library
            # directory, so scanning it naturally rediscovers that exact file.
            # That's not a second template worth listing, just the DB row's
            # mirror on disk, so skip it outright rather than showing an
            # identical row twice.
            if known_row.get("reference") == local_reference:
                seen_hashes.add(content_hash)
                continue
            row = dict(known_row)
            reference = local_reference
        else:
            response = client.post("/api/v1/device-templates", artifact)
            row = dict(response)
            hash_to_row[content_hash] = row
            reference = row.get("file_path") or local_reference
        seen_hashes.add(content_hash)
        if unique and is_duplicate:
            continue
        row["source"] = "stored"
        row["reference"] = reference
        stored.append(row)

    return stored


def _parse_json_object(raw: str, label: str) -> dict[str, object]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _resolve_device_config_id(client: DaemonClient, reference: str) -> int:
    """Resolve a numeric device-config id or a configured device nickname."""
    try:
        return int(reference)
    except (TypeError, ValueError):
        pass

    response = client.get("/api/v1/device-configs")
    if not isinstance(response, list):
        raise ValueError("Device config list response must be an array.")

    matches = [
        config
        for config in response
        if isinstance(config, Mapping) and config.get("nickname") == reference
    ]
    if not matches:
        raise ValueError(f"No device config found with id or nickname {reference!r}.")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple device configs have nickname {reference!r}; use the numeric id."
        )

    config_id = matches[0].get("id")
    if not isinstance(config_id, int):
        raise ValueError(f"Device config named {reference!r} has no valid id.")
    return config_id


def _find_device_registration(
    client: DaemonClient,
    reference: str,
) -> Mapping[str, object] | None:
    """Resolve a pre-configuration name, or return None for hardware syntax."""
    response = client.get("/api/v1/device-registrations")
    if not isinstance(response, list):
        raise ValueError("Device registration list response must be an array.")
    matches = [
        row
        for row in response
        if isinstance(row, Mapping) and row.get("nickname") == reference
    ]
    if len(matches) > 1:
        raise ValueError(f"Multiple device registrations have name {reference!r}.")
    if matches:
        return matches[0]

    # Configs created before migration 0014 may have a nickname but no
    # registration row. Preserve name-based access for those rows, while still
    # rejecting an ambiguous legacy nickname.
    config_response = client.get("/api/v1/device-configs")
    if not isinstance(config_response, list):
        raise ValueError("Device config list response must be an array.")
    config_matches = [
        row
        for row in config_response
        if isinstance(row, Mapping) and row.get("nickname") == reference
    ]
    if len(config_matches) > 1:
        raise ValueError(f"Multiple device configs have name {reference!r}; use the numeric id.")
    if not config_matches:
        return None
    config = config_matches[0]
    return {
        "type": config.get("type"),
        "hardware_id": config.get("hardware_id"),
        "nickname": config.get("nickname"),
        "device_config_id": config.get("id"),
    }


def _required_string(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Device registration response must include {field!r}.")
    return value


def _looks_like_hardware_id(value: str) -> bool:
    return len(value) == 5 and value.isalnum()


def _emit_or_save_config_template_export(
    client: DaemonClient,
    response: object,
    *,
    name: str,
    force: bool,
) -> None:
    artifact = _template_artifact_from_device_config(response, name=name)
    toml = export_device_template_artifact(artifact, format="toml")
    if not force:
        _raise_if_duplicate_template_content(client, artifact)
    client.post("/api/v1/device-templates", artifact)
    toml_path = _write_template_toml_file(name, toml, force=force)
    click.echo(toml, nl=False)
    click.echo(f"saved template: {name}", err=True)
    click.echo(f"saved TOML: {toml_path}", err=True)


def _write_template_toml_file(
    template_name: str,
    toml: str,
    *,
    force: bool,
) -> Path:
    path = _device_template_library_dir() / f"{_template_filename_stem(template_name)}.toml"
    if path.exists() and not force:
        raise ValueError(f"TOML file already exists: {path}. Pass --force to overwrite it.")
    path.write_text(toml, encoding="utf-8")
    return path


def _template_filename_stem(template_name: str) -> str:
    template_name = template_name.strip()
    for suffix in (".toml", ".json"):
        if template_name.lower().endswith(suffix):
            template_name = template_name[: -len(suffix)].rstrip()
            break
    invalid = set('<>:"/\\|?*')
    stem = "".join(
        "_" if char in invalid or ord(char) < 32 else char
        for char in template_name.strip()
    ).strip(" .")
    return stem or "device-template"


def _raise_if_duplicate_template_content(
    client: DaemonClient,
    artifact: Mapping[str, object],
) -> None:
    target_hash = device_template_content_hash(artifact)
    templates = _device_templates_from_response(client.get("/api/v1/device-templates"))
    duplicates = [
        template
        for template in templates
        if template.get("content_hash") == target_hash
    ]
    if not duplicates:
        return

    names = ", ".join(str(template.get("name", "?")) for template in duplicates)
    raise ValueError(
        f"Template content already exists as: {names}. "
        "Use that template, rename it, or pass --force to create another name "
        "with the same content."
    )


def _template_artifact_from_device_template(response: object) -> dict[str, object]:
    if not isinstance(response, Mapping):
        raise ValueError("Device template response must be an object.")

    name = response.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Device template response must include a name.")

    raw_content = response.get("content")
    content = raw_content if isinstance(raw_content, Mapping) else response
    device_type = content.get("type")
    if not isinstance(device_type, str) or not device_type:
        raise ValueError("Device template response must include a type.")

    parameters = content.get("parameters", {})
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise ValueError("Device template response parameters must be an object.")

    return {
        "name": name,
        "type": device_type,
        "parameters": dict(parameters),
    }


def _template_artifact_from_device_config(
    response: object,
    *,
    name: str | None,
) -> dict[str, object]:
    if not isinstance(response, Mapping):
        raise ValueError("Device config response must be an object.")

    device_type = response.get("type")
    if not isinstance(device_type, str) or not device_type:
        raise ValueError("Device config response must include a type.")

    parameters = response.get("parameters", {})
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise ValueError("Device config response parameters must be an object.")

    return {
        "name": name or _default_template_name_from_device_config(response, device_type),
        "type": device_type,
        "parameters": dict(parameters),
    }


def _default_template_name_from_device_config(
    response: Mapping[str, object],
    device_type: str,
) -> str:
    nickname = response.get("nickname")
    if isinstance(nickname, str) and nickname.strip():
        return nickname.strip()

    hardware_id = response.get("hardware_id")
    if isinstance(hardware_id, str) and hardware_id.strip():
        return f"{device_type}-{hardware_id.strip()}"

    config_id = response.get("id")
    if config_id is not None:
        return f"{device_type}-{config_id}"

    return device_type


def _device_parameters_from_cli(
    device_type: str,
    raw_parameters: str | None,
) -> dict[str, object]:
    if raw_parameters is not None:
        return _parse_json_object(raw_parameters, "parameters")

    schema = device_parameter_schema(device_type)
    parameters: dict[str, object] = {}
    for key in schema["required"]:
        raw_value = _prompt_parameter(key, required=True)
        parameters[key] = _parse_parameter_value(raw_value, key)
    for key in schema["optional"]:
        raw_value = _prompt_parameter(key, required=False)
        if raw_value == "":
            continue
        parameters[key] = _parse_parameter_value(raw_value, key)
    return parameters


def _normalize_device_type(value: str) -> str:
    try:
        return _DEVICE_TYPE_ALIASES[value.lower()]
    except KeyError:
        raise ValueError(f"unsupported device type: {value!r}") from None


def _resolve_device_port(
    client: DaemonClient,
    *,
    hardware_id: str,
    device_type: str | None,
) -> str:
    response = client.get("/api/v1/devices/pool")
    if not isinstance(response, Mapping):
        raise ValueError("Device pool response must be an object.")
    raw_devices = response.get("devices")
    if not isinstance(raw_devices, list):
        raise ValueError("Device pool response must include a devices list.")

    matches = []
    for raw_device in raw_devices:
        if not isinstance(raw_device, Mapping):
            continue
        if raw_device.get("hardware_id") != hardware_id:
            continue
        if device_type is not None and raw_device.get("type") != device_type:
            continue
        matches.append(raw_device)

    if not matches:
        qualifier = f" and type {device_type}" if device_type is not None else ""
        raise ValueError(
            f"No scanned device found for hardware_id {hardware_id!r}{qualifier}; "
            "pass --port to configure it manually."
        )
    if len(matches) > 1:
        raise ValueError(
            f"Multiple scanned devices match hardware_id {hardware_id!r}; pass --port."
        )

    port = matches[0].get("port")
    if not isinstance(port, str) or not port:
        raise ValueError(
            f"Scanned device {hardware_id!r} has no usable port; pass --port."
        )
    return port


def _prompt_parameter(key: str, *, required: bool) -> str:
    suffix = "" if required else " (optional, blank to skip)"
    while True:
        raw_value = click.prompt(f"{key}{suffix}", default="", show_default=False)
        raw_value = raw_value.strip()
        if raw_value or not required:
            return raw_value
        click.echo(f"{key} is required.")


_OMIT = object()


def _edit_template_interactively(
    client: DaemonClient,
    name: str,
) -> dict[str, object] | None:
    """Walk the operator through each parameter, defaulting to its saved value.

    Returns the new ``{type, parameters}`` content, or ``None`` if the operator
    left every value unchanged.
    """
    current = _template_artifact_from_device_template(
        client.get(f"/api/v1/device-templates/{_path_segment(name)}")
    )
    device_type = current["type"]
    current_parameters = dict(current["parameters"])
    schema = device_parameter_schema(device_type)

    click.echo(f"editing '{name}' (type: {device_type}) - press enter to keep a value")
    new_parameters: dict[str, object] = {}
    for key in schema["required"]:
        new_parameters[key] = _prompt_parameter_edit(
            key,
            current_value=current_parameters.get(key),
            required=True,
        )
    for key in schema["optional"]:
        value = _prompt_parameter_edit(
            key,
            current_value=current_parameters.get(key),
            required=False,
        )
        if value is not _OMIT:
            new_parameters[key] = value

    if new_parameters == current_parameters:
        return None
    return {"type": device_type, "parameters": new_parameters}


def _prompt_parameter_edit(key: str, *, current_value: object, required: bool) -> object:
    """Prompt for one parameter, defaulting to what's already saved.

    Returns ``_OMIT`` when an optional parameter is left unset or cleared.
    """
    if current_value is None:
        raw_value = _prompt_parameter(key, required=required)
        if raw_value == "":
            return _OMIT
        return _parse_parameter_value(raw_value, key)

    default = json.dumps(current_value)
    suffix = "" if required else " (optional; '-' clears)"
    raw_value = click.prompt(f"{key}{suffix}", default=default).strip()
    if not required and raw_value == "-":
        return _OMIT
    if raw_value == default:
        return current_value
    return _parse_parameter_value(raw_value, key)


def _parse_parameter_value(raw_value: str, key: str) -> object:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        if raw_value:
            return raw_value
        raise ValueError(f"{key} is required") from None


def _put_daemon(
    client: DaemonClient,
    path: str,
    payload: Mapping[str, object],
) -> object:
    put = getattr(client, "put", None)
    if put is not None:
        return put(path, payload)
    return client._request("PUT", path, payload)


def _patch_daemon(
    client: DaemonClient,
    path: str,
    payload: Mapping[str, object],
) -> object:
    patch = getattr(client, "patch", None)
    if patch is not None:
        return patch(path, payload)
    return client._request("PATCH", path, payload)


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def _confirm_reference_sensitive_action(force: bool, prompt: str) -> None:
    if force:
        return
    click.confirm(prompt, abort=True)


def _emit_reference_warning(response: object) -> None:
    if not isinstance(response, Mapping):
        return
    if response.get("warning") != "referencing_sessions":
        return
    raw_sessions = response.get("referencing_sessions")
    if not isinstance(raw_sessions, list) or not raw_sessions:
        return

    click.echo(_reference_warning(raw_sessions))


def _reference_warning(raw_sessions: list[object]) -> str:
    sessions = [session for session in raw_sessions if isinstance(session, Mapping)]
    count = len(sessions)
    noun = "session template" if count == 1 else "session templates"
    labels = ", ".join(_session_label(session) for session in sessions)
    if labels:
        return f"warning: {count} {noun} references this template: {labels}"
    return f"warning: {count} {noun} references this template"


def _session_label(session: Mapping[str, object]) -> str:
    name = session.get("name")
    session_id = session.get("id")
    if name and session_id:
        return f"{name} ({session_id})"
    if name:
        return str(name)
    if session_id:
        return str(session_id)
    return "unknown session"


__all__ = [
    "ConfigSource",
    "config_command",
    "delete_config_command",
    "device",
    "delete_command",
    "edit_config_command",
    "edit_command",
    "export_command",
    "import_command",
    "load_config_file",
    "list_command",
    "list_templates_command",
    "rename_command",
    "show_template_command",
    "template",
    "validate_command",
    "validate_config_source",
]
