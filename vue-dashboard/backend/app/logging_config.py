import logging
import sys
from typing import Any

import structlog

SAFE_LOG_FIELDS = frozenset(
    {
        # Core event metadata.
        "event",
        "level",
        "logger",
        "timestamp",
        # Correlation identifiers shared by Flask and watchdog processes.
        "request_id",
        "session_id",
        "dataflow_id",
        "command_id",
        "recovery_id",
        "watchdog_id",
        # HTTP summaries. Never add headers, query strings, or request bodies.
        "http_method",
        "http_route",
        "status_code",
        "duration_ms",
        # Bounded operational metadata.
        "component",
        "action",
        "command",
        "outcome",
        "reason",
        "error_code",
        "error_type",
        "attempt",
        "stream_status",
        "comms_status",
        "recovery_stage",
        "policy_mode",
        "phase",
        # Process/runtime identity for supervision diagnostics.
        "runtime_id",
        "report_id",
        "port",
        "pid",
        "watchdog_pid",
        "watchdog_state",
        "watchdog_status",
        "probed_runtime_id",
        "probed_dataflow_id",
        "probed_watchdog_id",
        "dead_runtime_id",
        "active_ownership",
        # Failure diagnostics. Exception type/message/traceback come from our
        # own raise sites, not payload data; without these a child that dies
        # logs only a bare header line (undiagnosable — see packet 6 hardware
        # checkpoint, 2026-07-15). Raw samples and payloads remain forbidden.
        "error",
        "message",
        "error_message",
        "traceback",
        "exception",
        # Scientific data summaries. Raw samples and payloads are forbidden.
        "sample_count",
        "byte_count",
        "sequence_number",
        # Watchdog status-report summaries. These are normalized, bounded
        # operational values — never raw device samples or command payloads.
        "device_id",
        "stream_index",
        "worker_status",
        "heartbeat_status",
        "heartbeat_age_seconds",
        "source_read_state",
        "source_read_error_type",
        "source_read_error_message",
        "source_read_consecutive_failures",
        "first_packet_timeout_seconds",
        "first_packet_remaining_seconds",
        "failure_count",
        "failure_threshold",
        "recovery_attempt",
    }
)


def retain_safe_log_fields(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Drop every field that is not explicitly approved for log output."""
    return {key: value for key, value in event_dict.items() if key in SAFE_LOG_FIELDS}


def configure_logging(config: type[Any], *, stream: Any = None) -> None:
    """Configure structlog and standard logging before Flask is created.

    ``stream`` defaults to stdout for the Flask app. Pass ``sys.stderr``
    explicitly for a process whose stdout is a parsed handshake protocol
    (e.g. the runtime host child prints ``PORT:<n>`` / ``READY`` on stdout —
    interleaving log lines there would break the parent's line-by-line read).
    """

    level = config.LOG_LEVEL.upper()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if config.LOG_FORMAT == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ExtraAdder(allow=SAFE_LOG_FIELDS),
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            retain_safe_log_fields,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Ensure Werkzeug uses the root handler instead of adding its own.
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.handlers.clear()
    werkzeug_logger.propagate = True

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
