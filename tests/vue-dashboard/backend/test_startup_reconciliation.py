import pytest

from app import create_app
from app.database import db
from app.domain.enums import (
    OperationState,
    RuntimeOwnershipState,
    SessionStatus,
    WatchdogProcessState,
)
from app.models.operation import Operation
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.services.operations import OperationConflict, create_operation, transition_operation
from app.services.reconciliation import reconcile_startup


def _app(database_url: str | None = None, **overrides):
    config = {"STARTUP_RECONCILIATION_ENABLED": False, **overrides}
    if database_url is not None:
        config["SQLALCHEMY_DATABASE_URI"] = database_url
    app = create_app("testing", config_overrides=config)
    with app.app_context():
        db.create_all()
    return app


def _session(
    *,
    session_id: int = 1,
    dataflow_id: str = "df-rec",
    status: SessionStatus = SessionStatus.STARTING,
) -> Session:
    session = Session(
        id=session_id,
        name=f"session-{session_id}",
        status=status,
        policy="recommend",
        device_flows=[
            {
                "device_id": "dev-a",
                "name": "device-a",
                "nickname": None,
                "hardware_id": "hw-a",
                "port": "usb-a",
                "parameters": {},
                "sink_type": "csv",
                "sink_location": "/data/dev-a.csv",
            }
        ],
        command_in_flight=True,
        dataflow_id=dataflow_id,
        watchdog_id="watchdog-rec",
    )
    db.session.add(session)
    db.session.commit()
    return session


def _operation(command: str, *, request_key: str = "req-rec", **kwargs) -> Operation:
    operation = create_operation(
        session_id=kwargs.pop("session_id", 1),
        dataflow_id=kwargs.pop("dataflow_id", "df-rec"),
        command=command,
        request_key=request_key,
        **kwargs,
    )
    return operation


def _dispatch(operation: Operation) -> Operation:
    transition_operation(operation.operation_id, OperationState.CLAIMED)
    return transition_operation(operation.operation_id, OperationState.DISPATCHED)


def test_queued_or_claimed_operations_fail_before_dispatch():
    app = _app()
    with app.app_context():
        session = _session()
        operation = _operation("start", manifest_hash="hash-a")
        transition_operation(operation.operation_id, OperationState.CLAIMED)

        result = reconcile_startup(status_probe=lambda port: {})

        db.session.refresh(operation)
        db.session.refresh(session)
        assert result.failed_operations == 1
        assert operation.state is OperationState.FAILED
        assert operation.error_code == "interrupted_before_dispatch"
        assert operation.finished_at is not None
        assert session.command_in_flight is False


def test_dispatched_start_succeeds_when_matching_runtime_is_running():
    app = _app()
    with app.app_context():
        session = _session()
        operation = _dispatch(_operation("start", manifest_hash="hash-a"))
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id="rt-a",
            session_id=session.id,
            dataflow_id="df-rec",
            manifest_hash="hash-a",
            token="token-a",
        )
        ownerships.mark_running("rt-a", pid=1234, port=8206)

        result = reconcile_startup(
            status_probe=lambda port: {
                "runtime_id": "rt-a",
                "pid": 1234,
                "phase": "running",
                "dataflow_id": "df-rec",
                "manifest_hash": "hash-a",
                "reports": [],
            }
        )

        db.session.refresh(operation)
        db.session.refresh(session)
        ownership = db.session.scalar(
            db.select(RuntimeOwnership).where(RuntimeOwnership.runtime_id == "rt-a")
        )
        assert result.succeeded_operations == 1
        assert operation.state is OperationState.SUCCEEDED
        assert operation.finished_at is not None
        assert session.status is SessionStatus.ACTIVE
        assert session.command_in_flight is False
        assert ownership.state is RuntimeOwnershipState.ADOPTED
        assert ownership.adopted_at is not None


def test_dispatched_start_becomes_uncertain_on_runtime_identity_mismatch():
    app = _app()
    with app.app_context():
        _session()
        operation = _dispatch(_operation("start", manifest_hash="hash-a"))
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id="rt-a",
            session_id=1,
            dataflow_id="df-rec",
            manifest_hash="hash-a",
            token="token-a",
        )
        ownerships.mark_running("rt-a", pid=1234, port=8206)

        result = reconcile_startup(
            status_probe=lambda port: {
                "runtime_id": "rt-other",
                "pid": 1234,
                "phase": "running",
                "dataflow_id": "df-rec",
                "manifest_hash": "hash-a",
                "reports": [],
            }
        )

        db.session.refresh(operation)
        ownership = db.session.scalar(
            db.select(RuntimeOwnership).where(RuntimeOwnership.runtime_id == "rt-a")
        )
        assert result.uncertain_operations == 1
        assert operation.state is OperationState.UNCERTAIN
        assert operation.error_code == "runtime_identity_mismatch"
        assert ownership.state is RuntimeOwnershipState.UNCERTAIN

        with pytest.raises(OperationConflict, match="unresolved uncertain dataflow"):
            create_operation(
                session_id=1,
                dataflow_id="df-rec",
                command="restart-all-streams",
                request_key="blocked-by-uncertain",
            )


