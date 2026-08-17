"""Runtime-host protocol import surface.

The concrete dataclasses still live near their current implementations while
the backend is being refactored. This module is the stable place for new code
to import the runtime command, manifest, acknowledgement, and report shapes.
"""

from app.runtime_child.driver import (
    DeviceReport,
    ReportCallback,
    RuntimePhase,
    RuntimeReport,
)
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.watchdog.adapters import CommandAcknowledgement
from app.watchdog.messages import (
    WATCHDOG_COMMAND_PATH,
    WATCHDOG_COMMANDS,
    WATCHDOG_PROTOCOL_VERSION,
    CommandEnvelope,
    CorrelationEnvelope,
)

__all__ = [
    "CommandAcknowledgement",
    "CommandEnvelope",
    "CorrelationEnvelope",
    "DeviceFlow",
    "DeviceReport",
    "MANIFEST_SCHEMA_VERSION",
    "Manifest",
    "ReportCallback",
    "RuntimePhase",
    "RuntimeReport",
    "WATCHDOG_COMMAND_PATH",
    "WATCHDOG_COMMANDS",
    "WATCHDOG_PROTOCOL_VERSION",
]
