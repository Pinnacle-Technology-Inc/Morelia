from structlog.contextvars import bind_contextvars

import app.services.sessions as session_service
from app import create_app
from app.database import db
from app.domain.enums import (
    DeviceClaimState,
    DeviceType,
    OperationScope,
    OperationState,
    SessionStatus,
    SinkType,
)
from app.domain.errors import CommandInFlight, InvalidTransition, StopProofMissing
from app.models.device_config import DeviceConfig
from app.models.operation import Operation
from app.models.runtime_manifest import RuntimeManifest
from app.output.managed_file import allocate_continuation, create as create_output_file
from app.repositories.output_files import (
    ACQUISITION_COMPLETE,
    ACQUISITION_INTERRUPTED,
    ARTIFACT_MERGE_PENDING,
    ARTIFACT_NOT_REQUIRED,
    OutputFilesRepository,
)
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.services.device_configs import create as create_device_config
from app.watchdog.adapters import FakeWatchdogAdapter, WatchdogUnavailableError


def _valid_flow():
    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id="OP001",
        port="COM3",
        parameters={"preamp_gain": 10},
    )
    return {
        "device_config_id": config.id,
        "sink_type": "csv",
        "sink_location": "C:/data/op.csv",
    }


class FakeSupervisor:
    def __init__(self, *, fail_dispatch: Exception | None = None) -> None:
        self.fail_dispatch = fail_dispatch
        self.spawned: list[tuple[int, str]] = []
        self.dispatched = []
        self.stopped = []

    def spawn(self, session, *, manifest=None):
        self.spawned.append((session.id, manifest.hash))
        session.runtime_port = 43210
        session.runtime_token = "fake-runtime-token"
        return session.runtime_port

    def dispatch(self, session, envelope):
        self.dispatched.append(envelope)
        if self.fail_dispatch is not None:
            raise self.fail_dispatch

    def stop(self, session, *, envelope=None):
        self.stopped.append(envelope)
        session.runtime_port = None
        session.runtime_token = None


class PreflightedIdentitySupervisor(FakeSupervisor):
    """Fake host that exposes the child watchdog identity before dispatch."""

    def spawn(self, session, *, manifest=None):
        port = super().spawn(session, manifest=manifest)
        runtime_id = "runtime-preflighted"
        watchdog_id = "watchdog-preflighted"
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id=runtime_id,
            session_id=session.id,
            dataflow_id=session.dataflow_id,
            manifest_hash=manifest.hash,
            token="fake-runtime-token",
        )
        ownerships.set_watchdog(runtime_id, watchdog_id=watchdog_id, pid=1234)
        ownerships.mark_running(runtime_id, pid=1234, port=port)
        ownerships.update_watchdog_seen(
            runtime_id,
            watchdog_id=watchdog_id,
            pid=1234,
        )
        return port


class FailingStopSupervisor(FakeSupervisor):
    def stop(self, session, *, envelope=None):
        self.stopped.append(envelope)
        raise WatchdogUnavailableError("Runtime host is unavailable.")


class StopProofMissingSupervisor(FakeSupervisor):
    """Simulates HostSupervisor.stop() tearing the process down but finding no
    durable proof of a clean stop — runtime identity/claims are left exactly
    as they were (the real stop() only clears them on the stop_proven path,
    which this raise short-circuits before reaching)."""

    def stop(self, session, *, envelope=None):
        self.stopped.append(envelope)
        raise StopProofMissing(session.dataflow_id, runtime_id="rt-proof-missing")


def test_start_creates_operation_and_dispatches_its_command_id():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "operation-backed-start",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-start-op")
        started = session_service.start(session.id, app.extensions["watchdog_adapter"])

        operation = db.session.scalars(db.select(Operation)).one()
        dispatched = app.extensions["watchdog_adapter"].messages[0]

        assert operation.command == "start"
        assert operation.request_id == "req-start-op"
        assert operation.command_id == operation.operation_id
        assert operation.state.value == "dispatched"
        assert operation.dispatched_at is not None
        assert dispatched.correlation.command_id == operation.command_id
        assert started.command_id == operation.command_id
        # Unmanaged path: no RuntimeOwnership row exists to attribute a
        # runtime_id to (packet 07 — the field is best-effort, not required).
        assert dispatched.correlation.runtime_id is None


