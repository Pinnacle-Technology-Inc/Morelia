"""Capture bounded Windows resource and recording evidence; see diagnose_resources.md."""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import re
import shutil
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    raise SystemExit(
        'Install the diagnostic extra: python -m pip install -e ".[diagnostics]"'
    ) from None

BACKEND = Path(__file__).resolve().parents[1]
MAX_SNAPSHOT_BYTES = 16 * 1024
MAX_RECORD_BYTES = 2 * 1024 * 1024
FAILURE_PATTERN = re.compile(
    r"\bWinError\s*[:=]?\s+1450\b|\bERROR_NO_SYSTEM_RESOURCES\b|"
    r'"(?:winerror|error_code)"\s*:\s*1450\b|'
    r"heartbeat_stale|pvfs_close_failed|PVFS (?:writer failed|frame sequence)|"
    r'"stream_status"\s*:\s*"unhealthy"',
    re.IGNORECASE,
)


class PerformanceInformation(ctypes.Structure):
    _fields_ = (
        [("cb", ctypes.c_ulong)]
        + [
            (name, ctypes.c_size_t)
            for name in (
                "CommitTotal",
                "CommitLimit",
                "CommitPeak",
                "PhysicalTotal",
                "PhysicalAvailable",
                "SystemCache",
                "KernelTotal",
                "KernelPaged",
                "KernelNonpaged",
                "PageSize",
            )
        ]
        + [(name, ctypes.c_ulong) for name in ("HandleCount", "ProcessCount", "ThreadCount")]
    )


def windows_memory():
    """Read system commitment and kernel pools directly, without WMI polling."""
    if sys.platform != "win32":
        return {"error": "Windows GetPerformanceInfo is unavailable on this platform"}
    info = PerformanceInformation()
    info.cb = ctypes.sizeof(info)
    library = ctypes.WinDLL("psapi", use_last_error=True)
    function = library.GetPerformanceInfo
    function.argtypes = [ctypes.POINTER(PerformanceInformation), ctypes.c_ulong]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(info), info.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "commit_bytes": info.CommitTotal * info.PageSize,
        "commit_limit_bytes": info.CommitLimit * info.PageSize,
        "commit_peak_bytes": info.CommitPeak * info.PageSize,
        "physical_total_bytes": info.PhysicalTotal * info.PageSize,
        "physical_available_bytes": info.PhysicalAvailable * info.PageSize,
        "kernel_paged_bytes": info.KernelPaged * info.PageSize,
        "kernel_nonpaged_bytes": info.KernelNonpaged * info.PageSize,
        "handles": info.HandleCount,
        "processes": info.ProcessCount,
        "threads": info.ThreadCount,
    }


class DiskCounters:
    """Read Windows disk latency and queue pressure with English PDH counter names."""

    def __init__(self):
        self.query = ctypes.c_void_p()
        self.counters = {}
        self.error = None
        if sys.platform != "win32":
            self.error = "Windows PDH disk counters unavailable"
            return
        try:
            self.pdh = ctypes.WinDLL("pdh")
            self.pdh.PdhOpenQueryW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self.pdh.PdhAddEnglishCounterW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self.pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            self.pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
            self.pdh.PdhGetFormattedCounterValue.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            status = self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query))
            if status:
                raise OSError(f"PdhOpenQuery: {status & 0xFFFFFFFF:#x}")
            for name, path in {
                "write_latency_seconds": r"\PhysicalDisk(_Total)\Avg. Disk sec/Write",
                "write_bytes_per_second": r"\PhysicalDisk(_Total)\Disk Write Bytes/sec",
                "queue_length": r"\PhysicalDisk(_Total)\Current Disk Queue Length",
            }.items():
                handle = ctypes.c_void_p()
                status = self.pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(handle))
                if status:
                    raise OSError(f"PdhAddEnglishCounter: {status & 0xFFFFFFFF:#x}")
                self.counters[name] = handle
            self.pdh.PdhCollectQueryData(self.query)
        except Exception as exc:
            self.error = str(exc)
            self.close()

    def sample(self):
        if self.error:
            return {"error": self.error}

        class Value(ctypes.Structure):
            _fields_ = [("status", ctypes.c_ulong), ("value", ctypes.c_double)]

        status = self.pdh.PdhCollectQueryData(self.query)
        if status:
            return {"error": f"PdhCollectQueryData: {status & 0xFFFFFFFF:#x}"}
        result = {}
        for name, handle in self.counters.items():
            value = Value()
            status = self.pdh.PdhGetFormattedCounterValue(handle, 0x200, None, ctypes.byref(value))
            result[name] = (
                value.value
                if (not status and value.status in (0, 1) and math.isfinite(value.value))
                else None
            )
        return result

    def close(self):
        if self.query.value:
            self.pdh.PdhCloseQuery(self.query)
            self.query = ctypes.c_void_p()


