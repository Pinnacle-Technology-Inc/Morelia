"""Read and export redacted, session-scoped diagnostic JSONL."""

from __future__ import annotations

import base64
import json
import re
from collections import defaultdict
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
_ROUTINE_POLL_ROUTE = re.compile(
    r"/(?:status|activity|notes|events|diagnostics(?:\.txt)?)$"
)
_HEALTH_FIELDS = frozenset(
    {"watchdog_status", "stream_status", "worker_status", "heartbeat_status"}
)
_HEALTHY_VALUES = frozenset({"ok", "healthy", "alive", "fresh"})
_ID_LABELS = {
    "runtime_id": ("Runtime", "letter"),
    "watchdog_id": ("Watchdog", "letter"),
    "operation_id": ("Operation", "number"),
    "command_id": ("Operation", "number"),
    "request_id": ("Request", "number"),
    "recovery_id": ("Recovery", "number"),
    "shutdown_id": ("Shutdown", "number"),
    "dataflow_id": ("Dataflow", "letter"),
    "incident_id": ("Incident", "number"),
    "activity_id": ("Activity", "number"),
    "source_id": ("Source", "letter"),
}
_HUMAN_METADATA_FIELDS = frozenset(
    {
        "event",
        "layer",
        "level",
        "logger",
        "pid",
        "session_id",
        "timestamp",
        "occurred_at",
        "created_at",
        "opened_at",
        "queued_at",
        "updated_at",
        "traceback",
        "exc_info",
        "stack_info",
    }
)


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


def export_text(session_id: int, *, root: str | None, view: str = "human") -> str:
    session = _require_session(session_id)
    records = [*_database_records(session_id), *_read_records(session_id, root=root)]
    if view == "verbose":
        return render_verbose(session_id, session.name, records)
    return render_human(session_id, session.name, records)


def render_verbose(
    session_id: int, session_name: str, records: list[dict[str, Any]]
) -> str:
    """Render the pre-existing raw JSONL export contract without reformatting."""
    lines = [
        "# Morelia session diagnostic log",
        f"# session_id={session_id}",
        f"# session_name={session_name}",
        f"# exported_at={datetime.now(UTC).isoformat()}",
        "# format=redacted JSON Lines; newest first",
    ]
    for record in records:
        lines.append(json.dumps(record, sort_keys=True, default=str))
    return "\n".join(lines) + "\n"


def render_human(
    session_id: int, session_name: str, records: list[dict[str, Any]]
) -> str:
    """Render loss-minimized, chronological diagnostics from raw telemetry."""
    chronological = sorted(records, key=_event_sort_key)
    included = _human_records(chronological)
    aliases = _AliasRegistry(included)
    lines = [
        "Morelia Session Diagnostics",
        f"Session {session_id} • {session_name}",
        f"Exported {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "View: Human",
        "",
    ]
    for record in included:
        lines.extend(_format_human_event(record, aliases))
        lines.append("")
    identifier_map = aliases.render_map()
    if identifier_map:
        lines.extend(["Identifier map", "─" * 32, *identifier_map, ""])
    return "\n".join(lines)


class _AliasRegistry:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._aliases: dict[str, str] = {}
        self._entries: list[tuple[str, str]] = []
        self._counters: dict[str, int] = defaultdict(int)
        command_by_id: dict[str, str] = {}
        for record in records:
            flattened = _flatten_record(record)
            command = _command_name(flattened)
            if not command:
                continue
            for key in ("operation_id", "command_id"):
                value = flattened.get(key)
                if isinstance(value, str) and value:
                    command_by_id[value] = command
        field_groups = (
            {"operation_id", "command_id"},
            {"watchdog_id"},
            {"runtime_id"},
            set(_ID_LABELS) - {"operation_id", "command_id", "watchdog_id", "runtime_id"},
        )
        for fields in field_groups:
            for record in records:
                flattened = _flatten_record(record)
                command = _command_name(flattened)
                for key, value in _walk_items(flattened):
                    if key in fields and isinstance(value, str) and value:
                        self._register(
                            key, value, command=command_by_id.get(value, command)
                        )

    def _register(self, key: str, value: str, *, command: str | None) -> None:
        if value in self._aliases:
            return
        base, style = _ID_LABELS[key]
        if key in {"operation_id", "command_id"} and command:
            base = command.title()
        self._counters[base] += 1
        index = self._counters[base]
        suffix = _letter(index) if style == "letter" else f"#{index}"
        alias = f"{base} {suffix}"
        self._aliases[value] = alias
        self._entries.append((alias, value))

    def get(self, value: object) -> str | None:
        return self._aliases.get(str(value)) if value is not None else None

    def replace(self, text: object) -> str:
        result = str(text)
        ordered_aliases = sorted(
            self._aliases.items(), key=lambda item: len(item[0]), reverse=True
        )
        for raw, alias in ordered_aliases:
            result = result.replace(raw, alias)
        return result

    def render_map(self) -> list[str]:
        if not self._entries:
            return []
        width = max(len(alias) for alias, _ in self._entries)
        return [
            f"{alias.ljust(width)}    {_short_id(raw)}" for alias, raw in self._entries
        ]


