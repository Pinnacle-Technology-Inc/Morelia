"""Requirement checks for duration, sample projection, and stop evidence.

Uses real marshmallow schemas, manifests and SQLite ORM/ingest. No hardware
or runtime execution is claimed by these tests.
"""
from datetime import UTC, datetime, timedelta
from dataclasses import replace

import pytest
from marshmallow import ValidationError

from app.api.schemas import SessionRunExecutionSchema
from app.database import db
from app.domain.duration import max_duration_seconds, validate_duration_seconds
from app.domain.enums import OperationState, PolicyMode, SessionStatus, SinkType
from app.domain.errors import StaleWatchdogReport
from app.models.backend_event import BackendEvent
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.runtime_host.manifest import Manifest, DeviceFlow
from app.services.event_ingest import ingest_watchdog_report
from app.services import sessions, output_finalization


@pytest.mark.parametrize("duration", [True, False, "60", 1.5, None, 0, -1])
def test_invalid_duration_is_rejected_without_coercion(duration):
    with pytest.raises(ValidationError):
        SessionRunExecutionSchema().load({"mode": "immediate", "duration_seconds": duration})


def test_duration_above_signed_32_bit_range_roundtrips(app):
    duration = 2**31
    execution = SessionRunExecutionSchema().load({
        "mode": "immediate", "duration_seconds": duration,
    })
    manifest = Manifest(schema_version="3", dataflow_id="data", policy=PolicyMode.AUTOMATE,
        duration_seconds=execution["duration_seconds"],
        device_flows=(DeviceFlow(device_id="source", name="device", hardware_id="123",
            port="COM1", parameters={}, sink_type=SinkType.CSV, sink_location="/data/test.csv"),))
    assert Manifest.from_dict(manifest.to_dict()).duration_seconds == duration
    with app.app_context():
        session = SessionRepository().create({"name": "Long duration", "duration_seconds": duration})
        db.session.commit()
        db.session.expire_all()
        assert session.duration_seconds == duration
        assert datetime(2026, 9, 23, 12, tzinfo=UTC) + timedelta(seconds=session.duration_seconds) == datetime(
            2094, 10, 11, 15, 14, 8, tzinfo=UTC,
        )


@pytest.mark.parametrize("duration", [10**12, 10**100])
def test_unrepresentable_deadline_is_rejected(duration):
    with pytest.raises(ValidationError, match="deadline"):
        SessionRunExecutionSchema().load({"mode": "immediate", "duration_seconds": duration})
    with pytest.raises(sessions.InvalidSessionEntry, match="deadline"):
        sessions.create_run({"execution": {"mode": "immediate", "duration_seconds": duration}})


@pytest.mark.parametrize("start", [
    datetime(2026, 10, 5, 0, 0, 0, 999999, tzinfo=UTC),
    datetime(9999, 12, 31, 23, 59, 57, 123456, tzinfo=UTC),
    datetime.fromisoformat("9999-12-31T18:59:57.123456-05:00"),
    datetime(9999, 12, 31, 23, 59, 57, 123456),
])
def test_duration_boundary_matches_python_datetime_arithmetic(start):
    utc_start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    maximum = max_duration_seconds(start)
    validate_duration_seconds(maximum, start_at=start)
    assert utc_start + timedelta(seconds=maximum) <= datetime.max.replace(tzinfo=UTC)
    with pytest.raises(OverflowError):
        utc_start + timedelta(seconds=maximum + 1)
    with pytest.raises(ValueError, match="Python's datetime maximum"):
        validate_duration_seconds(maximum + 1, start_at=start)


def test_duration_bound_shrinks_with_later_start():
    start = datetime(9999, 12, 31, 23, 59, 57, tzinfo=UTC)
    assert max_duration_seconds(start) == 2
    validate_duration_seconds(2, start_at=start)
    with pytest.raises(ValueError, match="at most 1 seconds"):
        validate_duration_seconds(2, start_at=start + timedelta(seconds=1))
    assert max_duration_seconds(datetime.max.replace(tzinfo=UTC)) == 0


