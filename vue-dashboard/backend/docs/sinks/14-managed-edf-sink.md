# Packet 14 — Add the managed EDF sink

Status: ready  
Size: S  
Depends on: 11, 13

## Purpose

Write EDF through the managed output lifecycle and recover from runtime errors with linked continuation components.

## Prior state

The raw Morelia EDF sink has no database-backed component lifecycle. The isolated experiment proved reopening an existing EDF path replaces prior values, so in-place recovery is unsafe.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “EDF”, “Isolated EDF/PVFS recovery experiment”, and release-critical scenario 2.
- `app/runtime_child/sink_factory.py` — adapter registration boundary.
- `app/output/managed_file.py` — component allocation and close behavior.
- `app/models/output_file.py` — lifecycle state fields.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/edf_sink.py` — EDF field/header/write behavior.
- `tests/test_managed_sink_append_on_recovery.py` — existing managed-sink conventions.

## Exact edit set

- `app/output/managed_edf_sink.py`
- `app/runtime_child/sink_factory.py`
- `tests/test_managed_edf_sink.py`

## Scope boundaries

Do not attempt same-file reopen, merge components, run finalizer jobs, or alter source recovery. Component merge belongs to packet 17.

## Contract / invariant

EDF component files are immutable after close. Runtime-error recovery always allocates a linked next component; user stop completes the acquisition without a continuation.

## Acceptance criteria

1. Initial writes produce a readable EDF component with expected channels, rates, units, and sample values.
2. Injected write/recovery interruption closes component N and writes subsequent data only to linked component N+1 without changing N.
3. Stop marks the current component/acquisition complete and does not schedule another component.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_managed_edf_sink.py
```

## Failure handling

If the current component cannot close cleanly, retain it as a failed component, record the boundary/loss uncertainty, and allocate a new path; never reopen it destructively.

## Handoff note

Record the exact metadata needed to reconstruct a merged EDF in packet 17.