def test_start_marks_operation_failed_when_dispatch_fails():
    fake = FakeWatchdogAdapter()
    fake.queue_error(WatchdogUnavailableError("Watchdog is unavailable."))
    app = create_app("testing", config_overrides={"WATCHDOG_ADAPTER": fake})
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "operation-backed-start",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-start-fail")
        try:
            session_service.start(session.id, app.extensions["watchdog_adapter"])
            raise AssertionError("expected watchdog dispatch failure")
        except WatchdogUnavailableError:
            pass

        operation = db.session.scalars(db.select(Operation)).one()
        db.session.refresh(session)

        assert operation.state.value == "failed"
        assert operation.finished_at is not None
        assert operation.error_code == "WatchdogUnavailableError"
        assert session.command_in_flight is False


def test_managed_start_spawns_runtime_persists_manifest_claims_config_and_completes():
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-start",
                "device_flows": [_valid_flow()],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]

        bind_contextvars(request_id="req-managed-start")
        started = session_service.start_managed(session.id, supervisor)

        operation = db.session.scalars(db.select(Operation)).one()
        manifest = db.session.scalars(db.select(RuntimeManifest)).one()
        config = db.session.get(DeviceConfig, config_id)

        assert started.status == SessionStatus.ACTIVE
        assert started.command_in_flight is False
        assert started.runtime_port == 43210
        assert operation.command == "start"
        assert operation.state is OperationState.SUCCEEDED
        assert operation.manifest_hash == manifest.hash
        # FakeSupervisor doesn't create a RuntimeOwnership row (unlike the real
        # HostSupervisor.spawn()) — stamping degrades to None rather than failing.
        assert operation.runtime_id is None
        assert supervisor.spawned == [(session.id, manifest.hash)]
        assert supervisor.dispatched[0].command == "start"
        assert config.claim_state is DeviceClaimState.CLAIMED
        assert config.claimed_session_id == session.id


def test_managed_start_targets_watchdog_identity_discovered_during_preflight():
    app = create_app("testing")
    supervisor = PreflightedIdentitySupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {"name": "preflighted-start", "device_flows": [_valid_flow()]}
        )

        bind_contextvars(request_id="req-preflighted-start")
        session_service.start_managed(session.id, supervisor)

        dispatched = supervisor.dispatched[0]
        assert dispatched.correlation.watchdog_id == "watchdog-preflighted"
        assert dispatched.correlation.watchdog_id != session.watchdog_id


def test_managed_start_failure_releases_claim_and_restores_session_state():
    app = create_app("testing")
    supervisor = FakeSupervisor(
        fail_dispatch=WatchdogUnavailableError("Runtime host is unavailable.")
    )
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-start-fails",
                "device_flows": [_valid_flow()],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]

        bind_contextvars(request_id="req-managed-start-fail")
        try:
            session_service.start_managed(session.id, supervisor)
            raise AssertionError("expected runtime dispatch failure")
        except WatchdogUnavailableError:
            pass

        operation = db.session.scalars(db.select(Operation)).one()
        config = db.session.get(DeviceConfig, config_id)
        db.session.refresh(session)

        assert operation.state is OperationState.FAILED
        assert operation.error_code == "WatchdogUnavailableError"
        assert session.status == SessionStatus.DRAFT
        assert session.command_in_flight is False
        assert session.runtime_port is None
        assert config.claim_state is DeviceClaimState.FREE
        assert config.claimed_session_id is None


def test_stop_creates_operation_and_dispatches_its_command_id():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "operation-backed-stop",
                "device_flows": [_valid_flow()],
            }
        )
        session.status = SessionStatus.ACTIVE
        session.dataflow_id = "dataflow-stop"
        session.watchdog_id = "watchdog-stop"
        db.session.commit()

        bind_contextvars(request_id="req-stop-op")
        stopped = session_service.stop(session.id, app.extensions["watchdog_adapter"])

        operation = db.session.scalars(db.select(Operation)).one()
        dispatched = app.extensions["watchdog_adapter"].messages[0]

        assert operation.command == "stop"
        assert operation.request_id == "req-stop-op"
        assert operation.command_id == operation.operation_id
        assert operation.state.value == "dispatched"
        assert operation.dispatched_at is not None
        assert dispatched.command == "stop"
        assert dispatched.correlation.command_id == operation.command_id
        assert stopped.command_id == operation.command_id
        assert stopped.status == SessionStatus.ENDING
        assert stopped.command_in_flight is True


