"""Tests for app.output.managed_pvfs_sink — packet 15 acceptance criteria.

Covers:
1. Initial writes produce a readable PVFS component (channels, rate, unit, values).
2. Injected recovery closes component N and writes only to linked component N+1,
   leaving N byte-for-byte unchanged.
3. Clean stop marks the acquisition complete and schedules no continuation.
Plus SINK-06 create-once safety, get_dict continuation reconstruction, pod-derived
channels, writer-process ownership (start/stop/join, no orphan), and the
deferred-open sink_factory wiring.

The container carries a native handle, so every reader/writer is explicitly closed
before ``tmp_path`` teardown (Windows keeps a lingering handle otherwise).
"""

import numpy as np
import multiprocessing as mp

import pytest

from app.models.output_file import OutputFile
from app.output.managed_pvfs_sink import ManagedPvfsSink, ManagedPvfsSinkError
from app.runtime_child.acknowledged_dataflow import ShutdownReporter, acknowledged_get_data_wrapper

_DF = "dataflow-pvfs-001"
_CH = ["EEG1", "EEG2"]
_RATE = 10


def _rows(logical_sink_id: str) -> list[OutputFile]:
    return (
        OutputFile.query.filter_by(logical_sink_id=logical_sink_id)
        .order_by(OutputFile.segment_index)
        .all()
    )


def _read_channel(path, channel: str) -> list[float]:
    """Read every sample of one channel from a closed PVFS container."""
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    reader = PvfsDataFile()
    assert reader.open(str(path)), f"could not open PVFS container at {path}"
    try:
        idf = reader.open_channel(channel)
        assert idf is not None, f"channel {channel!r} not found in {path}"
        start = idf.get_start_time().to_seconds()
        end = idf.get_end_time().to_seconds()
        _ts, values = idf.get_data(
            HighTime.from_seconds(start - 1.0), HighTime.from_seconds(end + 1.0)
        )
        return list(values)
    finally:
        reader.close()


def _channel_names(path) -> list[str]:
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    reader = PvfsDataFile()
    assert reader.open(str(path))
    try:
        return list(reader.get_channel_names())
    finally:
        reader.close()


class _Pod8206HR:
    sample_rate = 10


class _Pod8401HR:
    sample_rate = 10
    preamp = None


class _Packet8206:
    ch0, ch1, ch2 = 1.0, 2.0, 3.0


# Fake POD class names must match Morelia's for duck-typed channel derivation.
_Pod8206HR.__name__ = "Pod8206HR"
_Pod8401HR.__name__ = "Pod8401HR"
_Packet8206.__name__ = "Pod8206HR"  # only attribute access is used


# ---------------------------------------------------------------------------
# 1. Initial writes -> readable component
# ---------------------------------------------------------------------------


def test_construction_alone_creates_no_file_or_row(tmp_path, app):
    """SINK-21: a parent-built descriptor touches neither filesystem nor DB."""
    path = tmp_path / "data.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        assert not path.exists()
        assert sink.opened is False
        assert OutputFile.query.filter_by(path=str(path)).first() is None
        sink.close()  # never-opened descriptor closes as a no-op
    assert not path.exists()


def test_initial_writes_produce_readable_pvfs(tmp_path, app):
    path = tmp_path / "data.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        sink.open()
        for i in range(_RATE):
            sink.write_frame([float(i), float(i * 2)])
        sink.close()

        logical = sink.record.logical_sink_id
        assert sink.record.acquisition_state == "complete"
        assert sink.record.termination_reason == "clean"
        assert sink.record.row_offset == _RATE

    assert _channel_names(path) == _CH
    np.testing.assert_allclose(_read_channel(path, "EEG1"), np.arange(_RATE), atol=0.1)
    np.testing.assert_allclose(
        _read_channel(path, "EEG2"), np.arange(0, 2 * _RATE, 2), atol=0.1
    )

    with app.app_context():
        assert len(_rows(logical)) == 1, "one clean stop == one component"


def test_flush_packet_signature_writes_pod8206_frames(tmp_path, app):
    path = tmp_path / "stream.pvfs"
    channels = ["EEG1", "EEG2", "EEG3/EMG"]
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=channels, sample_rate=_RATE
        )
        sink.open()
        for _ in range(_RATE):
            sink.flush(123, _Packet8206())
        sink.close()

    np.testing.assert_allclose(_read_channel(path, "EEG1"), np.ones(_RATE), atol=0.1)
    np.testing.assert_allclose(
        _read_channel(path, "EEG2"), np.full(_RATE, 2.0), atol=0.1
    )
    np.testing.assert_allclose(
        _read_channel(path, "EEG3/EMG"), np.full(_RATE, 3.0), atol=0.1
    )


