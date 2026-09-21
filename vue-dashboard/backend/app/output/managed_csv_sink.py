"""Write CSV recordings and resume them after a worker restarts.

- DataFlow worker: delivers samples and owns the file.
- Morelia CSVSink: formats device packets as CSV rows.
- DictWriter: formats dictionary rows.
- ManagedOutputFile: writes bytes and tracks database progress.
"""

from __future__ import annotations

import csv
import io
import hashlib
import json
import math
import time
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from app.database import create_database_app, db
from app.domain.enums import DeviceType, SinkType
from app.models.output_file import OutputFile
from app.output import managed_file
from app.output.csv_schema import csv_fieldnames
from app.output.managed_file import ManagedOutputFile


class ManagedCsvSinkError(Exception):
    """The sink cannot open, resume, or write the requested recording."""


class ManagedCsvSink:
    """Coordinate CSV writing, file ownership, and recovery checks.

    - open(): create or validate the recording.
    - write_row(): write a dictionary.
    - flush(timestamp, packet): write a device packet.
    - flush(): save buffered data and progress.
    - close(): save progress and release resources.
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
        checkpoint_interval_sec: float = 1.0,
    ) -> None:
        # Store settings here. The worker opens the file later.
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
        if not math.isfinite(checkpoint_interval_sec) or checkpoint_interval_sec <= 0:
            raise ValueError("checkpoint_interval_sec must be positive and finite")
        self._checkpoint_interval_sec = checkpoint_interval_sec
        self._storage_schema_hash = schema_hash
        self._adapter: _CsvRecoveryAdapter | None = None
        self._device_csv = False
        self._dict_writer = None
        self._row_count = 0
        self._last_checkpoint = 0.0

        self._managed: ManagedOutputFile | None = None
        self._database_context = None
        self._opened = False
        self._closed = False

    # -- Open and close the recording ---------------------------------------

    @property
    def opened(self) -> bool:
        return self._opened

    def open(self) -> ManagedCsvSink:
        """Prepare the recording for writes in the DataFlow worker.

        - New recording: create the file and header.
        - Existing recording: validate before appending.
        - Already open: do nothing. Closed: raise an error.
        """
        if self._closed:
            raise ManagedCsvSinkError("cannot reopen a closed ManagedCsvSink")
        if self._opened:
            return self

        self._database_context = _ensure_database_context()
        try:
            path = Path(self._path)
            self._prepare_serializer()
            # Find the recording by ID, or by dataflow and path.
            if self._output_id is None:
                row = self._resumable_row(path)
            else:
                row = db.session.scalars(
                    db.select(OutputFile).where(OutputFile.output_id == self._output_id)
                ).first()
                if row is None:
                    raise ManagedCsvSinkError(
                        f"no output_files row for output_id={self._output_id!r}"
                    )
            if row is None:
                self._managed = managed_file.create(
                    path,
                    dataflow_id=self._dataflow_id,
                    sink_type=SinkType.CSV,
                    session_id=self._session_id,
                    device_id=self._device_id,
                    sink_id=self._sink_id,
                    schema_hash=self._storage_schema_hash,
                )
                # The header is not a data row.
                self._managed.write_buffered(self._header_bytes())
                self._managed.checkpoint(0)
            else:
                self._validate_identity(row, path)
                byte_offset, row_offset = row.byte_offset, row.row_offset
                self._managed = managed_file.reopen(
                    row, validate=lambda handle: self._validate_csv(handle, byte_offset, row_offset)
                )
            # Both writers share one file.
            target = _CsvTextTarget(self._managed)
            self._dict_writer = csv.DictWriter(target, fieldnames=self._fieldnames)
            if self._device_csv:
                self._adapter = _CsvRecoveryAdapter(
                    pod=self._pod, target=target, fieldnames=self._fieldnames
                )
            self._output_id = self._managed.record.output_id
            self._last_checkpoint = time.monotonic()
        except BaseException:
            # Release resources if setup fails.
            if self._managed is not None:
                with suppress(Exception):
                    self._managed.close(termination_reason="writer_failure", row_offset=self._row_count)
            self._closed = True
            self._release_database_context()
            raise

        self._opened = True
        return self

    def close(self) -> None:
        """Save final progress and release resources; repeated calls do nothing."""
        if self._closed:
            return
        try:
            if self._managed is not None:
                self._managed.close(row_offset=self._row_count)
        finally:
            self._closed = True
            self._release_database_context()

    def _release_database_context(self) -> None:
        """Release only the Flask context this sink created itself."""
        if self._database_context is not None:
            self._database_context.pop()
            self._database_context = None

    # -- Write samples and save progress ------------------------------------

    def write_row(self, row: dict) -> None:
        """Write one dictionary as a CSV row, opening the recording if needed."""
        if self._closed:
            raise ManagedCsvSinkError("cannot write to a closed ManagedCsvSink")
        if not self._opened:
            self.open()
        assert self._managed is not None
        self._dict_writer.writerow(row)
        self._row_count += 1
        self._maybe_checkpoint()

    def flush(self, *args: object) -> None:
        """Save progress or write a packet.

        - No arguments: flush bytes and save progress now.
        - (timestamp, packet): write its rows; checkpoint when due.
        """
        if not args:
            if self._opened and self._managed is not None:
                if not self._closed:
                    self._checkpoint()
            return
        if len(args) != 2:
            raise TypeError("flush() expects no args or (timestamp, packet)")
        timestamp, packet = args
        if self._closed:
            raise ManagedCsvSinkError("cannot write to a closed ManagedCsvSink")
        if not self._opened:
            self.open()
        if self._adapter is None:
            self.write_row(self._packet_row(timestamp, packet))
        else:
            before = self._adapter.rows_written
            try:
                self._adapter.write_packet(timestamp, packet)
            finally:
                # Count successful rows even if the packet fails partway through.
                self._row_count += self._adapter.rows_written - before
            self._maybe_checkpoint()

    def _checkpoint(self) -> None:
        """Flush file bytes, then save their position and the data-row count together."""
        self._managed.checkpoint(self._row_count)
        self._last_checkpoint = time.monotonic()

    def _maybe_checkpoint(self) -> None:
        """Save progress when due; this runs on writes, not on a background timer."""
        if time.monotonic() - self._last_checkpoint >= self._checkpoint_interval_sec:
            self._checkpoint()

    # -- Settings used to rebuild the sink ---------------------------------

    @property
    def managed(self) -> ManagedOutputFile | None:
        return self._managed

    def get_dict(self) -> dict:
        """Return settings for rebuilding the sink. The worker supplies pod.
        """
        return {
            "path": str(self._path),
            "dataflow_id": self._dataflow_id,
            "fieldnames": list(self._fieldnames),
            "output_id": self._output_id,
            "session_id": self._session_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "schema_hash": self._schema_hash,
            "observe_on_scheduler": self.observe_on_scheduler,
            "checkpoint_interval_sec": self._checkpoint_interval_sec,
        }

    def __enter__(self) -> ManagedCsvSink:
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- Check an existing recording before appending -----------------------

    def _resumable_row(self, path: Path) -> OutputFile | None:
        """Find this dataflow's database record for the path.

        open() validates the result before reuse.
        """
        row = db.session.scalars(
            db.select(OutputFile).where(
                OutputFile.dataflow_id == self._dataflow_id,
                OutputFile.path == str(path),
            )
        ).first()
        if row is None:
            return None  # create() will still refuse to overwrite an existing file.
        return row

    def _validate_identity(self, row: OutputFile, path: Path) -> None:
        """Require the same recording owner, path, and format, and an unfinished run."""
        expected = {
            "dataflow_id": self._dataflow_id, "session_id": self._session_id,
            "device_id": self._device_id, "sink_id": self._sink_id,
            "sink_type": str(SinkType.CSV),
        }
        for name, value in expected.items():
            if getattr(row, name) != value:
                raise ManagedCsvSinkError(f"cannot resume {path}: {name} mismatch")
        if Path(row.path).resolve() != path.resolve():
            raise ManagedCsvSinkError(f"cannot resume {path}: path mismatch")
        if row.acquisition_state == "complete":
            raise ManagedCsvSinkError(f"cannot resume {path}: acquisition is complete")
        if row.schema_hash != self._storage_schema_hash:
            raise ManagedCsvSinkError(
                f"cannot resume {path}: schema_hash mismatch "
                "(manifest or CSV serializer version changed; start a new recording)"
            )

    def _prepare_serializer(self) -> None:
        """Choose packet formatting and calculate an ID for the expected CSV format."""
        # Delay device imports until open().
        version = "managed-dict-csv-paired-checkpoint-v1"
        if self._pod is not None:
            from Morelia.Devices import AcquisitionDevice
            if isinstance(self._pod, AcquisitionDevice):
                try:
                    _CsvRecoveryAdapter.validate(pod=self._pod, fieldnames=self._fieldnames)
                except ValueError as exc:
                    raise ManagedCsvSinkError(str(exc)) from exc
                self._device_csv = True
                # Code-only refactors do not change the format version.
                version = "morelia-csv-v1"
        # Include the version to reject older channel mappings and checkpoints.
        signature = json.dumps([version, self._schema_hash, self._fieldnames])
        self._storage_schema_hash = hashlib.sha256(signature.encode("utf-8")).hexdigest()

    def _validate_csv(self, handle, byte_offset: int, row_offset: int) -> int:
        """Check the CSV before appending.

        - Validate the header and checkpoint position.
        - Count complete rows written after the checkpoint.
        - Reject malformed or unfinished trailing rows.
        - Trust earlier rows; do not scan the whole recording.
        """
        handle.seek(0, 2)
        size = handle.tell()
        if not size:
            raise ManagedCsvSinkError("cannot resume empty CSV")
        handle.seek(-1, 2)
        if handle.read(1) != b"\n":
            raise ManagedCsvSinkError("cannot resume CSV: incomplete trailing record")
        handle.seek(0)
        text = io.TextIOWrapper(handle, encoding="utf-8", newline="")
        try:
            # readline iterator keeps tell() available even for quoted headers.
            reader = csv.reader(iter(text.readline, ""), strict=True)
            if next(reader, None) != self._fieldnames:
                raise ManagedCsvSinkError("cannot resume CSV: header mismatch")
            header_end = text.tell()
            if byte_offset == 0 and row_offset == 0:
                byte_offset = header_end  # interrupted initial header checkpoint
            if (row_offset < 0 or byte_offset < header_end or byte_offset > size
                    or (byte_offset == header_end and row_offset != 0)):
                raise ManagedCsvSinkError("cannot resume CSV: invalid checkpoint offsets")
            text.seek(byte_offset - 1)
            if text.read(1) != "\n":
                raise ManagedCsvSinkError("cannot resume CSV: checkpoint is not a record boundary")
            text.seek(byte_offset)
            reader = csv.reader(text, strict=True)
            count = row_offset
            for row in reader:
                if len(row) != len(self._fieldnames):
                    raise ManagedCsvSinkError("cannot resume CSV: invalid record width")
                count += 1
        except (csv.Error, UnicodeError) as exc:
            raise ManagedCsvSinkError(f"cannot resume CSV: malformed record: {exc}") from exc
        finally:
            # Keep the underlying file open for appending.
            text.detach()
        self._row_count = count
        return count

    def _header_bytes(self) -> bytes:
        """Format the column names as one UTF-8 CSV header."""
        buf = io.StringIO()
        csv.DictWriter(buf, fieldnames=self._fieldnames, lineterminator="\r\n").writeheader()
        return buf.getvalue().encode("utf-8")

    def _packet_row(self, timestamp: object, packet: object) -> dict[str, object]:
        """Build one row for generic packet objects that do not use the device adapter."""
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


class _TextTarget(Protocol):
    """Describe the write(text) method needed by Python's CSV writer."""
    def write(self, value: str, /) -> int: ...


