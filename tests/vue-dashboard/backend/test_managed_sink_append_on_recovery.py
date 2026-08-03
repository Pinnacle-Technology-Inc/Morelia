"""Tests for app.output.managed_csv_sink — packet 4.2 acceptance criteria.

Focus: reconstruction via get_dict() → constructor is always append-only:
original bytes intact, new rows at EOF, exactly one header.
"""

import pytest

from app.models.output_file import OutputFile as _OutputFile  # noqa: F401
from app.output.managed_csv_sink import ManagedCsvSink, ManagedCsvSinkError

_DF = "dataflow-test-002"
_FIELDS = ["ts", "value", "label"]


class _Packet8206:
    ch0 = 1
    ch1 = 2
    ch2 = 3
    ttl1 = 0
    ttl2 = 1
    ttl3 = 0
    ttl4 = 1


class _Packet8401:
    ch0 = 10
    ch1 = 20
    ch2 = 30
    ch3 = 40
    ext0 = 100
    ext1 = 200
    ttl1 = 1
    ttl2 = 0
    ttl3 = 1
    ttl4 = 0


# ---------------------------------------------------------------------------
# First construction
# ---------------------------------------------------------------------------


def test_first_construction_creates_file_with_header(tmp_path, app):
    path = tmp_path / "data.csv"
    with app.app_context():
        # Deferred-open (SINK-21): construction opens nothing; open() creates the
        # handle, row, and header. Here open() stands in for the worker.
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.open()
        sink.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ts,value,label", "first line must be the CSV header"


def test_construction_alone_creates_no_file(tmp_path, app):
    """SINK-21: a parent-built descriptor must not touch the filesystem or DB."""
    from app.models.output_file import OutputFile

    path = tmp_path / "unopened.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        assert not path.exists(), "construction must not create the file"
        assert sink.opened is False
        assert sink.managed is None
        assert (
            OutputFile.query.filter_by(path=str(path)).first() is None
        ), "construction must not create an output_files row"
        # Closing a never-opened descriptor is a clean no-op.
        sink.close()
    assert not path.exists()


def test_fresh_worker_database_context_registers_fk_models(tmp_path):
    """A worker process can commit OutputFile rows without the full app factory."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from app import create_app
    from app.database import db

    database_path = tmp_path / "worker.sqlite3"
    schema_app = create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}"},
    )
    with schema_app.app_context():
        db.create_all()

    worker_script = """
from pathlib import Path
import sys

from app.config import TestingConfig

database_path = Path(sys.argv[1])
csv_path = Path(sys.argv[2])

class WorkerConfig(TestingConfig):
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"

import app.config
app.config.get_config = lambda config_name=None: WorkerConfig

from app.output.managed_csv_sink import ManagedCsvSink

sink = ManagedCsvSink(
    path=csv_path,
    dataflow_id="worker-dataflow",
    fieldnames=["ts", "value"],
)
sink.open()
sink.close()
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    subprocess.run(
        [sys.executable, "-c", worker_script, str(database_path), str(tmp_path / "worker.csv")],
        check=True,
        cwd=environment["PYTHONPATH"],
        env=environment,
    )

    assert (tmp_path / "worker.csv").read_text(encoding="utf-8").splitlines() == [
        "ts,value"
    ]


def test_first_construction_writes_rows_after_header(tmp_path, app):
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.write_row({"ts": "100", "value": "1.0", "label": "a"})
        sink.write_row({"ts": "200", "value": "2.0", "label": "b"})
        sink.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ts,value,label"
    assert lines[1] == "100,1.0,a"
    assert lines[2] == "200,2.0,b"


def test_get_dict_contains_output_id_after_construction(tmp_path, app):
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.open()
        d = sink.get_dict()
        sink.close()

    assert d["output_id"] is not None, "get_dict() must carry output_id for reconstruction"
    assert d["path"] == str(path)
    assert d["fieldnames"] == _FIELDS
    assert d["dataflow_id"] == _DF


# ---------------------------------------------------------------------------
# Reconstruction (simulates _rebuild_dataflow)
# ---------------------------------------------------------------------------


