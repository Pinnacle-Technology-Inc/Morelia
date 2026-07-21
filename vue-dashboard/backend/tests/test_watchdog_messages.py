"""Contract tests for Flask-to-watchdog command correlation."""

import pytest
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars

from app.domain.enums import DeviceType
from app.services.device_configs import create as create_device_config
from app.watchdog.commands import prepare_command
from app.watchdog.messages import (
    WATCHDOG_PROTOCOL_VERSION,
    CommandEnvelope,
    CorrelationEnvelope,
)
from app.watchdog.receiver import receive_command


def test_command_envelope_has_stable_serializable_identifier_fields():
    envelope = CommandEnvelope(
        command="restart",
        correlation=CorrelationEnvelope(
            request_id="request-1",
            dataflow_id="dataflow-1",
            command_id="command-1",
            recovery_id="recovery-1",
            watchdog_id="watchdog-1",
        ),
    )

    assert envelope.to_dict() == {
        "protocol_version": WATCHDOG_PROTOCOL_VERSION,
        "command": "restart",
        "correlation": {
            "request_id": "request-1",
            "dataflow_id": "dataflow-1",
            "command_id": "command-1",
            "recovery_id": "recovery-1",
            "watchdog_id": "watchdog-1",
        },
    }


def test_correlation_envelope_includes_runtime_id_when_provided():
    correlation = CorrelationEnvelope(
        request_id="request-1",
        dataflow_id="dataflow-1",
        command_id="command-1",
        watchdog_id="watchdog-1",
        runtime_id="runtime-1",
    )

    assert correlation.to_dict() == {
        "request_id": "request-1",
        "dataflow_id": "dataflow-1",
        "command_id": "command-1",
        "watchdog_id": "watchdog-1",
        "runtime_id": "runtime-1",
    }
    assert CorrelationEnvelope.from_dict(correlation.to_dict()) == correlation


def test_correlation_envelope_omits_runtime_id_instead_of_sending_null():
    correlation = CorrelationEnvelope(
        request_id="request-1",
        dataflow_id="dataflow-1",
        command_id="command-1",
        watchdog_id="watchdog-1",
    )

    assert "runtime_id" not in correlation.to_dict()
    assert correlation.runtime_id is None


def test_correlation_envelope_rejects_empty_runtime_id():
    with pytest.raises(ValueError, match="runtime_id"):
        CorrelationEnvelope(
            request_id="request-1",
            dataflow_id="dataflow-1",
            command_id="command-1",
            watchdog_id="watchdog-1",
            runtime_id="",
        )


def test_non_recovery_command_omits_recovery_id_instead_of_sending_null():
    correlation = CorrelationEnvelope(
        request_id="request-1",
        dataflow_id="dataflow-1",
        command_id="command-1",
        watchdog_id="watchdog-1",
    )

    assert "recovery_id" not in correlation.to_dict()


def test_correlation_envelope_carries_no_session_id():
    """session_id is a control-plane-only concept and never rides the wire."""
    correlation = CorrelationEnvelope(
        request_id="request-1",
        dataflow_id="dataflow-1",
        command_id="command-1",
        watchdog_id="watchdog-1",
    )

    assert "session_id" not in correlation.to_dict()
    assert not hasattr(correlation, "session_id")

    # A wire message that still names session_id is now an unknown field.
    with pytest.raises(ValueError, match="unknown correlation fields"):
        CorrelationEnvelope.from_dict(
            {
                "request_id": "request-1",
                "session_id": "session-1",
                "dataflow_id": "dataflow-1",
                "command_id": "command-1",
                "watchdog_id": "watchdog-1",
            }
        )


def test_watchdog_rebind_clears_stale_context_and_uses_envelope_fields():
    clear_contextvars()
    bind_contextvars(request_id="stale-request", session_id="stale-session")

    correlation = CorrelationEnvelope(
        request_id="request-1",
        dataflow_id="dataflow-1",
        command_id="command-1",
        recovery_id="recovery-1",
        watchdog_id="watchdog-1",
    )
    correlation.bind()

    # The stale session_id is cleared and never reintroduced — the envelope
    # carries no session_id to rebind.
    assert get_contextvars() == correlation.to_dict()
    assert "session_id" not in get_contextvars()
    clear_contextvars()


