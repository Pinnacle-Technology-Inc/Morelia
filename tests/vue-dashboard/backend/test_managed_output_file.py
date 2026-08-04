"""Tests for app.output.managed_file — packet 4.1 acceptance criteria."""

import builtins
from pathlib import Path

import pytest

from app.database import db
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output.managed_file import (
    ComponentAllocationError,
    OutputFileAlreadyExistsError,
    OutputPathNotWritableError,
    _derive_continuation_path,
    allocate_continuation,
    create,
    reopen,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DF = "dataflow-test-001"
_ST = SinkType.CSV


def _row(app, record_id: int) -> OutputFile | None:
    with app.app_context():
        return db.session.get(OutputFile, record_id)


# ---------------------------------------------------------------------------
# create-once
# ---------------------------------------------------------------------------


def test_create_makes_file_and_db_row(tmp_path, app):
    path = tmp_path / "out.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        try:
            assert path.exists(), "file must exist after create"
            row = db.session.get(OutputFile, mof.record.id)
            assert row is not None
            assert row.status == "open"
            assert row.byte_offset == 0
            assert row.output_id is not None
            assert row.path == str(path)
        finally:
            mof.close()


def test_create_raises_when_path_already_exists(tmp_path, app):
    path = tmp_path / "existing.bin"
    path.write_bytes(b"original content")

    with app.app_context():
        with pytest.raises(OutputFileAlreadyExistsError):
            create(path, dataflow_id=_DF, sink_type=_ST)

    # original bytes must be untouched
    assert path.read_bytes() == b"original content"


def test_second_create_on_same_path_raises(tmp_path, app):
    path = tmp_path / "once.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        mof.close()
        with pytest.raises(OutputFileAlreadyExistsError):
            create(path, dataflow_id=_DF, sink_type=_ST)


# ---------------------------------------------------------------------------
# persist-before-open
# ---------------------------------------------------------------------------


def test_row_persisted_before_handle_opens(tmp_path, app, monkeypatch):
    """DB row must be committed before open() is called."""
    path = tmp_path / "ordered.bin"
    rows_at_open_time: list[int] = []

    _real_open = builtins.open

    def spy_open(p, mode="r", *args, **kwargs):
        if mode == "xb" and Path(p) == path:
            count = db.session.execute(
                db.select(db.func.count()).select_from(OutputFile).where(
                    OutputFile.path == str(path)
                )
            ).scalar()
            rows_at_open_time.append(count)
        return _real_open(p, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy_open)

    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        mof.close()

    assert rows_at_open_time == [1], "row must exist in DB before the file handle is opened"


# ---------------------------------------------------------------------------
# reopen-append
# ---------------------------------------------------------------------------


def test_reopen_appends_new_content_at_eof(tmp_path, app):
    path = tmp_path / "append.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        mof.write(b"hello")
        mof.close()

        row = db.session.get(OutputFile, mof.record.id)
        mof2 = reopen(row)
        mof2.write(b" world")
        mof2.close()

    assert path.read_bytes() == b"hello world"


def test_reopen_does_not_truncate_existing_bytes(tmp_path, app):
    path = tmp_path / "keep.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        mof.write(b"existing")
        mof.close()

        row = db.session.get(OutputFile, mof.record.id)
        mof2 = reopen(row)
        mof2.close()

    assert path.read_bytes() == b"existing"


def test_reopen_byte_offset_tracks_eof(tmp_path, app):
    path = tmp_path / "offset.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        mof.write(b"12345")
        mof.close()

        assert mof.record.byte_offset == 5

        row = db.session.get(OutputFile, mof.record.id)
        mof2 = reopen(row)
        mof2.write(b"678")
        mof2.close()

        assert mof2.record.byte_offset == 8

    assert path.read_bytes() == b"12345678"


def test_reopen_sets_status_open(tmp_path, app):
    path = tmp_path / "status.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        mof.close()
        assert mof.record.status == "closed"

        row = db.session.get(OutputFile, mof.record.id)
        mof2 = reopen(row)
        assert mof2.record.status == "open"
        mof2.close()


# ---------------------------------------------------------------------------
# non-writable path
# ---------------------------------------------------------------------------


def test_non_writable_raises_before_db_write(tmp_path, app):
    """A non-existent parent directory raises before any DB row is written."""
    bad_path = tmp_path / "ghost_dir" / "data.bin"
    with app.app_context():
        with pytest.raises(OutputPathNotWritableError):
            create(bad_path, dataflow_id=_DF, sink_type=_ST)

        count = db.session.execute(
            db.select(db.func.count()).select_from(OutputFile).where(
                OutputFile.path == str(bad_path)
            )
        ).scalar()
        assert count == 0, "no row should be written for a non-writable path"


# ---------------------------------------------------------------------------
# Packet 11: component identity minting (create)
# ---------------------------------------------------------------------------


def test_create_mints_component_0_identity(tmp_path, app):
    """A plain create() is component 0 of a fresh logical output."""
    path = tmp_path / "base.bin"
    with app.app_context():
        mof = create(path, dataflow_id=_DF, sink_type=_ST)
        try:
            row = mof.record
            assert row.logical_sink_id is not None
            assert row.segment_index == 0
            assert row.previous_output_id is None
        finally:
            mof.close()


def test_create_two_outputs_get_distinct_logical_ids(tmp_path, app):
    with app.app_context():
        a = create(tmp_path / "a.bin", dataflow_id=_DF, sink_type=_ST)
        b = create(tmp_path / "b.bin", dataflow_id=_DF, sink_type=_ST)
        try:
            assert a.record.logical_sink_id != b.record.logical_sink_id
        finally:
            a.close()
            b.close()


def test_create_accepts_explicit_component_identity(tmp_path, app):
    with app.app_context():
        mof = create(
            tmp_path / "seg.bin",
            dataflow_id=_DF,
            sink_type=_ST,
            logical_sink_id="logical-x",
            segment_index=3,
            previous_output_id="out-prev",
        )
        try:
            assert mof.record.logical_sink_id == "logical-x"
            assert mof.record.segment_index == 3
            assert mof.record.previous_output_id == "out-prev"
        finally:
            mof.close()


# ---------------------------------------------------------------------------
# Packet 11: continuation allocation (allocate_continuation)
# ---------------------------------------------------------------------------


def test_derive_continuation_path_is_deterministic():
    base = Path("/data/recording.edf")
    assert _derive_continuation_path(base, 1) == Path("/data/recording.recovery-0001.edf")
    assert _derive_continuation_path(base, 2) == Path("/data/recording.recovery-0002.edf")


def test_allocate_continuation_links_and_names(tmp_path, app):
    base = tmp_path / "recording.bin"
    with app.app_context():
        first = create(base, dataflow_id=_DF, sink_type=_ST)
        first.write(b"seg0")
        first.close()

        cont = allocate_continuation(first.record)
        try:
            assert cont.record.logical_sink_id == first.record.logical_sink_id
            assert cont.record.segment_index == 1
            assert cont.record.previous_output_id == first.record.output_id
            assert Path(cont.record.path) == tmp_path / "recording.recovery-0001.bin"
            assert Path(cont.record.path).exists()
        finally:
            cont.close()

        # Predecessor is now the interrupted, superseded component.
        prev = db.session.get(OutputFile, first.record.id)
        assert prev.acquisition_state == "interrupted"
        assert prev.termination_reason == "recovery"


def test_allocate_continuation_monotonic_chain(tmp_path, app):
    base = tmp_path / "chain.bin"
    with app.app_context():
        c0 = create(base, dataflow_id=_DF, sink_type=_ST)
        c0.close()
        c1 = allocate_continuation(c0.record)
        c1.close()
        c2 = allocate_continuation(c1.record)
        c2.close()

        assert c1.record.segment_index == 1
        assert c2.record.segment_index == 2
        # Continuation names are always derived from component 0's base name.
        assert Path(c1.record.path) == tmp_path / "chain.recovery-0001.bin"
        assert Path(c2.record.path) == tmp_path / "chain.recovery-0002.bin"
        assert c2.record.previous_output_id == c1.record.output_id
        assert c2.record.logical_sink_id == c0.record.logical_sink_id


def test_allocate_continuation_is_idempotent_on_retry(tmp_path, app):
    """Re-allocating for the same predecessor adopts the existing component."""
    base = tmp_path / "retry.bin"
    with app.app_context():
        c0 = create(base, dataflow_id=_DF, sink_type=_ST)
        c0.close()

        first = allocate_continuation(c0.record)
        first.write(b"payload")
        first.close()
        bytes_before = Path(first.record.path).read_bytes()

        second = allocate_continuation(c0.record)
        try:
            # Same ordinal, same output_id, same path — not a duplicate.
            assert second.record.output_id == first.record.output_id
            assert second.record.segment_index == 1
        finally:
            second.close()

        # Exactly one component exists at ordinal 1 for this logical output.
        count = db.session.execute(
            db.select(db.func.count())
            .select_from(OutputFile)
            .where(
                OutputFile.logical_sink_id == c0.record.logical_sink_id,
                OutputFile.segment_index == 1,
            )
        ).scalar()
        assert count == 1
        # The existing file was reopened in append mode, never overwritten.
        assert Path(first.record.path).read_bytes() == bytes_before


def test_allocate_continuation_adopts_concurrent_winner(tmp_path, app):
    """A pre-existing ordinal-1 row for our predecessor is adopted, not duplicated.

    Simulates the loser of a concurrent race: the winner already committed the
    continuation before we run.
    """
    base = tmp_path / "race.bin"
    with app.app_context():
        c0 = create(base, dataflow_id=_DF, sink_type=_ST)
        c0.close()

        # Winner allocates ordinal 1 first.
        winner = allocate_continuation(c0.record)
        winner.close()

        # Loser retries against the same predecessor: adopts the winner's row.
        loser = allocate_continuation(c0.record)
        try:
            assert loser.record.output_id == winner.record.output_id
        finally:
            loser.close()


def test_allocate_continuation_rejects_foreign_ordinal_claim(tmp_path, app):
    """An ordinal already owned by a different predecessor is an error."""
    base = tmp_path / "conflict.bin"
    with app.app_context():
        c0 = create(base, dataflow_id=_DF, sink_type=_ST)
        c0.close()

        # A row at ordinal 1 links back to some OTHER predecessor.
        intruder = OutputFile(
            output_id="out-intruder",
            logical_sink_id=c0.record.logical_sink_id,
            segment_index=1,
            previous_output_id="someone-else",
            dataflow_id=_DF,
            sink_type="csv",
            path=str(tmp_path / "intruder.bin"),
        )
        db.session.add(intruder)
        db.session.commit()

        with pytest.raises(ComponentAllocationError):
            allocate_continuation(c0.record)


# ---------------------------------------------------------------------------
# Packet 11: user-stop completion closes without allocating a continuation
# ---------------------------------------------------------------------------


def test_user_stop_close_allocates_no_continuation(tmp_path, app):
    base = tmp_path / "userstop.bin"
    with app.app_context():
        mof = create(base, dataflow_id=_DF, sink_type=_ST)
        mof.write(b"data")
        mof.close(termination_reason="clean", acquisition_state="complete")

        row = db.session.get(OutputFile, mof.record.id)
        assert row.status == "closed"
        assert row.acquisition_state == "complete"
        assert row.termination_reason == "clean"

        # No continuation component was created for this logical output.
        count = db.session.execute(
            db.select(db.func.count())
            .select_from(OutputFile)
            .where(OutputFile.logical_sink_id == row.logical_sink_id)
        ).scalar()
        assert count == 1
