# Packet 22 — Expose sink status independently

Status: ready  
Size: S  
Depends on: 04, 21

## Purpose

Return per-sink runtime, buffering, loss, component, and finalization state alongside—but separate from—source status.

## Prior state

Session status responses focus on source/watchdog health and cannot explain that acquisition is running while one sink is degraded or finalizing.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “API/session services”, “Five release-critical scenarios”, and gaps SINK-08/SINK-23.
- `app/services/session_status.py` — current status aggregation.
- `app/api/schemas.py` — status response schemas.
- `app/api/sessions.py` — status endpoint boundary.
- `tests/test_session_status_api.py` — status API contract.

## Exact edit set

- `app/services/session_status.py`
- `app/api/schemas.py`
- `tests/test_session_status_api.py`

## Scope boundaries

Do not add Plot samples, raw outbox records, credential references/values, or mutate lifecycle state from a read endpoint.

## Contract / invariant

Status keys sinks by stable `sink_name`/ID and reports last update, health, delivery/buffer/loss, active component, and finalization separately. Source status is not derived from the worst sink.

## Acceptance criteria

1. A running source can simultaneously report healthy, degraded, buffering, failed, or finalizing sibling sinks.
2. Loss is explicit and monotonic; stale state is distinguishable from healthy state.
3. Responses contain bounded redacted diagnostics and no raw samples, tokens, or resolved credential material.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_session_status_api.py
```

## Failure handling

If current sink state cannot be loaded, return a sink-addressed unknown/stale status and preserve the rest of the session response.

## Handoff note

Freeze the response fixture for CLI rendering, Vue Plot context, and release tests.