def test_managed_stop_stops_runtime_releases_config_and_completes_session():
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-stop",
                "device_flows": [_valid_flow()],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]

        bind_contextvars(request_id="req-managed-start-before-stop")
        session_service.start_managed(session.id, supervisor)

        bind_contextvars(request_id="req-managed-stop")
        stopped = session_service.stop_managed(session.id, supervisor)

        operations = db.session.scalars(
            db.select(Operation).order_by(Operation.created_at, Operation.id)
        ).all()
        config = db.session.get(DeviceConfig, config_id)

        assert stopped.status == SessionStatus.COMPLETED
        assert stopped.command_in_flight is False
        assert stopped.runtime_port is None
        assert operations[-1].command == "stop"
        assert operations[-1].state is OperationState.SUCCEEDED
        assert supervisor.stopped[-1].command == "stop"
        assert config.claim_state is DeviceClaimState.FREE
        assert config.claimed_session_id is None


def test_managed_stop_force_releases_device_and_records_unclean_stop():
    """A forced stop terminalizes the session and frees its device, while the
    operation stays UNCERTAIN to record that teardown could not be verified.

    Regression: --force previously left the session ENDING with its device
    still CLAIMED, trapping the hardware with no recovery route but DB surgery.
    """
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-stop-force",
                "device_flows": [_valid_flow()],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]

        bind_contextvars(request_id="req-managed-start-before-force-stop")
        session_service.start_managed(session.id, FakeSupervisor())
        session.runtime_port = 43210
        session.runtime_token = "fake-runtime-token"
        db.session.commit()

        bind_contextvars(request_id="req-managed-stop-force")
        stopped = session_service.stop_managed(
            session.id,
            FailingStopSupervisor(),
            force=True,
        )

        operations = db.session.scalars(
            db.select(Operation).order_by(Operation.created_at, Operation.id)
        ).all()
        config = db.session.get(DeviceConfig, config_id)

        assert stopped.status == SessionStatus.COMPLETED
        assert stopped.command_in_flight is False
        assert stopped.runtime_port is None
        assert stopped.runtime_token is None
        # Operation records the unclean teardown even though the device is freed.
        assert operations[-1].command == "stop"
        assert operations[-1].state is OperationState.UNCERTAIN
        assert operations[-1].details == {"forced": True}
        assert operations[-1].error_code == "forced_stop"
        assert config.claim_state is DeviceClaimState.FREE
        assert config.claimed_session_id is None


