"""Command transport abstraction used until real process IPC is introduced."""

from app.watchdog.adapters import FakeWatchdogAdapter


class InMemoryWatchdogDispatcher(FakeWatchdogAdapter):
    """Backward-compatible name for the deterministic fake adapter."""
