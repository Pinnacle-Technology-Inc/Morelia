"""Integration tests for application-factory database configuration."""

import pytest
from sqlalchemy import URL
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.database import db


def test_testing_profile_initializes_sqlalchemy_with_in_memory_sqlite():
    app = create_app("testing")

    with app.app_context():
        assert db.engine.url.drivername == "sqlite"
        assert db.engine.url.database == ":memory:"


def test_factory_applies_database_override_before_sqlalchemy_initialization(tmp_path):
    database_url = URL.create("sqlite", database=str(tmp_path / "override.sqlite3"))

    app = create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": database_url},
    )

    with app.app_context():
        assert db.engine.url == database_url


def test_sqlite_safety_pragmas_apply_to_every_new_connection(tmp_path):
    database_url = URL.create("sqlite", database=str(tmp_path / "pragmas.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "SQLITE_BUSY_TIMEOUT_MS": 250,
        },
    )

    with (
        app.app_context(),
        db.engine.connect() as first,
        db.engine.connect() as second,
    ):
        for connection in (first, second):
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()

            assert foreign_keys == 1
            assert journal_mode == "wal"
            assert busy_timeout == 250


def test_sqlite_rejects_foreign_key_violations(tmp_path):
    database_url = URL.create("sqlite", database=str(tmp_path / "foreign-keys.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": database_url},
    )

    with app.app_context(), db.engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            """
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent (id)
            )
            """
        )

        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("INSERT INTO child (id, parent_id) VALUES (1, 999)")
