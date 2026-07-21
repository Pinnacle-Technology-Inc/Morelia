# Packet 11 — Allocate linked output components

Status: ready  
Size: M  
Depends on: 10

## Purpose

Provide race-safe component allocation and structured boundary recording for file-sink continuation after runtime errors.

## Prior state

Managed file reopening targets one path, while boundary recording accepts loose strings and does not claim a unique next ordinal atomically.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “File sinks”, “Output metadata and recovery boundaries”, and gaps SINK-18/SINK-24.
- `app/output/managed_file.py` — `ManagedOutputFile.create` and `reopen`.
- `app/output/boundaries.py` — `record_boundary`.
- `app/models/output_file.py` — lifecycle/component fields from packet 10.
- `app/repositories/recovery_gaps.py` — boundary persistence interface.
- `tests/test_managed_output_file.py` — file lifecycle tests.
- `tests/test_recovery_boundaries.py` — gap/boundary tests.

## Exact edit set

- `app/output/managed_file.py`
- `app/output/boundaries.py`
- `app/repositories/recovery_gaps.py`
- `tests/test_managed_output_file.py`
- `tests/test_recovery_boundaries.py`

## Scope boundaries

Do not implement format-specific append/merge, sink construction, finalizer jobs, or stop/start orchestration.

## Contract / invariant

Component 0 owns the base requested name; continuations receive monotonically increasing suffixes and stable predecessor links. Allocation and boundary recording are idempotent under retry and cannot overwrite an existing file.

## Acceptance criteria

1. Concurrent/retried allocation yields one unique component per ordinal with deterministic names and predecessor IDs.
2. Error recovery records one structured boundary linking prior and next components with source/sink/recovery identity and timing/count metadata.
3. User-stop completion closes the current component without allocating a continuation.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_managed_output_file.py tests/test_recovery_boundaries.py
```

## Failure handling

If allocation or boundary persistence fails, close any newly opened handle, remove only an uncommitted newly created file, and leave the previous component immutable.

## Handoff note

Provide allocator and boundary APIs plus deterministic filename examples to EDF/PVFS and finalization packets.
