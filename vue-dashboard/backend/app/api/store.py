"""In-memory session store — PLACEHOLDER.

Real persistence is SQLite (a later task). This dict-backed store exists only so
the reference endpoints can demonstrate the API conventions end to end. It is
attached per-app (``app.extensions``) so each test gets its own isolated store.

Note where the auto-generated name lives: HERE, in the construction layer — not
in the schema. The schema's job is to validate input; inventing a default name
needs the new id, which only exists at construction time. (Decision B.)
"""

import itertools
from datetime import UTC, datetime

from app.domain.enums import SessionStatus


class InMemorySessionStore:
    def __init__(self):
        self._items: dict[str, dict] = {}
        self._ids = itertools.count(1)

    def create(self, data: dict) -> dict:
        sid = str(next(self._ids))
        session = {
            "id": sid,
            "name": data["name"] or f"Session {sid}",  # auto-name when not given
            "status": SessionStatus.DRAFT,
            "policy": data["policy"],
            "experiment_id": data["experiment_id"],
            "schedule": data["schedule"],
            "device_flows": data["device_flows"],
            # Internal flag (not in any schema, so never serialized): models the
            # one-state-changing-command-at-a-time lock.
            "command_in_flight": False,
            "command_id": None,
            "dataflow_id": None,
            "watchdog_id": None,
            "created_at": datetime.now(UTC),
        }
        self._items[sid] = session
        return session

    def get(self, sid: str) -> dict | None:
        return self._items.get(sid)

    def all(self) -> list[dict]:
        return list(self._items.values())

    def delete(self, sid: str) -> None:
        self._items.pop(sid, None)
