"""Packet 32 spawned PVFS finalization release gate.

The test exercises the actual Windows-style spawn boundary: a DataFlow worker
reconstructs a managed PVFS sink, which owns a nested PVFS writer process.  The
parent's stop result is accepted only after a separate spawned reader verifies
the durable container.
"""

import hashlib
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from app import create_app
from app.database import db
from app.models.output_file import OutputFile
from app.output.managed_pvfs_sink import ManagedPvfsSink, ManagedPvfsSinkError
from app.runtime_child.acknowledged_dataflow import AcknowledgedDataFlow

_CHANNELS = ["EEG1", "EEG2"]
_RATE = 10


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Use one file-backed DB while keeping the worker fallback deliberately empty."""
    database_path = tmp_path / "test.sqlite3"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    test_app = create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": database_url},
    )
    with test_app.app_context():
        db.create_all()
    return test_app


class _Packet:
    def __init__(self, value: int) -> None:
        self.ch0 = float(value)
        self.ch1 = float(value * 2)


class _SpawnedSource:
    def __init__(self, sample_rate: int = _RATE, produced_count=None) -> None:
        self.sample_rate = sample_rate
        self._produced_count = produced_count
        self._port = None
        self._value = 0

    def get_dict(self):
        return {
            "sample_rate": self.sample_rate,
            "produced_count": self._produced_count,
        }

    def open_port(self):
        self._port = object()

    def close_port(self):
        self._port = None

    def obtain_read_queue(self):
        from queue import Queue

        return Queue()

    def check_write_queue(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read_pod_packet_streaming(self, **_kwargs):
        self._value += 1
        if self._produced_count is not None:
            with self._produced_count.get_lock():
                self._produced_count.value = self._value
        time.sleep(0.005)
        return _Packet(self._value)


class _FailingVerificationPvfsSink(ManagedPvfsSink):
    def _verify_finalized_container(self, _path):
        raise ManagedPvfsSinkError("injected catalog verification failure")


def _install_spawn_import_name() -> None:
    """Give multiprocessing spawn a stable, importable module name under pytest."""
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    stable_name = "test_pvfs_shutdown_integrity"
    sys.modules.setdefault(stable_name, sys.modules[__name__])
    _SpawnedSource.__module__ = stable_name
    _FailingVerificationPvfsSink.__module__ = stable_name


def _read_pvfs_in_child(path, output_queue) -> None:
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    reader = PvfsDataFile()
    if not reader.open(str(path)):
        output_queue.put({"ok": False, "reason": "reader_open_failed"})
        return
    try:
        names = list(reader.get_channel_names())
        values = {}
        for channel in names:
            indexed_file = reader.open_channel(channel)
            start = indexed_file.get_start_time().to_seconds()
            end = indexed_file.get_end_time().to_seconds()
            _timestamps, channel_values = indexed_file.get_data(
                HighTime.from_seconds(start - 1.0),
                HighTime.from_seconds(end + 1.0),
            )
            values[channel] = list(channel_values)
        output_queue.put({"ok": True, "names": names, "values": values})
    finally:
        reader.close()


def _run_independent_read(path):
    _install_spawn_import_name()
    _read_pvfs_in_child.__module__ = "test_pvfs_shutdown_integrity"
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    reader = context.Process(target=_read_pvfs_in_child, args=(path, output_queue))
    try:
        reader.start()
        reader_pid = reader.pid
        reader.join(timeout=30.0)
        assert not reader.is_alive(), "independent PVFS reader did not exit"
        assert reader.exitcode == 0
        return output_queue.get(timeout=2.0), {
            "pid": reader_pid,
            "exitcode": reader.exitcode,
        }
    finally:
        output_queue.close()
        output_queue.join_thread()
        reader.close()


def _run_spawned_flow(path, sink_type=ManagedPvfsSink):
    _install_spawn_import_name()
    produced_count = mp.Value("i", 0)
    source = _SpawnedSource(produced_count=produced_count)
    sink = sink_type(
        path=path,
        dataflow_id="packet-32-spawned-shutdown-test",
        channels=_CHANNELS,
        sample_rate=_RATE,
        sink_id="packet-32-spawned-pvfs",
        use_writer_process=True,
    )
    flow = AcknowledgedDataFlow([(source, [sink])])
    try:
        flow.collect()
        time.sleep(2.0)
        result = flow.stop_collection(join_timeout_sec=15.0)
        result["produced_sample_count"] = produced_count.value
        return result
    finally:
        for status_queue in getattr(flow, "_shutdown_status_queues", []):
            close = getattr(status_queue, "close", None)
            if callable(close):
                close()
        flow._workers = []


def test_spawned_clean_stop_is_readable_and_leaves_no_working_catalog(tmp_path, app):
    """A clean stop is true only after independent, exact durable readback."""
    path = tmp_path / "packet-32-clean.pvfs"
    with app.app_context():
        result = _run_spawned_flow(path)
        output = db.session.scalars(
            db.select(OutputFile).where(OutputFile.path == str(path))
        ).first()

    assert result["ok"] is True
    assert output is not None
    stream = result["stream_results"][0]
    assert stream["worker_exitcode"] == 0
    assert stream["terminal_phase"] == "complete"
    actions = [record.action for record in stream["transcript"]]
    expected_shutdown_actions = [
        "writer_stop_observed",
        "writer_queue_drained",
        "writer_native_flushed",
        "writer_native_closed",
        "pvfs_catalog_verified",
        "all_sinks_closed",
    ]
    action_positions = [actions.index(action) for action in expected_shutdown_actions]
    assert action_positions == sorted(action_positions)
    assert not list(tmp_path.glob("temp_*.db3")), "writer left a working catalog"

    produced_sample_count = result["produced_sample_count"]
    assert produced_sample_count > 0
    assert output.status == "closed"
    assert output.acquisition_state == "complete"
    assert output.termination_reason == "clean"
    assert output.row_offset == produced_sample_count
    assert output.sample_loss == 0
    assert output.byte_loss == 0

    before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    readback, reader_evidence = _run_independent_read(path)
    after_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    assert readback["ok"] is True
    assert readback["names"] == _CHANNELS
    sample_count = len(readback["values"]["EEG1"])
    assert sample_count == produced_sample_count
    expected = np.arange(1, sample_count + 1, dtype=float)
    np.testing.assert_allclose(readback["values"]["EEG1"], expected, atol=0.1)
    np.testing.assert_allclose(readback["values"]["EEG2"], expected * 2, atol=0.1)
    assert len(readback["values"]["EEG2"]) == sample_count
    assert before_hash == after_hash, "readback changed the published PVFS bytes"
    reader_residue = list(tmp_path.glob("temp_*.db3"))
    assert not reader_residue, (
        "reader left a working catalog after its clean exit: "
        f"pid={reader_evidence['pid']} exitcode={reader_evidence['exitcode']} "
        f"paths={[str(path) for path in reader_residue]}"
    )
    assert not list(tmp_path.glob("*.verify-*.db3"))


def test_spawned_verification_failure_is_not_clean_or_successful(tmp_path, app):
    """Close/verification failure must surface as failed stop evidence."""
    path = tmp_path / "packet-32-failed.pvfs"
    with app.app_context():
        result = _run_spawned_flow(path, sink_type=_FailingVerificationPvfsSink)
        output = db.session.scalars(
            db.select(OutputFile).where(OutputFile.path == str(path))
        ).first()

    assert result["ok"] is False
    assert output is not None
    assert output.status == "closed"
    assert output.acquisition_state == "interrupted"
    assert output.termination_reason == "writer_failure"
    stream = result["stream_results"][0]
    assert stream["worker_exitcode"] != 0
    assert stream["terminal_phase"] == "failed"
    actions = [record.action for record in stream["transcript"]]
    assert "all_sinks_closed" not in actions
    assert "pvfs_catalog_verification_failed" in actions
    assert not list(tmp_path.glob("temp_*.db3"))
