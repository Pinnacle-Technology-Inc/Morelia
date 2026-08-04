"""Integration tests for the atomic transaction helper.

These tests exercise real ``db.session`` transaction boundaries against a
temporary SQLite file — no mocks — so they prove the actual commit/rollback
behaviour services will rely on.
"""

import pytest
from sqlalchemy import URL, text
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.database import db, transaction


def _app_with_file_db(tmp_path):
    """Build a testing app backed by a real on-disk SQLite file.

    A file (rather than ``:memory:``) keeps the schema we create visible across
    the separate transactions each test runs.
    """
    database_url = URL.create("sqlite", database=str(tmp_path / "transactions.sqlite3"))
    return create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": database_url},
    )


def test_transaction_commits_when_the_block_succeeds(tmp_path):
    app = _app_with_file_db(tmp_path)

    with app.app_context():
        db.session.execute(
            text("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
        )
        db.session.commit()

        with transaction():
            db.session.execute(text("INSERT INTO widget (id, name) VALUES (1, 'alpha')"))
            db.session.execute(text("INSERT INTO widget (id, name) VALUES (2, 'beta')"))

        count = db.session.execute(text("SELECT COUNT(*) FROM widget")).scalar_one()
        assert count == 2


def test_transaction_rolls_back_all_writes_when_one_fails(tmp_path):
    app = _app_with_file_db(tmp_path)

    with app.app_context():
        db.session.execute(
            text("CREATE TABLE widget (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
        )
        db.session.commit()

        # The second insert violates the UNIQUE constraint. All-or-nothing means
        # the *first* (valid) insert must be rolled back too.
        with pytest.raises(IntegrityError), transaction():
            db.session.execute(text("INSERT INTO widget (id, name) VALUES (1, 'dup')"))
            db.session.execute(text("INSERT INTO widget (id, name) VALUES (2, 'dup')"))

        count = db.session.execute(text("SELECT COUNT(*) FROM widget")).scalar_one()
        assert count == 0


def test_transaction_reraises_the_original_error(tmp_path):
    app = _app_with_file_db(tmp_path)

    with app.app_context():

        class Boom(RuntimeError):
            pass

        with pytest.raises(Boom), transaction():
            raise Boom("service failed mid-operation")
