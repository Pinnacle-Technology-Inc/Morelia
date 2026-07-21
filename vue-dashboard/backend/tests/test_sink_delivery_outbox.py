"""Tests for the standalone service-sink raw delivery outbox.

Like ``tests/test_watchdog_process_outbox.py``, these deliberately do NOT use
the ``app``/``client`` fixtures: the delivery outbox is a Flask-less library
for the watchdog process, constructed directly with a ``tmp_path`` file. It is
a SEPARATE store from the telemetry ``WatchdogOutbox`` and the tests assert
that separation.
"""

from __future__ import annotations

import sqlite3

from flask import has_app_context

from app.watchdog_process.sink_delivery_outbox import (
    SinkDeliveryOutbox,
    default_sink_delivery_outbox_path,
    sink_delivery_key,
)

KEY_A = sink_delivery_key(acquisition_id="src-1", logical_sink_id="influx-1")
KEY_B = sink_delivery_key(acquisition_id="src-1", logical_sink_id="quest-1")


def _outbox(tmp_path, **kwargs) -> SinkDeliveryOutbox:
    return SinkDeliveryOutbox(tmp_path / "sink-delivery.sqlite3", **kwargs)


# ── construction / identity helpers ──────────────────────────────────────────

def test_creates_sqlite_file_at_configured_path(tmp_path):
    path = tmp_path / "nested" / "watchdog-1-sink-delivery.sqlite3"
    with SinkDeliveryOutbox(path):
        assert path.exists()


def test_default_path_names_file_by_stable_dataflow_id(tmp_path):
    path = default_sink_delivery_outbox_path(tmp_path / "dir", "dataflow-42")
    assert path == tmp_path / "dir" / "dataflow-42-sink-delivery.sqlite3"
    assert not path.exists()


def test_default_path_does_not_collide_with_telemetry_outbox_file():
    # Telemetry outbox is "{watchdog_id}.sqlite3"; the delivery file must differ.
    delivery = default_sink_delivery_outbox_path("dir", "wd-1").name
    assert delivery == "wd-1-sink-delivery.sqlite3"
    assert delivery != "wd-1.sqlite3"


def test_sink_delivery_key_is_stable_per_acquisition_and_sink():
    assert sink_delivery_key(acquisition_id="a", logical_sink_id="s") == "a::s"
    assert KEY_A != KEY_B


def test_no_flask_app_context_required(tmp_path):
    assert not has_app_context()
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"line", idempotency_key="i1")
        outbox.pending()
        outbox.ack("i1")
        outbox.count_pending()
        outbox.loss_report(KEY_A)
    assert not has_app_context()


# ── acceptance 1: enqueue, ordered replay/ack, crash reopen, dup retry ───────

def test_enqueue_returns_true_then_false_on_duplicate_idempotency_key(tmp_path):
    with _outbox(tmp_path) as outbox:
        first = outbox.enqueue(KEY_A, b"a", idempotency_key="i1")
        second = outbox.enqueue(KEY_A, b"b", idempotency_key="i1")
    assert first is True
    assert second is False


def test_duplicate_enqueue_does_not_change_or_duplicate_row(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"original", idempotency_key="i1")
        outbox.enqueue(KEY_A, b"different", idempotency_key="i1")
        pending = outbox.pending()
    assert len(pending) == 1
    assert pending[0].payload == b"original"


def test_pending_returns_records_in_insertion_order(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"1", idempotency_key="i1")
        outbox.enqueue(KEY_A, b"2", idempotency_key="i2")
        outbox.enqueue(KEY_A, b"3", idempotency_key="i3")
        pending = outbox.pending()
    assert [r.idempotency_key for r in pending] == ["i1", "i2", "i3"]


def test_pending_filters_by_sink_key_and_respects_limit(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"a1", idempotency_key="a1")
        outbox.enqueue(KEY_B, b"b1", idempotency_key="b1")
        outbox.enqueue(KEY_A, b"a2", idempotency_key="a2")

        assert [r.idempotency_key for r in outbox.pending(KEY_A)] == ["a1", "a2"]
        assert [r.idempotency_key for r in outbox.pending(KEY_A, limit=1)] == ["a1"]
        assert [r.idempotency_key for r in outbox.pending(KEY_B)] == ["b1"]


def test_ack_removes_only_the_acked_record(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"1", idempotency_key="i1")
        outbox.enqueue(KEY_A, b"2", idempotency_key="i2")
        outbox.ack("i1")
        pending = outbox.pending()
    assert [r.idempotency_key for r in pending] == ["i2"]