def test_reconstruction_via_get_dict_appends_at_eof(tmp_path, app):
    """get_dict() → ManagedCsvSink(**{**d, 'pod': source}) continues at EOF."""
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.write_row({"ts": "1", "value": "10.0", "label": "x"})
        saved = sink.get_dict()
        sink.close()

        original_bytes = path.read_bytes()

        # Simulate _rebuild_dataflow: sink_class(**{**sink_dict, "pod": source})
        source = object()
        rebuilt = ManagedCsvSink(**{**saved, "pod": source})
        rebuilt.write_row({"ts": "2", "value": "20.0", "label": "y"})
        rebuilt.close()

    final_bytes = path.read_bytes()
    assert final_bytes.startswith(original_bytes), "original bytes must be intact at start of file"

    final_text = final_bytes.decode("utf-8")
    assert "2,20.0,y\r\n" in final_text, "new row must appear after reconstruction"


def test_reconstruction_uses_append_mode_not_write(tmp_path, app):
    """File handle opened during reconstruction must be in append ('ab') mode."""
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.open()
        saved = sink.get_dict()
        sink.close()

        rebuilt = ManagedCsvSink(**{**saved, "pod": None})
        rebuilt.open()
        assert rebuilt.managed._handle.mode == "ab", "reconstruction must open in append mode"
        rebuilt.close()


def test_reconstruction_produces_exactly_one_header(tmp_path, app):
    """After reconstruction, the file must contain the header exactly once."""
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.write_row({"ts": "1", "value": "1.0", "label": "a"})
        saved = sink.get_dict()
        sink.close()

        rebuilt = ManagedCsvSink(**{**saved, "pod": None})
        rebuilt.write_row({"ts": "2", "value": "2.0", "label": "b"})
        rebuilt.close()

    content = path.read_text(encoding="utf-8")
    assert content.count("ts,value,label") == 1, "header must appear exactly once"


def test_original_rows_intact_after_reconstruction(tmp_path, app):
    """Every row written before reconstruction must be present and unmodified."""
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.write_row({"ts": "1", "value": "1.0", "label": "first"})
        sink.write_row({"ts": "2", "value": "2.0", "label": "second"})
        saved = sink.get_dict()
        sink.close()

        rebuilt = ManagedCsvSink(**{**saved, "pod": None})
        rebuilt.write_row({"ts": "3", "value": "3.0", "label": "third"})
        rebuilt.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ts,value,label"
    assert lines[1] == "1,1.0,first"
    assert lines[2] == "2,2.0,second"
    assert lines[3] == "3,3.0,third"


def test_pod_kwarg_does_not_affect_open_mode(tmp_path, app):
    """The 'pod' kwarg injected by _rebuild_dataflow must be silently accepted."""
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        sink.open()
        saved = sink.get_dict()
        sink.close()

        original_bytes = path.read_bytes()

        # Pass a non-None pod — must not change behaviour
        rebuilt = ManagedCsvSink(**{**saved, "pod": object()})
        rebuilt.write_row({"ts": "99", "value": "9.9", "label": "z"})
        rebuilt.close()

    final_bytes = path.read_bytes()
    assert final_bytes.startswith(original_bytes), "pod kwarg must not truncate existing content"


def test_morelia_worker_flush_signature_writes_packet_rows(tmp_path, app):
    path = tmp_path / "stream.csv"
    fields = ["time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"]
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=fields)
        saved = sink.get_dict()
        sink.close()

        rebuilt = ManagedCsvSink(**{**saved, "pod": object()})
        rebuilt.flush(123, _Packet8206())
        rebuilt.close()

    assert path.read_text(encoding="utf-8").splitlines() == [
        "time,EEG1,EEG2,EEG3/EMG,TTL1,TTL2,TTL3,TTL4",
        "123,1,2,3,0,1,0,1",
    ]