def windows_process_tree():
    """Read parent and thread counts once for the whole host to avoid repeated scans."""

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", ctypes.c_ulong),
            ("usage", ctypes.c_ulong),
            ("pid", ctypes.c_ulong),
            ("heap", ctypes.c_size_t),
            ("module", ctypes.c_ulong),
            ("threads", ctypes.c_ulong),
            ("ppid", ctypes.c_ulong),
            ("priority", ctypes.c_long),
            ("flags", ctypes.c_ulong),
            ("name", ctypes.c_wchar * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    for function in (kernel.Process32FirstW, kernel.Process32NextW):
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(Entry)]
        function.restype = ctypes.c_int
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        present = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not present:
            raise ctypes.WinError(ctypes.get_last_error())
        rows = {}
        while present:
            rows[entry.pid] = {"name": entry.name, "ppid": entry.ppid, "threads": entry.threads}
            present = kernel.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise ctypes.WinError(ctypes.get_last_error())
        return rows
    finally:
        kernel.CloseHandle(handle)


def windows_process_samples():
    """Read each process through one handle; inaccessible processes remain explicit."""

    class Memory(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_rss",
                "rss",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
                "private",
            )
        ]

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

        def seconds(self):
            return ((self.high << 32) | self.low) / 10_000_000

    class Io(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "read_count",
                "write_count",
                "other_count",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
    kernel.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(Io)]
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]
    rows = []
    for pid, basic in windows_process_tree().items():
        row = {"pid": pid, **basic}
        rows.append(row)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            row["error"] = f"OpenProcess: WinError {ctypes.get_last_error()}"
            continue
        try:
            memory = Memory()
            memory.cb = ctypes.sizeof(memory)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                row.update(private_bytes=memory.private, working_set_bytes=memory.rss)
            else:
                row["memory_error"] = ctypes.get_last_error()
            created, exited, system_cpu, user_cpu = (FileTime() for _ in range(4))
            if kernel.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(system_cpu),
                ctypes.byref(user_cpu),
            ):
                row.update(
                    create_time=created.seconds() - 11644473600,
                    cpu_seconds=system_cpu.seconds() + user_cpu.seconds(),
                )
            else:
                row["identity_error"] = ctypes.get_last_error()
            handles = ctypes.c_ulong()
            if kernel.GetProcessHandleCount(handle, ctypes.byref(handles)):
                row["handles"] = handles.value
            else:
                row["handles_error"] = ctypes.get_last_error()
            io = Io()
            if kernel.GetProcessIoCounters(handle, ctypes.byref(io)):
                row.update(read_bytes=io.read_bytes, write_bytes=io.write_bytes)
            else:
                row["io_error"] = ctypes.get_last_error()
        finally:
            kernel.CloseHandle(handle)
    return rows


def process_samples():
    """Identify memory owners by PID and creation time without collecting command lines."""
    if sys.platform == "win32":
        return windows_process_samples()
    result = []
    # Do not reuse a previous process object's creation time after Windows recycles its PID.
    psutil.process_iter.cache_clear()
    for process in psutil.process_iter():
        row = {"pid": process.pid}
        try:
            with process.oneshot():
                memory = process.memory_info()
                cpu = process.cpu_times()
                row.update(
                    name=row.get("name") or process.name(),
                    create_time=process.create_time(),
                    private_bytes=getattr(memory, "private", memory.vms),
                    working_set_bytes=memory.rss,
                    cpu_seconds=cpu.user + cpu.system,
                    handles=process.num_handles() if sys.platform == "win32" else process.num_fds(),
                )
                if sys.platform != "win32":
                    row.update(ppid=process.ppid(), threads=process.num_threads())
                try:
                    io = process.io_counters()
                    row.update(read_bytes=io.read_bytes, write_bytes=io.write_bytes)
                except (psutil.Error, AttributeError) as exc:
                    row["io_error"] = type(exc).__name__
        except psutil.Error as exc:
            row["error"] = type(exc).__name__
        result.append(row)
    return result


