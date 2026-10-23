"""Keep a Windows watchdog's entire Morelia process tree in one lifetime boundary."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_JOB_OBJECT_QUERY = 0x0004
_JOB_OBJECT_TERMINATE = 0x0008
_ERROR_ALREADY_EXISTS = 183
_ERROR_FILE_NOT_FOUND = 2
_CONTAINMENT_VERSION = 1


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


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class ProcessTreeCleanupResult:
    released: bool
    terminated: bool
    active_processes: int | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


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
    return _install_guard(None)


def install_owned_process_tree(
    outbox_path: str | os.PathLike,
    *,
    watchdog_id: str,
    dataflow_id: str,
    manifest_hash: str,
) -> ProcessTreeGuard | None:
    """Record containment before this watchdog can construct workers or writers."""
    if sys.platform != "win32":
        return None
    marker = _containment_marker(watchdog_id, dataflow_id, manifest_hash)
    path = Path(str(outbox_path) + ".containment.json")
    if path.exists():
        raise FileExistsError(f"watchdog containment marker already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    guard = _install_guard(marker["job_name"])
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(marker, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows rename publishes the complete proof and refuses to replace a generation.
        os.rename(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return guard


def cleanup_owned_process_tree(
    outbox_path: str | os.PathLike,
    *,
    watchdog_id: str,
    dataflow_id: str,
    manifest_hash: str,
    deadline: float,
) -> ProcessTreeCleanupResult:
    """Terminate an enrolled watchdog's remaining processes and observe their exit.

    The caller must stop its runtime host first so it cannot launch another generation.
    The deadline uses time.monotonic(). Missing enrollment cannot prove release.
    """
    if sys.platform != "win32":
        return ProcessTreeCleanupResult(False, False, None, "unsupported_platform")
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        return ProcessTreeCleanupResult(False, False, None, "invalid_deadline")
    try:
        expected = _containment_marker(watchdog_id, dataflow_id, manifest_hash)
        with open(str(outbox_path) + ".containment.json", "rb") as stream:
            encoded = stream.read(65537)
        if len(encoded) > 65536:
            return ProcessTreeCleanupResult(False, False, None, "invalid_containment_marker")
        marker = json.loads(encoded)
    except FileNotFoundError:
        return ProcessTreeCleanupResult(False, False, None, "containment_marker_missing")
    except (OSError, ValueError, TypeError):
        return ProcessTreeCleanupResult(False, False, None, "containment_marker_unreadable")
    if (not isinstance(marker, dict) or marker != expected
            or type(marker.get("version")) is not int
            or marker.get("installed") is not True):
        return ProcessTreeCleanupResult(False, False, None, "containment_identity_mismatch")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_kernel32(kernel32)
    handle = kernel32.OpenJobObjectW(
        _JOB_OBJECT_QUERY | _JOB_OBJECT_TERMINATE, False, expected["job_name"],
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == _ERROR_FILE_NOT_FOUND:
            # An installed job disappears only after its handles and all its processes are gone.
            return ProcessTreeCleanupResult(True, False, 0, "contained_job_exited")
        return ProcessTreeCleanupResult(False, False, None, f"open_job_error_{error}")
    terminated = False
    active = None
    try:
        while True:
            accounting = _BasicAccountingInformation()
            if not kernel32.QueryInformationJobObject(
                handle, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
                ctypes.byref(accounting), ctypes.sizeof(accounting), None,
            ):
                return ProcessTreeCleanupResult(
                    False, terminated, active, f"query_job_error_{ctypes.get_last_error()}",
                )
            active = int(accounting.ActiveProcesses)
            if active == 0:
                return ProcessTreeCleanupResult(True, terminated, 0, "contained_job_empty")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ProcessTreeCleanupResult(False, terminated, active, "process_tree_exit_timeout")
            if not terminated:
                if not kernel32.TerminateJobObject(handle, 1):
                    return ProcessTreeCleanupResult(
                        False, False, active, f"terminate_job_error_{ctypes.get_last_error()}",
                    )
                terminated = True
            time.sleep(min(0.05, remaining))
    finally:
        kernel32.CloseHandle(handle)


def _containment_marker(watchdog_id: str, dataflow_id: str, manifest_hash: str) -> dict:
    identity = (watchdog_id, dataflow_id, manifest_hash)
    if any(not isinstance(value, str) or not value for value in identity):
        raise ValueError("watchdog containment requires complete producer identity")
    digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    return {
        "version": _CONTAINMENT_VERSION,
        "platform": "win32",
        "watchdog_id": watchdog_id,
        "dataflow_id": dataflow_id,
        "manifest_hash": manifest_hash,
        "job_name": "Global\\Morelia-watchdog-" + digest,
        "installed": True,
    }


def _install_guard(job_name: str | None) -> ProcessTreeGuard:

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_kernel32(kernel32)
    job_handle = kernel32.CreateJobObjectW(None, job_name)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if job_name is not None and ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(job_handle)
        raise FileExistsError("watchdog containment job already exists")

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
    kernel32.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
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


__all__ = [
    "ProcessTreeGuard", "ProcessTreeCleanupResult", "install_process_tree_guard",
    "install_owned_process_tree", "cleanup_owned_process_tree",
]
