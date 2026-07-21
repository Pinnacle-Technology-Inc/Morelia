# Packet 09A — Report sink readiness in doctor output

Status: ready  
Size: S  
Depends on: 01, 08

## Purpose

Make the operator doctor command report dependency and platform readiness independently for every supported sink.

## Prior state

Doctor output covers general backend/runtime readiness but cannot explain which optional sink is installable, missing, unsupported, or intentionally unselected.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — gaps SINK-13/SINK-16 and the file-by-file deployment/doctor inventory.
- `app/cli/doctor.py` — current diagnostic checks and rendering.
- `app/services/registry.py` — supported sink types/categories.
- `pyproject.toml` — optional dependency groups from packet 08.
- `tests/test_pinnacle_doctor.py` — doctor command contract.

## Exact edit set

- `app/cli/doctor.py`
- `tests/test_pinnacle_doctor.py`

## Scope boundaries

Do not open output files, resolve secret values, contact configured production destinations, install packages, or fail general CSV readiness because an optional unselected sink is unavailable.

## Contract / invariant

Doctor reports each sink separately as ready, dependency-missing, configuration-required, platform-unsupported, or not checked. It prints credential variable names at most, never values.

## Acceptance criteria

1. Output includes all six registered types with actionable extra/package/platform guidance.
2. Missing one optional dependency affects only that sink's diagnostic and command exit policy is explicit.
3. Diagnostics are deterministic under mocked imports/environment and redact credential values.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_pinnacle_doctor.py
```

## Failure handling

If a dependency probe has side effects or hangs, replace it with bounded metadata/import discovery and report “not checked”; never instantiate the sink in doctor.

## Handoff note

Provide the exact readiness labels and remediation text to packet 31's support matrix/runbook.
