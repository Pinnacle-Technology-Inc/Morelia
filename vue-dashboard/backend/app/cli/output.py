"""Shared output helpers for standalone CLI commands."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import NoReturn

import click
from tabulate import tabulate


def echo_json(payload: object) -> None:
    """Emit canonical pretty JSON used by CLI show commands."""
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


def echo_table(rows: Sequence[Mapping[str, object]], headers: Sequence[str]) -> None:
    """Emit aligned table output for CLI list commands."""
    table_rows = [[_table_cell(row.get(header)) for header in headers] for row in rows]
    click.echo(tabulate(table_rows, headers=headers, tablefmt="plain", disable_numparse=True))


def exit_with_error(error: str | Exception) -> NoReturn:
    """Raise a ClickException with a normalized error message."""
    raise click.ClickException(str(error))


def _table_cell(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


__all__ = ["echo_json", "echo_table", "exit_with_error"]
