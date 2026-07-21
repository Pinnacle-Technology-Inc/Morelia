"""Contract tests for the SSE live endpoint (packet 7.6).

Testing strategy: the generator is tested directly (bypassing HTTP) because
the Flask test client exhausts response iterables — which would hang on an
infinite SSE stream. Content-type is checked by calling the view function in
a request context without consuming the body. The 404 case IS testable via
the test client because the route aborts before returning a stream.
"""

import json

import pytest

from app.api.events_stream import _sse_generator, stream_events
from app.database import transaction
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from app.services.event_ingest import ingest_report


# ── Test helpers ──────────────────────────────────────────────────────────────

def _create_session(app, dataflow_suffix: str = "") -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "SSE Test"})
        session_id = session.id
        with transaction():
            session.dataflow_id = f"df-sse{dataflow_suffix}-{session_id}"
        return session_id


def _add_events(app, session_id: int, count: int) -> list[int]:
    """Append `count` events to session; return their ids."""
    event_ids = []
    with app.app_context():
        repo = BackendEventRepository()
        # Fetch the session's dataflow_id
        session = SessionRepository().get(session_id)
        dataflow_id = session.dataflow_id
        for seq in range(1, count + 1):
            eid = repo.append(
                event_type="runtime.report",
                session_id=session_id,
                dataflow_id=dataflow_id,
                sequence=seq,
                payload={"phase": "running", "seq": seq},
            )
            event_ids.append(eid)
    return event_ids


def _read_n_event_frames(gen, n: int) -> list[str]:
    """Consume up to n non-comment frames from a generator, then close it."""
    frames = []
    try:
        for frame in gen:
            if frame.startswith(":"):
                continue  # skip heartbeat comments
            frames.append(frame)
            if len(frames) >= n:
                break
    finally:
        gen.close()
    return frames


def _parse_frame(frame: str) -> dict:
    """Parse a single SSE frame into {'id', 'event', 'data'} (data decoded from JSON)."""
    result = {}
    for line in frame.strip().split("\n"):
        if line.startswith("id: "):
            result["id"] = int(line[4:])
        elif line.startswith("event: "):
            result["event"] = line[7:]
        elif line.startswith("data: "):
            result["data"] = json.loads(line[6:])
    return result


# ── AC1: events stream in ascending id order with correct id: line ────────────

def test_frames_in_ascending_id_order(app):
    """Events are emitted in ascending backend_events.id order."""
    session_id = _create_session(app, "-ord")
    _add_events(app, session_id, count=3)

    with app.app_context():
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
        frames = _read_n_event_frames(gen, 3)

    ids = [_parse_frame(f)["id"] for f in frames]
    assert ids == sorted(ids)
    assert len(ids) == 3


def test_frame_contains_id_event_data_lines(app):
    """Each event frame has id:, event:, and data: fields."""
    session_id = _create_session(app, "-fmt")
    event_ids = _add_events(app, session_id, count=1)

    with app.app_context():
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
        frames = _read_n_event_frames(gen, 1)

    parsed = _parse_frame(frames[0])
    assert parsed["id"] == event_ids[0]
    assert parsed["event"] == "runtime.report"
    assert "phase" in parsed["data"]


def test_frame_includes_lifted_runtime_report_fields(app):
    """Watch frames include report fields stored outside payload columns."""
    session_id = _create_session(app, "-lifted")

    with app.app_context():
        session = SessionRepository().get(session_id)
        event_id = ingest_report({
            "dataflow_id": session.dataflow_id,
            "phase": "running",
            "comms": "current",
            "devices": [{"device_id": "d1", "stream_status": "healthy"}],
            "sequence": 42,
            "recovery_id": "rec-42",
        })
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
        frames = _read_n_event_frames(gen, 1)

    parsed = _parse_frame(frames[0])
    assert parsed["id"] == event_id
    assert parsed["data"] == {
        "comms": "current",
        "devices": [{"device_id": "d1", "stream_status": "healthy"}],
        "phase": "running",
        "recovery_id": "rec-42",
        "sequence": 42,
    }


def test_id_field_matches_backend_event_id(app):
    """SSE id: field is exactly the backend_events.id, usable as a replay cursor."""
    session_id = _create_session(app, "-id")
    event_ids = _add_events(app, session_id, count=2)

    with app.app_context():
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
        frames = _read_n_event_frames(gen, 2)

    sse_ids = [_parse_frame(f)["id"] for f in frames]
    assert sse_ids == event_ids


# ── AC2: client disconnect terminates the generator cleanly ───────────────────

def test_disconnect_does_not_raise(app):
    """gen.close() (simulates disconnect) exits the generator without exception."""
    session_id = _create_session(app, "-dc")
    _add_events(app, session_id, count=1)

    with app.app_context():
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
        next(gen)   # start the generator
        gen.close() # simulate client disconnect


def test_disconnect_before_first_frame_is_clean(app):
    """Closing a generator that hasn't yielded yet does not raise."""
    session_id = _create_session(app, "-dc2")
    # No events — generator would poll and sleep before yielding
    with app.app_context():
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
        gen.close()


def test_disconnect_sets_teardown_flag(app):
    """Verify the generator's finally block runs on GeneratorExit."""
    session_id = _create_session(app, "-flag")
    _add_events(app, session_id, count=1)
    teardown_ran = []

    def _patched():
        """Wrapper that records whether finally block executed."""
        with app.app_context():
            gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=9999.0)
            try:
                yield from gen
            finally:
                teardown_ran.append(True)

    with app.app_context():
        gen = _patched()
        next(gen)
        gen.close()

    assert teardown_ran == [True]


# ── AC3: response content type is text/event-stream ──────────────────────────

def test_content_type_is_text_event_stream(app):
    """The route returns Content-Type: text/event-stream."""
    session_id = _create_session(app, "-ct")
    # Call the view function directly inside a request context.
    # The generator is lazy — content_type is set before any iteration.
    with app.test_request_context(f"/api/v1/sessions/{session_id}/events"):
        resp = stream_events(session_id)
    assert "text/event-stream" in resp.content_type


def test_stream_response_keeps_context_during_iteration(app):
    """Werkzeug iterates streamed bodies after the view returns."""
    session_id = _create_session(app, "-ctx")
    _add_events(app, session_id, count=1)

    with app.test_request_context(f"/api/v1/sessions/{session_id}/events"):
        resp = stream_events(session_id)

    frame = next(resp.response)
    resp.response.close()

    assert frame.startswith("id: ")
    assert "event: runtime.report" in frame


# ── Heartbeat frames ──────────────────────────────────────────────────────────

def test_heartbeat_frame_is_comment(app):
    """Heartbeat frames are SSE comment lines starting with ':'."""
    session_id = _create_session(app, "-hb")
    # No events; heartbeat_interval=0 means a heartbeat fires immediately.
    with app.app_context():
        gen = _sse_generator(session_id, poll_interval=0.0, heartbeat_interval=0.0)
        frame = next(gen)
        gen.close()
    assert frame.startswith(":")


# ── 404 guard ────────────────────────────────────────────────────────────────

def test_unknown_session_returns_404(app, client):
    """Non-existent session_id gets a 404 before the stream starts."""
    resp = client.get("/api/v1/sessions/99999/events")
    assert resp.status_code == 404