def validate_snapshot(row):
    """Reject incomplete or malformed counters instead of treating them as zero."""
    if not isinstance(row, dict) or row.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema")
    for name in ("observed_at", "sample_rate"):
        value = row.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid {name}")
    for name in (
        "accepted_frames",
        "consumed_frames_reported",
        "confirmed_frames",
        "pending_confirmation_frames",
    ):
        if type(row.get(name)) is not int or row[name] < 0:
            raise ValueError(f"invalid {name}")
    if not (
        row["confirmed_frames"] <= row["consumed_frames_reported"] <= row["accepted_frames"]
        and row["pending_confirmation_frames"] == row["accepted_frames"] - row["confirmed_frames"]
    ):
        raise ValueError("inconsistent recording counters")
    for name in ("output_id", "device_id", "sink_id", "dataflow_id", "timestamp", "terminal_error"):
        value = row.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > 1024):
            raise ValueError(f"invalid {name}")
    if not row.get("output_id") or type(row.get("closed")) is not bool:
        raise ValueError("output_id and closed are required")
    if row.get("session_id") is not None and type(row["session_id"]) is not int:
        raise ValueError("invalid session_id")
    for role in ("producer", "writer"):
        pid, created = row.get(f"{role}_pid"), row.get(f"{role}_create_time")
        if pid is not None and (type(pid) is not int or pid <= 0):
            raise ValueError(f"invalid {role} PID")
        if created is not None and (
            type(created) not in (int, float) or not math.isfinite(created) or created <= 0
        ):
            raise ValueError(f"invalid {role} creation time")
    known = {
        "schema_version",
        "observed_at",
        "sample_rate",
        "timestamp",
        "output_id",
        "session_id",
        "dataflow_id",
        "device_id",
        "sink_id",
        "accepted_frames",
        "consumed_frames_reported",
        "confirmed_frames",
        "pending_confirmation_frames",
        "closed",
        "terminal_error",
        "producer_pid",
        "writer_pid",
        "producer_create_time",
        "writer_create_time",
    }
    return {key: value for key, value in row.items() if key in known}


def recording_samples(directory, processes, session_id, now, stale_seconds):
    """Join snapshots to live process identities and label missing evidence explicitly."""
    if directory is None:
        return [], ["recording_snapshots_not_configured"]
    by_pid = {row["pid"]: row for row in processes}
    rows, errors = [], []
    for index, path in enumerate(directory.glob("pvfs-*.json")):
        if index >= 512:
            errors.append("snapshot_file_limit_exceeded")
            break
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_SNAPSHOT_BYTES:
                raise ValueError("snapshot exceeds size limit")
            row = validate_snapshot(json.loads(raw))
            if session_id is not None and row.get("session_id") != session_id:
                continue
            observed = row["observed_at"]
            row["snapshot_age_seconds"] = now - observed
            row["stale"] = now - observed > stale_seconds or observed > now + 5
            for role in ("producer", "writer"):
                pid, created = row.get(f"{role}_pid"), row.get(f"{role}_create_time")
                process = by_pid.get(pid)
                if pid is None:
                    state = "not_configured"
                elif process is None:
                    state = "missing"
                elif created is None or process.get("create_time") is None:
                    state = "unknown"
                elif abs(created - process["create_time"]) > 0.01:
                    state = "pid_reused"
                else:
                    state = "alive"
                row[f"{role}_state"] = state
            rows.append(row)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    if not rows:
        errors.append("no_recording_snapshots")
    return rows, errors


class LogTail:
    """Inspect only newly appended log bytes, with bounded work per poll."""

    def __init__(self, paths):
        self.positions = {}
        for path in paths:
            try:
                self.positions[path] = path.stat().st_size
            except OSError:
                self.positions[path] = 0
        self.pending = {}

    def sample(self):
        matches, errors = [], []
        for path, position in self.positions.items():
            try:
                size = path.stat().st_size
                if size < position:
                    position = 0
                    self.pending.pop(path, None)
                with path.open("rb") as stream:
                    stream.seek(position)
                    raw = stream.read(256 * 1024)
                    self.positions[path] = stream.tell()
                lines = (self.pending.pop(path, b"") + raw).split(b"\n")
                self.pending[path] = lines.pop()[-4096:]
                for line in lines:
                    text = line.decode("utf-8", errors="replace")
                    match = FAILURE_PATTERN.search(text)
                    if match:
                        start = max(0, match.start() - 100)
                        matches.append({"file": str(path), "match": text[start : start + 512]})
                        if len(matches) >= 32:
                            break
            except OSError as exc:
                errors.append(f"{path}: {type(exc).__name__}")
        return matches, errors