def test_managed_stop_proof_missing_leaves_session_active_and_retryable():
    """Non-force stop_managed: when the supervisor cannot prove a clean stop,
    the session stays ACTIVE (not COMPLETED) with its runtime identity and
    device claim untouched, and the operation is FAILED rather than
    SUCCEEDED — so the operator can retry, and --force stays the explicit way
    to resolve it (see StopProofMissing)."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-stop-proof-missing",
                "device_flows": [_valid_flow()],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]

        bind_contextvars(request_id="req-managed-start-before-proof-missing")
        session_service.start_managed(session.id, FakeSupervisor())

        bind_contextvars(request_id="req-managed-stop-proof-missing")
        try:
            session_service.stop_managed(session.id, StopProofMissingSupervisor())
            raise AssertionError("expected StopProofMissing")
        except StopProofMissing:
            pass

        operations = db.session.scalars(
            db.select(Operation).order_by(Operation.created_at, Operation.id)
        ).all()
        config = db.session.get(DeviceConfig, config_id)
        db.session.refresh(session)

        assert session.status == SessionStatus.ACTIVE
        assert session.command_in_flight is False
        # Runtime identity is NOT cleared — no proof this stop was clean.
        assert session.runtime_port == 43210
        assert session.runtime_token == "fake-runtime-token"
        assert operations[-1].command == "stop"
        assert operations[-1].state is OperationState.FAILED
        assert operations[-1].error_code == "StopProofMissing"
        # Claim is NOT released — only --force releases an unproven stop's claim.
        assert config.claim_state is DeviceClaimState.CLAIMED
        assert config.claimed_session_id == session.id


def test_managed_stop_force_after_proof_missing_retry_completes_the_session():
    """End-to-end 'guide to force' flow: a non-force stop fails proof and
    leaves the session ACTIVE/retryable; the operator's follow-up --force
    retry then completes it (COMPLETED, device released, operation UNCERTAIN)
    even though the host is, by then, already torn down."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-stop-proof-missing-then-force",
                "device_flows": [_valid_flow()],
            }
        )
        config_id = session.device_flows[0]["device_config_id"]

        bind_contextvars(request_id="req-managed-start-before-proof-missing-2")
        session_service.start_managed(session.id, FakeSupervisor())

        bind_contextvars(request_id="req-managed-stop-proof-missing-2")
        try:
            session_service.stop_managed(session.id, StopProofMissingSupervisor())
            raise AssertionError("expected StopProofMissing")
        except StopProofMissing:
            pass

        db.session.refresh(session)
        assert session.status == SessionStatus.ACTIVE  # retryable

        bind_contextvars(request_id="req-managed-stop-force-after-proof-missing")
        stopped = session_service.stop_managed(
            session.id, StopProofMissingSupervisor(), force=True
        )

        operations = db.session.scalars(
            db.select(Operation).order_by(Operation.created_at, Operation.id)
        ).all()
        config = db.session.get(DeviceConfig, config_id)

        assert stopped.status == SessionStatus.COMPLETED
        assert stopped.command_in_flight is False
        assert operations[-1].command == "stop"
        assert operations[-1].state is OperationState.UNCERTAIN
        assert operations[-1].error_code == "forced_stop"
        assert operations[-1].details == {"forced": True}
        assert config.claim_state is DeviceClaimState.FREE
        assert config.claimed_session_id is None


def test_managed_stop_stamps_operation_with_active_runtime_id():
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-stop-runtime-id",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-managed-stop-runtime-id-start")
        started = session_service.start_managed(session.id, supervisor)

        # The real HostSupervisor.spawn() would have created this row itself;
        # FakeSupervisor doesn't, so create it directly to simulate a live host.
        RuntimeOwnershipRepository().create_starting(
            runtime_id="host-abc123",
            session_id=started.id,
            dataflow_id=started.dataflow_id,
            manifest_hash="irrelevant-for-this-test",
            token="fake-token",
        )

        bind_contextvars(request_id="req-managed-stop-runtime-id-stop")
        session_service.stop_managed(started.id, supervisor)

        stop_op = db.session.scalars(
            db.select(Operation).where(Operation.command == "stop")
        ).one()
        assert stop_op.runtime_id == "host-abc123"
        # Packet 07: the dispatched command envelope carries the same active
        # runtime_id the operation was stamped with — not just the operation row.
        assert supervisor.stopped[-1].correlation.runtime_id == "host-abc123"


def test_stop_marks_operation_failed_when_dispatch_fails():
    fake = FakeWatchdogAdapter()
    fake.queue_error(WatchdogUnavailableError("Watchdog is unavailable."))
    app = create_app("testing", config_overrides={"WATCHDOG_ADAPTER": fake})
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "operation-backed-stop",
                "device_flows": [_valid_flow()],
            }
        )
        session.status = SessionStatus.ACTIVE
        session.dataflow_id = "dataflow-stop-fail"
        session.watchdog_id = "watchdog-stop-fail"
        db.session.commit()

        bind_contextvars(request_id="req-stop-fail")
        try:
            session_service.stop(session.id, app.extensions["watchdog_adapter"])
            raise AssertionError("expected watchdog dispatch failure")
        except WatchdogUnavailableError:
            pass

        operation = db.session.scalars(db.select(Operation)).one()
        db.session.refresh(session)

        assert operation.command == "stop"
        assert operation.state.value == "failed"
        assert operation.finished_at is not None
        assert operation.error_code == "WatchdogUnavailableError"
        assert session.command_in_flight is False
        assert session.status == SessionStatus.ACTIVE


