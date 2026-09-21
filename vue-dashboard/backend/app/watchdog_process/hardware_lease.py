"""OS-held exclusive leases for physical devices owned by a watchdog process."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import BinaryIO

from app.runtime_host.manifest import Manifest


class HardwareLeaseBusy(RuntimeError):
    """Another live process still owns one of the requested devices."""


def _lease_name(hardware_id: str) -> str:
    """Identify the device independently of its current port."""
    digest = hashlib.sha256(hardware_id.encode()).hexdigest()
    return f"device-{digest}.lock"


def _lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class HardwareLeaseSet:
    """Acquire all device leases atomically from the caller's perspective.

    OS releases these file locks when the watchdog exits. 
    These locks are the final physical-access barrier.
    """

    def __init__(self, manifest: Manifest, *, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._devices = sorted(
            ((flow.hardware_id, flow.port) for flow in manifest.device_flows),
            key=lambda item: (item[0], item[1]),
        )
        self._handles: list[BinaryIO] = []

    @property
    def acquired(self) -> bool:
        return bool(self._handles)

    @property
    def keys(self) -> tuple[str, ...]:
        # Preserve the existing diagnostic wire format.
        return tuple(f"{hardware_id}@{port}" for hardware_id, port in self._devices)

    def acquire(self) -> None:
        if self._handles:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        try:
            for hardware_id, port in self._devices:
                # Keep ownership stable when the device's port changes.
                path = self._directory / _lease_name(hardware_id)
                # Keep the handle open until release() to retain the lock.
                handle = open(path, "a+b")  # noqa: SIM115
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                try:
                    _lock(handle)
                except OSError as exc:
                    handle.close()
                    raise HardwareLeaseBusy(
                        f"hardware lease is held for {hardware_id!r} on {port!r}"
                    ) from exc
                self._handles.append(handle)
        except Exception:
            self.release()
            raise

    def release(self) -> None:
        while self._handles:
            handle = self._handles.pop()
            try:
                _unlock(handle)
            finally:
                handle.close()

    def __enter__(self) -> HardwareLeaseSet:
        self.acquire()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()


__all__ = ["HardwareLeaseBusy", "HardwareLeaseSet"]
