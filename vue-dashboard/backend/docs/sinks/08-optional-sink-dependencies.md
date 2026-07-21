# Packet 08 — Declare optional sink dependencies

Status: ready  
Size: S  
Depends on: 00

## Purpose

Define reproducible dependency groups for EDF, PVFS, Influx, and Quest without making unselected sinks break the base backend.

## Prior state

`pyproject.toml` and `requirements.lock` do not declare the third-party libraries imported by Morelia sink implementations, so availability depends on an unmanaged environment.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Runtime construction and dependency preflight” and gap SINK-13.
- `pyproject.toml` — project dependencies and existing optional groups.
- `requirements.lock` — resolved environment inputs.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/edf_sink.py` — EDF imports.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/pvfs_sink.py` — PVFS imports.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/influx_sink.py` — Influx imports.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/quest_sink.py` — Quest imports.
- `tests/test_package_imports.py` — base/import smoke coverage.

## Exact edit set

- `pyproject.toml`
- `requirements.lock`
- `tests/test_package_imports.py`

## Scope boundaries

Do not import optional sink libraries at backend module import time, install GUI Plot dependencies, or change runtime construction. Plot's browser implementation must not require Morelia's desktop plotting stack.

## Contract / invariant

The base install remains usable for CSV-only work. Each optional group pins the library set needed by its sink and can be installed reproducibly.

## Acceptance criteria

1. Explicit extras exist for EDF, PVFS, Influx, and Quest, plus an aggregate all-sinks extra.
2. Importing the backend in a base environment does not import or require any optional sink library.
3. The lock representation and project metadata agree on supported versions.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_package_imports.py
.\venv\Scripts\python.exe -m pip check
```

## Failure handling

If an upstream package cannot be locked for a supported platform, mark that sink unavailable with a documented platform constraint; do not silently leave it unmanaged.

## Handoff note

Record import module names and installation hints for packet 09 and the rollout support matrix.
