"""File-authoritative device-template library."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import current_app

from app.domain.errors import DeviceTemplateNameExists, DeviceTemplateNotFound
from app.models.device_template import DeviceTemplate
from app.services.registry import lookup_device


def _template_library_dir() -> Path:
    configured = Path(current_app.config["DEVICE_TEMPLATE_DIR"])
    directory = configured if configured.is_absolute() else Path(current_app.instance_path) / configured
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def _filename_stem(name: str) -> str:
    invalid = set('<>:"/\\|?*')
    stem = "".join("_" if char in invalid or ord(char) < 32 else char for char in name).strip(" .")
    return stem or "device-template"


def _normalize_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("device template name must be a string")
    normalized = name.strip()
    for suffix in (".toml", ".json"):
        if normalized.lower().endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip()
            break
    if not normalized:
        raise ValueError("device template name is required")
    return normalized


def _normalize_reference(reference: str) -> str:
    if not isinstance(reference, str):
        raise ValueError("device template path must be a string")
    normalized = reference.strip().replace("\\", "/")
    if normalized.startswith("device-templates/"):
        normalized = normalized[len("device-templates/") :]
    if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
        raise DeviceTemplateNotFound(reference)
    if not normalized.lower().endswith(".toml"):
        normalized = f"{normalized}.toml"
    return normalized


def _path_for_reference(reference: str) -> Path:
    library = _template_library_dir()
    candidate = (library / _normalize_reference(reference)).resolve()
    if candidate != library and library not in candidate.parents:
        raise DeviceTemplateNotFound(reference)
    return candidate


def _relative_file_path(path: Path) -> str:
    return f"device-templates/{path.resolve().relative_to(_template_library_dir()).as_posix()}"


def _canonicalize(raw_content: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_content, Mapping):
        raise ValueError("device template content must be a mapping")
    unknown = set(raw_content) - {"name", "type", "parameters"}
    if unknown:
        raise ValueError(f"unknown device template fields: {', '.join(sorted(unknown))}")
    parameters = raw_content.get("parameters", {})
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise ValueError("device template parameters must be a mapping")
    spec = lookup_device(str(raw_content.get("type", "")), parameters)
    return {"type": spec.type.value, "parameters": spec.as_dict()}


def _content_hash(content: Mapping[str, Any]) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _toml_value(value: Any) -> str:
    return json.dumps(value)


def _to_toml(artifact: Mapping[str, Any]) -> str:
    lines = [f"name = {_toml_value(artifact['name'])}", f"type = {_toml_value(artifact['type'])}"]
    parameters = artifact.get("parameters", {})
    if parameters:
        lines.extend(("", "[parameters]"))
        for key in sorted(parameters):
            lines.append(f"{key} = {_toml_value(parameters[key])}")
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _read(path: Path) -> DeviceTemplate:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid device template file {path.name!r}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError(f"device template file {path.name!r} must contain a mapping")
    name = _normalize_name(str(raw.get("name") or path.stem))
    canonical = _canonicalize(raw)
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
    return DeviceTemplate(
        name=name,
        file_path=_relative_file_path(path),
        type=canonical["type"],
        content=canonical,
        content_hash=_content_hash(canonical),
        created_at=modified_at,
        modified_at=modified_at,
    )


def _iter_paths() -> list[Path]:
    return sorted(_template_library_dir().glob("*.toml"), key=lambda path: path.name.lower())


def list() -> list[DeviceTemplate]:  # noqa: A001
    templates = []
    for path in _iter_paths():
        try:
            templates.append(_read(path))
        except ValueError:
            # Configuration pickers must never offer an invalid template. The
            # catalog below still exposes it so an operator can inspect/repair it.
            continue
    return templates


def catalog() -> list[DeviceTemplate]:
    """Return every device-template file, including invalid repair candidates."""

    entries = []
    for path in _iter_paths():
        try:
            entries.append(_read(path))
            continue
        except ValueError as exc:
            validation_error = str(exc)

        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        raw: Mapping[str, Any] = {}
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, Mapping):
                raw = parsed
        except (OSError, tomllib.TOMLDecodeError):
            pass

        raw_name = raw.get("name")
        raw_type = raw.get("type")
        entries.append(DeviceTemplate(
            name=str(raw_name).strip() if isinstance(raw_name, str) and raw_name.strip() else path.stem,
            file_path=_relative_file_path(path),
            type=str(raw_type).strip() if isinstance(raw_type, str) else "",
            content=dict(raw),
            content_hash="",
            created_at=modified_at,
            modified_at=modified_at,
            status="INVALID",
            validation_error=validation_error,
        ))
    return entries


def read_source(reference: str) -> str:
    """Read one library TOML file without allowing paths outside the library."""

    path = _path_for_reference(reference)
    if not path.is_file():
        raise DeviceTemplateNotFound(reference)
    return path.read_text(encoding="utf-8")


def validate_toml(source: str) -> dict[str, Any]:
    """Validate device-template TOML in memory without writing it."""

    try:
        raw = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid device template TOML: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("device template source must contain a mapping")
    name = _normalize_name(str(raw.get("name", "device-template")))
    return {"name": name, **_canonicalize(raw)}


def repair_source(reference: str, source: str) -> DeviceTemplate:
    """Validate and atomically replace one existing device-template source."""

    path = _path_for_reference(reference)
    if not path.is_file():
        raise DeviceTemplateNotFound(reference)
    validate_toml(source)
    _write_atomic(path, source if source.endswith("\n") else f"{source}\n")
    return _read(path)


def get_by_path(file_path: str) -> DeviceTemplate | None:
    path = _path_for_reference(file_path)
    return _read(path) if path.is_file() else None


def get_by_name(name: str) -> DeviceTemplate | None:
    normalized = _normalize_name(name)
    return next(
        (template for template in list() if template.name == normalized or Path(template.file_path).stem == normalized),
        None,
    )


def get_by_id(template_id: int) -> DeviceTemplate | None:
    """Return the file-backed template row matching its stable model id."""
    from app.database import db

    return db.session.get(DeviceTemplate, template_id)


def get_by_content_hash(content_hash: str) -> DeviceTemplate | None:
    return next((template for template in list() if template.content_hash == content_hash), None)


def find_by_content_hash(content_hash: str) -> list[DeviceTemplate]:
    return [template for template in list() if template.content_hash == content_hash]


def _template_path(name: str) -> Path:
    return _template_library_dir() / f"{_filename_stem(_normalize_name(name))}.toml"


def create(name: str, raw_content: Mapping[str, Any]) -> DeviceTemplate:
    """Validate and atomically write a template file.

    Replacing the same named file is intentional and idempotent.  Listing and
    reading templates never create or mutate anything.
    """
    normalized = _normalize_name(name)
    canonical = _canonicalize(raw_content)
    path = _template_path(normalized)
    _write_atomic(path, _to_toml({"name": normalized, **canonical}))
    return _read(path)


def update(name: str, raw_content: Mapping[str, Any]) -> DeviceTemplate:
    template = get_by_name(name)
    if template is None:
        raise DeviceTemplateNotFound(name)
    return create(template.name, raw_content)


def _referencing_session_templates(file_path: str) -> list[Any]:
    from app.services import session_templates

    normalized = _normalize_reference(file_path)
    references: list[Any] = []
    for row in session_templates.catalog():
        flows = (row.content or {}).get("device_flows", [])
        if any(
            isinstance(flow, Mapping)
            and (
                (flow.get("device_template_path") or flow.get("device_template")) is not None
            )
            and _normalize_reference(
                str(flow.get("device_template_path") or flow.get("device_template"))
            ) == normalized
            for flow in flows
        ):
            references.append(row)
    return references


def references(name: str) -> list[Any]:
    template = get_by_name(name)
    return [] if template is None else _referencing_session_templates(template.file_path)


def rename(old_name: str, new_name: str) -> tuple[DeviceTemplate, list[Any]]:
    old = get_by_name(old_name)
    if old is None:
        raise DeviceTemplateNotFound(old_name)
    new = _normalize_name(new_name)
    old_path = _path_for_reference(old.file_path)
    new_path = _template_path(new)
    if new_path.exists() and new_path.resolve() != old_path.resolve():
        raise DeviceTemplateNameExists(new)
    references = _referencing_session_templates(old.file_path)
    old_path.replace(new_path)
    _write_atomic(new_path, _to_toml({"name": new, **old.content}))
    return _read(new_path), references


def delete(name: str) -> list[Any]:
    template = get_by_name(name)
    if template is not None:
        path = _path_for_reference(template.file_path)
        file_path = template.file_path
    else:
        # Invalid files are absent from list()/get_by_name() so they cannot be
        # selected for device configuration, but the catalog inspector may
        # still remove one by its safe, library-relative filename.
        path = _path_for_reference(name)
        if not path.is_file():
            raise DeviceTemplateNotFound(name)
        file_path = _relative_file_path(path)
    references = _referencing_session_templates(file_path)
    path.unlink()
    return references


def diff(config_a: DeviceTemplate, config_b: DeviceTemplate) -> dict[str, Any]:
    if config_a.content_hash == config_b.content_hash:
        return {"equal": True, "type": None, "parameters": {"added": {}, "removed": {}, "modified": {}}}
    old = config_a.content.get("parameters", {})
    new = config_b.content.get("parameters", {})
    return {
        "equal": False,
        "type": {"old": config_a.type, "new": config_b.type} if config_a.type != config_b.type else None,
        "parameters": {
            "added": {key: new[key] for key in sorted(set(new) - set(old))},
            "removed": {key: old[key] for key in sorted(set(old) - set(new))},
            "modified": {
                key: {"old": old[key], "new": new[key]}
                for key in sorted(set(old) & set(new))
                if old[key] != new[key]
            },
        },
    }


def import_config(source: str | Mapping[str, Any], *, name: str | None = None, format: str | None = None) -> DeviceTemplate:
    if isinstance(source, Mapping):
        data = dict(source)
    elif isinstance(source, str):
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
    else:
        raise ValueError("device template source must be a mapping or string")
    if not isinstance(data, Mapping):
        raise ValueError("device template source must parse to a mapping")
    template_name = name if name is not None else data.get("name")
    if template_name is None:
        raise ValueError("device template name is required")
    return create(str(template_name), data)


def export(config: DeviceTemplate, *, format: str = "json") -> str:
    artifact = {"name": config.name, **config.content}
    if format == "json":
        return json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    if format == "toml":
        return _to_toml(artifact)
    raise ValueError(f"unsupported format: {format!r}")


def export_artifact(raw_content: Mapping[str, Any], *, format: str = "json") -> str:
    name = _normalize_name(str(raw_content.get("name", "")))
    artifact = {"name": name, **_canonicalize(raw_content)}
    if format == "json":
        return json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    if format == "toml":
        return _to_toml(artifact)
    raise ValueError(f"unsupported format: {format!r}")


def content_hash(raw_content: Mapping[str, Any]) -> str:
    return _content_hash(_canonicalize(raw_content))


def clone(source: DeviceTemplate, *, name: str | None = None) -> DeviceTemplate:
    return create(name or source.name, source.content)
