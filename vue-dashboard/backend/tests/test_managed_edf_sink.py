"""Tests for app.output.managed_edf_sink — packet 14 acceptance criteria.

Covers:
1. Initial writes produce a readable EDF component (channels, rate, units, values).
2. Injected recovery closes component N and writes only to linked component N+1,
   leaving N byte-for-byte unchanged.
3. Clean stop marks the acquisition complete and schedules no continuation.
Plus SINK-05 create-once safety, get_dict continuation reconstruction, pod-derived
channels, and the deferred-open sink_factory wiring.
"""

import numpy as np
import pytest
from pyedflib import EdfReader

from app.models.output_file import OutputFile
from app.output.managed_edf_sink import ManagedEdfSink, ManagedEdfSinkError

_DF = "dataflow-edf-001"
_CH = ["EEG1", "EEG2"]
_RATE = 10


def _rows(logical_sink_id: str) -> list[OutputFile]:
    return (
        OutputFile.query.filter_by(logical_sink_id=logical_sink_id)
        .order_by(OutputFile.segment_index)
        .all()
    )


class _Pod8206HR:
    sample_rate = 10


class _Pod8401HR:
    sample_rate = 10
    preamp = None


class _Packet8206:
    ch0, ch1, ch2 = 1.0, 2.0, 3.0
    ttl1, ttl2, ttl3, ttl4 = 0, 1, 0, 1


# Fake POD class names must match Morelia's for duck-typed channel derivation.
_Pod8206HR.__name__ = "Pod8206HR"
_Pod8401HR.__name__ = "Pod8401HR"
_Packet8206.__name__ = "Pod8206HR"  # only class name is inspected


# ---------------------------------------------------------------------------
# 1. Initial writes -> readable component
# ---------------------------------------------------------------------------


def test_construction_alone_creates_no_file_or_row(tmp_path, app):
    """SINK-21: a parent-built descriptor touches neither filesystem nor DB."""
    path = tmp_path / "data.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
        assert not path.exists()
        assert sink.opened is False
        assert OutputFile.query.filter_by(path=str(path)).first() is None
        sink.close()  # never-opened descriptor closes as a no-op
    assert not path.exists()


def test_initial_writes_produce_readable_edf(tmp_path, app):
    path = tmp_path / "data.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
        sink.open()
        for i in range(_RATE):
            sink.write_frame([float(i), float(i * 2)])
        sink.close()

        logical = sink.record.logical_sink_id
        assert sink.record.acquisition_state == "complete"
        assert sink.record.termination_reason == "clean"

    reader = EdfReader(str(path))
    try:
        assert reader.getSignalLabels() == _CH
        assert reader.getSampleFrequency(0) == float(_RATE)
        assert reader.getPhysicalDimension(0).strip() == "uV"
        np.testing.assert_allclose(reader.readSignal(0), np.arange(_RATE), atol=0.1)
        np.testing.assert_allclose(
            reader.readSignal(1), np.arange(0, 2 * _RATE, 2), atol=0.1
        )
    finally:
        reader.close()

    with app.app_context():
        assert len(_rows(logical)) == 1, "one clean stop == one component"


def test_flush_packet_signature_writes_pod8206_frames(tmp_path, app):
    path = tmp_path / "stream.edf"
    channels = ["EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"]
    with app.app_context():
        sink = ManagedEdfSink(
            path=path, dataflow_id=_DF, channels=channels, sample_rate=_RATE
        )
        sink.open()
        for _ in range(_RATE):
            sink.flush(123, _Packet8206())
        sink.close()

    reader = EdfReader(str(path))
    try:
        assert reader.getSignalLabels() == channels
        np.testing.assert_allclose(reader.readSignal(0), np.ones(_RATE), atol=0.1)
        np.testing.assert_allclose(reader.readSignal(1), np.full(_RATE, 2.0), atol=0.1)
        np.testing.assert_allclose(reader.readSignal(4), np.ones(_RATE), atol=0.1)  # TTL2
    finally:
        reader.close()


# ---------------------------------------------------------------------------
# 2. Injected recovery -> component N closed, N+1 linked, N unchanged
# ---------------------------------------------------------------------------


def test_recovery_writes_linked_continuation_without_touching_prior(tmp_path, app):
    path = tmp_path / "data.edf"
    cont = tmp_path / "data.recovery-0001.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
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

    reader0 = EdfReader(str(path))
    try:
        np.testing.assert_allclose(reader0.readSignal(0), np.arange(_RATE), atol=0.1)
    finally:
        reader0.close()
    reader1 = EdfReader(str(cont))
    try:
        np.testing.assert_allclose(
            reader1.readSignal(0), np.arange(100, 100 + _RATE), atol=0.1
        )
    finally:
        reader1.close()


def test_multiple_recoveries_are_monotonic(tmp_path, app):
    path = tmp_path / "data.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
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
        assert (tmp_path / f"data.recovery-{index:04d}.edf").exists()


# ---------------------------------------------------------------------------
# 3. Clean stop marks complete, no continuation
# ---------------------------------------------------------------------------


def test_clean_stop_schedules_no_continuation(tmp_path, app):
    path = tmp_path / "data.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
        sink.open()
        logical = sink.record.logical_sink_id
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])
        sink.close()

        assert len(_rows(logical)) == 1
        assert sink.record.acquisition_state == "complete"
    assert not (tmp_path / "data.recovery-0001.edf").exists()


