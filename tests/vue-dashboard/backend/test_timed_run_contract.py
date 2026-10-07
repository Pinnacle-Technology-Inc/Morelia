from datetime import UTC, datetime, timedelta
from dataclasses import replace

import pytest
from marshmallow import ValidationError

from app.api.schemas import SessionRunExecutionSchema
from app.database import db
from app.domain.duration import max_duration_seconds, validate_duration_seconds
from app.repositories.sessions import SessionRepository
from app.services import sessions
from app.domain.enums import PolicyMode, SinkType
from app.runtime_host.manifest import Manifest, DeviceFlow


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
