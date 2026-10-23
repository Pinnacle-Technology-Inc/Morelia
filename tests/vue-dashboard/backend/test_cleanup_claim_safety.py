"""Real SQLite ownership-fencing and lease-cleanup regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import update

from app.database import create_database_app, db
from app.domain.enums import DeviceClaimState, DeviceType, RuntimeOwnershipState, SessionStatus, WatchdogProcessState
from app.domain.errors import DeviceClaimConflict
from app.models.device_config import DeviceConfig
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.services import device_configs


@pytest.fixture
def claims_app(tmp_path):
    app = create_database_app("testing", {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'claims.sqlite3'}"})
    with app.app_context():
        db.create_all()
        db.session.add_all([Session(id=1, name="old"), Session(id=2, name="new")])
        db.session.flush()
        db.session.add(DeviceConfig(id=1, device_type=DeviceType.POD8206HR, hardware_id="001", port="001"))
        db.session.commit()
    return app


def _expired_claim(**session_changes):
    session = db.session.get(Session, 1)
    for key, value in session_changes.items():
        setattr(session, key, value)
    row = db.session.get(DeviceConfig, 1)
    row.claim_state = DeviceClaimState.STARTING
    row.claimed_session_id = 1
    row.claim_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db.session.commit()
    return row


def _runtime(*, state=RuntimeOwnershipState.RUNNING, **changes):
    row = RuntimeOwnership(runtime_id="runtime", session_id=1, dataflow_id="flow", manifest_hash="hash", state=state, **changes)
    db.session.add(row)
    db.session.commit()
    return row


@pytest.mark.parametrize("changes", [
    {"status": status} for status in (SessionStatus.STARTING, SessionStatus.ACTIVE, SessionStatus.STOPPING)
] + [{"command_in_flight": True}, {"command_id": "launch"}, {"dataflow_id": "flow"}, {"runtime_port": 9000}, {"runtime_token": "token"}])
def test_expired_launch_intent_retains_claim(claims_app, changes):
    with claims_app.app_context():
        row = _expired_claim(**changes)
        assert device_configs.release_expired_starting_claims() == 0
        with pytest.raises(DeviceClaimConflict):
            device_configs.claim(1, 2, force=True)
        db.session.refresh(row)
        assert row.claimed_session_id == 1


@pytest.mark.parametrize("state", [RuntimeOwnershipState.STARTING, RuntimeOwnershipState.RUNNING, RuntimeOwnershipState.UNCERTAIN, RuntimeOwnershipState.STOPPING])
def test_terminal_session_with_unresolved_runtime_retains_claim(claims_app, state):
    with claims_app.app_context():
        row = _expired_claim(status=SessionStatus.COMPLETED)
        _runtime(state=state)
        assert device_configs.release_expired_starting_claims() == 0
        with pytest.raises(DeviceClaimConflict):
            device_configs.release(1, expected_session_id=1)
        assert row.claimed_session_id == 1


def test_expired_never_launched_reservation_is_released(claims_app):
    with claims_app.app_context():
        row = _expired_claim()
        assert device_configs.release_expired_starting_claims() == 1
        db.session.refresh(row)
        assert (row.claim_state, row.claimed_session_id, row.claim_expires_at) == (DeviceClaimState.FREE, None, None)
        assert device_configs.release_expired_starting_claims() == 0


def test_expired_never_launched_reservation_can_be_reclaimed(claims_app):
    with claims_app.app_context():
        _expired_claim()
        assert device_configs.claim(1, 2).claimed_session_id == 2


@pytest.mark.parametrize("runtime_changes, released", [
    ({}, False),
    ({"stopped_at": datetime.now(UTC), "watchdog_id": "watchdog", "watchdog_state": WatchdogProcessState.UNCERTAIN}, False),
    ({"stopped_at": datetime.now(UTC), "watchdog_pid": 12}, False),
    ({"stopped_at": datetime.now(UTC), "watchdog_id": "watchdog", "watchdog_state": WatchdogProcessState.STOPPED}, False),
    ({"stopped_at": datetime.now(UTC), "watchdog_id": "watchdog", "watchdog_state": WatchdogProcessState.STOPPED, "watchdog_exit_details": {"teardown_confirmed": True}}, True),
])
def test_terminal_cleanup_requires_completed_runtime_teardown(claims_app, runtime_changes, released):
    with claims_app.app_context():
        _expired_claim(status=SessionStatus.COMPLETED)
        _runtime(state=RuntimeOwnershipState.STOPPED, **runtime_changes)
        assert device_configs.release_expired_starting_claims() == int(released)


@pytest.mark.parametrize("action", ["claim", "activate", "release"])
def test_stale_snapshot_cannot_overwrite_successor(claims_app, monkeypatch, action):
    with claims_app.app_context():
        old = device_configs.claim(1, 1, starting=True)
        # Keep a stale ORM identity but install successor through an independent
        # database connection, after the service has read its expected owner.
        original = device_configs._update_claim
        def interleave(row, **kwargs):
            with db.engine.begin() as conn:
                conn.execute(update(DeviceConfig).where(DeviceConfig.id == 1).values(claimed_session_id=2))
            return original(row, **kwargs)
        monkeypatch.setattr(device_configs, "_update_claim", interleave)
        with pytest.raises(DeviceClaimConflict):
            if action == "claim":
                device_configs.claim(1, 1, starting=True)
            elif action == "activate":
                device_configs.activate(1, 1)
            else:
                device_configs.release(1)
        db.session.refresh(old)
        assert old.claimed_session_id == 2
        assert old.claim_state == DeviceClaimState.STARTING


def test_delayed_owner_release_rejects_new_reservation(claims_app):
    with claims_app.app_context():
        row = device_configs.claim(1, 2, starting=True)
        with pytest.raises(DeviceClaimConflict):
            device_configs.release(1, expected_session_id=1)
        assert row.claimed_session_id == 2
        device_configs.release(1, expected_session_id=2)
        assert device_configs.release(1, expected_session_id=2).claim_state == DeviceClaimState.FREE


def test_simultaneous_claimants_have_one_winner(claims_app, monkeypatch):
    barrier = Barrier(2)
    original = device_configs._require
    def simultaneous_snapshot(config_id):
        row = original(config_id)
        barrier.wait(timeout=5)
        return row
    monkeypatch.setattr(device_configs, "_require", simultaneous_snapshot)
    def acquire(session_id):
        with claims_app.app_context():
            try:
                device_configs.claim(1, session_id, starting=True)
                return session_id
            except DeviceClaimConflict:
                return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(acquire, (1, 2)))
    winners = [value for value in outcomes if value is not None]
    assert len(winners) == 1
    with claims_app.app_context():
        assert db.session.get(DeviceConfig, 1).claimed_session_id == winners[0]


def test_force_cannot_replace_nonexpiring_live_claim(claims_app):
    with claims_app.app_context():
        session = db.session.get(Session, 1)
        session.status = SessionStatus.ACTIVE
        db.session.commit()
        row = device_configs.claim(1, 1)
        with pytest.raises(DeviceClaimConflict):
            device_configs.claim(1, 2, force=True)
        assert row.claimed_session_id == 1
        assert row.claim_state == DeviceClaimState.CLAIMED


def test_starting_owner_can_activate_then_release_after_terminal_proof(claims_app):
    with claims_app.app_context():
        device_configs.claim(1, 1, starting=True)
        row = device_configs.activate(1, 1)
        assert row.claim_state == DeviceClaimState.CLAIMED
        assert row.claim_expires_at is None
        session = db.session.get(Session, 1)
        session.status = SessionStatus.COMPLETED
        db.session.commit()
        _runtime(state=RuntimeOwnershipState.STOPPED, stopped_at=datetime.now(UTC),
                 watchdog_id="watchdog", watchdog_state=WatchdogProcessState.STOPPED,
                 watchdog_exit_details={"teardown_confirmed": True})
        assert device_configs.release(1, expected_session_id=1).claim_state == DeviceClaimState.FREE


def test_lease_renewal_fences_a_stale_release(claims_app, monkeypatch):
    with claims_app.app_context():
        row = _expired_claim()
        original = device_configs._update_claim
        renewed = datetime.now(UTC) + timedelta(seconds=120)
        def renew_lease(row, **kwargs):
            with db.engine.begin() as conn:
                conn.execute(update(DeviceConfig).where(DeviceConfig.id == 1).values(claim_expires_at=renewed))
            return original(row, **kwargs)
        monkeypatch.setattr(device_configs, "_update_claim", renew_lease)
        with pytest.raises(DeviceClaimConflict):
            device_configs.release(1, expected_session_id=1)
        db.session.refresh(row)
        assert row.claimed_session_id == 1
        assert row.claim_expires_at.replace(tzinfo=UTC) == renewed


@pytest.mark.parametrize("mismatch", [None, "runtime_id", "watchdog_id", "dataflow_id", "manifest_hash", "teardown_confirmed"])
def test_administrative_teardown_receipt_must_match_owner(claims_app, mismatch):
    with claims_app.app_context():
        _expired_claim(status=SessionStatus.COMPLETED)
        record = {"runtime_id": "runtime", "watchdog_id": "watchdog", "dataflow_id": "flow",
                  "manifest_hash": "hash", "payload": {"teardown_confirmed": True}}
        if mismatch == "teardown_confirmed":
            record["payload"]["teardown_confirmed"] = False
        elif mismatch:
            record[mismatch] = "stale"
        _runtime(state=RuntimeOwnershipState.STOPPED, stopped_at=datetime.now(UTC),
                 watchdog_id="watchdog", watchdog_state=WatchdogProcessState.STOPPED,
                 details={"administrative_stop_evidence": record})
        assert device_configs.release_expired_starting_claims() == int(mismatch is None)


@pytest.mark.parametrize("identities", [{}, {"pid": 42}, {"watchdog_id": "watchdog"}, {"watchdog_pid": 43}])
def test_failed_launch_proof_requires_no_child_identity(claims_app, identities):
    with claims_app.app_context():
        _expired_claim(status=SessionStatus.COMPLETED)
        _runtime(state=RuntimeOwnershipState.STOPPED, stopped_at=datetime.now(UTC),
                 details={"host_launch_failed": True}, **identities)
        assert device_configs.release_expired_starting_claims() == int(not identities)


def test_legacy_stopped_runtime_cannot_be_forced_or_released(claims_app):
    with claims_app.app_context():
        _expired_claim(status=SessionStatus.COMPLETED)
        _runtime(state=RuntimeOwnershipState.STOPPED, stopped_at=datetime.now(UTC),
                 pid=42, watchdog_id="watchdog", watchdog_pid=43,
                 watchdog_state=WatchdogProcessState.STOPPED)
        with pytest.raises(DeviceClaimConflict):
            device_configs.claim(1, 2, force=True)
        with pytest.raises(DeviceClaimConflict):
            device_configs.release(1, expected_session_id=1)
        assert db.session.get(DeviceConfig, 1).claimed_session_id == 1