class _CountingWriter:
    """Count rows only after the CSV writer successfully writes them."""
    def __init__(self, target: _TextTarget) -> None:
        self._writer = csv.writer(target)
        self.rows_written = 0

    def writerow(self, row: Iterable[object]) -> int:
        result = self._writer.writerow(row)
        # A burst can fail after some rows; retain those successful writes.
        self.rows_written += 1
        return result


class _CsvRecoveryAdapter:
    """Use Morelia to format packets and count rows. ManagedCsvSink owns the file.
    """

    def __init__(
        self, *, pod: object, target: _TextTarget, fieldnames: Sequence[str]
    ) -> None:
        self.validate(pod=pod, fieldnames=fieldnames)
        from Morelia.Stream.sink.csv_sink import CSVSink

        self._writer = _CountingWriter(target)
        # Skip CSVSink.__enter__ and supply our writer; file_path is unused.
        self._serializer = CSVSink(file_path="", pod=pod)
        self._serializer._csv_writer = self._writer

    @staticmethod
    def validate(*, pod: object, fieldnames: Sequence[str]) -> None:
        """Check the device type and column order before creating a writer."""
        from Morelia.Devices import Pod8206HR, Pod8274D, Pod8401HR

        if isinstance(pod, Pod8206HR):
            device_type = DeviceType.POD8206HR
        elif isinstance(pod, Pod8401HR):
            device_type = DeviceType.POD8401HR
        elif isinstance(pod, Pod8274D):
            device_type = DeviceType.POD8274D
        else:
            raise ValueError(f"unsupported CSV device: {type(pod).__name__}")
        expected = csv_fieldnames(device_type, pod)
        if tuple(fieldnames) != expected:
            raise ValueError(
                f"CSV fieldnames do not match {device_type.value}: expected {expected!r}"
            )

    @property
    def rows_written(self) -> int:
        return self._writer.rows_written

    def write_packet(self, timestamp: int, packet: object) -> None:
        self._serializer.flush(timestamp, packet)


class _CsvTextTarget:
    """Send CSV text to ManagedOutputFile as UTF-8 bytes."""

    def __init__(self, managed: ManagedOutputFile) -> None:
        self._managed = managed

    def write(self, text: str) -> int:
        self._managed.write_buffered(text.encode("utf-8"))
        return len(text)


def _ensure_database_context():
    """Use the current Flask context, or create and return one for later cleanup."""
    from flask import has_app_context

    if has_app_context():
        return None

    context = create_database_app().app_context()
    context.push()
    return context
