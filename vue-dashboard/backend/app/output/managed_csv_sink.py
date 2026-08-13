"""Writes session samples to a CSV file.

Only the DataFlow worker may open the file. The parent builds and rebuilds
sink descriptors during the recovery process, but never opens them.

Rebuild a sink with:
    ManagedCsvSink(**{**sink.get_dict(), "pod": source})

open()
    With ``output_id``: reopen that file in append mode (no second header).
    Without ``output_id``: create the file and write the header once. If this
    dataflow already has the same path open (worker respawn), append instead.

Methods
    open()            Open the file. Safe to call more than once. Worker only.
    write_row()/flush Write one sample. Opens on first use if needed.
    get_dict()        Snapshot for rebuilding in another process.
                      Includes ``output_id`` after open; else ``None``.
    close()           Close the file. Safe to call more than once.
                      No-op if never opened.
    recover           Rebuild from get_dict() and open() again — same path,
                      or a linked continuation file.
"""

from __future__ import annotations

import csv
import io
from contextlib import suppress
from pathlib import Path

from app.database import create_database_app, db
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output import managed_file
from app.output.managed_file import ManagedOutputFile


class ManagedCsvSinkError(Exception):
    """Raised when a required OutputFile row cannot be found on reconstruction."""


class ManagedCsvSink:
    """CSV sink backed by a ManagedOutputFile, with worker-only handle ownership.

    Invariants:
    - Construction opens nothing (SINK-21): the live handle exists only in the
      worker that calls open() (directly, via ``with``, or via the first write).
    - Header is written exactly once, during the opening first construction.
    - get_dict() -> constructor round-trip reopens the same file in append mode.
    - close() is idempotent and safe to call on a never-opened descriptor.
    - The ``pod`` kwarg injected by Morelia reconstruction is accepted and ignored.
    """

    supports_missing_samples = True

    def __init__(
        self,
        *,
        path: str | Path,
        dataflow_id: str,
        fieldnames: list[str],
        output_id: str | None = None,
        session_id: int | None = None,
        device_id: str | None = None,
        sink_id: str | None = None,
        schema_hash: str | None = None,
        pod: object = None,
        observe_on_scheduler: str | None = None,
    ) -> None:
        # Descriptor only. No filesystem, database, or handle work happens here —
        # that is deferred to open() so the parent watchdog process can build and
        # rebuild these without ever owning a live CSV handle.
        self._path = path
        self._fieldnames = list(fieldnames)
        self._dataflow_id = dataflow_id
        self._output_id = output_id
        self._session_id = session_id
        self._device_id = device_id
        self._sink_id = sink_id
        self._schema_hash = schema_hash
        self._pod = pod
        self.observe_on_scheduler = observe_on_scheduler

        self._managed: ManagedOutputFile | None = None
        self._database_context = None
        self._opened = False
        self._closed = False

    # -- lifecycle ----------------------------------------------------------

    @property
    def opened(self) -> bool:
        return self._opened

    def open(self) -> ManagedCsvSink:
        """Open (or resume) the live CSV handle. Worker-side, idempotent.

        This is the ONLY place a physical file, ``output_files`` row, or header
        is created. It must run inside the DataFlow worker; the parent watchdog
        process never calls it. Repeated calls are no-ops once opened.
        """
        if self._opened:
            return self
        if self._closed:
            raise ManagedCsvSinkError("cannot reopen a closed ManagedCsvSink")

        self._database_context = _ensure_database_context()
        path = Path(self._path)

        if self._output_id is None:
            resumable = self._resumable_row(path)
            if resumable is not None:
                self._managed = managed_file.reopen(resumable)
            else:
                self._managed = managed_file.create(
                    path,
                    dataflow_id=self._dataflow_id,
                    sink_type=SinkType.CSV,
                    session_id=self._session_id,
                    device_id=self._device_id,
                    sink_id=self._sink_id,
                    schema_hash=self._schema_hash,
                )
                self._write_header_or_fail()
        else:
            row = db.session.scalars(
                db.select(OutputFile).where(OutputFile.output_id == self._output_id)
            ).first()
            if row is None:
                # Nothing was allocated — release the context and refuse. There is
                # no half-open handle to mark failed here.
                self._release_database_context()
                raise ManagedCsvSinkError(
                    f"no output_files row for output_id={self._output_id!r}"
                )
            self._managed = managed_file.reopen(row)

        self._opened = True
        return self

    def _write_header_or_fail(self) -> None:
        """Write the one-time header; on failure close and mark the component failed.

        Failure handling (packet spec): the row + handle already exist from
        create(); if the header write fails we must not pretend acquisition
        started successfully — close the handle and record a writer failure.
        """
        assert self._managed is not None
        try:
            self._managed.write(self._header_bytes())
            self._managed.flush()
        except Exception:
            with suppress(Exception):
                self._managed.close(termination_reason="writer_failure")
            self._release_database_context()
            raise

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self._managed is not None:
                self._managed.close()
        finally:
            self._closed = True
            self._release_database_context()

    def _release_database_context(self) -> None:
        if self._database_context is not None:
            self._database_context.pop()
            self._database_context = None

    # -- writes -------------------------------------------------------------

    def write_row(self, row: dict) -> None:
        if not self._opened:
            self.open()
        assert self._managed is not None
        self._managed.write(self._encode_row(row))
        self._managed.advance_row_offset(1)

    def flush(self, *args: object) -> None:
        if not args:
            if self._opened and self._managed is not None:
                self._managed.flush()
            return
        if len(args) != 2:
            raise TypeError("flush() expects no args or (timestamp, packet)")
        timestamp, packet = args
        self.write_row(self._packet_row(timestamp, packet))

    # -- introspection / reconstruction ------------------------------------

    @property
    def managed(self) -> ManagedOutputFile | None:
        return self._managed

    def get_dict(self) -> dict:
        """Return kwargs sufficient to reconstruct this sink via __init__.

        Carries ``output_id`` only once opened; an unopened descriptor reports
        ``output_id=None`` so the reconstructing worker opens/resumes rather than
        reopening a row the parent never allocated.
        """
        if self._managed is not None:
            path = self._managed.record.path
            output_id = self._managed.record.output_id
        else:
            path = str(self._path)
            output_id = self._output_id
        return {
            "path": path,
            "dataflow_id": self._dataflow_id,
            "fieldnames": list(self._fieldnames),
            "output_id": output_id,
            "session_id": self._session_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "schema_hash": self._schema_hash,
            "observe_on_scheduler": self.observe_on_scheduler,
        }

    def __enter__(self) -> ManagedCsvSink:
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- resume / helpers ---------------------------------------------------

    def _resumable_row(self, path: Path) -> OutputFile | None:
        """This dataflow's own file at ``path``, if it can safely be resumed.

        A respawned watchdog worker rebuilds its sinks from the SAME manifest the
        crashed identity used, so it arrives here with no output_id while the
        crashed run's file already exists on disk. Resume-append it — same
        dataflow, same path, same schema — one continuous file across the crash.
        Anything else keeps create-once semantics: a file this dataflow does not
        own is never appended to, and a schema mismatch is refused rather than
        silently mixed.
        """
        if not path.exists():
            return None  # nothing to resume; create() reclaims any stale row
        row = db.session.scalars(
            db.select(OutputFile).where(
                OutputFile.dataflow_id == self._dataflow_id,
                OutputFile.path == str(path),
            )
        ).first()
        if row is None:
            return None  # foreign file at this path — create() will refuse it
        if row.schema_hash != self._schema_hash:
            raise ManagedCsvSinkError(
                f"cannot resume {path}: schema_hash mismatch "
                f"(existing {row.schema_hash!r} vs manifest {self._schema_hash!r})"
            )
        return row

    def _header_bytes(self) -> bytes:
        buf = io.StringIO()
        csv.DictWriter(buf, fieldnames=self._fieldnames, lineterminator="\r\n").writeheader()
        return buf.getvalue().encode("utf-8")

    def _encode_row(self, row: dict) -> bytes:
        buf = io.StringIO()
        csv.DictWriter(buf, fieldnames=self._fieldnames, lineterminator="\r\n").writerow(row)
        return buf.getvalue().encode("utf-8")

    def _packet_row(self, timestamp: object, packet: object) -> dict[str, object]:
        if getattr(packet, "is_missing_sample", False):
            return {
                field: timestamp if field in {"time", "timestamp", "ts"} else None
                for field in self._fieldnames
            }
        values = {
            "time": timestamp,
            "timestamp": timestamp,
            "ts": timestamp,
            "EEG1": getattr(packet, "ch0", None),
            "EEG2": getattr(packet, "ch1", None),
            "EEG3/EMG": getattr(packet, "ch2", None),
            "A": getattr(packet, "ch0", None),
            "B": getattr(packet, "ch1", None),
            "C": getattr(packet, "ch2", None),
            "D": getattr(packet, "ch3", None),
            "aEXT0": getattr(packet, "ext0", None),
            "aEXT1": getattr(packet, "ext1", None),
            "TTL1": getattr(packet, "ttl1", None),
            "TTL2": getattr(packet, "ttl2", None),
            "TTL3": getattr(packet, "ttl3", None),
            "TTL4": getattr(packet, "ttl4", None),
            "aTTL1": getattr(packet, "ttl1", None),
            "aTTL2": getattr(packet, "ttl2", None),
            "aTTL3": getattr(packet, "ttl3", None),
            "aTTL4": getattr(packet, "ttl4", None),
        }
        return {
            field: values.get(field, getattr(packet, field, None))
            for field in self._fieldnames
        }


def _ensure_database_context():
    from flask import has_app_context

    if has_app_context():
        return None

    context = create_database_app().app_context()
    context.push()
    return context
