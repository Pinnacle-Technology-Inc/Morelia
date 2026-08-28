"""Writes session samples to a PVFS file.

Only the DataFlow worker may open the file. The parent builds and rebuilds
sink descriptors, but never opens them.

Do not reopen an existing PVFS container to avoid data overwrite or data loss.
Always claim a new empty path first, then hand that path to PvfsDataFile.create.

After close, a segment is immutable. On error, recover keeps the old
segment and starts a linked continuation (recording.pvfs -> recording.recovery-0001.pvfs).
A clean close finalizes the current segment and does not allocate a continuation.

When use_writer_process=True, native PVFS I/O runs in a child process
this adapter owns. Nothing else may open the same segment.

Methods
    open()            Claim an empty path and create the container. Worker only.
    write_row()/flush Write one sample. Opens on first use if needed.
    get_dict()        Snapshot for rebuilding in another process.
    close()           Finalize the current segment. No continuation.
    recover           Finalize as interrupted; open a linked continuation.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import time
from collections.abc import Callable
from queue import Empty
from pathlib import Path
from uuid import uuid4

import structlog

from app.database import create_database_app, db, transaction
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output import managed_file
from app.output.managed_file import ManagedOutputFile
from Morelia.shutdown import ShutdownActor, ShutdownOutcome, ShutdownPhase

_log = structlog.get_logger(__name__)

# How long to wait for a writer child to drain and exit cleanly before it is
# force-terminated and the segment is marked forcibly closed.
_WRITER_JOIN_TIMEOUT = 15.0
_WRITER_TERMINATE_TIMEOUT = 2.0

_DEFAULT_SAMPLE_RATE = 400.0

# label -> packet attribute, covering Pod8206HR / Pod8401HR / Pod8274D channel maps
# (mirrors Morelia's PvfsSink.flush()). Labels absent here fall back to getattr.
_PACKET_FIELD_FOR_LABEL: dict[str, str] = {
    "EEG1": "ch0",
    "EEG2": "ch1",
    "EEG3/EMG": "ch2",
    "A": "ch0",
    "B": "ch1",
    "C": "ch2",
    "D": "ch3",
    "length_in_bytes": "length_in_bytes",
    "data": "data",
}


class ManagedPvfsSinkError(Exception):
    """Raised when a PVFS segment cannot be allocated, opened, or reconstructed."""


def _pvfs_writer_target(
    queue: "mp.Queue",
    stop_event,
    file_path: str,
    channels: tuple[str, ...],
    units: tuple[str, ...],
    sample_rate: float,
    device_preferences: list[dict] | None = None,
    shutdown_reporter=None,
    evidence_queue=None,
    sample_count=None,
) -> None:
    """Child-process PVFS writer. Owns the container's native I/O exclusively.

    Drains *queue* in batches, buffering one sample per channel and flushing a
    whole second of data at a time to the ``pvfs_tools`` container. Exits when
    *stop_event* is set and the queue is empty. The pvfs_tools import is lazy
    so importing this module never loads the native library.
    """
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    def report(phase, action, *, outcome=ShutdownOutcome.ACKNOWLEDGED, reason=None, error_type=None):
        if shutdown_reporter is None:
            return
        record = shutdown_reporter.emit(
            phase,
            action,
            outcome=outcome,
            reason=reason,
            error_type=error_type,
            actor=ShutdownActor.PVFS_WRITER,
            actor_pid=os.getpid(),
        )
        if evidence_queue is not None:
            evidence_queue.put(record)

    try:
        pvfs_data = PvfsDataFile()
        if not pvfs_data.create(file_path):
            raise ManagedPvfsSinkError("PVFS writer create returned false")

        start_time = HighTime.from_seconds(time.time())
        pvfs_data.set_experiment_info(
            name="Morelia PVFS recording",
            description="Streamed data from Morelia data collection",
            start_time=start_time,
        )
        for ch_name, unit in zip(channels, units):
            idf = pvfs_data.create_channel(ch_name, data_rate=sample_rate, unit=unit or "uV")
            if idf is None:
                raise ManagedPvfsSinkError(f"PVFS writer channel creation failed: {ch_name}")
            idf._delta_time = HighTime(0, 1.0 / sample_rate)

        if device_preferences:
            pvfs_data.set_device_preferences(device_preferences)

        n_channels = len(channels)
        buf: list[list[float]] = [[] for _ in channels]
        samples_written = 0
        flush_threshold = max(1, int(sample_rate))

        def write_buf() -> None:
            nonlocal samples_written
            if not buf[0]:
                return
            n = len(buf[0])
            block_start = HighTime.from_seconds(
                start_time.to_seconds() + samples_written / sample_rate
            )
            for ch_name, ch_buf in zip(channels, buf):
                idf = pvfs_data._indexed_data_files.get(ch_name)
                if idf is not None:
                    idf.append_block(block_start, ch_buf)
            samples_written += n
            if sample_count is not None:
                with sample_count.get_lock():
                    sample_count.value = samples_written
            for b in buf:
                b.clear()

        def drain_queue() -> None:
            while True:
                try:
                    item = queue.get_nowait()
                except Exception:
                    break
                for ch_idx in range(n_channels):
                    buf[ch_idx].append(item[ch_idx])
                if len(buf[0]) >= flush_threshold:
                    write_buf()

        while not stop_event.is_set():
            try:
                item = queue.get(timeout=0.1)
            except Exception:
                continue
            for ch_idx in range(n_channels):
                buf[ch_idx].append(item[ch_idx])
            drain_queue()
            if len(buf[0]) >= flush_threshold:
                write_buf()

        report(ShutdownPhase.SINKS_FINALIZING, "writer_stop_observed")
        drain_queue()
        write_buf()
        report(ShutdownPhase.SINKS_FINALIZING, "writer_queue_drained", outcome=ShutdownOutcome.COMPLETED)
        for idf in pvfs_data._indexed_data_files.values():
            if idf is not None:
                idf.flush(synchronous=True)
        pvfs_data.flush(synchronous=True)
        report(ShutdownPhase.SINKS_FINALIZING, "writer_native_flushed", outcome=ShutdownOutcome.COMPLETED)
        close_result = pvfs_data.close()
        if close_result is not True:
            raise ManagedPvfsSinkError("PVFS native close returned false")
        report(ShutdownPhase.SINKS_FINALIZING, "writer_native_closed", outcome=ShutdownOutcome.COMPLETED)
    except BaseException as exc:
        report(
            ShutdownPhase.PHASE_FAILED,
            "writer_shutdown_failed",
            outcome=ShutdownOutcome.FAILED,
            reason=str(exc),
            error_type=type(exc).__name__,
        )
        raise


class ManagedPvfsSink:
    """PVFS sink backed by exclusively-allocated, immutable, linked segments.

    Invariants:
    - Construction opens nothing and imports no native library (SINK-21).
    - The configured path is claimed create-once via ``managed_file.create``
      before any pvfs_tools container is created; a foreign file is
      refused, and the container is only ever created over a zero-byte placeholder.
    - Component containers are immutable after close; error recovery always
      allocates a linked continuation and never reopens/mutates a prior segment.
    - A clean stop marks the acquisition complete and allocates no continuation.
    - With ``use_writer_process`` the adapter is the sole owner of the writer
      child: it is started, fed, stopped, joined, and force-terminated by this
      object — never orphaned, never duplicated.
    - The ``pod`` kwarg injected by Morelia reconstruction is accepted; channels,
      units, and the sample rate are derived from it when not given explicitly.
    """

    supports_missing_samples = True

    def __init__(
        self,
        *,
        path: str | Path,
        dataflow_id: str,
        channels: list[str] | None = None,
        units: list[str] | None = None,
        sample_rate: float | None = None,
        output_id: str | None = None,
        logical_sink_id: str | None = None,
        segment_index: int = 0,
        previous_output_id: str | None = None,
        session_id: int | None = None,
        device_id: str | None = None,
        sink_id: str | None = None,
        schema_hash: str | None = None,
        pod: object = None,
        observe_on_scheduler: str | None = None,
        use_writer_process: bool = False,
        device_preferences: list[dict] | None = None,
    ) -> None:
        # Descriptor only — no filesystem, database, container, or native-import
        # work happens here so the parent watchdog can build/rebuild it safely.
        self._base_path = Path(path)
        self._dataflow_id = dataflow_id
        self._channels = list(channels) if channels is not None else None
        self._units = list(units) if units is not None else None
        self._sample_rate = sample_rate
        self._output_id = output_id
        self._logical_sink_id = logical_sink_id
        self._segment_index = segment_index
        self._previous_output_id = previous_output_id
        self._session_id = session_id
        self._device_id = device_id
        self._sink_id = sink_id
        self._schema_hash = schema_hash
        self._pod = pod
        self._use_writer_process = use_writer_process
        self._device_preferences = device_preferences
        # Morelia forces the scheduler off in writer-process mode (the child owns
        # all I/O), so mirror that so a reconstruction cannot double-schedule.
        self.observe_on_scheduler = None if use_writer_process else observe_on_scheduler

        self._record: OutputFile | None = None
        self._pvfs_data = None  # pvfs_tools PvfsDataFile, created worker-side in open()
        self._start_time = None
        self._buffer: list[list[float]] = []
        self._samples_written = 0
        self._forced_termination = False
        self._pvfs_close_failed = False
        self._on_sink_error: Callable[[dict], None] | None = None
        self._database_context = None
        self._opened = False
        self._closed = False

        # Writer-process handles (worker-side only).
        self._writer_queue: "mp.Queue | None" = None
        self._writer_proc: "mp.Process | None" = None
        self._writer_stop = None
        self._writer_evidence_queue = None
        self._writer_sample_count = None
        self._shutdown_reporter = None

    # -- lifecycle ----------------------------------------------------------

    @property
    def opened(self) -> bool:
        return self._opened

    @property
    def record(self) -> OutputFile | None:
        return self._record

    @property
    def use_writer_process(self) -> bool:
        return self._use_writer_process

    @property
    def writer_alive(self) -> bool:
        """True while the owned writer child is still running (test/introspection)."""
        return self._writer_proc is not None and self._writer_proc.is_alive()

    @property
    def forced_termination(self) -> bool:
        """True if the writer child had to be force-terminated on finalize."""
        return self._forced_termination

    def open(self) -> "ManagedPvfsSink":
        """Open the live PVFS segment. Worker-side, idempotent.

        First construction (no ``output_id``) mints component 0 at the configured
        path. Reconstruction (``output_id`` present) never reopens the closed
        segment — it allocates a linked continuation from it, honoring SINK-06.
        """
        if self._opened:
            return self
        if self._closed:
            raise ManagedPvfsSinkError("cannot reopen a closed ManagedPvfsSink")

        self._database_context = _ensure_database_context()
        self._resolve_channels_units_rate()

        if self._output_id is None:
            managed = managed_file.create(
                self._base_path,
                dataflow_id=self._dataflow_id,
                sink_type=SinkType.PVFS,
                session_id=self._session_id,
                device_id=self._device_id,
                sink_id=self._sink_id,
                schema_hash=self._schema_hash,
                logical_sink_id=self._logical_sink_id,
                segment_index=self._segment_index,
                previous_output_id=self._previous_output_id,
            )
            self._start_segment(managed)
        else:
            previous = db.session.scalars(
                db.select(OutputFile).where(OutputFile.output_id == self._output_id)
            ).first()
            if previous is None:
                self._release_database_context()
                raise ManagedPvfsSinkError(
                    f"no output_files row for output_id={self._output_id!r}"
                )
            # Never reopen a closed PVFS segment (SINK-06) — continue it.
            managed = managed_file.allocate_continuation(
                previous, termination_reason="recovery", schema_hash=self._schema_hash
            )
            self._start_segment(managed)

        self._opened = True
        return self

    def recover(self, *, termination_reason: str = "recovery") -> "ManagedPvfsSink":
        """Interruption handler: close component N, continue in linked component N+1.

        Component N is retained byte-for-byte and marked ``interrupted``; the
        successor is a fresh, exclusively-allocated container that links back
        through ``previous_output_id``. Subsequent writes land only in N+1; N is
        never reopened or mutated.
        """
        if not self._opened:
            raise ManagedPvfsSinkError("cannot recover a sink that was never opened")
        if self._closed:
            raise ManagedPvfsSinkError("cannot recover a closed sink")

        assert self._record is not None
        self._finalize_segment(
            termination_reason=termination_reason, acquisition_state="interrupted"
        )
        managed = managed_file.allocate_continuation(
            self._record, termination_reason=termination_reason, schema_hash=self._schema_hash
        )
        self._start_segment(managed)
        return self

    def close(self, *, termination_reason: str = "clean") -> None:
        """Clean stop: finalize the current component, mark acquisition complete.

        By design this allocates no continuation — a later start of the same
        hardware becomes a separate logical output (design doc section 6 "PVFS").
        The writer child (if any) is stopped and joined BEFORE the segment is
        recorded closed. Idempotent; a never-opened descriptor closes as a no-op.
        """
        if self._closed:
            return
        try:
            if self._opened and (self._pvfs_data is not None or self._writer_proc is not None):
                self._finalize_segment(
                    termination_reason=termination_reason, acquisition_state="complete"
                )
        finally:
            self._closed = True
            self._release_database_context()

    def __enter__(self) -> "ManagedPvfsSink":
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    def bind_error_callback(self, callback: Callable[[dict], None] | None) -> None:
        """Bind the worker-local sink reporter after Morelia reconstruction."""
        self._on_sink_error = callback

    def bind_shutdown_reporter(self, reporter) -> None:
        """Bind the worker-local shutdown reporter after sink reconstruction."""
        self._shutdown_reporter = reporter

    # -- writes -------------------------------------------------------------

    def write_frame(self, samples) -> None:
        """Append one sample per channel (ordered to match ``channels``)."""
        if not self._opened:
            self.open()
        if len(samples) != len(self._channels):
            raise ValueError(
                f"expected {len(self._channels)} channel samples, got {len(samples)}"
            )
        values = [_coerce(v) for v in samples]

        if self._use_writer_process:
            if self._writer_queue is not None:
                try:
                    self._writer_queue.put_nowait(tuple(values))
                except Exception:
                    # Unbounded queue: a failed put is an anomaly, not a drop path.
                    # Backlog/drop telemetry is a packet-18/26 concern (see handoff).
                    pass
            return

        for index, value in enumerate(values):
            self._buffer[index].append(value)
        if len(self._buffer[0]) >= self._flush_threshold:
            self._write_buffer()

    def write_row(self, row: dict) -> None:
        """Append one frame from a ``{channel_label: value}`` mapping."""
        self.write_frame([row.get(channel, 0.0) for channel in self._channels])

    def flush(self, *args: object) -> None:
        """No-arg: flush buffered blocks. ``(timestamp, packet)``: Morelia stream.

        The Morelia worker calls ``flush(timestamp, packet)`` once per packet; the
        timestamp is unused (PVFS block time is derived from ``samples_written``).
        """
        if not args:
            if (
                self._opened
                and not self._use_writer_process
                and self._buffer
                and len(self._buffer[0]) > 0
            ):
                self._write_buffer()
            return
        if len(args) != 2:
            raise TypeError("flush() expects no args or (timestamp, packet)")
        _timestamp, packet = args
        self.write_frame(self._frame_from_packet(packet))

    # -- introspection / reconstruction ------------------------------------

    def get_dict(self) -> dict:
        """Kwargs to reconstruct this sink. Carries the current segment identity.

        A reconstructing worker that opens this descriptor allocates a linked
        continuation (never a destructive reopen). ``path`` is the component-0
        base path; the continuation name is derived from it by the allocator.
        """
        if self._record is not None:
            output_id = self._record.output_id
            logical_sink_id = self._record.logical_sink_id
            segment_index = self._record.segment_index
        else:
            output_id = self._output_id
            logical_sink_id = self._logical_sink_id
            segment_index = self._segment_index
        return {
            "path": str(self._base_path),
            "dataflow_id": self._dataflow_id,
            "channels": list(self._channels) if self._channels is not None else None,
            "units": list(self._units) if self._units is not None else None,
            "sample_rate": self._sample_rate,
            "output_id": output_id,
            "logical_sink_id": logical_sink_id,
            "segment_index": segment_index,
            "session_id": self._session_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "schema_hash": self._schema_hash,
            "observe_on_scheduler": self.observe_on_scheduler,
            "use_writer_process": self._use_writer_process,
            "device_preferences": self._device_preferences,
        }

    def component_metadata(self) -> dict:
        """Channel/device metadata the packet-18 PVFS merger needs per component.

        Returned per-segment so the merger can verify channel identity/order,
        units, sample rate, and pinned device preferences match across linked
        components before a format-aware read-and-rewrite merge.
        """
        return {
            "logical_sink_id": self._logical_sink_id
            if self._record is None
            else self._record.logical_sink_id,
            "segment_index": self._segment_index
            if self._record is None
            else self._record.segment_index,
            "path": None if self._record is None else self._record.path,
            "channels": list(self._channels) if self._channels is not None else None,
            "units": list(self._units) if self._units is not None else None,
            "sample_rate": self._sample_rate,
            "device_preferences": self._device_preferences,
        }

    # -- segment machinery --------------------------------------------------

    @property
    def _flush_threshold(self) -> int:
        return max(1, int(self._sample_rate))

    def _start_segment(self, managed: ManagedOutputFile) -> None:
        """Adopt an allocated component: own its path with a fresh PVFS container.

        ``managed`` arrives holding the exclusive ``open(path, "xb")`` claim that
        reserved the path (and refused a foreign file). PVFS writing is owned by
        ``pvfs_tools`` (in-process) or the writer child, both of which create the
        container themselves, so the raw placeholder handle is dropped WITHOUT
        marking the row closed, then the container is created on the now-ours,
        empty path (create-over-empty is non-destructive; create-over-data is not).
        """
        self._record = managed.record
        _release_placeholder(managed)
        self._samples_written = 0
        self._forced_termination = False
        self._buffer = [[] for _ in self._channels]

        if self._use_writer_process:
            self._start_writer_process(self._record.path)
        else:
            self._start_in_process(self._record.path)

    def _start_in_process(self, path: str) -> None:
        from pvfs_tools.Core.pvfs_binding import HighTime
        from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

        pvfs_data = PvfsDataFile()
        if not pvfs_data.create(path):
            self._mark_record_failed("writer_failure")
            raise ManagedPvfsSinkError(f"PvfsDataFile.create failed for {path}")
        self._pvfs_data = pvfs_data
        self._start_time = HighTime.from_seconds(time.time())
        pvfs_data.set_experiment_info(
            name="Morelia PVFS recording",
            description="Streamed data from Morelia data collection",
            start_time=self._start_time,
        )
        for ch_name, unit in zip(self._channels, self._units):
            idf = pvfs_data.create_channel(
                ch_name, data_rate=self._sample_rate, unit=unit or "uV"
            )
            if idf is None:
                self._mark_record_failed("writer_failure")
                raise ManagedPvfsSinkError(f"failed to create PVFS channel {ch_name}")
            idf._delta_time = HighTime(0, 1.0 / self._sample_rate)
        if self._device_preferences:
            pvfs_data.set_device_preferences(self._device_preferences)

    def _start_writer_process(self, path: str) -> None:
        self._writer_queue = mp.Queue(maxsize=0)
        self._writer_evidence_queue = mp.Queue(maxsize=0) if self._shutdown_reporter is not None else None
        self._writer_sample_count = mp.Value("q", 0)
        self._writer_stop = mp.Event()
        self._writer_proc = mp.Process(
            target=_pvfs_writer_target,
            args=(
                self._writer_queue,
                self._writer_stop,
                path,
                tuple(self._channels),
                tuple(self._units),
                float(self._sample_rate),
                self._device_preferences,
                self._shutdown_reporter,
                self._writer_evidence_queue,
                self._writer_sample_count,
            ),
        )
        self._writer_proc.start()

    def _finalize_segment(self, *, termination_reason: str, acquisition_state: str) -> None:
        """Flush remaining data, close the container/child, mark the component closed.

        Best-effort per the packet's failure handling: if data cannot be flushed
        or the container cannot close cleanly, the component is retained (never
        reopened destructively) as a failed/interrupted component and the loss is
        recorded. The writer child is always stopped and joined before the DB row
        is transitioned so two owners can never coexist.
        """
        assert self._record is not None

        close_failure: str | None = None
        if self._use_writer_process:
            close_failure = self._stop_writer_process()
        else:
            close_failure = self._finalize_in_process(termination_reason)
            if close_failure is not None:
                termination_reason = "writer_failure"
        if self._forced_termination and termination_reason == "clean":
            termination_reason = "forced"
            close_failure = "PVFS writer process exceeded its shutdown timeout"

        path = self._record.path
        if close_failure is None:
            try:
                self._verify_finalized_container(path)
                self._emit_shutdown_action(
                    ShutdownPhase.SINKS_FINALIZING,
                    "pvfs_catalog_verified",
                    outcome=ShutdownOutcome.COMPLETED,
                )
            except Exception as exc:
                close_failure = f"PVFS finalized container verification failed: {exc}"
                termination_reason = "writer_failure"
                self._emit_shutdown_failure("pvfs_catalog_verification_failed", exc)

        if close_failure is not None:
            acquisition_state = "interrupted"
            self._emit_shutdown_failure("sink_close_failed", ManagedPvfsSinkError(close_failure))

        byte_size = os.path.getsize(path) if os.path.exists(path) else 0
        with transaction():
            self._record.status = "closed"
            self._record.termination_reason = termination_reason
            self._record.acquisition_state = acquisition_state
            self._record.byte_offset = byte_size
            self._record.row_offset = self._samples_written

        if close_failure is not None:
            self._report_close_failure(close_failure)
            raise ManagedPvfsSinkError(close_failure)

        _log.info(
            "pvfs_close_completed",
            dataflow_id=self._dataflow_id,
            device_id=self._device_id,
            sink_id=self._sink_id,
            output_id=self._record.output_id,
            samples_written=self._samples_written,
            byte_size=byte_size,
            channels=list(self._channels),
        )

    def _finalize_in_process(self, termination_reason: str) -> str | None:
        self._pvfs_close_failed = False
        failure: str | None = None
        if self._buffer and len(self._buffer[0]) > 0:
            buffered = len(self._buffer[0])
            try:
                self._write_buffer()
            except Exception as exc:
                self._record.sample_loss = self._record.sample_loss + buffered
                failure = f"PVFS final buffer flush failed: {type(exc).__name__}: {exc}"
        if self._pvfs_data is not None:
            try:
                for idf in self._pvfs_data._indexed_data_files.values():
                    if idf is not None:
                        idf.flush(synchronous=True)
                self._pvfs_data.flush(synchronous=True)
            except Exception as exc:
                self._pvfs_close_failed = True
                failure = failure or f"PVFS native flush failed: {type(exc).__name__}: {exc}"
            try:
                close_result = self._pvfs_data.close()
                if close_result is not True:
                    self._pvfs_close_failed = True
                    failure = failure or "PVFS native close returned false"
            except Exception as exc:
                self._pvfs_close_failed = True
                failure = failure or f"PVFS native close failed: {type(exc).__name__}: {exc}"
            finally:
                self._pvfs_data = None
        self._start_time = None
        return failure

    def _verify_finalized_container(self, path: str) -> None:
        """Verify the embedded catalog without opening the container for writing."""
        from pvfs_tools.Core.pvfs_binding import PvfsFile

        pvfs_file = None
        container_path = Path(path)
        catalog_path = container_path.with_name(
            f".{container_path.name}.verify-{uuid4().hex}.db3"
        )
        try:
            pvfs_file = PvfsFile.open(str(container_path))
            embedded_files = set(pvfs_file.get_file_list())
            if "experiment.db3" not in embedded_files:
                raise ManagedPvfsSinkError("embedded experiment.db3 is missing")

            pvfs_file.extract("experiment.db3", str(catalog_path))
            catalog_uri = f"{catalog_path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(catalog_uri, uri=True)
            try:
                rows = connection.execute(
                    "SELECT name FROM experiment_channel_information_table"
                ).fetchall()
            finally:
                connection.close()
            embedded_channels = {str(row[0]) for row in rows}
            missing_channels = [
                channel for channel in self._channels if channel not in embedded_channels
            ]
            if missing_channels:
                raise ManagedPvfsSinkError(
                    "finalized catalog missing expected channels: "
                    + ", ".join(missing_channels)
                )
        finally:
            if pvfs_file is not None:
                pvfs_file.close()
            try:
                catalog_path.unlink(missing_ok=True)
            except OSError:
                _log.warning(
                    "pvfs_verification_catalog_cleanup_failed",
                    path=str(catalog_path),
                )

    def _report_close_failure(self, reason: str) -> None:
        event = {
            "source_id": self._device_id or "unknown-source",
            "sink_id": self._sink_id or "unknown-sink",
            "sink_class": type(self).__name__,
            "failure_kind": "sink_close",
            "exception_type": "ManagedPvfsSinkError",
            "message": reason[:500],
            "state": "terminal",
            "last_success_seq": self._samples_written or None,
            "timestamp_ns": time.time_ns(),
            "sample_loss": 0 if self._record is None else self._record.sample_loss,
            "byte_loss": 0 if self._record is None else self._record.byte_loss,
        }
        _log.error(
            "pvfs_close_failed",
            dataflow_id=self._dataflow_id,
            device_id=self._device_id,
            sink_id=self._sink_id,
            output_id=None if self._record is None else self._record.output_id,
            samples_written=self._samples_written,
            reason=reason,
        )
        if self._on_sink_error is not None:
            try:
                self._on_sink_error(event)
            except Exception:
                _log.warning(
                    "pvfs_close_failure_callback_failed",
                    dataflow_id=self._dataflow_id,
                    sink_id=self._sink_id,
                )

    def _stop_writer_process(self) -> str | None:
        if self._writer_stop is not None:
            self._writer_stop.set()
        proc = self._writer_proc
        if proc is not None:
            proc.join(timeout=_WRITER_JOIN_TIMEOUT)
            if proc.is_alive():
                self._forced_termination = True
                proc.terminate()
                proc.join(timeout=_WRITER_TERMINATE_TIMEOUT)
        required = {
            "writer_stop_observed",
            "writer_queue_drained",
            "writer_native_flushed",
            "writer_native_closed",
        }
        observed = set()
        if self._writer_evidence_queue is not None:
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and required - observed:
                try:
                    record = self._writer_evidence_queue.get(timeout=0.05)
                except Empty:
                    continue
                observed.add(getattr(record, "action", None))
        if self._writer_sample_count is not None:
            self._samples_written = int(self._writer_sample_count.value)
        # Release the queue's feeder resources deterministically.
        if self._writer_queue is not None:
            try:
                self._writer_queue.close()
                self._writer_queue.join_thread()
            except Exception:
                pass
        if self._writer_evidence_queue is not None:
            try:
                self._writer_evidence_queue.close()
                self._writer_evidence_queue.join_thread()
            except Exception:
                pass
        self._writer_proc = None
        self._writer_queue = None
        self._writer_stop = None
        self._writer_evidence_queue = None
        self._writer_sample_count = None
        if self._forced_termination:
            return "PVFS writer process was force-terminated"
        if proc is not None and getattr(proc, "exitcode", 0) != 0:
            return f"PVFS writer process exited with code {proc.exitcode}"
        if self._shutdown_reporter is not None and required - observed:
            return "PVFS writer shutdown acknowledgement missing: " + ", ".join(sorted(required - observed))
        return None

    def _emit_shutdown_action(self, phase, action, *, outcome=ShutdownOutcome.ACKNOWLEDGED, reason=None):
        if self._shutdown_reporter is None:
            return
        self._shutdown_reporter.emit(
            phase,
            action,
            outcome=outcome,
            reason=reason,
            sink_id=self._sink_id,
            output_id=None if self._record is None else self._record.output_id,
            actor=ShutdownActor.SINK,
        )

    def _emit_shutdown_failure(self, action, exc):
        self._emit_shutdown_action(
            ShutdownPhase.PHASE_FAILED,
            action,
            outcome=ShutdownOutcome.FAILED,
            reason=str(exc),
        )

    def _write_buffer(self) -> None:
        from pvfs_tools.Core.pvfs_binding import HighTime

        assert self._pvfs_data is not None and self._record is not None
        if self._start_time is None or not self._buffer or not self._buffer[0]:
            return
        lengths = [len(b) for b in self._buffer]
        if len(set(lengths)) != 1:
            # Mismatched buffers would corrupt block alignment; drop and record.
            dropped = max(lengths)
            self._buffer = [[] for _ in self._channels]
            with transaction():
                self._record.sample_loss = self._record.sample_loss + dropped
            return
        n = lengths[0]
        block_start = HighTime.from_seconds(
            self._start_time.to_seconds() + self._samples_written / self._sample_rate
        )
        for ch_name, buf in zip(self._channels, self._buffer):
            idf = self._pvfs_data._indexed_data_files.get(ch_name)
            if idf is not None:
                idf.append_block(block_start, buf)
        self._samples_written += n
        self._buffer = [[] for _ in self._channels]
        with transaction():
            self._record.row_offset = self._samples_written

    def _frame_from_packet(self, packet: object) -> list[float]:
        if getattr(packet, "is_missing_sample", False):
            return [float("nan")] * len(self._channels)
        frame = []
        for label in self._channels:
            attr = _PACKET_FIELD_FOR_LABEL.get(label, label)
            frame.append(_coerce(getattr(packet, attr, 0.0)))
        return frame

    def _mark_record_failed(self, termination_reason: str) -> None:
        if self._record is None:
            return
        with transaction():
            self._record.status = "closed"
            self._record.termination_reason = termination_reason
            self._record.acquisition_state = "interrupted"

    # -- channel / unit / rate resolution ----------------------------------

    def _resolve_channels_units_rate(self) -> None:
        if self._sample_rate is None:
            self._sample_rate = getattr(self._pod, "sample_rate", None)
        if self._channels is None and self._pod is not None:
            channels, units = _channels_units_for_pod(self._pod)
            self._channels = list(channels)
            if self._units is None:
                self._units = list(units)
        if self._channels is not None and self._units is None:
            self._units = ["uV"] * len(self._channels)
        if not self._channels or self._sample_rate is None:
            self._release_database_context()
            raise ManagedPvfsSinkError(
                "PVFS sink requires explicit channels+sample_rate or a pod to derive them"
            )
        if len(self._units) != len(self._channels):
            self._release_database_context()
            raise ManagedPvfsSinkError(
                f"units length {len(self._units)} != channels length {len(self._channels)}"
            )

    def _release_database_context(self) -> None:
        if self._database_context is not None:
            self._database_context.pop()
            self._database_context = None


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _release_placeholder(managed: ManagedOutputFile) -> None:
    """Drop the exclusive ``"xb"`` placeholder handle without closing the row.

    ``managed_file.create``/``allocate_continuation`` open the path with
    ``open(path, "xb")`` purely to claim it atomically (and prove it is not a
    foreign file). The PVFS container bytes are written by ``pvfs_tools``, which
    creates the container itself, so the raw handle is released here; the
    ``output_files`` row stays ``open`` and is transitioned to ``closed`` only by
    :meth:`ManagedPvfsSink._finalize_segment`.
    """
    handle = getattr(managed, "_handle", None)
    if handle is not None and not handle.closed:
        handle.close()


def _channels_units_for_pod(pod: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Derive PVFS channel labels + units from a POD, mirroring Morelia's PvfsSink.

    Duck-typed on the class name so tests need no real Morelia device; the
    Pod8401HR preamp channel map is consulted through Morelia only when a real
    preamp is present, otherwise the default A-D labels are used.
    """
    name = type(pod).__name__
    if name == "Pod8206HR":
        channels = ("EEG1", "EEG2", "EEG3/EMG")
        return channels, ("uV",) * len(channels)
    if name == "Pod8401HR":
        preamp_names: list[str] | None = None
        preamp = getattr(pod, "preamp", None)
        if preamp is not None:
            try:
                from Morelia.Devices import Pod8401HR

                preamp_names = list(
                    Pod8401HR.get_channel_map_for_preamp_device(preamp).values()
                )
            except Exception:
                preamp_names = None
        if not preamp_names:
            preamp_names = ["A", "B", "C", "D"]
        channels = tuple(preamp_names)
        return channels, ("uV",) * len(channels)
    if name == "Pod8274D":
        return ("length_in_bytes", "data"), ("", "")
    raise ManagedPvfsSinkError(
        f"cannot derive PVFS channels for pod of type {name!r}; pass channels explicitly"
    )


def _coerce(value: object) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in (float("inf"), float("-inf")):  # NaN/inf guard
        return 0.0
    return result


def _ensure_database_context():
    from flask import has_app_context

    if has_app_context():
        return None

    context = create_database_app().app_context()
    context.push()
    return context
