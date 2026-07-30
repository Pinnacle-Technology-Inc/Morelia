"""Consistent error responses in RFC 9457 ("Problem Details") format.

Every error the API emits — a validation failure, a missing resource, a locked
dataflow — flows through this ONE place and comes out as `application/problem+json`,
so the Vue client can handle them all with a single code path.

The body shape (RFC 9457):
    {
      "type":     "about:blank",            # URI naming the error KIND (about:blank = generic)
      "title":    "Not Found",              # short, stable human label for the kind
      "status":   404,                      # HTTP status, mirrored into the body
      "detail":   "No session with id 42",  # specifics for THIS occurrence
      "instance": "/api/v1/sessions/42",    # which request/resource it happened on
      "code":     "not_found",              # EXTENSION: stable, machine-readable key
      "errors":   {...}                     # EXTENSION: per-field messages (validation only)
    }

Contract rule for the frontend: branch on `code`, never on `detail`. `detail`
is human prose that may be reworded any time; `code` is the promise.
"""

from http import HTTPStatus

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

# The machine-readable `code` to use when an abort() didn't supply its own.
# These line up with the status-code taxonomy from the issue's verification.
_DEFAULT_CODE = {
    400: "bad_request",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    423: "locked",
}


def _build_problem(
    status: int,
    *,
    detail: str,
    code: str,
    errors: dict | None = None,
    extensions: dict | None = None,
) -> dict:
    """Assemble an RFC 9457 problem body from typed components."""
    problem = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "instance": request.path,
        "code": code,
    }
    if errors is not None:
        problem["errors"] = errors
    if extensions:
        problem.update(extensions)
    return problem


def _make_response(problem: dict):
    response = jsonify(problem)
    response.status_code = problem["status"]
    response.content_type = "application/problem+json"
    return response


def _problem_response(exc: HTTPException):
    """Render any werkzeug HTTPException as an RFC 9457 problem document."""
    status = exc.code or 500

    # flask-smorest's abort() stashes extra kwargs (e.g. message=, code=) on
    # `exc.data`; webargs stashes field-validation failures under "messages".
    data = getattr(exc, "data", None) or {}

    return _make_response(_build_problem(
        status,
        detail=data.get("message") or exc.description,
        code=data.get("code") or _DEFAULT_CODE.get(status, "http_error"),
        errors=data.get("messages"),
    ))


def register_error_handlers(app) -> None:
    """Route ALL HTTPExceptions through the problem+json formatter.

    Must be called AFTER flask-smorest's Api(app): Flask keys error handlers by
    exception class, so registering ours for HTTPException last makes it win
    over flask-smorest's default error shape — giving the whole API one structure.
    """
    from app.domain.errors import (
        CommandInFlight,
        DeviceClaimConflict,
        DeviceConfigExists,
        DeviceConfigNotFound,
        DeviceConfigNotFree,
        DeviceNicknameExists,
        DeviceTemplateNameExists,
        DeviceTemplateNotFound,
        EmptySession,
        IncidentNotFound,
        InvalidHardwareId,
        InvalidSessionEntry,
        InvalidTransition,
        OperationNotFound,
        OperationResolutionError,
        RuntimeNotTracked,
        SessionNotFound,
        SessionTemplateNameExists,
        SessionTemplateNotFound,
        SinkLocationExists,
        SinkParentUnavailable,
        StopProofMissing,
    )
    from app.watchdog.adapters import (
        WatchdogInvalidResponseError,
        WatchdogTimeoutError,
        WatchdogUnavailableError,
    )
    from app.services.experiments import ExperimentArchived, ExperimentNotFound

    app.register_error_handler(HTTPException, _problem_response)

    def _domain(status: int, code: str):
        def _handler(e):
            return _make_response(_build_problem(
                status,
                detail=str(e),
                code=getattr(e, "code", code),
                extensions=getattr(e, "details", None),
            ))

        return _handler

    def _invalid_session_entry(e):
        """422 for a semantically-invalid session/template device flow.

        Raised by the session-config service (app.services.session_config) for
        a malformed ``sinks[]``/device-flow entry posted to the session create
        route. ``str(e)`` names the offending field (e.g.
        ``sinks[0].sink_parameters.token``) but never echoes a rejected secret
        VALUE — the service rejects a secret-looking key before reading it —
        so this detail is always safe to return to the client. ``field`` is
        surfaced as an extension so a client can address the exact input.

        NOTE: the session-template routes catch ValueError themselves and abort
        with ``invalid_session_template`` before it reaches this handler, so
        this only governs the session (and template-export) paths.
        """
        return _make_response(_build_problem(
            422,
            detail=str(e),
            code="invalid_session_entry",
            extensions={"field": e.field},
        ))

    app.register_error_handler(SessionNotFound,             _domain(404, "session_not_found"))
    app.register_error_handler(ExperimentNotFound,          _domain(404, "experiment_not_found"))
    app.register_error_handler(ExperimentArchived,          _domain(409, "experiment_archived"))
    app.register_error_handler(
        SessionTemplateNotFound,
        _domain(404, "session_template_not_found"),
    )
    app.register_error_handler(
        SessionTemplateNameExists,
        _domain(409, "session_template_name_exists"),
    )
    app.register_error_handler(
        DeviceTemplateNotFound,
        _domain(404, "device_template_not_found"),
    )
    app.register_error_handler(
        DeviceTemplateNameExists,
        _domain(409, "device_template_name_exists"),
    )
    app.register_error_handler(
        DeviceConfigNotFound,
        _domain(404, "device_config_not_found"),
    )
    app.register_error_handler(
        DeviceConfigExists,
        _domain(409, "device_config_exists"),
    )
    app.register_error_handler(
        DeviceNicknameExists,
        _domain(409, "device_nickname_exists"),
    )
    app.register_error_handler(
        DeviceConfigNotFree,
        _domain(409, "device_config_not_free"),
    )
    app.register_error_handler(
        DeviceClaimConflict,
        _domain(409, "device_claim_conflict"),
    )
    app.register_error_handler(
        InvalidHardwareId,
        _domain(422, "invalid_hardware_id"),
    )
    app.register_error_handler(InvalidSessionEntry, _invalid_session_entry)
    app.register_error_handler(CommandInFlight,             _domain(423, "command_in_flight"))
    app.register_error_handler(InvalidTransition,           _domain(409, "invalid_transition"))
    app.register_error_handler(EmptySession,                _domain(409, "empty_session"))
    app.register_error_handler(SinkLocationExists,          _domain(409, "sink_location_exists"))
    app.register_error_handler(
        SinkParentUnavailable,
        _domain(422, "sink_parent_unavailable"),
    )
    app.register_error_handler(OperationNotFound,           _domain(404, "operation_not_found"))
    app.register_error_handler(IncidentNotFound,            _domain(404, "incident_not_found"))
    app.register_error_handler(RuntimeNotTracked,           _domain(409, "runtime_not_tracked"))
    app.register_error_handler(StopProofMissing,            _domain(409, "stop_proof_missing"))
    app.register_error_handler(
        OperationResolutionError,
        _domain(409, "operation_resolution_error"),
    )
    app.register_error_handler(WatchdogTimeoutError,        _domain(504, "watchdog_timeout"))
    app.register_error_handler(WatchdogUnavailableError,    _domain(503, "watchdog_unavailable"))
    app.register_error_handler(
        WatchdogInvalidResponseError,
        _domain(502, "watchdog_invalid_response"),
    )