def _human_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    included: list[dict[str, Any]] = []
    healthy_by_subject: dict[tuple[object, ...], dict[str, str]] = {}
    logical_events: set[tuple[str, str, str]] = set()
    for record in records:
        flattened = _flatten_record(record)
        if _is_routine_successful_poll(flattened):
            continue
        if _is_repeated_healthy_state(flattened, healthy_by_subject):
            continue
        fingerprint = _logical_fingerprint(flattened)
        if fingerprint is not None:
            if fingerprint in logical_events:
                continue
            logical_events.add(fingerprint)
        included.append(record)
    return included


def _is_routine_successful_poll(record: dict[str, Any]) -> bool:
    if str(record.get("http_method") or "").upper() != "GET":
        return False
    route = str(record.get("http_route") or "").rstrip("/")
    if not _ROUTINE_POLL_ROUTE.search(route):
        return False
    event = str(record.get("event") or "")
    if event == "http_request_started":
        return True
    status = record.get("status_code")
    return event == "http_request_completed" and isinstance(status, int) and 200 <= status < 300


def _is_repeated_healthy_state(
    record: dict[str, Any],
    previous: dict[tuple[object, ...], dict[str, str]],
) -> bool:
    states = {
        key: str(value).lower()
        for key, value in record.items()
        if key in _HEALTH_FIELDS and value is not None
    }
    if not states:
        return False
    subject = (
        record.get("watchdog_id"),
        record.get("runtime_id"),
        record.get("device_id"),
        record.get("source_id"),
        record.get("stream_index"),
        record.get("layer"),
    )
    prior = previous.get(subject)
    previous[subject] = states
    return prior == states and all(value in _HEALTHY_VALUES for value in states.values())


def _logical_fingerprint(record: dict[str, Any]) -> tuple[str, str, str] | None:
    if str(record.get("level") or "").lower() in {"error", "critical"} or any(
        record.get(key) for key in ("error", "exception", "traceback", "exc_info")
    ):
        return None
    event = str(record.get("event") or "")
    if event in {"session_activity_committed", "database.activity"}:
        identity = record.get("operation_id") or record.get("activity_id")
        action = record.get("action") or record.get("kind")
        if identity and action:
            return ("activity", str(identity), str(action))
    operation_id = record.get("operation_id") or record.get("command_id")
    command = _command_name(record)
    if not operation_id or not command:
        return None
    stage = None
    state = str(record.get("state") or "").lower()
    if event == "database.operation":
        stage = {
            "queued": "requested",
            "running": "started",
            "succeeded": "succeeded",
            "failed": "failed",
        }.get(state)
    elif "command_started" in event:
        stage = "started"
    elif "command_requested" in event:
        stage = "requested"
    elif "command_failed" in event or event == "runtime command failed":
        stage = "failed"
    elif "command_confirmed" in event:
        stage = str(record.get("outcome") or "succeeded")
    return ("operation", str(operation_id), f"{command}.{stage}") if stage else None


def _format_human_event(record: dict[str, Any], aliases: _AliasRegistry) -> list[str]:
    values = _flatten_record(record)
    timestamp = _format_timestamp(_event_timestamp(values))
    subject = _human_subject(values, aliases)
    level = str(values.get("level") or "info").upper()
    level_text = f"  {level}" if level not in {"INFO", ""} else ""
    lines = [f"{timestamp}  {subject}{level_text}", f"  {_event_message(values, aliases)}"]

    missing_phases = values.get("missing_phases")
    exception_lines = _format_exception(values, aliases)
    omitted = _HUMAN_METADATA_FIELDS | {"record", "missing_phases", "message", "error", "exception"}
    for key, value in values.items():
        if key in omitted or value is None:
            continue
        if key in _ID_LABELS:
            continue
        lines.extend(_format_detail(key, value, aliases))
    if isinstance(missing_phases, (list, tuple)) and missing_phases:
        lines.extend(["", "  Missing phases:"])
        lines.extend(f"    {aliases.replace(phase)}" for phase in missing_phases)
    if exception_lines:
        lines.extend(["", *exception_lines])
    return lines


def _human_subject(record: dict[str, Any], aliases: _AliasRegistry) -> str:
    layer = str(record.get("layer") or "").lower()
    watchdog = aliases.get(record.get("watchdog_id"))
    if "watchdog" in layer and watchdog:
        return watchdog.upper()
    if "runtime" in layer:
        return "RUNTIME"
    if "worker" in layer:
        return "WORKER"
    if "stream" in layer:
        return "STREAM"
    if "control" in layer or layer == "database":
        return "CONTROL"
    return (layer or "diagnostic").replace("-", " ").upper()


