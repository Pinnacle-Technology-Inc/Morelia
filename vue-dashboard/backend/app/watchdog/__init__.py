"""Contracts for communicating with watchdog processes."""

from app.watchdog.adapters import (
    CommandAcknowledgement,
    ControlPlaneCommandSender,
    WatchdogAdapterError,
    WatchdogInvalidResponseError,
    WatchdogTimeoutError,
    WatchdogUnavailableError,
    WatchdogUnsupportedProtocolError,
)
from app.watchdog.commands import prepare_command
from app.watchdog.messages import (
    WATCHDOG_COMMAND_PATH,
    WATCHDOG_PROTOCOL_VERSION,
    CommandEnvelope,
    CorrelationEnvelope,
)
from app.watchdog.receiver import receive_command

__all__ = [
    "WATCHDOG_COMMAND_PATH",
    "WATCHDOG_PROTOCOL_VERSION",
    "CommandAcknowledgement",
    "CommandEnvelope",
    "ControlPlaneCommandSender",
    "CorrelationEnvelope",
    "WatchdogAdapterError",
    "WatchdogInvalidResponseError",
    "WatchdogTimeoutError",
    "WatchdogUnavailableError",
    "WatchdogUnsupportedProtocolError",
    "prepare_command",
    "receive_command",
]
