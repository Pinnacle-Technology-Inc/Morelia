"""Tests for output finalization coordination — packet 16 acceptance criteria.

Covers the durable, fenced finalization JOB state machine and the finalizer
process wiring. Deliberately does NOT exercise real EDF/PVFS byte merging
(packets 17/18) — mergers are injected as fakes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import TestingConfig
from app.database import db
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output.managed_file import allocate_continuation, create
from app.repositories.output_files import (
    ARTIFACT_MERGE_FAILED,
    ARTIFACT_MERGE_PENDING,
    ARTIFACT_MERGED,
    ARTIFACT_MERGING,
    ARTIFACT_NOT_REQUIRED,
    NotFinalizable,
    OutputFilesRepository,
    StaleFinalizerClaim,
)
from app.services.output_finalization import (
    FinalizationCoordinator,
    MergeRequest,
    MergeResult,
    coordinator_from_config,
    resolve_merger,
)

_DF = "dataflow-final-001"
_ST = SinkType.CSV
_TTL = 300.0
_RETENTION = 7 * 24 * 3600.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logical_output(
    tmp_path, *, components: int, complete: bool = True, name: str = "rec"
) -> str:
    """Build a logical output with ``components`` linked segments on disk.

    Returns its ``logical_sink_id``. Earlier segments are ``interrupted`` (via
    allocate_continuation); the final segment is closed ``complete`` when
    ``complete`` is set, else left ``open`` acquisition state.
    """
    base = tmp_path / f"{name}.bin"
    head = create(base, dataflow_id=_DF, sink_type=_ST)
    head.write(b"seg0")
    logical = head.record.logical_sink_id

    last = head
    for _ in range(1, components):
        last.close()
        last = allocate_continuation(last.record)
        last.write(b"segN")

    if complete:
        last.close(termination_reason="clean", acquisition_state="complete")
    else:
        last.close()
    return logical


def _component_rows(logical: str) -> list[OutputFile]:
    return list(
        db.session.scalars(
            db.select(OutputFile)
            .where(OutputFile.logical_sink_id == logical)
            .order_by(OutputFile.segment_index.asc())
        ).all()
    )


def _good_merger(tmp_path, *, sample_count: int = 20):
    """A merger that actually writes and 'publishes' a real merged file."""

    def merge(request: MergeRequest) -> MergeResult:
        temp = tmp_path / f"{request.logical_sink_id}.merging"
        temp.write_bytes(b"TEMP")
        published = tmp_path / f"{request.logical_sink_id}.merged.bin"
        published.write_bytes(b"MERGED-ARTIFACT")
        return MergeResult(
            ok=True,
            temp_path=str(temp),
            published_path=str(published),
            final_output_id=uuid.uuid4().hex,
            sample_count=sample_count,
        )

    return merge


def _failing_merger(tmp_path):
    """A merger that fails but retains a diagnostic temp path (no publish)."""

    def merge(request: MergeRequest) -> MergeResult:
        temp = tmp_path / f"{request.logical_sink_id}.broken.tmp"
        temp.write_bytes(b"PARTIAL")
        return MergeResult(
            ok=False,
            temp_path=str(temp),
            reason="segment 1 unreadable",
        )

    return merge


def _lying_merger():
    """Reports ok but names a published path that does not exist."""

    def merge(request: MergeRequest) -> MergeResult:
        return MergeResult(
            ok=True,
            published_path="/nonexistent/ghost.bin",
            final_output_id=uuid.uuid4().hex,
        )

    return merge


def _coord(now_fn=None) -> FinalizationCoordinator:
    return FinalizationCoordinator(
        temp_dir="finalizer-temp",
        lease_ttl_seconds=_TTL,
        retention_seconds=_RETENTION,
        now_fn=now_fn or (lambda: datetime.now(UTC)),
    )


# ---------------------------------------------------------------------------
# Scheduling / finalizability (contract: only complete acquisitions finalize)
# ---------------------------------------------------------------------------


def test_schedule_single_component_is_not_required(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=1, complete=True)
        head = OutputFilesRepository().mark_merge_pending(logical)
        assert head.artifact_state == ARTIFACT_NOT_REQUIRED


def test_schedule_multi_component_is_merge_pending(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=3, complete=True)
        head = OutputFilesRepository().mark_merge_pending(logical)
        assert head.artifact_state == ARTIFACT_MERGE_PENDING


def test_schedule_rejects_incomplete_acquisition(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2, complete=False)
        with pytest.raises(NotFinalizable):
            OutputFilesRepository().mark_merge_pending(logical)


def test_schedule_is_idempotent(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2, complete=True)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        head = repo.mark_merge_pending(logical)
        assert head.artifact_state == ARTIFACT_MERGE_PENDING


# ---------------------------------------------------------------------------
# Claim / lease / fence token
# ---------------------------------------------------------------------------


def test_claim_transitions_to_merging_and_mints_fence(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2, complete=True)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)

        claim = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        assert claim is not None
        assert claim.fence_token == 1
        assert claim.finalization_id
        assert claim.component_count == 2

        head = repo.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGING
        assert head.finalization_id == claim.finalization_id
        assert head.finalizer_fence_token == 1


def test_claim_returns_none_when_nothing_pending(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2, complete=True)
        repo = OutputFilesRepository()
        # Not scheduled yet -> not claimable.
        assert repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL) is None


def test_claim_next_picks_pending_output(tmp_path, app):
    with app.app_context():
        repo = OutputFilesRepository()
        a = _make_logical_output(tmp_path, components=2, name="a")
        repo.mark_merge_pending(a)
        claim = repo.claim_next(worker_id="w1", lease_ttl_seconds=_TTL)
        assert claim is not None
        assert claim.logical_sink_id == a


def test_second_claim_of_healthy_lease_returns_none(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        first = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        assert first is not None
        # Lease is fresh -> a second worker cannot steal it.
        second = repo.claim(logical, worker_id="w2", lease_ttl_seconds=_TTL)
        assert second is None


# ---------------------------------------------------------------------------
# Heartbeat + stale-lease recovery + fencing
# ---------------------------------------------------------------------------


def test_heartbeat_ok_for_owner(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        claim = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        # Should not raise.
        repo.heartbeat(
            logical,
            finalization_id=claim.finalization_id,
            fence_token=claim.fence_token,
        )


def test_stale_lease_is_reclaimable_and_fences_prior_owner(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)

        first = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        assert first.fence_token == 1

        # Simulate a crashed finalizer: its lease heartbeat goes stale.
        head = repo.get_head(logical)
        head.finalized_at = datetime.now(UTC) - timedelta(seconds=_TTL + 60)
        db.session.commit()

        second = repo.claim(logical, worker_id="w2", lease_ttl_seconds=_TTL)
        assert second is not None
        assert second.fence_token == 2

        # The prior owner is now fenced out: it can neither heartbeat nor publish.
        with pytest.raises(StaleFinalizerClaim):
            repo.heartbeat(
                logical,
                finalization_id=first.finalization_id,
                fence_token=first.fence_token,
            )
        with pytest.raises(StaleFinalizerClaim):
            repo.mark_merged(
                logical,
                finalization_id=first.finalization_id,
                fence_token=first.fence_token,
                final_output_id="ghost",
            )
        # No false artifact was published.
        assert repo.get_head(logical).final_output_id is None


def test_stale_attempt_cannot_publish_after_takeover(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        first = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)

        head = repo.get_head(logical)
        head.finalized_at = datetime.now(UTC) - timedelta(seconds=_TTL + 60)
        db.session.commit()
        second = repo.claim(logical, worker_id="w2", lease_ttl_seconds=_TTL)

        # The live (second) owner publishes normally.
        repo.mark_merged(
            logical,
            finalization_id=second.finalization_id,
            fence_token=second.fence_token,
            final_output_id="real-artifact",
        )
        assert repo.get_head(logical).artifact_state == ARTIFACT_MERGED
        assert repo.get_head(logical).final_output_id == "real-artifact"

        # The fenced-out first attempt cannot overwrite the published artifact.
        with pytest.raises(StaleFinalizerClaim):
            repo.mark_merged(
                logical,
                finalization_id=first.finalization_id,
                fence_token=first.fence_token,
                final_output_id="stale-artifact",
            )
        assert repo.get_head(logical).final_output_id == "real-artifact"


def test_publish_under_fence_rejects_stale_before_filesystem_callback(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        first = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        head = repo.get_head(logical)
        head.finalized_at = datetime.now(UTC) - timedelta(seconds=_TTL + 60)
        db.session.commit()
        assert repo.claim(logical, worker_id="w2", lease_ttl_seconds=_TTL) is not None

        called = []
        with pytest.raises(StaleFinalizerClaim):
            repo.publish_under_fence(
                logical,
                finalization_id=first.finalization_id,
                fence_token=first.fence_token,
                final_output_id="stale",
                publish=lambda: called.append(True),
            )
        assert called == []
        assert repo.get_head(logical).final_output_id is None


# ---------------------------------------------------------------------------
# Terminal transitions
# ---------------------------------------------------------------------------


def test_mark_merged_stamps_final_output_id_on_all_components(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=3)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        claim = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)

        repo.mark_merged(
            logical,
            finalization_id=claim.finalization_id,
            fence_token=claim.fence_token,
            final_output_id="final-xyz",
        )
        rows = _component_rows(logical)
        assert len(rows) == 3
        assert all(r.final_output_id == "final-xyz" for r in rows)
        head = repo.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGED
        assert head.finalized_at is not None


def test_mark_merged_is_idempotent(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        claim = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        kwargs = dict(
            finalization_id=claim.finalization_id,
            fence_token=claim.fence_token,
            final_output_id="final-1",
        )
        repo.mark_merged(logical, **kwargs)
        again = repo.mark_merged(logical, **kwargs)  # replay
        assert again.artifact_state == ARTIFACT_MERGED
        assert again.final_output_id == "final-1"


def test_mark_merge_failed_preserves_components_and_publishes_nothing(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        claim = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)

        rows_before = {r.output_id: r.path for r in _component_rows(logical)}
        repo.mark_merge_failed(
            logical,
            finalization_id=claim.finalization_id,
            fence_token=claim.fence_token,
        )
        head = repo.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGE_FAILED
        assert head.final_output_id is None

        rows_after = {r.output_id: r.path for r in _component_rows(logical)}
        assert rows_after == rows_before
        for path in rows_after.values():
            assert Path(path).exists(), "component file must be retained on failure"


def test_merge_failed_is_retryable(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        repo = OutputFilesRepository()
        repo.mark_merge_pending(logical)
        first = repo.claim(logical, worker_id="w1", lease_ttl_seconds=_TTL)
        repo.mark_merge_failed(
            logical,
            finalization_id=first.finalization_id,
            fence_token=first.fence_token,
        )
        # A fresh claim can retry a failed merge, bumping the fence token.
        retry = repo.claim(logical, worker_id="w2", lease_ttl_seconds=_TTL)
        assert retry is not None
        assert retry.fence_token == 2
        assert repo.get_head(logical).artifact_state == ARTIFACT_MERGING


# ---------------------------------------------------------------------------
# Coordinator (service) end-to-end with injected mergers
# ---------------------------------------------------------------------------


def test_coordinator_finalize_once_publishes(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        coord = _coord()
        coord.schedule(logical)

        outcome = coord.finalize_once(
            _good_merger(tmp_path), worker_id="w1", logical_sink_id=logical
        )
        assert outcome is not None
        assert outcome.action == "merged"
        assert outcome.final_output_id
        head = coord.repository.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGED
        # Components remain on disk after publish.
        for row in _component_rows(logical):
            assert Path(row.path).exists()


def test_coordinator_atomically_publishes_verified_temp(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        coord = _coord()
        coord.schedule(logical)
        target = tmp_path / "staged.merged.bin"

        def staged(request):
            temp = tmp_path / f"{request.finalization_id}.partial"
            temp.write_bytes(b"VERIFIED")
            return MergeResult(
                ok=True,
                temp_path=str(temp),
                published_path=str(target),
                final_output_id="artifact-1",
            )

        outcome = coord.finalize_once(staged, worker_id="w1", logical_sink_id=logical)

        assert outcome.action == "merged"
        assert target.read_bytes() == b"VERIFIED"
        assert not Path(outcome.temp_path).exists()


def test_coordinator_failure_retains_components_and_temp(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        coord = _coord()
        coord.schedule(logical)

        outcome = coord.finalize_once(
            _failing_merger(tmp_path), worker_id="w1", logical_sink_id=logical
        )
        assert outcome.action == "failed"
        assert outcome.reason == "segment 1 unreadable"
        assert Path(outcome.temp_path).exists(), "diagnostic temp must be retained"
        head = coord.repository.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGE_FAILED
        assert head.final_output_id is None
        for row in _component_rows(logical):
            assert Path(row.path).exists()


def test_coordinator_downgrades_false_success_to_failed(tmp_path, app):
    """A merger that claims ok but has no real published file must not publish."""
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        coord = _coord()
        coord.schedule(logical)

        outcome = coord.finalize_once(
            _lying_merger(), worker_id="w1", logical_sink_id=logical
        )
        assert outcome.action == "failed"
        head = coord.repository.get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGE_FAILED
        assert head.final_output_id is None


def test_coordinator_crashing_merger_does_not_publish(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        coord = _coord()
        coord.schedule(logical)

        def _boom(_request):
            raise RuntimeError("merger died")

        outcome = coord.finalize_once(
            _boom, worker_id="w1", logical_sink_id=logical
        )
        assert outcome.action == "failed"
        assert coord.repository.get_head(logical).artifact_state == ARTIFACT_MERGE_FAILED


def test_coordinator_finalize_once_returns_none_when_idle(tmp_path, app):
    with app.app_context():
        coord = _coord()
        assert coord.finalize_once(_good_merger(tmp_path), worker_id="w1") is None


# ---------------------------------------------------------------------------
# Cleanup eligibility (boundary for packet 29)
# ---------------------------------------------------------------------------


def test_cleanup_not_eligible_before_publish(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        coord = _coord()
        coord.schedule(logical)
        assert coord.cleanup_eligibility(logical) is False


def test_cleanup_not_eligible_until_retention_elapses(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2)
        clock = {"now": datetime.now(UTC)}
        coord = FinalizationCoordinator(
            temp_dir="finalizer-temp",
            lease_ttl_seconds=_TTL,
            retention_seconds=100.0,
            now_fn=lambda: clock["now"],
        )
        coord.schedule(logical)
        coord.finalize_once(
            _good_merger(tmp_path), worker_id="w1", logical_sink_id=logical
        )
        # Immediately after publish: retention window not yet elapsed.
        assert coord.cleanup_eligibility(logical) is False
        # After the retention window: eligible.
        clock["now"] = clock["now"] + timedelta(seconds=101)
        assert coord.cleanup_eligibility(logical) is True


def test_cleanup_never_eligible_for_single_component(tmp_path, app):
    with app.app_context():
        logical = _make_logical_output(tmp_path, components=1)
        coord = _coord()
        coord.schedule(logical)  # -> not_required
        assert coord.cleanup_eligibility(logical) is False


# ---------------------------------------------------------------------------
# Merger registry helper
# ---------------------------------------------------------------------------


def test_resolve_merger_falls_back_when_unregistered(app):
    with app.app_context():
        merger = resolve_merger({}, "edf")
        result = merger(
            MergeRequest(
                logical_sink_id="l",
                finalization_id="f",
                fence_token=1,
                sink_type="edf",
                base_path="/tmp/x",
                temp_dir="finalizer-temp",
                components=(),
            )
        )
        assert result.ok is False
        assert "no merger registered" in result.reason


def test_coordinator_from_config_reads_knobs():
    coord = coordinator_from_config(TestingConfig)
    assert coord._lease_ttl_seconds == TestingConfig.FINALIZER_LEASE_TTL_SECONDS
    assert coord._retention_seconds == TestingConfig.FINALIZER_COMPONENT_RETENTION_SECONDS


# ---------------------------------------------------------------------------
# Finalizer process entrypoint (no hardware; READY handshake; run_cycle)
# ---------------------------------------------------------------------------


def test_finalizer_process_owns_no_hardware_handles():
    """The dedicated finalizer must import no hardware/runtime-worker modules."""
    import ast

    source = Path("app/finalizer_process/__main__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = (
        "morelia",
        "hardware_lease",
        "runtime_child",
        "runtime_host",
        "watchdog_process",
    )
    for module in imported:
        low = module.lower()
        for token in forbidden:
            assert token not in low, f"finalizer must not import {module!r}"

    # Must use the minimal worker DB app, never the full HTTP application factory.
    assert "create_database_app" in source
    assert "from app import create_app" not in source


def test_finalizer_arg_parser():
    from app.finalizer_process.__main__ import build_arg_parser

    args = build_arg_parser().parse_args(["--worker-id", "w1", "--once"])
    assert args.worker_id == "w1"
    assert args.once is True


def test_finalizer_run_cycle_finalizes_all_pending(tmp_path, app):
    from app.finalizer_process.__main__ import run_cycle

    with app.app_context():
        repo = OutputFilesRepository()
        a = _make_logical_output(tmp_path, components=2, name="a")
        b = _make_logical_output(tmp_path, components=2, name="b")
        repo.mark_merge_pending(a)
        repo.mark_merge_pending(b)

        coord = _coord()
        registry = {"csv": _good_merger(tmp_path)}
        outcomes = run_cycle(coord, worker_id="w1", registry=registry)

        assert {o.action for o in outcomes} == {"merged"}
        assert len(outcomes) == 2
        assert repo.get_head(a).artifact_state == ARTIFACT_MERGED
        assert repo.get_head(b).artifact_state == ARTIFACT_MERGED


def test_finalizer_main_once_prints_ready_and_finalizes(tmp_path, app, monkeypatch, capsys):
    import app.finalizer_process.__main__ as entry

    # Point the process at the test app's in-memory DB (same thread/engine).
    monkeypatch.setattr(entry, "create_database_app", lambda *a, **k: app)

    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2, name="main")
        OutputFilesRepository().mark_merge_pending(logical)

    rc = entry.main(
        ["--worker-id", "w1", "--config", "testing", "--once"],
        merger_registry={"csv": _good_merger(tmp_path)},
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "READY" in out

    with app.app_context():
        assert (
            OutputFilesRepository().get_head(logical).artifact_state == ARTIFACT_MERGED
        )


def test_finalizer_main_once_ignored_state_when_no_merger(tmp_path, app, monkeypatch, capsys):
    """With an empty registry the job fails (retryable), never falsely merges."""
    import app.finalizer_process.__main__ as entry

    monkeypatch.setattr(entry, "create_database_app", lambda *a, **k: app)

    with app.app_context():
        logical = _make_logical_output(tmp_path, components=2, name="nomerge")
        OutputFilesRepository().mark_merge_pending(logical)

    rc = entry.main(["--worker-id", "w1", "--config", "testing", "--once"])
    assert rc == 0

    with app.app_context():
        head = OutputFilesRepository().get_head(logical)
        assert head.artifact_state == ARTIFACT_MERGE_FAILED
        assert head.final_output_id is None


def test_finalizer_main_builds_production_registry_by_default(app, monkeypatch):
    import app.finalizer_process.__main__ as entry

    marker = {"edf": lambda request: request}
    calls = []
    monkeypatch.setattr(entry, "create_database_app", lambda *a, **k: app)
    monkeypatch.setattr(
        entry,
        "build_default_merger_registry",
        lambda: calls.append("built") or marker,
    )

    class IdleCoordinator:
        def finalize_once(self, merger, *, worker_id):
            return None

    assert entry.main(
        ["--worker-id", "w1", "--config", "testing", "--once"],
        coordinator_factory=lambda config: IdleCoordinator(),
    ) == 0
    assert calls == ["built"]
