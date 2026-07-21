# Packet 07 — Resolve configuration into manifest v2

Status: ready  
Size: M  
Depends on: 02, 06

## Purpose

Convert canonical session configuration into reproducible manifest v2 descriptors, allocating locations only for file sinks.

## Prior state

The resolver allocates a single sink location and builds manifest v1. Non-file sinks are forced through file-path assumptions.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Runtime manifest v2”, “Runtime construction and dependency preflight”, and gap SINK-03.
- `app/services/manifests.py` — `_allocate_sink_location`, `resolve`, `build_for_preview`, and `_build_manifest`.
- `app/services/session_config.py` — canonical `sinks[]` output.
- `app/services/sink_paths.py` — file-sink path policy.
- `app/runtime_host/manifest.py` — v2 constructors from packet 06.
- `tests/test_runtime_manifest.py` — resolution/hash cases.
- `tests/test_pinnacle_session_preview.py` — preview behavior.

## Exact edit set

- `app/services/manifests.py`
- `tests/test_runtime_manifest.py`
- `tests/test_pinnacle_session_preview.py`

## Scope boundaries

Do not open files, resolve credentials, probe service availability, instantiate Morelia classes, or mutate persisted session configuration.

## Contract / invariant

Resolution is pure apart from explicit file-location allocation. Each manifest sink retains its source-local identity and order. Service/Plot sinks have no fabricated file path.

## Acceptance criteria

1. A canonical multi-sink source resolves to ordered v2 descriptors with stable session/source/sink identities.
2. Only CSV/EDF/PVFS receive validated globally unique file locations; file-conflict overrides are keyed by source nickname plus `sink_name`, while Influx/Quest/Plot never enter filename conflict handling.
3. Preview and persisted resolution are reproducible and differ only in explicitly documented persistence identities/allocated paths.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_runtime_manifest.py tests/test_pinnacle_session_preview.py
```

## Failure handling

On allocation collision or invalid path, fail manifest creation before the runtime starts and leave no partial output row or file.

## Handoff note

Record the resolved descriptor fixture used by preflight, factory, and integration packets.
