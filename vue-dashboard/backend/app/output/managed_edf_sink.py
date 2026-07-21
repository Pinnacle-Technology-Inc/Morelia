"""Managed EDF sink: deferred-open, worker-owned EDF writer with linked segments.

Ownership / safety boundary (gaps SINK-05, SINK-21; design doc section 6 "EDF")
------------------------------------------------------------------------------
Morelia's raw ``EDFSink`` is destructive: ``__enter__`` ``os.remove``\\s an
existing destination, and the isolated recovery experiment proved that opening
an *existing* path with ``pyedflib`` 0.1.42's ``EdfWriter`` silently replaces the
prior samples. Reopening an EDF path in place is therefore unsafe and disabled.

This adapter never lets ``EdfWriter`` touch the logical configured path blindly.
It allocates an **exclusive segment BEFORE constructing the writer**:
``app.output.managed_file.create`` claims the path with ``open(path, "xb")`` — a
create-once claim that refuses a foreign file — and commits the ``output_files``
row first. Only then is the (now provably empty, provably ours) path handed to a
fresh ``EdfWriter``.

Recovery model (immutable components + linked continuations)
-----------------------------------------------------------
EDF component files are immutable after close. A runtime-error interruption never
reopens/mutates the prior segment: :meth:`recover` finalizes component ``N``
(retained byte-for-byte, marked ``interrupted``) and allocates a monotonically
indexed linked continuation ``N+1`` via
:func:`app.output.managed_file.allocate_continuation`. Its deterministic name is
``<stem>.recovery-<NNNN><suffix>`` (e.g. ``recording.edf`` ->
``recording.recovery-0001.edf``), and the new row links back through
``previous_output_id``. A clean user stop (:meth:`close`) finalizes the current
component, marks the acquisition ``complete``, and allocates **no** continuation;
merging linked segments into one artifact belongs to packet 17.

Lifecycle protocol (open -> write/flush -> get_dict -> close -> recover)
-----------------------------------------------------------------------
Construction is side-effect free (SINK-21): ``__init__`` opens nothing, imports
no native EDF library, and is safe to build/rebuild in the parent watchdog. The
live ``EdfWriter``, the metadata row, and the headers exist only after
:meth:`open`, which must run in the DataFlow worker. ``get_dict()`` carries the
logical sink id and current segment identity for cross-process reconstruction —
never permission to delete/reuse the old path: a reconstructing worker always
allocates a linked continuation rather than reopening a closed segment.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from app.database import create_database_app, db, transaction
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output import managed_file
from app.output.managed_file import ManagedOutputFile

# EDF header scaling constants (mirror Morelia's EDFSink so merged artifacts and
# single-segment recordings share one digital<->physical mapping).
_EDF_PHYSICAL_MAX = 2046
_EDF_PHYSICAL_MIN = -2046
_EDF_DIGITAL_MAX = 32767
_EDF_DIGITAL_MIN = -32768
_EDF_DIMENSION = "uV"

# label -> packet attribute, covering both Pod8206HR and Pod8401HR channel maps.
_PACKET_FIELD_FOR_LABEL: dict[str, str] = {
    "EEG1": "ch0",
    "EEG2": "ch1",
    "EEG3/EMG": "ch2",
    "A": "ch0",
    "B": "ch1",
    "C": "ch2",
    "D": "ch3",
    "EXT0": "ext0",
    "EXT1": "ext1",
    "TTL1": "ttl1",
    "TTL2": "ttl2",
    "TTL3": "ttl3",
    "TTL4": "ttl4",
}


class ManagedEdfSinkError(Exception):
    """Raised when an EDF segment cannot be allocated, opened, or reconstructed."""


class ManagedEdfSink:
    """EDF sink backed by exclusively-allocated, immutable, linked segments.

    Invariants:
    - Construction opens nothing and imports no native library (SINK-21).
    - The configured path is claimed create-once via ``managed_file.create``
      before any ``EdfWriter`` opens it (SINK-05); a foreign file is refused.
    - Component files are immutable after close; error recovery always allocates
      a linked continuation and never reopens/mutates a prior segment.
    - A clean stop marks the acquisition complete and allocates no continuation.
    - The ``pod`` kwarg injected by Morelia reconstruction is accepted; channels
      and the sample rate are derived from it when not given explicitly.
    """

    def __init__(
        self,
        *,
        path: str | Path,
        dataflow_id: str,
        channels: list[str] | None = None,
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
    ) -> None:
        # Descriptor only — no filesystem, database, EDF-writer, or native-import
        # work happens here so the parent watchdog can build/rebuild it safely.
        self._base_path = Path(path)
        self._dataflow_id = dataflow_id
        self._channels = list(channels) if channels is not None else None
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
        self.observe_on_scheduler = observe_on_scheduler

        self._record: OutputFile | None = None
        self._writer = None  # pyedflib.EdfWriter, created worker-side in open()
        self._buffer: list[list[float]] = []
        self._total_frames = 0
        self._database_context = None
        self._opened = False
        self._closed = False

    # -- lifecycle ----------------------------------------------------------

    @property
    def opened(self) -> bool:
        return self._opened

    @property
    def record(self) -> OutputFile | None:
        return self._record

    def open(self) -> ManagedEdfSink:
        """Open the live EDF writer. Worker-side, idempotent.

        First construction (no ``output_id``) mints component 0 at the configured
        path. Reconstruction (``output_id`` present) never reopens the closed
        segment — it allocates a linked continuation from it, honoring SINK-05.
        """
        if self._opened:
            return self
        if self._closed:
            raise ManagedEdfSinkError("cannot reopen a closed ManagedEdfSink")

        self._database_context = _ensure_database_context()
        self._resolve_channels_and_rate()

        if self._output_id is None:
            managed = managed_file.create(
                self._base_path,
                dataflow_id=self._dataflow_id,
                sink_type=SinkType.EDF,
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
                raise ManagedEdfSinkError(
                    f"no output_files row for output_id={self._output_id!r}"
                )
            # Never reopen a closed EDF segment (SINK-05) — continue it.
            managed = managed_file.allocate_continuation(
                previous, termination_reason="recovery", schema_hash=self._schema_hash
            )
            self._start_segment(managed)

        self._opened = True
        return self

    def recover(self, *, termination_reason: str = "recovery") -> ManagedEdfSink:
        """Interruption handler: close component N, continue in linked component N+1.

        Component N is retained byte-for-byte and marked ``interrupted``; the
        successor is a fresh, exclusively-allocated file that links back through
        ``previous_output_id``. Subsequent writes land only in N+1; N is never
        reopened or mutated.
        """
        if not self._opened:
            raise ManagedEdfSinkError("cannot recover a sink that was never opened")
        if self._closed:
            raise ManagedEdfSinkError("cannot recover a closed sink")

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
        hardware becomes a separate logical output (design doc section 6 "EDF").
        Idempotent; a never-opened descriptor closes as a no-op.
        """
        if self._closed:
            return
        try:
            if self._opened and self._writer is not None:
                self._finalize_segment(
                    termination_reason=termination_reason, acquisition_state="complete"
                )
        finally:
            self._closed = True
            self._release_database_context()

    def __enter__(self) -> ManagedEdfSink:
        return self.open()

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- writes -------------------------------------------------------------

    def write_frame(self, samples) -> None:
        """Append one sample per channel (ordered to match ``channels``)."""
        if not self._opened:
            self.open()
        if len(samples) != len(self._channels):
            raise ValueError(
                f"expected {len(self._channels)} channel samples, got {len(samples)}"
            )
        for index, value in enumerate(samples):
            self._buffer[index].append(float(value))
        # One data record == sample_rate frames; flush a whole record at a time so
        # each incremental writeSamples() aligns to a record boundary.
        if len(self._buffer[0]) >= self._record_frames:
            self._write_buffer()

    def write_row(self, row: dict) -> None:
        """Append one frame from a ``{channel_label: value}`` mapping."""
        self.write_frame([_coerce(row.get(channel, 0.0)) for channel in self._channels])

    def flush(self, *args: object) -> None:
        """No-arg: flush buffered records. ``(timestamp, packet)``: Morelia stream.

        The Morelia worker calls ``flush(timestamp, packet)`` once per packet; the
        timestamp is unused (EDF ordering is implicit in write order).
        """
        if not args:
            if self._opened and self._buffer and len(self._buffer[0]) > 0:
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
            "sample_rate": self._sample_rate,
            "output_id": output_id,
            "logical_sink_id": logical_sink_id,
            "segment_index": segment_index,
            "session_id": self._session_id,
            "device_id": self._device_id,
            "sink_id": self._sink_id,
            "schema_hash": self._schema_hash,
            "observe_on_scheduler": self.observe_on_scheduler,
        }

    # -- segment machinery --------------------------------------------------

    @property
    def _record_frames(self) -> int:
        return max(1, int(self._sample_rate))

    def _start_segment(self, managed: ManagedOutputFile) -> None:
        """Adopt an allocated component: own its path with a fresh ``EdfWriter``.

        ``managed`` arrives holding the exclusive ``open(path, "xb")`` claim that
        reserved the path (and refused a foreign file). EDF writing is owned by
        ``EdfWriter``, which must open the path itself, so the raw placeholder
        handle is dropped WITHOUT marking the row closed, then the writer opens
        the now-ours, empty file.
        """
        self._record = managed.record
        _release_placeholder(managed)
        self._writer = self._make_writer(self._record.path)
        self._write_headers()
        self._buffer = [[] for _ in self._channels]

    def _finalize_segment(self, *, termination_reason: str, acquisition_state: str) -> None:
        """Flush remaining frames, close the writer, mark the component closed.

        Best-effort per the packet's failure handling: if the buffer cannot be
        written or the writer cannot close cleanly, the component is retained as a
        failed/interrupted component with the lost frame count recorded — it is
        never reopened destructively.
        """
        assert self._record is not None
        lost = 0
        if self._buffer and len(self._buffer[0]) > 0:
            try:
                self._write_buffer()
            except Exception:
                lost = len(self._buffer[0])
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                if termination_reason == "clean":
                    termination_reason = "writer_failure"
        self._writer = None

        path = self._record.path
        byte_size = os.path.getsize(path) if os.path.exists(path) else 0
        with transaction():
            self._record.status = "closed"
            self._record.termination_reason = termination_reason
            self._record.acquisition_state = acquisition_state
            self._record.byte_offset = byte_size
            if lost:
                self._record.sample_loss = self._record.sample_loss + lost

    def _write_buffer(self) -> None:
        import numpy as np

        assert self._writer is not None and self._record is not None
        arrays = [np.array(channel, dtype=np.float64) for channel in self._buffer]
        self._writer.writeSamples(arrays)
        self._total_frames += len(self._buffer[0])
        self._buffer = [[] for _ in self._channels]
        with transaction():
            self._record.row_offset = self._total_frames

    def _make_writer(self, path: str):
        from pyedflib import EdfWriter

        return EdfWriter(str(path), len(self._channels))

    def _write_headers(self) -> None:
        assert self._writer is not None
        for index, label in enumerate(self._channels):
            self._writer.setSignalHeader(
                index,
                {
                    "label": label,
                    "dimension": _EDF_DIMENSION,
                    "sample_frequency": self._sample_rate,
                    "physical_max": _EDF_PHYSICAL_MAX,
                    "physical_min": _EDF_PHYSICAL_MIN,
                    "digital_max": _EDF_DIGITAL_MAX,
                    "digital_min": _EDF_DIGITAL_MIN,
                    "transducer": "",
                    "prefilter": "",
                },
            )

    def _frame_from_packet(self, packet: object) -> list[float]:
        frame = []
        for label in self._channels:
            attr = _PACKET_FIELD_FOR_LABEL.get(label, label)
            frame.append(_coerce(getattr(packet, attr, 0.0)))
        return frame

    # -- channel / rate resolution -----------------------------------------

    def _resolve_channels_and_rate(self) -> None:
        if self._sample_rate is None:
            self._sample_rate = getattr(self._pod, "sample_rate", None)
        if self._channels is None and self._pod is not None:
            self._channels = list(_channels_for_pod(self._pod))
        if not self._channels or self._sample_rate is None:
            self._release_database_context()
            raise ManagedEdfSinkError(
                "EDF sink requires explicit channels+sample_rate or a pod to derive them"
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
    foreign file). EDF bytes are written by ``EdfWriter``, which opens the path
    itself, so the raw handle is released here; the ``output_files`` row stays
    ``open`` and is transitioned to ``closed`` only by :meth:`_finalize_segment`.
    """
    handle = getattr(managed, "_handle", None)
    if handle is not None and not handle.closed:
        handle.close()


def _channels_for_pod(pod: object) -> tuple[str, ...]:
    """Derive EDF channel labels from a POD, mirroring Morelia's EDFSink.

    Duck-typed on the class name so tests need no real Morelia device; the
    Pod8401HR preamp channel map is consulted through Morelia only when a real
    preamp is present, otherwise the default A-D labels are used.
    """
    name = type(pod).__name__
    if name == "Pod8206HR":
        return ("EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4")
    if name == "Pod8401HR":
        preamp_names: list[str] | None = None
        preamp = getattr(pod, "preamp", None)
        if preamp is not None:
            with suppress(Exception):
                from Morelia.Devices import Pod8401HR

                preamp_names = list(
                    Pod8401HR.get_channel_map_for_preamp_device(preamp).values()
                )
        if not preamp_names:
            preamp_names = ["A", "B", "C", "D"]
        return tuple(preamp_names) + ("EXT0", "EXT1", "TTL1", "TTL2", "TTL3", "TTL4")
    raise ManagedEdfSinkError(
        f"cannot derive EDF channels for pod of type {name!r}; pass channels explicitly"
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
