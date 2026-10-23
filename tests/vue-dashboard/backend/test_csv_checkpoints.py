"""Checkpoint and append invariants with real SQLite and physical CSV files."""
import csv
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.database import db, transaction
from app.output.managed_csv_sink import ManagedCsvSink, ManagedCsvSinkError


def make_sink(path, **kwargs):
    return ManagedCsvSink(path=path, dataflow_id="flow", fieldnames=["time", "value"], **kwargs)


def test_hot_path_has_no_sql_and_checkpoint_commits_both_offsets(tmp_path, app, monkeypatch):
    import app.output.managed_csv_sink as module
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    with app.app_context():
        sink = make_sink(tmp_path / "data.csv").open()
        statements, commits = [], []
        def sql(conn, cursor, statement, *args):
            statements.append(statement)
        def commit(conn):
            commits.append(True)
        event.listen(db.engine, "before_cursor_execute", sql)
        event.listen(db.engine, "commit", commit)
        try:
            for i in range(2000):
                sink.write_row({"time": i, "value": i})
            assert not statements and not commits
            now[0] += 1
            sink.write_row({"time": 2000, "value": 2000})
            assert len(commits) == 1
            updates = [s for s in statements if s.startswith("UPDATE")]
            assert len(updates) == 1
            assert "byte_offset" in updates[0] and "row_offset" in updates[0]
            assert sink.managed.record.row_offset == 2001
            assert sink.managed.record.byte_offset == (tmp_path / "data.csv").stat().st_size
            sink.write_row({"time": 2001, "value": 2001})
            sink.close()
            assert sink.managed.record.row_offset == 2002
        finally:
            event.remove(db.engine, "before_cursor_execute", sql)
            event.remove(db.engine, "commit", commit)
            sink.close()


def test_resume_recounts_uncheckpointed_disk_rows_and_preserves_prefix(tmp_path, app):
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = make_sink(path).open()
        descriptor = sink.get_dict()
        sink.write_row({"time": 1, "value": "quoted, multiline\nvalue"})
        # Simulate a process exit after file flush but before a DB checkpoint.
        sink.managed._handle.flush()
        sink.managed._handle.close()
        assert sink.managed.record.row_offset == 0
        before = path.read_bytes()
        rebuilt = ManagedCsvSink(**descriptor).open()
        assert rebuilt.managed.record.row_offset == 1
        rebuilt.write_row({"time": 2, "value": 10})
        rebuilt.close()
        assert rebuilt.managed.record.row_offset == 2
    assert path.read_bytes().startswith(before)
    with path.open(newline="") as stream:
        assert len(list(csv.reader(stream))) == 3


@pytest.mark.parametrize("bad", [b"time,value\r\n1,par", b'time,value\r\n1,"unterminated\n',
                                  b"wrong,value\r\n", b"time,value\r\n1,2,3\r\n", b""])
def test_invalid_resume_preserves_bytes_and_metadata(tmp_path, app, bad):
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = make_sink(path).open()
        descriptor = sink.get_dict()
        sink.close()
        record = sink.managed.record
        original = (record.status, record.row_offset, record.byte_offset)
        path.write_bytes(bad)
        with pytest.raises(ManagedCsvSinkError):
            ManagedCsvSink(**descriptor).open()
        db.session.refresh(record)
        assert (record.status, record.row_offset, record.byte_offset) == original
    assert path.read_bytes() == bad


@pytest.mark.parametrize("explicit_id", [False, True])
def test_missing_recording_is_never_recreated(tmp_path, app, explicit_id):
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = make_sink(path).open()
        descriptor = sink.get_dict()
        sink.close()
        path.unlink()
        if not explicit_id:
            descriptor["output_id"] = None
        with pytest.raises(FileNotFoundError):
            ManagedCsvSink(**descriptor).open()
    assert not path.exists()


@pytest.mark.parametrize("field,value", [("dataflow_id", "other"), ("device_id", "other"),
    ("sink_id", "other"), ("session_id", 99), ("schema_hash", "other"), ("path", "elsewhere.csv")])
def test_explicit_identity_cannot_bypass_validation(tmp_path, app, field, value):
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = make_sink(path).open()
        descriptor = sink.get_dict()
        sink.close()
        before = path.read_bytes()
        descriptor[field] = value
        with pytest.raises(ManagedCsvSinkError, match="mismatch"):
            ManagedCsvSink(**descriptor).open()
        assert path.read_bytes() == before


def pod8401():
    from Morelia.Devices import Pod8401HR, Preamp
    pod = object.__new__(Pod8401HR)
    pod._preamp = Preamp.Preamp8407_SE
    return pod


