"""Contract tests for SSE replay from cursor (packet 7.7)."""

from __future__ import annotations

import json

from app.api.events_stream import _sse_generator, stream_events
from app.database import transaction
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository


def _create_session(app, suffix: str = "") -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "Replay Test"})
        session_id = session.id
        with transaction():
            session.dataflow_id = f"df-replay{suffix}-{session_id}"
        return session_id


def _append_event(app, session_id: int, sequence: int) -> int:
    with app.app_context():
        session = SessionRepository().get(session_id)
        return BackendEventRepository().append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id=session.dataflow_id,
            sequence=sequence,
            payload={"sequence": sequence},
        )


def _append_events(app, session_id: int, count: int) -> list[int]:
    return [_append_event(app, session_id, sequence) for sequence in range(1, count + 1)]


def _read_n_event_frames(gen, n: int) -> list[str]:
    frames = []
    try:
        for frame in gen:
            if frame.startswith(":"):
                continue
            frames.append(frame)
            if len(frames) == n:
                break
    finally:
        gen.close()
    return frames


def _parse_frame(frame: str) -> dict:
    result = {}
    for line in frame.strip().split("\n"):
        if line.startswith("id: "):
            result["id"] = int(line[4:])
        elif line.startswith("event: "):
            result["event"] = line[7:]
        elif line.startswith("data: "):
            result["data"] = json.loads(line[6:])
    return result


def test_reconnect_with_last_event_id_replays_events_after_cursor(app):
    session_id = _create_session(app, "-hdr")
    event_ids = _append_events(app, session_id, count=4)

    with app.test_request_context(
        f"/api/v1/sessions/{session_id}/events",
        headers={"Last-Event-ID": str(event_ids[1])},
    ):
        response = stream_events(session_id)
        frames = _read_n_event_frames(response.response, 2)

    assert [_parse_frame(frame)["id"] for frame in frames] == event_ids[2:]


def test_query_after_takes_precedence_over_last_event_id_header(app):
    session_id = _create_session(app, "-query")
    event_ids = _append_events(app, session_id, count=4)

    with app.test_request_context(
        f"/api/v1/sessions/{session_id}/events?after={event_ids[2]}",
        headers={"Last-Event-ID": str(event_ids[0])},
    ):
        response = stream_events(session_id)
        frames = _read_n_event_frames(response.response, 1)

    assert [_parse_frame(frame)["id"] for frame in frames] == [event_ids[3]]


def test_replay_then_live_has_no_gap_or_duplicate_at_boundary(app):
    session_id = _create_session(app, "-seam")
    event_ids = _append_events(app, session_id, count=3)

    with app.app_context():
        gen = _sse_generator(
            session_id,
            after_id=event_ids[0],
            poll_interval=0.0,
            heartbeat_interval=9999.0,
        )
        first_replayed = next(gen)
        second_replayed = next(gen)
        live_id = BackendEventRepository().append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id=SessionRepository().get(session_id).dataflow_id,
            sequence=4,
            payload={"sequence": 4},
        )
        first_live = next(gen)
        gen.close()

    assert [_parse_frame(frame)["id"] for frame in (first_replayed, second_replayed)] == (
        event_ids[1:]
    )
    assert _parse_frame(first_live)["id"] == live_id


def test_missing_or_garbage_cursor_uses_live_stream_behavior_without_error(app):
    session_id = _create_session(app, "-bad")
    event_ids = _append_events(app, session_id, count=2)

    with app.test_request_context(
        f"/api/v1/sessions/{session_id}/events?after=not-an-int",
        headers={"Last-Event-ID": "also-bad"},
    ):
        response = stream_events(session_id)
        frames = _read_n_event_frames(response.response, 2)

    assert [_parse_frame(frame)["id"] for frame in frames] == event_ids