def test_ack_is_idempotent_and_ignores_unknown_key(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"1", idempotency_key="i1")
        outbox.ack("i1")
        outbox.ack("i1")
        outbox.ack("does-not-exist")
        assert outbox.pending() == []


def test_ack_many_removes_all_given(tmp_path):
    with _outbox(tmp_path) as outbox:
        for i in range(3):
            outbox.enqueue(KEY_A, b"x", idempotency_key=f"i{i}")
        outbox.ack_many(["i0", "i2"])
        assert [r.idempotency_key for r in outbox.pending()] == ["i1"]


def test_crash_reopen_preserves_pending_records(tmp_path):
    path = tmp_path / "sink-delivery.sqlite3"
    with SinkDeliveryOutbox(path) as outbox:
        outbox.enqueue(KEY_A, b"payload", idempotency_key="i1", sample_count=7)
    with SinkDeliveryOutbox(path) as reopened:
        pending = reopened.pending()
    assert len(pending) == 1
    assert pending[0].payload == b"payload"
    assert pending[0].sample_count == 7


def test_enqueue_new_allocates_distinct_durable_identity_after_reopen(tmp_path):
    path = tmp_path / "sink-delivery.sqlite3"
    with SinkDeliveryOutbox(path) as outbox:
        first = outbox.enqueue_new(KEY_A, b"first")
    with SinkDeliveryOutbox(path) as reopened:
        second = reopened.enqueue_new(KEY_A, b"second")
        pending = reopened.pending(KEY_A)

    assert first is not None
    assert second is not None
    assert first.idempotency_key != second.idempotency_key
    assert [record.payload for record in pending] == [b"first", b"second"]


def test_enqueue_commits_synchronously(tmp_path):
    path = tmp_path / "sink-delivery.sqlite3"
    with SinkDeliveryOutbox(path) as outbox:
        outbox.enqueue(KEY_A, b"p", idempotency_key="i1")
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT idempotency_key FROM sink_delivery_records"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("i1",)]


def test_string_payload_is_encoded_and_round_trips(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, "temp=1i", idempotency_key="i1")
        rec = outbox.pending()[0]
    assert rec.payload == b"temp=1i"
    assert rec.byte_size == len(b"temp=1i")


# ── acceptance 2: age + byte bounds + global cap evict oldest & record loss ──

def test_age_bound_evicts_expired_and_records_exact_loss(tmp_path):
    with _outbox(tmp_path, max_age_seconds=100) as outbox:
        # Two old samples (t=0, t=10) and one fresh (t=1000) evaluated at now=1000.
        outbox.enqueue(KEY_A, b"aa", idempotency_key="old1",
                       sample_count=2, record_time=0.0, now=0.0)
        outbox.enqueue(KEY_A, b"bbbb", idempotency_key="old2",
                       sample_count=4, record_time=10.0, now=10.0)
        outbox.enqueue(KEY_A, b"c", idempotency_key="fresh",
                       sample_count=1, record_time=1000.0, now=1000.0)

        assert [r.idempotency_key for r in outbox.pending()] == ["fresh"]
        loss = outbox.loss_report(KEY_A)
    assert loss.lost_records == 2
    assert loss.lost_bytes == len(b"aa") + len(b"bbbb")
    assert loss.lost_samples == 2 + 4
    assert loss.lost_time_start == 0.0
    assert loss.lost_time_end == 10.0
    assert loss.degraded is True


def test_evict_can_run_independently_of_enqueue(tmp_path):
    with _outbox(tmp_path, max_age_seconds=50) as outbox:
        outbox.enqueue(KEY_A, b"x", idempotency_key="i1",
                       record_time=0.0, now=0.0)
        # No new enqueue; a periodic sweep at now=1000 must still expire it.
        evicted = outbox.evict(now=1000.0)
        assert evicted == 1
        assert outbox.pending() == []
        assert outbox.is_degraded(KEY_A) is True


def test_per_sink_byte_bound_drops_oldest_until_under(tmp_path):
    # Cap 10 bytes/sink; four 4-byte records => must drop oldest to fit.
    with _outbox(tmp_path, max_age_seconds=1e9, max_bytes_per_sink=10) as outbox:
        for i in range(4):
            outbox.enqueue(KEY_A, b"xxxx", idempotency_key=f"i{i}",
                           record_time=float(i), now=float(i))
        pending = outbox.pending(KEY_A)
        loss = outbox.loss_report(KEY_A)
    # 16 bytes total, cap 10 => keep newest 2 (8 bytes), drop oldest 2.
    assert [r.idempotency_key for r in pending] == ["i2", "i3"]
    assert loss.lost_records == 2
    assert loss.lost_bytes == 8


