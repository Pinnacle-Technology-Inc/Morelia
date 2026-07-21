# Packet 26 — Integrate multi-sink runtime supervision

Status: ready  
Size: M  
Depends on: 14, 15, 20, 23, 24, 25

## Purpose

Construct every selected sink in manifest order, attach them to one source, isolate sink failures, emit per-sink reports, and tear down ownership deterministically.

## Prior state

Runtime stack construction assumes one sink. Morelia sink errors are not yet connected to backend reports/recovery actions, and partial multi-sink construction has no unified rollback.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Runtime construction”, ownership map, and release-critical scenarios 1–3.
- `app/runtime_child/morelia.py` — `_build_stack`, `_emit_report`, `_close_sinks`, and recovery lifecycle.
- `app/runtime_child/sink_factory.py` — adapter creation/lifecycle.
- `app/runtime_host/manifest.py` — ordered v2 descriptors.
- `app/watchdog_process/__main__.py` — worker-side dependencies/outbox construction.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/data_flow.py` — source-to-many-sinks attachment.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/source.py` — structured callback from packet 23.
- `tests/test_morelia_runtime_pod8401.py` — runtime stack fixtures.

## Exact edit set

- `app/runtime_child/morelia.py`
- `app/watchdog_process/__main__.py`
- `tests/test_runtime_multi_sink_stack.py`
- `tests/test_watchdog_process_entrypoint.py`

## Scope boundaries

Do not implement frontend Plot rendering, finalization orchestration, API status aggregation, or modify Morelia again. Preserve the one-source-to-many-sinks / one-sink-to-one-source ownership rule.

## Contract / invariant

Each selected sink receives each source sample once in manifest order. `SinkDeliveryOutbox` is created only when at least one Influx or Quest sink is selected; file-only/Plot-only stacks create none. Sink failures affect only that sink's lifecycle; source errors drive source recovery. Partial start closes all created sinks and does not begin hardware acquisition.

## Acceptance criteria

1. CSV+EDF+PVFS+Influx+Quest test doubles attach to one source with stable identities/order and receive the expected samples; outbox construction occurs only for selected Influx/Quest sinks.
2. A single sink failure produces its state transition/recovery behavior while healthy siblings and source acquisition continue.
3. Stop, crash, and partial-construction paths close clients/handles/outboxes exactly once and emit a final bounded report.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_runtime_multi_sink_stack.py tests/test_morelia_runtime_pod8401.py tests/test_watchdog_process_entrypoint.py
```

## Failure handling

On construction failure, abort before acquisition and unwind in reverse order. After start, classify the failing sink and follow its adapter policy without converting it into a source restart.

## Handoff note

Record the lifecycle event timeline and injectable seams used by Plot, stop/restart, and release-gate packets.

## Implemented reliability details

- Reconstructed Morelia worker sinks receive the structured error callback additively through `bind_error_callback`, including service-sink degradation, recovery, buffering, and loss counters.
- Stack construction is all-or-nothing across every source. A failure on any later source closes already-built sinks and pods in reverse order, closes the error queue, and leaves no DataFlow or Watchdog instance.
- The raw delivery outbox is named by stable `dataflow_id`, while watchdog telemetry retains its separate per-process outbox and identity rules.
