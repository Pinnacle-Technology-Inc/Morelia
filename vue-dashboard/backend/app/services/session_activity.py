"""Durable operator Activity and its live notification contract."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import structlog

from app.database import transaction
from app.domain.errors import SessionNotFound
from app.models.session_activity_entry import SessionActivityEntry
from app.repositories.backend_events import BackendEventRepository
from app.repositories.session_activity_entries import SessionActivityEntryRepository
from app.repositories.sessions import SessionRepository

_activity = SessionActivityEntryRepository()
_events = BackendEventRepository()
_sessions = SessionRepository()
_log = structlog.get_logger(__name__)


def serialize_entry(row: SessionActivityEntry) -> dict[str, object]:
    """Stable SSE representation shared with the JSON API schema."""
    return {
        "activity_id": row.activity_id,
        "session_id": row.session_id,
        "dataflow_id": row.dataflow_id,
        "kind": row.kind,
        "category": row.category,
        "severity": row.severity,
        "title": row.title,
        "summary": row.summary,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "operation_id": row.operation_id,
        "incident_id": row.incident_id,
        "gap_id": row.gap_id,
        "command_id": row.command_id,
        "recovery_id": row.recovery_id,
        "details": row.details,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def record(
    *,
    session_id: int,
    dataflow_id: str | None,
    kind: str,
    category: str,
    severity: str,
    title: str,
    summary: str,
    source_type: str,
    source_id: str,
    event_type: str = "activity.recorded",
    event_payload: Mapping[str, Any] | None = None,
    operation_id: str | None = None,
    incident_id: str | None = None,
    gap_id: str | None = None,
    command_id: str | None = None,
    recovery_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
    commit: bool = True,
) -> SessionActivityEntry:
    """Persist one Activity fact and its SSE notification in one transaction."""

    def persist() -> SessionActivityEntry:
        entry = _activity.create(
            session_id=session_id,
            dataflow_id=dataflow_id,
            kind=kind,
            category=category,
            severity=severity,
            title=title,
            summary=summary,
            source_type=source_type,
            source_id=source_id,
            operation_id=operation_id,
            incident_id=incident_id,
            gap_id=gap_id,
            command_id=command_id,
            recovery_id=recovery_id,
            details=details,
            occurred_at=occurred_at,
            commit=False,
        )
        payload = dict(event_payload or {})
        payload["activity"] = serialize_entry(entry)
        _events.append(
            event_type=event_type,
            session_id=session_id,
            dataflow_id=dataflow_id or f"session-{session_id}",
            payload=payload,
            runtime_id=None,
            watchdog_id=None,
            report_id=entry.activity_id,
            recovery_id=recovery_id,
            commit=False,
        )
        _log.info(
            "session_activity_committed",
            session_id=session_id,
            dataflow_id=dataflow_id,
            operation_id=operation_id,
            incident_id=incident_id,
            gap_id=gap_id,
            command_id=command_id,
            recovery_id=recovery_id,
            action=kind,
            outcome=severity,
        )
        return entry

    if not commit:
        return persist()
    with transaction():
        return persist()


def list_page(
    session_id: int, *, page_size: int, cursor: str | None
) -> dict[str, object]:
    if _sessions.get(session_id) is None:
        raise SessionNotFound(session_id)
    after = _decode_cursor(cursor, session_id=session_id) if cursor else None
    rows, has_more = _activity.list_page(
        session_id=session_id, page_size=page_size, after=after
    )
    return {
        "items": rows,
        "has_more": has_more,
        "next_cursor": (
            _encode_cursor(session_id=session_id, row=rows[-1])
            if has_more and rows
            else None
        ),
    }


def _encode_cursor(*, session_id: int, row: SessionActivityEntry) -> str:
    payload = {
        "v": 1,
        "k": "session-activity",
        "session": session_id,
        "t": row.occurred_at.isoformat(),
        "id": row.id,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, session_id: int) -> tuple[datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if (
            payload.get("v") != 1
            or payload.get("k") != "session-activity"
            or payload.get("session") != session_id
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(payload["t"])
        row_id = int(payload["id"])
        if row_id <= 0:
            raise ValueError
        return timestamp, row_id
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid session activity cursor") from exc