def test_device_preferences_are_accepted(tmp_path, app):
    """Pinned device preferences are applied without error (merger metadata)."""
    path = tmp_path / "prefs.pvfs"
    prefs = [
        {
            "name": "gain",
            "type": "int",
            "value": 5,
            "ProductNumber": "8206-HR",
            "SerialNumber": "SN-001",
        }
    ]
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            device_preferences=prefs,
        )
        sink.open()
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])
        assert sink.component_metadata()["device_preferences"] == prefs
        sink.close()

    np.testing.assert_allclose(_read_channel(path, "EEG1"), np.arange(_RATE), atol=0.1)


# ---------------------------------------------------------------------------
# 2. Injected recovery -> component N closed, N+1 linked, N unchanged
# ---------------------------------------------------------------------------


def test_recovery_writes_linked_continuation_without_touching_prior(tmp_path, app):
    path = tmp_path / "data.pvfs"
    cont = tmp_path / "data.recovery-0001.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        sink.open()
        seg0_output_id = sink.record.output_id
        logical = sink.record.logical_sink_id
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])

        # Injected interruption: close N, continue in linked N+1.
        sink.recover()
        seg1_output_id = sink.record.output_id
        seg0_bytes = path.read_bytes()  # N is now finalized + immutable

        for i in range(_RATE):
            sink.write_frame([float(100 + i), float(100 + i)])
        sink.close()

        # N must be byte-for-byte unchanged after N+1 was written and closed.
        assert path.read_bytes() == seg0_bytes
        assert cont.exists()

        rows = _rows(logical)
        assert [r.segment_index for r in rows] == [0, 1]
        seg0, seg1 = rows
        assert seg0.output_id == seg0_output_id
        assert seg1.output_id == seg1_output_id
        assert seg1.previous_output_id == seg0_output_id
        assert seg1.logical_sink_id == seg0.logical_sink_id
        assert seg0.acquisition_state == "interrupted"
        assert seg0.termination_reason == "recovery"
        assert seg1.acquisition_state == "complete"

    np.testing.assert_allclose(_read_channel(path, "EEG1"), np.arange(_RATE), atol=0.1)
    np.testing.assert_allclose(
        _read_channel(cont, "EEG1"), np.arange(100, 100 + _RATE), atol=0.1
    )


def test_multiple_recoveries_are_monotonic(tmp_path, app):
    path = tmp_path / "data.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        sink.open()
        logical = sink.record.logical_sink_id
        for _ in range(3):
            for i in range(_RATE):
                sink.write_frame([float(i), float(i)])
            sink.recover()
        sink.close()

        rows = _rows(logical)
        assert [r.segment_index for r in rows] == [0, 1, 2, 3]

    for index in range(1, 4):
        assert (tmp_path / f"data.recovery-{index:04d}.pvfs").exists()


# ---------------------------------------------------------------------------
# 3. Clean stop marks complete, no continuation
# ---------------------------------------------------------------------------


def test_clean_stop_schedules_no_continuation(tmp_path, app):
    path = tmp_path / "data.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        sink.open()
        logical = sink.record.logical_sink_id
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])
        sink.close()

        assert len(_rows(logical)) == 1
        assert sink.record.acquisition_state == "complete"
    assert not (tmp_path / "data.recovery-0001.pvfs").exists()


def test_close_is_idempotent(tmp_path, app):
    path = tmp_path / "data.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        sink.open()
        sink.write_frame([1.0, 2.0])
        sink.close()
        sink.close()  # second close is a no-op


def test_native_close_false_marks_writer_failure_and_reports_it(tmp_path, app, monkeypatch):
    """A swallowed pvfs_tools close failure must never look like a clean output."""

    class _FakeIndexedFile:
        def flush(self, synchronous=True):
            return None

    class _FalseClosingPvfsData:
        _indexed_data_files = {"EEG1": _FakeIndexedFile(), "EEG2": _FakeIndexedFile()}

        def flush(self, synchronous=True):
            return None

        def close(self):
            return False

    failures = []
    path = tmp_path / "close-fails.pvfs"

    def _start_with_false_closer(sink, claimed_path):
        sink._pvfs_data = _FalseClosingPvfsData()

    monkeypatch.setattr(ManagedPvfsSink, "_start_in_process", _start_with_false_closer)

    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            sink_id="pod:test:pvfs",
        )
        sink.bind_error_callback(failures.append)
        sink.open()

        with pytest.raises(ManagedPvfsSinkError, match="native close returned false"):
            sink.close()

        assert sink.record.status == "closed"
        assert sink.record.termination_reason == "writer_failure"
        assert sink.record.acquisition_state == "interrupted"

    assert len(failures) == 1
    assert failures[0]["sink_id"] == "pod:test:pvfs"
    assert failures[0]["failure_kind"] == "sink_close"
    assert failures[0]["state"] == "terminal"
    assert "native close returned false" in failures[0]["message"]