def test_arrival_validates_bound_against_actual_start(app):
    with app.app_context():
        session, owner = setup_run()
        session.duration_seconds = 2
        db.session.commit()
        payload = {"started_at": "9999-12-31T23:59:58+00:00", "recording_bounds": [],
                   "clock_anchor": {"kind": "test", "boot_id": "boot", "deadline_elapsed": 2}}
        with pytest.raises(ValueError, match="Python's datetime maximum"):
            ingest_watchdog_report(envelope("runtime.acquisition_started", payload))
        assert session.started_at is None


def test_duration_optional_and_scheduled_forbidden():
    assert "duration_seconds" not in SessionRunExecutionSchema().load({"mode": "immediate"})
    assert SessionRunExecutionSchema().load({"mode": "immediate", "duration_seconds": 60})["duration_seconds"] == 60
    with pytest.raises(ValidationError):
        SessionRunExecutionSchema().load({"mode": "scheduled", "duration_seconds": 60,
            "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()})


def test_manifest_duration_hash_and_roundtrip():
    untimed = Manifest(schema_version="3", dataflow_id="data", policy=PolicyMode.AUTOMATE,
        device_flows=(DeviceFlow(device_id="source", name="device", hardware_id="123",
            port="COM1", parameters={}, sink_type=SinkType.CSV, sink_location="/data/test.csv"),))
    assert untimed.to_dict()["duration_seconds"] is None
    assert Manifest.from_dict(untimed.to_dict()).hash == untimed.hash
    timed = replace(untimed, duration_seconds=60)
    assert Manifest.from_dict(timed.to_dict()) == timed
    assert timed.hash != replace(timed, duration_seconds=61).hash
    tampered = timed.to_dict() | {"duration_seconds": 61}
    with pytest.raises(ValueError, match="hash mismatch"):
        Manifest.from_dict(tampered)


def setup_run():
    session = SessionRepository().create({"name": "Timed", "duration_seconds": 60,
        "status": SessionStatus.ACTIVE})
    session.dataflow_id = "data"
    db.session.commit()
    repo = RuntimeOwnershipRepository()
    owner = repo.create_starting(runtime_id="runtime", session_id=session.id,
        dataflow_id="data", manifest_hash="hash", token="secret")
    owner.watchdog_id = "watchdog"
    db.session.commit()
    return session, owner


def envelope(kind, payload, report_id=None, watchdog_id="watchdog"):
    return {"report_id": report_id or kind, "event_type": kind, "payload": payload,
        "dataflow_id": "data", "runtime_id": "runtime", "watchdog_id": watchdog_id,
        "manifest_hash": "hash"}


def recording(first="2026-09-23T12:00:00+00:00", last="2026-09-23T12:00:05+00:00"):
    return {"started_at": first, "ended_at": last, "recording_bounds": [{
        "source_id": "source", "sink_id": "sink", "first_sample_at": first, "last_sample_at": last}]}


def test_arrival_starts_countdown_without_inventing_recorded_bounds(app):
    from app.api.schemas import SessionSchema
    arrival = "2026-09-23T12:00:10+00:00"
    payload = {"started_at": arrival, "recording_bounds": [],
               "clock_anchor": {"kind": "test", "boot_id": "boot", "deadline_elapsed": 100}}
    with app.app_context():
        session, owner = setup_run()
        ingest_watchdog_report(envelope("runtime.acquisition_started", payload))
        db.session.refresh(session)
        assert session.started_at.replace(tzinfo=UTC).isoformat() == arrival
        assert session.ended_at is None
        assert owner.details["recording_state"]["clock_anchor"] == payload["clock_anchor"]
        wire = SessionSchema().dump(session)
        assert wire["started_at"] == arrival and wire["recording_bounds"] == []
        assert "first_data_at" not in wire
        saved = recording()
        ingest_watchdog_report(envelope("runtime.recording_started", payload | {
            "recording_bounds": saved["recording_bounds"], "ended_at": saved["ended_at"]}))
        db.session.refresh(session)
        assert session.started_at.replace(tzinfo=UTC).isoformat() == arrival
        assert SessionSchema().dump(session)["recording_bounds"] == saved["recording_bounds"]
        assert session.ended_at.replace(tzinfo=UTC).isoformat() == saved["ended_at"]


def test_session_api_preserves_sample_bounds_across_runtime_replacements(app):
    with app.app_context():
        session, owner = setup_run()
        arrival = "2026-09-23T12:00:10+00:00"
        ingest_watchdog_report(envelope("runtime.acquisition_started", {
            "started_at": arrival, "recording_bounds": [],
            "clock_anchor": {"kind": "test", "boot_id": "boot", "deadline_elapsed": 100},
        }))
        ingest_watchdog_report(envelope("runtime.recording_started", {
            **recording(), "started_at": arrival,
        }))
        replacement = RuntimeOwnershipRepository().create_starting(
            runtime_id="replacement", session_id=session.id, dataflow_id="data",
            manifest_hash="hash", token="replacement-secret",
            details={"recording_state": recording(
                "2026-09-23T07:00:03-05:00", "2026-09-23T07:00:20-05:00")},
        )
        other = SessionRepository().create({"name": "Other"})
        db.session.commit()
        client = app.test_client()
        detail = client.get(f"/api/v1/sessions/{session.id}").get_json()
        rows = {row["id"]: row for row in client.get("/api/v1/sessions/").get_json()}
        assert detail["started_at"] == arrival
        assert "first_data_at" not in detail
        assert detail["recording_bounds"] == [{
            "source_id": "source", "sink_id": "sink",
            "first_sample_at": "2026-09-23T12:00:00+00:00",
            "last_sample_at": "2026-09-23T07:00:20-05:00",
        }]
        assert rows[str(session.id)]["recording_bounds"] == detail["recording_bounds"]
        assert rows[str(other.id)]["recording_bounds"] == []


def stop(teardown=True, integrity=True):
    return {"command_id": "duration-stop", "stop_reason": "duration_ended",
        "requested_at": "2026-09-23T12:01:00+00:00", "shutdown_result": {"ok": integrity},
        "teardown_confirmed": teardown, "output_integrity_confirmed": integrity, "errors": []}


def test_sample_times_remain_fixed_monotonic_and_independent_of_stop(app):
    with app.app_context():
        session, owner = setup_run()
        first = envelope("runtime.recording_started", recording())
        ingest_watchdog_report(first)
        ingest_watchdog_report(first)
        ingest_watchdog_report(envelope("runtime.recording_progress", recording(
            "2026-09-23T11:59:00+00:00", "2026-09-23T12:00:02+00:00")))
        ingest_watchdog_report(envelope("runtime.stop_finished", stop()))
        db.session.refresh(session)
        assert session.started_at.replace(tzinfo=UTC).isoformat() == "2026-09-23T12:00:00+00:00"
        assert session.ended_at.replace(tzinfo=UTC).isoformat() == "2026-09-23T12:00:05+00:00"
        assert session.status == SessionStatus.COMPLETED
        assert len(db.session.scalars(db.select(Operation)).all()) == 1
        assert len(db.session.scalars(db.select(BackendEvent).where(BackendEvent.event_type == "runtime.recording_started")).all()) == 1


@pytest.mark.parametrize("teardown,integrity,status,op_state", [
    (True, True, SessionStatus.COMPLETED, OperationState.SUCCEEDED),
    (True, False, SessionStatus.COMPLETED, OperationState.SUCCEEDED),
    (False, False, SessionStatus.STOPPING, OperationState.UNCERTAIN),
])
def test_shutdown_truth_table_and_no_fabricated_sample_times(app, teardown, integrity, status, op_state):
    with app.app_context():
        session, owner = setup_run()
        receipt = envelope("runtime.stop_finished", stop(teardown, integrity))
        ingest_watchdog_report(receipt)
        ingest_watchdog_report(receipt)
        assert session.status == status
        assert session.started_at is None and session.ended_at is None
        assert db.session.scalar(db.select(Operation)).state == op_state


def test_corrupt_evidence_has_no_projection_or_event(app):
    with app.app_context():
        session, owner = setup_run()
        with pytest.raises(ValueError):
            ingest_watchdog_report(envelope("runtime.stop_finished", stop(False, True)))
        assert session.status == SessionStatus.ACTIVE
        assert db.session.scalar(db.select(db.func.count()).select_from(BackendEvent)) == 0


def test_old_shutdown_never_completes_current_producer(app):
    with app.app_context():
        session, owner = setup_run()
        owner.details = {"predecessor_watchdogs": [{"watchdog_id": "old", "runtime_id": "runtime",
            "dataflow_id": "data", "manifest_hash": "hash", "outbox_path": "old.sqlite3"}]}
        db.session.commit()
        ingest_watchdog_report(envelope("runtime.stop_finished", stop(), watchdog_id="old"))
        assert session.status == SessionStatus.ACTIVE
        assert owner.watchdog_id == "watchdog"
        assert owner.stopped_at is None
        with pytest.raises(StaleWatchdogReport):
            ingest_watchdog_report(envelope("runtime.report", {}, watchdog_id="old"))


def test_stop_pending_schedule_is_idempotent_and_never_launches(app):
    class MustNotLaunch:
        def stop(self, *args, **kwargs):
            raise AssertionError("pending scheduled Stop must not launch or contact runtime")
    with app.app_context():
        session = SessionRepository().create({"name": "Future", "status": SessionStatus.SCHEDULED,
            "scheduled_for": datetime.now(UTC) + timedelta(hours=1), "schedule": {"mode": "once"}})
        sessions.stop_managed(session.id, MustNotLaunch())
        sessions.stop_managed(session.id, MustNotLaunch())
        assert session.status == SessionStatus.COMPLETED
        assert session.scheduled_for is None
        assert session.started_at is None and session.ended_at is None
        operation = db.session.scalar(db.select(Operation))
        assert operation.details["stop_reason"] == "user_stop"
        assert operation.details["before_scheduled_start"] is True


def test_completed_unclean_output_is_not_promoted_by_finalizer(app):
    with app.app_context():
        session, owner = setup_run()
        row = OutputFile(output_id="output", logical_sink_id="logical", session_id=session.id,
            dataflow_id="data", sink_id="sink", sink_type="csv", path="incomplete.csv")
        db.session.add(row)
        db.session.commit()
        ingest_watchdog_report(envelope("runtime.stop_finished", stop(True, False)))
        output_finalization.reconcile_completed_session_acquisitions()
        assert row.acquisition_state == "interrupted"
        assert row.artifact_state != "merged"


def test_conflicting_report_replay_cannot_change_recorded_bounds(app):
    with app.app_context():
        session, owner = setup_run()
        ingest_watchdog_report(envelope("runtime.recording_started", recording(), "same-id"))
        with pytest.raises(ValueError, match="different durable evidence"):
            ingest_watchdog_report(envelope("runtime.recording_started", recording(
                last="2026-09-23T12:05:00+00:00"), "same-id"))
        db.session.refresh(session)
        assert session.ended_at.replace(tzinfo=UTC).isoformat() == "2026-09-23T12:00:05+00:00"


def test_stronger_teardown_proof_resolves_uncertainty_without_claiming_clean_output(app):
    with app.app_context():
        session, owner = setup_run()
        sessions.apply_shutdown_result(session, stop(False, False), owner)
        assert session.status == SessionStatus.STOPPING
        sessions.apply_shutdown_result(session, stop(True, True), owner)
        assert session.status == SessionStatus.COMPLETED
        operation = db.session.scalar(db.select(Operation))
        assert operation.state == OperationState.SUCCEEDED
        assert operation.details["output_integrity_confirmed"] is False
        assert len(operation.details["shutdown_receipt_history"]) == 1


def test_current_reboot_anchor_updates_but_old_producer_replay_cannot_revert(app):
    with app.app_context():
        session, owner = setup_run()
        payload = recording() | {"clock_anchor": {
            "kind": "test", "boot_id": "boot-A", "deadline_elapsed": 100.0}}
        ingest_watchdog_report(envelope("runtime.recording_started", payload))
        owner.details = dict(owner.details) | {"predecessor_watchdogs": [{
            "watchdog_id": "old", "runtime_id": "runtime", "dataflow_id": "data", "manifest_hash": "hash"}]}
        db.session.commit()
        reboot = payload | {"clock_anchor": {"kind": "test", "boot_id": "boot-B", "deadline_elapsed": 50.0}}
        ingest_watchdog_report(envelope("runtime.recording_progress", reboot, "reboot"))
        ingest_watchdog_report(envelope("runtime.recording_progress", payload, "historical", watchdog_id="old"))
        assert owner.details["recording_state"]["clock_anchor"] == reboot["clock_anchor"]


def test_late_terminal_replay_cannot_release_another_sessions_device_claim(app):
    from app.models.device_config import DeviceConfig
    from app.domain.enums import DeviceType, DeviceClaimState
    with app.app_context():
        session, owner = setup_run()
        next_run = SessionRepository().create({"name": "Next", "status": SessionStatus.ACTIVE})
        config = DeviceConfig(device_type=DeviceType.POD8206HR, hardware_id="claim-test", port="COM1",
            claim_state=DeviceClaimState.CLAIMED, claimed_session_id=next_run.id)
        db.session.add(config)
        db.session.flush()
        session.device_flows = [{"device_config_id": config.id}]
        db.session.commit()
        ingest_watchdog_report(envelope("runtime.stop_finished", stop()))
        sessions._release_device_configs([config.id], session_id=session.id)
        db.session.refresh(config)
        assert config.claimed_session_id == next_run.id
        assert config.claim_state == DeviceClaimState.CLAIMED


def test_adopted_watchdog_can_replay_same_immutable_report_under_new_host(app):
    with app.app_context():
        session, owner = setup_run()
        report = envelope("runtime.recording_started", recording(), "adoption-replay")
        original_id = ingest_watchdog_report(report)
        adopted = RuntimeOwnershipRepository().create_starting(runtime_id="adopted", session_id=session.id,
            dataflow_id="data", manifest_hash="hash", token="new-token")
        adopted.watchdog_id = "watchdog"
        db.session.commit()
        assert ingest_watchdog_report(report | {"runtime_id": "adopted"}) == original_id
        assert adopted.details["recording_state"]["started_at"] == report["payload"]["started_at"]


def test_lost_stop_delivery_retries_same_command_and_persists_pending_request(app):
    from structlog.contextvars import bound_contextvars
    class LostFirstDelivery:
        def __init__(self):
            self.commands = []
        def stop(self, session, *, envelope, force=False):
            self.commands.append(envelope.correlation.command_id)
            raise OSError("connection lost before acknowledgement")
    with app.app_context(), bound_contextvars(request_id="retry-stop"):
        session, owner = setup_run()
        supervisor = LostFirstDelivery()
        sessions.stop_managed(session.id, supervisor)
        sessions.stop_managed(session.id, supervisor)
        assert len(supervisor.commands) == 2
        assert len(set(supervisor.commands)) == 1
        assert owner.details["pending_stop_request"]["command_id"] == supervisor.commands[0]
        assert session.status == SessionStatus.STOPPING
        assert db.session.scalar(db.select(Operation)).state == OperationState.UNCERTAIN


def test_lost_response_after_durable_stop_receipt_cannot_resurrect_session(app):
    from structlog.contextvars import bound_contextvars
    with app.app_context(), bound_contextvars(request_id="lost-response-after-stop"):
        session, owner = setup_run()
        class ReceiptThenLostResponse:
            def stop(self, session, *, envelope):
                payload = stop() | {"command_id": envelope.correlation.command_id, "stop_reason": "user_stop"}
                sessions.apply_shutdown_result(session, payload, owner)
                raise OSError("receipt delivered, response lost")
        sessions.stop_managed(session.id, ReceiptThenLostResponse())
        assert session.status == SessionStatus.COMPLETED
        operation = db.session.scalar(db.select(Operation))
        assert operation.state == OperationState.SUCCEEDED
        assert operation.details["stop_reason"] == "user_stop"
