"""Flask CLI registration for backend operator commands."""

from flask import Flask

from app.cli.operations import ops_group


def register_cli(app: Flask) -> None:
    app.cli.add_command(ops_group)


__all__ = ["register_cli"]
