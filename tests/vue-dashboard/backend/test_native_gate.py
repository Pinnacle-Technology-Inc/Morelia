"""Real unrelated-process gate tests; these never load the native USB driver."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest


GATE_PATH = Path(__file__).resolve().parents[3] / "vue-dashboard/backend/app/discovery/native_gate.py"
spec = importlib.util.spec_from_file_location("isolated_native_gate", GATE_PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

CHILD = """
import importlib.util, json, os, pathlib, sys, threading, time
spec = importlib.util.spec_from_file_location('native_gate', sys.argv[1])
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
mode, ready, go = sys.argv[2:]
pathlib.Path(ready).touch()
deadline = time.monotonic() + 15
while not pathlib.Path(go).exists():
    if time.monotonic() > deadline:
        raise RuntimeError('start signal missing')
    time.sleep(.005)
lock = threading.RLock() if mode == 'local' else gate.native_driver_gate()
with lock:
    if mode == 'abandon':
        os._exit(0)
    begin = time.monotonic()
    time.sleep(.2)
    print(json.dumps([begin, time.monotonic()]), flush=True)
"""


def run_processes(tmp_path, mode):
    go = tmp_path / "go"
    ready = [tmp_path / f"ready-{i}" for i in range(3)]
    children = [subprocess.Popen(
        [sys.executable, "-c", CHILD, str(GATE_PATH), mode, str(path), str(go)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for path in ready]
    try:
        deadline = time.monotonic() + 15
        while not all(path.exists() for path in ready):
            assert time.monotonic() < deadline, "gate processes never became ready"
            time.sleep(.01)
        go.touch()
        intervals = []
        for child in children:
            out, err = child.communicate(timeout=15)
            assert child.returncode == 0, err
            intervals.append(json.loads(out))
        return sorted(intervals)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_unrelated_process_transactions_do_not_overlap(tmp_path):
    intervals = run_processes(tmp_path, "native")
    assert all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:]))


def test_negative_control_process_local_rlocks_overlap(tmp_path):
    intervals = run_processes(tmp_path, "local")
    assert any(left[1] > right[0] for left, right in zip(intervals, intervals[1:]))


def test_gate_nests_and_releases_after_exception():
    with pytest.raises(RuntimeError, match="synthetic"):
        with gate.native_driver_gate():
            with gate.native_driver_gate(timeout_sec=0):
                raise RuntimeError("synthetic")
    with gate.native_driver_gate(timeout_sec=0):
        pass


def test_other_thread_has_bounded_timeout():
    outcomes = []
    def wait():
        try:
            with gate.native_driver_gate(timeout_sec=.05):
                outcomes.append("unexpected acquisition")
        except TimeoutError:
            outcomes.append("timeout")
    with gate.native_driver_gate():
        contender = threading.Thread(target=wait)
        contender.start()
        contender.join(timeout=2)
        assert not contender.is_alive()
    assert outcomes == ["timeout"]


def test_other_process_has_bounded_timeout():
    code = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('gate', sys.argv[1])
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
try:
    with gate.native_driver_gate(timeout_sec=.05):
        raise RuntimeError('unexpected acquisition')
except TimeoutError:
    print('timeout')
"""
    with gate.native_driver_gate():
        result = subprocess.run([sys.executable, "-c", code, str(GATE_PATH)],
                                capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "timeout"


@pytest.mark.skipif(os.name != "nt", reason="Windows mutex abandonment semantics")
def test_abandoned_windows_mutex_is_acquired_and_released(tmp_path):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    # Retain an unowned reference so the mutex survives the owner's exit.
    reference = kernel.CreateMutexW(None, False, gate._MUTEX_NAME)
    assert reference
    try:
        go = tmp_path / "go"
        go.touch()
        result = subprocess.run([sys.executable, "-c", CHILD, str(GATE_PATH), "abandon",
                                 str(tmp_path / "ready"), str(go)], timeout=5)
        assert result.returncode == 0
        with gate.native_driver_gate(timeout_sec=.1):
            pass
        with gate.native_driver_gate(timeout_sec=.1):
            pass
    finally:
        kernel.CloseHandle(reference)