def test_unreadable_embedded_catalog_cannot_be_marked_clean(tmp_path, app, monkeypatch):
    """Native close success is insufficient when the finalized catalog is empty."""

    class _FakeIndexedFile:
        def flush(self, synchronous=True):
            return None

    class _TrueClosingPvfsData:
        _indexed_data_files = {"EEG1": _FakeIndexedFile(), "EEG2": _FakeIndexedFile()}

        def flush(self, synchronous=True):
            return None

        def close(self):
            return True

    failures = []
    path = tmp_path / "empty-catalog.pvfs"

    def _start_with_true_closer(sink, claimed_path):
        sink._pvfs_data = _TrueClosingPvfsData()

    def _reject_empty_catalog(sink, finalized_path):
        raise ManagedPvfsSinkError(
            "PVFS finalized catalog missing expected channels: EEG1, EEG2"
        )

    monkeypatch.setattr(ManagedPvfsSink, "_start_in_process", _start_with_true_closer)
    monkeypatch.setattr(
        ManagedPvfsSink,
        "_verify_finalized_container",
        _reject_empty_catalog,
        raising=False,
    )

    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            sink_id="pod:test:pvfs",
        )
        sink.bind_error_callback(failures.append)
        sink.open()

        with pytest.raises(ManagedPvfsSinkError, match="missing expected channels"):
            sink.close()

        assert sink.record.status == "closed"
        assert sink.record.termination_reason == "writer_failure"
        assert sink.record.acquisition_state == "interrupted"

    assert len(failures) == 1
    assert "missing expected channels" in failures[0]["message"]


# ---------------------------------------------------------------------------
# SINK-06 safety + reconstruction
# ---------------------------------------------------------------------------


def test_foreign_file_at_path_is_refused(tmp_path, app):
    """A file the sink does not own is never created-over/overwritten (create-once)."""
    from app.output.managed_file import OutputFileAlreadyExistsError

    path = tmp_path / "foreign.pvfs"
    path.write_bytes(b"someone else's recording")
    with app.app_context(), pytest.raises(OutputFileAlreadyExistsError):
        ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        ).open()
    assert path.read_bytes() == b"someone else's recording"


def test_get_dict_reconstruction_allocates_continuation_not_reopen(tmp_path, app):
    """Reconstruction from get_dict() links a NEW segment; it never reopens N."""
    path = tmp_path / "data.pvfs"
    cont = tmp_path / "data.recovery-0001.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        )
        sink.open()
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])
        saved = sink.get_dict()
        seg0_output_id = saved["output_id"]
        seg0_bytes = path.read_bytes()
        assert seg0_output_id is not None
        assert saved["use_writer_process"] is False

        # Fresh worker rebuilds from the descriptor (predecessor process gone).
        rebuilt = ManagedPvfsSink(**{**saved, "pod": None})
        rebuilt.open()
        assert rebuilt.record.path == str(cont), "must open a new linked path, not reuse"
        assert rebuilt.record.previous_output_id == seg0_output_id
        for i in range(_RATE):
            rebuilt.write_frame([float(200 + i), float(200 + i)])
        rebuilt.close()

        assert path.read_bytes() == seg0_bytes, "predecessor container must be immutable"

    assert cont.exists()
    np.testing.assert_allclose(
        _read_channel(cont, "EEG1"), np.arange(200, 200 + _RATE), atol=0.1
    )


def test_reconstruction_unknown_output_id_raises(tmp_path, app):
    path = tmp_path / "ghost.pvfs"
    with app.app_context(), pytest.raises(ManagedPvfsSinkError):
        ManagedPvfsSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            output_id="00000000-0000-0000-0000-000000000000",
        ).open()


# ---------------------------------------------------------------------------
# Pod-derived channels/units/rate
# ---------------------------------------------------------------------------


