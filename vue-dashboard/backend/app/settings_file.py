"""Load non-secret operator settings from a portable TOML file.

``.env`` stays for secrets and machine-local paths. ``settings.toml`` is the
shareable knob file (timing, thresholds, limits). Precedence when both are
used (see ``app/__init__.py``):

    real environment > ``.env`` > ``settings.toml`` > code defaults

TOML layout: use the same names as ``Config`` / env vars. Optional one-level
tables become a prefix:

    SOURCE_STATUS_STALE_AFTER_SECONDS = 3.0

    [WATCHDOG]
    REPORT_INTERVAL_SECONDS = 3.0   # -> WATCHDOG_REPORT_INTERVAL_SECONDS
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS_FILENAME = "settings.toml"
SETTINGS_FILE_ENV = "PINNACLE_SETTINGS_FILE"


def default_settings_path(base_dir: Path | None = None) -> Path:
    """Resolve the settings file path.

    ``PINNACLE_SETTINGS_FILE`` (absolute or relative) wins when set; otherwise
    ``settings.toml`` next to ``.env`` (the backend package parent).
    """
    override = os.environ.get(SETTINGS_FILE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    root = base_dir if base_dir is not None else Path(__file__).resolve().parent.parent
    return root / DEFAULT_SETTINGS_FILENAME


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_stringify(item) for item in value)
    return str(value)


def flatten_settings(data: Mapping[str, Any]) -> dict[str, str]:
    """Flatten a TOML table into ``ENV_NAME -> string`` pairs."""
    out: dict[str, str] = {}
    for key, value in data.items():
        prefix = str(key).upper()
        if isinstance(value, Mapping):
            for subkey, subval in value.items():
                if isinstance(subval, Mapping):
                    raise ValueError(
                        f"settings.toml tables may only be one level deep "
                        f"({prefix}.{subkey} is nested further)"
                    )
                out[f"{prefix}_{str(subkey).upper()}"] = _stringify(subval)
        else:
            out[prefix] = _stringify(value)
    return out


def load_settings_file(
    path: Path | str | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
    override: bool = False,
) -> list[str]:
    """Load ``settings.toml`` into ``environ`` (default: ``os.environ``).

    Missing file is a no-op. Returns the list of keys that were written.
    When ``override`` is False (default), existing environ keys are left alone
    so real env and ``.env`` stay higher priority.
    """
    target = environ if environ is not None else os.environ
    settings_path = Path(path) if path is not None else default_settings_path()
    if not settings_path.is_file():
        return []

    try:
        raw = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid settings file {settings_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"settings file root must be a table: {settings_path}")

    applied: list[str] = []
    for key, value in flatten_settings(raw).items():
        if not override and key in target:
            continue
        target[key] = value
        applied.append(key)
    return applied
