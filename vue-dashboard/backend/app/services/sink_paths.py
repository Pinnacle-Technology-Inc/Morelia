"""Sink-location path resolution, shared by create-time and start-time validation.

Split out of manifests.py so session_config.py (create-time) can validate a
sink_location the same way manifests.py (start-time) does, without the two
modules importing each other.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from flask import current_app

_MAX_DEDUP_ATTEMPTS = 500


def output_root() -> Path:
    """Base directory sink_location paths resolve against.

    Configured via ``OUTPUT_DIR`` (app/config.py). A relative value is
    resolved under the Flask instance directory, matching flask-sqlalchemy's
    convention for relative SQLite paths.
    """
    configured = Path(str(current_app.config.get("OUTPUT_DIR", "output")))
    if configured.is_absolute():
        return configured
    return Path(current_app.instance_path) / configured


def is_absolute_location(location: str) -> bool:
    """True for a path that's already fully specified, POSIX or Windows style.

    Session configs are authored on whatever OS the operator uses (test
    fixtures mix "/data/out.csv" and "C:/data/out.csv"), but the runtime host
    that ultimately opens the file runs on a specific OS. Path(location) alone
    is not enough: PureWindowsPath("/data/out.csv").is_absolute() is False (no
    drive letter), so on Windows a Unix-style absolute path would otherwise be
    (wrongly) treated as relative and re-joined under the output root.
    """
    return PurePosixPath(location).is_absolute() or PureWindowsPath(location).is_absolute()


def resolve_sink_location(location: str) -> str:
    """Join a relative sink_location under the output root; pass absolute paths through.

    Absolute paths are returned byte-for-byte, not round-tripped through
    Path() — normalizing "/data/out.csv" via the native (Windows) Path class
    would rewrite its separators and silently change the stored value.
    """
    if is_absolute_location(location):
        return location
    return str(output_root() / Path(location))


def path_is_claimed(location: str) -> bool:
    """True if ``location`` cannot be used for a brand-new managed output file.

    Filesystem existence is the only thing that counts: a leftover
    OutputFile row from an earlier run (app/models/output_file.py) does NOT
    claim a path once its physical file is gone — managed_file.create()
    self-heals that case by deleting the stale row (see its
    _reclaim_stale_row), so the exact same filename becomes reusable the
    moment the operator deletes the old file. Mirroring that same rule here
    means this check and create()'s actual behavior never disagree.
    """
    return Path(location).exists()


def next_available_path(path: Path, *, session_id: int | None = None) -> Path:
    """Return a path that doesn't collide with an existing file, based on ``path``.

    With a ``session_id`` (a DB primary key, unique for the app's lifetime):
    tries ``<stem>-<session_id>-<n><suffix>`` — name.csv -> name-14-1.csv ->
    name-14-2.csv -> ... The session_id makes the name traceable (which
    session made this file, at a glance, no DB lookup needed) and rules out
    ever colliding with a DIFFERENT session's retries. ``n`` still climbs
    because ONE session can have several device flows that start from the
    same stem (e.g. two flows both explicitly set "test.csv") — it
    disambiguates those siblings, not different sessions.

    Without a session_id (create-time validation, before the session has an
    id) falls back to a bare numeric suffix: name.csv -> name-2.csv -> ...

    Bounded so a directory that can never produce a free name (e.g.
    persistently unwritable) fails loud instead of looping forever.
    """
    if not path_is_claimed(str(path)):
        return path

    stem, suffix, parent = path.stem, path.suffix, path.parent
    if session_id is not None:
        for n in range(1, _MAX_DEDUP_ATTEMPTS + 1):
            candidate = parent / f"{stem}-{session_id}-{n}{suffix}"
            if not path_is_claimed(str(candidate)):
                return candidate
    else:
        for n in range(2, _MAX_DEDUP_ATTEMPTS + 2):
            candidate = parent / f"{stem}-{n}{suffix}"
            if not path_is_claimed(str(candidate)):
                return candidate
    raise RuntimeError(
        f"could not find a free filename near {path} after {_MAX_DEDUP_ATTEMPTS} attempts"
    )
