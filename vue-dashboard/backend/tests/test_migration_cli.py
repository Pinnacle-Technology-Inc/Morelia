"""Integration test for the application-factory migration command."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, text

from app import create_app

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _head_revision() -> str:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(config).get_current_head()


def test_flask_db_upgrade_applies_head_to_fresh_database(tmp_path):
    database_url = URL.create("sqlite", database=str(tmp_path / "fresh.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": database_url},
    )

    result = app.test_cli_runner().invoke(args=["db", "upgrade"])

    assert result.exit_code == 0, result.output or repr(result.exception)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()

    # `flask db upgrade` applies the whole graph; assert against the current
    # head so new migrations don't require touching this test.
    assert revision == _head_revision()
