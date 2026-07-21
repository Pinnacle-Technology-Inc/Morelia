"""Concurrency test: one writer and several readers share a WAL database.

SQLite in WAL mode lets readers keep reading a consistent snapshot while a
writer commits. This test runs a writer thread alongside reader threads against
a real on-disk database and asserts nobody errors out, no read ever sees
corrupt/partial data, and the file passes an integrity check afterward.
"""

import threading

from sqlalchemy import URL, text

from app import create_app
from app.database import db

WRITES = 100
READER_COUNT = 4


def test_wal_supports_one_writer_with_concurrent_readers(tmp_path):
    database_url = URL.create("sqlite", database=str(tmp_path / "concurrency.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            # A generous busy timeout so transient lock contention waits rather
            # than raising "database is locked".
            "SQLITE_BUSY_TIMEOUT_MS": 5_000,
        },
    )

    # Grab the Engine inside an app context, then share it across threads. The
    # Engine (and its connection pool) is thread-safe; reusing it avoids needing
    # a Flask app context inside every worker thread.
    with app.app_context():
        engine = db.engine

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE counter (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)"
        )
        conn.exec_driver_sql("INSERT INTO counter (id, value) VALUES (1, 0)")
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"

    errors: list[Exception] = []
    reads: list[int] = []
    stop = threading.Event()
    # Release writer + readers simultaneously to maximise overlap.
    start = threading.Barrier(READER_COUNT + 1)

    def writer() -> None:
        try:
            start.wait()
            for value in range(1, WRITES + 1):
                with engine.begin() as conn:
                    conn.execute(
                        text("UPDATE counter SET value = :value WHERE id = 1"),
                        {"value": value},
                    )
        except Exception as exc:  # noqa: BLE001 - surfaced via the errors list
            errors.append(exc)
        finally:
            stop.set()

    def reader() -> None:
        try:
            start.wait()
            while not stop.is_set():
                with engine.connect() as conn:
                    value = conn.exec_driver_sql(
                        "SELECT value FROM counter WHERE id = 1"
                    ).scalar_one()
                # A reader must always see a committed integer in range — never
                # NULL, a missing row, or a half-applied write.
                assert value is not None and 0 <= value <= WRITES
                reads.append(value)
        except Exception as exc:  # noqa: BLE001 - surfaced via the errors list
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(READER_COUNT)]
    threads.append(threading.Thread(target=writer))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"concurrent workers raised: {errors!r}"
    assert reads, "readers never observed the database during the write"

    with engine.connect() as conn:
        final = conn.exec_driver_sql("SELECT value FROM counter WHERE id = 1").scalar_one()
        integrity = conn.exec_driver_sql("PRAGMA integrity_check").scalar_one()

    assert final == WRITES
    assert integrity == "ok"
