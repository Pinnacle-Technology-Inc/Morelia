# Packet 06 — Define runtime manifest v2

Status: ready  
Size: M  
Depends on: 00, 01

## Purpose

Define an immutable, hash-stable manifest that carries acquisition identity and an ordered collection of fully resolved sink descriptors per source.

## Prior state

Manifest schema version 1 models one flattened sink and lacks the persisted session/acquisition context needed for output linkage and sink health.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Runtime manifest v2” and gaps SINK-03/SINK-11/SINK-20.
- `app/runtime_host/manifest.py` — `MANIFEST_SCHEMA_VERSION`, `DeviceFlow`, `_content_hash`, and `Manifest`.
- `app/domain/enums.py` — sink type/category vocabulary.
- `app/watchdog_process/__main__.py` — manifest reader boundary.
- `app/runtime_host/__main__.py` — host manifest loading boundary.
- `tests/test_runtime_host_manifest.py` — immutability/hash tests.

## Exact edit set

- `app/runtime_host/manifest.py`
- `tests/test_runtime_host_manifest.py`

## Scope boundaries

Do not resolve paths, allocate output rows, resolve credentials, construct sinks, or change process launch behavior.

## Contract / invariant

Manifest v2 is immutable, JSON-serializable, secret-free, and deterministically hashed. It contains stable session/acquisition/source/sink identities and ordered sink descriptors; preview manifests may use an explicitly nullable persisted identity.

## Acceptance criteria

1. Equivalent v2 manifests have identical hashes regardless of incidental dictionary construction order, while sink list order remains significant.
2. The v2 reader rejects unknown versions and can translate documented v1 input to one canonical sink without emitting v1.
3. No manifest field can contain a resolved Influx token or live object/handle.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_runtime_host_manifest.py
```

## Failure handling

If a current reader cannot consume v2, keep the writer gated behind packet 07 and document the reader dependency; do not emit an ambiguous hybrid schema.

## Handoff note

Publish the exact v2 JSON fixture and content-hash rules for resolver and process-contract packets.