def test_real_8401_delegate_mapping_reconstruction_and_legacy_refusal(tmp_path, app):
    pod = pod8401()
    fields = ["time", "Bio", "EEG1", "EMG", "EEG2", "aEXT0", "aEXT1",
              "aTTL1", "aTTL2", "aTTL3", "aTTL4"]
    packet = SimpleNamespace(ch0=11, ch1=22, ch2=33, ch3=44, ext0=5, ext1=6,
                             ttl1=1, ttl2=0, ttl3=1, ttl4=0)
    path = tmp_path / "device.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id="flow", fieldnames=fields,
                              pod=pod, schema_hash="manifest")
        sink.flush(100, packet)
        descriptor = sink.get_dict()
        sink.close()
        rebuilt = ManagedCsvSink(**descriptor, pod=pod)
        rebuilt.flush(200, packet)
        rebuilt.close()
        assert rebuilt.managed.record.row_offset == 2
        # Legacy manifest hash is not sufficient: old 8401 column values differed.
        with transaction():
            rebuilt.managed.record.schema_hash = "manifest"
        before = path.read_bytes()
        with pytest.raises(ManagedCsvSinkError, match="serializer version"):
            ManagedCsvSink(**descriptor, pod=pod).open()
        assert before == path.read_bytes()
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert [rows[0][name] for name in ("Bio", "EEG1", "EMG", "EEG2")] == ["11", "22", "33", "44"]


def test_8274_counts_expanded_rows_and_missing_marker(tmp_path, app):
    from Morelia.Devices import Pod8274D
    pod = object.__new__(Pod8274D)
    pod._sample_rate = 1000
    with app.app_context():
        sink = ManagedCsvSink(path=tmp_path / "expanded.csv", dataflow_id="flow",
                              fieldnames=["time", "Ch5", "Ch6", "Ch7"], pod=pod)
        sink.flush(1_000_000, SimpleNamespace(ch5=[1, 2], ch6=[3, 4], ch7=[5, 6]))
        sink.flush(3_000_000, SimpleNamespace(is_missing_sample=True))
        sink.close()
        assert sink.managed.record.row_offset == 3


def test_original_csv_lifecycle_is_never_used_for_managed_append(tmp_path, app, monkeypatch):
    from Morelia.Stream.sink.csv_sink import CSVSink
    def forbidden(*args, **kwargs):
        raise AssertionError("original CSV lifecycle would open/truncate or close the file")
    monkeypatch.setattr(CSVSink, "__enter__", forbidden)
    monkeypatch.setattr(CSVSink, "__exit__", forbidden)
    pod = pod8401()
    fields = ["time", "Bio", "EEG1", "EMG", "EEG2", "aEXT0", "aEXT1",
              "aTTL1", "aTTL2", "aTTL3", "aTTL4"]
    path = tmp_path / "borrowed.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id="flow", fieldnames=fields, pod=pod)
        sink.flush(1, SimpleNamespace(is_missing_sample=True))
        descriptor = sink.get_dict()
        sink.close()
        prefix = path.read_bytes()
        rebuilt = ManagedCsvSink(**descriptor, pod=pod)
        rebuilt.flush(2, SimpleNamespace(is_missing_sample=True))
        rebuilt.close()
        assert rebuilt.managed.record.row_offset == 2
        assert path.read_bytes().startswith(prefix)
    assert path.read_text().count(",".join(fields)) == 1


def test_partial_8274_failure_checkpoints_only_successful_rows(tmp_path, app):
    from Morelia.Devices import Pod8274D
    class BadValue:
        def __str__(self):
            raise ValueError("cannot serialize second row")
    pod = object.__new__(Pod8274D)
    pod._sample_rate = 1000
    path = tmp_path / "partial.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id="flow",
                              fieldnames=["time", "Ch5", "Ch6", "Ch7"], pod=pod)
        packet = SimpleNamespace(ch5=[1, BadValue()], ch6=[3, 4], ch7=[5, 6])
        with pytest.raises(ValueError, match="second row"):
            sink.flush(1_000_000, packet)
        sink.close()
        assert sink.managed.record.row_offset == 1
        assert sink.managed.record.byte_offset == path.stat().st_size
    assert path.read_text().splitlines() == ["time,Ch5,Ch6,Ch7", "1000000,1,3,5"]


