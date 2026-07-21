"""SSE live endpoint — GET /api/v1/sessions/<id>/events.

Each frame uses the backend_events autoincrement id as the SSE `id:` field,
making the cursor position durable across reconnects (7.7 replay builds on
this). The generator polls the DB at a configurable interval; a heartbeat
comment frame is emitted when no events arrive, keeping the connection alive
and allowing disconnect detection.

Registered directly on the Flask app (not the OpenAPI `api` object) because
the response type is `text/event-stream`, which falls outside the JSON-centric
OpenAPI spec.
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator

from flask import Blueprint, Response, current_app, request, stream_with_context
from flask_smorest import abort

from app.database import db
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository

blp = Blueprint("events_stream", __name__, url_prefix="/api/v1/sessions")

_BATCH_LIMIT = 50


def _parse_cursor(value: str | None) -> int | None:
    """Parse a non-negative SSE cursor; invalid values mean "no cursor"."""
    if value is None:
        return None
    try:
        cursor = int(value)
    except (TypeError, ValueError):
        return None
    if cursor < 0:
        return None
    return cursor


def _request_cursor() -> int:
    """Resolve the reconnect cursor from query or header.

    ``?after=`` is an explicit URL override and wins over the standard
    ``Last-Event-ID`` reconnect header. If neither parses, fall back to the
    original live stream behavior from cursor zero.
    """
    query_cursor = _parse_cursor(request.args.get("after"))
    if query_cursor is not None:
        return query_cursor
    header_cursor = _parse_cursor(request.headers.get("Last-Event-ID"))
    if header_cursor is not None:
        return header_cursor
    return 0


def _sse_generator(
    session_id: int,
    *,
    after_id: int = 0,
    poll_interval: float,
    heartbeat_interval: float,
) -> Generator[str, None, None]:
    """Core SSE generator — exposed at module level so tests can drive it directly.

    Yields SSE text frames (already encoded as str with the trailing blank line).
    Handles GeneratorExit (client disconnect) in a try/finally so callers that
    call gen.close() see a clean teardown with no leaked resources.
    """
    repo = BackendEventRepository()
    cursor = after_id
    last_hb = time.monotonic()

    try:
        while True:
            # expire_all() ensures each poll cycle starts a fresh DB read so
            # events committed by concurrent push/poll paths are visible.
            db.session.expire_all()
            rows = repo.since(session_id, after_id=cursor, limit=_BATCH_LIMIT)

            for row in rows:
                cursor = row.id
                yield (
                    f"id: {row.id}\n"
                    f"event: {row.event_type}\n"
                    f"data: {json.dumps(_event_payload(row))}\n\n"
                )

            now = time.monotonic()
            if now - last_hb >= heartbeat_interval:
                yield ": heartbeat\n\n"
                last_hb = now

            time.sleep(poll_interval)
    except GeneratorExit:
        pass  # client disconnected — generator exits cleanly


def _event_payload(row) -> dict:
    """Return the JSON body clients see for one backend event row."""
    payload = dict(row.payload or {})
    payload["sequence"] = row.sequence
    if row.phase is not None:
        payload["phase"] = row.phase
    if row.comms is not None:
        payload["comms"] = row.comms
    if row.recovery_id is not None:
        payload["recovery_id"] = row.recovery_id
    if row.runtime_id is not None:
        payload["runtime_id"] = row.runtime_id
    return payload


@blp.route("/<int:session_id>/events")
def stream_events(session_id: int):
    """Stream backend events for a session as Server-Sent Events.

    Frame format per SSE spec (https://html.spec.whatwg.org/multipage/server-sent-events.html):
        id: <backend_events.id>
        event: <event_type>
        data: <json payload>
        <blank line>

    The `id:` field doubles as the replay cursor for 7.7.
    """
    if SessionRepository().get(session_id) is None:
        abort(404, message=f"No session with id {session_id!r}.")

    poll_interval = current_app.config.get("SSE_POLL_INTERVAL", 2.0)
    heartbeat_interval = current_app.config.get("SSE_HEARTBEAT_INTERVAL", 15.0)

    return Response(
        stream_with_context(
            _sse_generator(
                session_id,
                after_id=_request_cursor(),
                poll_interval=poll_interval,
                heartbeat_interval=heartbeat_interval,
            )
        ),
        content_type="text/event-stream",
    )
