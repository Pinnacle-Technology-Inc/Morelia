"""Verify exclusive allocation and preservation of existing component evidence."""

import sqlite3
from pathlib import Path

import pytest
from app.database import db
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output import managed_file
from sqlalchemy import event


def _snapshot():
    db.session.expire_all()
    return [dict(row) for row in db.session.execute(
        db.select(OutputFile.__table__).order_by(OutputFile.id)
    ).mappings()]


def _bytes(paths):
    return {str(path): path.read_bytes() if path.exists() else None for path in paths}


def _record(path, *, logical="oracle-logical", index=0, previous=None, status="open"):
    row = OutputFile(
        output_id=f"{logical}-{index}", logical_sink_id=logical,
        segment_index=index, previous_output_id=previous,
        dataflow_id="oracle-dataflow", device_id="oracle-device", sink_id="oracle-sink",
        sink_type=str(SinkType.PVFS), path=str(path), schema_hash="oracle-schema",
        status=status, acquisition_state="interrupted", artifact_state="merge_pending",
        termination_reason="writer_failure", delivery_state="degraded",
        byte_offset=17, row_offset=23, byte_loss=5, sample_loss=7,
        finalization_id="oracle-finalization", finalizer_fence_token=29,
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.mark.parametrize("state", ["missing", "empty", "nonempty", "closed"])
def test_fresh_successor_rejection_preserves_every_column_and_byte(app, tmp_path, state):
    predecessor_path = tmp_path / "original.pvfs"
    successor_path = tmp_path / "successor.pvfs"
    predecessor_path.write_bytes(b"previous native component")
    if state != "missing":
        successor_path.write_bytes(b"existing native component" if state in {"nonempty", "closed"} else b"")
    with app.app_context():
        previous = _record(predecessor_path)
        _record(successor_path, index=1, previous=previous.output_id,
                status="closed" if state == "closed" else "open")
        before_rows, before_bytes = _snapshot(), _bytes([predecessor_path, successor_path])
        with pytest.raises(managed_file.ComponentAllocationError):
            managed_file.allocate_continuation(previous, require_new_file=True)
        assert _snapshot() == before_rows
        assert _bytes([predecessor_path, successor_path]) == before_bytes


@pytest.mark.parametrize("state", ["missing", "empty", "nonempty", "closed"])
def test_fresh_unique_constraint_race_preserves_winner(app, tmp_path, monkeypatch, state):
    previous_path, winner_path, loser_path = [tmp_path / name for name in (
        "previous.pvfs", "winner.pvfs", "loser.pvfs"
    )]
    previous_path.write_bytes(b"previous native component")
    if state != "missing":
        winner_path.write_bytes(b"winner bytes" if state in {"nonempty", "closed"} else b"")
    with app.app_context():
        previous = _record(previous_path)
        _record(winner_path, index=1, previous=previous.output_id,
                status="closed" if state == "closed" else "open")
        before_rows = _snapshot()
        before_bytes = _bytes([previous_path, winner_path, loser_path])
        real_lookup = managed_file._component_at
        hidden = False
        database_errors = []

        def stale_first_lookup(logical, index):
            nonlocal hidden
            if index == 1 and not hidden:
                hidden = True
                return None
            return real_lookup(logical, index)

        def capture_constraint(context):
            database_errors.append(context.original_exception)

        monkeypatch.setattr(managed_file, "_component_at", stale_first_lookup)
        event.listen(db.engine, "handle_error", capture_constraint)
        try:
            with pytest.raises(managed_file.ComponentAllocationError):
                managed_file.allocate_continuation(previous, path=loser_path, require_new_file=True)
        finally:
            event.remove(db.engine, "handle_error", capture_constraint)
        assert any(isinstance(error, sqlite3.IntegrityError) and "UNIQUE constraint" in str(error)
                   for error in database_errors)
        assert _snapshot() == before_rows
        assert _bytes([previous_path, winner_path, loser_path]) == before_bytes


@pytest.mark.parametrize("state", ["missing_row", "empty_path", "nonempty_path"])
def test_fresh_create_does_not_reclaim_existing_ownership(app, tmp_path, state):
    path = tmp_path / "owned.pvfs"
    with app.app_context():
        if state == "missing_row":
            _record(path)
        else:
            path.write_bytes(b"" if state == "empty_path" else b"existing bytes")
        before_rows, before_bytes = _snapshot(), _bytes([path])
        with pytest.raises((managed_file.ComponentAllocationError, managed_file.OutputFileAlreadyExistsError)):
            managed_file.create(path, dataflow_id="oracle-dataflow", sink_type=SinkType.PVFS,
                                require_new_file=True)
        assert _snapshot() == before_rows
        assert _bytes([path]) == before_bytes


def test_fresh_continuation_releases_only_its_empty_claim_once(app, tmp_path):
    path = tmp_path / "previous.pvfs"
    path.write_bytes(b"previous bytes")
    with app.app_context():
        previous = _record(path)
        previous_identity = previous.output_id, previous.logical_sink_id
        reservation = managed_file.allocate_continuation(previous, require_new_file=True)
        successor = reservation.record
        assert (successor.previous_output_id, successor.logical_sink_id) == previous_identity
        assert successor.segment_index == 1
        before_rows = _snapshot()
        reservation.release_file_placeholder()
        assert reservation._handle.closed
        assert Path(successor.path).read_bytes() == b""
        assert path.read_bytes() == b"previous bytes"
        assert _snapshot() == before_rows
        with pytest.raises(managed_file.ComponentAllocationError):
            reservation.release_file_placeholder()
        assert _snapshot() == before_rows


@pytest.mark.parametrize("fault", ["buffered_write", "external_write", "closed", "unowned", "missing", "replaced"])
def test_release_rejects_invalid_claim_without_metadata_change(app, tmp_path, monkeypatch, fault):
    path = tmp_path / "reservation.pvfs"
    with app.app_context():
        reservation = managed_file.create(
            path, dataflow_id="oracle-dataflow", sink_type=SinkType.PVFS,
            require_new_file=fault != "unowned",
        )
        try:
            if fault == "buffered_write":
                reservation.write_buffered(b"buffered data")
            elif fault == "external_write":
                with path.open("ab") as external:
                    external.write(b"external data")
            elif fault == "closed":
                reservation._handle.close()
            elif fault in {"missing", "replaced"}:
                alternate_path = tmp_path / "unrelated-empty.pvfs"
                alternate_path.write_bytes(b"")
                alternate_stat = alternate_path.stat()
                real_stat = managed_file.os.stat

                def changed_path_stat(candidate, *args, **kwargs):
                    if str(candidate) == str(path):
                        if fault == "missing":
                            raise FileNotFoundError(str(path))
                        return alternate_stat
                    return real_stat(candidate, *args, **kwargs)

                monkeypatch.setattr(managed_file.os, "stat", changed_path_stat)
            before_rows = _snapshot()
            before_bytes = path.read_bytes()
            with pytest.raises(managed_file.ComponentAllocationError):
                reservation.release_file_placeholder()
            assert _snapshot() == before_rows
            assert path.read_bytes() == before_bytes
            if fault != "closed":
                assert not reservation._handle.closed
        finally:
            reservation._handle.close()


@pytest.mark.parametrize("sink_type", [SinkType.CSV, SinkType.EDF])
def test_default_allocator_still_reuses_existing_successor(app, tmp_path, sink_type):
    with app.app_context():
        original = managed_file.create(tmp_path / f"recording.{sink_type}",
                                       dataflow_id="oracle-dataflow", sink_type=sink_type)
        original.write_buffered(b"original bytes")
        original.close()
        successor = managed_file.allocate_continuation(original.record)
        successor.write_buffered(b"successor bytes")
        successor.close()
        successor_id = successor.record.output_id
        reused = managed_file.allocate_continuation(original.record)
        try:
            assert reused.record.output_id == successor_id
            assert reused.record.status == "open"
            assert Path(reused.record.path).read_bytes() == b"successor bytes"
            assert len(_snapshot()) == 2
        finally:
            reused.close()


@pytest.mark.parametrize("sink_type", [SinkType.CSV, SinkType.EDF])
def test_default_create_still_reclaims_a_missing_file_row(app, tmp_path, sink_type):
    path = tmp_path / f"recording.{sink_type}"
    with app.app_context():
        stale = _record(path)
        stale_output_id = stale.output_id
        replacement = managed_file.create(path, dataflow_id="oracle-dataflow", sink_type=sink_type)
        try:
            assert replacement.record.output_id != stale_output_id
            assert len(_snapshot()) == 1
            assert path.read_bytes() == b""
        finally:
            replacement.close()