def test_unreachable_runtime_with_watchdog_hints_is_deferred_for_host_supervisor():
    """Leave adoption-eligible ownership visible to HostSupervisor.reconcile."""
    app = _app()
    with app.app_context():
        _session(status=SessionStatus.ACTIVE)
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id="rt-orphan",
            session_id=1,
            dataflow_id="df-rec",
            manifest_hash="hash-a",
            token="token-a",
        )
        ownerships.mark_running("rt-orphan", pid=1234, port=8206)
        ownerships.set_watchdog("rt-orphan", watchdog_id="wd-orphan", pid=5678)
        ownerships.update_watchdog_seen(
            "rt-orphan",
            watchdog_id="wd-orphan",
            pid=5678,
            state=WatchdogProcessState.RUNNING,
        )

        result = reconcile_startup(
            status_probe=lambda port: (_ for _ in ()).throw(ConnectionError())
        )

        db.session.expire_all()
        ownership = ownerships.get("rt-orphan")
        assert result.deferred_runtimes == 1
        assert ownership is not None
        assert ownership.state is RuntimeOwnershipState.RUNNING
        assert ownership.watchdog_state is WatchdogProcessState.RUNNING


def test_dispatched_stop_succeeds_when_stopping_runtime_is_absent():
    app = _app()
    with app.app_context():
        session = _session(status=SessionStatus.ENDING)
        operation = _dispatch(_operation("stop", manifest_hash="hash-a"))
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id="rt-stop",
            session_id=session.id,
            dataflow_id="df-rec",
            manifest_hash="hash-a",
            token="token-a",
        )
        ownerships.mark_running("rt-stop", pid=1234, port=8206)
        ownerships.mark_stopping("rt-stop")

        result = reconcile_startup(
            status_probe=lambda port: (_ for _ in ()).throw(ConnectionError("gone"))
        )

        db.session.refresh(operation)
        db.session.refresh(session)
        ownership = db.session.scalar(
            db.select(RuntimeOwnership).where(RuntimeOwnership.runtime_id == "rt-stop")
        )
        assert result.succeeded_operations == 1
        assert operation.state is OperationState.SUCCEEDED
        assert session.status is SessionStatus.STOPPED
        assert session.command_in_flight is False
        assert ownership.state is RuntimeOwnershipState.STOPPED
        assert ownership.stopped_at is not None


def test_recovery_succeeds_when_matching_recovery_reports_target_healthy():
    app = _app()
    with app.app_context():
        _session(status=SessionStatus.ACTIVE)
        operation = _dispatch(
            _operation(
                "reconnect",
                request_key="req-recovery",
                target_device_id="dev-a",
                recovery_id="rec-a",
                manifest_hash="hash-a",
            )
        )
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id="rt-a",
            session_id=1,
            dataflow_id="df-rec",
            manifest_hash="hash-a",
            token="token-a",
        )
        ownerships.mark_running("rt-a", pid=1234, port=8206)

        result = reconcile_startup(
            status_probe=lambda port: {
                "runtime_id": "rt-a",
                "pid": 1234,
                "phase": "running",
                "dataflow_id": "df-rec",
                "manifest_hash": "hash-a",
                "reports": [
                    {
                        "dataflow_id": "df-rec",
                        "phase": "running",
                        "comms": "current",
                        "sequence": 7,
                        "recovery_id": "rec-a",
                        "devices": [
                            {"device_id": "dev-a", "stream_status": "healthy"}
                        ],
                    }
                ],
            }
        )

        db.session.refresh(operation)
        assert result.succeeded_operations == 1
        assert operation.state is OperationState.SUCCEEDED


def test_app_startup_runs_reconciliation_when_enabled(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'startup.sqlite3'}"
    seed_app = _app(database_url)
    with seed_app.app_context():
        _session()
        _operation("start", manifest_hash="hash-a")

    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "STARTUP_RECONCILIATION_ENABLED": True,
            "STARTUP_RECONCILIATION_STATUS_PROBE": lambda port: {},
        },
    )

    with app.app_context():
        operation = db.session.scalar(db.select(Operation))
        assert operation.state is OperationState.FAILED
        assert operation.error_code == "interrupted_before_dispatch"


def test_app_startup_reconciles_host_supervisor_dataflows(tmp_path):
    """DB-only reconciliation must not be the only thing that runs at boot.

    HostSupervisor._children is a separate, in-process registry that
    reconcile_startup() never touches. Without this wiring, a daemon restart
    while a session is running leaves stop()/dispatch() broken forever for
    that dataflow (see RuntimeNotTracked).
    """
    database_url = f"sqlite:///{tmp_path / 'startup-supervisor.sqlite3'}"
    seed_app = _app(database_url)
    with seed_app.app_context():
        session = _session(dataflow_id="df-wire-1", status=SessionStatus.ACTIVE)
        session.runtime_port = 8206
        session.runtime_token = "token-wire"
        db.session.commit()

    calls = []

    class StubSupervisor:
        def reconcile(self, sessions):
            calls.append([s.dataflow_id for s in sessions])

    create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "STARTUP_RECONCILIATION_ENABLED": True,
            "STARTUP_RECONCILIATION_STATUS_PROBE": lambda port: {},
            "HOST_SUPERVISOR": StubSupervisor(),
        },
    )

    assert calls == [["df-wire-1"]]


