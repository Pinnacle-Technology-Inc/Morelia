"""Compact, token-free read-only diagnostic of one isolated acceptance run."""
import json
from pathlib import Path
import sqlite3
import sys

root = Path(sys.argv[1])
with sqlite3.connect(root / "stack.sqlite3") as db:
    db.row_factory = sqlite3.Row
    for table, fields in (("sessions", "id,status,started_at,ended_at"), ("operations", "command,state,details,error_code,error_message"), ("runtime_ownerships", "runtime_id,state,watchdog_id,watchdog_state,details")):
        try:
            print(table, json.dumps([dict(row) for row in db.execute(f"SELECT {fields} FROM {table}")], indent=2))
        except sqlite3.OperationalError as exc:
            print(exc)
for path in (root / "outboxes").glob("*.sqlite3"):
    with sqlite3.connect(path) as db:
        for kind, raw in db.execute("SELECT event_type,payload FROM outbox_reports WHERE event_type IN ('runtime.stop_requested','runtime.stop_finished')"):
            payload = json.loads(raw)
            print(path.name, kind, json.dumps({key: value for key, value in payload.items() if key not in {"shutdown_result", "recording_bounds"}}, indent=2))
