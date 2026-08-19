from datetime import UTC, datetime, timedelta

from app.database import transaction
from app.domain.enums import DeviceClaimState, DeviceType
from app.repositories.sessions import SessionRepository
from app.services import device_configs


def test_expired_starting_claim_can_be_reclaimed(app):
    with app.app_context():
        first_session = SessionRepository().create({"name": "first"})
        second_session = SessionRepository().create({"name": "second"})
        first = device_configs.create(
            device_type=DeviceType.POD8206HR,
            hardware_id="001",
            port="COM4",
            parameters={
                "preamp_gain": 10,
                "sample_rate": 2000,
                },
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
