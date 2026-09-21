"""Manage output files and the database records that describe them.

- Wraps a file handle and its database record.
- Writes bytes supplied by CSV, EDF, and PVFS sinks.
- Does not read devices or format samples.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import IO, Callable

from sqlalchemy.exc import IntegrityError

from app.database import db, transaction
from app.domain.enums import SinkType
from app.models.output_file import OutputFile


class OutputFileAlreadyExistsError(Exception):
    """Path already exists when creating a new managed output file."""


class OutputPathNotWritableError(Exception):
    """Parent directory does not exist or is not writable."""


class ComponentAllocationError(Exception):
    """A new file could not be assigned to continue an existing recording."""


class ManagedOutputFile:
    """Wrap a file and track its progress.

    - byte_offset: file position in bytes.
    - row_offset: data-row count supplied by the sink.
    - CSV calls write_buffered(), then checkpoint() to save both.
    - write() and flush() update only byte_offset.
    """

    def __init__(self, record: OutputFile, handle: IO[bytes]) -> None:
        self._record = record
        self._handle = handle

    @property
    def record(self) -> OutputFile:
        return self._record

    def write(self, data: bytes) -> int:
        """Write bytes and save the file position, without flushing the file buffer."""
        n = self._handle.write(data)
        with transaction():
            self._record.byte_offset = self._handle.tell()
        return n

    def advance_row_offset(self, rows: int) -> None:
        """Add to the stored row count in a separate database transaction."""
        with transaction():
            self._record.row_offset = self._record.row_offset + rows

    def write_buffered(self, data: bytes) -> int:
        """Write bytes without updating the database; call checkpoint() to save progress."""
        n = self._handle.write(data)
        if n != len(data):
            raise OSError(f"short output write: {n} of {len(data)} bytes")
        return n

    def checkpoint(self, row_offset: int) -> None:
        """Flush bytes, then save byte position and row count in one transaction.

        Supports process-crash recovery. No fsync: power loss can still lose data.
        """
        self._handle.flush()
        offset = self._handle.tell()
        with transaction():
            self._record.byte_offset = offset
            self._record.row_offset = row_offset

    def flush(self) -> None:
        """Flush buffered bytes and save the file position; leave the row count alone."""
        self._handle.flush()
        with transaction():
            self._record.byte_offset = self._handle.tell()

    def close(
        self,
        *,
        termination_reason: str | None = None,
        acquisition_state: str | None = None,
        row_offset: int | None = None,
    ) -> None:
        """Flush, save final progress and status, then close the file.

        Always close the handle, even if flushing or saving fails.
        """
        try:
            self._handle.flush()
            with transaction():
                self._record.byte_offset = self._handle.tell()
                if row_offset is not None:
                    self._record.row_offset = row_offset
                self._record.status = "closed"
                if termination_reason is not None:
                    self._record.termination_reason = termination_reason
                if acquisition_state is not None:
                    self._record.acquisition_state = acquisition_state
        finally:
            self._handle.close()

    def __enter__(self) -> ManagedOutputFile:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def create(
    path: str | Path,
    *,
    dataflow_id: str,
    sink_type: SinkType,
    output_id: str | None = None,
    session_id: int | None = None,
    device_id: str | None = None,
    sink_id: str | None = None,
    schema_hash: str | None = None,
    logical_sink_id: str | None = None,
    segment_index: int = 0,
    previous_output_id: str | None = None,
) -> ManagedOutputFile:
    """Create an empty file and its database record.

    - Save the database record before opening the file.
    - Refuse to overwrite an existing file.
    - The sink writes its own header.
    - Use allocate_continuation() for later files in the same recording.
    """
    path = Path(path)
    _assert_directory_writable(path)

    if path.exists():
        raise OutputFileAlreadyExistsError(f"output path already exists: {path}")

    _reclaim_stale_row(path)

    record = OutputFile(
        output_id=output_id or str(uuid.uuid4()),
        logical_sink_id=logical_sink_id or str(uuid.uuid4()),
        segment_index=segment_index,
        previous_output_id=previous_output_id,
        session_id=session_id,
        dataflow_id=dataflow_id,
        device_id=device_id,
        sink_id=sink_id,
        sink_type=str(sink_type),
        path=str(path),
        schema_hash=schema_hash,
        status="open",
        byte_offset=0,
        row_offset=0,
    )
    with transaction():
        db.session.add(record)

    try:
        handle = open(path, "xb")  # Fail if another process created the file first.
    except FileExistsError:
        raise OutputFileAlreadyExistsError(f"output path already exists: {path}")
    except PermissionError as exc:
        raise OutputPathNotWritableError(f"cannot create output file at {path}: {exc}") from exc

    return ManagedOutputFile(record, handle)


def reopen(
    record: OutputFile,
    *,
    validate: Callable[[IO[bytes]], int] | None = None,
) -> ManagedOutputFile:
    """Open the file for appending without erasing existing bytes.

    - With validate: require an existing file and check it before saving metadata.
      The callback returns the total row count.
    - Without validate: append mode may create a missing file.
    """
    path = Path(record.path)
    _assert_directory_writable(path)

    # CSV recovery must fail if the original file is missing.
    if validate is not None:
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_BINARY", 0)
        handle = os.fdopen(os.open(path, flags), "a+b")  # deliberately no O_CREAT
    else:
        handle = open(path, "ab")
    try:
        rows = validate(handle) if validate is not None else None
        handle.seek(0, os.SEEK_END)
        with transaction():
            record.status = "open"
            if rows is not None:
                record.byte_offset = handle.tell()
                record.row_offset = rows
    except BaseException:
        handle.close()
        raise

    return ManagedOutputFile(record, handle)


def allocate_continuation(
    previous: OutputFile,
    *,
    path: str | Path | None = None,
    termination_reason: str = "recovery",
    schema_hash: str | None = None,
) -> ManagedOutputFile:
    """Continue a recording in a new file after its previous writer has stopped.

    - Caller must stop the old writer first.
    - Keep logical_sink_id; increment segment_index; link to the previous file.
    - Default name: recording.recovery-0001.edf.
    - Reuse an already allocated next file on retry.
    - The database prevents duplicate segment numbers for one recording.
    """
    logical_sink_id = previous.logical_sink_id
    next_index = previous.segment_index + 1

    existing = _component_at(logical_sink_id, next_index)
    if existing is not None:
        if existing.previous_output_id != previous.output_id:
            raise ComponentAllocationError(
                f"ordinal {next_index} of logical output {logical_sink_id!r} "
                f"is already claimed by predecessor "
                f"{existing.previous_output_id!r}, not {previous.output_id!r}"
            )
        _mark_superseded(previous, termination_reason=termination_reason)
        return reopen(existing)  # Reuse the next file if it was already allocated.

    if path is None:
        base = _component_at(logical_sink_id, 0)
        base_path = Path(base.path) if base is not None else Path(previous.path)
        cont_path = _derive_continuation_path(base_path, next_index)
    else:
        cont_path = Path(path)

    try:
        managed = create(
            cont_path,
            dataflow_id=previous.dataflow_id,
            sink_type=SinkType(previous.sink_type),
            session_id=previous.session_id,
            device_id=previous.device_id,
            sink_id=previous.sink_id,
            schema_hash=schema_hash if schema_hash is not None else previous.schema_hash,
            logical_sink_id=logical_sink_id,
            segment_index=next_index,
            previous_output_id=previous.output_id,
        )
    except IntegrityError:
        # Another process may have created the next record after our initial check.
        db.session.rollback()
        winner = _component_at(logical_sink_id, next_index)
        if winner is not None and winner.previous_output_id == previous.output_id:
            return reopen(winner)
        raise

    # Mark the old file interrupted only after the new file was created successfully.
    _mark_superseded(previous, termination_reason=termination_reason)

    return managed


def _mark_superseded(previous: OutputFile, *, termination_reason: str) -> None:
    """Mark the previous file closed and interrupted without changing its bytes.

    Caller must stop the old writer first. Read its final size from disk.
    """
    path = Path(previous.path)
    with transaction():
        if path.exists():
            previous.byte_offset = path.stat().st_size
        previous.status = "closed"
        previous.termination_reason = termination_reason
        previous.acquisition_state = "interrupted"


def _component_at(logical_sink_id: str, segment_index: int) -> OutputFile | None:
    return db.session.scalars(
        db.select(OutputFile).where(
            OutputFile.logical_sink_id == logical_sink_id,
            OutputFile.segment_index == segment_index,
        )
    ).first()


def _derive_continuation_path(base_path: Path, segment_index: int) -> Path:
    """Add a numbered recovery suffix to the original recording's filename.

    For example, segment 1 of recording.edf is recording.recovery-0001.edf.
    """
    return base_path.with_name(
        f"{base_path.stem}.recovery-{segment_index:04d}{base_path.suffix}"
    )


def _assert_directory_writable(path: Path) -> None:
    directory = path.parent
    if not directory.exists() or not os.access(directory, os.W_OK):
        raise OutputPathNotWritableError(f"directory is not writable: {directory}")


def _reclaim_stale_row(path: Path) -> None:
    """Remove a database record for a path that create() found missing on disk.

    Allows filename reuse. Does not check for concurrent allocation.
    """
    existing = db.session.scalars(
        db.select(OutputFile).where(OutputFile.path == str(path))
    ).first()
    if existing is not None:
        with transaction():
            db.session.delete(existing)