def test_channels_derived_from_pod8206(tmp_path, app):
    path = tmp_path / "p8206.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(path=path, dataflow_id=_DF, pod=_Pod8206HR())
        sink.open()
        assert sink._channels == ["EEG1", "EEG2", "EEG3/EMG"]
        assert sink._units == ["uV", "uV", "uV"]
        assert sink._sample_rate == 10
        for _ in range(_RATE):
            sink.write_frame([1.0, 1.0, 1.0])
        sink.close()

    assert _channel_names(path) == ["EEG1", "EEG2", "EEG3/EMG"]


def test_channels_derived_from_pod8401(tmp_path, app):
    path = tmp_path / "p8401.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(path=path, dataflow_id=_DF, pod=_Pod8401HR())
        sink.open()
        assert sink._channels == ["A", "B", "C", "D"]
        assert sink._units == ["uV", "uV", "uV", "uV"]
        sink.close()


def test_missing_channels_and_pod_raises(tmp_path, app):
    path = tmp_path / "nope.pvfs"
    with app.app_context(), pytest.raises(ManagedPvfsSinkError):
        ManagedPvfsSink(path=path, dataflow_id=_DF).open()


# ---------------------------------------------------------------------------
# Writer-process ownership (start/stop/join, no orphan/duplicate writer)
# ---------------------------------------------------------------------------


def test_writer_process_owned_cleanly_and_produces_readable_output(tmp_path, app):
    path = tmp_path / "wp.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            use_writer_process=True,
        )
        sink.open()
        assert sink.writer_alive, "writer child must be running after open()"
        # Morelia forces the scheduler off in writer-process mode.
        assert sink.observe_on_scheduler is None
        for i in range(2 * _RATE):
            sink.write_frame([float(i), float(i)])
        sink.close()

        assert not sink.writer_alive, "writer child must be joined (no orphan) after close()"
        assert sink.forced_termination is False, "clean stop must not force-terminate"
        assert sink.record.acquisition_state == "complete"

    values = _read_channel(path, "EEG1")
    assert len(values) == 2 * _RATE
    np.testing.assert_allclose(values, np.arange(2 * _RATE), atol=0.1)


def test_writer_process_requires_and_reports_shutdown_evidence(tmp_path, app):
    path = tmp_path / "wp-evidence.pvfs"
    status_queue = mp.Queue()
    reporter = ShutdownReporter(status_queue, "shutdown-pvfs-1", 0)
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            use_writer_process=True,
        )
        sink.bind_shutdown_reporter(reporter)
        sink.open()
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])
        sink.close()

        assert sink.forced_termination is False
        assert sink.record.acquisition_state == "complete"

    records = []
    while True:
        try:
            records.append(status_queue.get_nowait())
        except Exception:
            break
    actions = [record.action for record in records]
    assert actions[:4] == [
        "writer_stop_observed",
        "writer_queue_drained",
        "writer_native_flushed",
        "writer_native_closed",
    ]
    assert actions[-1] == "pvfs_catalog_verified"


# ---------------------------------------------------------------------------
# sink_factory wiring (deferred, worker-side open)
# ---------------------------------------------------------------------------


class _FakeSinkConfig:
    def __init__(self, sink_id, type_, parameters):
        self.sink_id = sink_id
        self.type = type_
        self.parameters = parameters


def test_factory_builds_deferred_pvfs_descriptor(tmp_path, app):
    from app.domain.enums import SinkType
    from app.runtime_child.sink_factory import RuntimeContext, build_sink

    path = tmp_path / "factory.pvfs"
    sink_config = _FakeSinkConfig(
        "sink-pvfs-1",
        SinkType.PVFS,
        {
            "file_path": str(path),
            "observe_on_scheduler": "thread_pool",
            "use_writer_process": False,
        },
    )
    ctx = RuntimeContext(dataflow_id=_DF, device_id="dev-1", schema_hash="h1")

    sink = build_sink(sink_config, pod=_Pod8206HR(), runtime_context=ctx)
    assert isinstance(sink, ManagedPvfsSink)
    assert sink.opened is False
    assert not path.exists(), "factory must not open a handle or create the file"

    with app.app_context():
        sink.open()
        assert sink.record.sink_id == "sink-pvfs-1"
        assert sink.record.device_id == "dev-1"
        assert sink.record.schema_hash == "h1"
        sink.close()


def test_factory_missing_file_path_raises(app):
    from app.domain.enums import SinkType
    from app.runtime_child.sink_factory import RuntimeContext, build_sink

    sink_config = _FakeSinkConfig("sink-pvfs-2", SinkType.PVFS, {})
    ctx = RuntimeContext(dataflow_id=_DF, device_id="dev-1")
    with pytest.raises(ValueError, match="no resolved file_path"):
        build_sink(sink_config, pod=None, runtime_context=ctx)
