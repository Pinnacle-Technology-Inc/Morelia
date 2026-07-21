# Packet 23 — Emit structured Morelia sink failures

Status: ready  
Size: M  
Depends on: 00

## Purpose

Replace printed sink exceptions with a structured callback/event that identifies the failing sink without terminating or misclassifying the source.

## Prior state

The Morelia source loop catches sink failures and prints them. The backend cannot reliably attribute, persist, buffer, or recover a specific sink failure.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — gaps SINK-08/SINK-19/SINK-23 and the ownership map.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/source.py` — `get_data` and `get_data_wrapper` sink dispatch/error handling.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/data_flow.py` — `DataFlow` lifecycle and source/sink association.
- `C:/Users/ahoang/Morelia/tests/test_stream_watcher_recovery.py` — source recovery tests.
- `C:/Users/ahoang/Morelia/tests/test_watchdog_lifecycle.py` — lifecycle compatibility tests.
- `app/runtime_child/morelia.py` — downstream callback consumer boundary.

## Exact edit set

- `C:/Users/ahoang/Morelia/src/Morelia/Stream/source.py`
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/data_flow.py`
- `C:/Users/ahoang/Morelia/tests/test_sink_error_reporting.py`

## Scope boundaries

This packet changes the separate, currently dirty Morelia checkout. Preserve unrelated edits and record its starting branch/commit. Do not add backend persistence, network retries, outbox logic, or source restart policy.

## Contract / invariant

Every sink write exception emits one bounded structured event with stable source/sink identity, exception class, redacted message, and timestamp. Callback failure cannot crash acquisition; source failures remain a distinct path.

## Acceptance criteria

1. A failing sink emits an attributable event while healthy sibling sinks continue receiving the same source data.
2. The source is not marked failed/recovered solely because a sink write failed.
3. With no callback configured, behavior remains compatible except that tests no longer depend on stdout text.

## Verification

```powershell
Push-Location C:\Users\ahoang\Morelia
python -m pytest -q tests/test_sink_error_reporting.py tests/test_stream_watcher_recovery.py tests/test_watchdog_lifecycle.py
Pop-Location
```

## Failure handling

If the required signature change breaks an unknown caller, stop and split a compatibility adapter packet; do not restore print-only error handling.

## Handoff note

Record the Morelia commit/worktree diff and callback signature for packet 26. Preserve evidence of pre-existing dirty files.
