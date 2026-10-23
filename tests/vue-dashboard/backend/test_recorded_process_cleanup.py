"""Recorded Windows process identities constrain forced cleanup."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.runtime_host.process_evidence import (
    ProcessState, record_process_identity, terminate_recorded_process,
)


@pytest.fixture
def process():
    if sys.platform != "win32":
        pytest.skip("Windows process identity behavior")
    executable = Path(sys.base_prefix) / "python.exe"
    child = subprocess.Popen(
        [str(executable), "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_recorded_creation_time_is_exact_and_cleanup_stops_process(process):
    identity = record_process_identity(process.pid)
    assert identity is not None
    assert identity == record_process_identity(process.pid)
    assert identity["pid"] == process.pid
    assert isinstance(identity["creation_filetime"], str)
    assert int(identity["creation_filetime"]) > 2**53

    result = terminate_recorded_process(identity, timeout=5)

    assert result.state is ProcessState.DEAD
    assert result.reason == "recorded_process_terminated"
    assert process.wait(timeout=1) == 1


def test_wrong_creation_time_preserves_unrelated_live_process(process):
    identity = record_process_identity(process.pid)
    assert identity is not None
    identity["creation_filetime"] = str(int(identity["creation_filetime"]) - 1)

    result = terminate_recorded_process(identity, timeout=5)

    assert result.state is ProcessState.DEAD
    assert result.reason == "process_identity_reused"
    assert process.poll() is None


def test_cleanup_of_already_exited_recorded_process_is_idempotent(process):
    identity = record_process_identity(process.pid)
    assert identity is not None
    process.kill()
    process.wait(timeout=5)
    assert terminate_recorded_process(identity, timeout=1).state is ProcessState.DEAD


@pytest.mark.parametrize("identity", [
    None, {}, {"pid": True, "creation_filetime": "123"},
    {"pid": 1, "creation_filetime": 123},
    {"pid": 1, "creation_filetime": "-1"},
    {"pid": 1, "creation_filetime": str(2**64)},
])
def test_invalid_identity_cannot_authorize_termination(identity):
    result = terminate_recorded_process(identity, timeout=1)
    assert result.state is ProcessState.UNKNOWN
    assert result.reason == "missing_or_invalid_process_identity"


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf")])
def test_invalid_timeout_preserves_process(process, timeout):
    identity = record_process_identity(process.pid)
    result = terminate_recorded_process(identity, timeout=timeout)
    assert result.state is ProcessState.UNKNOWN
    assert process.poll() is None
