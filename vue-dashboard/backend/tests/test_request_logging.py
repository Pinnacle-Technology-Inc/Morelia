"""Behavior tests for HTTP request correlation."""

import logging
import re


def test_generated_request_id_is_returned_in_response(client):
    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)


def test_supplied_request_id_is_reused(client):
    response = client.get(
        "/health",
        headers={"X-Request-ID": "test-request-123"},
    )

    assert response.headers["X-Request-ID"] == "test-request-123"


def test_invalid_request_id_is_replaced(client):
    invalid_request_id = "spaces are not allowed"

    response = client.get(
        "/health",
        headers={"X-Request-ID": invalid_request_id},
    )

    replacement = response.headers["X-Request-ID"]
    assert replacement != invalid_request_id
    assert re.fullmatch(r"[0-9a-f]{32}", replacement)


def test_request_context_does_not_leak_between_requests(client, caplog):
    caplog.set_level(logging.INFO, logger="http")

    client.get(
        "/api/v1/sessions/missing-session",
        headers={"X-Request-ID": "session-request"},
    )
    client.get(
        "/health",
        headers={"X-Request-ID": "health-request"},
    )

    health_start_event = next(
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict)
        and record.msg.get("event") == "http_request_started"
        and record.msg.get("request_id") == "health-request"
    )

    assert "session_id" not in health_start_event
