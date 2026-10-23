"""Failed containment observations must retain ownership."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.watchdog_process import process_tree


IDENTITY = {"watchdog_id": "watchdog", "dataflow_id": "dataflow", "manifest_hash": "manifest"}


@pytest.fixture
def enrolled(tmp_path):
    path = tmp_path / "watchdog.sqlite3"
    marker = process_tree._containment_marker(**IDENTITY)
    (tmp_path / "watchdog.sqlite3.containment.json").write_text(json.dumps(marker))
    return path


class Kernel:
    def __init__(self, *, handle=17, active=1, query=True, terminate=True):
        self.handle = handle
        self.active = active
        self.query = query
        self.terminate = terminate
        self.closed = []
        self.terminated = []

    def OpenJobObjectW(self, *args):
        return self.handle

    def QueryInformationJobObject(self, handle, information_class, accounting, size, length):
        accounting._obj.ActiveProcesses = self.active
        return self.query

    def TerminateJobObject(self, handle, exit_code):
        self.terminated.append(handle)
        return self.terminate

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


def configure(monkeypatch, kernel, *, error=5):
    monkeypatch.setattr(process_tree.sys, "platform", "win32")
    monkeypatch.setattr(process_tree, "_configure_kernel32", lambda kernel: None)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)


def cleanup(path, *, deadline=None):
    return process_tree.cleanup_owned_process_tree(
        path, **IDENTITY, deadline=time.monotonic() + 0.2 if deadline is None else deadline,
    )


def test_missing_marker_cannot_authorize_native_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(process_tree.sys, "platform", "win32")
    result = cleanup(tmp_path / "missing")
    assert not result.released
    assert result.reason == "containment_marker_missing"


def test_modified_identity_cannot_authorize_native_cleanup(enrolled, monkeypatch):
    monkeypatch.setattr(process_tree.sys, "platform", "win32")
    marker_path = enrolled.with_name(enrolled.name + ".containment.json")
    marker = json.loads(marker_path.read_text())
    marker["watchdog_id"] = "unrelated-watchdog"
    marker_path.write_text(json.dumps(marker))
    assert cleanup(enrolled).reason == "containment_identity_mismatch"


@pytest.mark.parametrize("error,released", [(2, True), (5, False), (87, False)])
def test_only_absent_enrolled_job_proves_exit(enrolled, monkeypatch, error, released):
    kernel = Kernel(handle=0)
    configure(monkeypatch, kernel, error=error)
    assert cleanup(enrolled).released is released
    assert kernel.closed == []
    assert kernel.terminated == []


@pytest.mark.parametrize("failure", ["query", "terminate", "deadline"])
def test_native_failure_never_releases_and_closes_handle(enrolled, monkeypatch, failure):
    kernel = Kernel(query=failure != "query", terminate=failure != "terminate")
    configure(monkeypatch, kernel)
    result = cleanup(enrolled, deadline=time.monotonic() - 1 if failure == "deadline" else None)
    assert not result.released
    assert kernel.closed == [17]
    if failure != "terminate":
        assert kernel.terminated == []


def test_empty_job_requires_no_termination(enrolled, monkeypatch):
    kernel = Kernel(active=0)
    configure(monkeypatch, kernel)
    result = cleanup(enrolled)
    assert result.released
    assert result.active_processes == 0
    assert not result.terminated
    assert kernel.closed == [17]
    assert kernel.terminated == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows production containment startup")
@pytest.mark.parametrize("persistence_blocked", [False, True])
def test_default_entrypoint_persists_containment_before_process_factory(tmp_path, persistence_blocked):
    from app.domain.enums import PolicyMode
    from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
    from app.watchdog_process.outbox import default_outbox_path

    watchdog_id = uuid4().hex
    manifest = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION, dataflow_id=uuid4().hex,
        policy=PolicyMode.RECOMMEND,
        device_flows=(DeviceFlow(
            device_id="startup-device", name="startup-device", hardware_id="unused-hardware",
            port="unused-port", parameters={}, sink_type="csv",
            sink_location=str(tmp_path / "unused.csv"),
        ),),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    outbox_dir = tmp_path / "outboxes"
    if persistence_blocked:
        outbox_dir.write_text("A file prevents the containment directory from being created.")
    outbox_path = default_outbox_path(outbox_dir, watchdog_id)
    marker_path = Path(str(outbox_path) + ".containment.json")
    factory_flag = manifest_path.with_suffix(".factory-called")
    helper = """
import json
import os
import sys
from pathlib import Path
from app.watchdog_process.__main__ import main
from app.watchdog_process.outbox import default_outbox_path

def factory(args):
    Path(args.manifest).with_suffix('.factory-called').write_text('called')
    marker_path = Path(str(default_outbox_path(args.outbox_dir, args.watchdog_id)) + '.containment.json')
    marker = json.loads(marker_path.read_text())
    assert marker['installed'] is True
    assert marker['watchdog_id'] == args.watchdog_id
    os._exit(0)

main(sys.argv[1:], process_factory=factory, poll_interval_seconds=0.01)
"""
    completed = subprocess.run(
        [sys.executable, "-c", helper, "--manifest", str(manifest_path),
         "--runtime-id", uuid4().hex, "--watchdog-id", watchdog_id,
         "--ingest-url", "http://127.0.0.1:1", "--outbox-dir", str(outbox_dir)],
        capture_output=True, text=True, timeout=30,
    )

    if persistence_blocked:
        assert completed.returncode != 0
        assert not factory_flag.exists(), completed.stderr
        assert not marker_path.exists()
        return
    assert completed.returncode == 0, completed.stderr
    assert factory_flag.read_text() == "called"
    marker = json.loads(marker_path.read_text())
    assert marker["watchdog_id"] == watchdog_id
    assert marker["dataflow_id"] == manifest.dataflow_id
    assert marker["manifest_hash"] == manifest.hash
    result = process_tree.cleanup_owned_process_tree(
        outbox_path, watchdog_id=watchdog_id, dataflow_id=manifest.dataflow_id,
        manifest_hash=manifest.hash, deadline=time.monotonic() + 5,
    )
    assert result.released, result
    assert result.active_processes == 0
