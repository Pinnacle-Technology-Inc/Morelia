import pytest

from app.database import transaction
from app.domain.errors import UnknownDataflow
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from app.services.event_ingest import ingest_report


def _raw_report(dataflow_id: str, sequence: int = 1) -> dict:
    return {
        "dataflow_id": dataflow_id,
        "phase": "running",
        "comms": "current",
        "devices": [{"device_id": "d1", "stream_status": "healthy"}],
        "sequence": sequence,
    }


def _session_with_dataflow(app, dataflow_id: str) -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "Ingest Test"})
        with transaction():
            session.dataflow_id = dataflow_id
        return session.id


# ── Acceptance criterion 1 ────────────────────────────────────────────────────

def test_received_at_is_stamped_by_backend(app):
    """A report with no timestamp produces a row whose received_at is a backend UTC value."""
    session_id = _session_with_dataflow(app, "df-ac1")

    with app.app_context():
        event_id = ingest_report(_raw_report("df-ac1", sequence=1))
        rows = BackendEventRepository().since(session_id, after_id=0, limit=10)

    assert len(rows) == 1
    assert rows[0].id == event_id
    assert rows[0].received_at is not None


# ── Acceptance criterion 2 ────────────────────────────────────────────────────

def test_duplicate_sequence_returns_same_id(app):
    """Same (dataflow_id, sequence) ingested twice yields one row and the same id."""
    _session_with_dataflow(app, "df-ac2")

    with app.app_context():
        first_id = ingest_report(_raw_report("df-ac2", sequence=7))
        second_id = ingest_report(_raw_report("df-ac2", sequence=7))

    assert first_id == second_id


# ── Acceptance criterion 3 ────────────────────────────────────────────────────

def test_unknown_field_raises_value_error_and_writes_nothing(app):
    """Unknown report field raises ValueError and persists nothing."""
    session_id = _session_with_dataflow(app, "df-ac3")
    raw = {**_raw_report("df-ac3"), "unexpected_field": "boom"}

    with app.app_context():
        with pytest.raises(ValueError, match="unknown runtime report fields"):
            ingest_report(raw)
        rows = BackendEventRepository().since(session_id, after_id=0, limit=10)

    assert rows == []


# ── Additional contract tests ─────────────────────────────────────────────────

def test_unknown_dataflow_raises_before_write(app):
    """A dataflow_id with no linked session raises UnknownDataflow."""
    with app.app_context():
        with pytest.raises(UnknownDataflow):
            ingest_report(_raw_report("df-orphan", sequence=1))


def test_lifted_columns_match_report(app):
    """phase, comms, recovery_id, and sequence are stored in dedicated columns."""
    session_id = _session_with_dataflow(app, "df-cols")

    with app.app_context():
        event_id = ingest_report({
            "dataflow_id": "df-cols",
            "phase": "preflight",
            "comms": "delayed",
            "devices": [],
            "sequence": 42,
            "recovery_id": "rec-99",
        })
        event = BackendEventRepository().since(session_id, after_id=0, limit=100)
        row = next(r for r in event if r.id == event_id)

    assert row.phase == "preflight"
    assert row.comms == "delayed"
    assert row.sequence == 42
    assert row.recovery_id == "rec-99"


def test_devices_stored_in_payload(app):
    """Device list is flattened into the payload JSON, not a separate column."""
    session_id = _session_with_dataflow(app, "df-payload")

    with app.app_context():
        raw = _raw_report("df-payload")
        event_id = ingest_report(raw)
        event = BackendEventRepository().since(session_id, after_id=0, limit=100)
        row = next(r for r in event if r.id == event_id)

    assert "devices" in row.payload
    assert row.payload["devices"] == [{"device_id": "d1", "stream_status": "healthy"}]
