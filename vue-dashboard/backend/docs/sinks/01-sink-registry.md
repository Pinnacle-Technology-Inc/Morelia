# Packet 01 — Define the complete sink registry

Status: ready  
Size: M  
Depends on: 00

## Purpose

Make CSV, EDF, Influx, Plot, PVFS, and Quest first-class validated sink types with stable categories and per-type parameter schemas.

## Prior state

The backend registry and enum only model CSV comprehensively. Validation cannot distinguish file, service, and browser sinks or safely describe their different parameters.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — sections “Sink categories”, “Per-type parameter schemas”, and gaps SINK-01/SINK-17.
- `app/domain/enums.py` — `SinkType`.
- `app/domain/errors.py` — domain validation errors.
- `app/services/registry.py` — `ParamSchema`, `SinkSpec`, and `lookup_sink`.
- `tests/test_registry.py` — current registry contract tests.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/pvfs_sink.py` — PVFS preference keys passed to the underlying writer.
- `C:/Users/ahoang/vue-dashboard/backend/venv/Lib/site-packages/pvfs_tools/Core/pvfs_data_file.py` — `set_device_preferences` validation surface, if installed.

## Exact edit set

- `app/domain/enums.py`
- `app/domain/errors.py`
- `app/services/registry.py`
- `tests/test_registry.py`

## Scope boundaries

Do not construct sinks, open files, resolve environment variables, contact services, or add UI behavior. If the installed PVFS library does not expose a stable enforceable preference schema, reject `device_preferences` rather than accepting arbitrary dictionaries.

## Contract / invariant

Registry metadata is declarative and secret-free. Each supported type has a stable category (`file`, `service`, or `plot`), required/optional fields, defaults, and unknown-field rejection.

## Acceptance criteria

1. `lookup_sink` recognizes exactly the six approved sink types and returns their category and validated public parameters.
2. Unknown types, missing required parameters, invalid values, and unknown parameters raise a stable domain validation error.
3. Influx configuration stores only an environment-variable reference; no schema accepts a token value.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_registry.py
```

## Failure handling

If Morelia or a third-party library needs additional parameters, record the incompatibility in the audit before broadening the public schema.

## Handoff note

Publish the final per-type schema and category names for packets 02, 05, 06, 08, and 13.
