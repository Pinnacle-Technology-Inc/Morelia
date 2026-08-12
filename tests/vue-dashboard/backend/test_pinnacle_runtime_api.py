from app.database import db
from app.domain.enums import SessionStatus
from app.models.operation import Operation
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.services.operations import create_operation


def _session(session_id: int = 1, *, dataflow_id: str = "df-runtime") -> Session:
    session = Session(
        id=session_id,
        name=f"runtime-session-{session_id}",
        status=SessionStatus.STARTING,
        policy="recommend",
        device_flows=[{"device": "dev-1", "sinks": [{"destination": "C:/data/out.bin"}]}],
        command_in_flight=True,
        dataflow_id=dataflow_id,
        watchdog_id="watchdog-runtime",
    )
    db.session.add(session)
    db.session.commit()
    return session


def test_runtime_list_returns_active_ownership_rows(client, app):
    with app.app_context():
        _session(1, dataflow_id="df-active")
        _session(2, dataflow_id="df-stopped")
        ownerships = RuntimeOwnershipRepository()
        ownerships.create_starting(
            runtime_id="rt-active",
            session_id=1,
            dataflow_id="df-active",
            manifest_hash="hash-active",
            token="secret-active",
        )
        ownerships.mark_running("rt-active", pid=1234, port=8206)
        ownerships.create_starting(
            runtime_id="rt-stopped",
            session_id=2,
            dataflow_id="df-stopped",
            manifest_hash="hash-stopped",
            token="secret-stopped",
        )
        ownerships.mark_stopped("rt-stopped")

    response = client.get("/api/v1/runtimes/")

    assert response.status_code == 200
    body = response.get_json()
    assert [row["runtime_id"] for row in body] == ["rt-active"]
    assert body[0]["dataflow_id"] == "df-active"
    assert body[0]["state"] == "running"
    assert body[0]["pid"] == 1234
    assert body[0]["port"] == 8206
    assert body[0]["started_at"] is not None
    assert body[0]["last_seen_at"] is not None
    assert "token" not in body[0]


def test_runtime_list_empty_db_returns_empty_list(client):
    response = client.get("/api/v1/runtimes/")

    assert response.status_code == 200
    assert response.get_json() == []


def test_runtime_reconcile_returns_all_zero_summary_for_empty_db(client):
    response = client.post("/api/v1/runtimes/reconcile")

    assert response.status_code == 200
    assert response.get_json() == {
        "succeeded_operations": 0,
        "failed_operations": 0,
        "uncertain_operations": 0,
        "adopted_runtimes": 0,
        "stopped_runtimes": 0,
        "uncertain_runtimes": 0,
        "deferred_runtimes": 0,
        "released_orphan_sessions": 0,
    }


def test_runtime_shutdown_delegates_to_host_supervisor(client, app):
    class StubSupervisor:
        def __init__(self) -> None:
            self.calls = []

        def stop_all(self, *, force: bool = False):
            self.calls.append(force)
            return {
                "running_count": 1,
                "stopped_count": 0,
                "failed_count": 1,
                "failures": [{"dataflow_id": "df-runtime", "error": "wedged"}],
                "forced": force,
            }

    supervisor = StubSupervisor()
    app.extensions["host_supervisor"] = supervisor

    response = client.post("/api/v1/runtimes/shutdown", json={"force": True})

    assert response.status_code == 200
    assert supervisor.calls == [True]
    assert response.get_json()["forced"] is True
    assert response.get_json()["failed_count"] == 1


