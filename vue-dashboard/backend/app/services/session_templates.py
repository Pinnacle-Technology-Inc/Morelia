"""File-authoritative session-template library.

The TOML file is the only definition source. SQLite stores only registry
metadata used to identify, observe, and reconcile that file.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import current_app

from app.database import transaction
from app.domain.errors import (
    DeviceTemplateNotFound,
    InvalidSessionEntry,
    SessionTemplateNameExists,
    SessionTemplateNotFound,
)
from app.models.session import Session
from app.models.session_template import SessionTemplate
from app.repositories.session_templates import SessionTemplateRepository
from app.services import device_templates
from app.services.session_config import _policy_value, _resolve_sinks


CANONICAL_HASH_VERSION = "session-template-v1"
_repository = SessionTemplateRepository()
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
_HARDWARE_ID_PATTERN = re.compile(r"^[0-9]{1,8}$")


def _normalize_name(name: str) -> str:
    """Normalize a user-facing name without treating an extension as identity."""

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


def _filename_stem(name: str) -> str:
    """Convert a validated display name into a safe Windows-compatible stem."""

    invalid = set('<>:"/\\|?*')
    stem = "".join("_" if char in invalid or ord(char) < 32 else char for char in name).strip(" .")
    return stem or "session-template"


def _library_dir() -> Path:
    """Return and initialize the configured flat session-template directory."""

    configured = Path(current_app.config["SESSION_TEMPLATE_DIR"])
    directory = configured if configured.is_absolute() else Path(current_app.instance_path) / configured
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def _direct_file(path: Path) -> Path | None:
    """Accept only direct TOML children of the configured template directory."""

    library = _library_dir()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if resolved.parent != library or not resolved.is_file() or resolved.suffix.lower() != ".toml":
        return None
    return resolved


def _iter_library_files() -> list[Path]:
    """List direct template files in deterministic case-insensitive order."""

    library = _library_dir()
    files: list[Path] = []
    for candidate in library.iterdir():
        resolved = _direct_file(candidate)
        if resolved is not None:
            files.append(resolved)
    return sorted(files, key=lambda path: path.name.lower())


def _template_path(name: str) -> Path:
    return _library_dir() / f"{_filename_stem(_normalize_name(name))}.toml"


def _relative_path(path: Path) -> str:
    resolved = _direct_file(path)
    if resolved is None:
        raise SessionTemplateNotFound(path.name)
    return resolved.name


def _filesystem_identity(path: Path) -> str | None:
    """Return the platform file identity used as the strongest rename signal."""

    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{stat.st_dev}:{stat.st_ino}"


def _canonical_flow(raw_flow: Any, *, resolve_reference: bool) -> dict[str, Any]:
    """Validate and normalize one device flow for hashing or persisted TOML."""

    if not isinstance(raw_flow, Mapping):
        raise InvalidSessionEntry("device_flows", "each flow must be a mapping")
    unknown = set(raw_flow) - _FLOW_FIELDS
    if unknown:
        raise InvalidSessionEntry(
            ",".join(sorted(unknown)),
            f"unknown field(s): {', '.join(sorted(unknown))}",
        )
    path = raw_flow.get("device_template_path")
    if not isinstance(path, str) or not path.strip():
        raise InvalidSessionEntry("device_template_path", "is required")

    template = device_templates.get_by_path(path) if resolve_reference else None
    if resolve_reference and template is None:
        raise DeviceTemplateNotFound(path)

    expected_hash = raw_flow.get("device_template_content_hash")
    if expected_hash is None and template is not None:
        expected_hash = template.content_hash
    if expected_hash is not None:
        if not isinstance(expected_hash, str) or not _HASH_PATTERN.fullmatch(expected_hash):
            raise InvalidSessionEntry("device_template_content_hash", "must be a SHA-256 hex digest")

    sinks = _resolve_sinks(raw_flow) if resolve_reference else _canonical_file_sinks(raw_flow)
    canonical: dict[str, Any] = {
        "device_template_path": template.file_path if template is not None else path.strip(),
        "sinks": sinks,
    }
    if expected_hash is not None:
        canonical["device_template_content_hash"] = expected_hash
    if raw_flow.get("hardware_id") is not None:
        hardware_id = raw_flow["hardware_id"]
        if not isinstance(hardware_id, str) or not _HARDWARE_ID_PATTERN.fullmatch(hardware_id.strip()):
            raise InvalidSessionEntry("hardware_id", "must be 1-8 digits")
        canonical["hardware_id"] = hardware_id.strip()
    if raw_flow.get("nickname") is not None:
        nickname = raw_flow["nickname"]
        if not isinstance(nickname, str) or not nickname.strip():
            raise InvalidSessionEntry("nickname", "must be a non-empty string")
        canonical["nickname"] = nickname.strip()
    return canonical


def _canonical_file_sinks(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize already-filed sink data without checking live output paths."""

    if "sinks" in entry:
        raw_sinks = entry["sinks"]
        if not isinstance(raw_sinks, builtins.list) or not raw_sinks:
            raise InvalidSessionEntry("sinks", "must contain at least one sink")
    elif "sink_type" in entry:
        raw_sinks = [
            {
                key: entry[key]
                for key in ("sink_type", "sink_location", "sink_parameters")
                if key in entry
            }
        ]
    else:
        raise InvalidSessionEntry("sinks", "is required")

    canonical: list[dict[str, Any]] = []
    for index, raw_sink in enumerate(raw_sinks):
        if not isinstance(raw_sink, Mapping):
            raise InvalidSessionEntry(f"sinks[{index}]", "must be a mapping")
        sink_type = raw_sink.get("sink_type")
        if not isinstance(sink_type, str) or not sink_type.strip():
            raise InvalidSessionEntry(f"sinks[{index}].sink_type", "is required")
        sink_name = raw_sink.get("sink_name") or sink_type.strip().lower()
        if not isinstance(sink_name, str) or not sink_name.strip():
            raise InvalidSessionEntry(f"sinks[{index}].sink_name", "is required")
        params = raw_sink.get("sink_parameters") or {}
        if not isinstance(params, Mapping):
            raise InvalidSessionEntry(f"sinks[{index}].sink_parameters", "must be a mapping")
        item: dict[str, Any] = {
            "sink_name": sink_name.strip(),
            "sink_type": sink_type.strip().lower(),
        }
        if raw_sink.get("sink_location") is not None:
            item["sink_location"] = str(raw_sink["sink_location"])
        item["sink_parameters"] = dict(params)
        canonical.append(item)
    return canonical


