# Packet 13 — Centralize runtime sink construction

Status: ready  
Size: S  
Depends on: 07, 08, 12

## Purpose

Introduce one worker-side factory that converts manifest sink descriptors into lifecycle-compatible runtime adapters.

## Prior state

Morelia runtime construction assumes a CSV path and has no typed extension point for file, service, or browser sinks.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Runtime construction and dependency preflight” and “Process and ownership boundary map”.
- `app/runtime_host/manifest.py` — v2 sink descriptors.
- `app/runtime_child/morelia.py` — `_build_stack` and sink teardown.
- `app/output/managed_csv_sink.py` — established lifecycle protocol.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/__init__.py` — available Morelia sink classes.
- `tests/test_morelia_runtime_pod8401.py` — runtime fixture boundary.

## Exact edit set

- `app/runtime_child/sink_factory.py`
- `app/runtime_child/morelia.py`
- `tests/test_sink_factory.py`

## Scope boundaries

Register CSV fully. For adapters not yet implemented, return a typed “selected sink unavailable” construction error. Do not inline format logic, network clients, credential resolution, or Plot queues in the factory.

## Contract / invariant

The worker factory is the sole mapping from manifest type to runtime adapter. It preserves manifest order and identity and returns adapters with a common explicit lifecycle.

## Acceptance criteria

1. CSV descriptors construct the managed CSV adapter without changing output semantics.
2. Every approved type has an explicit factory branch; unfinished adapters fail with sink-addressed typed errors rather than falling through.
3. Unknown descriptors and adapter construction failures close already-created sibling adapters in reverse order.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_sink_factory.py tests/test_morelia_runtime_pod8401.py
```

## Failure handling

On partial construction, close all created adapters, retain the first failure as cause, and report cleanup failures as secondary diagnostics.

## Handoff note

Freeze the adapter lifecycle and dependency-injection points for packets 14, 15, 24, 25, and 27.
