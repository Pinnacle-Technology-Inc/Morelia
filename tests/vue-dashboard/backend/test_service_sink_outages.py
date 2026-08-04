"""Packet 30 — service-sink outage release gates.

Proves bounded Influx/Quest delivery-outbox behavior under outage: age and byte
bounds with exact oldest-drop accounting, ordered replay/ack, durable loss
counters, and no credential material in stored payloads. Telemetry WatchdogOutbox
must remain a separate store.

Owning packets on failure: 19 (outbox), 24/25 (adapters). Disposable real
Influx/Quest services are optional CI extras; this file stays hermetic.
"""

from __future__ import annotations

import sqlite3

from app.watchdog_process.sink_delivery_outbox import (
    SinkDeliveryOutbox,
    default_sink_delivery_outbox_path,
    sink_delivery_key,
)

KEY_INFLUX = sink_delivery_key(acquisition_id="acq-gate", logical_sink_id="influx-1")
KEY_QUEST = sink_delivery_key(acquisition_id="acq-gate", logical_sink_id="quest-1")


def _outbox(tmp_path, **kwargs) -> SinkDeliveryOutbox:
    return SinkDeliveryOutbox(tmp_path / "gate-sink-delivery.sqlite3", **kwargs)


def test_delivery_outbox_is_separate_from_telemetry_filename(tmp_path):
    delivery = default_sink_delivery_outbox_path(tmp_path, "df-gate")
    assert delivery.name == "df-gate-sink-delivery.sqlite3"
    assert delivery.name != "wd-gate.sqlite3"
    # Construct without requiring Flask; presence of an ambient app context from
    # other tests must not be required for the outbox to open.
    with SinkDeliveryOutbox(delivery) as outbox:
        outbox.enqueue(KEY_INFLUX, b"x", idempotency_key="sep")
        assert outbox.count_pending() == 1


def test_outage_buffers_in_order_and_replays_after_ack(tmp_path):
    with _outbox(tmp_path) as outbox:
        assert outbox.enqueue(KEY_INFLUX, b"line=1i", idempotency_key="i1") is True
        assert outbox.enqueue(KEY_INFLUX, b"line=2i", idempotency_key="i2") is True
        # Duplicate retry during outage must not reorder or duplicate.
        assert outbox.enqueue(KEY_INFLUX, b"line=1i-dup", idempotency_key="i1") is False

        pending = outbox.pending(KEY_INFLUX)
        assert [r.idempotency_key for r in pending] == ["i1", "i2"]
        assert [r.payload for r in pending] == [b"line=1i", b"line=2i"]

        outbox.ack("i1")
        assert [r.idempotency_key for r in outbox.pending(KEY_INFLUX)] == ["i2"]


def test_age_and_byte_bounds_record_exact_oldest_drop_accounting(tmp_path):
    with _outbox(tmp_path, max_age_seconds=100, max_bytes_per_sink=10) as outbox:
        # Age eviction: two old + one fresh.
        outbox.enqueue(
            KEY_INFLUX,
            b"aa",
            idempotency_key="old1",
            sample_count=2,
            record_time=0.0,
            now=0.0,
        )
        outbox.enqueue(
            KEY_INFLUX,
            b"bbbb",
            idempotency_key="old2",
            sample_count=4,
            record_time=10.0,
            now=10.0,
        )
        outbox.enqueue(
            KEY_INFLUX,
            b"c",
            idempotency_key="fresh",
            sample_count=1,
            record_time=1000.0,
            now=1000.0,
        )
        age_loss = outbox.loss_report(KEY_INFLUX)
        assert [r.idempotency_key for r in outbox.pending(KEY_INFLUX)] == ["fresh"]
        assert age_loss.lost_records == 2
        assert age_loss.lost_bytes == len(b"aa") + len(b"bbbb")
        assert age_loss.lost_samples == 6
        assert age_loss.degraded is True

        # Byte bound on an independent sink: four 4-byte records, cap 10.
        for i in range(4):
            outbox.enqueue(
                KEY_QUEST,
                b"xxxx",
                idempotency_key=f"q{i}",
                record_time=float(i),
                now=float(i),
            )
        byte_loss = outbox.loss_report(KEY_QUEST)
        assert [r.idempotency_key for r in outbox.pending(KEY_QUEST)] == ["q2", "q3"]
        assert byte_loss.lost_records == 2
        assert byte_loss.lost_bytes == 8
        # Sibling Influx loss counters stay independent.
        assert outbox.loss_report(KEY_INFLUX).lost_records == 2


def test_loss_counters_survive_reopen_and_payloads_carry_no_secrets(tmp_path):
    path = tmp_path / "durable-delivery.sqlite3"
    secret = b"api_token=super-secret-value"
    with SinkDeliveryOutbox(path, max_age_seconds=50) as outbox:
        outbox.enqueue(
            KEY_INFLUX,
            b"temp=1i",
            idempotency_key="keep",
            record_time=1000.0,
            now=1000.0,
        )
        outbox.enqueue(
            KEY_INFLUX,
            secret,
            idempotency_key="old",
            sample_count=1,
            record_time=0.0,
            now=0.0,
        )
        # Force age eviction of the secret-bearing row.
        outbox.evict(now=1000.0)
        assert outbox.loss_report(KEY_INFLUX).lost_records == 1

    with SinkDeliveryOutbox(path, max_age_seconds=50) as reopened:
        loss = reopened.loss_report(KEY_INFLUX)
        assert loss.lost_records == 1
        pending = reopened.pending(KEY_INFLUX)
        assert [r.idempotency_key for r in pending] == ["keep"]
        assert pending[0].payload == b"temp=1i"

    # Evicted secret payload must not linger in the SQLite file.
    con = sqlite3.connect(path)
    try:
        blobs = [row[0] for row in con.execute("SELECT payload FROM sink_delivery_records")]
    finally:
        con.close()
    assert secret not in blobs
    assert all(b"super-secret-value" not in (blob or b"") for blob in blobs)


def test_quest_and_influx_outages_do_not_cross_contaminate(tmp_path):
    with _outbox(tmp_path, max_age_seconds=1e9, max_bytes_per_sink=10) as outbox:
        for i in range(4):
            outbox.enqueue(
                KEY_INFLUX,
                b"xxxx",
                idempotency_key=f"inf{i}",
                record_time=float(i),
                now=float(i),
            )
        outbox.enqueue(
            KEY_QUEST,
            b"yy",
            idempotency_key="quest0",
            record_time=0.0,
            now=0.0,
        )
        assert outbox.loss_report(KEY_INFLUX).lost_records == 2
        assert outbox.loss_report(KEY_QUEST).lost_records == 0
        assert [r.idempotency_key for r in outbox.pending(KEY_QUEST)] == ["quest0"]
