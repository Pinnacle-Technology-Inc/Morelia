import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli.main import pinnacle
from app.database import create_database_app, db
from app.domain.enums import RuntimeOwnershipState, SessionStatus
from app.models.output_file import OutputFile
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.services.output_finalization import OutputReconciliationRefused


class _DatabaseApp:
    def app_context(self):
        return nullcontext()


@pytest.mark.parametrize(
    ("session_id", "mode_args", "expected_apply"),
    [
        (1, [], False),
        (23, ["--dry-run"], False),
        (987, ["--apply"], True),
    ],
)
def test_output_reconcile_forwards_mode_and_serializes_service_result(
    monkeypatch, session_id, mode_args, expected_apply
):
    import app.cli.output_cmd as output_cmd

    calls = []
    service_result = {
        "session_id": session_id,
        "mode": "apply" if expected_apply else "dry_run",
        "proof": f"service-result-{session_id}",
    }
    monkeypatch.setattr(output_cmd, "create_database_app", lambda: _DatabaseApp())
    monkeypatch.setattr(
        output_cmd,
        "reconcile_stopped_session_outputs",
        lambda session_id, apply: calls.append((session_id, apply))
        or service_result,
    )

    result = CliRunner().invoke(
        pinnacle,
        ["output", "reconcile", "--session", str(session_id), *mode_args],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(session_id, expected_apply)]
    assert json.loads(result.output) == service_result


@pytest.mark.parametrize(
    "error",
    [
        KeyError("session 404 not found"),
        OutputReconciliationRefused("session 23 still has active ownership"),
    ],
)
def test_output_reconcile_reports_expected_service_refusals(monkeypatch, error):
    import app.cli.output_cmd as output_cmd

    monkeypatch.setattr(output_cmd, "create_database_app", lambda: _DatabaseApp())

    def refuse_reconciliation(_session_id, *, apply):  # noqa: ARG001
        raise error

    monkeypatch.setattr(
        output_cmd,
        "reconcile_stopped_session_outputs",
        refuse_reconciliation,
    )

    result = CliRunner().invoke(pinnacle, ["output", "reconcile", "--session", "23"])

    assert result.exit_code != 0
    assert str(error) in result.output


def test_output_reconcile_rejects_conflicting_modes_before_database_access(monkeypatch):
    import app.cli.output_cmd as output_cmd

    def unexpected_database_access():
        raise AssertionError("conflicting CLI flags must be rejected before database access")

    monkeypatch.setattr(output_cmd, "create_database_app", unexpected_database_access)
    result = CliRunner().invoke(
        pinnacle,
        ["output", "reconcile", "--session", "23", "--dry-run", "--apply"],
    )

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


@pytest.fixture
def reconciliation_app(tmp_path):
    database_path = tmp_path / "reconciliation.sqlite3"
    app = create_database_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}"},
    )
    with app.app_context():
        db.create_all()
    return app


def _seed_repairable_output(app, directory: Path) -> tuple[int, int, int]:
    head_path = directory / "segment-0.pvfs"
    terminal_path = directory / "segment-1.pvfs"
    head_path.write_bytes(b"superseded component")
    terminal_path.write_bytes(b"terminal component")

    with app.app_context():
        session = Session(name="Completed run", status=SessionStatus.COMPLETED)
        db.session.add(session)
        db.session.flush()
        head = OutputFile(
            output_id="output-head",
            logical_sink_id="logical-output",
            segment_index=0,
            session_id=session.id,
            dataflow_id="dataflow-1",
            sink_id="pvfs-main",
            sink_type="pvfs",
            path=str(head_path),
            status="open",
            acquisition_state="interrupted",
            artifact_state="not_required",
        )
        terminal = OutputFile(
            output_id="output-terminal",
            logical_sink_id="logical-output",
            segment_index=1,
            previous_output_id="output-head",
            session_id=session.id,
            dataflow_id="dataflow-1",
            sink_id="pvfs-main",
            sink_type="pvfs",
            path=str(terminal_path),
            status="closed",
            acquisition_state="complete",
            artifact_state="not_required",
            termination_reason="clean",
        )
        db.session.add_all([head, terminal])
        db.session.commit()
        return session.id, head.id, terminal.id


def test_output_reconcile_dry_run_is_non_mutating_and_apply_repairs_real_database(
    monkeypatch, reconciliation_app, tmp_path
):
    import app.cli.output_cmd as output_cmd

    session_id, head_id, terminal_id = _seed_repairable_output(
        reconciliation_app, tmp_path
    )
    monkeypatch.setattr(
        output_cmd,
        "create_database_app",
        lambda: reconciliation_app,
    )

    dry_run = CliRunner().invoke(
        pinnacle,
        ["output", "reconcile", "--session", str(session_id)],
    )

    assert dry_run.exit_code == 0, dry_run.output
    dry_report = json.loads(dry_run.output)
    assert dry_report["mode"] == "dry_run"
    assert dry_report["repairable_components"] == 1
    assert dry_report["repaired_components"] == 0
    assert dry_report["logical_outputs"][0]["action"] == "would_repair"
    with reconciliation_app.app_context():
        assert db.session.get(OutputFile, head_id).status == "open"
        assert db.session.get(OutputFile, terminal_id).acquisition_state == "complete"

    applied = CliRunner().invoke(
        pinnacle,
        ["output", "reconcile", "--session", str(session_id), "--apply"],
    )

    assert applied.exit_code == 0, applied.output
    apply_report = json.loads(applied.output)
    assert apply_report["mode"] == "apply"
    assert apply_report["repaired_components"] == 1
    assert apply_report["scheduled_outputs"] == 1
    assert apply_report["logical_outputs"][0]["action"] == "repaired"
    with reconciliation_app.app_context():
        head = db.session.get(OutputFile, head_id)
        terminal = db.session.get(OutputFile, terminal_id)
        assert head.status == "closed"
        assert head.acquisition_state == "interrupted"
        assert head.termination_reason == "recovery"
        assert head.artifact_state == "merge_pending"
        assert terminal.status == "closed"
        assert terminal.acquisition_state == "complete"


def test_output_reconcile_refuses_live_runtime_ownership_without_mutation(
    monkeypatch, reconciliation_app
):
    import app.cli.output_cmd as output_cmd

    with reconciliation_app.app_context():
        session = Session(name="Still owned", status=SessionStatus.COMPLETED)
        db.session.add(session)
        db.session.flush()
        ownership = RuntimeOwnership(
            runtime_id="runtime-live",
            session_id=session.id,
            dataflow_id="dataflow-live",
            manifest_hash="manifest-live",
            state=RuntimeOwnershipState.RUNNING,
        )
        db.session.add(ownership)
        db.session.commit()
        session_id = session.id
        ownership_id = ownership.id

    monkeypatch.setattr(
        output_cmd,
        "create_database_app",
        lambda: reconciliation_app,
    )
    result = CliRunner().invoke(
        pinnacle,
        ["output", "reconcile", "--session", str(session_id), "--apply"],
    )

    assert result.exit_code != 0
    assert "runtime ownership" in result.output
    with reconciliation_app.app_context():
        assert db.session.get(RuntimeOwnership, ownership_id).state is RuntimeOwnershipState.RUNNING
