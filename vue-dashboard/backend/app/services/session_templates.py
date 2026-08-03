"""Persistent session-template compositions.

Session templates reference device-template files by path and canonical content
hash.  They do not contain device-template database IDs.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import current_app

from app.database import transaction
from app.domain.errors import DeviceTemplateNotFound, InvalidSessionEntry, SessionTemplateNameExists, SessionTemplateNotFound
from app.models.session import Session
from app.models.session_template import SessionTemplate
from app.repositories.session_templates import SessionTemplateRepository
from app.services import device_templates
from app.services.session_config import _policy_value, _resolve_sinks

_repository = SessionTemplateRepository()
# Fields accepted on a raw template device-flow entry. ``sinks`` is the
# canonical multi-sink collection (packet 02 shape); ``sink_type``/
# ``sink_location``/``sink_parameters`` are the retained legacy flattened form
# (a single sink expressed at the top level). ``_resolve_sinks`` normalizes
# either shape to an ordered ``sinks[]`` list and rejects mixing the two.
_FLOW_FIELDS = {
    "device_template_path",
    "device_template_content_hash",
    "hardware_id",
    "nickname",
    "sinks",
    "sink_type",
    "sink_location",
    "sink_parameters",
}
_CONTENT_FIELDS = {"policy", "device_flows"}
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HARDWARE_ID_PATTERN = re.compile(r"^[0-9A-Za-z]{4,8}$")


def _normalize_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("session template name must be a string")
    normalized = name.strip()
    for suffix in (".toml", ".json"):
        if normalized.lower().endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip()
            break
    if not normalized:
        raise ValueError("session template name is required")
    return normalized


def _canonical_flow(raw_flow: Any) -> dict[str, Any]:
    if not isinstance(raw_flow, Mapping):
        raise InvalidSessionEntry("device_flows", "each flow must be a mapping")
    unknown = set(raw_flow) - _FLOW_FIELDS
    if unknown:
        raise InvalidSessionEntry(",".join(sorted(unknown)), f"unknown field(s): {', '.join(sorted(unknown))}")
    path = raw_flow.get("device_template_path")
    if not isinstance(path, str) or not path.strip():
        raise InvalidSessionEntry("device_template_path", "is required")
    template = device_templates.get_by_path(path)
    if template is None:
        raise DeviceTemplateNotFound(path)
    sinks = _resolve_sinks(raw_flow)
    expected_hash = raw_flow.get("device_template_content_hash", template.content_hash)
    if not isinstance(expected_hash, str) or not _HASH_PATTERN.fullmatch(expected_hash):
        raise InvalidSessionEntry("device_template_content_hash", "must be a SHA-256 hex digest")
    canonical: dict[str, Any] = {
        "device_template_path": template.file_path,
        "device_template_content_hash": expected_hash,
        "sinks": sinks,
    }
    if raw_flow.get("hardware_id") is not None:
        hardware_id = raw_flow["hardware_id"]
        if not isinstance(hardware_id, str) or not _HARDWARE_ID_PATTERN.fullmatch(hardware_id.strip()):
            raise InvalidSessionEntry("hardware_id", "must be exactly five alphanumeric characters")
        canonical["hardware_id"] = hardware_id.strip()
    if raw_flow.get("nickname") is not None:
        nickname = raw_flow["nickname"]
        if not isinstance(nickname, str) or not nickname.strip():
            raise InvalidSessionEntry("nickname", "must be a non-empty string")
        canonical["nickname"] = nickname.strip()
    return canonical


def _canonicalize(raw_content: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_content, Mapping):
        raise ValueError("session template content must be a mapping")
    unknown = set(raw_content) - _CONTENT_FIELDS
    if unknown:
        raise ValueError(f"unknown session template fields: {', '.join(sorted(unknown))}")
    raw_flows = raw_content.get("device_flows")
    if not isinstance(raw_flows, builtins.list) or not raw_flows:
        raise ValueError("session template device_flows must be a non-empty list")
    return {
        "policy": _policy_value(raw_content.get("policy")).value,
        "device_flows": [_canonical_flow(flow) for flow in raw_flows],
    }


def _content_hash(content: Mapping[str, Any]) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def resolve_device_template_reference(flow: Mapping[str, Any]):
    """Resolve a path/hash reference and return ``(template, warnings)``."""
    path = flow.get("device_template_path")
    if not isinstance(path, str) or not path.strip():
        raise DeviceTemplateNotFound(str(path))
    expected_hash = flow.get("device_template_content_hash")
    template = device_templates.get_by_path(path)
    warnings: list[str] = []
    if template is not None:
        if expected_hash and expected_hash != template.content_hash:
            warnings.append(
                f"device template changed at {template.file_path}: expected {expected_hash}, found {template.content_hash}"
            )
        return template, warnings
    if not isinstance(expected_hash, str) or not expected_hash:
        raise DeviceTemplateNotFound(path)
    matches = device_templates.find_by_content_hash(expected_hash)
    if len(matches) == 1:
        warnings.append(f"device template path missing; using hash match {matches[0].file_path}")
        return matches[0], warnings
    if len(matches) > 1:
        raise ValueError(f"device template path {path!r} is missing and its hash matches multiple files")
    raise DeviceTemplateNotFound(path)


def _attach_reference_warnings(row: SessionTemplate) -> SessionTemplate:
    warnings: list[str] = []
    flows = (row.content or {}).get("device_flows", [])
    for index, flow in enumerate(flows, start=1):
        if not isinstance(flow, Mapping):
            continue
        try:
            _, flow_warnings = resolve_device_template_reference(flow)
            warnings.extend(f"flow {index}: {warning}" for warning in flow_warnings)
        except DeviceTemplateNotFound:
            warnings.append(
                f"flow {index}: device template path {flow.get('device_template_path')!r} cannot be resolved"
            )
        except ValueError as exc:
            warnings.append(f"flow {index}: {exc}")
    row.reference_warnings = warnings
    return row


def create(name: str, raw_content: Mapping[str, Any]) -> SessionTemplate:
    normalized_name = _normalize_name(name)
    canonical = _canonicalize(raw_content)
    content_hash = _content_hash(canonical)
    with transaction():
        existing = _repository.get_by_name(normalized_name)
        if existing is not None:
            if existing.content_hash == content_hash:
                return _attach_reference_warnings(existing)
            raise SessionTemplateNameExists(normalized_name)
        row = _repository.create(name=normalized_name, content=canonical, content_hash=content_hash)
    return _attach_reference_warnings(row)


def update(name: str, raw_content: Mapping[str, Any]) -> SessionTemplate:
    normalized_name = _normalize_name(name)
    canonical = _canonicalize(raw_content)
    content_hash = _content_hash(canonical)
    with transaction():
        row = _repository.get_by_name(normalized_name)
        if row is None:
            raise SessionTemplateNotFound(normalized_name)
        row.content = canonical
        row.content_hash = content_hash
    return _attach_reference_warnings(row)


def get_by_id(template_id: int) -> SessionTemplate | None:
    row = _repository.get_by_id(template_id)
    return None if row is None else _attach_reference_warnings(row)


def get_by_name(name: str) -> SessionTemplate | None:
    row = _repository.get_by_name(_normalize_name(name))
    return None if row is None else _attach_reference_warnings(row)


def list() -> list[SessionTemplate]:  # noqa: A001
    return [_attach_reference_warnings(row) for row in _repository.list()]


def _library_dir() -> Path:
    configured = Path(current_app.config["SESSION_TEMPLATE_DIR"])
    directory = configured if configured.is_absolute() else Path(current_app.instance_path) / configured
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def _load_library_file(path: Path) -> dict[str, Any]:
    """Leniently parse one library file.

    Mirrors the CLI's ``_load_session_template_file``: no canonicalization and
    no device-reference resolution, so a draft referencing a missing device
    template still lists instead of disappearing.
    """
    text = path.read_text(encoding="utf-8")
    parsed = json.loads(text) if path.suffix.lower() == ".json" else tomllib.loads(text)
    if not isinstance(parsed, Mapping):
        raise ValueError("session template file must parse to a mapping")
    raw_flows = parsed.get("device_flows")
    if not isinstance(raw_flows, builtins.list) or not raw_flows:
        raise ValueError("session template file device_flows must be a non-empty list")
    return {"policy": parsed.get("policy"), "device_flows": builtins.list(raw_flows)}


def catalog() -> builtins.list[dict[str, Any]]:
    """Stored templates plus on-disk library drafts, tagged by ``source``.

    Server-side equivalent of the CLI's ``_session_template_catalog``, which the
    browser cannot reproduce because it has no filesystem access. The
    stored-then-local ordering and the ``source`` split match the CLI so both
    surfaces describe the library the same way.

    A name may appear twice — once ``stored``, once ``local`` — when a file has
    also been imported; differing ``content_hash`` values then mean the on-disk
    draft has diverged from the stored copy.
    """
    entries: builtins.list[dict[str, Any]] = [
        {
            "source": "stored",
            "name": row.name,
            "content_hash": row.content_hash,
            "content": row.content,
            "reference": row.name,
            "warnings": getattr(row, "reference_warnings", []),
        }
        for row in list()
    ]
    candidates = sorted(
        (
            candidate
            for candidate in _library_dir().iterdir()
            if candidate.is_file() and candidate.suffix.lower() in {".toml", ".json"}
        ),
        key=lambda candidate: (candidate.stem.lower(), candidate.suffix.lower()),
    )
    for path in candidates:
        entry: dict[str, Any] = {
            "source": "local",
            "name": path.stem,
            "reference": f"session-templates/{path.name}",
        }
        try:
            content = _load_library_file(path)
        except (OSError, ValueError) as exc:
            # An unreadable draft is reported in-band; one bad file must not
            # blank the whole library view.
            entries.append({**entry, "content_hash": "", "content": None, "warnings": [str(exc)]})
            continue
        entries.append({**entry, "content_hash": _content_hash(content), "content": content, "warnings": []})
    return entries


def _looks_like_library_reference(reference: str) -> bool:
    normalized = reference.replace("\\", "/")
    if normalized.startswith("session-templates/"):
        return True
    return Path(normalized).suffix.lower() in {".toml", ".json"}


def _library_file_for_reference(reference: str) -> Path | None:
    """Map a catalog/CLI reference onto a file under the session-template dir.

    Accepts ``session-templates/<file>``, a bare filename, or a stem. Rejects
    path traversal so a crafted reference cannot escape the library.
    """
    library = _library_dir()
    relative = reference.strip().replace("\\", "/")
    if relative.startswith("session-templates/"):
        relative = relative[len("session-templates/") :]
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None
    candidates = [library / relative]
    if Path(relative).suffix.lower() not in {".toml", ".json"}:
        candidates.extend((library / f"{relative}.toml", library / f"{relative}.json"))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and (resolved == library or library in resolved.parents):
            return resolved
    return None


class _PlanTemplate:
    """Minimal name/content carrier shared by stored rows and local drafts."""

    __slots__ = ("name", "content", "reference")

    def __init__(self, *, name: str, content: Mapping[str, Any], reference: str):
        self.name = name
        self.content = dict(content)
        self.reference = reference


def resolve_for_plan(reference: str) -> _PlanTemplate:
    """Resolve a catalog ``reference`` (or stored name) for assignment planning.

    Explicit library refs (``session-templates/<file>`` or a ``.toml``/``.json``
    path) always load the on-disk draft. Bare names try the stored table first,
    then fall back to a same-stem library file so folder-only drafts still plan.
    """
    if not isinstance(reference, str) or not reference.strip():
        raise SessionTemplateNotFound(reference if isinstance(reference, str) else "")
    ref = reference.strip()

    if _looks_like_library_reference(ref):
        path = _library_file_for_reference(ref)
        if path is None:
            raise SessionTemplateNotFound(ref)
        try:
            content = _load_library_file(path)
        except (OSError, ValueError) as exc:
            raise SessionTemplateNotFound(ref) from exc
        return _PlanTemplate(name=path.stem, content=content, reference=f"session-templates/{path.name}")

    row = get_by_name(ref)
    if row is not None:
        return _PlanTemplate(name=row.name, content=row.content or {}, reference=row.name)

    path = _library_file_for_reference(ref)
    if path is not None:
        try:
            content = _load_library_file(path)
        except (OSError, ValueError) as exc:
            raise SessionTemplateNotFound(ref) from exc
        return _PlanTemplate(name=path.stem, content=content, reference=f"session-templates/{path.name}")

    raise SessionTemplateNotFound(ref)


def delete(name: str) -> None:
    normalized = _normalize_name(name)
    with transaction():
        row = _repository.get_by_name(normalized)
        if row is None:
            raise SessionTemplateNotFound(normalized)
        _repository.delete(row)


def import_config(source: Mapping[str, Any], *, name: str | None = None) -> SessionTemplate:
    if not isinstance(source, Mapping):
        raise ValueError("session template source must be a mapping")
    data = dict(source)
    template_name = name if name is not None else data.pop("name", None)
    if template_name is None:
        raise ValueError("session template name is required")
    data.pop("name", None)
    return create(template_name, data)


def create_from_session(session: Session, name: str, *, include_hardware_id: bool = False) -> SessionTemplate:
    from app.services.session_config import _template_for_export
    from app.services import device_configs

    device_flows: list[dict[str, Any]] = []
    for index, entry in enumerate(session.device_flows or [], start=1):
        template = _template_for_export(session, entry, index)
        # Canonical ``Session.device_flows`` entries carry the full ordered
        # ``sinks[]`` collection (packet 02). Copy it straight through so the
        # template preserves every sink's name/type/location/parameters and
        # order; ``create`` re-validates it via ``_resolve_sinks``.
        flow: dict[str, Any] = {
            "device_template_path": template.file_path,
            "device_template_content_hash": template.content_hash,
            "sinks": entry["sinks"],
        }
        if entry.get("nickname") is not None:
            flow["nickname"] = entry["nickname"]
        if include_hardware_id and entry.get("device_config_id") is not None:
            config = device_configs.get_by_id(int(entry["device_config_id"]))
            if config is not None:
                flow["hardware_id"] = config.hardware_id
        device_flows.append(flow)

    policy = session.policy.value if hasattr(session.policy, "value") else str(session.policy)
    return create(name, {"policy": policy, "device_flows": device_flows})
