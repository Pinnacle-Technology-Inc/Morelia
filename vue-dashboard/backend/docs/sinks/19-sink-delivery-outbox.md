# Packet 19 — Add the service-sink delivery outbox

Status: ready  
Size: M  
Depends on: 08, 10

## Purpose

Add a dedicated durable buffer for raw Influx/Quest delivery data with independent per-sink time and byte bounds plus a global disk cap.

## Prior state

`WatchdogOutbox` persists bounded telemetry envelopes only. Reusing it for raw samples would mix retention, replay, privacy, and loss semantics and still would not reconstruct service writes.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Service sinks”, gap SINK-27, and release-critical scenario 3.
- `app/watchdog_process/outbox.py` — telemetry-only `WatchdogOutbox` conventions and separation boundary.
- `app/watchdog_process/process.py` — current outbox ownership/flush lifecycle.
- `app/config.py` — configured limits and paths.
- `app/models/output_file.py` — sink delivery/loss state vocabulary.
- `app/contracts/watchdog_process_protocol.py` — telemetry payload boundary that must remain unchanged.
- `tests/test_watchdog_process_outbox.py` — durability/retry test patterns.

## Exact edit set

- `app/watchdog_process/sink_delivery_outbox.py`
- `app/config.py`
- `tests/test_sink_delivery_outbox.py`

## Scope boundaries

Do not modify `WatchdogOutbox`, send network requests, resolve credentials, or wire the new outbox into adapters. Do not claim dropped records are recoverable from telemetry.

## Contract / invariant

Each service sink has a stable acquisition/sink key and ordered durable records. Default bounds are 300 seconds and 256 MiB per sink plus an explicit global disk cap. On overflow, drop oldest, persist exact loss counters/ranges, and expose degraded/permanent-loss state.

## Acceptance criteria

1. Enqueue, ordered replay/ack, crash reopen, and duplicate retry are deterministic and idempotency-key aware.
2. Both time and byte bounds, plus the global cap, are enforced by dropping oldest records and atomically recording lost bytes/records/time range.
3. Telemetry outbox data/files/APIs remain independent and cannot be interpreted as raw service delivery data.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_sink_delivery_outbox.py tests/test_watchdog_process_outbox.py
```

## Failure handling

If durable enqueue fails, surface explicit degraded/loss state and apply the documented in-memory fallback bound; never silently block acquisition indefinitely or report delivery success.

## Handoff note

Publish the enqueue/replay/ack API, stable key format, and loss report shape for Influx, Quest, ingest, and stop packets.