def test_control_plane_shutdown_stops_hosts_and_schedules_process_exit(client, app, monkeypatch):
    import app.api.runtimes as runtimes_api

    class StubSupervisor:
        def __init__(self) -> None:
            self.calls = []

        def stop_all(self, *, force: bool = False):
            self.calls.append(force)
            return {
                "running_count": 1,
                "stopped_count": 1,
                "failed_count": 0,
                "failures": [],
                "forced": force,
            }

    scheduled = []
    supervisor = StubSupervisor()
    app.extensions["host_supervisor"] = supervisor
    monkeypatch.setattr(runtimes_api, "_schedule_process_shutdown", lambda: scheduled.append(True))

    response = client.post("/api/v1/runtimes/control-plane-shutdown", json={"force": False})

    assert response.status_code == 202
    body = response.get_json()
    assert body["shutdown_scheduled"] is True
    assert body["runtime_shutdown"]["stopped_count"] == 1
    assert supervisor.calls == [False]
    assert scheduled == [True]


def test_control_plane_restart_quiesces_without_stopping_hosts(client, app, monkeypatch):
    import app.api.runtimes as runtimes_api

    class StubSupervisor:
        def __init__(self) -> None:
            self.quiesce_calls = 0
            self.stop_all_calls = 0

        def quiesce(self):
            self.quiesce_calls += 1
            return {"tracked_runtime_count": 2}

        def stop_all(self, *, force: bool = False):
            self.stop_all_calls += 1
            raise AssertionError("restart must not stop runtime hosts")

    scheduled = []
    supervisor = StubSupervisor()
    app.extensions["host_supervisor"] = supervisor
    monkeypatch.setattr(runtimes_api, "_schedule_process_shutdown", lambda: scheduled.append(True))

    response = client.post("/api/v1/runtimes/control-plane-restart")

    assert response.status_code == 202
    assert response.get_json() == {
        "quiesced": True,
        "shutdown_scheduled": True,
        "tracked_runtime_count": 2,
    }
    assert supervisor.quiesce_calls == 1
    assert supervisor.stop_all_calls == 0
    assert app.extensions["control_plane_state"].preserve_runtime_hosts_on_exit is True
    assert scheduled == [True]


def test_quiescing_control_plane_rejects_new_session_lifecycle_commands(
    client, app, monkeypatch
):
    import app.api.runtimes as runtimes_api

    class StubSupervisor:
        def quiesce(self):
            return {"tracked_runtime_count": 0}

    app.extensions["host_supervisor"] = StubSupervisor()
    monkeypatch.setattr(
        runtimes_api, "_schedule_process_shutdown", lambda: None
    )

    restart = client.post("/api/v1/runtimes/control-plane-restart")

    response = client.post(
        "/api/v1/session-runs",
        json={
            "idempotency_key": "quiescing-test-1",
            "source_template_id": "test-template",
            "expected_template_hash": "0" * 64,
            "assignments": [
                {
                    "flow_index": 0,
                    "device_config_id": 1,
                    "sink_locations": [],
                }
            ],
            "execution": {
                "mode": "immediate",
            },
        },
    )

    assert restart.status_code == 202
    assert response.status_code == 503, response.get_json()
    assert response.get_json()["code"] == "control_plane_quiescing"


def test_runtime_reconcile_runs_startup_reconciliation(client, app):
    with app.app_context():
        _session()
        operation = create_operation(
            session_id=1,
            dataflow_id="df-runtime",
            command="start",
            request_key="req-runtime-reconcile",
        )
        operation_id = operation.operation_id

    response = client.post("/api/v1/runtimes/reconcile")

    assert response.status_code == 200
    assert response.get_json() == {
        "succeeded_operations": 0,
        "failed_operations": 1,
        "uncertain_operations": 0,
        "adopted_runtimes": 0,
        "stopped_runtimes": 0,
        "uncertain_runtimes": 0,
        "deferred_runtimes": 0,
        "released_orphan_sessions": 0,
    }
    with app.app_context():
        stored = db.session.scalar(
            db.select(Operation).where(Operation.operation_id == operation_id)
        )
        session = db.session.get(Session, 1)
        assert stored.state.value == "failed"
        assert stored.error_code == "interrupted_before_dispatch"
        assert session.command_in_flight is False