def test_restart_startup_uses_adopt_only_supervisor_reconciliation(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'restart-adopt-only.sqlite3'}"
    seed_app = _app(database_url)
    with seed_app.app_context():
        session = _session(dataflow_id="df-restart-1", status=SessionStatus.ACTIVE)
        session.runtime_port = 8206
        session.runtime_token = "token-wire"
        db.session.commit()

    calls = []

    class StubSupervisor:
        def reconcile(self, sessions, *, adopt_only=False):
            calls.append(([s.dataflow_id for s in sessions], adopt_only))
            return {"adopted": ["df-restart-1"], "uncertain": []}

    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "STARTUP_RECONCILIATION_ENABLED": True,
            "STARTUP_RECONCILIATION_ADOPT_ONLY": True,
            "HOST_SUPERVISOR": StubSupervisor(),
        },
    )

    assert calls == [(["df-restart-1"], True)]
    assert app.extensions["restart_reconciliation_report"] == {
        "adopted": ["df-restart-1"],
        "uncertain": [],
    }


def test_app_startup_skips_host_supervisor_reconcile_when_tables_missing(tmp_path):
    """Guard: don't query the sessions table before migrations have run."""
    database_url = f"sqlite:///{tmp_path / 'startup-no-tables.sqlite3'}"

    calls = []

    class StubSupervisor:
        def reconcile(self, sessions):
            calls.append(sessions)

    create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "STARTUP_RECONCILIATION_ENABLED": True,
            "STARTUP_RECONCILIATION_STATUS_PROBE": lambda port: {},
            "HOST_SUPERVISOR": StubSupervisor(),
        },
    )

    assert calls == []


def _claimed_config_session(*, status: SessionStatus, runtime_port: int | None):
    """An ACTIVE/ENDING session that has claimed a real device config."""
    from app.domain.enums import DeviceType
    from app.services import device_configs
    from app.services.device_configs import create as create_device_config

    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id="RC001",
        port="COM3",
        parameters={"preamp_gain": 10},
    )
    session = Session(
        id=1,
        name="orphan",
        status=status,
        policy="recommend",
        device_flows=[
            {
                "device_config_id": config.id,
                "sink_type": "csv",
                "sink_location": "/data/rc.csv",
            }
        ],
        command_in_flight=False,
        dataflow_id="df-orphan",
        watchdog_id="wd-orphan",
        runtime_port=runtime_port,
        runtime_token="tok" if runtime_port is not None else None,
    )
    db.session.add(session)
    db.session.commit()
    device_configs.claim(config.id, session.id)
    return session, config.id


def test_orphan_active_session_without_runtime_port_is_completed_and_released():
    """A session left ACTIVE with no runtime host gets closed and its device freed.

    Reproduces the daemon-shutdown zombie: status stays ACTIVE with the device
    still CLAIMED, so the next session that needs it fails DeviceConfigNotFree.
    """
    from app.domain.enums import DeviceClaimState
    from app.models.device_config import DeviceConfig

    app = _app()
    with app.app_context():
        session, config_id = _claimed_config_session(
            status=SessionStatus.ACTIVE, runtime_port=None
        )
        assert db.session.get(DeviceConfig, config_id).claim_state is DeviceClaimState.CLAIMED

        result = reconcile_startup(status_probe=lambda port: {})

        db.session.refresh(session)
        assert result.released_orphan_sessions == 1
        assert session.status is SessionStatus.STOPPED
        config = db.session.get(DeviceConfig, config_id)
        assert config.claim_state is DeviceClaimState.FREE
        assert config.claimed_session_id is None


def test_active_session_with_runtime_port_is_left_for_host_supervisor():
    """A session that still carries a port is HostSupervisor.reconcile's job.

    reconcile_startup must NOT release its device — the host may be live (adopt)
    or dead-but-respawnable, and either way the claim must survive.
    """
    from app.domain.enums import DeviceClaimState
    from app.models.device_config import DeviceConfig

    app = _app()
    with app.app_context():
        session, config_id = _claimed_config_session(
            status=SessionStatus.ACTIVE, runtime_port=51000
        )

        result = reconcile_startup(status_probe=lambda port: {})

        db.session.refresh(session)
        assert result.released_orphan_sessions == 0
        assert session.status is SessionStatus.ACTIVE
        assert db.session.get(DeviceConfig, config_id).claim_state is DeviceClaimState.CLAIMED
