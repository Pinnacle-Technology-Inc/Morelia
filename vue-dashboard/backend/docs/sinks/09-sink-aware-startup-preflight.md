# Packet 09 — Preflight selected sinks at startup

Status: ready  
Size: M  
Depends on: 07, 08

## Purpose

Fail a start before hardware acquisition when a selected sink dependency, credential reference, path, or initially required service is unavailable.

## Prior state

Startup checks primarily prove the runtime driver/Morelia import. They do not validate the exact sink set, and optional sink import failures can surface too late.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Runtime construction and dependency preflight”, “Service sinks”, and gap SINK-13.
- `app/control/supervisor.py` — `ensure_runtime_driver_ready`, `_ensure_morelia_ready`, and start orchestration.
- `app/runtime_child/morelia.py` — `_import_morelia` and runtime initialization.
- `app/watchdog_process/__main__.py` — worker construction and environment boundary.
- `app/config.py` — relevant timeout/settings definitions.
- `tests/test_runtime_driver_selection.py` — driver selection/preflight cases.
- `tests/test_startup_failure_recovery.py` — failed-start cleanup contract.
- `tests/test_watchdog_process_entrypoint.py` — worker construction tests.

## Exact edit set

- `app/control/supervisor.py`
- `app/runtime_child/morelia.py`
- `app/watchdog_process/__main__.py`
- `tests/test_runtime_driver_selection.py`
- `tests/test_startup_failure_recovery.py`

## Scope boundaries

Do not write data, create delivery outboxes, retry after a successful start, or validate unselected sink dependencies. Keep credential values worker-local and redact all failures.

## Contract / invariant

Preflight is selection-aware and side-effect bounded. Influx/Quest must be reachable initially; missing credential references or dependencies fail the start before hardware ownership changes.

## Acceptance criteria

1. Each selected sink is checked for its dependency and configuration requirements; unselected optional sinks cannot block startup.
2. Influx/Quest initial unavailability fails startup with a sink-addressed, redacted error and leaves the session restartable.
3. A successful preflight does not leave open files, network clients, worker processes, or hardware handles.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_runtime_driver_selection.py tests/test_startup_failure_recovery.py tests/test_watchdog_process_entrypoint.py
```

## Failure handling

On any preflight failure, unwind resources in reverse ownership order and preserve the original sink-specific cause.

## Handoff note

Document the preflight result shape and redaction rules for runtime integration and CLI/status rendering.
