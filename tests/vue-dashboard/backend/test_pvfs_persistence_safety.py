"""Requirement-derived checks for retained PVFS allocations and confirmed progress."""

import sqlite3
from pathlib import Path

import pytest
from app.database import create_database_app, db
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output import managed_file
from app.repositories.output_files import (
    latest_component,
    mark_pvfs_recording_gap,
    record_pvfs_progress,
)


@pytest.fixture
def persistence_app(tmp_path):
    app = create_database_app("testing", {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'evidence.sqlite3'}",
    })
    with app.app_context():
        db.create_all()
    return app


def _create(path, **kwargs):
    return managed_file.create(
        path, dataflow_id="flow", sink_id="sink", sink_type=SinkType.PVFS,
        require_new_file=True, **kwargs,
    )


def _snapshot():
    return [tuple(getattr(row, key) for key in (
        "output_id", "logical_sink_id", "segment_index", "previous_output_id", "path",
        "status", "acquisition_state", "termination_reason", "row_offset", "sample_loss",
    )) for row in db.session.scalars(db.select(OutputFile).order_by(OutputFile.id))]


@pytest.mark.parametrize("state", ["missing", "empty", "unreadable"])
def test_stale_descriptor_finds_latest_without_reading_or_reusing_it(
    persistence_app, tmp_path, state,
):
    with persistence_app.app_context():
        first = _create(tmp_path / "recording.pvfs")
        first.write(b"first component")
        first.close()
        second = managed_file.allocate_continuation(first.record, require_new_file=True)
        second.close()
        second_path = Path(second.record.path)
        if state == "missing":
            second_path.unlink()
        elif state == "unreadable":
            second_path.write_bytes(b"not a native container; must stay untouched")
        before = second_path.read_bytes() if second_path.exists() else None
        newest = latest_component(first.record.output_id, dataflow_id="flow", sink_id="sink")
        assert newest.output_id == second.record.output_id
        third = managed_file.allocate_continuation(newest, require_new_file=True)
        assert third.record.segment_index == 2
        assert third.record.previous_output_id == second.record.output_id
        third.close()
        assert (second_path.read_bytes() if second_path.exists() else None) == before
        assert (tmp_path / "recording.pvfs").read_bytes() == b"first component"
        assert db.session.scalar(db.select(db.func.count()).select_from(OutputFile)) == 3


@pytest.mark.parametrize("race", [False, True])
@pytest.mark.parametrize("has_bytes", [False, True])
def test_fresh_allocation_rejects_both_existing_successor_branches(
    persistence_app, tmp_path, monkeypatch, race, has_bytes,
):
    with persistence_app.app_context():
        first = _create(tmp_path / "recording.pvfs")
        first.close()
        second = managed_file.allocate_continuation(first.record, require_new_file=True)
        if has_bytes:
            second.write(b"winner bytes")
        second.close()
        before = _snapshot()
        original = managed_file._component_at
        calls = []
        if race:
            def hide_initial_successor(logical_id, ordinal):
                calls.append(ordinal)
                if calls == [1]:
                    return None
                return original(logical_id, ordinal)
            monkeypatch.setattr(managed_file, "_component_at", hide_initial_successor)
        # A different path reaches SQLite's ordinal constraint in the race case.
        with pytest.raises(managed_file.ComponentAllocationError):
            managed_file.allocate_continuation(
                first.record, path=tmp_path / "loser.pvfs", require_new_file=True,
            )
        assert _snapshot() == before
        assert Path(second.record.path).read_bytes() == (b"winner bytes" if has_bytes else b"")
        assert not (tmp_path / "loser.pvfs").exists()
        if race:
            assert calls == [1, 1]


def test_new_reservation_does_not_reclaim_missing_file_row(persistence_app, tmp_path):
    with persistence_app.app_context():
        path = tmp_path / "reserved.pvfs"
        first = _create(path)
        first.close()
        path.unlink()
        before = _snapshot()
        with pytest.raises(managed_file.ComponentAllocationError):
            _create(path)
        assert _snapshot() == before
        assert not path.exists()


@pytest.mark.parametrize("wrong", ["flow", "sink", "device", "kind", "link"])
def test_latest_lookup_rejects_foreign_or_broken_chain(persistence_app, tmp_path, wrong):
    with persistence_app.app_context():
        first = _create(tmp_path / "recording.pvfs")
        first.close()
        second = managed_file.allocate_continuation(first.record, require_new_file=True)
        second.close()
        if wrong == "flow":
            second.record.dataflow_id = "other"
        elif wrong == "sink":
            second.record.sink_id = "other"
        elif wrong == "device":
            second.record.device_id = "other"
        elif wrong == "kind":
            second.record.sink_type = SinkType.CSV
        else:
            second.record.previous_output_id = "foreign"
        db.session.commit()
        before = _snapshot()
        with pytest.raises(ValueError):
            latest_component(first.record.output_id, dataflow_id="flow", sink_id="sink")
        assert _snapshot() == before


def test_progress_and_gap_survive_fresh_connection_without_loss_inference(
    persistence_app, tmp_path,
):
    with persistence_app.app_context():
        managed = _create(tmp_path / "recording.pvfs")
        output_id = managed.record.output_id
        managed.release_file_placeholder()
        record_pvfs_progress(output_id, 7)
        record_pvfs_progress(output_id, 3)
        mark_pvfs_recording_gap(output_id, 5)
        db.session.remove()
    with sqlite3.connect(tmp_path / "evidence.sqlite3") as connection:
        stored = connection.execute(
            "SELECT row_offset, acquisition_state, termination_reason, status, sample_loss "
            "FROM output_files WHERE output_id=?", (output_id,),
        ).fetchone()
    assert stored == (7, "interrupted", "writer_failure", "open", 0)


@pytest.mark.parametrize("invalid", [-1, 1.5, True, "4", None])
def test_invalid_receipt_cannot_change_persisted_evidence(persistence_app, tmp_path, invalid):
    with persistence_app.app_context():
        managed = _create(tmp_path / "recording.pvfs")
        managed.close()
        before = _snapshot()
        with pytest.raises(ValueError):
            record_pvfs_progress(managed.record.output_id, invalid)
        with pytest.raises(ValueError):
            mark_pvfs_recording_gap(managed.record.output_id, invalid)
        assert _snapshot() == before


@pytest.mark.parametrize("method", [record_pvfs_progress, mark_pvfs_recording_gap])
def test_unknown_receipt_identity_is_rejected(persistence_app, method):
    with persistence_app.app_context(), pytest.raises(ValueError):
        method("missing-output", 3)


def test_placeholder_release_checks_identity_and_content(persistence_app, tmp_path):
    with persistence_app.app_context():
        managed = _create(tmp_path / "recording.pvfs")
        managed.write(b"unexpected content")
        managed._handle.flush()
        with pytest.raises(managed_file.ComponentAllocationError, match="not empty"):
            managed.release_file_placeholder()
        managed.close()
        assert (tmp_path / "recording.pvfs").read_bytes() == b"unexpected content"


def test_placeholder_release_is_single_use(persistence_app, tmp_path):
    with persistence_app.app_context():
        managed = _create(tmp_path / "recording.pvfs")
        managed.release_file_placeholder()
        with pytest.raises(managed_file.ComponentAllocationError, match="no live fresh"):
            managed.release_file_placeholder()
