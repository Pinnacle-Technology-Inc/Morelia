"""Conservative OS process observations; failed queries never prove exit."""

from __future__ import annotations

import ctypes
import math
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum


class ProcessState(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProcessEvidence:
    pid: int | None
    state: ProcessState
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def record_process_identity(pid: int) -> dict | None:
    """Record the creation time needed to distinguish this process from a reused PID."""
    if sys.platform != "win32" or type(pid) is not int or pid <= 0:
        return None
    try:
        kernel = _identity_kernel()
    except OSError:
        return None
    handle = kernel.OpenProcess(0x00101000, False, pid)
    if not handle:
        return None
    try:
        created = _creation_filetime(kernel, handle)
        if created is None or kernel.WaitForSingleObject(handle, 0) != 258:
            return None
        return {"pid": pid, "creation_filetime": str(created)}
    finally:
        kernel.CloseHandle(handle)


def terminate_recorded_process(identity: Mapping, *, timeout: float) -> ProcessEvidence:
    """Stop an exact recorded process without terminating a replacement that reused its PID."""
    pid = identity.get("pid") if isinstance(identity, Mapping) else None
    stamp = identity.get("creation_filetime") if isinstance(identity, Mapping) else None
    if (type(pid) is not int or pid <= 0 or not isinstance(stamp, str)
            or not stamp.isascii() or not stamp.isdecimal()
            or len(stamp) > 20 or not 0 < int(stamp) < 2**64):
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "missing_or_invalid_process_identity")
    if sys.platform != "win32":
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "unsupported_platform")
    if (not isinstance(timeout, (int, float)) or not math.isfinite(timeout)
            or timeout < 0):
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "invalid_termination_timeout")
    try:
        kernel = _identity_kernel()
    except OSError:
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "process_api_unavailable")
    handle = kernel.OpenProcess(0x00101001, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        state = ProcessState.DEAD if error == 87 else ProcessState.UNKNOWN
        return ProcessEvidence(pid, state, f"open_recorded_process_error_{error}")
    try:
        created = _creation_filetime(kernel, handle)
        if created is None:
            return ProcessEvidence(pid, ProcessState.UNKNOWN, "process_creation_query_failed")
        if created != int(stamp):
            return ProcessEvidence(pid, ProcessState.DEAD, "process_identity_reused")
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            return ProcessEvidence(pid, ProcessState.DEAD, "recorded_process_already_exited")
        if status != 258:
            return ProcessEvidence(pid, ProcessState.UNKNOWN, "process_wait_failed")
        if not kernel.TerminateProcess(handle, 1):
            error = ctypes.get_last_error()
            if kernel.WaitForSingleObject(handle, 0) == 0:
                return ProcessEvidence(pid, ProcessState.DEAD, "recorded_process_exited_during_cleanup")
            return ProcessEvidence(pid, ProcessState.UNKNOWN, f"terminate_process_error_{error}")
        milliseconds = min(math.ceil(min(timeout, 0xFFFFFFFE / 1000) * 1000), 0xFFFFFFFE)
        status = kernel.WaitForSingleObject(handle, milliseconds)
        if status == 0:
            return ProcessEvidence(pid, ProcessState.DEAD, "recorded_process_terminated")
        if status == 258:
            return ProcessEvidence(pid, ProcessState.ALIVE, "recorded_process_exit_timeout")
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "process_wait_failed")
    finally:
        kernel.CloseHandle(handle)


def _creation_filetime(kernel, handle) -> int | None:
    from ctypes import wintypes

    created, exited, user, system = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(
        handle, ctypes.byref(created), ctypes.byref(exited),
        ctypes.byref(system), ctypes.byref(user),
    ):
        return None
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def _identity_kernel():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def probe_process(pid: int | None) -> ProcessEvidence:
    if type(pid) is not int or pid <= 0:
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "missing_or_invalid_pid")
    try:
        if sys.platform == "win32":
            return _probe_windows(pid)
        os.kill(pid, 0)
    except ProcessLookupError:
        return ProcessEvidence(pid, ProcessState.DEAD, "process_absent")
    except (OSError, ValueError):
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "process_query_failed")
    return ProcessEvidence(pid, ProcessState.ALIVE, "process_exists")


def _probe_windows(pid: int) -> ProcessEvidence:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        state = ProcessState.DEAD if error == 87 else ProcessState.UNKNOWN
        return ProcessEvidence(pid, state, f"open_process_error_{error}")
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            return ProcessEvidence(pid, ProcessState.DEAD, "process_handle_signalled")
        if status == 258:
            return ProcessEvidence(pid, ProcessState.ALIVE, "process_handle_unsignalled")
        return ProcessEvidence(pid, ProcessState.UNKNOWN, "process_wait_failed")
    finally:
        kernel.CloseHandle(handle)
