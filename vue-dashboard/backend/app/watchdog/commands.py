"""Flask-side construction and logging of guarded watchdog commands."""

from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, get_contextvars, unbind_contextvars

from app.watchdog.messages import CommandEnvelope, CorrelationEnvelope

log = structlog.get_logger("commands")


def prepare_command(
    *,
    command: str,
    dataflow_id: str,
    watchdog_id: str,
    command_id: str | None = None,
    recovery_id: str | None = None,
    target_device_id: str | None = None,
    runtime_id: str | None = None,
    publish: bool = True,
) -> CommandEnvelope:
    """Create a command, optionally publishing its correlation to control-plane logs.

    ``target_device_id`` names the one device→sink stream a recovery command
    acts on (reconnect/restart/reset-stream); leave it None for whole-dataflow
    commands like start/stop.

    ``runtime_id`` is the owning runtime host ownership row, when known (see
    ``app.services.sessions._active_runtime_id``) — omitted for the legacy
    single-watchdog dispatch path, which has no per-dataflow runtime host to
    attribute it to.

    No ``session_id`` parameter by design: it is a control-plane-only concept
    and never rides the command envelope down to a watchdog (see
    ``CorrelationEnvelope``). Control-plane logs still carry ``session_id`` —
    bound from the request route by ``app.request_logging`` — so dropping it
    here loses no observability on this side of the wire.

    Immediate create-and-start uses ``publish=False`` until dispatch returns,
    so a definitely rejected attempt is correlated only by ``request_id`` and
    never publishes a dataflow identity.
    """
    request_id = get_contextvars().get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("request_id must be bound before preparing a command")

    correlation = CorrelationEnvelope(
        request_id=request_id,
        dataflow_id=dataflow_id,
        command_id=command_id or uuid4().hex,
        watchdog_id=watchdog_id,
        recovery_id=recovery_id,
        runtime_id=runtime_id,
    )

    envelope = CommandEnvelope(
        command=command,
        correlation=correlation,
        target_device_id=target_device_id,
    )
    if publish:
        publish_command(envelope)
    return envelope


def publish_command(envelope: CommandEnvelope) -> None:
    """Publish command identity to logs after its durable visibility boundary."""
    correlation = envelope.correlation
    if correlation.recovery_id is None:
        unbind_contextvars("recovery_id")
    if correlation.runtime_id is None:
        unbind_contextvars("runtime_id")
    bind_contextvars(**correlation.to_dict())
    log.info("command_started", command=envelope.command)
