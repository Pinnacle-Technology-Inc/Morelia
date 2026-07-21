# Packet 00 — Restore the targeted baseline

Status: ready  
Size: S  
Depends on: 00A

## Purpose

Repair stale tests so later sink work starts from a trustworthy baseline. The observed targeted baseline is 14 failures and 83 passes; 13 failures use the retired device-template ID/name contract and one watchdog stub lacks the current telemetry-timeout setting.

## Prior state

Production session configuration is path/content-hash based, but selected tests still construct `device_template` or `device_template_id`. The watchdog entrypoint test's config stub predates `WATCHDOG_TELEMETRY_TIMEOUT_SECONDS`.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — sections “Repository health” and “Current baseline evidence”.
- `app/services/session_config.py` — `_ENTRY_FIELDS`, `validate_entry`, and canonical device-template fields.
- `app/services/device_templates.py` — current path-based template model and resolution behavior.
- `app/watchdog_process/__main__.py` — settings consumed by `build_process`.
- `tests/test_session_config.py` — stale session fixtures and assertions.
- `tests/test_runtime_manifest.py` — stale manifest input fixtures.
- `tests/test_watchdog_process_entrypoint.py` — incomplete settings stub.

## Exact edit set

- `tests/test_session_config.py`
- `tests/test_runtime_manifest.py`
- `tests/test_watchdog_process_entrypoint.py`

## Scope boundaries

Do not change production behavior, loosen validation, add sink types, or redesign fixtures beyond the stale fields identified above.

## Contract / invariant

Tests describe the current path-based device-template contract and complete runtime settings contract. Production code remains unchanged.

## Acceptance criteria

1. The targeted suite reports 97 passing tests and no failures.
2. No test uses the retired `device_template` or `device_template_id` session-entry fields.
3. The watchdog test stub supplies the same required setting names consumed by production.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_registry.py tests/test_session_config.py tests/test_runtime_manifest.py tests/test_managed_sink_append_on_recovery.py tests/test_watchdog_process_respawn.py tests/test_watchdog_process_entrypoint.py
```

Expected result: `97 passed`.

## Failure handling

If production code must change to pass, stop this packet and document the newly discovered contradiction; do not hide it in a fixture repair.

## Handoff note

Record the passing test count and any fixture vocabulary that later packets must preserve.
