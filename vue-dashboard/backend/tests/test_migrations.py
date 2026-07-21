"""Migration tests: drive real Alembic upgrades/downgrades on temp databases.

These build the Alembic ``Config`` programmatically (no alembic.ini logging,
URL pointed at a throwaway file) so each test is isolated and exercises the
actual ``migrations/`` scripts and ``env.py`` wiring end to end.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def _alembic_config(db_path: Path) -> Config:
    """An Alembic Config pointed at a temporary on-disk SQLite database."""
    url = URL.create("sqlite", database=str(db_path)).render_as_string(hide_password=False)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _table_names(db_path: Path) -> set[str]:
    engine = create_engine(
        URL.create("sqlite", database=str(db_path)).render_as_string(hide_password=False)
    )
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _column_names(db_path: Path, table: str) -> set[str]:
    engine = create_engine(
        URL.create("sqlite", database=str(db_path)).render_as_string(hide_password=False)
    )
    try:
        return {column["name"] for column in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _current_version(db_path: Path) -> str | None:
    engine = create_engine(
        URL.create("sqlite", database=str(db_path)).render_as_string(hide_password=False)
    )
    try:
        if "alembic_version" not in inspect(engine).get_table_names():
            return None
        with engine.connect() as connection:
            # scalar_one_or_none: after a downgrade to base the table still
            # exists but holds no row.
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    finally:
        engine.dispose()


def test_fresh_database_upgrades_to_head_in_one_command(tmp_path):
    db_path = tmp_path / "fresh.sqlite3"
    config = _alembic_config(db_path)

    command.upgrade(config, "head")

    head = ScriptDirectory.from_config(config).get_current_head()
    assert _current_version(db_path) == head
    assert _table_names(db_path) == {
        "alembic_version",
        "backend_events",
        "device_configs",
        "device_seen",
        "device_registrations",
        "incidents",
        "session_templates",
        "operations",
        "output_files",
        "recovery_gaps",
        "runtime_ownerships",
        "runtime_manifests",
        "sessions",
    }
    assert "color" in _column_names(db_path, "device_configs")
    assert "claim_expires_at" in _column_names(db_path, "device_configs")
    assert "source_template_id" not in _column_names(db_path, "device_configs")
    assert "source_template_hash" in _column_names(db_path, "device_configs")


def test_downgrade_one_revision_then_reupgrade_preserves_schema(tmp_path):
    db_path = tmp_path / "roundtrip.sqlite3"
    config = _alembic_config(db_path)

    script = ScriptDirectory.from_config(config)
    command.upgrade(config, "head")
    head = script.get_current_head()
    schema_at_head = _table_names(db_path)
    assert _current_version(db_path) == head

    # Downgrade one revision and assert we land on head's immediate parent
    # (computed from the graph, not hardcoded, so adding a migration later
    # doesn't silently invalidate this test).
    expected_parent = script.get_revision(head).down_revision
    command.downgrade(config, "-1")
    assert _current_version(db_path) == expected_parent

    # Re-upgrading restores the identical revision and schema.
    command.upgrade(config, "head")
    assert _current_version(db_path) == head
    assert _table_names(db_path) == schema_at_head


def test_runtime_watchdog_identity_columns_present_at_head(tmp_path):
    db_path = tmp_path / "watchdog-identity.sqlite3"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    watchdog_columns = {
        "watchdog_id",
        "watchdog_token_hash",
        "watchdog_pid",
        "watchdog_state",
        "watchdog_outbox_path",
        "watchdog_last_seen_at",
        "watchdog_exit_details",
        "watchdog_control_port",
    }
    assert watchdog_columns <= _column_names(db_path, "runtime_ownerships")


def test_migration_repository_chains_lifecycle_onto_baseline():
    config = _alembic_config(Path(":memory:"))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())

    # walk_revisions yields newest-first; 0002 chains from the 0001 baseline.
    assert [revision.revision for revision in revisions] == ["0002", "0001"]
    assert script.get_current_head() == "0002"
    assert script.get_revision("0002").down_revision == "0001"


# ---------------------------------------------------------------------------
# Packet 10: output lifecycle + recovery boundary schema
# ---------------------------------------------------------------------------


def _execute(db_path: Path, statements):
    engine = create_engine(
        URL.create("sqlite", database=str(db_path)).render_as_string(hide_password=False)
    )
    try:
        with engine.begin() as connection:
            for statement, params in statements:
                connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


def _fetch_one(db_path: Path, query: str, params: dict | None = None):
    engine = create_engine(
        URL.create("sqlite", database=str(db_path)).render_as_string(hide_password=False)
    )
    try:
        with engine.connect() as connection:
            return connection.execute(text(query), params or {}).mappings().first()
    finally:
        engine.dispose()


def test_output_lifecycle_columns_present_at_head(tmp_path):
    db_path = tmp_path / "output-lifecycle.sqlite3"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    lifecycle_columns = {
        "logical_sink_id",
        "segment_index",
        "previous_output_id",
        "final_output_id",
        "acquisition_state",
        "artifact_state",
        "termination_reason",
        "delivery_state",
        "byte_loss",
        "sample_loss",
        "finalization_id",
        "finalizer_fence_token",
        "finalized_at",
    }
    assert lifecycle_columns <= _column_names(db_path, "output_files")


def test_recovery_gap_boundary_columns_present_at_head(tmp_path):
    db_path = tmp_path / "gap-boundary.sqlite3"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    boundary_columns = {
        "boundary_kind",
        "boundary_version",
        "output_id",
        "previous_output_id",
        "next_output_id",
        "pre_offset",
        "post_offset",
        "boundary_payload",
    }
    assert boundary_columns <= _column_names(db_path, "recovery_gaps")
    # Legacy offset columns must survive: record_boundary() still writes them.
    assert {"previous_segment_id", "next_segment_id"} <= _column_names(
        db_path, "recovery_gaps"
    )


def test_upgrade_backfills_logical_identity_for_existing_output(tmp_path):
    db_path = tmp_path / "upgrade-backfill.sqlite3"
    config = _alembic_config(db_path)

    # Land on the 0001 baseline and seed a pre-lifecycle output row.
    command.upgrade(config, "0001")
    _execute(
        db_path,
        [
            (
                "INSERT INTO output_files "
                "(output_id, session_id, dataflow_id, sink_type, path, status, "
                "byte_offset, row_offset) VALUES "
                "(:oid, NULL, :df, :st, :path, :status, 0, 0)",
                {
                    "oid": "legacy-out-1",
                    "df": "df-legacy",
                    "st": "csv",
                    "path": "/data/legacy-1.csv",
                    "status": "closed",
                },
            )
        ],
    )

    command.upgrade(config, "head")

    row = _fetch_one(
        db_path,
        "SELECT output_id, logical_sink_id, segment_index, acquisition_state, "
        "artifact_state, byte_loss, sample_loss, path "
        "FROM output_files WHERE output_id = :oid",
        {"oid": "legacy-out-1"},
    )
    assert row is not None, "existing output row must survive upgrade"
    # Each legacy output becomes the sole component of its own logical output.
    assert row["logical_sink_id"] == "legacy-out-1"
    assert row["segment_index"] == 0
    # A closed file maps to a completed acquisition; artifact needs no merge yet.
    assert row["acquisition_state"] == "complete"
    assert row["artifact_state"] == "not_required"
    assert row["byte_loss"] == 0
    assert row["sample_loss"] == 0
    assert row["path"] == "/data/legacy-1.csv"


def test_downgrade_preserves_output_and_gap_rows(tmp_path):
    db_path = tmp_path / "downgrade-preserve.sqlite3"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    _execute(
        db_path,
        [
            (
                "INSERT INTO output_files "
                "(output_id, logical_sink_id, segment_index, dataflow_id, "
                "sink_type, path, status, acquisition_state, artifact_state, "
                "byte_offset, row_offset, byte_loss, sample_loss) VALUES "
                "(:oid, :lsid, 0, :df, :st, :path, 'open', 'open', "
                "'not_required', 0, 0, 0, 0)",
                {
                    "oid": "out-2",
                    "lsid": "logical-2",
                    "df": "df-2",
                    "st": "csv",
                    "path": "/data/out-2.csv",
                },
            ),
            (
                "INSERT INTO recovery_gaps "
                "(gap_id, session_id, dataflow_id, reason, confidence, "
                "boundary_kind, output_id) VALUES "
                "(:gid, 1, :df, :reason, 'uncertain', 'segmented', :oid)",
                {
                    "gid": "gap-2",
                    "df": "df-2",
                    "reason": "reconnect",
                    "oid": "out-2",
                },
            ),
        ],
    )

    command.downgrade(config, "-1")

    # Rows (and their still-supported columns) survive the column drop.
    out_row = _fetch_one(
        db_path,
        "SELECT output_id, path, status FROM output_files WHERE output_id = :oid",
        {"oid": "out-2"},
    )
    assert out_row is not None
    assert out_row["path"] == "/data/out-2.csv"
    assert out_row["status"] == "open"

    gap_row = _fetch_one(
        db_path,
        "SELECT gap_id, reason FROM recovery_gaps WHERE gap_id = :gid",
        {"gid": "gap-2"},
    )
    assert gap_row is not None
    assert gap_row["reason"] == "reconnect"
    # The lifecycle columns are gone after downgrade.
    assert "logical_sink_id" not in _column_names(db_path, "output_files")
    assert "boundary_kind" not in _column_names(db_path, "recovery_gaps")
