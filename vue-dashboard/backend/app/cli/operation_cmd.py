"""Online operation CLI commands backed by the daemon API."""

from __future__ import annotations

from urllib.parse import urlencode

import click

from app.cli.daemon_client import DaemonClient, DaemonError, DaemonUnavailable
from app.cli.output import echo_json, echo_table, exit_with_error

_OPERATION_LIST_HEADERS = (
    "operation_id",
    "state",
    "command",
    "session_id",
    "dataflow_id",
    "target_device_id",
    "runtime_id",
    "error_code",
    "resolved_at",
    "created_at",
)


@click.group(name="operation")
def operation() -> None:
    """Inspect daemon operations."""


@operation.command(name="list")
@click.option("--state", default=None, help="Filter by state.")
@click.option("--session", "session_id", type=int, default=None, help="Filter by session id.")
@click.option("--dataflow", "dataflow_id", default=None, help="Filter by dataflow id.")
def list_command(
    state: str | None,
    session_id: int | None,
    dataflow_id: str | None,
) -> None:
    """List operations from the daemon."""
    query: dict[str, object] = {}
    if state is not None:
        query["state"] = state
    if session_id is not None:
        query["session"] = session_id
    if dataflow_id is not None:
        query["dataflow"] = dataflow_id

    path = "/api/v1/operations/"
    if query:
        path = f"{path}?{urlencode(query)}"

    try:
        response = DaemonClient().get(path)
        if not isinstance(response, list):
            raise DaemonError("Invalid daemon response", "Operation list response must be a list.")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    if not response:
        click.echo("no operations")
        return
    echo_table(response, _OPERATION_LIST_HEADERS)


@operation.command(name="show")
@click.argument("operation_id")
def show_command(operation_id: str) -> None:
    """Fetch one operation from the daemon."""
    try:
        response = DaemonClient().get(f"/api/v1/operations/{operation_id}")
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    echo_json(response)


@operation.command(name="resolve")
@click.argument("operation_id")
@click.option("--by", "resolved_by", required=True, help="Operator identity.")
@click.option("--note", "resolution_note", required=True, help="Resolution note.")
def resolve_command(operation_id: str, resolved_by: str, resolution_note: str) -> None:
    """Resolve an uncertain operation through the daemon."""
    try:
        response = DaemonClient().post(
            f"/api/v1/operations/{operation_id}/resolve",
            {
                "resolved_by": resolved_by,
                "resolution_note": resolution_note,
            },
        )
    except (DaemonUnavailable, DaemonError) as exc:
        exit_with_error(exc)

    echo_json(response)


__all__ = ["list_command", "operation", "resolve_command", "show_command"]