class EvidenceLog:
    """Bound rotating samples and preserve the first trigger with preceding samples."""

    def __init__(self, directory, max_bytes, backups, history_seconds):
        self.directory = directory
        self.path = directory / "samples.jsonl"
        self.max_bytes = max_bytes
        self.backups = backups
        self.history_seconds = history_seconds
        self.history = deque()
        self.history_bytes = 0
        self.captured = False
        directory.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("xb")
        self.size = 0

    def append(self, record, reasons):
        line = (json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n").encode()
        if len(line) > min(self.max_bytes, MAX_RECORD_BYTES):
            raise ValueError("sample exceeds log record budget; increase --max-mb")
        if self.size + len(line) > self.max_bytes:
            self.stream.close()
            oldest = self.directory / f"samples.{self.backups}.jsonl"
            oldest.unlink(missing_ok=True)
            for index in range(self.backups - 1, 0, -1):
                source = self.directory / f"samples.{index}.jsonl"
                if source.exists():
                    source.replace(self.directory / f"samples.{index + 1}.jsonl")
            self.path.replace(self.directory / "samples.1.jsonl")
            self.stream = self.path.open("xb")
            self.size = 0
        self.stream.write(line)
        self.stream.flush()
        self.size += len(line)
        now = time.monotonic()
        self.history.append((now, line))
        self.history_bytes += len(line)
        while self.history and (
            now - self.history[0][0] > self.history_seconds or self.history_bytes > self.max_bytes
        ):
            self.history_bytes -= len(self.history.popleft()[1])
        if reasons and not self.captured:
            with (self.directory / "incident.jsonl").open("xb") as stream:
                for _, previous in self.history:
                    stream.write(previous)
            self.captured = True
            print("Evidence preserved: " + "; ".join(reasons[:4]), flush=True)

    def close(self):
        self.stream.close()


def triggers(record, previous, backlog_seconds):
    reasons = []
    system = record["system"]
    if (
        system.get("commit_limit_bytes", 0) > 0
        and system["commit_bytes"] / system["commit_limit_bytes"] >= 0.90
    ):
        reasons.append("system_commit_above_90_percent")
    if record["log_matches"]:
        reasons.append("failure_in_log")
    for row in record["recordings"]:
        identity = row.get("output_id")
        if row.get("terminal_error"):
            reasons.append(f"recording_failed:{identity}")
        if row.get("closed"):
            continue
        if row["stale"]:
            reasons.append(f"stale_recording_snapshot:{identity}")
        for role in ("producer", "writer"):
            if row[f"{role}_state"] in {"missing", "pid_reused"}:
                reasons.append(f"{role}_{row[f'{role}_state']}:{identity}")
        old = previous.get(identity)
        pending, rate = row.get("pending_confirmation_frames"), row.get("sample_rate")
        if (
            isinstance(pending, (int, float))
            and isinstance(rate, (int, float))
            and rate > 0
            and pending / rate > backlog_seconds
            and old is not None
            and pending > old.get("pending_confirmation_frames", pending)
        ):
            reasons.append(f"growing_recording_backlog:{identity}")
    return reasons


def recording_progress(rows, history, now):
    """Measure observed progress without treating delayed receipts as exact queue depth."""
    updated = {}
    for row in rows:
        identity = row.get("output_id")
        confirmed = row.get("confirmed_frames")
        accepted = row.get("accepted_frames")
        pending = row.get("pending_confirmation_frames")
        rate = row.get("sample_rate")
        old = history.get(identity)
        changed = now if old is None or old["confirmed"] != confirmed else old["changed"]
        row["confirmation_unchanged_seconds"] = now - changed
        row["pending_sample_seconds"] = (
            pending / rate
            if (isinstance(pending, (int, float)) and isinstance(rate, (int, float)) and rate > 0)
            else None
        )
        if old is not None and now > old["time"]:
            for name, current, previous in (
                ("accepted_frames_per_second", accepted, old["accepted"]),
                ("confirmed_frames_per_second", confirmed, old["confirmed"]),
            ):
                row[name] = (
                    (current - previous) / (now - old["time"])
                    if (
                        isinstance(current, int)
                        and isinstance(previous, int)
                        and current >= previous
                    )
                    else None
                )
        updated[identity] = {
            "time": now,
            "changed": changed,
            "accepted": accepted,
            "confirmed": confirmed,
        }
    return updated


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", type=Path, required=True, help="New directory for this capture")
    result.add_argument(
        "--snapshots", type=Path, help="MORELIA_DIAGNOSTICS_DIR used by the backend"
    )
    result.add_argument("--session-id", type=int)
    result.add_argument("--interval", type=float, default=1.0)
    result.add_argument(
        "--duration", type=float, default=600.0, help="Seconds; 0 runs until Ctrl+C"
    )
    result.add_argument("--history-seconds", type=float, default=600.0)
    result.add_argument(
        "--max-mb", type=float, default=64.0, help="Per-file and history byte budget"
    )
    result.add_argument("--backups", type=int, default=4)
    result.add_argument("--stale-seconds", type=float, default=5.0)
    result.add_argument("--backlog-seconds", type=float, default=10.0)
    result.add_argument("--log", type=Path, action="append", default=[])
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    for name in ("interval", "history_seconds", "max_mb", "stale_seconds", "backlog_seconds"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be finite and positive")
    if not math.isfinite(args.duration) or args.duration < 0:
        raise SystemExit("--duration must be finite and nonnegative")
    if args.interval < 0.2 or not 1 <= args.backups <= 20 or args.max_mb > 128:
        raise SystemExit("Use interval >= 0.2, backups 1..20, and max-mb <= 128")
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("--output must be a new or empty directory")
    if args.session_id is not None:
        root = BACKEND / "instance" / "diagnostics" / f"session-{args.session_id}"
        args.log += [
            root / f"{name}.jsonl" for name in ("watchdog-driver", "runtime-host", "control-plane")
        ]
    if len(args.log) > 8:
        raise SystemExit("At most 8 log files may be followed")
    log = EvidenceLog(
        args.output, int(args.max_mb * 1024 * 1024), args.backups, args.history_seconds
    )
    disk = DiskCounters()
    tail = LogTail(args.log)
    previous = {}
    progress = {}
    last_snapshot_at = None
    started = time.monotonic()
    print(f"Collecting resources in {args.output.resolve()}; Ctrl+C stops the probe.", flush=True)
    try:
        while True:
            tick = time.monotonic()
            sample_started = time.perf_counter()
            errors = []
            try:
                system = windows_memory()
            except Exception as exc:
                system = {"error": f"{type(exc).__name__}: {exc}"}
            process_error = None
            try:
                processes = process_samples()
            except Exception as exc:
                processes = []
                process_error = f"process_sampling: {type(exc).__name__}: {exc}"
                errors.append(process_error)
            if len(processes) < system.get("processes", 0) * 0.75:
                errors.append("process_inventory_incomplete: run outside a restricted sandbox")
            recordings, snapshot_errors = recording_samples(
                args.snapshots, processes, args.session_id, time.time(), args.stale_seconds
            )
            if process_error:
                for row in recordings:
                    row["producer_state"] = row["writer_state"] = "unknown"
            progress = recording_progress(recordings, progress, tick)
            if recordings:
                last_snapshot_at = tick
            matches, log_errors = tail.sample()
            errors.extend(snapshot_errors + log_errors)
            try:
                free = shutil.disk_usage(args.output).free
            except OSError as exc:
                free = None
                errors.append(f"disk_free: {exc}")
            record = {
                "schema_version": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "elapsed_seconds": tick - started,
                "collector_pid": os.getpid(),
                "system": system,
                "disk": disk.sample(),
                "output_disk_free_bytes": free,
                "processes": processes,
                "recordings": recordings,
                "log_matches": matches,
                "errors": errors,
                "sampling_seconds": time.perf_counter() - sample_started,
                "requested_interval_seconds": args.interval,
            }
            record["sampling_overrun"] = record["sampling_seconds"] > args.interval
            reasons = triggers(record, previous, args.backlog_seconds)
            if process_error:
                reasons.append("process_sampling_failed")
            if last_snapshot_at is not None and tick - last_snapshot_at > args.stale_seconds:
                reasons.append("recording_snapshots_disappeared")
            for row in recordings:
                if (
                    not row.get("closed")
                    and row.get("pending_confirmation_frames", 0) > 0
                    and row["confirmation_unchanged_seconds"] > args.backlog_seconds
                ):
                    reasons.append(f"recording_confirmation_stalled:{row.get('output_id')}")
            record["triggers"] = reasons
            log.append(record, reasons)
            previous = {row.get("output_id"): row for row in recordings}
            remaining = args.duration - (time.monotonic() - started)
            if args.duration and remaining <= 0:
                break
            pause = max(0, args.interval - (time.monotonic() - tick))
            time.sleep(min(pause, remaining) if args.duration else pause)
    except KeyboardInterrupt:
        pass
    finally:
        disk.close()
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
