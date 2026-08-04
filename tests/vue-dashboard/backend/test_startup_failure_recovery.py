from datetime import UTC, datetime, timedelta

import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.database import db, transaction
from app.domain.enums import DeviceClaimState, DeviceType, OperationState
from app.models.device_config import DeviceConfig
from app.models.operation import Operation
from app.models.session import Session
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from app.services import device_configs
from app.services.sessions import create as create_session
from app.services.sessions import start_managed


class _PreflightFailureSupervisor:
    def spawn(self, session, *, manifest=None):  # noqa: ANN001
        raise RuntimeError("watchdog preflight failed")


class _SinkDependencyMissingSupervisor:
    """Fails spawn the way sink-aware startup preflight does when a SELECTED
    sink's optional/native dependency is unavailable (gap SINK-13)."""

    def spawn(self, session, *, manifest=None):  # noqa: ANN001
        from app.domain.enums import SinkType
        from app.runtime_child.sink_factory import SinkDependencyMissing

        raise SinkDependencyMissing(
            "dev:quest",
            SinkType.QUEST,
            reason="missing import: reactivex",
            extra="quest",
        )


def _session_with_config(app, tmp_path):
    with app.app_context():
        config = device_configs.create(
            device_type=DeviceType.POD8206HR,
            hardware_id="START",
            port="COM3",
            parameters={"preamp_gain": 10},
        )
        # Route through the sessions SERVICE create (not the raw repository) so
        # the flat sink_type/sink_location is canonicalized into the resolvable
        # sinks[] collection the manifest resolver requires.
        session = create_session(
            {
                "name": "startup failure",
                "device_flows": [
                    {
                        "device_config_id": config.id,
                        "sink_type": "csv",
                        "sink_location": str(tmp_path / "output.csv"),
                    }
                ],
            }
        )
        return session.id, config.id


def test_watchdog_preflight_failure_is_durable_and_releases_claims(app, tmp_path):
    session_id, config_id = _session_with_config(app, tmp_path)
    bind_contextvars(request_id="startup-failure-request")
    try:
        with app.app_context(), pytest.raises(RuntimeError, match="preflight"):
            start_managed(session_id, _PreflightFailureSupervisor())
    finally:
        clear_contextvars()

    with app.app_context():
        session = db.session.get(Session, session_id)
        config = db.session.get(DeviceConfig, config_id)
        operation = db.session.scalar(
            db.select(Operation).where(Operation.session_id == session_id)
        )
        events = BackendEventRepository().since(session_id, after_id=0, limit=20)

    assert session.status.value == "draft"
    assert session.command_in_flight is False
    assert config.claim_state is DeviceClaimState.FREE
    assert config.claimed_session_id is None
    assert operation.state is OperationState.FAILED
    failure = next(event for event in events if event.event_type == "runtime.command_failed")
    assert failure.payload["error_code"] == "RuntimeError"
    assert failure.payload["details"]["startup_rollback"] is True


def test_missing_sink_dependency_start_is_durable_and_leaves_session_restartable(
    app, tmp_path
):
    """A selected sink whose dependency is missing fails the start with the typed,
    sink-addressed error, and the rollback frees claims + returns the session to
    draft so it is restartable (acceptance criterion 2)."""
    session_id, config_id = _session_with_config(app, tmp_path)
    bind_contextvars(request_id="sink-dep-missing-request")
    try:
        from app.runtime_child.sink_factory import SinkDependencyMissing

        with app.app_context(), pytest.raises(SinkDependencyMissing, match="quest"):
            start_managed(session_id, _SinkDependencyMissingSupervisor())
    finally:
        clear_contextvars()

    with app.app_context():
        session = db.session.get(Session, session_id)
        config = db.session.get(DeviceConfig, config_id)
        operation = db.session.scalar(
            db.select(Operation).where(Operation.session_id == session_id)
        )
        events = BackendEventRepository().since(session_id, after_id=0, limit=20)

    # Restartable: back to draft, no in-flight lock, device claim released.
    assert session.status.value == "draft"
    assert session.command_in_flight is False
    assert config.claim_state is DeviceClaimState.FREE
    assert config.claimed_session_id is None
    assert operation.state is OperationState.FAILED
    failure = next(event for event in events if event.event_type == "runtime.command_failed")
    assert failure.payload["error_code"] == "SinkDependencyMissing"
    assert failure.payload["details"]["startup_rollback"] is True


def test_expired_starting_claim_can_be_reclaimed(app):
    with app.app_context():
        first_session = SessionRepository().create({"name": "first"})
        second_session = SessionRepository().create({"name": "second"})
        first = device_configs.create(
            device_type=DeviceType.POD8206HR,
            hardware_id="LEASE",
            port="COM4",
            parameters={"preamp_gain": 10},
        )
        device_configs.claim(first.id, session_id=first_session.id, starting=True, lease_seconds=1)
        with transaction():
            first.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)

        reclaimed = device_configs.claim(
            first.id, session_id=second_session.id, starting=True, lease_seconds=30
        )
        state = reclaimed.claim_state
        owner = reclaimed.claimed_session_id
        expires_at = reclaimed.claim_expires_at
        expected_owner = second_session.id

    assert state is DeviceClaimState.STARTING
    assert owner == expected_owner
    assert expires_at is not None
