"""File acknowledgements follow successful writes and preserve sample time."""
import csv
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.output.managed_csv_sink import ManagedCsvSink
from app.output.managed_edf_sink import ManagedEdfSink

STAMP = 1_790_164_800_000_000_000
ISO = datetime.fromtimestamp(STAMP // 1_000_000_000, UTC).isoformat()


def csv_sink(path):
    return ManagedCsvSink(path=path, dataflow_id="recording-ack", fieldnames=["time", "value"],
                          device_id="pod:one", sink_id="csv")


def test_csv_first_ack_follows_readable_checkpoint_and_final_drain_keeps_sample_time(tmp_path, app):
    path = tmp_path / "ack.csv"
    events = []
    with app.app_context():
        sink = csv_sink(path)
        def acknowledged(event):
            # Independent filesystem observer at the actual callback boundary.
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert rows and int(rows[-1]["time"]) <= STAMP + 1_000_000_000
            assert sink.managed.record.row_offset == len(rows)
            events.append(event)
        sink.bind_recording_callback(acknowledged)
        sink.write_row({"time": STAMP, "value": 1})
        assert len(events) == 1
        assert events[0] == {"source_id": "pod:one", "sink_id": "csv", "first_sample_at": ISO, "last_sample_at": ISO}
        sink.write_row({"time": STAMP + 1_000_000_000, "value": 2})
        sink.close()
        assert events[-1]["last_sample_at"] == datetime.fromtimestamp(STAMP // 1_000_000_000 + 1, UTC).isoformat()


def test_csv_failed_checkpoint_never_acknowledges_buffered_samples(tmp_path, app, monkeypatch):
    with app.app_context():
        sink = csv_sink(tmp_path / "failed.csv").open()
        events = []
        sink.bind_recording_callback(events.append)
        def fail(*_args):
            raise OSError("injected checkpoint failure")
        with monkeypatch.context() as patch:
            patch.setattr(sink.managed, "checkpoint", fail)
            with pytest.raises(OSError, match="checkpoint failure"):
                sink.write_row({"time": STAMP, "value": 1})
            assert events == []
        sink.close()


def test_real_edf_acknowledges_only_written_batch_and_retains_buffered_sample_times(tmp_path, app):
    from pyedflib import EdfReader
    path = tmp_path / "ack.edf"
    with app.app_context():
        events = []
        sink = ManagedEdfSink(path=path, dataflow_id="recording-edf", channels=["EEG1"], sample_rate=2,
                              device_id="pod:one", sink_id="edf")
        sink.bind_recording_callback(events.append)
        sink.flush(STAMP, SimpleNamespace(ch0=1))
        assert events == []
        sink.flush(STAMP + 500_000_000, SimpleNamespace(ch0=2))
        assert events[0]["first_sample_at"] == ISO
        assert events[0]["last_sample_at"].endswith(".500000+00:00")
        sink.close()
    with EdfReader(str(path)) as reader:
        assert reader.getStartdatetime().replace(tzinfo=UTC).isoformat() == ISO
        assert reader.getNSamples().tolist() == [2]
        assert reader.readSignal(0).tolist() == pytest.approx([1, 2], abs=0.07)


def test_edf_failed_native_write_never_acknowledges(tmp_path, app, monkeypatch):
    with app.app_context():
        sink = ManagedEdfSink(path=tmp_path / "failed.edf", dataflow_id="recording-edf", channels=["EEG1"], sample_rate=1).open()
        events = []
        sink.bind_recording_callback(events.append)
        def fail(*_args):
            raise OSError("injected native write failure")
        with monkeypatch.context() as patch:
            patch.setattr(sink._writer, "writeSamples", fail)
            with pytest.raises(OSError, match="native write failure"):
                sink.flush(STAMP, SimpleNamespace(ch0=1))
            assert events == []
        sink.close()