def test_stop_draft_session_raises_invalid_transition():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "draft-stop",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-stop-draft")
        try:
            session_service.stop(session.id, app.extensions["watchdog_adapter"])
            raise AssertionError("expected InvalidTransition on a draft session")
        except InvalidTransition as exc:
            assert exc.current == SessionStatus.DRAFT


def test_stop_locked_session_raises_command_in_flight_before_state_check():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "locked-draft-stop",
                "device_flows": [_valid_flow()],
            }
        )
        session.command_in_flight = True
        db.session.commit()

        bind_contextvars(request_id="req-stop-locked")
        try:
            session_service.stop(session.id, app.extensions["watchdog_adapter"])
            raise AssertionError("expected CommandInFlight on a locked session")
        except CommandInFlight:
            pass


def test_managed_recover_dispatches_stream_scoped_operation_without_locking():
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-recover",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-managed-recover-start")
        session_service.start_managed(session.id, supervisor)

        bind_contextvars(request_id="req-managed-recover")
        recovered = session_service.recover_managed(
            session.id, "dev-op001", "reconnect", supervisor
        )

        recover_op = db.session.scalars(
            db.select(Operation).where(Operation.command == "reconnect")
        ).one()

        assert recover_op.scope is OperationScope.STREAM
        assert recover_op.target_device_id == "dev-op001"
        assert recover_op.recovery_id is not None
        assert recover_op.state is OperationState.SUCCEEDED
        # stream-scoped: the session is untouched — still ACTIVE, never locked.
        assert recovered.status is SessionStatus.ACTIVE
        assert recovered.command_in_flight is False

        envelope = supervisor.dispatched[-1]
        assert envelope.command == "reconnect"
        assert envelope.target_device_id == "dev-op001"
        assert envelope.correlation.recovery_id == recover_op.recovery_id


def test_managed_recover_stamps_operation_with_active_runtime_id():
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "managed-recover-runtime-id",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-managed-recover-runtime-id-start")
        started = session_service.start_managed(session.id, supervisor)

        RuntimeOwnershipRepository().create_starting(
            runtime_id="host-def456",
            session_id=started.id,
            dataflow_id=started.dataflow_id,
            manifest_hash="irrelevant-for-this-test",
            token="fake-token",
        )

        bind_contextvars(request_id="req-managed-recover-runtime-id")
        session_service.recover_managed(started.id, "dev-op001", "reconnect", supervisor)

        recover_op = db.session.scalars(
            db.select(Operation).where(Operation.command == "reconnect")
        ).one()
        assert recover_op.runtime_id == "host-def456"
        # Packet 07: the dispatched command envelope carries the same active
        # runtime_id the operation was stamped with — not just the operation row.
        assert supervisor.dispatched[-1].correlation.runtime_id == "host-def456"


def test_recover_draft_session_raises_invalid_transition():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {
                "name": "recover-draft",
                "device_flows": [_valid_flow()],
            }
        )

        bind_contextvars(request_id="req-recover-draft")
        try:
            session_service.recover(
                session.id, "dev-op001", "reconnect", app.extensions["watchdog_adapter"]
            )
            raise AssertionError("expected InvalidTransition on a non-active session")
        except InvalidTransition:
            pass