def test_close_is_idempotent(tmp_path, app):
    path = tmp_path / "data.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
        sink.open()
        sink.write_frame([1.0, 2.0])
        sink.close()
        sink.close()  # second close is a no-op


# ---------------------------------------------------------------------------
# SINK-05 safety + reconstruction
# ---------------------------------------------------------------------------


def test_foreign_file_at_path_is_refused(tmp_path, app):
    """A file the sink does not own is never opened/overwritten (create-once)."""
    from app.output.managed_file import OutputFileAlreadyExistsError

    path = tmp_path / "foreign.edf"
    path.write_bytes(b"someone else's recording")
    with app.app_context(), pytest.raises(OutputFileAlreadyExistsError):
        ManagedEdfSink(
            path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE
        ).open()
    assert path.read_bytes() == b"someone else's recording"


def test_get_dict_reconstruction_allocates_continuation_not_reopen(tmp_path, app):
    """Reconstruction from get_dict() links a NEW segment; it never reopens N."""
    path = tmp_path / "data.edf"
    cont = tmp_path / "data.recovery-0001.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, channels=_CH, sample_rate=_RATE)
        sink.open()
        for i in range(_RATE):
            sink.write_frame([float(i), float(i)])
        saved = sink.get_dict()
        seg0_output_id = saved["output_id"]
        assert seg0_output_id is not None

        # Fresh worker rebuilds from the descriptor (predecessor process gone).
        rebuilt = ManagedEdfSink(**{**saved, "pod": None})
        rebuilt.open()
        assert rebuilt.record.path == str(cont), "must open a new linked path, not reuse"
        assert rebuilt.record.previous_output_id == seg0_output_id
        for i in range(_RATE):
            rebuilt.write_frame([float(200 + i), float(200 + i)])
        rebuilt.close()

    assert cont.exists()


def test_reconstruction_unknown_output_id_raises(tmp_path, app):
    path = tmp_path / "ghost.edf"
    with app.app_context(), pytest.raises(ManagedEdfSinkError):
        ManagedEdfSink(
            path=path,
            dataflow_id=_DF,
            channels=_CH,
            sample_rate=_RATE,
            output_id="00000000-0000-0000-0000-000000000000",
        ).open()


# ---------------------------------------------------------------------------
# Pod-derived channels/rate (both device types)
# ---------------------------------------------------------------------------


def test_channels_derived_from_pod8206(tmp_path, app):
    path = tmp_path / "p8206.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, pod=_Pod8206HR())
        sink.open()
        assert sink._channels == [
            "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4",
        ]
        assert sink._sample_rate == 10
        for _ in range(_RATE):
            sink.write_frame([1.0] * 7)
        sink.close()

    reader = EdfReader(str(path))
    try:
        assert len(reader.getSignalLabels()) == 7
    finally:
        reader.close()


def test_channels_derived_from_pod8401(tmp_path, app):
    path = tmp_path / "p8401.edf"
    with app.app_context():
        sink = ManagedEdfSink(path=path, dataflow_id=_DF, pod=_Pod8401HR())
        sink.open()
        assert sink._channels == [
            "A", "B", "C", "D", "EXT0", "EXT1", "TTL1", "TTL2", "TTL3", "TTL4",
        ]
        sink.close()


def test_missing_channels_and_pod_raises(tmp_path, app):
    path = tmp_path / "nope.edf"
    with app.app_context(), pytest.raises(ManagedEdfSinkError):
        ManagedEdfSink(path=path, dataflow_id=_DF).open()


# ---------------------------------------------------------------------------
# sink_factory wiring (deferred, worker-side open)
# ---------------------------------------------------------------------------


class _FakeSinkConfig:
    def __init__(self, sink_id, type_, parameters):
        self.sink_id = sink_id
        self.type = type_
        self.parameters = parameters


def test_factory_builds_deferred_edf_descriptor(tmp_path, app):
    from app.domain.enums import SinkType
    from app.runtime_child.sink_factory import RuntimeContext, build_sink

    path = tmp_path / "factory.edf"
    sink_config = _FakeSinkConfig(
        "sink-edf-1", SinkType.EDF, {"file_path": str(path), "observe_on_scheduler": "thread_pool"}
    )
    ctx = RuntimeContext(dataflow_id=_DF, device_id="dev-1", schema_hash="h1")

    sink = build_sink(sink_config, pod=_Pod8206HR(), runtime_context=ctx)
    assert isinstance(sink, ManagedEdfSink)
    assert sink.opened is False
    assert not path.exists(), "factory must not open a handle or create the file"
    assert sink.observe_on_scheduler == "thread_pool"

    with app.app_context():
        sink.open()
        assert sink.record.sink_id == "sink-edf-1"
        assert sink.record.device_id == "dev-1"
        assert sink.record.schema_hash == "h1"
        sink.close()


def test_factory_missing_file_path_raises(app):
    from app.domain.enums import SinkType
    from app.runtime_child.sink_factory import RuntimeContext, build_sink

    sink_config = _FakeSinkConfig("sink-edf-2", SinkType.EDF, {})
    ctx = RuntimeContext(dataflow_id=_DF, device_id="dev-1")
    with pytest.raises(ValueError, match="no resolved file_path"):
        build_sink(sink_config, pod=None, runtime_context=ctx)
