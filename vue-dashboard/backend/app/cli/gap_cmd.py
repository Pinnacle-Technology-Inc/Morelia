"""Online recovery-gap CLI commands backed by the daemon API."""

from __future__ import annotations

import click

from app.cli.daemon_client import DaemonClient, DaemonError, DaemonUnavailable
from app.cli.output import echo_table, exit_with_error

_GAP_LIST_HEADERS = (
    "gap_id",
    "device_id",
    "confidence",
    "reason",
    "incident_id",
    "recovery_id",
    "created_at",
)


@click.group(name="gap")
def gap() -> None:
    """Inspect recovery output-continuity gaps."""


@gap.command(name="list")
@click.option(
    "--session",
    "session_id",
    type=int,
    required=True,
    help="Session id to list gaps for.",
)
def list_command(session_id: int) -> None:
    """List recovery gaps for a session from the daemon."""
    try:
        response = DaemonClient().get(f"/api/v1/gaps?session={session_id}")
        if not isinstance(response, list):
            raise DaemonError("Invalid daemon response", "Gap list response must be a list.")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    if not response:
        click.echo("no gaps")
        return
    echo_table(response, _GAP_LIST_HEADERS)


__all__ = ["gap", "list_command"]
