# Packet 04 — Expose the multi-sink API contract

Status: ready  
Size: M  
Depends on: 02, 03

## Purpose

Make session and section-template endpoints accept and return the canonical ordered `sinks[]` model with useful validation errors.

## Prior state

API schemas expose one sink per device flow and cannot carry sink names or type-specific parameters.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “API/session services” and gap SINK-22/SINK-25.
- `app/api/schemas.py` — `SinkSchema`, `DeviceFlowSchema`, and session/template payloads.
- `app/api/sessions.py` — create, preview, and response mapping.
- `app/api/session_templates.py` — template endpoint mapping.
- `app/errors.py` — HTTP/domain error translation.
- `tests/test_sessions.py` — session API coverage.
- `tests/test_session_template_api.py` — template API coverage.

## Exact edit set

- `app/api/schemas.py`
- `app/errors.py`
- `tests/test_sessions.py`
- `tests/test_session_template_api.py`

## Scope boundaries

Do not implement runtime manifests, status telemetry, live Plot transport, or UI changes. Route code should remain unchanged unless a failing contract test proves it cannot pass the canonical service object through.

## Contract / invariant

The API mirrors the canonical service contract without inventing another sink representation. Validation identifies the source and sink index/name and never echoes secret values.

## Acceptance criteria

1. Session and template endpoints accept and return multiple ordered sinks, including repeated types with distinct names.
2. Legacy request input remains accepted only through the documented compatibility path; responses use only `sinks[]`.
3. Invalid sink payloads produce stable client errors with no credential leakage.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_sessions.py tests/test_session_template_api.py
```

## Failure handling

If route glue must change, add only the proven route file to the edit set and keep the total at five; otherwise split a follow-up packet.

## Handoff note

Record example request/response payloads for the CLI and Vue consumers.
