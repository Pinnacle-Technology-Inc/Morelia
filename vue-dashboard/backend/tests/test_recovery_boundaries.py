"""Tests for app.output.boundaries — versioned recovery-boundary recording."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import db
from app.domain.enums import GapConfidence
from app.models.incident import Incident  # noqa: F401 — registers model so FK resolves
from app.models.output_file import OutputFile
from app.models.recovery_gap import RecoveryGap
from app.output.boundaries import (
    record_boundary,
    record_same_file_boundary,
    record_segmented_boundary,
)
from app.output.managed_csv_sink import ManagedCsvSink
from app.repositories.sessions import SessionRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sid(app):
    """A committed session row; returns its integer id."""
    with app.app_context():
        session = SessionRepository().create({"name": "boundary-test"})
        return session.id


# ---------------------------------------------------------------------------
# One boundary → one RecoveryGap row (same-file resume)
# ---------------------------------------------------------------------------


def test_record_boundary_persists_exactly_one_row(app, sid):
    with app.app_context():
        before = db.session.scalars(db.select(RecoveryGap)).all()
        record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="device reconnected",
            output_id="out-a",
            pre_offset={"byte": 200, "row": 10},
            post_offset={"byte": 200, "row": 10},
        )
        after = db.session.scalars(db.select(RecoveryGap)).all()
        assert len(after) == len(before) + 1


def test_record_boundary_returns_gap_row(app, sid):
    with app.app_context():
        gap = record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="reconnect",
            output_id="out-a",
            pre_offset={"byte": 50, "row": 2},
            post_offset={"byte": 50, "row": 2},
        )
        assert gap.id is not None
        assert gap.gap_id is not None
        assert gap.dataflow_id == "df-1"
        assert gap.reason == "reconnect"
        assert gap.boundary_kind == "same_file"
        assert gap.boundary_version == 1


# ---------------------------------------------------------------------------
# Versioned columns replace legacy segment-id overloading
# ---------------------------------------------------------------------------


def test_record_same_file_boundary_stores_structured_offsets(app, sid):
    with app.app_context():
        gap = record_same_file_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="reconnect",
            output_id="out-a",
            pre_offset={"byte": 1024, "row": 8},
            post_offset={"byte": 2048, "row": 12},
            boundary_payload={"note": "same-file resume"},
        )
        assert gap.boundary_kind == "same_file"
        assert gap.output_id == "out-a"
        assert gap.pre_offset == {"byte": 1024, "row": 8}
        assert gap.post_offset == {"byte": 2048, "row": 12}
        assert gap.boundary_payload == {"note": "same-file resume"}


def test_boundary_does_not_overload_legacy_segment_columns(app, sid):
    with app.app_context():
        gap = record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="r",
            output_id="out-a",
            pre_offset={"byte": 300, "row": 15},
            post_offset={"byte": 300, "row": 15},
        )
        # Offsets live in dedicated JSON columns, not the legacy strings.
        assert gap.previous_segment_id is None
        assert gap.next_segment_id is None


def test_segmented_boundary_links_prior_and_next_components(app, sid):
    """Acceptance 2: one boundary links prior/next components with identity."""
    with app.app_context():
        gap = record_segmented_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="edf recovery continuation",
            previous_output_id="out-a",
            next_output_id="out-b",
            device_id="pod-1",
            sink_id="sink-1",
            recovery_id="rec-1",
            gap_start={"ts": "2024-01-01T00:00:00"},
            gap_end={"ts": "2024-01-01T00:00:05"},
            boundary_payload={"samples_lost": 40},
        )
        assert gap.boundary_kind == "segmented"
        assert gap.previous_output_id == "out-a"
        assert gap.next_output_id == "out-b"
        # source / sink / recovery identity
        assert gap.device_id == "pod-1"
        assert gap.sink_id == "sink-1"
        assert gap.recovery_id == "rec-1"
        # timing / count metadata
        assert gap.gap_start == {"ts": "2024-01-01T00:00:00"}
        assert gap.gap_end == {"ts": "2024-01-01T00:00:05"}
        assert gap.boundary_payload == {"samples_lost": 40}
        # legacy offset strings stay untouched
        assert gap.previous_segment_id is None
        assert gap.next_segment_id is None


# ---------------------------------------------------------------------------
# Idempotency per recovery_id
# ---------------------------------------------------------------------------


def test_record_boundary_is_idempotent_by_recovery_id(app, sid):
    with app.app_context():
        first = record_segmented_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="recovery",
            previous_output_id="out-a",
            next_output_id="out-b",
            recovery_id="rec-42",
        )
        second = record_segmented_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="recovery",
            previous_output_id="out-a",
            next_output_id="out-b",
            recovery_id="rec-42",
        )
        assert second.id == first.id
        rows = db.session.scalars(
            db.select(RecoveryGap).where(RecoveryGap.recovery_id == "rec-42")
        ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_default_confidence_is_uncertain(app, sid):
    with app.app_context():
        gap = record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="r",
            output_id="out-a",
            pre_offset={"byte": 0, "row": 0},
            post_offset={"byte": 0, "row": 0},
        )
        assert gap.confidence == GapConfidence.UNCERTAIN


def test_explicit_confidence_is_stored(app, sid):
    with app.app_context():
        gap = record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="r",
            output_id="out-a",
            pre_offset={"byte": 0, "row": 0},
            post_offset={"byte": 0, "row": 0},
            confidence=GapConfidence.CONFIRMED,
        )
        assert gap.confidence == GapConfidence.CONFIRMED


# ---------------------------------------------------------------------------
# Partial-final-row (option a) — carried in the versioned boundary payload
# ---------------------------------------------------------------------------


def test_partial_final_row_sets_payload_flag(app, sid):
    with app.app_context():
        gap = record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="r",
            output_id="out-a",
            pre_offset={"byte": 512, "row": 3},
            post_offset={"byte": 512, "row": 3},
            partial_final_row=True,
        )
        assert gap.boundary_payload is not None
        assert gap.boundary_payload["partial_final_row"] is True


def test_no_partial_flag_leaves_payload_none(app, sid):
    with app.app_context():
        gap = record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="r",
            output_id="out-a",
            pre_offset={"byte": 0, "row": 0},
            post_offset={"byte": 0, "row": 0},
            partial_final_row=False,
        )
        assert gap.boundary_payload is None


def test_partial_final_row_does_not_modify_file_bytes(tmp_path, app, sid):
    """record_boundary is DB-only; existing file bytes must remain untouched."""
    path = tmp_path / "data.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=path, dataflow_id="df-1", fieldnames=["ts", "v"])
        sink.write_row({"ts": "1", "v": "10"})
        sink.close()

        bytes_before = path.read_bytes()
        pre_byte = sink.managed.record.byte_offset
        pre_row = sink.managed.record.row_offset

        record_boundary(
            session_id=sid,
            dataflow_id="df-1",
            reason="crash recovery",
            output_id=sink.managed.record.output_id,
            pre_offset={"byte": pre_byte, "row": pre_row},
            post_offset={"byte": pre_byte, "row": pre_row},
            partial_final_row=True,
        )

        assert path.read_bytes() == bytes_before, "record_boundary must not touch file bytes"


# ---------------------------------------------------------------------------
# Packet 10: output lifecycle identity + component constraints
# ---------------------------------------------------------------------------


def _component(**overrides) -> OutputFile:
    """Build a valid physical-component OutputFile row for a logical output."""
    fields = {
        "output_id": "out-a",
        "logical_sink_id": "logical-a",
        "segment_index": 0,
        "dataflow_id": "df-1",
        "sink_type": "csv",
        "path": "/data/out-a.csv",
    }
    fields.update(overrides)
    return OutputFile(**fields)


def test_output_component_defaults_separate_acquisition_and_artifact(app):
    with app.app_context():
        row = _component()
        db.session.add(row)
        db.session.commit()

        stored = db.session.get(OutputFile, row.id)
        assert stored.logical_sink_id == "logical-a"
        assert stored.segment_index == 0
        # Acquisition and artifact state are distinct axes, not source health.
        assert stored.acquisition_state == "open"
        assert stored.artifact_state == "not_required"
        assert stored.byte_loss == 0
        assert stored.sample_loss == 0
        assert stored.previous_output_id is None
        assert stored.final_output_id is None


def test_monotonic_component_chain_links_by_stable_ids(app):
    with app.app_context():
        first = _component(output_id="out-a", segment_index=0, path="/data/a-0.csv")
        second = _component(
            output_id="out-b",
            segment_index=1,
            path="/data/a-1.csv",
            previous_output_id="out-a",
            termination_reason="recovery",
        )
        db.session.add_all([first, second])
        db.session.commit()

        stored = db.session.get(OutputFile, second.id)
        assert stored.logical_sink_id == "logical-a"
        assert stored.segment_index == 1
        assert stored.previous_output_id == "out-a"
        assert stored.termination_reason == "recovery"


def test_duplicate_component_ordinal_within_logical_output_is_rejected(app):
    with app.app_context():
        db.session.add(_component(output_id="out-a", segment_index=0, path="/data/a.csv"))
        db.session.commit()

        db.session.add(
            _component(output_id="out-b", segment_index=0, path="/data/b.csv")
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_duplicate_component_path_within_logical_output_is_rejected(app):
    with app.app_context():
        db.session.add(_component(output_id="out-a", segment_index=0, path="/data/dup.csv"))
        db.session.commit()

        db.session.add(
            _component(output_id="out-b", segment_index=1, path="/data/dup.csv")
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_component_cannot_be_its_own_predecessor(app):
    with app.app_context():
        db.session.add(_component(output_id="out-a", previous_output_id="out-a"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_finalizer_fencing_and_final_artifact_fields_persist(app):
    with app.app_context():
        row = _component(
            output_id="out-a",
            acquisition_state="complete",
            artifact_state="merged",
            final_output_id="artifact-1",
            finalization_id="final-attempt-1",
            finalizer_fence_token=7,
            delivery_state="delivered",
            byte_loss=128,
            sample_loss=4,
        )
        db.session.add(row)
        db.session.commit()

        stored = db.session.get(OutputFile, row.id)
        assert stored.artifact_state == "merged"
        assert stored.final_output_id == "artifact-1"
        assert stored.finalization_id == "final-attempt-1"
        assert stored.finalizer_fence_token == 7
        assert stored.delivery_state == "delivered"
        assert stored.byte_loss == 128
        assert stored.sample_loss == 4


# ---------------------------------------------------------------------------
# Packet 10: versioned recovery-boundary payload (replaces offset overloading)
# ---------------------------------------------------------------------------


def test_segmented_boundary_links_output_ids_without_offset_overloading(app, sid):
    with app.app_context():
        gap = RecoveryGap(
            gap_id="gap-seg-1",
            session_id=sid,
            dataflow_id="df-1",
            reason="recovery",
            confidence=GapConfidence.UNCERTAIN.value,
            boundary_kind="segmented",
            boundary_version=1,
            output_id="out-a",
            previous_output_id="out-a",
            next_output_id="out-b",
        )
        db.session.add(gap)
        db.session.commit()

        stored = db.session.get(RecoveryGap, gap.id)
        assert stored.boundary_kind == "segmented"
        assert stored.boundary_version == 1
        assert stored.previous_output_id == "out-a"
        assert stored.next_output_id == "out-b"
        # Offsets are not smuggled through the legacy segment-id strings.
        assert stored.previous_segment_id is None
        assert stored.next_segment_id is None


def test_same_file_boundary_stores_structured_offsets(app, sid):
    with app.app_context():
        gap = RecoveryGap(
            gap_id="gap-samefile-1",
            session_id=sid,
            dataflow_id="df-1",
            reason="reconnect",
            confidence=GapConfidence.UNCERTAIN.value,
            boundary_kind="same_file",
            boundary_version=1,
            output_id="out-a",
            pre_offset={"byte": 1024, "row": 8},
            post_offset={"byte": 1024, "row": 8},
            boundary_payload={"note": "same-file resume"},
        )
        db.session.add(gap)
        db.session.commit()

        stored = db.session.get(RecoveryGap, gap.id)
        assert stored.boundary_kind == "same_file"
        assert stored.pre_offset == {"byte": 1024, "row": 8}
        assert stored.post_offset == {"byte": 1024, "row": 8}
        assert stored.boundary_payload == {"note": "same-file resume"}
