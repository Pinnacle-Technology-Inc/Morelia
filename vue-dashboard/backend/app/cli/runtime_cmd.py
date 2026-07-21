"""Online runtime CLI commands backed by the daemon API."""

from __future__ import annotations

import click

from app.cli.daemon_client import DaemonClient, DaemonError, DaemonUnavailable
from app.cli.output import echo_json, echo_table, exit_with_error

_RUNTIME_LIST_HEADERS = (
    "runtime_id",
    "session_id",
    "dataflow_id",
    "state",
    "pid",
    "port",
    "last_seen_at",
)


@click.group(name="runtime")
def runtime() -> None:
    """Inspect and reconcile daemon runtime ownership."""


@runtime.command(name="list")
def list_command() -> None:
    """List active runtime ownership rows from the daemon."""
    try:
        response = DaemonClient().get("/api/v1/runtimes/")
        if not isinstance(response, list):
            raise DaemonError("Invalid daemon response", "Runtime list response must be a list.")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    if not response:
        click.echo("no runtimes")
        return
    echo_table(response, _RUNTIME_LIST_HEADERS)


@runtime.command(name="reconcile")
def reconcile_command() -> None:
    """Trigger startup reconciliation through the daemon."""
    try:
        response = DaemonClient().post("/api/v1/runtimes/reconcile", {})
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    echo_json(response)


__all__ = ["list_command", "reconcile_command", "runtime"]
