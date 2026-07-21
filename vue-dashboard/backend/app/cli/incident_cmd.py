"""Online incident CLI commands backed by the daemon API."""

from __future__ import annotations

import click

from app.cli.daemon_client import DaemonClient, DaemonError, DaemonUnavailable
from app.cli.output import echo_json, echo_table, exit_with_error

_INCIDENT_LIST_HEADERS = (
    "incident_id",
    "status",
    "device_id",
    "reason",
    "opened_at",
    "recovery_id",
)


@click.group(name="incident")
def incident() -> None:
    """Inspect and acknowledge operator-facing incidents."""


@incident.command(name="list")
@click.option(
    "--session",
    "session_id",
    type=int,
    required=True,
    help="Session id to list incidents for.",
)
@click.option("--status", default=None, help="Filter by status (open/acknowledged/resolved).")
def list_command(session_id: int, status: str | None) -> None:
    """List incidents for a session from the daemon."""
    path = f"/api/v1/incidents?session={session_id}"
    if status is not None:
        path = f"{path}&status={status}"
    try:
        response = DaemonClient().get(path)
        if not isinstance(response, list):
            raise DaemonError("Invalid daemon response", "Incident list response must be a list.")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    if not response:
        click.echo("no incidents")
        return
    echo_table(response, _INCIDENT_LIST_HEADERS)


@incident.command(name="show")
@click.argument("incident_id")
def show_command(incident_id: str) -> None:
    """Fetch one incident from the daemon."""
    try:
        response = DaemonClient().get(f"/api/v1/incidents/{incident_id}")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    echo_json(response)


@incident.command(name="ack")
@click.argument("incident_id")
@click.option("--by", "acknowledged_by", default=None, help="Who is acknowledging the incident.")
@click.option("--note", default=None, help="Acknowledgement note.")
def ack_command(incident_id: str, acknowledged_by: str | None, note: str | None) -> None:
    """Acknowledge an incident through the daemon."""
    payload: dict[str, object] = {}
    if acknowledged_by is not None:
        payload["acknowledged_by"] = acknowledged_by
    if note is not None:
        payload["note"] = note
    try:
        response = DaemonClient().post(f"/api/v1/incidents/{incident_id}/ack", payload)
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    echo_json(response)


__all__ = ["ack_command", "incident", "list_command", "show_command"]
