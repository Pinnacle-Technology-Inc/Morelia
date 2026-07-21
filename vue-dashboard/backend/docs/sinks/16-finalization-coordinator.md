# Packet 16 — Coordinate durable output finalization

Status: ready  
Size: M  
Depends on: 10, 11

## Purpose

Create a control-plane-owned, durable, fenced job that finalizes completed multi-component outputs without retaining hardware ownership.

## Prior state

No finalizer exists. Merging in the runtime worker would block recovery/stop and make crash handling ambiguous.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “File sinks”, “Process and ownership boundary map”, gap SINK-26, and release-critical scenario 4.
- `app/models/output_file.py` — completion/finalization/fencing fields from packet 10.
- `app/output/managed_file.py` — component metadata and immutable-close rules.
- `app/services/sessions.py` — stop/completion service boundary.
- `app/config.py` — retention and worker settings.
- `app/watchdog_process/__main__.py` — subprocess entrypoint conventions and environment isolation.
- `tests/test_session_operations.py` — service lifecycle patterns.

## Exact edit set

- `app/repositories/output_files.py`
- `app/services/output_finalization.py`
- `app/finalizer_process/__main__.py`
- `app/config.py`
- `tests/test_output_finalization.py`

## Scope boundaries

Do not implement EDF/PVFS format merge logic, delete component files, wait synchronously in the stop request, or acquire hardware.

## Contract / invariant

Only a completed acquisition can be finalized. A durable lease/fence permits one active attempt; the worker writes a temporary artifact, verifies it, atomically publishes it, and records success before cleanup is eligible.

## Acceptance criteria

1. Job claim, heartbeat, retry, stale-lease recovery, and terminal state transitions are idempotent and fenced; the dedicated process receives no hardware/runtime-worker handles.
2. Failed/cancelled finalization preserves every component and any diagnostic temporary path without publishing a false final artifact.
3. Component retention is configurable and cleanup cannot run until a verified publish is durable.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_output_finalization.py
```

## Failure handling

Release the lease only through a fenced state transition, retain components, and retry with bounded backoff; an obsolete worker must be unable to publish.

## Handoff note

Publish the merger callable contract, verification result schema, and cleanup eligibility rule for packets 17, 18, and 29.

## Implemented fence boundary

Format mergers registered in production now stop after writing and verifying a temporary artifact. The coordinator refreshes the lease while long format I/O runs, rechecks the active `(finalization_id, fence_token)`, and performs the atomic rename while holding the database write fence. A stale worker is rejected before its filesystem callback can touch the published target.
