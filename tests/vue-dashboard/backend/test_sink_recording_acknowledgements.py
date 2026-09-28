"""CSV acknowledgements follow successful checkpoints and preserve sample time."""
import csv
from datetime import UTC, datetime

import pytest

from app.output.managed_csv_sink import ManagedCsvSink

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
