"""Tests for the standalone watchdog-process SQLite outbox.

Deliberately does not use the `app`/`client` fixtures from conftest.py: the
outbox must work with no Flask app context at all, since it is a library for
the (Flask-less) watchdog process, not the control-plane app.
"""

from __future__ import annotations

import sqlite3

import pytest
from flask import has_app_context

from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope
from app.watchdog_process.outbox import WatchdogOutbox, default_outbox_path


def _envelope(report_id: str, *, event_type: str = "runtime.report") -> WatchdogTelemetryEnvelope:
    return WatchdogTelemetryEnvelope(
        report_id=report_id,
        dataflow_id="df-1",
        runtime_id="runtime-1",
        watchdog_id="watchdog-1",
        manifest_hash="hash-1",
        event_type=event_type,
        payload={"devices": [{"device_id": "d1", "stream_status": "healthy"}]},
    )


# ── Acceptance criterion 1: creates/opens a SQLite file at a configured path ──

def test_creates_sqlite_file_at_configured_path(tmp_path):
    """Constructing an outbox creates the file (and parent dirs) on disk."""
    path = tmp_path / "nested" / "watchdog-1.sqlite3"

    with WatchdogOutbox(path):
        assert path.exists()


def test_reopening_existing_file_preserves_rows(tmp_path):
    """Closing and reopening the same path is opening, not recreating."""
    path = tmp_path / "outbox.sqlite3"

    with WatchdogOutbox(path) as outbox:
        outbox.enqueue(_envelope("r1"))

    with WatchdogOutbox(path) as reopened:
        pending = reopened.pending()

    assert [row.envelope.report_id for row in pending] == ["r1"]


def test_default_outbox_path_names_file_by_watchdog_id(tmp_path):
    """default_outbox_path is pure path arithmetic — no filesystem access."""
    path = default_outbox_path(tmp_path / "outbox-dir", "watchdog-42")

    assert path == tmp_path / "outbox-dir" / "watchdog-42.sqlite3"
    assert not path.exists()


def test_authenticated_adoption_rebinds_only_pending_runtime_rows(tmp_path):
    outbox = WatchdogOutbox(tmp_path / "outbox.sqlite3")
    try:
        outbox.enqueue(_envelope("r1"))
        outbox.enqueue(_envelope("r2"))
        outbox.mark_delivered("r1")

        outbox.rebind_pending_runtime(watchdog_id="watchdog-1", runtime_id="runtime-new")

        pending = outbox.pending()
        assert [row.envelope.runtime_id for row in pending] == ["runtime-new"]
    finally:
        outbox.close()


def test_no_flask_app_context_required(tmp_path):
    """Every outbox operation works with no Flask app context active."""
    assert not has_app_context()

    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))
        outbox.pending()
        outbox.mark_delivered("r1")
        outbox.count_pending()

    assert not has_app_context()


# ── Acceptance criterion 2: enqueue is durable and idempotent by report_id ───

def test_enqueue_returns_true_on_first_insert_false_on_duplicate(tmp_path):
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        first = outbox.enqueue(_envelope("r1", event_type="a"))
        second = outbox.enqueue(_envelope("r1", event_type="b"))

    assert first is True
    assert second is False


def test_duplicate_enqueue_does_not_change_stored_row(tmp_path):
    """A duplicate report_id is a no-op — the original row's fields stick."""
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1", event_type="original"))
        outbox.enqueue(_envelope("r1", event_type="different"))

        pending = outbox.pending()

    assert len(pending) == 1
    assert pending[0].envelope.event_type == "original"


def test_enqueue_persists_across_reconnect(tmp_path):
    """Enqueue commits synchronously — a crash right after must not lose it."""
    path = tmp_path / "outbox.sqlite3"
    with WatchdogOutbox(path) as outbox:
        outbox.enqueue(_envelope("r1"))

    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT report_id FROM outbox_reports").fetchall()
    finally:
        conn.close()

    assert rows == [("r1",)]


# ── Acceptance criterion 3: pending rows flush in insertion order and can ────
# ── be marked delivered ───────────────────────────────────────────────────────

def test_pending_returns_rows_in_insertion_order(tmp_path):
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))
        outbox.enqueue(_envelope("r2"))
        outbox.enqueue(_envelope("r3"))

        pending = outbox.pending()

    assert [row.envelope.report_id for row in pending] == ["r1", "r2", "r3"]


def test_pending_respects_limit(tmp_path):
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))
        outbox.enqueue(_envelope("r2"))
        outbox.enqueue(_envelope("r3"))

        pending = outbox.pending(limit=2)

    assert [row.envelope.report_id for row in pending] == ["r1", "r2"]


def test_mark_delivered_removes_row_from_pending(tmp_path):
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))
        outbox.enqueue(_envelope("r2"))

        outbox.mark_delivered("r1")
        pending = outbox.pending()

    assert [row.envelope.report_id for row in pending] == ["r2"]


def test_mark_delivered_is_idempotent_and_ignores_unknown_report_id(tmp_path):
    """Marking an already-delivered or unknown report_id must not raise."""
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))

        outbox.mark_delivered("r1")
        outbox.mark_delivered("r1")
        outbox.mark_delivered("does-not-exist")

        pending = outbox.pending()

    assert pending == []


def test_mark_delivered_many_marks_all_given_reports(tmp_path):
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))
        outbox.enqueue(_envelope("r2"))
        outbox.enqueue(_envelope("r3"))

        outbox.mark_delivered_many(["r1", "r3"])
        pending = outbox.pending()

    assert [row.envelope.report_id for row in pending] == ["r2"]


def test_count_pending_reflects_delivered_state(tmp_path):
    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(_envelope("r1"))
        outbox.enqueue(_envelope("r2"))
        assert outbox.count_pending() == 2

        outbox.mark_delivered("r1")
        assert outbox.count_pending() == 1


def test_pending_envelope_round_trips_payload(tmp_path):
    """The envelope decoded back from the outbox matches the one enqueued."""
    envelope = _envelope("r1")

    with WatchdogOutbox(tmp_path / "outbox.sqlite3") as outbox:
        outbox.enqueue(envelope)
        pending = outbox.pending()

    assert len(pending) == 1
    assert pending[0].envelope == envelope
