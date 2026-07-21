"""In-process control-plane lifecycle state.

The restart path quiesces lifecycle work before the daemon exits while leaving
runtime hosts alive for the next daemon to adopt.
"""

from __future__ import annotations

import threading


class ControlPlaneState:
    """Thread-safe gate for lifecycle commands and restart-preserving exit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._quiescing = False
        self._preserve_runtime_hosts_on_exit = False

    def begin_restart(self) -> None:
        with self._lock:
            self._quiescing = True
            self._preserve_runtime_hosts_on_exit = True

    @property
    def quiescing(self) -> bool:
        with self._lock:
            return self._quiescing

    @property
    def preserve_runtime_hosts_on_exit(self) -> bool:
        with self._lock:
            return self._preserve_runtime_hosts_on_exit


__all__ = ["ControlPlaneState"]
