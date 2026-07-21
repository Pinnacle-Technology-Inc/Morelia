"""Standalone Click entry point for the Pinnacle control-plane CLI."""

from __future__ import annotations

import click

from app.cli.device_cmd import device
from app.cli.doctor import doctor
from app.cli.gap_cmd import gap
from app.cli.incident_cmd import incident
from app.cli.lifecycle import restart_command, shutdown_command, start_command, status_command
from app.cli.operation_cmd import operation
from app.cli.runtime_cmd import runtime
from app.cli.session_cmd import session


@click.group(name="pinnacle")
def pinnacle() -> None:
    """Control the Guarded Experiment daemon."""


pinnacle.add_command(start_command)
pinnacle.add_command(shutdown_command)
pinnacle.add_command(restart_command)
pinnacle.add_command(status_command)
pinnacle.add_command(device)
pinnacle.add_command(session)
pinnacle.add_command(operation)
pinnacle.add_command(incident)
pinnacle.add_command(gap)
pinnacle.add_command(runtime)
pinnacle.add_command(doctor)


def main() -> None:
    """Run the standalone CLI."""
    pinnacle()


__all__ = ["main", "pinnacle"]
