"""PVFS continuation-component merger (packet 18; gaps SINK-06 / SINK-26).

Reads one acquisition-complete, ordered PVFS component chain and writes ONE
verified merged PVFS container WITHOUT mutating or deleting any source
component. It is the format-aware ``Merger`` the finalization coordinator
(packet 16) injects for ``sink_type == "pvfs"`` — the sibling of packet 17's
:mod:`app.output.edf_merger`.

Contract (see :mod:`app.services.output_finalization`)
------------------------------------------------------
Given a :class:`~app.services.output_finalization.MergeRequest` it:

1. orders the components by ``segment_index`` and verifies the
   ``previous_output_id`` back-chain (missing / duplicate / gapped / reordered
   chains fail the attempt — never a silent partial merge);
2. opens every component with ``pvfs_tools`` and validates the PVFS metadata is
   uniform across segments — channel identity AND order, per-channel unit,
   per-channel data rate, and the pinned ``device_preferences`` rows in the
   container's ``experiment.db3``; an incompatible schema/preference set fails
   the attempt rather than concealing it;
3. reads each channel's samples per segment and concatenates them in ordinal
   (chronological) order (nothing is interpolated, nothing is overwritten — the
   destructive same-container reopen that SINK-06 documents is never used);
4. writes a temporary merged container on the SAME filesystem as the components,
   re-opens it to verify channel identity / order / unit / rate and the exact
   merged sample count per channel, then atomically publishes it to a FRESH path
   (``<stem>.merged<suffix>``) distinct from every component — so every component
   remains for packet-29 retention cleanup;
5. returns :class:`~app.services.output_finalization.MergeResult` with
   ``ok=True``, the ``published_path``, a fresh ``final_output_id`` and the merged
   ``sample_count`` — or ``ok=False`` with a classified ``reason`` and the
   retained ``temp_path`` for diagnosis.

Why the merge runs in a child process
--------------------------------------
The native ``pvfs_tools`` library keeps a container's OS file handle open for the
lifetime of the process that opened it — even after ``PvfsDataFile.close()``, and
even for a read-only open (verified on this platform). While such a handle is
held, Windows refuses the atomic ``os.replace`` that publishes the merged
artifact. So ALL native PVFS I/O (read components, write temp, verify readback)
is confined to a dedicated child process, mirroring the managed sink's
writer-process ownership model: the child opens/writes/verifies and then EXITS,
releasing every handle, and only then does the parent — which never opens a PVFS
file — atomically rename the temp container onto the published path. The parent
therefore holds no native handle, satisfying both the atomic-publish contract and
the finalizer's "release all native handles" requirement.

PVFS is a single container file on this platform (design doc section 6 "PVFS"),
so the temp/publish rename is a single atomic ``os.replace``. Values round-trip
through the native ``float32`` sample encoding exactly as the original
acquisition wrote them; the merge adds no re-quantization.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import time
import uuid
from pathlib import Path

from app.services.output_finalization import MergeRequest, MergeResult

# The merge child is CPU/IO bound by the total component size; this ceiling only
# guards against a wedged native call, not normal runtime.
_WORKER_JOIN_TIMEOUT = 300.0
_WORKER_TERMINATE_TIMEOUT = 5.0


class PvfsMergeError(Exception):
    """A classified reason a PVFS merge could not be produced (retryable)."""


def pvfs_merger(request: MergeRequest) -> MergeResult:
    """Merge an ordered PVFS component chain into one published container.

    Pure function matching the ``Merger`` type. Never mutates or deletes a
    component; on any failure it publishes nothing and retains a diagnostic
    temp container when one was written.
    """
    return _pvfs_merger(request, publish=True)


def pvfs_staging_merger(request: MergeRequest) -> MergeResult:
    """Produce and verify a temporary container for fenced publication."""
    return _pvfs_merger(request, publish=False)


def _pvfs_merger(request: MergeRequest, *, publish: bool) -> MergeResult:
    started = time.monotonic()
    temp_path: Path | None = None
    try:
        ordered = _ordered_components(request)  # chain validation (pure, no I/O)
        paths = [component.path for component in ordered]

        published_path = _published_path(request.base_path)
        temp_path = _temp_path(published_path, request.finalization_id)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        # A retried attempt may find a stale partial from a crashed predecessor;
        # remove it so the child's create() starts from a clean, provably-ours path.
        if temp_path.exists():
            temp_path.unlink()

        # All native PVFS I/O happens here and is released when the child exits.
        outcome = _run_merge_worker(paths, temp_path)
        if not outcome.get("ok"):
            return _failure(temp_path, outcome.get("reason", "pvfs merge worker failed"))

        if not temp_path.exists():
            return _failure(None, "merged artifact vanished before publish")

        # Parent holds no PVFS handle (the child released them on exit), so this
        # atomic rename succeeds and overwrites any prior merged artifact (an
        # idempotent re-run yields an equivalent container, never a duplicate).
        if publish:
            os.replace(temp_path, published_path)
        if publish and not published_path.exists():
            return _failure(str(temp_path), "published artifact missing after replace")

        return MergeResult(
            ok=True,
            temp_path=str(temp_path),
            published_path=str(published_path),
            final_output_id=uuid.uuid4().hex,
            sample_count=outcome["sample_count"],
            details={
                "sink_type": "pvfs",
                "component_count": len(ordered),
                "channels": outcome["channels"],
                "units": outcome["units"],
                "sample_rate": outcome["sample_rate"],
                "per_segment_sample_counts": outcome["per_segment_counts"],
                "merged_sample_count": outcome["sample_count"],
                "device_preference_count": outcome["device_preference_count"],
                "elapsed_seconds": round(time.monotonic() - started, 6),
            },
        )
    except PvfsMergeError as exc:
        return _failure(temp_path, str(exc))
    except Exception as exc:  # noqa: BLE001 - any read/write fault is a failed, retryable merge
        return _failure(temp_path, f"pvfs merge error: {exc!r}")


# ---------------------------------------------------------------------------
# Ordering / chain validation (mirrors app.output.edf_merger)
# ---------------------------------------------------------------------------


def _ordered_components(request: MergeRequest) -> list:
    components = list(request.components)
    if not components:
        raise PvfsMergeError("no components to merge")

    for component in components:
        if component.sink_type != "pvfs":
            raise PvfsMergeError(
                f"component {component.output_id!r} is not a PVFS component "
                f"(sink_type={component.sink_type!r})"
            )

    ordered = sorted(components, key=lambda c: c.segment_index)
    indices = [c.segment_index for c in ordered]
    if indices != list(range(len(ordered))):
        raise PvfsMergeError(
            f"component segment indices {indices} are not a contiguous 0..N "
            f"chain (missing, duplicate, or gapped segments)"
        )

    if ordered[0].previous_output_id is not None:
        raise PvfsMergeError(
            "head component (segment_index 0) must have no previous_output_id"
        )
    for previous, current in zip(ordered, ordered[1:]):
        if current.previous_output_id != previous.output_id:
            raise PvfsMergeError(
                f"broken component chain at segment_index {current.segment_index}: "
                f"previous_output_id {current.previous_output_id!r} does not link "
                f"to predecessor {previous.output_id!r} (reordered/mismatched chain)"
            )
    return ordered


# ---------------------------------------------------------------------------
# Child-process merge worker (owns every native PVFS handle)
# ---------------------------------------------------------------------------


def _run_merge_worker(paths: list[str], temp_path: Path) -> dict:
    """Run read+write+verify in a child process; return its result dict.

    The child is the sole owner of every native PVFS handle. When it exits the
    handles are released, so the parent can atomically publish the temp file.
    """
    queue: mp.Queue = mp.Queue()
    proc = mp.Process(target=_merge_worker, args=(queue, paths, str(temp_path)))
    proc.start()

    result: dict | None = None
    deadline = time.monotonic() + _WORKER_JOIN_TIMEOUT
    while time.monotonic() < deadline:
        try:
            result = queue.get(timeout=0.5)
            break
        except Exception:  # noqa: BLE001 - Empty; keep polling while the child lives
            if not proc.is_alive():
                # Child gone: give the queue one final flush window, then stop.
                try:
                    result = queue.get(timeout=0.5)
                except Exception:  # noqa: BLE001
                    result = None
                break

    proc.join(_WORKER_TERMINATE_TIMEOUT)
    if proc.is_alive():
        proc.terminate()
        proc.join(_WORKER_TERMINATE_TIMEOUT)
        result = {"ok": False, "reason": "pvfs merge worker timed out"}

    try:
        queue.close()
        queue.join_thread()
    except Exception:  # noqa: BLE001
        pass

    if result is None:
        return {
            "ok": False,
            "reason": f"pvfs merge worker exited without a result "
            f"(exitcode={proc.exitcode})",
        }
    return result


def _merge_worker(queue: "mp.Queue", paths: list[str], temp_path: str) -> None:
    """Child entrypoint: read+validate components, write temp, verify readback.

    Puts exactly one result dict on *queue*. All native handles opened here are
    released when this process exits, which is what lets the parent publish.
    """
    try:
        schema, segments, per_segment_counts, device_preferences = _read_and_validate(
            paths
        )
        _write_merged(Path(temp_path), schema, segments, device_preferences)
        sample_count = _verify(Path(temp_path), schema, per_segment_counts)
        queue.put(
            {
                "ok": True,
                "sample_count": sample_count,
                "channels": list(schema.channels),
                "units": list(schema.units),
                "sample_rate": schema.sample_rate,
                "per_segment_counts": list(per_segment_counts),
                "device_preference_count": len(device_preferences),
            }
        )
    except PvfsMergeError as exc:
        queue.put({"ok": False, "reason": str(exc)})
    except Exception as exc:  # noqa: BLE001 - any fault is a failed, retryable merge
        queue.put({"ok": False, "reason": f"pvfs merge error: {exc!r}"})


# ---------------------------------------------------------------------------
# Read + metadata-compatibility validation (child-process only)
# ---------------------------------------------------------------------------


class _Schema:
    """The uniform PVFS metadata a compatible chain must share."""

    __slots__ = ("channels", "units", "sample_rate")

    def __init__(
        self, channels: tuple[str, ...], units: tuple[str, ...], sample_rate: float
    ):
        self.channels = channels
        self.units = units
        self.sample_rate = sample_rate

    def signature(self) -> tuple:
        return (self.channels, self.units, self.sample_rate)


def _read_and_validate(paths: list[str]):
    """Open every component, validate metadata uniformity, and read its samples.

    Returns ``(schema, segments, per_segment_counts, device_preferences)`` where
    ``segments`` is a list (one per component, in ordinal order) of
    ``{channel_name: [float, ...]}`` and ``device_preferences`` is the pinned,
    cross-component-verified preference row set to re-apply to the merged file.
    """
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    reference: _Schema | None = None
    reference_prefs: list[dict] | None = None
    segments: list[dict[str, list[float]]] = []
    per_segment_counts: list[int] = []

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            raise PvfsMergeError(f"component file missing: {path}")

        reader = PvfsDataFile()
        try:
            if not reader.open(str(path)):
                raise PvfsMergeError(
                    f"component {path} is unreadable or corrupt (open failed)"
                )

            channels = tuple(reader.get_channel_names())
            if not channels:
                raise PvfsMergeError(f"component {path} exposes no channels")

            units: list[str] = []
            rates: list[float] = []
            channel_data: dict[str, list[float]] = {}
            for name in channels:
                idf = reader.open_channel(name)
                if idf is None:
                    raise PvfsMergeError(
                        f"component {path} channel {name!r} could not be opened"
                    )
                info = reader.get_channel_info(name)
                units.append((getattr(info, "unit", "") or "").strip())
                rates.append(float(idf.get_data_rate()))
                channel_data[name] = _read_channel(idf, HighTime)

            rate_set = set(rates)
            if len(rate_set) != 1:
                raise PvfsMergeError(
                    f"component {path} mixes channel data rates {sorted(rate_set)}"
                )
            schema = _Schema(channels, tuple(units), rates[0])
            prefs = _read_device_preferences(reader)

            if reference is None:
                reference = schema
                reference_prefs = prefs
            else:
                if schema.signature() != reference.signature():
                    raise PvfsMergeError(
                        f"component {path} has an incompatible PVFS schema: "
                        f"{schema.signature()} != {reference.signature()}"
                    )
                if prefs != reference_prefs:
                    raise PvfsMergeError(
                        f"component {path} has incompatible device preferences: "
                        f"{prefs} != {reference_prefs}"
                    )

            counts = {len(v) for v in channel_data.values()}
            if len(counts) != 1:
                raise PvfsMergeError(
                    f"component {path} has ragged channel sample counts "
                    f"{ {k: len(v) for k, v in channel_data.items()} }"
                )
            segments.append(channel_data)
            per_segment_counts.append(next(iter(counts)))
        finally:
            reader.close()

    assert reference is not None
    return reference, segments, per_segment_counts, (reference_prefs or [])


def _read_channel(idf, HighTime) -> list[float]:
    """Read every sample of one channel from an opened indexed data file."""
    start = idf.get_start_time().to_seconds()
    end = idf.get_end_time().to_seconds()
    _ts, values = idf.get_data(
        HighTime.from_seconds(start - 1.0), HighTime.from_seconds(end + 1.0)
    )
    return list(values)


def _read_device_preferences(reader) -> list[dict]:
    """Read the pinned ``device_preferences_table`` rows from a container.

    ``pvfs_tools`` exposes no reader for this table, so query the extracted
    ``experiment.db3`` through the open handle's database session. A container
    without the table (older layout) is treated as having no preferences.
    """
    database = getattr(reader, "_database", None)
    if database is None:
        return []
    try:
        from sqlalchemy import text

        with database.session() as session:
            rows = session.execute(
                text(
                    "SELECT name, type, value, ProductNumber, SerialNumber "
                    "FROM device_preferences_table ORDER BY rowid"
                )
            ).fetchall()
    except Exception:  # noqa: BLE001 - a missing/legacy table means no pinned prefs
        return []
    return [
        {
            "name": row[0],
            "type": row[1],
            "value": row[2],
            "ProductNumber": row[3],
            "SerialNumber": row[4],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Merged-container write (child-process only)
# ---------------------------------------------------------------------------


def _write_merged(
    temp_path: Path,
    schema: _Schema,
    segments: list[dict[str, list[float]]],
    device_preferences: list[dict],
) -> None:
    """Create the merged container and append every segment's block in order."""
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    rate = schema.sample_rate
    writer = PvfsDataFile()
    try:
        if not writer.create(str(temp_path)):
            raise PvfsMergeError(
                f"could not create merged PVFS container at {temp_path}"
            )

        start_time = HighTime.from_seconds(time.time())
        writer.set_experiment_info(
            name="Morelia PVFS recording (merged)",
            description="Merged continuation components from Morelia data collection",
            start_time=start_time,
        )
        for name, unit in zip(schema.channels, schema.units):
            idf = writer.create_channel(name, data_rate=rate, unit=unit or "uV")
            if idf is None:
                raise PvfsMergeError(f"failed to create merged PVFS channel {name}")
            idf._delta_time = HighTime(0, 1.0 / rate)

        # Append blocks in ordinal (chronological) order, timing each block off the
        # running sample count exactly as the acquisition sink did.
        samples_written = 0
        for segment in segments:
            n = len(next(iter(segment.values()))) if segment else 0
            if n == 0:
                continue
            block_start = HighTime.from_seconds(
                start_time.to_seconds() + samples_written / rate
            )
            for name in schema.channels:
                idf = writer._indexed_data_files.get(name)
                if idf is not None:
                    idf.append_block(block_start, segment[name])
            samples_written += n

        if device_preferences:
            writer.set_device_preferences(device_preferences)

        for idf in writer._indexed_data_files.values():
            if idf is not None:
                idf.flush(synchronous=True)
        writer.flush(synchronous=True)
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Verification (child-process only)
# ---------------------------------------------------------------------------


