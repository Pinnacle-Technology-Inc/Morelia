from app.database import db
from app.domain.enums import OperationState, SessionStatus
from app.models.operation import Operation
from app.models.session import Session
from app.services.operations import create_operation


def test_operator_can_get_operation_by_id(client, app):
    with app.app_context():
        db.session.add(Session(id=1, name="ops-api", dataflow_id="df-api"))
        db.session.commit()
        operation = create_operation(
            session_id=1,
            dataflow_id="df-api",
            command="start",
            request_key="req-show",
            request_id="request-show",
            watchdog_id="watchdog-show",
        )
        operation.state = OperationState.DISPATCHED
        db.session.commit()
        operation_id = operation.operation_id

    response = client.get(f"/api/v1/operations/{operation_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["operation_id"] == operation_id
    assert body["request_key"] == "req-show"
    assert body["session_id"] == 1
    assert body["dataflow_id"] == "df-api"
    assert body["scope"] == "dataflow"
    assert body["command"] == "start"
    assert body["request_id"] == "request-show"
    assert body["watchdog_id"] == "watchdog-show"
    assert body["state"] == "dispatched"


def test_get_unknown_operation_returns_404_problem_json(client):
    response = client.get("/api/v1/operations/missing-operation")

    assert response.status_code == 404
    assert response.get_json(force=True)["code"] == "operation_not_found"


def test_operator_can_list_and_resolve_uncertain_operation(client, app):
    with app.app_context():
        db.session.add(Session(id=1, name="ops-api", dataflow_id="df-api"))
        db.session.commit()
        operation = create_operation(
            session_id=1,
            dataflow_id="df-api",
            command="start",
            request_key="req-api",
        )
        operation.state = OperationState.UNCERTAIN
        operation.error_code = "runtime_identity_mismatch"
        db.session.commit()
        operation_id = operation.operation_id

    listed = client.get("/api/v1/operations/?state=uncertain")

    assert listed.status_code == 200
    assert [row["operation_id"] for row in listed.get_json()] == [operation_id]

    response = client.post(
        f"/api/v1/operations/{operation_id}/resolve",
        json={
            "resolved_by": "operator@example.com",
            "resolution_note": "Verified runtime manually.",
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["operation_id"] == operation_id
    assert body["state"] == "uncertain"
    assert body["resolved_by"] == "operator@example.com"
    assert body["resolved_at"] is not None
    assert body["resolution_note"] == "Verified runtime manually."

    with app.app_context():
        stored = db.session.scalar(
            db.select(Operation).where(Operation.operation_id == operation_id)
        )
        assert stored.resolved_by == "operator@example.com"
        assert stored.resolved_at is not None
        next_operation = create_operation(
            session_id=1,
            dataflow_id="df-api",
            command="restart-all-streams",
            request_key="after-resolution",
        )
        assert next_operation.operation_id != operation_id


def test_operator_can_filter_operations_by_session_and_dataflow(client, app):
    with app.app_context():
        db.session.add(Session(id=1, name="ops-api-a", dataflow_id="df-api-a"))
        db.session.add(Session(id=2, name="ops-api-b", dataflow_id="df-api-b"))
        db.session.commit()
        op_a = create_operation(
            session_id=1,
            dataflow_id="df-api-a",
            command="start",
            request_key="req-api-a",
        )
        op_a_id = op_a.operation_id
        create_operation(
            session_id=2,
            dataflow_id="df-api-b",
            command="start",
            request_key="req-api-b",
        )
        db.session.commit()

    by_session = client.get("/api/v1/operations/?session=1")
    by_dataflow = client.get("/api/v1/operations/?dataflow=df-api-a")
    combined = client.get("/api/v1/operations/?session=1&dataflow=df-api-b")

    assert by_session.status_code == 200
    assert [row["operation_id"] for row in by_session.get_json()] == [op_a_id]
    assert by_dataflow.status_code == 200
    assert [row["operation_id"] for row in by_dataflow.get_json()] == [op_a_id]
    assert combined.status_code == 200
    assert combined.get_json() == []


def test_blocked_risky_command_returns_blocking_uncertain_operation(client, app):
    with app.app_context():
        db.session.add(
            Session(
                id=2,
                name="blocked-session",
                status=SessionStatus.DRAFT,
                dataflow_id="df-blocked",
                device_flows=[
                    {
                        "device": "dev-1",
                        "sinks": [{"destination": "C:/data/out.bin"}],
                    }
                ],
            )
        )
        db.session.commit()
        operation = create_operation(
            session_id=2,
            dataflow_id="df-blocked",
            command="start",
            request_key="req-blocking-op",
        )
        operation.state = OperationState.UNCERTAIN
        operation.error_code = "runtime_identity_mismatch"
        db.session.commit()
        operation_id = operation.operation_id

    response = client.post("/api/v1/sessions/2/commands/start")

    assert response.status_code == 423
    body = response.get_json(force=True)
    assert body["code"] == "operation_blocked_by_uncertain"
    assert body["operation_id"] == operation_id
    assert body["dataflow_id"] == "df-blocked"
    assert body["scope"] == "dataflow"
    assert body["command"] == "start"
    assert body["operation_state"] == "uncertain"
    assert body["resolution_required"] is True
