"""Operator CLI commands for durable operations."""

from __future__ import annotations

import json
from datetime import datetime

import click
from flask.cli import with_appcontext

from app.cli.output import echo_table
from app.domain.enums import OperationState
from app.domain.errors import OperationNotFound, OperationResolutionError
from app.models.operation import Operation
from app.services.operations import (
    list_operations,
    resolve_uncertain_operation,
)


@click.group(name="ops")
def ops_group() -> None:
    """Inspect and resolve durable runtime operations."""


_OPERATION_LIST_HEADERS = (
    "operation_id",
    "state",
    "command",
    "dataflow_id",
    "target_device_id",
    "error_code",
    "resolved",
)


@ops_group.command(name="list")
@click.option(
    "--state",
    type=click.Choice([state.value for state in OperationState]),
    default=None,
    help="Filter operations by state.",
)
@with_appcontext
def list_ops(state: str | None) -> None:
    state_filter = OperationState(state) if state is not None else None
    operations = list_operations(state=state_filter)
    if not operations:
        click.echo("No operations found.")
        return

    echo_table(
        [
            {
                "operation_id": operation.operation_id,
                "state": operation.state.value,
                "command": operation.command,
                "dataflow_id": operation.dataflow_id,
                "target_device_id": operation.target_device_id,
                "error_code": operation.error_code,
                "resolved": "yes" if operation.resolved_at is not None else "no",
            }
            for operation in operations
        ],
        _OPERATION_LIST_HEADERS,
    )


@ops_group.command(name="show")
@click.argument("operation_id")
@with_appcontext
def show_op(operation_id: str) -> None:
    operation = next(
        (row for row in list_operations() if row.operation_id == operation_id),
        None,
    )
    if operation is None:
        raise click.ClickException(f"No operation with id {operation_id!r}.")
    click.echo(json.dumps(_operation_to_dict(operation), indent=2, sort_keys=True))


@ops_group.command(name="resolve")
@click.argument("operation_id")
@click.option("--by", "resolved_by", required=True, help="Operator identity.")
@click.option("--note", "resolution_note", required=True, help="Resolution note.")
@with_appcontext
def resolve_op(operation_id: str, resolved_by: str, resolution_note: str) -> None:
    try:
        operation = resolve_uncertain_operation(
            operation_id,
            resolved_by=resolved_by,
            resolution_note=resolution_note,
        )
    except (OperationNotFound, OperationResolutionError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"resolved {operation.operation_id}")


def _operation_to_dict(operation: Operation) -> dict:
    return {
        "id": operation.id,
        "operation_id": operation.operation_id,
        "request_key": operation.request_key,
        "session_id": operation.session_id,
        "dataflow_id": operation.dataflow_id,
        "scope": operation.scope.value,
        "target_device_id": operation.target_device_id,
        "command": operation.command,
        "request_id": operation.request_id,
        "command_id": operation.command_id,
        "watchdog_id": operation.watchdog_id,
        "recovery_id": operation.recovery_id,
        "manifest_hash": operation.manifest_hash,
        "state": operation.state.value,
        "error_code": operation.error_code,
        "error_message": operation.error_message,
        "details": operation.details,
        "resolved_by": operation.resolved_by,
        "resolved_at": _format_datetime(operation.resolved_at),
        "resolution_note": operation.resolution_note,
        "created_at": _format_datetime(operation.created_at),
        "updated_at": _format_datetime(operation.updated_at),
    }


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
