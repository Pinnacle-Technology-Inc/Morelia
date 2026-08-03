import pytest

from app import create_app
from app.database import db
from app.domain.enums import OperationScope, OperationState
from app.models.session import Session
from app.services.operations import (
    OperationConflict,
    OperationTransitionError,
    RequestKeyConflict,
    create_operation,
    transition_operation,
)


@pytest.fixture
def ops_app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="ops-test", dataflow_id="df-1"))
        db.session.commit()
    return app


def test_stream_operations_on_different_streams_can_run_together(ops_app):
    with ops_app.app_context():
        first = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="key-a",
            target_device_id="dev-a",
        )
        second = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="key-b",
            target_device_id="dev-b",
        )

        assert first.scope is OperationScope.STREAM
        assert second.scope is OperationScope.STREAM
        assert first.target_device_id == "dev-a"
        assert second.target_device_id == "dev-b"


def test_stream_operation_conflicts_with_same_active_stream(ops_app):
    with ops_app.app_context():
        create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="key-a",
            target_device_id="dev-a",
        )

        with pytest.raises(OperationConflict, match="active stream-scope operation"):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="reset-stream",
                request_key="key-b",
                target_device_id="dev-a",
            )


def test_dataflow_operation_conflicts_with_any_active_stream_operation(ops_app):
    with ops_app.app_context():
        create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="stream-key",
            target_device_id="dev-a",
        )

        with pytest.raises(OperationConflict, match="active stream-scope operation"):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="restart-all-streams",
                request_key="all-key",
            )


def test_stream_operation_conflicts_with_active_dataflow_operation(ops_app):
    with ops_app.app_context():
        create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart-all-streams",
            request_key="all-key",
        )

        with pytest.raises(OperationConflict, match="active dataflow-scope operation"):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="restart",
                request_key="stream-key",
                target_device_id="dev-a",
            )

def test_restart_all_streams_is_dataflow_scope(ops_app):
    with ops_app.app_context():
        operation = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart-all-streams",
            request_key="all-key",
        )

        assert operation.scope is OperationScope.DATAFLOW
        assert operation.target_device_id is None

def test_same_request_key_returns_existing_operation(ops_app):
    with ops_app.app_context():
        first = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="retry-key",
            target_device_id="dev-a",
        )
        second = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="retry-key",
            target_device_id="dev-a",
        )

        assert second.operation_id == first.operation_id
        assert first.command_id == first.operation_id
        assert first.queued_at is not None


def test_operation_state_machine_records_transition_timestamps(ops_app):
    with ops_app.app_context():
        operation = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="start",
            request_key="start-key",
        )

        claimed = transition_operation(operation.operation_id, OperationState.CLAIMED)
        dispatched = transition_operation(operation.operation_id, OperationState.DISPATCHED)
        running = transition_operation(operation.operation_id, OperationState.RUNNING)
        verifying = transition_operation(operation.operation_id, OperationState.VERIFYING)
        succeeded = transition_operation(operation.operation_id, OperationState.SUCCEEDED)

        assert claimed.claimed_at is not None
        assert dispatched.dispatched_at is not None
        assert running.running_at is not None
        assert verifying.verifying_at is not None
        assert succeeded.finished_at is not None


def test_operation_state_machine_rejects_illegal_transition(ops_app):
    with ops_app.app_context():
        operation = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="start",
            request_key="start-key",
        )

        with pytest.raises(OperationTransitionError, match="cannot transition"):
            transition_operation(operation.operation_id, OperationState.RUNNING)


def test_operation_terminal_state_rejects_later_transition(ops_app):
    with ops_app.app_context():
        operation = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="start",
            request_key="start-key",
        )
        transition_operation(operation.operation_id, OperationState.FAILED)

        with pytest.raises(OperationTransitionError, match="terminal"):
            transition_operation(operation.operation_id, OperationState.SUCCEEDED)

def test_request_key_rejects_different_payload(ops_app):
    with ops_app.app_context():
        create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="retry-key",
            target_device_id="dev-a",
        )

        with pytest.raises(RequestKeyConflict):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="restart",
                request_key="retry-key",
                target_device_id="dev-b",
            )

def test_unresolved_uncertain_stream_blocks_same_stream_and_dataflow_but_not_other_stream(
    ops_app,
):
    with ops_app.app_context():
        uncertain = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="uncertain-key",
            target_device_id="dev-a",
        )
        uncertain.state = OperationState.UNCERTAIN
        db.session.commit()

        create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="restart",
            request_key="other-stream-key",
            target_device_id="dev-b",
        )

        with pytest.raises(OperationConflict, match="unresolved uncertain stream-scope operation"):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="reset-stream",
                request_key="same-stream-key",
                target_device_id="dev-a",
            )

        with pytest.raises(OperationConflict, match="unresolved uncertain stream-scope operation"):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="stop",
                request_key="stop-key",
            )

def test_unresolved_uncertain_dataflow_blocks_all_scopes(ops_app):
    with ops_app.app_context():
        uncertain = create_operation(
            session_id=1,
            dataflow_id="df-1",
            command="start",
            request_key="start-key",
        )
        uncertain.state = OperationState.UNCERTAIN
        db.session.commit()

        with pytest.raises(
            OperationConflict,
            match="unresolved uncertain dataflow-scope operation",
        ):
            create_operation(
                session_id=1,
                dataflow_id="df-1",
                command="restart",
                request_key="stream-key",
                target_device_id="dev-a",
            )
