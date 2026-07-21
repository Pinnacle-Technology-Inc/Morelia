# Packet 10 — Persist output lifecycle state

Status: ready  
Size: M  
Depends on: 00

## Purpose

Extend persistence so one logical sink output can own multiple physical components and explicit delivery/finalization state.

## Prior state

`OutputFile` represents one path with open/closed status. Recovery gaps store free-form segment strings, and the schema lacks acquisition, predecessor, completeness, merge, and service-delivery lifecycle fields.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Output metadata and recovery boundaries” and gaps SINK-12/SINK-20/SINK-24/SINK-26.
- `app/models/output_file.py` — existing output row.
- `app/models/recovery_gap.py` — existing boundary row.
- `migrations/versions/0001_baseline_schema.py` — migration conventions/current schema.
- `app/database.py` — model registration/import behavior.
- `tests/test_migrations.py` — migration assertions.
- `tests/test_recovery_boundaries.py` — boundary persistence expectations.

## Exact edit set

- `app/models/output_file.py`
- `app/models/recovery_gap.py`
- `migrations/versions/0002_sink_output_lifecycle.py`
- `tests/test_migrations.py`
- `tests/test_recovery_boundaries.py`

## Scope boundaries

Do not implement allocation, merging, service replay, or stop orchestration. Preserve existing CSV rows through migration.

## Contract / invariant

Persistence distinguishes logical acquisition output from physical component, includes `session_id` and acquisition identity, links components by stable IDs, and represents open/complete/finalizing/finalized/degraded/loss states without overloading source health.

## Acceptance criteria

1. Upgrade and downgrade paths preserve existing output and recovery-gap data with deterministic defaults.
2. The schema can represent a monotonic component chain, predecessor, completion cause, final artifact, delivery state, byte/sample loss counters, and finalizer fencing metadata.
3. Database constraints prevent duplicate component ordinals/paths within a logical sink output and invalid self-links.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_migrations.py tests/test_recovery_boundaries.py
```

## Failure handling

If a legacy row cannot be mapped, abort the migration transaction with the row identity; never drop or infer away historical output data.

## Handoff note

Publish the model field/state vocabulary for allocator, finalizer, outbox, ingest, and status packets.
