"""Event-driven waiting for a spawned or adopted runtime process to exit."""

from __future__ import annotations

import ctypes
import os
import select
import subprocess
import sys
import time
from ctypes import wintypes


def wait_for_process_exit(
    process: subprocess.Popen | None,
    *,
    process_id: int,
) -> int | None:
    """Block until the exact process exits and return its exit code when known."""
    if process is not None and process.pid == process_id:
        return process.wait()
    if sys.platform == "win32":
        return _wait_for_windows_process(process_id)
    if hasattr(os, "pidfd_open"):
        return _wait_for_pidfd(process_id)
    return _wait_for_pid_fallback(process_id)


def _wait_for_windows_process(process_id: int) -> int | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    synchronize = 0x00100000
    query_limited_information = 0x1000
    infinite = 0xFFFFFFFF
    wait_failed = 0xFFFFFFFF

    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        synchronize | query_limited_information,
        False,
        process_id,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error in (87, 1168):  # invalid PID / process no longer exists
            return None
        raise ctypes.WinError(error)
    try:
        if kernel32.WaitForSingleObject(handle, infinite) == wait_failed:
            raise ctypes.WinError()
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise ctypes.WinError()
        return int(exit_code.value)
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_pidfd(process_id: int) -> None:
    try:
        pidfd = os.pidfd_open(process_id)  # type: ignore[attr-defined]
    except ProcessLookupError:
        return
    try:
        select.select([pidfd], [], [])
    finally:
        os.close(pidfd)


def _wait_for_pid_fallback(process_id: int) -> None:
    # Non-Linux POSIX platforms have no stdlib event handle for a non-child PID.
    # Keep this fallback local to adopted processes; spawned children use wait().
    while _pid_exists(process_id):
        time.sleep(0.25)


def _pid_exists(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


__all__ = ["wait_for_process_exit"]
