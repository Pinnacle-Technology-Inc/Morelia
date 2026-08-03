"""Guarded local output-reconciliation commands."""

from __future__ import annotations

import click

from app.cli.output import echo_json, exit_with_error
from app.database import create_database_app
from app.services.output_finalization import (
    OutputReconciliationRefused,
    reconcile_stopped_session_outputs,
)


@click.group(name="output")
def output() -> None:
    """Inspect and repair durable output-finalization metadata."""


@output.command(name="reconcile")
@click.option("--session", "session_id", type=click.IntRange(min=1), required=True)
@click.option("--dry-run", is_flag=True, help="Preview safe repairs without writing.")
@click.option("--apply", "apply_changes", is_flag=True, help="Apply the reported repairs.")
def reconcile_command(session_id: int, dry_run: bool, apply_changes: bool) -> None:
    """Repair superseded open components for one stopped session."""
    if dry_run and apply_changes:
        raise click.UsageError("--dry-run and --apply are mutually exclusive")

    app = create_database_app()
    try:
        with app.app_context():
            report = reconcile_stopped_session_outputs(
                session_id,
                apply=apply_changes,
            )
    except (KeyError, OutputReconciliationRefused) as exc:
        exit_with_error(exc)
    echo_json(report)


__all__ = ["output", "reconcile_command"]
