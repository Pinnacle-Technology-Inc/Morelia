"""Watchdog-side command receipt and correlation binding."""

import logging
from collections.abc import Mapping

from structlog.contextvars import clear_contextvars

from app.watchdog.messages import CommandEnvelope

log = logging.getLogger("watchdog")


def receive_command(values: Mapping[str, object]) -> CommandEnvelope:
    """Validate an incoming command and emit its first correlated watchdog event."""
    envelope = CommandEnvelope.from_dict(values)
    envelope.correlation.bind()

    try:
        log.info(
            "watchdog_command_received",
            extra={
                **envelope.correlation.to_dict(),
                "command": envelope.command,
            },
        )
        return envelope
    finally:
        clear_contextvars()
