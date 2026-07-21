import re
import time
from uuid import uuid4

import structlog
from flask import Flask, g, request
from structlog.contextvars import bind_contextvars, clear_contextvars

log = structlog.get_logger("http")

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id() -> str:
    supplied = request.headers.get("X-Request-ID", "")

    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied

    return uuid4().hex


def register_request_logging(app: Flask) -> None:
    @app.before_request
    def start_request() -> None:
        clear_contextvars()

        request_id = _request_id()
        route = request.url_rule.rule if request.url_rule else "<unmatched>"

        identifiers = {
            "request_id": request_id,
            "http_method": request.method,
            "http_route": route,
        }

        # Session endpoints already expose this as a route parameter.
        if request.view_args and request.view_args.get("session_id"):
            identifiers["session_id"] = request.view_args["session_id"]

        bind_contextvars(**identifiers)

        g.request_id = request_id
        g.request_started_at = time.perf_counter()

        log.info("http_request_started")

    @app.after_request
    def complete_request(response):
        started_at = getattr(g, "request_started_at", None)
        request_id = getattr(g, "request_id", uuid4().hex)

        if started_at is not None:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        else:
            duration_ms = None

        response.headers["X-Request-ID"] = request_id

        log.info(
            "http_request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response

    @app.teardown_request
    def clear_request_context(_error=None) -> None:
        clear_contextvars()
