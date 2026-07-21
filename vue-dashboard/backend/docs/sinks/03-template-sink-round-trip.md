# Packet 03 — Preserve sinks in section templates

Status: ready  
Size: M  
Depends on: 02

## Purpose

Allow section templates to store, import, export, clone, and reuse complete source sink selections.

## Prior state

Template canonicalization is aligned to a single flattened sink and cannot faithfully represent repeated types or type-specific parameters.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Template import/export” and gap SINK-25.
- `app/services/session_config.py` — canonical source/sink shape from packet 02.
- `app/services/session_templates.py` — `_canonical_flow`, `_canonicalize`, import/export, and create.
- `app/repositories/session_templates.py` — persisted template boundary.
- `tests/test_session_templates.py` — service-level template cases.
- `tests/test_session_template_api.py` — persisted/API round-trip cases.

## Exact edit set

- `app/services/session_templates.py`
- `tests/test_session_templates.py`
- `tests/test_session_template_api.py`

## Scope boundaries

Do not add CLI interactivity or alter API request models in this packet. Do not persist resolved credentials or runtime-only sink state.

## Contract / invariant

Template sink data is portable, declarative, ordered, and secret-free. Loading a template yields the same canonical `sinks[]` contract accepted by session creation.

## Acceptance criteria

1. Templates round-trip multiple sinks, repeated sink types, names, order, and public parameters.
2. Legacy single-sink templates normalize on read and export in the new shape.
3. Invalid or secret-bearing template sink data fails before persistence with field-addressable errors.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_session_templates.py tests/test_session_template_api.py
```

## Failure handling

If stored legacy templates cannot be normalized deterministically, leave them unchanged and return an explicit migration error identifying the template.

## Handoff note

Provide one canonical multi-sink template fixture for packets 04 and 05.
