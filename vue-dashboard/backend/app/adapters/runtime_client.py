"""South-bound client adapter for Runtime Host commands.

The original implementation still lives under ``app.watchdog``. This module
adds a clearer package entry point for new control-plane code while keeping the
existing Watchdog names and behavior intact.
"""

from app.watchdog.adapters import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    CommandAcknowledgement,
    FakeWatchdogAdapter,
    HttpWatchdogAdapter,
    UrllibWatchdogTransport,
    WatchdogAdapterError,
    WatchdogHttpResponse,
    WatchdogInvalidResponseError,
    WatchdogTimeoutError,
    WatchdogTransport,
    WatchdogUnavailableError,
    WatchdogUnsupportedProtocolError,
)

RuntimeHostClient = HttpWatchdogAdapter
FakeRuntimeHostClient = FakeWatchdogAdapter

__all__ = [
    "CommandAcknowledgement",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "FakeRuntimeHostClient",
    "FakeWatchdogAdapter",
    "HttpWatchdogAdapter",
    "RuntimeHostClient",
    "UrllibWatchdogTransport",
    "WatchdogAdapterError",
    "WatchdogHttpResponse",
    "WatchdogInvalidResponseError",
    "WatchdogTimeoutError",
    "WatchdogTransport",
    "WatchdogUnavailableError",
    "WatchdogUnsupportedProtocolError",
]
