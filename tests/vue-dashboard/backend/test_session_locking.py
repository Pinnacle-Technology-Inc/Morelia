"""Persistence and concurrency guarantees for the per-dataflow in-flight lock.

The lock (``Session.command_in_flight``) must hold two properties that the
single-client tests in test_sessions.py cannot prove:

* It is **durable** — a value committed by one process is visible to a freshly
  built app instance (a simulated restart), because it lives in a column, not
  in memory.
* It is **atomic under concurrency** — two requests starting the *same* session
  at the same instant resolve to exactly one winner (202) and one
  ``CommandInFlight`` (423). The sequential ``test_start_twice_is_locked_423``
  would still pass even if the guard were a non-atomic read-then-write, so it
  cannot catch a reintroduced TOCTOU race. These do.

Both use a real on-disk SQLite file (not ``:memory:``) so state survives the
separate app instances and the separate per-thread sessions each test creates.
"""

import threading

from sqlalchemy import URL
from structlog.contextvars import bind_contextvars

import app.services.sessions as session_service
from app import create_app
from app.database import db
from app.domain.enums import DeviceType, SessionStatus
from app.domain.errors import CommandInFlight
from app.services.device_configs import create as create_device_config


def _app_on_file(db_path):
    """A fresh testing app bound to an on-disk SQLite file.

    Building a new instance against the same file is our stand-in for a process
    restart: nothing is shared in memory, so anything the next instance reads
    came from the database.
    """
    database_url = URL.create("sqlite", database=str(db_path))
    return create_app("testing", config_overrides={"SQLALCHEMY_DATABASE_URI": database_url})


def _make_session(app, **overrides):
    """Create a startable session and return its id."""
    with app.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="LOCK1",
            port="COM3",
            parameters={"preamp_gain": 10},
        )
        data = {
            "name": "lock-test",
            "device_flows": [
                {
                    "device_config_id": config.id,
                    "sink_type": "csv",
                    "sink_location": "C:/data/lock.csv",
                }
            ],
        }
        data.update(overrides)
        return session_service.create(data).id


def test_in_flight_lock_persists_across_restart(tmp_path):
    db_path = tmp_path / "locking.sqlite3"

    # --- process #1: build schema, create a session, lock it via start() ---
    app1 = _app_on_file(db_path)
    with app1.app_context():
        db.create_all()
    session_id = _make_session(app1)

    with app1.app_context():
        bind_contextvars(request_id="boot-1")
        started = session_service.start(session_id, app1.extensions["watchdog_adapter"])
        assert started.command_in_flight is True
        assert started.status == SessionStatus.STARTING

    # --- process #2: brand-new app, same file — the lock must be visible ---
    app2 = _app_on_file(db_path)
    with app2.app_context():
        reloaded = session_service.get(session_id)
        assert reloaded.command_in_flight is True
        assert reloaded.status == SessionStatus.STARTING
        # And a second start on the still-locked session is rejected.
        bind_contextvars(request_id="boot-2")
        try:
            session_service.start(session_id, app2.extensions["watchdog_adapter"])
            raise AssertionError("expected CommandInFlight on an already-locked session")
        except CommandInFlight:
            pass


def test_concurrent_start_has_exactly_one_winner(tmp_path):
    db_path = tmp_path / "race.sqlite3"
    app = _app_on_file(db_path)
    with app.app_context():
        db.create_all()
    session_id = _make_session(app)

    adapter = app.extensions["watchdog_adapter"]
    outcomes: dict[str, str] = {}
    unexpected: list[Exception] = []
    # Release both threads as close to simultaneously as the scheduler allows,
    # maximising overlap on the check-and-set.
    barrier = threading.Barrier(2)

    def attempt(tag: str) -> None:
        # Each thread is an independent unit of work: its own app context, its
        # own scoped session (scoped_session keys by thread), its own request_id.
        with app.app_context():
            bind_contextvars(request_id=f"req-{tag}")
            barrier.wait()
            try:
                session_service.start(session_id, adapter)
                outcomes[tag] = "won"
            except CommandInFlight:
                outcomes[tag] = "locked"
            except Exception as exc:  # noqa: BLE001 - surfaced via the list below
                unexpected.append(exc)
                outcomes[tag] = "error"

    threads = [threading.Thread(target=attempt, args=(tag,)) for tag in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not unexpected, f"a starter raised unexpectedly: {unexpected!r}"
    assert sorted(outcomes.values()) == ["locked", "won"], f"outcomes={outcomes}"

    # The committed end state matches the single winner: locked and STARTING.
    with app.app_context():
        final = session_service.get(session_id)
        assert final.command_in_flight is True
        assert final.status == SessionStatus.STARTING
