# Packet 02 — Canonicalize multi-sink session configuration

Status: ready  
Size: M  
Depends on: 01

## Purpose

Replace the single flattened sink fields on a source with an ordered, validated `sinks[]` collection while keeping legacy input readable.

## Prior state

Session entries contain `sink_type` and `sink_location`, allowing only one CSV-like sink and losing per-sink identity.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Proposed public configuration contract” and “Backward compatibility”.
- `app/services/registry.py` — sink validation entry points from packet 01.
- `app/services/session_config.py` — `_ENTRY_FIELDS`, `_resolve_sink`, `validate_entry`, `_canonicalize`, import, and export.
- `app/services/sink_paths.py` — current file-location rules.
- `tests/test_session_config.py` — import/export and validation coverage.

## Exact edit set

- `app/services/session_config.py`
- `tests/test_session_config.py`

## Scope boundaries

Do not change template storage, API schemas, CLI prompts, manifests, runtime construction, or create filesystem paths.

## Contract / invariant

Every canonical source entry contains a non-empty ordered `sinks[]`. Each sink has a source-local unique `sink_name`; repeated sink types are permitted. File locations are accepted only for file sinks, and secrets are rejected everywhere.

## Acceptance criteria

1. Nested multi-sink JSON and TOML round-trip without reordering or losing per-sink parameters.
2. Legacy flattened input normalizes to one named sink, while all exports emit only `sinks[]`.
3. Duplicate names, empty collections, category-invalid locations, unknown fields, and token-like secret values fail with field-addressable errors.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_session_config.py
```

## Failure handling

If a legacy field is ambiguous, reject it with an actionable migration message rather than guessing a sink mapping.

## Handoff note

Record the canonical dictionary shape and legacy normalization rule for template, API, CLI, and manifest packets.