def test_close_releases_handle_even_if_commit_fails(tmp_path, app, monkeypatch):
    with app.app_context():
        sink = make_sink(tmp_path / "data.csv").open()
        sink.write_row({"time": 1, "value": 2})
        def fail():
            raise RuntimeError("database unavailable")
        monkeypatch.setattr(db.session, "commit", fail)
        with pytest.raises(RuntimeError, match="database unavailable"):
            sink.close()
        assert sink.managed._handle.closed


def test_buffer_flush_failure_does_not_advance_checkpoint(tmp_path, app, monkeypatch):
    with app.app_context():
        sink = make_sink(tmp_path / "data.csv").open()
        before = (sink.managed.record.byte_offset, sink.managed.record.row_offset)
        sink.write_row({"time": 1, "value": 2})
        def fail():
            raise OSError("disk full")
        with monkeypatch.context() as patch:
            patch.setattr(sink.managed._handle, "flush", fail)
            with pytest.raises(OSError, match="disk full"):
                sink.flush()
        assert (sink.managed.record.byte_offset, sink.managed.record.row_offset) == before
        sink.close()


def test_descriptor_after_close_needs_no_database_context(tmp_path, app, monkeypatch):
    import app.output.managed_csv_sink as module
    from flask import has_app_context
    monkeypatch.setattr(module, "create_database_app", lambda: app)
    assert not has_app_context()
    sink = make_sink(tmp_path / "owned-context.csv").open()
    descriptor = sink.get_dict()
    sink.close()
    assert not has_app_context()
    assert sink.get_dict() == descriptor
    with pytest.raises(ManagedCsvSinkError, match="closed"):
        sink.write_row({"time": 1, "value": 2})


def test_completed_acquisition_is_not_resumed(tmp_path, app):
    with app.app_context():
        sink = make_sink(tmp_path / "complete.csv").open()
        descriptor = sink.get_dict()
        sink.close()
        with transaction():
            sink.managed.record.acquisition_state = "complete"
        with pytest.raises(ManagedCsvSinkError, match="complete"):
            ManagedCsvSink(**descriptor).open()


def test_legacy_generic_unpaired_offsets_are_not_trusted(tmp_path, app):
    with app.app_context():
        sink = make_sink(tmp_path / "legacy.csv", schema_hash="manifest").open()
        sink.write_row({"time": 1, "value": 2})
        descriptor = sink.get_dict()
        sink.close()
        # Old write() committed bytes before advance_row_offset() could commit.
        with transaction():
            sink.managed.record.schema_hash = "manifest"
            sink.managed.record.row_offset = 0
        with pytest.raises(ManagedCsvSinkError, match="schema_hash mismatch"):
            ManagedCsvSink(**descriptor).open()


@pytest.mark.parametrize("offset", [3, 100000])
def test_invalid_checkpoint_boundary_is_refused(tmp_path, app, offset):
    with app.app_context():
        sink = make_sink(tmp_path / "boundary.csv").open()
        sink.write_row({"time": 1, "value": 2})
        descriptor = sink.get_dict()
        sink.close()
        with transaction():
            sink.managed.record.byte_offset = offset
        with pytest.raises(ManagedCsvSinkError, match="checkpoint"):
            ManagedCsvSink(**descriptor).open()


def test_recovery_reads_tail_not_full_checkpointed_history(tmp_path, app, monkeypatch):
    path = tmp_path / "long.csv"
    with app.app_context():
        sink = make_sink(path, checkpoint_interval_sec=60).open()
        for i in range(20_000):
            sink.write_row({"time": i, "value": "x" * 100})
        descriptor = sink.get_dict()
        sink.close()
        size = path.stat().st_size
        assert size > 2_000_000
        # A complete row beyond the last checkpoint must still be recovered.
        with path.open("ab") as stream:
            stream.write(b"20000,tail\r\n")
        reads = [0]
        class ReadBudget:
            def __init__(self, file):
                self.file = file
            def __getattr__(self, name):
                return getattr(self.file, name)
            def read(self, count=-1):
                data = self.file.read(count)
                reads[0] += len(data)
                assert reads[0] < 64_000, "recovery scanned checkpointed history"
                return data
            def read1(self, count=-1):
                data = self.file.read1(count)
                reads[0] += len(data)
                assert reads[0] < 64_000, "recovery scanned checkpointed history"
                return data
        original = ManagedCsvSink._validate_csv
        monkeypatch.setattr(ManagedCsvSink, "_validate_csv",
                            lambda self, handle, *args: original(self, ReadBudget(handle), *args))
        rebuilt = ManagedCsvSink(**descriptor).open()
        assert rebuilt.managed.record.row_offset == 20_001
        rebuilt.close()
        assert path.stat().st_size == size + len(b"20000,tail\r\n")
