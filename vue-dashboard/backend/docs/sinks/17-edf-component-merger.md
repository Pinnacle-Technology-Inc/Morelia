# Packet 17 — Merge EDF continuation components

Status: ready  
Size: S  
Depends on: 14, 16

## Purpose

Produce one verified EDF artifact from a completed ordered component chain without modifying its source components.

## Prior state

Synthetic format-aware read/rewrite succeeded, but no production merger validates EDF metadata/ordering or participates in the finalizer protocol.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “EDF”, the recovery experiment, and finalization policy.
- `app/services/output_finalization.py` — merger callable and publish protocol from packet 16.
- `app/output/managed_edf_sink.py` — component metadata/header behavior.
- `app/models/output_file.py` — ordered chain/final artifact fields.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/edf_sink.py` — channel/header conventions.
- `tests/test_managed_edf_sink.py` — component fixtures.

## Exact edit set

- `app/output/edf_merger.py`
- `app/services/output_finalization.py`
- `tests/test_edf_component_merger.py`

## Scope boundaries

Do not delete components, merge an open acquisition, interpolate gaps, or conceal incompatible channel schemas.

## Contract / invariant

Merge reads components in ordinal order, preserves samples and channel metadata, writes only a fresh temporary path, and returns verification evidence before the coordinator publishes.

## Acceptance criteria

1. Two or more compatible EDF components merge to one readable file with exact ordered samples and expected metadata.
2. Missing, duplicate, reordered, corrupt, or schema-incompatible components fail without modifying components or publishing a target.
3. Repeating the finalizer after success is idempotent and does not duplicate samples.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_edf_component_merger.py tests/test_managed_edf_sink.py
```

## Failure handling

Mark finalization retryable or terminal according to error classification, retain all inputs, and preserve verification diagnostics.

## Handoff note

Record merge performance and metadata limitations for the support matrix and release gate.
