"""Managed output file: create-once, reopen-append lifecycle backed by a DB row."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import IO

from sqlalchemy.exc import IntegrityError

from app.database import db, transaction
from app.domain.enums import SinkType
from app.models.output_file import OutputFile


class OutputFileAlreadyExistsError(Exception):
    """Path already exists when creating a new managed output file."""


class OutputPathNotWritableError(Exception):
    """Parent directory does not exist or is not writable."""


class ComponentAllocationError(Exception):
    """A continuation component could not be allocated for a logical output."""


class ManagedOutputFile:
    """Wraps a physical file handle alongside its OutputFile metadata row.

    Callers write through this object so byte_offset stays current in the DB after
    every write and flush, allowing 4.3 to record a gap boundary at any time.
    """

    def __init__(self, record: OutputFile, handle: IO[bytes]) -> None:
        self._record = record
        self._handle = handle

    @property
    def record(self) -> OutputFile:
        return self._record

    def write(self, data: bytes) -> int:
        n = self._handle.write(data)
        with transaction():
            self._record.byte_offset = self._handle.tell()
        return n

    def advance_row_offset(self, rows: int) -> None:
        with transaction():
            self._record.row_offset = self._record.row_offset + rows

    def flush(self) -> None:
        self._handle.flush()
        with transaction():
            self._record.byte_offset = self._handle.tell()

    def close(
        self,
        *,
        termination_reason: str | None = None,
        acquisition_state: str | None = None,
    ) -> None:
        """Close the handle and mark the component ``closed``.

        Optionally records why writing ended (``termination_reason`` such as
        ``clean``/``forced``/``recovery``) and the resulting acquisition
        lifecycle (``acquisition_state``). A user-stop completion passes
        ``acquisition_state="complete"``; it closes this component and — by
        design — never allocates a continuation.
        """
        self._handle.flush()
        with transaction():
            self._record.byte_offset = self._handle.tell()
            self._record.status = "closed"
            if termination_reason is not None:
                self._record.termination_reason = termination_reason
            if acquisition_state is not None:
                self._record.acquisition_state = acquisition_state
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
    """Create a new managed output file with exclusive creation.

    The metadata row is committed BEFORE the file handle is opened.
    Raises OutputFileAlreadyExistsError if the path already exists.
    Raises OutputPathNotWritableError if the parent directory is not writable.

    "Already exists" is decided by the filesystem alone, not by history: a
    leftover OutputFile row for this path from an earlier run whose file the
    operator has since deleted does not block reuse of that exact name — see
    _reclaim_stale_row.

    Component identity (packet 11)
    ------------------------------
    Every physical file is one *component* of a logical output. When
    ``logical_sink_id`` is omitted this is component 0 of a brand-new logical
    output and a fresh id is minted here; ``segment_index`` defaults to 0 and
    ``previous_output_id`` to NULL. Continuations pass an explicit
    ``logical_sink_id`` (shared with their predecessor), the next
    ``segment_index``, and the predecessor ``previous_output_id`` — see
    :func:`allocate_continuation`, which is the race-safe way to derive them.
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
        handle = open(path, "xb")  # exclusive binary create — raises FileExistsError on race
    except FileExistsError:
        raise OutputFileAlreadyExistsError(f"output path already exists: {path}")
    except PermissionError as exc:
        raise OutputPathNotWritableError(f"cannot create output file at {path}: {exc}") from exc

    return ManagedOutputFile(record, handle)


def reopen(record: OutputFile) -> ManagedOutputFile:
    """Reopen an existing managed output file in append mode.

    Existing bytes are preserved; writes land at EOF. Never truncates.
    Raises OutputPathNotWritableError if the parent directory is not writable.
    """
    path = Path(record.path)
    _assert_directory_writable(path)

    handle = open(path, "ab")  # binary append — writes always go to EOF
    with transaction():
        record.status = "open"

    return ManagedOutputFile(record, handle)


def allocate_continuation(
    previous: OutputFile,
    *,
    path: str | Path | None = None,
    termination_reason: str = "recovery",
    schema_hash: str | None = None,
) -> ManagedOutputFile:
    """Allocate the next physical component of an existing logical output.

    Used by error-triggered recovery: the predecessor's writer must already be
    closed. This mints NO new ``logical_sink_id`` — the continuation shares
    ``previous.logical_sink_id``, takes ``segment_index = previous.segment_index
    + 1``, and links back through ``previous_output_id = previous.output_id``.
    The unique ``(logical_sink_id, segment_index)`` constraint guarantees one
    component per ordinal even under concurrent allocation.

    Deterministic name: component 0 owns the base requested name; each
    continuation ``N`` is ``<stem>.recovery-<NNNN><suffix>`` derived from
    component 0's path (override with ``path`` when a format needs its own
    scheme). Example: ``recording.edf`` → ``recording.recovery-0001.edf``.

    Idempotent under retry: if the continuation for this predecessor already
    exists, its existing file is reopened in append mode (never truncated) and
    the existing row returned — no duplicate ordinal, no overwrite. This also
    absorbs the loser of a concurrent race, which adopts the winner's component.

    Failure handling: :func:`create` commits the row before opening the file, so
    a failed allocation never mutates the immutable predecessor; only the freshly
    minted continuation row/handle is involved.
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
        return reopen(existing)  # idempotent retry / concurrent-loser adoption

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
        # A concurrent allocator won this ordinal between our check and insert.
        db.session.rollback()
        winner = _component_at(logical_sink_id, next_index)
        if winner is not None and winner.previous_output_id == previous.output_id:
            return reopen(winner)
        raise

    # The predecessor is now the interrupted, superseded component. Recorded only
    # after the continuation exists, so a failed allocation leaves it immutable.
    with transaction():
        previous.termination_reason = termination_reason
        previous.acquisition_state = "interrupted"

    return managed


def _component_at(logical_sink_id: str, segment_index: int) -> OutputFile | None:
    return db.session.scalars(
        db.select(OutputFile).where(
            OutputFile.logical_sink_id == logical_sink_id,
            OutputFile.segment_index == segment_index,
        )
    ).first()


def _derive_continuation_path(base_path: Path, segment_index: int) -> Path:
    """Deterministic continuation name derived from component 0's base path.

    ``recording.edf`` at ordinal 1 → ``recording.recovery-0001.edf``; the
    zero-padded ordinal keeps names lexicographically monotonic.
    """
    return base_path.with_name(
        f"{base_path.stem}.recovery-{segment_index:04d}{base_path.suffix}"
    )


def _assert_directory_writable(path: Path) -> None:
    directory = path.parent
    if not directory.exists() or not os.access(directory, os.W_OK):
        raise OutputPathNotWritableError(f"directory is not writable: {directory}")


def _reclaim_stale_row(path: Path) -> None:
    """Delete a leftover OutputFile row for ``path`` whose physical file is gone.

    ``path`` is a UNIQUE column (app/models/output_file.py), so without this
    a create() at a path some earlier run wrote to — and the operator later
    deleted by hand — would crash with a raw IntegrityError on insert instead
    of just working.

    Safe by construction: the caller only reaches here after confirming
    ``not path.exists()``, and open(path, "xb") creates the file on disk the
    moment a writer legitimately claims it — so any row still on file for
    this exact path, regardless of its status, cannot belong to a live
    writer. It's orphaned metadata from a run that's gone.
    """
    existing = db.session.scalars(
        db.select(OutputFile).where(OutputFile.path == str(path))
    ).first()
    if existing is not None:
        with transaction():
            db.session.delete(existing)
