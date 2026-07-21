# Packet 18 — Merge PVFS continuation components

Status: ready  
Size: S  
Depends on: 15, 16

## Purpose

Produce one verified PVFS artifact from a completed ordered component chain without modifying its source components.

## Prior state

Synthetic format-aware read/rewrite succeeded, but no production merger validates PVFS channels/preferences/ordering or participates in the finalizer protocol.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “PVFS”, the recovery experiment, and finalization policy.
- `app/services/output_finalization.py` — merger callable and publish protocol from packet 16.
- `app/output/managed_pvfs_sink.py` — component channel/preference behavior.
- `app/models/output_file.py` — ordered chain/final artifact fields.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/pvfs_sink.py` — channel/preferences conventions.
- `tests/test_managed_pvfs_sink.py` — component fixtures.

## Exact edit set

- `app/output/pvfs_merger.py`
- `app/services/output_finalization.py`
- `tests/test_pvfs_component_merger.py`

## Scope boundaries

Do not reopen components for writing, delete components, merge an open acquisition, interpolate gaps, or accept incompatible device preferences.

## Contract / invariant

Merge reads components in ordinal order, preserves values and compatible PVFS metadata, writes only a fresh temporary path, and verifies the complete readback before publish.

## Acceptance criteria

1. Two or more compatible PVFS components merge to one readable file containing exact ordered, non-overwritten values and expected metadata.
2. Missing, duplicate, reordered, corrupt, or incompatible components fail without modifying inputs or publishing a target.
3. Repeating finalization after success is idempotent and does not duplicate values.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_pvfs_component_merger.py tests/test_managed_pvfs_sink.py
```

## Failure handling

Retain components and diagnostics, remove only an uncommitted temporary artifact when safe, and leave the job retryable unless incompatibility is terminal.

## Handoff note

Record merge performance and supported preference/channel constraints for release documentation.
