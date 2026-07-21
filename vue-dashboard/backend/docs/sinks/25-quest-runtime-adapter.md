# Packet 25 — Add the Quest runtime adapter

Status: ready  
Size: S  
Depends on: 13, 19, 23

## Purpose

Deliver source samples to Quest with initial availability enforcement and bounded post-start buffering/replay.

## Prior state

The backend has no managed Quest adapter and cannot distinguish a post-start Quest outage from source failure or permanent silent loss.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Quest”, “Service sinks”, and release-critical scenario 3.
- `app/runtime_child/sink_factory.py` — adapter construction boundary.
- `app/watchdog_process/sink_delivery_outbox.py` — enqueue/replay/ack/loss API.
- `app/runtime_child/morelia.py` — worker reporting boundary.
- `C:/Users/ahoang/Morelia/src/Morelia/Stream/sink/quest_sink.py` — Quest row/protocol conventions.
- `tests/test_sink_factory.py` — construction test conventions.

## Exact edit set

- `app/output/quest_sink.py`
- `app/runtime_child/sink_factory.py`
- `tests/test_quest_sink.py`

## Scope boundaries

Do not add an undocumented credential field, change outbox bounds, implement Influx, or alter API/template configuration. Initial service probing belongs to packet 09.

## Contract / invariant

Direct delivery and replay use stable identities/order. Post-start unavailability buffers within packet 19's bounds, warns/degrades, drops oldest on overflow, and explicitly reports permanent loss without stopping a healthy source.

## Acceptance criteria

1. A disposable/fake Quest unavailable-at-start case fails cleanly before acquisition and closes its client.
2. A post-start outage proves ordered buffering, reconnect replay, acknowledgements, and no duplicate logical rows under retry.
3. Bound overflow reports exact dropped records/bytes/time range while healthy sibling sinks continue.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_quest_sink.py tests/test_sink_delivery_outbox.py
```

## Failure handling

If write acknowledgement is ambiguous, replay with the same stable identity and surface uncertainty; never silently discard or double-count the record.

## Handoff note

Record required Quest protocol/version behavior and retryable error classes for integration and rollout packets.

## Implemented reliability details

- The runtime uses the official `questdb` Sender in acknowledged ILP/HTTP mode (default port `9000`), not an unacknowledged raw TCP send.
- Startup creates the target table when absent and validates its designated timestamp plus deduplication UPSERT keys: `timestamp`, `acquisition_id`, `sink_id`, and `channel`. An incompatible existing table fails startup.
- Every structured row batch is persisted to the stable per-dataflow delivery outbox before its first network attempt. Transactional sender flush must succeed before acknowledgement.
- The deployment pins QuestDB-compatible client bounds (`questdb>=3.0,<5.0`); disposable-service verification remains an explicit release gate.
