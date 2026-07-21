# Packet 15 — Add the managed PVFS sink

Status: ready  
Size: S  
Depends on: 11, 13

## Purpose

Write PVFS through the managed output lifecycle and recover from runtime errors with linked continuation components.

## Prior state

The raw Morelia PVFS sink lacks managed component metadata. The isolated experiment showed writable reopen can report success while overwriting earlier values, and create-on-existing erases channels.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “PVFS”, “Isolated EDF/PVFS recovery experiment”, and release-critical scenario 2.
- `app/runtime_child/sink_factory.py` — adapter registration boundary.
- `app/output/managed_file.py` — component allocation and close behavior.
- `app/models/output_file.py` — lifecycle state fields.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/pvfs_sink.py` — PVFS channel/preferences/write behavior.
- `tests/test_managed_sink_append_on_recovery.py` — existing managed-sink conventions.

## Exact edit set

- `app/output/managed_pvfs_sink.py`
- `app/runtime_child/sink_factory.py`
- `tests/test_managed_pvfs_sink.py`

## Scope boundaries

Do not reopen an existing PVFS path for continued writes, merge components, run finalizer jobs, or broaden `device_preferences` beyond packet 01's validated schema.

## Contract / invariant

PVFS component files are immutable after close. Runtime-error recovery always allocates a linked next component; user stop completes the acquisition without a continuation.

## Acceptance criteria

1. Initial writes produce a readable PVFS component with expected channel metadata and values.
2. Injected interruption preserves component N byte-for-byte and writes later values only to linked component N+1.
3. Stop marks the current component/acquisition complete and does not schedule another component.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_managed_pvfs_sink.py
```

## Failure handling

If close integrity is uncertain, retain and mark the component failed, record uncertainty/loss state, and continue only on a newly allocated path.

## Handoff note

Record channel and device-preference metadata required by the PVFS merger in packet 18.