def _canonicalize(raw_content: Mapping[str, Any], *, resolve_references: bool = True) -> dict[str, Any]:
    """Build the versioned semantic representation used for execution and hashing."""

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
        "device_flows": [
            _canonical_flow(flow, resolve_reference=resolve_references) for flow in raw_flows
        ],
    }


def _content_hash(content: Mapping[str, Any]) -> str:
    """Hash canonical configuration independently of TOML formatting and key order."""

    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


def _toml_value(value: Any) -> str:
    """Serialize one supported canonical value into deterministic TOML syntax."""

    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    if isinstance(value, Mapping):
        items = ", ".join(f"{_toml_key(str(key))} = {_toml_value(item)}" for key, item in value.items())
        return "{ " + items + " }"
    if isinstance(value, builtins.list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ValueError(f"unsupported TOML value: {value!r}")


def _to_toml(content: Mapping[str, Any]) -> str:
    """Serialize canonical template content without adding registry metadata."""

    lines = [f"policy = {_toml_value(content['policy'])}"]
    for flow in content["device_flows"]:
        lines.extend(("", "[[device_flows]]"))
        for key, value in flow.items():
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    """Replace one safe flat-folder TOML file through an fsynced temporary file."""

    library = _library_dir()
    safe_path = _direct_file(path) if path.exists() else path.resolve()
    if safe_path is None or safe_path.parent != library or safe_path.suffix.lower() != ".toml":
        raise SessionTemplateNotFound(path.name)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{safe_path.name}.", suffix=".tmp", dir=library)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, safe_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _load_library_file(path: Path) -> dict[str, Any]:
    """Parse and canonicalize one safe library file without resolving live devices."""

    safe_path = _direct_file(path)
    if safe_path is None:
        raise SessionTemplateNotFound(path.name)
    try:
        parsed = tomllib.loads(safe_path.read_text(encoding="utf-8"))
        return _canonicalize(parsed, resolve_references=False)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ValueError(f"invalid session template file {safe_path.name!r}: {exc}") from exc


@dataclass(frozen=True)
class _FileObservation:
    path: Path
    relative_path: str
    content: dict[str, Any] | None
    observed_hash: str | None
    filesystem_identity: str | None
    warnings: tuple[str, ...]


def _stat_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _snapshot_library() -> list[_FileObservation]:
    """Read one stable, deterministic snapshot without mutating registry state."""

    observations: list[_FileObservation] = []
    for path in _iter_library_files():
        safe_path = _direct_file(path)
        if safe_path is None:
            continue
        before = _stat_signature(safe_path)
        if before is None:
            continue
        warnings: list[str] = []
        try:
            content = _load_library_file(safe_path)
            observed_hash = _content_hash(content)
        except (OSError, ValueError, SessionTemplateNotFound) as exc:
            content = None
            observed_hash = None
            warnings.append(str(exc))
        after = _stat_signature(safe_path)
        if after != before:
            content = None
            observed_hash = None
            warnings.append(f"template file {safe_path.name!r} changed during reconciliation")
        observations.append(
            _FileObservation(
                path=safe_path,
                relative_path=safe_path.name,
                content=content,
                observed_hash=observed_hash,
                filesystem_identity=_filesystem_identity(safe_path),
                warnings=tuple(warnings),
            )
        )
    return sorted(observations, key=lambda item: item.relative_path.lower())


@dataclass
class SessionTemplateFile:
    metadata: SessionTemplate
    content: dict[str, Any] | None
    reference_warnings: list[str]

    @property
    def template_id(self) -> str:
        return self.metadata.template_id

    @property
    def id(self) -> str:
        return self.metadata.template_id

    @property
    def relative_path(self) -> str:
        return self.metadata.relative_path

    @property
    def name(self) -> str:
        return Path(self.metadata.relative_path).stem

    @property
    def registered_hash(self) -> str:
        return self.metadata.registered_hash

    @property
    def observed_hash(self) -> str | None:
        return self.metadata.observed_hash

    @property
    def content_hash(self) -> str:
        return self.metadata.observed_hash or self.metadata.registered_hash

    @property
    def filesystem_identity(self) -> str | None:
        return self.metadata.filesystem_identity

    @property
    def state(self) -> str:
        return self.metadata.state

    @property
    def lineage_parent_id(self) -> str | None:
        return self.metadata.lineage_parent_id

    @property
    def duplicate_of_template_id(self) -> str | None:
        return self.metadata.duplicate_of_template_id

    @property
    def created_at(self):
        return self.metadata.created_at

    @property
    def updated_at(self):
        return self.metadata.updated_at

    @property
    def reference(self) -> str:
        return f"session-templates/{self.relative_path}"

    @property
    def source(self) -> str:
        return "file"

    @property
    def warnings(self) -> list[str]:
        return self.reference_warnings


def _attach_reference_warnings(template: SessionTemplateFile) -> SessionTemplateFile:
    """Add non-fatal warnings for missing or changed device-template dependencies."""

    warnings = builtins.list(template.reference_warnings)
    for index, flow in enumerate((template.content or {}).get("device_flows", []), start=1):
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
    template.reference_warnings[:] = warnings
    return template


# DISCOVERED: a valid file exists but has not been registered for use.
# PENDING: a create/update crossed the file/DB boundary but has not converged yet.
# ACTIVE: the registered file matches its trusted hash and may create sessions.
# DUPLICATE: another observed file has the same canonical content as an owner.
# AMBIGUOUS_RENAME: several files could be one missing registered template.
# CHANGED: an active file differs from its trusted registered hash.
# REPLACED: an older immutable revision was replaced by an explicitly accepted revision.
# ARCHIVED: a user-retired revision; hash differences remain visible as drift warnings.
# MISSING: a registered active file cannot currently be found.
# INVALID: a file cannot be safely parsed or canonicalized.
_NON_OWNER_STATES = {"DISCOVERED", "DUPLICATE", "AMBIGUOUS_RENAME", "REPLACED"}
_ARCHIVED_STATES = {"ARCHIVED"}


def _is_registered_owner(row: SessionTemplate) -> bool:
    return bool(row.registered_hash) and row.state not in _NON_OWNER_STATES


def _row_order(row: SessionTemplate) -> tuple[str, str]:
    created_at = row.created_at.isoformat() if row.created_at is not None else ""
    return created_at, row.template_id


def _owner_state(row: SessionTemplate, observation: _FileObservation) -> str:
    """Derive an owner's safe display state while preserving pending and archive intent."""

    if row.state == "PENDING":
        return (
            "ACTIVE"
            if observation.observed_hash is not None
            and observation.observed_hash == row.registered_hash
            else "PENDING"
        )
    if observation.observed_hash is None:
        return "ARCHIVED" if row.state in _ARCHIVED_STATES else "INVALID"
    if row.state in _ARCHIVED_STATES:
        return "ARCHIVED"
    return "ACTIVE" if observation.observed_hash == row.registered_hash else "CHANGED"


def _missing_owner_state(row: SessionTemplate) -> str:
    return row.state if row.state in _ARCHIVED_STATES else "MISSING"


def _reconcile_row(
    row: SessionTemplate,
    observation: _FileObservation,
    *,
    state: str,
    lineage_parent_id: str | None = None,
    duplicate_of_template_id: str | None = None,
) -> SessionTemplate:
    """Apply one observation to an existing registry row without losing lineage."""

    if lineage_parent_id is None:
        lineage_parent_id = row.lineage_parent_id
    if duplicate_of_template_id is None:
        duplicate_of_template_id = row.duplicate_of_template_id
    return _repository.reconcile(
        row.template_id,
        relative_path=observation.relative_path,
        registered_hash=row.registered_hash,
        observed_hash=observation.observed_hash,
        filesystem_identity=observation.filesystem_identity,
        state=state,
        lineage_parent_id=lineage_parent_id,
        duplicate_of_template_id=duplicate_of_template_id,
    )


def _upsert_observation_row(
    observation: _FileObservation,
    rows_by_path: dict[str, SessionTemplate],
    *,
    state: str,
    lineage_parent_id: str | None = None,
    duplicate_of_template_id: str | None = None,
) -> SessionTemplate:
    """Create or refresh metadata for one unclaimed filesystem observation."""

    row = rows_by_path.get(observation.relative_path)
    if row is None:
        row = _repository.create(
            relative_path=observation.relative_path,
            registered_hash=observation.observed_hash or "",
            observed_hash=observation.observed_hash,
            filesystem_identity=observation.filesystem_identity,
            state=state,
            lineage_parent_id=lineage_parent_id,
            duplicate_of_template_id=duplicate_of_template_id,
        )
        rows_by_path[observation.relative_path] = row
        return row
    return _repository.reconcile(
        row.template_id,
        relative_path=observation.relative_path,
        registered_hash=observation.observed_hash or row.registered_hash,
        observed_hash=observation.observed_hash,
        filesystem_identity=observation.filesystem_identity,
        state=state,
        lineage_parent_id=lineage_parent_id,
        duplicate_of_template_id=duplicate_of_template_id,
    )


def _claim_renamed_observation(
    owner: SessionTemplate,
    observation: _FileObservation,
    rows_by_path: dict[str, SessionTemplate],
) -> SessionTemplate:
    """Rebind a confidently matched renamed file to its durable template ID."""

    displaced = rows_by_path.get(observation.relative_path)
    if displaced is not None and displaced.template_id != owner.template_id:
        _repository.delete(displaced)
    rows_by_path.pop(owner.relative_path, None)
    owner = _reconcile_row(owner, observation, state=_owner_state(owner, observation))
    rows_by_path[observation.relative_path] = owner
    return owner


def _reconcile_snapshot(observations: list[_FileObservation]) -> None:
    """Apply deterministic path, identity, hash, ambiguity, and duplicate precedence."""

    observations_by_path = {item.relative_path: item for item in observations}
    rows = _repository.list()
    rows_by_path = {row.relative_path: row for row in rows}
    owners = sorted(
        (row for row in rows if _is_registered_owner(row)),
        key=_row_order,
    )
    claimed_paths: set[str] = set()

    with transaction():
        # Registered path always wins, even when its file is invalid or changed.
        for owner in owners:
            observation = observations_by_path.get(owner.relative_path)
            if observation is None:
                continue
            _reconcile_row(owner, observation, state=_owner_state(owner, observation))
            claimed_paths.add(observation.relative_path)

        # Missing owners next use filesystem identity, then a unique hash. A
        # candidate row from an earlier scan is replaced by the preserved ID.
        for owner in owners:
            if owner.relative_path in claimed_paths:
                continue
            if owner.state == "PENDING":
                _repository.reconcile(
                    owner.template_id,
                    relative_path=owner.relative_path,
                    registered_hash=owner.registered_hash,
                    observed_hash=None,
                    filesystem_identity=owner.filesystem_identity,
                    state="PENDING",
                    lineage_parent_id=owner.lineage_parent_id,
                    duplicate_of_template_id=owner.duplicate_of_template_id,
                )
                continue
            available = [item for item in observations if item.relative_path not in claimed_paths]
            identity_matches = [
                item
                for item in available
                if owner.filesystem_identity is not None
                and item.filesystem_identity == owner.filesystem_identity
            ]
            hash_matches = [
                item
                for item in available
                if item.observed_hash is not None and item.observed_hash == owner.registered_hash
            ]
            selected = identity_matches[0] if len(identity_matches) == 1 else None
            if selected is None and not identity_matches and len(hash_matches) == 1:
                selected = hash_matches[0]
            if selected is not None:
                _claim_renamed_observation(owner, selected, rows_by_path)
                claimed_paths.add(selected.relative_path)
                continue
            if len(hash_matches) > 1:
                _repository.reconcile(
                    owner.template_id,
                    relative_path=owner.relative_path,
                    registered_hash=owner.registered_hash,
                    observed_hash=None,
                    filesystem_identity=owner.filesystem_identity,
                    state=_missing_owner_state(owner),
                )
                for candidate in hash_matches:
                    _upsert_observation_row(
                        candidate,
                        rows_by_path,
                        state="AMBIGUOUS_RENAME",
                        lineage_parent_id=owner.template_id,
                    )
                    claimed_paths.add(candidate.relative_path)
                continue
            _repository.reconcile(
                owner.template_id,
                relative_path=owner.relative_path,
                registered_hash=owner.registered_hash,
                observed_hash=None,
                filesystem_identity=owner.filesystem_identity,
                state=_missing_owner_state(owner),
            )

        current_rows = _repository.list()
        active_by_hash: dict[str, SessionTemplate] = {}
        for row in sorted(current_rows, key=_row_order):
            if row.state != "ACTIVE" or row.relative_path not in claimed_paths:
                continue
            original = active_by_hash.get(row.registered_hash)
            if original is None:
                active_by_hash[row.registered_hash] = row
                continue
            observation = observations_by_path[row.relative_path]
            _reconcile_row(
                row,
                observation,
                state="DUPLICATE",
                duplicate_of_template_id=original.template_id,
            )

        current_rows = _repository.list()
        duplicate_target_by_hash: dict[str, SessionTemplate] = {}
        target_rows = sorted(
            (
                row
                for row in current_rows
                if row.relative_path in claimed_paths
                and row.state not in _NON_OWNER_STATES
                and row.state != "INVALID"
            ),
            key=lambda row: (row.state != "ACTIVE", *_row_order(row)),
        )
        for row in target_rows:
            current_hash = row.observed_hash or row.registered_hash
            duplicate_target_by_hash.setdefault(current_hash, row)

        # Anything not claimed by a registered owner is invalid, a duplicate,
        # or a unique discovery. Process by path so scan order cannot decide IDs.
        for observation in observations:
            if observation.relative_path in claimed_paths:
                continue
            if observation.observed_hash is None:
                _upsert_observation_row(observation, rows_by_path, state="INVALID")
                continue
            duplicate_of = duplicate_target_by_hash.get(observation.observed_hash)
            if duplicate_of is not None:
                _upsert_observation_row(
                    observation,
                    rows_by_path,
                    state="DUPLICATE",
                    duplicate_of_template_id=duplicate_of.template_id,
                )
            else:
                discovered = _upsert_observation_row(
                    observation,
                    rows_by_path,
                    state="DISCOVERED",
                )
                duplicate_target_by_hash[observation.observed_hash] = discovered


def _state_warning(state: str, relative_path: str) -> str | None:
    """Return the primary operator guidance for a non-runnable state."""

    messages = {
        "PENDING": f"template creation for {relative_path!r} has not converged",
        "MISSING": f"registered template file {relative_path!r} is missing",
        "DUPLICATE": "duplicate template configuration; open the registered original",
        "AMBIGUOUS_RENAME": "several files could be the renamed registered template",
        "CHANGED": "observed configuration differs from the trusted registered revision",
        "REPLACED": "template revision was replaced by a newer accepted revision",
    }
    return messages.get(state)


def _catalog_from_snapshot(observations: list[_FileObservation]) -> builtins.list[SessionTemplateFile]:
    """Join reconciled metadata to immutable disk observations for API consumption."""

    observations_by_path = {item.relative_path: item for item in observations}
    result: list[SessionTemplateFile] = []
    for row in _repository.list():
        observation = observations_by_path.get(row.relative_path)
        warnings = builtins.list(observation.warnings) if observation is not None else []
        if observation is None and row.state in _ARCHIVED_STATES:
            warnings.append(f"registered template file {row.relative_path!r} is missing")
        if (
            observation is not None
            and row.state == "ARCHIVED"
            and row.observed_hash is not None
            and row.observed_hash != row.registered_hash
        ):
            warnings.append("archived template file differs from its registered revision")
        state_warning = _state_warning(row.state, row.relative_path)
        if state_warning is not None:
            warnings.append(state_warning)
        result.append(
            _attach_reference_warnings(
                SessionTemplateFile(
                    row,
                    observation.content if observation is not None else None,
                    warnings,
                )
            )
        )
    return sorted(result, key=lambda item: (item.relative_path.lower(), item.template_id))


def _observe(path: Path) -> SessionTemplateFile:
    safe_path = _direct_file(path)
    if safe_path is None:
        raise SessionTemplateNotFound(path.name)
    relative_path = safe_path.name
    return next(
        row for row in catalog() if row.relative_path == relative_path
    )


def catalog() -> builtins.list[SessionTemplateFile]:
    """Reconcile a stable folder snapshot and return every registry state."""

    observations = _snapshot_library()
    _reconcile_snapshot(observations)
    return _catalog_from_snapshot(observations)


def list() -> builtins.list[SessionTemplateFile]:  # noqa: A001
    return catalog()


def get_by_name(name: str) -> SessionTemplateFile | None:
    """Prefer the active revision when several historical rows share a display name."""

    normalized = _normalize_name(name)
    matches = [template for template in catalog() if template.name == normalized]
    return (
        min(
            matches,
            key=lambda item: (
                item.state != "ACTIVE",
                item.created_at.isoformat() if item.created_at is not None else "",
                item.template_id,
            ),
        )
        if matches
        else None
    )


def get_by_reference(reference: str) -> SessionTemplateFile | None:
    relative_path = _relative_reference(reference)
    if relative_path is None:
        return None
    return next((row for row in catalog() if row.relative_path == relative_path), None)


def get_by_id(template_id: str) -> SessionTemplateFile | None:
    return next((row for row in catalog() if row.template_id == template_id), None)


def resolve_device_template_reference(flow: Mapping[str, Any]):
    """Resolve a device-template path/hash reference and return warnings."""

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


def _existing_for_path(path: Path) -> SessionTemplateFile | None:
    """Return the observed template at a path or reject an unsafe collision."""

    if not path.exists():
        return None
    safe_path = _direct_file(path)
    if safe_path is None:
        raise SessionTemplateNameExists(path.stem)
    return _observe(safe_path)


def _create_pending(path: Path, registered_hash: str) -> SessionTemplate:
    """Record intent before crossing the non-atomic database/file boundary."""

    with transaction():
        return _repository.create(
            relative_path=path.name,
            registered_hash=registered_hash,
            state="PENDING",
        )


def create(name: str, raw_content: Mapping[str, Any]) -> SessionTemplateFile:
    """Create one file-backed template and converge its pending metadata to active."""

    normalized_name = _normalize_name(name)
    canonical = _canonicalize(raw_content)
    content_hash = _content_hash(canonical)
    path = _template_path(normalized_name)
    existing = _existing_for_path(path)
    if existing is not None:
        if existing.content_hash == content_hash and existing.content is not None:
            return existing
        raise SessionTemplateNameExists(normalized_name)

    _create_pending(path, content_hash)
    _write_atomic(path, _to_toml(canonical))
    return _observe(path)


def update(name: str, raw_content: Mapping[str, Any]) -> SessionTemplateFile:
    """Replace API-managed content through the pending crash-recovery protocol."""

    existing = get_by_reference(name) or get_by_name(name)
    if existing is None:
        raise SessionTemplateNotFound(name)
    canonical = _canonicalize(raw_content)
    content_hash = _content_hash(canonical)
    if existing.content_hash == content_hash and existing.content is not None:
        return existing

    with transaction():
        row = _repository.get_by_id(existing.template_id)
        if row is None:
            raise SessionTemplateNotFound(name)
        row.registered_hash = content_hash
        row.state = "PENDING"
    path = _library_dir() / existing.relative_path
    _write_atomic(path, _to_toml(canonical))
    return _observe(path)


def register(template_id: str) -> SessionTemplateFile:
    """Promote one unique discovered file to a trusted active template."""

    template = get_by_id(template_id)
    if template is None:
        raise SessionTemplateNotFound(template_id)
    if template.state == "ACTIVE":
        return template
    if template.state != "DISCOVERED" or template.observed_hash is None:
        raise ValueError(f"template {template_id!r} cannot be registered from state {template.state}")
    with transaction():
        row = _repository.get_by_id(template_id)
        if row is None:
            raise SessionTemplateNotFound(template_id)
        _repository.reconcile(
            template_id,
            relative_path=row.relative_path,
            registered_hash=template.observed_hash,
            observed_hash=template.observed_hash,
            filesystem_identity=row.filesystem_identity,
            state="ACTIVE",
        )
    registered = get_by_id(template_id)
    if registered is None:
        raise SessionTemplateNotFound(template_id)
    return registered


def archive(template_id: str) -> SessionTemplateFile:
    """Retire an active or changed template without modifying its TOML file."""

    template = get_by_id(template_id)
    if template is None:
        raise SessionTemplateNotFound(template_id)
    if template.state in _ARCHIVED_STATES:
        return template
    if template.state not in {"ACTIVE", "CHANGED"}:
        raise ValueError(f"template {template_id!r} cannot be archived from state {template.state}")
    with transaction():
        _repository.update_state(template_id, "ARCHIVED")
    archived = get_by_id(template_id)
    if archived is None:
        raise SessionTemplateNotFound(template_id)
    return archived


def _replaced_relative_path(row: SessionTemplate) -> str:
    return f".revisions/{row.template_id}/{Path(row.relative_path).name}"


def accept_change(template_id: str) -> SessionTemplateFile:
    """Replace a changed revision with a new active ID while retaining history."""

    template = get_by_id(template_id)
    if template is None:
        raise SessionTemplateNotFound(template_id)
    if template.state != "CHANGED" or template.observed_hash is None:
        raise ValueError(f"template {template_id!r} cannot accept change from state {template.state}")
    original_path = template.relative_path
    with transaction():
        row = _repository.get_by_id(template_id)
        if row is None:
            raise SessionTemplateNotFound(template_id)
        _repository.reconcile(
            template_id,
            relative_path=_replaced_relative_path(row),
            registered_hash=row.registered_hash,
            observed_hash=row.observed_hash,
            filesystem_identity=row.filesystem_identity,
            state="REPLACED",
        )
        accepted = _repository.create(
            relative_path=original_path,
            registered_hash=template.observed_hash,
            observed_hash=template.observed_hash,
            filesystem_identity=template.filesystem_identity,
            state="ACTIVE",
            lineage_parent_id=template_id,
        )
        accepted_id = accepted.template_id
    result = get_by_id(accepted_id)
    if result is None:
        raise SessionTemplateNotFound(accepted_id)
    return result


def resolve_ambiguous_rename(template_id: str, selected_relative_path: str) -> SessionTemplateFile:
    """Preserve the old ID on the selected rename and mark other candidates duplicate."""

    catalog_rows = catalog()
    owner = next((row for row in catalog_rows if row.template_id == template_id), None)
    if owner is None:
        raise SessionTemplateNotFound(template_id)
    selected_path = _relative_reference(selected_relative_path)
    selected = next(
        (
            row
            for row in catalog_rows
            if row.relative_path == selected_path
            and row.state == "AMBIGUOUS_RENAME"
            and row.lineage_parent_id == template_id
        ),
        None,
    )
    if (
        owner.state not in {"MISSING", *_ARCHIVED_STATES}
        or selected is None
        or selected.observed_hash is None
    ):
        raise ValueError("selected file is not an ambiguous rename candidate for this template")
    selected_id = selected.template_id
    selected_hash = selected.observed_hash
    selected_identity = selected.filesystem_identity
    with transaction():
        candidate = _repository.get_by_id(selected_id)
        source = _repository.get_by_id(template_id)
        if candidate is None or source is None:
            raise SessionTemplateNotFound(selected_relative_path)
        _repository.delete(candidate)
        _repository.reconcile(
            template_id,
            relative_path=selected.relative_path,
            registered_hash=source.registered_hash,
            observed_hash=selected_hash,
            filesystem_identity=selected_identity,
            state="ARCHIVED" if owner.state in _ARCHIVED_STATES else "ACTIVE",
        )
        for other in _repository.list():
            if other.state != "AMBIGUOUS_RENAME" or other.lineage_parent_id != template_id:
                continue
            _repository.reconcile(
                other.template_id,
                relative_path=other.relative_path,
                registered_hash=other.registered_hash,
                observed_hash=other.observed_hash,
                filesystem_identity=other.filesystem_identity,
                state="DUPLICATE",
                duplicate_of_template_id=template_id,
            )
    result = get_by_id(template_id)
    if result is None:
        raise SessionTemplateNotFound(template_id)
    return result


def _relative_reference(reference: str) -> str | None:
    """Normalize a client reference while rejecting traversal and nested paths."""

    if not isinstance(reference, str):
        return None
    relative = reference.strip().replace("\\", "/")
    if relative.startswith("session-templates/"):
        relative = relative[len("session-templates/") :]
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None
    if len(Path(relative).parts) != 1:
        return None
    if Path(relative).suffix.lower() != ".toml":
        relative = f"{relative}.toml"
    return relative


def _library_file_for_reference(reference: str) -> Path | None:
    relative = _relative_reference(reference)
    if relative is None:
        return None
    candidate = _library_dir() / relative
    return _direct_file(candidate)


def resolve_for_plan(reference: str) -> "_PlanTemplate":
    """Return runnable content only when the reconciled template is active."""

    if not isinstance(reference, str) or not reference.strip():
        raise SessionTemplateNotFound(reference if isinstance(reference, str) else "")
    template = get_by_reference(reference) if _looks_like_library_reference(reference) else get_by_name(reference)
    if template is None or template.state != "ACTIVE" or template.content is None:
        raise SessionTemplateNotFound(reference)
    return _PlanTemplate(name=template.name, content=template.content, reference=template.reference)


def _looks_like_library_reference(reference: str) -> bool:
    normalized = reference.replace("\\", "/")
    return normalized.startswith("session-templates/") or Path(normalized).suffix.lower() == ".toml"


class _PlanTemplate:
    __slots__ = ("name", "content", "reference")

    def __init__(self, *, name: str, content: Mapping[str, Any], reference: str):
        self.name = name
        self.content = dict(content)
        self.reference = reference


def delete(name: str) -> None:
    """Delete an explicitly named template file and its corresponding metadata."""

    template = get_by_reference(name) or get_by_name(name)
    if template is None:
        raise SessionTemplateNotFound(name)
    path = _library_dir() / template.relative_path
    path.unlink()
    with transaction():
        row = _repository.get_by_id(template.template_id)
        if row is not None:
            _repository.delete(row)


def import_config(source: Mapping[str, Any], *, name: str | None = None) -> SessionTemplateFile:
    """Import user-authored configuration through the normal safe create workflow."""

    if not isinstance(source, Mapping):
        raise ValueError("session template source must be a mapping")
    data = dict(source)
    template_name = name if name is not None else data.pop("name", None)
    if template_name is None:
        raise ValueError("session template name is required")
    data.pop("name", None)
    return create(template_name, data)


def create_from_session(
    session: Session,
    name: str,
    *,
    include_hardware_id: bool = False,
) -> SessionTemplateFile:
    """Export a session snapshot as a reusable file-backed template."""

    from app.services.session_config import _template_for_export
    from app.services import device_configs

    device_flows: list[dict[str, Any]] = []
    for index, entry in enumerate(session.device_flows or [], start=1):
        template = _template_for_export(session, entry, index)
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