def test_recover_route_returns_202_and_dispatches_recovery(app):
    with app.app_context():
        session = session_service.create(
            {
                "name": "route-backed-recover",
                "device_flows": [_valid_flow()],
            }
        )
        session.status = SessionStatus.ACTIVE
        session.dataflow_id = "route-dataflow-recover"
        session.watchdog_id = "route-watchdog-recover"
        db.session.commit()
        session_id = session.id

    response = app.test_client().post(
        f"/api/v1/sessions/{session_id}/commands/recover",
        json={"device_id": "dev-1", "action": "restart"},
        headers={"X-Request-ID": "route-recover"},
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["id"] == str(session_id)
    # stream-scoped recovery leaves the session ACTIVE.
    assert body["status"] == "active"

    envelope = app.extensions["watchdog_adapter"].messages[-1]
    assert envelope.command == "restart"
    assert envelope.target_device_id == "dev-1"
    assert envelope.correlation.recovery_id is not None


def test_stop_route_returns_409_stop_proof_missing_when_proof_is_absent(app):
    """The managed stop route maps StopProofMissing to a distinct 409 — never
    a generic 500 — carrying dataflow_id/runtime_id and a "retry with force"
    remedy in its detail, and the session stays ACTIVE (retryable)."""
    app.config["SESSION_RUNTIME_HOST_ENABLED"] = True
    app.extensions["host_supervisor"] = StopProofMissingSupervisor()

    with app.app_context():
        session = session_service.create(
            {
                "name": "route-backed-stop-proof-missing",
                "device_flows": [_valid_flow()],
            }
        )
        session_id = session.id

    client = app.test_client()
    started = client.post(
        f"/api/v1/sessions/{session_id}/commands/start",
        headers={"X-Request-ID": "route-start-before-proof-missing"},
    )
    assert started.status_code == 202

    response = client.post(
        f"/api/v1/sessions/{session_id}/commands/stop",
        headers={"X-Request-ID": "route-stop-proof-missing"},
    )

    assert response.status_code == 409
    body = response.get_json(force=True)
    assert body["code"] == "stop_proof_missing"
    assert "force" in body["detail"].lower()
    assert body["dataflow_id"]
    assert body["runtime_id"] == "rt-proof-missing"

    with app.app_context():
        refreshed = session_service.get(session_id)
        assert refreshed.status == SessionStatus.ACTIVE
        assert refreshed.command_in_flight is False


# ---------------------------------------------------------------------------
# Packet 29 — clean stop is a completion boundary; a later start is a new
# acquisition that never resumes the prior (completed) output.
# ---------------------------------------------------------------------------


def _seed_logical_output(session, tmp_path, *, name, components):
    """Simulate the running child's sink writing a logical output for a session.

    ``components`` linked segments on disk (segment 0 + recovery continuations),
    with all writers closed but acquisition NOT yet marked complete — exactly
    what the control plane finds when it processes a clean stop. Returns the
    ``logical_sink_id``.
    """
    head = create_output_file(
        tmp_path / f"{name}.bin",
        dataflow_id=session.dataflow_id,
        sink_type=SinkType.CSV,
        session_id=session.id,
    )
    head.write(b"seg0")
    logical = head.record.logical_sink_id

    last = head
    for _ in range(1, components):
        last.close()
        last = allocate_continuation(last.record)
        last.write(b"segN")
    last.close()
    return logical


def test_managed_stop_completes_acquisition_and_schedules_finalization(tmp_path):
    """A clean user stop marks the acquisition complete, records termination
    'clean', and enqueues the EDF/PVFS merge — WITHOUT waiting for it."""
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {"name": "stop-finalize", "device_flows": [_valid_flow()]}
        )

        bind_contextvars(request_id="req-stop-finalize-start")
        started = session_service.start_managed(session.id, supervisor)

        logical = _seed_logical_output(started, tmp_path, name="rec", components=2)

        bind_contextvars(request_id="req-stop-finalize-stop")
        stopped = session_service.stop_managed(started.id, supervisor)

        repo = OutputFilesRepository()
        components = repo.list_components(logical)
        head, terminal = components[0], components[-1]

        assert stopped.status == SessionStatus.COMPLETED
        # Durable completion boundary: terminal component complete + clean.
        assert terminal.acquisition_state == ACQUISITION_COMPLETE
        assert terminal.termination_reason == "clean"
        # The earlier (recovery-split) segment stays distinctly 'interrupted'.
        assert head.acquisition_state == ACQUISITION_INTERRUPTED
        assert head.termination_reason == "recovery"
        # Multi-component merge is ENQUEUED, not performed (stop did not wait).
        assert head.artifact_state == ARTIFACT_MERGE_PENDING
        assert head.final_output_id is None


def test_managed_stop_single_component_output_needs_no_merge(tmp_path):
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {"name": "stop-solo", "device_flows": [_valid_flow()]}
        )

        bind_contextvars(request_id="req-stop-solo-start")
        started = session_service.start_managed(session.id, supervisor)

        logical = _seed_logical_output(started, tmp_path, name="solo", components=1)

        bind_contextvars(request_id="req-stop-solo-stop")
        session_service.stop_managed(started.id, supervisor)

        repo = OutputFilesRepository()
        head = repo.get_head(logical)
        assert head.acquisition_state == ACQUISITION_COMPLETE
        assert head.termination_reason == "clean"
        # One component: nothing to merge.
        assert head.artifact_state == ARTIFACT_NOT_REQUIRED


