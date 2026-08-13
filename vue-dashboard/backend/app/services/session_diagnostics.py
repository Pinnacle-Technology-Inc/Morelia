"""Read and export redacted, session-scoped diagnostic JSONL."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.database import db
from app.domain.errors import SessionNotFound
from app.models.incident import Incident
from app.models.operation import Operation
from app.models.recovery_gap import RecoveryGap
from app.models.session_activity_entry import SessionActivityEntry
from app.repositories.sessions import SessionRepository

_sessions = SessionRepository()
_MAX_LINE_BYTES = 256 * 1024


def list_page(
    session_id: int,
    *,
    root: str | None,
    page_size: int,
    cursor: str | None = None,
) -> dict[str, object]:
    _require_session(session_id)
    offset = _decode_cursor(cursor, session_id=session_id) if cursor else 0
    records = _read_records(session_id, root=root)
    page = records[offset : offset + page_size]
    next_offset = offset + len(page)
    has_more = next_offset < len(records)
    return {
        "items": page,
        "has_more": has_more,
        "next_cursor": (
            _encode_cursor(session_id=session_id, offset=next_offset)
            if has_more
            else None
        ),
    }


def export_text(session_id: int, *, root: str | None) -> str:
    session = _require_session(session_id)
    lines = [
        "# Morelia session diagnostic log",
        f"# session_id={session_id}",
        f"# session_name={session.name}",
        f"# exported_at={datetime.now(UTC).isoformat()}",
        "# format=redacted JSON Lines; newest first",
    ]
    for record in _database_records(session_id):
        lines.append(json.dumps(record, sort_keys=True, default=str))
    for record in _read_records(session_id, root=root):
        lines.append(json.dumps(record, sort_keys=True, default=str))
    return "\n".join(lines) + "\n"


def _require_session(session_id: int):
    session = _sessions.get(session_id)
    if session is None:
        raise SessionNotFound(session_id)
    return session


def _read_records(session_id: int, *, root: str | None) -> list[dict[str, Any]]:
    if not root:
        return []
    folder = Path(root) / f"session-{session_id}"
    if not folder.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.jsonl")):
        try:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    if not line.strip() or len(line.encode("utf-8")) > _MAX_LINE_BYTES:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if record.get("session_id") != session_id:
                        continue
                    record.setdefault("layer", path.stem)
                    records.append(record)
        except OSError:
            continue
    return sorted(
        records,
        key=lambda record: str(record.get("timestamp") or ""),
        reverse=True,
    )


def _database_records(session_id: int) -> list[dict[str, Any]]:
    """Add durable facts so an export is useful even after process log loss."""
    selections = (
        (
            "activity",
            SessionActivityEntry,
            SessionActivityEntry.occurred_at,
            (
                "activity_id", "kind", "category", "severity", "title", "summary",
                "source_type", "source_id", "operation_id", "incident_id", "gap_id",
                "command_id", "recovery_id", "occurred_at", "created_at",
            ),
        ),
        (
            "operation",
            Operation,
            Operation.created_at,
            (
                "operation_id", "request_key", "dataflow_id", "scope", "command",
                "target_device_id", "request_id", "command_id", "watchdog_id",
                "recovery_id", "runtime_id", "state", "queued_at", "claimed_at",
                "dispatched_at", "running_at", "verifying_at", "finished_at",
                "error_code", "error_message", "resolved_by", "resolved_at",
                "resolution_note", "created_at", "updated_at",
            ),
        ),
        (
            "issue",
            Incident,
            Incident.opened_at,
            (
                "incident_id", "dataflow_id", "device_id", "sink_id", "runtime_id",
                "operation_id", "recovery_id", "status", "reason", "policy",
                "opened_at", "acknowledged_at", "acknowledged_by",
                "acknowledgement_note", "resolved_at", "resolution",
            ),
        ),
        (
            "gap",
            RecoveryGap,
            RecoveryGap.created_at,
            (
                "gap_id", "dataflow_id", "device_id", "sink_id", "output_id",
                "runtime_id", "operation_id", "incident_id", "recovery_id", "reason",
                "gap_start", "gap_end", "boundary_kind", "confidence", "created_at",
            ),
        ),
    )
    records: list[dict[str, Any]] = []
    for record_type, model, order_column, allowed_fields in selections:
        rows = db.session.scalars(
            db.select(model)
            .where(model.session_id == session_id)
            .order_by(order_column.desc(), model.id.desc())
        ).all()
        for row in rows:
            # Explicit allowlist: arbitrary ``details`` JSON can originate in
            # driver/API payloads and must never hitch a ride into a support
            # bundle. Every included field is bounded operational metadata.
            values = {name: getattr(row, name) for name in allowed_fields}
            records.append(
                {
                    "layer": "control-plane-db",
                    "event": f"database.{record_type}",
                    "session_id": session_id,
                    "record": values,
                }
            )
    return records


def _encode_cursor(*, session_id: int, offset: int) -> str:
    raw = json.dumps(
        {"v": 1, "k": "session-diagnostics", "session": session_id, "offset": offset},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, session_id: int) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if (
            payload.get("v") != 1
            or payload.get("k") != "session-diagnostics"
            or payload.get("session") != session_id
        ):
            raise ValueError
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError
        return offset
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid session diagnostics cursor") from exc