def _event_message(record: dict[str, Any], aliases: _AliasRegistry) -> str:
    event = str(record.get("event") or "diagnostic_record")
    if event in {"session_activity_committed", "database.activity"}:
        action = record.get("action") or record.get("kind")
        if action:
            return aliases.replace(str(action).replace(".", " ").replace("_", " "))
    operation = aliases.get(record.get("command_id") or record.get("operation_id"))
    if operation:
        if event == "database.operation" and record.get("state"):
            return f"{operation} {str(record['state']).replace('_', ' ')}"
        if "accepted" in event:
            return f"{operation} accepted"
        if "confirmed" in event:
            outcome = str(record.get("outcome") or "completed")
            return f"{operation} {('completed' if outcome == 'succeeded' else outcome)}"
        if "failed" in event:
            return f"{operation} failed"
        if "requested" in event:
            return f"{operation} requested"
    return aliases.replace(event.replace("_", " "))


def _format_detail(key: str, value: object, aliases: _AliasRegistry) -> list[str]:
    if isinstance(value, dict):
        rendered = json.dumps(_alias_value(value, aliases), indent=2, sort_keys=True, default=str)
        return [f"  {key}:", *(f"    {line}" for line in rendered.splitlines())]
    if isinstance(value, (list, tuple)):
        return [f"  {key}:", *(f"    - {aliases.replace(item)}" for item in value)]
    return [f"  {key}={aliases.replace(value)}"]


def _format_exception(record: dict[str, Any], aliases: _AliasRegistry) -> list[str]:
    traceback_text = record.get("traceback") or record.get("exc_info")
    error_type = record.get("error") or record.get("exception_type")
    exception = record.get("exception")
    if not traceback_text and isinstance(exception, str) and "Traceback" in exception:
        traceback_text = exception
        exception = None
        final_line = next(
            (line.strip() for line in reversed(str(traceback_text).splitlines()) if line.strip()),
            "",
        )
        parsed_error = re.match(r"([\w.]+(?:Error|Exception)):\s*(.*)", final_line)
        if parsed_error:
            error_type = error_type or parsed_error.group(1)
            exception = parsed_error.group(2)
    message = record.get("message") or exception
    if not traceback_text and not error_type and not message:
        return []
    lines: list[str] = []
    if error_type and message:
        lines.append(f"  {aliases.replace(error_type)}: {aliases.replace(message)}")
    elif message:
        lines.append(f"  {aliases.replace(message)}")
    elif error_type:
        lines.append(f"  {aliases.replace(error_type)}")
    if not traceback_text:
        return lines
    source_lines = str(traceback_text).splitlines()
    for index, line in enumerate(source_lines):
        match = re.match(r'\s*File "([^"]+)", line (\d+)(?:, in .*)?$', line)
        if not match:
            continue
        filename = match.group(1).replace("\\", "/").rsplit("/", 1)[-1]
        lines.extend(["", f"  {filename}:{match.group(2)}"])
        if index + 1 < len(source_lines):
            code = source_lines[index + 1].strip()
            if code and not code.startswith("File "):
                lines.append(f"    {aliases.replace(code)}")
    return lines


def _flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    nested = record.get("record")
    return {**record, **nested} if isinstance(nested, dict) else dict(record)


def _walk_items(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk_items(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_items(item)


def _alias_value(value: object, aliases: _AliasRegistry) -> object:
    if isinstance(value, dict):
        return {
            key: _alias_value(item, aliases)
            for key, item in value.items()
            if key not in {"session_id", "dataflow_id"}
        }
    if isinstance(value, list):
        return [_alias_value(item, aliases) for item in value]
    return aliases.replace(value)


def _command_name(record: dict[str, Any]) -> str | None:
    command = record.get("command")
    if isinstance(command, str) and command:
        return command.replace("_", " ")
    searchable = " ".join(
        str(record.get(key) or "") for key in ("event", "action", "kind", "title")
    ).lower()
    for candidate in ("forced stop", "restart", "recover", "stop", "start"):
        if candidate in searchable:
            return candidate
    return None


def _event_timestamp(record: dict[str, Any]) -> object:
    for key in (
        "timestamp",
        "occurred_at",
        "created_at",
        "opened_at",
        "queued_at",
        "updated_at",
    ):
        if record.get(key) is not None:
            return record[key]
    return ""


def _event_sort_key(record: dict[str, Any]) -> str:
    value = _event_timestamp(_flatten_record(record))
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed is not None else str(value or "")


def _format_timestamp(value: object) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return str(value or "Time unavailable")
    return parsed.strftime("%H:%M:%S.%f")[:-3]


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _short_id(value: str) -> str:
    return f"{value[:8]}…" if len(value) > 8 else value


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
                "operation_id", "incident_id", "recovery_id", "reason",
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
