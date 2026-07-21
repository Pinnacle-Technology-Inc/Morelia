"""Keep a Windows watchdog's entire Morelia process tree in one lifetime boundary."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class ProcessTreeGuard:
    """Own a kill-on-close Job Object handle for this process's lifetime.

    The handle is intentionally not closed from Python. Windows closes it when
    the watchdog exits; at that point ``KILL_ON_JOB_CLOSE`` terminates any
    Morelia workers and queue servers that outlived the watchdog itself.
    """

    __slots__ = ("_handle",)

    def __init__(self, handle: int) -> None:
        self._handle = handle


def install_process_tree_guard() -> ProcessTreeGuard | None:
    """Contain this watchdog and future descendants in a Windows Job Object."""
    if sys.platform != "win32":
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_kernel32(kernel32)
    job_handle = kernel32.CreateJobObjectW(None, None)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            job_handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        if not configured:
            error = ctypes.get_last_error()
            raise ctypes.WinError(error)

        assigned = kernel32.AssignProcessToJobObject(
            job_handle,
            kernel32.GetCurrentProcess(),
        )
        if not assigned:
            error = ctypes.get_last_error()
            raise ctypes.WinError(error)
    except Exception:
        kernel32.CloseHandle(job_handle)
        raise

    return ProcessTreeGuard(job_handle)


def _configure_kernel32(kernel32) -> None:
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL


__all__ = ["ProcessTreeGuard", "install_process_tree_guard"]
