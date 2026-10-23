"""One bounded native-driver transaction gate shared by backend processes.

The name deliberately does not depend on app configuration, working directory,
or a parent-created multiprocessing object. Never hold this gate for stream I/O.
"""

from contextlib import contextmanager
import math
import os
from threading import RLock, local
import time


_MUTEX_NAME = r"Local\Morelia.Backend.FTDI.NativeDriver.v1"
_thread_lock = RLock()
_state = local()


@contextmanager
def _process_gate(timeout_sec):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel.ReleaseMutex.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = False
        try:
            result = kernel.WaitForSingleObject(handle, min(math.ceil(timeout_sec * 1000), 0xFFFFFFFE))
            if result == 0x102:
                raise TimeoutError("Timed out waiting for native FTDI driver gate")
            # WAIT_ABANDONED also transfers mutex ownership. There is no shared
            # application state to repair: each transaction starts from the DLL.
            if result not in (0, 0x80):
                raise ctypes.WinError(ctypes.get_last_error())
            acquired = True
            yield
        finally:
            try:
                if acquired and not kernel.ReleaseMutex(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(handle)
    else:
        import fcntl

        # Stable per-user inode; do not unlink it, which would split lock owners.
        fd = os.open(f"/tmp/morelia-ftdi-native-{os.getuid()}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        expires = time.monotonic() + timeout_sec
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    remaining = expires - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for native FTDI driver gate")
                    time.sleep(min(0.01, remaining))
            yield
        finally:
            try:
                if acquired:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


@contextmanager
def native_driver_gate(timeout_sec=10):
    """Serialize complete inventory/open/setup/close transactions; nesting is safe."""
    if not math.isfinite(timeout_sec) or timeout_sec < 0:
        raise ValueError("Native FTDI gate timeout must be finite and nonnegative")
    started = time.monotonic()
    if not _thread_lock.acquire(timeout=timeout_sec):
        raise TimeoutError("Timed out waiting for native FTDI driver gate")
    try:
        if getattr(_state, "entered", False):
            yield
        else:
            with _process_gate(max(0, timeout_sec - (time.monotonic() - started))):
                _state.entered = True
                try:
                    yield
                finally:
                    _state.entered = False
    finally:
        _thread_lock.release()
