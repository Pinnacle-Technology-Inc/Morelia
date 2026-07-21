# Packet 29 — Enforce acquisition completion boundaries

Status: ready  
Size: M  
Depends on: 16, 17, 18, 19, 21, 26

## Purpose

Make user stop complete the current acquisition, enqueue any needed finalization, and allow an immediate later start on the same hardware to create wholly new output identities.

## Prior state

Stop/close and source-error recovery are not modeled distinctly enough to prevent accidental continuation into a completed file or to decouple merge work from hardware reuse.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — gaps SINK-24/SINK-26 and release-critical scenario 4.
- `app/services/sessions.py` — start/stop and session lifecycle.
- `app/control/supervisor.py` — runtime stop/start ownership.
- `app/services/output_finalization.py` — durable job coordination.
- `app/models/output_file.py` — acquisition/component/finalization states.
- `tests/test_session_operations.py` — start/stop behavior.
- `tests/test_runtime_host_supervision.py` — process ownership/restart tests.

## Exact edit set

- `app/services/sessions.py`
- `app/control/supervisor.py`
- `app/services/output_finalization.py`
- `tests/test_session_operations.py`
- `tests/test_runtime_host_supervision.py`

## Scope boundaries

Do not wait for merge completion in the stop request, reuse completed acquisition/output/component IDs, or make finalizers hold hardware/worker leases. Do not discard buffered service records without recording their terminal state.

## Contract / invariant

User stop is a completion boundary. Error recovery may continue the same acquisition; a later explicit start always creates a new acquisition and new file base names/outbox keys, even while prior finalization runs.

## Acceptance criteria

1. Stop closes all active components/clients, records completion cause `user_stop`, schedules eligible EDF/PVFS finalization, and returns without waiting for merge.
2. Immediate restart on the same hardware succeeds with distinct acquisition/output/component/outbox identities and cannot append to prior files.
3. A stale prior runtime/finalizer cannot mutate the new acquisition because leases, reports, acknowledgements, and publishes are fenced by acquisition identity.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_session_operations.py tests/test_runtime_host_supervision.py tests/test_output_finalization.py
```

## Failure handling

If close/finalizer scheduling partially fails, persist a retryable completion state, release hardware safely, and report affected sinks; never reopen the completed acquisition on restart.

## Handoff note

Provide the stop→close→enqueue-finalize→restart event timeline and identity evidence to packet 30.
