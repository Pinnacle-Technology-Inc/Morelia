"""EDF continuation-component merger (packet 17; gaps SINK-05 / SINK-26).

Reads one acquisition-complete, ordered EDF component chain and writes ONE
verified merged EDF artifact WITHOUT mutating or deleting any source component.
It is the format-aware ``Merger`` the finalization coordinator (packet 16)
injects for ``sink_type == "edf"``.

Contract (see :mod:`app.services.output_finalization`)
------------------------------------------------------
Given a :class:`~app.services.output_finalization.MergeRequest` it:

1. orders the components by ``segment_index`` and verifies the
   ``previous_output_id`` back-chain (missing / duplicate / gapped / reordered
   chains fail the attempt — never a silent partial merge);
2. reads every segment with ``pyedflib`` and validates the EDF headers are
   uniform (channel count, labels, dimension, ``sample_frequency``, physical /
   digital bounds); an incompatible schema fails the attempt rather than
   concealing it;
3. concatenates the samples in chronological order (nothing is interpolated);
4. writes a temporary merged artifact on the SAME filesystem as the components,
   re-reads it to verify channel count / labels / sample count, then atomically
   publishes it to a FRESH path (``<stem>.merged<suffix>``) distinct from every
   component — so both components remain for packet-29 retention cleanup;
5. returns :class:`~app.services.output_finalization.MergeResult` with
   ``ok=True``, the ``published_path``, a fresh ``final_output_id`` and the
   ``sample_count`` — or ``ok=False`` with a classified ``reason`` and the
   retained ``temp_path`` for diagnosis.

Digital round-trip: segments are read and written in DIGITAL units
(``digital=True``) so the merged artifact preserves each source sample's exact
digital code — the merge introduces NO extra quantization on top of the
original acquisition write.

Metadata limitation (recorded for the support matrix / release gate): EDF stores
whole data records only, so a segment interrupted mid-record is padded with
trailing zeros to a record boundary on close; that padding is indistinguishable
from real samples on read and therefore appears in the merged stream between
segments. Clean, record-aligned segments merge sample-exact.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import numpy as np
from pyedflib import highlevel

from app.services.output_finalization import MergeRequest, MergeResult


class EdfMergeError(Exception):
    """A classified reason an EDF merge could not be produced (retryable)."""


def edf_merger(request: MergeRequest) -> MergeResult:
    """Merge an ordered EDF component chain into one published artifact.

    Pure function matching the ``Merger`` type. Never mutates or deletes a
    component; on any failure it publishes nothing and retains a diagnostic
    temp artifact when one was written.
    """
    return _edf_merger(request, publish=True)


def edf_staging_merger(request: MergeRequest) -> MergeResult:
    """Produce and verify a temporary artifact for fenced publication."""
    return _edf_merger(request, publish=False)


def _edf_merger(request: MergeRequest, *, publish: bool) -> MergeResult:
    started = time.monotonic()
    temp_path: Path | None = None
    try:
        ordered = _ordered_components(request)
        signal_lists, signal_headers, header, per_segment_counts = _read_and_validate(
            ordered
        )
        merged_signals = _concatenate(signal_lists, len(signal_headers))

        published_path = _published_path(request.base_path)
        temp_path = _temp_path(published_path, request.finalization_id)
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        # digital=True: write the exact digital codes we read, no re-quantization.
        highlevel.write_edf(
            str(temp_path), merged_signals, signal_headers, header, digital=True
        )

        sample_count = _verify(temp_path, signal_headers, merged_signals)

        # Atomic publish: temp and target share the component filesystem, so
        # os.replace is atomic and overwrites any prior merged artifact
        # (idempotent re-run produces byte-equivalent output, never a duplicate).
        if publish:
            os.replace(temp_path, published_path)

        return MergeResult(
            ok=True,
            temp_path=str(temp_path),
            published_path=str(published_path),
            final_output_id=uuid.uuid4().hex,
            sample_count=sample_count,
            details={
                "sink_type": "edf",
                "component_count": len(ordered),
                "channels": [_label(sh) for sh in signal_headers],
                "per_segment_sample_counts": per_segment_counts,
                "merged_sample_count": sample_count,
                "elapsed_seconds": round(time.monotonic() - started, 6),
            },
        )
    except EdfMergeError as exc:
        return _failure(temp_path, str(exc))
    except Exception as exc:  # noqa: BLE001 - any read/write fault is a failed, retryable merge
        return _failure(temp_path, f"edf merge error: {exc!r}")


# ---------------------------------------------------------------------------
# Ordering / chain validation
# ---------------------------------------------------------------------------


def _ordered_components(request: MergeRequest) -> list:
    components = list(request.components)
    if not components:
        raise EdfMergeError("no components to merge")

    for component in components:
        if component.sink_type != "edf":
            raise EdfMergeError(
                f"component {component.output_id!r} is not an EDF component "
                f"(sink_type={component.sink_type!r})"
            )

    ordered = sorted(components, key=lambda c: c.segment_index)
    indices = [c.segment_index for c in ordered]
    if indices != list(range(len(ordered))):
        raise EdfMergeError(
            f"component segment indices {indices} are not a contiguous 0..N "
            f"chain (missing, duplicate, or gapped segments)"
        )

    if ordered[0].previous_output_id is not None:
        raise EdfMergeError(
            "head component (segment_index 0) must have no previous_output_id"
        )
    for previous, current in zip(ordered, ordered[1:]):
        if current.previous_output_id != previous.output_id:
            raise EdfMergeError(
                f"broken component chain at segment_index {current.segment_index}: "
                f"previous_output_id {current.previous_output_id!r} does not link "
                f"to predecessor {previous.output_id!r} (reordered/mismatched chain)"
            )
    return ordered


# ---------------------------------------------------------------------------
# Read + header-compatibility validation
# ---------------------------------------------------------------------------


def _read_and_validate(ordered: list):
    signal_lists: list = []
    per_segment_counts: list[int] = []
    reference_signature = None
    reference_signal_headers = None
    reference_header = None

    for component in ordered:
        path = Path(component.path)
        if not path.exists():
            raise EdfMergeError(f"component file missing: {path}")
        try:
            signals, signal_headers, header = highlevel.read_edf(
                str(path), digital=True
            )
        except Exception as exc:  # noqa: BLE001 - unreadable/corrupt segment fails the merge
            raise EdfMergeError(
                f"component {path} is unreadable or corrupt: {exc!r}"
            ) from exc

        signature = _header_signature(signal_headers)
        if reference_signature is None:
            reference_signature = signature
            reference_signal_headers = signal_headers
            reference_header = header
        elif signature != reference_signature:
            raise EdfMergeError(
                f"component {path} has an incompatible EDF schema: "
                f"{signature} != {reference_signature}"
            )

        signal_lists.append(signals)
        per_segment_counts.append(int(len(signals[0])) if len(signals) else 0)

    return signal_lists, reference_signal_headers, reference_header, per_segment_counts


def _concatenate(signal_lists: list, n_channels: int) -> list:
    merged: list = []
    for channel in range(n_channels):
        merged.append(
            np.concatenate([np.asarray(signals[channel]) for signals in signal_lists])
        )
    return merged


def _header_signature(signal_headers: list) -> tuple:
    signature = []
    for sh in signal_headers:
        frequency = sh.get("sample_frequency", sh.get("sample_rate"))
        signature.append(
            (
                _label(sh),
                (sh.get("dimension") or "").strip(),
                float(frequency) if frequency is not None else None,
                float(sh.get("physical_min")),
                float(sh.get("physical_max")),
                int(sh.get("digital_min")),
                int(sh.get("digital_max")),
            )
        )
    return tuple(signature)


def _label(signal_header: dict) -> str:
    return signal_header.get("label")


# ---------------------------------------------------------------------------
# Verification + publish helpers
# ---------------------------------------------------------------------------


def _verify(temp_path: Path, signal_headers: list, merged_signals: list) -> int:
    try:
        signals, headers, _header = highlevel.read_edf(str(temp_path), digital=True)
    except Exception as exc:  # noqa: BLE001
        raise EdfMergeError(
            f"merged artifact at {temp_path} failed verification read: {exc!r}"
        ) from exc

    if len(signals) != len(signal_headers):
        raise EdfMergeError(
            f"merged artifact channel count {len(signals)} != expected "
            f"{len(signal_headers)}"
        )

    expected_labels = [_label(sh) for sh in signal_headers]
    actual_labels = [_label(h) for h in headers]
    if actual_labels != expected_labels:
        raise EdfMergeError(
            f"merged artifact labels {actual_labels} != expected {expected_labels}"
        )

    expected_count = int(len(merged_signals[0])) if len(merged_signals) else 0
    actual_count = int(len(signals[0])) if len(signals) else 0
    if actual_count != expected_count:
        raise EdfMergeError(
            f"merged artifact sample count {actual_count} != expected "
            f"{expected_count}"
        )
    return actual_count


def _published_path(base_path: str) -> Path:
    base = Path(base_path)
    return base.with_name(f"{base.stem}.merged{base.suffix}")


def _temp_path(published_path: Path, finalization_id: str) -> Path:
    # Keep the ``.edf`` suffix so pyedflib accepts the temp path; the merge is
    # written here first, verified, then atomically renamed onto published_path.
    return published_path.with_name(
        f"{published_path.stem}.{finalization_id}.partial{published_path.suffix}"
    )


def _failure(temp_path: Path | None, reason: str) -> MergeResult:
    return MergeResult(
        ok=False,
        temp_path=str(temp_path) if temp_path is not None else None,
        reason=reason,
        details={"sink_type": "edf"},
    )
