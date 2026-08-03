from app.database import db
from app.domain.enums import OperationState
from app.models.session import Session
from app.services.operations import create_operation


def test_ops_cli_lists_shows_and_resolves_uncertain_operation(app):
    with app.app_context():
        db.session.add(Session(id=1, name="ops-cli", dataflow_id="df-cli"))
        db.session.commit()
        operation = create_operation(
            session_id=1,
            dataflow_id="df-cli",
            command="start",
            request_key="req-cli",
        )
        operation.state = OperationState.UNCERTAIN
        operation.error_code = "runtime_identity_mismatch"
        db.session.commit()
        operation_id = operation.operation_id

    runner = app.test_cli_runner()

    listed = runner.invoke(args=["ops", "list", "--state", "uncertain"])
    assert listed.exit_code == 0
    assert operation_id in listed.output
    assert "runtime_identity_mismatch" in listed.output

    shown = runner.invoke(args=["ops", "show", operation_id])
    assert shown.exit_code == 0
    assert '"operation_id":' in shown.output
    assert operation_id in shown.output

    resolved = runner.invoke(
        args=[
            "ops",
            "resolve",
            operation_id,
            "--by",
            "operator@example.com",
            "--note",
            "Verified runtime manually.",
        ]
    )
    assert resolved.exit_code == 0
    assert "resolved" in resolved.output
    assert operation_id in resolved.output

    with app.app_context():
        next_operation = create_operation(
            session_id=1,
            dataflow_id="df-cli",
            command="restart-all-streams",
            request_key="after-cli-resolution",
        )
        assert next_operation.operation_id != operation_id