def _verify(temp_path: Path, schema: _Schema, per_segment_counts: list[int]) -> int:
    """Re-open the merged container and confirm it backs a publish.

    Checks channel identity + order, per-channel unit and rate, and that every
    channel holds exactly the total merged sample count. Returns that count.
    """
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    expected_total = sum(per_segment_counts)
    reader = PvfsDataFile()
    try:
        if not reader.open(str(temp_path)):
            raise PvfsMergeError(
                f"merged artifact at {temp_path} failed verification open"
            )
        channels = tuple(reader.get_channel_names())
        if channels != schema.channels:
            raise PvfsMergeError(
                f"merged artifact channels {channels} != expected {schema.channels}"
            )
        for name, unit in zip(schema.channels, schema.units):
            idf = reader.open_channel(name)
            if idf is None:
                raise PvfsMergeError(
                    f"merged artifact channel {name!r} could not be opened"
                )
            actual_rate = float(idf.get_data_rate())
            if actual_rate != schema.sample_rate:
                raise PvfsMergeError(
                    f"merged artifact channel {name!r} rate {actual_rate} != "
                    f"expected {schema.sample_rate}"
                )
            info = reader.get_channel_info(name)
            actual_unit = (getattr(info, "unit", "") or "").strip()
            if actual_unit != unit:
                raise PvfsMergeError(
                    f"merged artifact channel {name!r} unit {actual_unit!r} != "
                    f"expected {unit!r}"
                )
            actual_count = len(_read_channel(idf, HighTime))
            if actual_count != expected_total:
                raise PvfsMergeError(
                    f"merged artifact channel {name!r} sample count {actual_count} "
                    f"!= expected {expected_total}"
                )
    finally:
        reader.close()
    return expected_total


# ---------------------------------------------------------------------------
# Publish helpers
# ---------------------------------------------------------------------------


def _published_path(base_path: str) -> Path:
    base = Path(base_path)
    return base.with_name(f"{base.stem}.merged{base.suffix}")


def _temp_path(published_path: Path, finalization_id: str) -> Path:
    # Keep the ``.pvfs`` suffix; the merge is written here first, verified, then
    # atomically renamed onto published_path (PVFS is a single container file).
    return published_path.with_name(
        f"{published_path.stem}.{finalization_id}.partial{published_path.suffix}"
    )


def _failure(temp_path: Path | str | None, reason: str) -> MergeResult:
    return MergeResult(
        ok=False,
        temp_path=str(temp_path) if temp_path is not None else None,
        reason=reason,
        details={"sink_type": "pvfs"},
    )