def test_later_start_allocates_new_output_identity_not_a_resume(tmp_path):
    """After a clean stop schedules the prior output, a later run on the same
    session/hardware gets a wholly new logical/physical identity and never
    resumes or waits on the completed output."""
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {"name": "new-acq", "device_flows": [_valid_flow()]}
        )

        bind_contextvars(request_id="req-new-acq-start")
        started = session_service.start_managed(session.id, supervisor)
        logical_a = _seed_logical_output(started, tmp_path, name="run-a", components=2)

        bind_contextvars(request_id="req-new-acq-stop")
        session_service.stop_managed(started.id, supervisor)

        repo = OutputFilesRepository()
        assert repo.get_head(logical_a).artifact_state == ARTIFACT_MERGE_PENDING

        # A later run allocates a brand-new output (child would do this on the
        # next start) — new logical id, new path, no back-link to A.
        new_run = create_output_file(
            tmp_path / "run-b.bin",
            dataflow_id=started.dataflow_id,
            sink_type=SinkType.CSV,
            session_id=started.id,
        )
        new_run.write(b"fresh")
        logical_b = new_run.record.logical_sink_id

        assert logical_b != logical_a
        assert new_run.record.path != repo.get_head(logical_a).path
        assert new_run.record.previous_output_id is None  # not a continuation
        assert new_run.record.acquisition_state == "open"  # a fresh acquisition
        # Prior acquisition is untouched by the new run — no resume, no wait.
        assert repo.get_head(logical_a).artifact_state == ARTIFACT_MERGE_PENDING


def test_stale_finalizer_claim_cannot_touch_a_new_acquisition(tmp_path):
    """Finalization is fenced by acquisition identity: a stale finalizer holding
    the prior output's claim can only ever publish the prior output — the new
    acquisition's distinct logical id means distinct rows it cannot reach."""
    app = create_app("testing")
    supervisor = FakeSupervisor()
    with app.app_context():
        db.create_all()
        session = session_service.create(
            {"name": "fenced-acq", "device_flows": [_valid_flow()]}
        )

        bind_contextvars(request_id="req-fenced-start")
        started = session_service.start_managed(session.id, supervisor)
        logical_a = _seed_logical_output(started, tmp_path, name="fa", components=2)

        bind_contextvars(request_id="req-fenced-stop")
        session_service.stop_managed(started.id, supervisor)

        repo = OutputFilesRepository()
        claim = repo.claim(logical_a, worker_id="w1", lease_ttl_seconds=300.0)
        assert claim is not None

        # New acquisition on the same session/hardware.
        new_run = create_output_file(
            tmp_path / "fb.bin",
            dataflow_id=started.dataflow_id,
            sink_type=SinkType.CSV,
            session_id=started.id,
        )
        logical_b = new_run.record.logical_sink_id

        # The claim publishes A; it cannot mutate B.
        repo.mark_merged(
            logical_a,
            finalization_id=claim.finalization_id,
            fence_token=claim.fence_token,
            final_output_id="A-final",
        )
        assert repo.get_head(logical_a).final_output_id == "A-final"
        head_b = repo.get_head(logical_b)
        assert head_b.final_output_id is None
        assert head_b.artifact_state == ARTIFACT_NOT_REQUIRED


def test_stop_route_returns_202_and_session_payload(app):
    with app.app_context():
        session = session_service.create(
            {
                "name": "route-backed-stop",
                "device_flows": [_valid_flow()],
            }
        )
        session.status = SessionStatus.ACTIVE
        session.dataflow_id = "route-dataflow-stop"
        session.watchdog_id = "route-watchdog-stop"
        db.session.commit()
        session_id = session.id

    response = app.test_client().post(
        f"/api/v1/sessions/{session_id}/commands/stop",
        headers={"X-Request-ID": "route-stop"},
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["id"] == str(session_id)
    assert body["status"] == "ending"
    assert app.extensions["watchdog_adapter"].messages[0].command == "stop"
