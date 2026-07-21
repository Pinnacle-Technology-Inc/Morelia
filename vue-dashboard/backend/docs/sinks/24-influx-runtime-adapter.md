# Packet 24 — Add the Influx runtime adapter

Status: ready  
Size: S  
Depends on: 13, 19, 23

## Purpose

Deliver source samples to Influx with worker-side environment credential resolution, initial availability enforcement, and bounded post-start buffering/replay.

## Prior state

The backend has no managed Influx adapter. Raw Morelia construction risks embedding credentials and does not satisfy the approved degradation/loss semantics.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Influx”, “Secrets”, and release-critical scenario 3.
- `app/runtime_child/sink_factory.py` — adapter construction boundary.
- `app/watchdog_process/sink_delivery_outbox.py` — enqueue/replay/ack/loss API.
- `app/runtime_child/morelia.py` — worker environment and report callback boundary.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/influx_sink.py` — point/tag/field conventions.
- `tests/test_sink_factory.py` — construction test conventions.

## Exact edit set

- `app/output/influx_sink.py`
- `app/runtime_child/sink_factory.py`
- `tests/test_influx_sink.py`

## Scope boundaries

Do not persist or return resolved tokens, change outbox bounds, implement Quest, or alter API/template configuration. Initial service probing belongs to packet 09; this adapter must honor that contract.

## Contract / invariant

The token environment-variable reference crosses into the worker; its value does not. Direct delivery and replay share stable idempotency keys. Post-start unavailability buffers within packet 19's bounds, warns/degrades, drops oldest on overflow, and explicitly reports permanent loss.

## Acceptance criteria

1. Missing/empty credential environment variables fail adapter construction with a redacted sink-addressed error and never appear in logs/reports.
2. A disposable/fake Influx outage test proves ordered buffer, reconnect replay, acknowledgement, and no duplicate logical points under retry.
3. Bound overflow reports exact dropped records/bytes/time range while healthy sibling sinks continue.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_influx_sink.py tests/test_sink_delivery_outbox.py
```

## Failure handling

If direct write outcome is ambiguous, enqueue/retry with the same idempotency identity and report uncertainty; never acknowledge before confirmed delivery.

## Handoff note

Record required Influx server capabilities, retryable error classes, and redaction assertions for integration and rollout packets.

## Implemented reliability details

- Writes use the Influx Python client's synchronous write mode, so an outbox record is acknowledged only after the server write call succeeds.
- Every sample is persisted to the stable per-dataflow delivery outbox before its first network attempt. Restarted watchdog processes reopen the same database and replay pending records.
- Logical identity is encoded in tags plus timestamp; retries preserve that identity and therefore follow Influx's duplicate-point overwrite semantics.
- Degradation and recovery callbacks include current buffered records/bytes and cumulative evicted records/bytes.
