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

