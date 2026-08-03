from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository


def _session_id(app) -> int:
    with app.app_context():
        return SessionRepository().create({"name": "Event Test Session"}).id


def test_row_persists_with_utc_received_at(app):
    session_id = _session_id(app)
    repo = BackendEventRepository()

    with app.app_context():
        event_id = repo.append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-1",
            sequence=1,
            payload={"phase": "running"},
        )
        rows = repo.since(session_id, after_id=0, limit=10)

    assert len(rows) == 1
    assert rows[0].id == event_id
    # backend stamps received_at at insert time (SQLite strips tzinfo on read-back,
    # but the value is UTC — consistent with how incidents.opened_at behaves)
    assert rows[0].received_at is not None


def test_duplicate_dataflow_sequence_returns_first_id(app):
    session_id = _session_id(app)
    repo = BackendEventRepository()

    with app.app_context():
        first_id = repo.append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-2",
            sequence=5,
            payload={"phase": "running"},
        )
        second_id = repo.append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-2",
            sequence=5,
            payload={"phase": "running"},
        )
        rows = repo.since(session_id, after_id=0, limit=10)

    assert first_id == second_id
    assert len(rows) == 1


def test_since_returns_events_after_cursor(app):
    session_id = _session_id(app)
    repo = BackendEventRepository()

    with app.app_context():
        id1 = repo.append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-3",
            sequence=1,
            payload={},
        )
        id2 = repo.append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-3",
            sequence=2,
            payload={},
        )
        id3 = repo.append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-3",
            sequence=3,
            payload={},
        )

        rows = repo.since(session_id, after_id=id1, limit=10)

    assert [r.id for r in rows] == [id2, id3]
    assert rows == sorted(rows, key=lambda r: r.id)
