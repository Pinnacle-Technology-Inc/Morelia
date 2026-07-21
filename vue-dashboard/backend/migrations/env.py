"""Alembic environment for the Guarded Experiment backend.

This wiring keeps two foundation rules intact:

* The database URL is resolved at runtime, never hardcoded. Precedence is an
  explicit override (``-x dburl=...`` on the CLI, or ``sqlalchemy.url`` set
  programmatically by tests) first, then the Flask application config.
* SQLite migrations run with batch mode enabled, because SQLite cannot ALTER
  most table constraints in place; Alembic's "batch" mode rewrites the table.
"""

from logging.config import fileConfig

from alembic import context
from flask import current_app, has_app_context
from sqlalchemy import create_engine

from app.database import Base, db

# The Alembic Config object provides access to values in alembic.ini.
config = context.config

# Interpret the config file for Python logging (set up loggers).
#
# `disable_existing_loggers=False` is load-bearing: fileConfig() defaults to
# True, which disables every logger that already exists but is not declared in
# alembic.ini. When a migration runs in-process (Flask CLI, tests, or a future
# migrate-on-boot path), that silently mutes the application's own loggers —
# notably the module-level "watchdog" logger created at import time. Opting out
# keeps Alembic from reconfiguring loggers it does not own.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Target metadata drives autogenerate. Domain models register themselves on
# this shared Base as downstream tasks add them.
target_metadata = Base.metadata


def _flask_migrate_extension():
    """Return Flask-Migrate state when invoked through the Flask CLI."""
    if not has_app_context():
        return None
    return current_app.extensions.get("migrate")


def _resolve_database_url() -> str:
    """Resolve the database URL without hardcoding a machine path.

    Order of precedence:
      1. ``-x dburl=...`` passed on the alembic command line.
      2. ``sqlalchemy.url`` set on the Config (used by tests).
      3. The Flask application's configured ``SQLALCHEMY_DATABASE_URI``.
    """
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("dburl"):
        return x_args["dburl"]

    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured

    migrate_extension = _flask_migrate_extension()
    if migrate_extension is not None:
        return migrate_extension.db.engine.url.render_as_string(hide_password=False)

    # Import lazily so direct Alembic commands can still resolve app config.
    from app import create_app

    app = create_app(config_overrides={"STARTUP_RECONCILIATION_ENABLED": False})
    with app.app_context():
        return db.engine.url.render_as_string(hide_password=False)


def _configure_args() -> dict:
    """Use Flask-Migrate options or equivalent direct-Alembic defaults."""
    migrate_extension = _flask_migrate_extension()
    if migrate_extension is not None:
        return dict(migrate_extension.configure_args)
    return {"compare_type": True, "render_as_batch": True}


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI needed)."""
    context.configure(
        url=_resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_args(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    migrate_extension = _flask_migrate_extension()
    connectable = (
        migrate_extension.db.engine
        if migrate_extension is not None
        else create_engine(_resolve_database_url())
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **_configure_args(),
        )

        with context.begin_transaction():
            context.run_migrations()

    if migrate_extension is None:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
