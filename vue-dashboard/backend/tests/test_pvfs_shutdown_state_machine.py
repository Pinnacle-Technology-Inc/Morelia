import hashlib
import multiprocessing as mp
import sys
import time
from queue import Empty
from pathlib import Path

import numpy as np
import pytest

from app.output.managed_pvfs_sink import ManagedPvfsSink, ManagedPvfsSinkError
from Morelia.Stream.data_flow import DataFlow


_CHANNELS = ["EEG1", "EEG2"]
_RATE = 10


class _Packet:
    def __init__(self, value):
        self.ch0 = float(value)
        self.ch1 = float(value * 2)


class _SpawnedSource:
    def __init__(self, sample_rate=_RATE):
        self.sample_rate = sample_rate
        self._port = None
        self._value = 0

    def get_dict(self):
        return {"sample_rate": self.sample_rate}

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
        time.sleep(0.005)
        return _Packet(self._value)


class _FailingVerificationPvfsSink(ManagedPvfsSink):
    def _verify_finalized_container(self, _path):
        raise ManagedPvfsSinkError("injected catalog verification failure")


def _independent_read(path, output_queue):
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
            idf = reader.open_channel(channel)
            start = idf.get_start_time().to_seconds()
            end = idf.get_end_time().to_seconds()
            _timestamps, channel_values = idf.get_data(
                HighTime.from_seconds(start - 1.0),
                HighTime.from_seconds(end + 1.0),
            )
            values[channel] = list(channel_values)
        output_queue.put({"ok": True, "names": names, "values": values})
    finally:
        reader.close()


def _run_spawned_flow(path, sink_type=ManagedPvfsSink, app=None):
    # Pytest's importlib mode can name this file with the hyphenated workspace
    # path when combined with root-level tests. Give spawn a stable import name.
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    stable_module = sys.modules[__name__]
    sys.modules.setdefault("test_pvfs_shutdown_state_machine", stable_module)
    _SpawnedSource.__module__ = "test_pvfs_shutdown_state_machine"
    _FailingVerificationPvfsSink.__module__ = "test_pvfs_shutdown_state_machine"
    source = _SpawnedSource()
    sink = sink_type(
        path=path,
        dataflow_id="spawned-shutdown-test",
        channels=_CHANNELS,
        sample_rate=_RATE,
        sink_id="spawned-shutdown-pvfs",
        use_writer_process=True,
    )
    flow = DataFlow([(source, [sink])])
    try:
        flow.collect()
        time.sleep(2.0)
        return flow.stop_collection(join_timeout_sec=15.0)
    finally:
        for queue in getattr(flow, "_shutdown_status_queues", []):
            close = getattr(queue, "close", None)
            if callable(close):
                close()
        flow._workers = []


def _read_in_child(path):
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    sys.modules.setdefault("test_pvfs_shutdown_state_machine", sys.modules[__name__])
    _independent_read.__module__ = "test_pvfs_shutdown_state_machine"
    context = mp.get_context("spawn")
    output_queue = context.Queue()
    reader = context.Process(target=_independent_read, args=(path, output_queue))
    reader.start()
    reader.join(timeout=30.0)
    assert not reader.is_alive()
    assert reader.exitcode == 0
    try:
        return output_queue.get(timeout=2.0)
    finally:
        output_queue.close()
        output_queue.join_thread()


def test_spawned_pvfs_shutdown_reaches_complete_and_preserves_readback(tmp_path, app):
    path = tmp_path / "spawned-clean.pvfs"
    with app.app_context():
        result = _run_spawned_flow(path, app=app)

    assert result["ok"] is True
    stream = result["stream_results"][0]
    assert stream["worker_exitcode"] == 0
    assert stream["terminal_phase"] == "complete"
    actions = [record.action for record in stream["transcript"]]
    assert "pvfs_catalog_verified" in actions
    assert actions.index("pvfs_catalog_verified") < actions.index("all_sinks_closed")

    before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    readback = _read_in_child(path)
    after_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    assert readback["ok"] is True
    assert readback["names"] == _CHANNELS
    assert len(readback["values"]["EEG1"]) > 0
    np.testing.assert_allclose(
        readback["values"]["EEG2"],
        np.asarray(readback["values"]["EEG1"]) * 2,
        atol=0.1,
    )
    assert before_hash == after_hash
    assert not list(tmp_path.glob("temp_*.db3"))
    assert not list(tmp_path.glob("*.verify-*.db3"))


def test_spawned_verification_failure_is_failed_and_not_clean(tmp_path, app):
    path = tmp_path / "spawned-failed.pvfs"
    with app.app_context():
        result = _run_spawned_flow(path, sink_type=_FailingVerificationPvfsSink, app=app)

    assert result["ok"] is False
    stream = result["stream_results"][0]
    assert stream["terminal_phase"] == "failed"
    assert stream["worker_exitcode"] != 0
    assert "all_sinks_closed" not in [record.action for record in stream["transcript"]]
    assert any(record.action == "pvfs_catalog_verification_failed" for record in stream["transcript"])
    assert not list(tmp_path.glob("temp_*.db3"))