def test_per_sink_byte_bound_is_independent_across_sinks(tmp_path):
    with _outbox(tmp_path, max_age_seconds=1e9, max_bytes_per_sink=10) as outbox:
        for i in range(4):
            outbox.enqueue(KEY_A, b"xxxx", idempotency_key=f"a{i}",
                           record_time=float(i), now=float(i))
        # KEY_B has only one small record and must be untouched by KEY_A's overflow.
        outbox.enqueue(KEY_B, b"yy", idempotency_key="b0",
                       record_time=0.0, now=0.0)

        assert [r.idempotency_key for r in outbox.pending(KEY_B)] == ["b0"]
        assert outbox.loss_report(KEY_B).lost_records == 0
        assert outbox.loss_report(KEY_A).lost_records == 2


def test_global_disk_cap_drops_oldest_across_all_sinks(tmp_path):
    # Per-sink cap generous, but global cap 10 bytes forces cross-sink eviction.
    with _outbox(
        tmp_path,
        max_age_seconds=1e9,
        max_bytes_per_sink=1_000_000,
        max_total_bytes=10,
    ) as outbox:
        outbox.enqueue(KEY_A, b"xxxx", idempotency_key="a0",
                       record_time=0.0, now=0.0)
        outbox.enqueue(KEY_B, b"yyyy", idempotency_key="b0",
                       record_time=1.0, now=1.0)
        outbox.enqueue(KEY_A, b"zzzz", idempotency_key="a1",
                       record_time=2.0, now=2.0)

        remaining = {r.idempotency_key for r in outbox.pending()}
        total = outbox.total_bytes()
    # 12 bytes total, cap 10 => oldest (a0, 4 bytes) evicted globally.
    assert remaining == {"b0", "a1"}
    assert total == 8


def test_loss_counters_are_durable_across_reopen(tmp_path):
    path = tmp_path / "sink-delivery.sqlite3"
    with SinkDeliveryOutbox(path, max_age_seconds=50) as outbox:
        outbox.enqueue(KEY_A, b"aa", idempotency_key="old", sample_count=3,
                       record_time=0.0, now=1000.0)
        assert outbox.loss_report(KEY_A).lost_records == 1

    with SinkDeliveryOutbox(path, max_age_seconds=50) as reopened:
        loss = reopened.loss_report(KEY_A)
    assert loss.lost_records == 1
    assert loss.lost_samples == 3
    assert loss.degraded is True


def test_loss_report_zero_when_nothing_lost(tmp_path):
    with _outbox(tmp_path) as outbox:
        outbox.enqueue(KEY_A, b"x", idempotency_key="i1")
        loss = outbox.loss_report(KEY_A)
    assert loss.lost_records == 0
    assert loss.lost_bytes == 0
    assert loss.lost_time_start is None
    assert loss.lost_time_end is None
    assert loss.degraded is False


def test_count_and_total_bytes_track_pending(tmp_path):
    with _outbox(tmp_path, max_age_seconds=1e9) as outbox:
        outbox.enqueue(KEY_A, b"xxxx", idempotency_key="i1",
                       record_time=0.0, now=0.0)
        outbox.enqueue(KEY_A, b"yy", idempotency_key="i2",
                       record_time=0.0, now=0.0)
        assert outbox.count_pending() == 2
        assert outbox.count_pending(KEY_A) == 2
        assert outbox.total_bytes() == 6
        outbox.ack("i1")
        assert outbox.count_pending() == 1
        assert outbox.total_bytes() == 2


# ── acceptance 3: telemetry outbox data/schema stays independent ─────────────

def test_delivery_outbox_schema_is_not_the_telemetry_schema(tmp_path):
    """The delivery store must not present as the telemetry outbox: its raw
    payload table exists and the telemetry ``outbox_reports`` table does not."""
    path = tmp_path / "sink-delivery.sqlite3"
    with SinkDeliveryOutbox(path):
        pass
    conn = sqlite3.connect(str(path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "sink_delivery_records" in tables
    assert "sink_delivery_loss" in tables
    assert "outbox_reports" not in tables
