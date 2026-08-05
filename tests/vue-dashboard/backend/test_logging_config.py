"""Output-contract tests for environment-specific log rendering."""

import io
import json
import logging

import structlog

from app.config import DevelopmentConfig, ProductionConfig
from app.logging_config import configure_logging


def _configured_output(config) -> io.StringIO:
    configure_logging(config)

    output = io.StringIO()
    root_handler = logging.getLogger().handlers[0]
    root_handler.setStream(output)
    return output


def _capture_log_lines(config) -> list[str]:
    output = _configured_output(config)

    structlog.get_logger("application").info("application_ready", component="flask")
    logging.getLogger("watchdog").info("watchdog_ready")

    return output.getvalue().splitlines()


def test_production_logs_are_json_for_structlog_and_standard_logging():
    lines = _capture_log_lines(ProductionConfig)

    events = [json.loads(line) for line in lines]

    assert [event["event"] for event in events] == [
        "application_ready",
        "watchdog_ready",
    ]
    assert events[0]["component"] == "flask"
    assert all(event["level"] == "info" for event in events)


def test_development_logs_are_human_readable():
    lines = _capture_log_lines(DevelopmentConfig)

    assert "application_ready" in lines[0]
    assert "component=flask" in lines[0]
    assert "watchdog_ready" in lines[1]

    for line in lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            continue
        raise AssertionError("development log unexpectedly rendered as JSON")


def test_structlog_excludes_sensitive_and_scientific_payload_fields():
    output = _configured_output(ProductionConfig)
    sentinel = "DO-NOT-LOG-STRUCTLOG-SENTINEL"

    structlog.get_logger("dataflow").info(
        "dataflow_packet_received",
        request_id="request-1",
        dataflow_id="dataflow-1",
        sample_count=128,
        password=sentinel,
        authorization=sentinel,
        request_body={"secret": sentinel},
        payload={"samples": [sentinel]},
        samples=[sentinel],
    )

    raw_output = output.getvalue()
    event = json.loads(raw_output)

    assert sentinel not in raw_output
    assert event["request_id"] == "request-1"
    assert event["dataflow_id"] == "dataflow-1"
    assert event["sample_count"] == 128
    assert "password" not in event
    assert "authorization" not in event
    assert "request_body" not in event
    assert "payload" not in event
    assert "samples" not in event


def test_standard_logging_keeps_safe_identifiers_and_excludes_sensitive_fields():
    output = _configured_output(ProductionConfig)
    sentinel = "DO-NOT-LOG-STDLIB-SENTINEL"

    logging.getLogger("watchdog").info(
        "watchdog_heartbeat",
        extra={
            "watchdog_id": "watchdog-1",
            "dataflow_id": "dataflow-1",
            "sample_count": 64,
            "token": sentinel,
            "payload": {"samples": [sentinel]},
        },
    )

    raw_output = output.getvalue()
    event = json.loads(raw_output)

    assert sentinel not in raw_output
    assert event["watchdog_id"] == "watchdog-1"
    assert event["dataflow_id"] == "dataflow-1"
    assert event["sample_count"] == 64
    assert "token" not in event
    assert "payload" not in event
