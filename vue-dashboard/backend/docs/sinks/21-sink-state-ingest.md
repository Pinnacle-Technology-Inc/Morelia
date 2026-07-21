# Packet 21 — Persist sink state transitions

Status: ready  
Size: M  
Depends on: 10, 20

## Purpose

Ingest per-sink reports into idempotent incidents, recovery boundaries, delivery loss, and current state while leaving source health independent.

## Prior state

Event ingest primarily maps source/watchdog recovery signals. It cannot persist a service-sink outage or file-sink continuation as a sink-specific lifecycle.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Output metadata and recovery boundaries”, gap SINK-23, and release-critical scenarios 2/3.
- `app/services/event_ingest.py` — event/report dispatch and idempotency.
- `app/services/incidents.py` — incident state transitions.
- `app/services/gaps.py` — recovery gap creation.
- `app/models/output_file.py` — current sink delivery/finalization fields.
- `app/models/recovery_gap.py` — structured component boundary fields.
- `tests/test_incident_gap_ingest.py` — ingest behavior.

## Exact edit set

- `app/services/event_ingest.py`
- `app/services/incidents.py`
- `app/services/gaps.py`
- `tests/test_incident_gap_ingest.py`

## Scope boundaries

Do not change HTTP response schemas, create sink adapters, store raw samples, or trigger source restarts solely because a sink is degraded.

## Contract / invariant

State transitions are idempotent by runtime/sink sequence identity. Source, sink, delivery, and component states remain distinct, and loss counters never decrease.

## Acceptance criteria

1. Replayed/out-of-order reports do not duplicate incidents, boundaries, components, or loss counts.
2. File continuation, service degradation/recovery, and permanent loss create sink-addressed records with acquisition identity.
3. A sink-only failure leaves source health/running state unchanged unless an independent source event says otherwise.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_incident_gap_ingest.py tests/test_event_ingest.py tests/test_incidents_and_gaps.py
```

## Failure handling

Quarantine malformed transitions with their report identity and retain last durable state; do not partially apply counters and incidents in separate transactions.

## Handoff note

Publish query-ready current-state semantics for packet 22 and lifecycle hooks for packet 29.