def test_morelia_worker_flush_signature_writes_pod8401_rows(tmp_path, app):
    path = tmp_path / "stream-8401.csv"
    fields = [
        "time",
        "A",
        "B",
        "C",
        "D",
        "aEXT0",
        "aEXT1",
        "aTTL1",
        "aTTL2",
        "aTTL3",
        "aTTL4",
    ]
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=fields)
        saved = sink.get_dict()
        sink.close()

        rebuilt = ManagedCsvSink(**{**saved, "pod": object()})
        rebuilt.flush(456, _Packet8401())
        rebuilt.close()

    assert path.read_text(encoding="utf-8").splitlines() == [
        "time,A,B,C,D,aEXT0,aEXT1,aTTL1,aTTL2,aTTL3,aTTL4",
        "456,10,20,30,40,100,200,1,0,1,0",
    ]


# ---------------------------------------------------------------------------
# Respawn resume (packet 8): no output_id, but the dataflow owns the file
# ---------------------------------------------------------------------------


def _crash(sink: ManagedCsvSink) -> None:
    """Simulate a hard watchdog kill: the OS reclaims the file handle, but the
    OutputFile row is never marked closed and no output_id is handed forward."""
    sink._managed._handle.close()


def test_respawn_without_output_id_resumes_same_file_in_append(tmp_path, app):
    path = tmp_path / "data.csv"
    with app.app_context():
        first = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        first.write_row({"ts": "1", "value": "1.0", "label": "before-crash"})
        _crash(first)
        original_bytes = path.read_bytes()

        # The respawned watchdog rebuilds from the same manifest: same path,
        # same dataflow_id, NO output_id — must resume, not die on create.
        respawned = ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS)
        respawned.open()
        assert respawned.managed._handle.mode == "ab"
        respawned.write_row({"ts": "2", "value": "2.0", "label": "after-crash"})
        respawned.close()

    final = path.read_bytes()
    assert final.startswith(original_bytes), "pre-crash bytes must be intact"
    lines = final.decode("utf-8").splitlines()
    assert lines.count("ts,value,label") == 1, "header must not be rewritten on resume"
    assert lines[1] == "1,1.0,before-crash"
    assert lines[2] == "2,2.0,after-crash"


def test_respawn_resume_refuses_schema_mismatch(tmp_path, app):
    path = tmp_path / "data.csv"
    with app.app_context():
        first = ManagedCsvSink(
            path=path, dataflow_id=_DF, fieldnames=_FIELDS, schema_hash="hash-a"
        )
        first.open()
        _crash(first)

        with pytest.raises(ManagedCsvSinkError, match="schema_hash mismatch"):
            ManagedCsvSink(
                path=path, dataflow_id=_DF, fieldnames=_FIELDS, schema_hash="hash-b"
            ).open()


def test_foreign_file_at_path_is_still_refused(tmp_path, app):
    """A file this dataflow does not own (no OutputFile row) keeps create-once."""
    from app.output.managed_file import OutputFileAlreadyExistsError

    path = tmp_path / "foreign.csv"
    path.write_text("someone else's data\n", encoding="utf-8")
    with app.app_context(), pytest.raises(OutputFileAlreadyExistsError):
        ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS).open()


def test_other_dataflows_file_at_path_is_not_resumed(tmp_path, app):
    """A managed file owned by a DIFFERENT dataflow is never appended to."""
    from app.output.managed_file import OutputFileAlreadyExistsError

    path = tmp_path / "shared.csv"
    with app.app_context():
        other = ManagedCsvSink(path=path, dataflow_id="dataflow-other", fieldnames=_FIELDS)
        other.open()
        _crash(other)

        with pytest.raises(OutputFileAlreadyExistsError):
            ManagedCsvSink(path=path, dataflow_id=_DF, fieldnames=_FIELDS).open()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_reconstruction_with_unknown_output_id_raises(tmp_path, app):
    """Reconstruction with an output_id not in the DB raises ManagedCsvSinkError."""
    path = tmp_path / "ghost.csv"
    with app.app_context(), pytest.raises(ManagedCsvSinkError):
        ManagedCsvSink(
            path=path,
            dataflow_id=_DF,
            fieldnames=_FIELDS,
            output_id="00000000-0000-0000-0000-000000000000",
        ).open()