def test_correlation_envelope_rejects_unknown_or_empty_identifier_fields():
    with pytest.raises(ValueError, match="unknown correlation fields"):
        CorrelationEnvelope.from_dict(
            {
                "request_id": "request-1",
                "dataflow_id": "dataflow-1",
                "command_id": "command-1",
                "watchdog_id": "watchdog-1",
                "payload": "scientific-data",
            }
        )

    with pytest.raises(ValueError, match="request_id"):
        CorrelationEnvelope.from_dict(
            {
                "request_id": "",
                "dataflow_id": "dataflow-1",
                "command_id": "command-1",
                "watchdog_id": "watchdog-1",
            }
        )


def test_command_envelope_rejects_unsupported_protocol_version():
    with pytest.raises(ValueError, match="unsupported watchdog protocol version"):
        CommandEnvelope.from_dict(
            {
                "protocol_version": "2",
                "command": "start",
                "correlation": {
                    "request_id": "request-1",
                    "dataflow_id": "dataflow-1",
                    "command_id": "command-1",
                    "watchdog_id": "watchdog-1",
                },
            }
        )


def test_one_flask_request_is_correlated_with_the_watchdog_event(app, client, caplog):
    with app.app_context():
        config = create_device_config(
            device_type=DeviceType.POD8206HR,
            hardware_id="MSG01",
            port="COM3",
            parameters={"preamp_gain": 10},
        )
        config_id = config.id
    created = client.post(
        "/api/v1/sessions/",
        json={
            "device_flows": [
                {
                    "device_config_id": config_id,
                    "sink_type": "csv",
                    "sink_location": "C:/data/message.csv",
                }
            ]
        },
    ).get_json()
    caplog.clear()

    response = client.post(
        f"/api/v1/sessions/{created['id']}/commands/start",
        headers={"X-Request-ID": "trace-request-1"},
    )

    dispatched = app.extensions["watchdog_dispatcher"].messages[0]
    receive_command(dispatched.to_dict())

    flask_event = next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "command_started"
    )
    watchdog_record = next(
        record
        for record in caplog.records
        if record.name == "watchdog" and record.getMessage() == "watchdog_command_received"
    )

    # session_id is intentionally absent from this set: it does not cross the
    # wire, so the watchdog log has no session_id to correlate against. The
    # control-plane log keeps its own session_id via request_logging.
    identifier_fields = (
        "request_id",
        "dataflow_id",
        "command_id",
        "watchdog_id",
    )

    assert response.status_code == 202
    assert dispatched.command == "start"
    assert {
        field: flask_event[field] for field in identifier_fields
    } == {
        field: getattr(watchdog_record, field) for field in identifier_fields
    }
    assert not hasattr(watchdog_record, "session_id")


def test_recovery_command_keeps_recovery_id_across_flask_and_watchdog_logs(caplog):
    clear_contextvars()
    bind_contextvars(request_id="request-1", session_id="session-1")

    envelope = prepare_command(
        command="restart",
        dataflow_id="dataflow-1",
        watchdog_id="watchdog-1",
        recovery_id="recovery-1",
    )
    receive_command(envelope.to_dict())

    flask_event = next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == "command_started"
    )
    watchdog_record = next(
        record
        for record in caplog.records
        if record.name == "watchdog" and record.getMessage() == "watchdog_command_received"
    )

    assert flask_event["recovery_id"] == "recovery-1"
    assert watchdog_record.recovery_id == "recovery-1"
    assert envelope.correlation.recovery_id == "recovery-1"
    clear_contextvars()


def test_prepare_command_threads_runtime_id_onto_the_envelope():
    clear_contextvars()
    bind_contextvars(request_id="request-1", session_id="session-1")

    envelope = prepare_command(
        command="restart",
        dataflow_id="dataflow-1",
        watchdog_id="watchdog-1",
        recovery_id="recovery-1",
        runtime_id="runtime-1",
    )

    assert envelope.correlation.runtime_id == "runtime-1"
    assert get_contextvars()["runtime_id"] == "runtime-1"
    clear_contextvars()


def test_prepare_command_omits_runtime_id_when_not_given():
    clear_contextvars()
    bind_contextvars(request_id="request-1", session_id="session-1", runtime_id="stale-runtime")

    envelope = prepare_command(
        command="restart",
        dataflow_id="dataflow-1",
        watchdog_id="watchdog-1",
        recovery_id="recovery-1",
    )

    assert envelope.correlation.runtime_id is None
    assert "runtime_id" not in get_contextvars()
    clear_contextvars()


def test_prepare_command_requires_request_context():
    clear_contextvars()

    with pytest.raises(RuntimeError, match="request_id"):
        prepare_command(
            command="restart",
            dataflow_id="dataflow-1",
            watchdog_id="watchdog-1",
            recovery_id="recovery-1",
        )
