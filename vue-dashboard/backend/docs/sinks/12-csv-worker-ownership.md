# Packet 12 — Enforce worker-only CSV ownership

Status: ready  
Size: M  
Depends on: 07, 11

## Purpose

Remove eager parent-process CSV side effects and guarantee that live CSV handles exist only in the runtime worker.

## Prior state

`ManagedCsvSink` performs eager construction/database work, and manifest/runtime boundaries allow parent and worker ownership to blur during start and recovery.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “CSV”, “Process and ownership boundary map”, and gap SINK-21.
- `app/output/managed_csv_sink.py` — construction, writes, close, and `get_dict`.
- `app/runtime_child/morelia.py` — `_build_stack` and `_close_sinks`.
- `app/output/managed_file.py` — worker-side allocation/reopen API.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/data_flow.py` — sink attachment and lifecycle.
- `tests/test_managed_sink_append_on_recovery.py` — CSV recovery behavior.
- `tests/test_morelia_runtime_pod8401.py` — runtime ownership fixtures.

## Exact edit set

- `app/output/managed_csv_sink.py`
- `app/runtime_child/morelia.py`
- `tests/test_managed_sink_append_on_recovery.py`
- `tests/test_sink_worker_ownership.py`

## Scope boundaries

Do not add other sink types, redesign manifests, or implement service outboxes. Parent-side code may pass descriptors but may not create a CSV writer.

## Contract / invariant

Exactly one worker owns each live CSV handle. Construction is explicit, close is idempotent, error recovery appends/reopens only when safe, and user stop completes the current file.

## Acceptance criteria

1. Building/resolving a manifest in the parent creates no file, output row, database handle, or CSV writer.
2. Worker construction opens one CSV handle, writes once per delivered sample, and closes it exactly once across normal/error paths.
3. Existing CSV append-on-error recovery and stop completion tests remain valid under the new ownership boundary.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_managed_sink_append_on_recovery.py tests/test_morelia_runtime_pod8401.py tests/test_sink_worker_ownership.py
```

## Failure handling

If worker construction fails after allocation, close the handle and mark the component failed without pretending the acquisition started successfully.

## Handoff note

Document the sink lifecycle protocol (`open/write/report/close/recover`) for packet 13.
