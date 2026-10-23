"""The actual host registers itself before a watchdog can start."""

import os

import pytest

from app.database import db
from app.domain.enums import PolicyMode, RuntimeOwnershipState, SessionStatus
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.runtime_host.__main__ import _build_driver
from app.runtime_host.manifest import DeviceFlow, Manifest, MANIFEST_SCHEMA_VERSION
from app.runtime_host.process_evidence import record_process_identity


@pytest.fixture
def startup(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(app.config["SQLALCHEMY_DATABASE_URI"]))
    with app.app_context():
        flow = DeviceFlow(device_id="startup-device", name="startup-device",
            hardware_id="unused-hardware", port="unused-port", parameters={},
            sink_type="csv", sink_location=str(tmp_path / "unused.csv"))
        manifest = Manifest(schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="startup-flow", policy=PolicyMode.RECOMMEND, device_flows=(flow,))
        session = Session(name="startup identity", status=SessionStatus.PREPARING,
            policy=manifest.policy, dataflow_id=manifest.dataflow_id,
            device_flows=[flow.to_dict()])
        db.session.add(session)
        db.session.flush()
        owner = RuntimeOwnership(runtime_id="startup-runtime", session_id=session.id,
            dataflow_id=manifest.dataflow_id, manifest_hash=manifest.hash,
            state=RuntimeOwnershipState.STARTING, pid=999999,
            details={"unrelated": "preserved", "host_process_identity_source": "launcher",
                     "host_process_identity": {"pid": 999999, "creation_filetime": "1"}})
        db.session.add(owner)
        db.session.commit()
        driver = _build_driver(manifest, manifest_path=str(tmp_path / "manifest.json"),
            driver_name="morelia", on_report=lambda report: None,
            runtime_id=owner.runtime_id, ingest_url="http://127.0.0.1:1", ingest_token=None,
            outbox_dir=str(tmp_path / "outboxes"), hardware_lock_dir=None, control_token=None,
            adopt_watchdog_id=None, adopt_watchdog_pid=None, adopt_watchdog_control_port=None)
        yield driver, owner


def _assert_actual_host(owner):
    db.session.refresh(owner)
    assert owner.pid == os.getpid()
    assert owner.details["host_process_identity"] == record_process_identity(os.getpid())
    assert owner.details["host_process_identity_source"] == "runtime_host"
    assert owner.details["unrelated"] == "preserved"


def test_actual_host_identity_commits_before_watchdog_popen(startup):
    driver, owner = startup
    invoked = []

    class ReachedSpawnBoundary(Exception):
        pass

    def observe_spawn(*args, **kwargs):
        kwargs["stderr"].close()
        _assert_actual_host(owner)
        assert owner.watchdog_id
        invoked.append(True)
        raise ReachedSpawnBoundary

    driver._popen = observe_spawn
    with pytest.raises(ReachedSpawnBoundary):
        driver._spawn_watchdog_process()
    assert invoked == [True]


@pytest.mark.parametrize("state,intent_key", [
    (RuntimeOwnershipState.STOPPING, None),
    (RuntimeOwnershipState.STOPPED, None),
    (RuntimeOwnershipState.UNCERTAIN, "pending_stop_request"),
    (RuntimeOwnershipState.UNCERTAIN, "stop_intent"),
])
def test_stop_accepted_after_driver_creation_blocks_spawn_but_retains_host(startup, state, intent_key):
    driver, owner = startup
    owner.state = state
    if intent_key:
        owner.details = {**owner.details, intent_key: {
            "command_id": "accepted-stop", "requested_at": "2026-10-14T12:00:00Z",
            "stop_reason": "user_stop",
        }}
    db.session.commit()
    invoked = []
    driver._popen = lambda *args, **kwargs: invoked.append(True)

    with pytest.raises(RuntimeError, match="persisted stop intent forbids watchdog spawn"):
        driver._spawn_watchdog_process()

    assert invoked == []
    _assert_actual_host(owner)
    assert owner.state is state
    assert owner.watchdog_id is None


def test_post_spawn_identity_update_is_retained_after_stop_intent(startup):
    driver, owner = startup
    owner.state = RuntimeOwnershipState.STOPPING
    db.session.commit()
    driver._before_spawn("already-spawned-watchdog", "outbox.sqlite3", pid=12345)
    _assert_actual_host(owner)
    assert owner.state is RuntimeOwnershipState.STOPPING
    assert owner.watchdog_pid == 12345


def test_cleanup_rejects_launcher_exit_when_host_identity_changes_during_probe(startup, monkeypatch):
    from app.control import supervisor as supervisor_module
    from app.runtime_host.process_evidence import ProcessEvidence, ProcessState

    driver, owner = startup
    owner.watchdog_id = "registered-watchdog"
    owner.details = {**owner.details, "pending_stop_request": {
        "command_id": "accepted-stop", "requested_at": "2026-10-14T12:00:00Z",
        "stop_reason": "user_stop",
    }}
    db.session.commit()
    old_pid = owner.pid
    runtime_id = owner.runtime_id
    session = db.session.get(Session, owner.session_id)
    replacement_pid = old_pid + 1
    replacement_details = {**owner.details,
        "host_process_identity": {"pid": replacement_pid, "creation_filetime": "2"},
        "host_process_identity_source": "runtime_host"}
    probes = []
    cleaned = []

    def probe_and_replace(pid):
        probes.append(pid)
        # A separate DB connection models the host publishing its identity during observation.
        with db.engine.begin() as connection:
            connection.execute(db.update(RuntimeOwnership).where(
                RuntimeOwnership.runtime_id == runtime_id,
            ).values(pid=replacement_pid, details=replacement_details))
        return ProcessEvidence(pid, ProcessState.DEAD, "launcher_exited")

    supervisor = supervisor_module.HostSupervisor()
    monkeypatch.setattr(supervisor_module, "probe_process", probe_and_replace)
    monkeypatch.setattr(supervisor, "_manifest_for_reconcile", lambda *args: driver._manifest)
    monkeypatch.setattr(supervisor, "_lifecycle_reports", lambda *args: [])
    monkeypatch.setattr(supervisor, "_cleanup_contained_watchdogs", lambda *args: cleaned.append(True))

    assert supervisor._administrative_stop_evidence(session, owner) is None
    assert probes == [old_pid]
    assert cleaned == []
    assert owner.pid == replacement_pid
