# Packet 27 — Publish bounded live Plot data

Status: complete  

Size: M  
Depends on: 13, 20, 26

## Purpose

Implement Plot as a backend-to-browser live sample stream with bounded memory, explicit lag/drop state, and authenticated session/sink scoping.

## Prior state

Morelia's Plot sink is desktop-oriented and `get_dict()` mutates/reset rate state. The Vue dashboard has no live transport contract.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Plot”, gaps SINK-09/SINK-10, and release-critical scenario 5.
- `app/runtime_child/sink_factory.py` — Plot adapter construction boundary.
- `app/runtime_child/morelia.py` — sample dispatch and report path.
- `app/api/events_stream.py` — existing authenticated streaming conventions.
- `app/__init__.py` — router/application registration.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/plot_sink.py` — current rate/reset behavior to avoid.
- `tests/test_event_stream_sse.py` — streaming test conventions.

## Exact edit set

- `app/output/plot_sink.py`
- `app/api/plot_stream.py`
- `app/runtime_child/sink_factory.py`
- `app/__init__.py`
- `tests/test_plot_stream.py`

## Scope boundaries

Do not use Morelia's desktop GUI/Qt Plot sink, persist raw Plot samples, render Vue UI, or let a slow/disconnected browser block acquisition.

## Contract / invariant

Plot publishes bounded downsampled batches keyed by authorized session/source/sink. Each subscriber has bounded lag; oldest plot-only samples may drop with explicit counters. Observing status must not mutate/reset runtime rate counters.

## Acceptance criteria

1. An authorized client receives ordered schema/versioned sample batches and rate/timestamp metadata for the selected Plot sink only.
2. Slow/disconnected clients cause bounded plot drops and cleanup, never source/sibling-sink backpressure or unbounded memory.
3. Unauthorized/cross-session subscription fails, and payloads expose no credentials or non-Plot sink data.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_plot_stream.py tests/test_event_stream_sse.py
```

## Failure handling

Drop/close only the affected subscriber after its bound is exceeded, publish lag/drop state, and keep acquisition running.

## Handoff note

Freeze the stream URL, auth behavior, reconnect cursor semantics, schema version, and drop counters for packet 28.
