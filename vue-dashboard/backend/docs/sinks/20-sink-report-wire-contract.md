# Packet 20 — Define the per-sink report wire contract

Status: ready  
Size: M  
Depends on: 06

## Purpose

Carry bounded, serializable per-sink health and delivery state from runtime child through watchdog without conflating it with source health.

## Prior state

`DeviceReport`/`RuntimeReport` center on device/source state. Sink failures may be printed or inferred and cannot be attributed consistently across process boundaries.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Process and ownership boundary map”, gaps SINK-08/SINK-19/SINK-23, and the coverage matrix.
- `app/runtime_child/driver.py` — `DeviceReport`, `RuntimeReport`, and `RuntimeControlDriver`.
- `app/runtime_child/morelia.py` — `_emit_report` and `_watchdog_diagnostics`.
- `app/watchdog_process/process.py` — `to_envelope` and `_on_report`.
- `app/contracts/watchdog_process_protocol.py` — process telemetry envelope.
- `tests/test_runtime_driver.py` — report serialization.
- `tests/test_watchdog_process_entrypoint.py` — child/watchdog wiring fixtures.

## Exact edit set

- `app/runtime_child/driver.py`
- `app/watchdog_process/process.py`
- `tests/test_runtime_driver.py`
- `tests/test_watchdog_process_entrypoint.py`

## Scope boundaries

Do not persist incidents/gaps, alter source recovery decisions, include raw samples, or expose credential/config values.

## Contract / invariant

Reports key sinks by stable source/sink identity and separate health, delivery, buffering, loss, component, and finalization fields. Payload size is bounded and secrets/raw data are forbidden.

## Acceptance criteria

1. Reports serialize/deserialize multiple sinks without changing source health and preserve monotonic per-sink sequence/state timestamps.
2. Degraded, buffering, recovered, permanent-loss, and failed states carry bounded redacted diagnostics and counters.
3. Old children/watchdogs either translate the documented prior shape or reject it explicitly; no partial ambiguous decode is accepted.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_runtime_driver.py tests/test_watchdog_process_entrypoint.py
```

## Failure handling

Reject malformed/oversized reports, retain last known state with a stale marker, and raise protocol diagnostics without crashing unrelated source supervision.

## Handoff note

Provide canonical report fixtures to state ingest, status API, Morelia callback, and runtime integration packets.
