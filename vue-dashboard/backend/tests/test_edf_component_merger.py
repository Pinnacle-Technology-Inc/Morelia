"""Tests for app.output.edf_merger — packet 17 acceptance criteria.

Covers:
1. Two or more compatible EDF components merge to ONE readable file with exact
   ordered samples and preserved metadata (labels, sample rate, dimension).
2. Missing, duplicate, reordered, corrupt, or schema-incompatible components
   fail the attempt WITHOUT mutating any component or publishing a target.
3. Repeating the merge after success is idempotent — same sample count, no
   duplicated samples.

Plus: the merger is registered so ``resolve_merger(registry, "edf")`` finds it,
and it drives a real end-to-end publish through the packet-16 coordinator.

Real multi-segment EDF inputs are built through the packet-14 ``ManagedEdfSink``
(open -> write -> recover -> write -> close) so the merger is exercised against
genuine linked component files, never hand-forged bytes. All files live under
``tmp_path``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
from pyedflib import EdfReader

from app.models.output_file import OutputFile
from app.output.edf_merger import edf_merger, edf_staging_merger
from app.output.managed_edf_sink import ManagedEdfSink
from app.repositories.output_files import ComponentRef
from app.services.output_finalization import (
    MergeRequest,
    build_default_merger_registry,
    resolve_merger,
)

_DF = "dataflow-edf-merge-001"
_CH = ["EEG1", "EEG2"]
_RATE = 10


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _build_segments(tmp_path, *, n: int, channels=None, rate: int = _RATE) -> str:
    """Build an ``n``-segment EDF logical output on disk; return logical_sink_id.

    Segment ``k`` writes ``rate`` record-aligned frames valued ``k*100 + i`` on
    every channel, so the expected merged channel-0 stream is
    ``[0..rate-1, 100..100+rate-1, 200..]`` — ordering is verifiable by value.
    Earlier segments are ``interrupted`` (recovery), the last ``complete``.
    """
    channels = channels or _CH
    base = tmp_path / "rec.edf"
    sink = ManagedEdfSink(
        path=base, dataflow_id=_DF, channels=channels, sample_rate=rate
    )
    sink.open()
    logical = sink.record.logical_sink_id
    for seg in range(n):
        for i in range(rate):
            value = float(seg * 100 + i)
            sink.write_frame([value] * len(channels))
        if seg < n - 1:
            sink.recover()
        else:
            sink.close()
    return logical


def _refs(logical: str) -> tuple[ComponentRef, ...]:
    rows = (
        OutputFile.query.filter_by(logical_sink_id=logical)
        .order_by(OutputFile.segment_index)
        .all()
    )
    return tuple(
        ComponentRef(
            output_id=r.output_id,
            segment_index=r.segment_index,
            path=r.path,
            previous_output_id=r.previous_output_id,
            sink_type=r.sink_type,
            schema_hash=r.schema_hash,
            byte_offset=r.byte_offset,
            row_offset=r.row_offset,
            acquisition_state=r.acquisition_state,
            termination_reason=r.termination_reason,
        )
        for r in rows
    )


def _request(logical: str, tmp_path, *, refs=None) -> MergeRequest:
    refs = refs if refs is not None else _refs(logical)
    return MergeRequest(
        logical_sink_id=logical,
        finalization_id="fin-1",
        fence_token=1,
        sink_type="edf",
        base_path=refs[0].path,
        temp_dir=str(tmp_path / "finalizer-temp"),
        components=refs,
    )


def _expected_channel(n: int, rate: int = _RATE) -> np.ndarray:
    return np.concatenate([np.arange(seg * 100, seg * 100 + rate) for seg in range(n)])


# ---------------------------------------------------------------------------
# 1. Compatible components merge to one readable, ordered file
# ---------------------------------------------------------------------------


def test_two_components_merge_to_one_ordered_readable_edf(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        request = _request(logical, tmp_path)
        component_paths = [c.path for c in request.components]
        component_bytes = {p: Path(p).read_bytes() for p in component_paths}

        result = edf_merger(request)

    assert result.ok is True
    assert result.reason is None
    assert result.final_output_id
    assert result.sample_count == 2 * _RATE
    published = Path(result.published_path)
    assert published.exists()
    # Published artifact is a fresh path, distinct from every component.
    assert result.published_path not in component_paths
    assert published == tmp_path / "rec.merged.edf"

    reader = EdfReader(str(published))
    try:
        assert reader.getSignalLabels() == _CH
        assert reader.getSampleFrequency(0) == float(_RATE)
        assert reader.getPhysicalDimension(0).strip() == "uV"
        np.testing.assert_allclose(reader.readSignal(0), _expected_channel(2), atol=0.1)
        np.testing.assert_allclose(reader.readSignal(1), _expected_channel(2), atol=0.1)
    finally:
        reader.close()

    # Both components remain byte-for-byte (retention/cleanup is packet 29).
    for path, original in component_bytes.items():
        assert Path(path).read_bytes() == original


def test_three_components_merge_in_chronological_order(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=3)
        result = edf_merger(_request(logical, tmp_path))

    assert result.ok is True
    assert result.sample_count == 3 * _RATE
    reader = EdfReader(str(result.published_path))
    try:
        np.testing.assert_allclose(reader.readSignal(0), _expected_channel(3), atol=0.1)
    finally:
        reader.close()


def test_merge_details_record_metadata(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        result = edf_merger(_request(logical, tmp_path))

    assert result.details["component_count"] == 2
    assert result.details["channels"] == _CH
    assert result.details["per_segment_sample_counts"] == [_RATE, _RATE]
    assert result.details["merged_sample_count"] == 2 * _RATE


# ---------------------------------------------------------------------------
# 2. Bad chains / schemas fail without mutating components or publishing
# ---------------------------------------------------------------------------


def test_missing_component_fails_without_publishing(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        refs = _refs(logical)
        # Remove the continuation file on disk.
        Path(refs[1].path).unlink()
        result = edf_merger(_request(logical, tmp_path, refs=refs))

    assert result.ok is False
    assert "missing" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()
    # The surviving component is untouched.
    assert Path(refs[0].path).exists()


def test_duplicate_segment_index_fails(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        refs = _refs(logical)
        dup_refs = refs + (refs[1],)  # segment_index 1 appears twice
        result = edf_merger(_request(logical, tmp_path, refs=dup_refs))

    assert result.ok is False
    assert "contiguous" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()


def test_gapped_segment_chain_fails(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=3)
        refs = _refs(logical)
        # Drop the middle segment -> indices [0, 2] are non-contiguous.
        gapped = (refs[0], refs[2])
        result = edf_merger(_request(logical, tmp_path, refs=gapped))

    assert result.ok is False
    assert "contiguous" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()


def test_reordered_broken_chain_fails(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=3)
        refs = _refs(logical)
        # Break the back-chain: segment 2 no longer links to segment 1.
        broken = (
            refs[0],
            refs[1],
            dataclasses.replace(refs[2], previous_output_id="not-the-predecessor"),
        )
        result = edf_merger(_request(logical, tmp_path, refs=broken))

    assert result.ok is False
    assert "chain" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()


def test_head_with_predecessor_fails(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        refs = _refs(logical)
        tampered = (
            dataclasses.replace(refs[0], previous_output_id="ghost"),
            refs[1],
        )
        result = edf_merger(_request(logical, tmp_path, refs=tampered))

    assert result.ok is False
    assert "previous_output_id" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()


def test_corrupt_component_fails_without_publishing(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        refs = _refs(logical)
        original_head = Path(refs[0].path).read_bytes()
        # Corrupt the continuation into non-EDF bytes.
        Path(refs[1].path).write_bytes(b"not a valid EDF file at all")
        result = edf_merger(_request(logical, tmp_path, refs=refs))

    assert result.ok is False
    assert "corrupt" in result.reason or "unreadable" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()
    # The uncorrupted component is untouched.
    assert Path(refs[0].path).read_bytes() == original_head


def test_schema_incompatible_components_fail(tmp_path, app):
    with app.app_context():
        # Segment 0 has 2 channels; a mismatched segment has 3 channels.
        logical = _build_segments(tmp_path, n=1)
        head_refs = _refs(logical)

        other = tmp_path / "other.edf"
        other_sink = ManagedEdfSink(
            path=other,
            dataflow_id=_DF,
            channels=["EEG1", "EEG2", "EEG3/EMG"],
            sample_rate=_RATE,
        )
        other_sink.open()
        for i in range(_RATE):
            other_sink.write_frame([float(i)] * 3)
        other_sink.close()

        # Stitch the incompatible file in as a linked "segment 1".
        mismatched = (
            head_refs[0],
            dataclasses.replace(
                head_refs[0],
                output_id="seg-1",
                segment_index=1,
                path=str(other),
                previous_output_id=head_refs[0].output_id,
            ),
        )
        result = edf_merger(_request(logical, tmp_path, refs=mismatched))

    assert result.ok is False
    assert "incompatible" in result.reason
    assert not (tmp_path / "rec.merged.edf").exists()


def test_empty_component_set_fails(tmp_path, app):
    with app.app_context():
        request = MergeRequest(
            logical_sink_id="l",
            finalization_id="f",
            fence_token=1,
            sink_type="edf",
            base_path=str(tmp_path / "rec.edf"),
            temp_dir=str(tmp_path),
            components=(),
        )
        result = edf_merger(request)
    assert result.ok is False
    assert "no components" in result.reason


# ---------------------------------------------------------------------------
# 3. Idempotent repeat: same sample count, no duplication
# ---------------------------------------------------------------------------


def test_repeated_merge_is_idempotent(tmp_path, app):
    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        first = edf_merger(_request(logical, tmp_path))
        second = edf_merger(_request(logical, tmp_path))

    assert first.ok and second.ok
    assert first.sample_count == second.sample_count == 2 * _RATE
    reader = EdfReader(str(second.published_path))
    try:
        assert reader.getNSamples()[0] == 2 * _RATE  # not 4 * _RATE
        np.testing.assert_allclose(reader.readSignal(0), _expected_channel(2), atol=0.1)
    finally:
        reader.close()


# ---------------------------------------------------------------------------
# Registration + end-to-end through the packet-16 coordinator
# ---------------------------------------------------------------------------


def test_edf_merger_is_registered(app):
    with app.app_context():
        registry = build_default_merger_registry()
        assert "edf" in registry
        assert resolve_merger(registry, "edf") is edf_staging_merger


def test_end_to_end_finalization_publishes_merged_edf(tmp_path, app):
    from datetime import UTC, datetime

    from app.repositories.output_files import ARTIFACT_MERGED, OutputFilesRepository
    from app.services.output_finalization import FinalizationCoordinator

    with app.app_context():
        logical = _build_segments(tmp_path, n=2)
        repo = OutputFilesRepository()
        coord = FinalizationCoordinator(
            repository=repo,
            temp_dir=str(tmp_path / "finalizer-temp"),
            lease_ttl_seconds=300.0,
            retention_seconds=3600.0,
            now_fn=lambda: datetime.now(UTC),
        )
        coord.schedule(logical)

        registry = build_default_merger_registry()
        outcome = coord.finalize_once(
            lambda request: resolve_merger(registry, request.sink_type)(request),
            worker_id="w1",
            logical_sink_id=logical,
        )

        assert outcome is not None
        assert outcome.action == "merged"
        assert outcome.final_output_id
        head = repo.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGED
        # Components remain on disk after publish.
        for ref in _refs(logical):
            assert Path(ref.path).exists()

        published = Path(outcome.published_path)

    assert published.exists()
    reader = EdfReader(str(published))
    try:
        np.testing.assert_allclose(reader.readSignal(0), _expected_channel(2), atol=0.1)
    finally:
        reader.close()
