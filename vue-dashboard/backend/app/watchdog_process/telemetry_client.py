"""HTTP client that delivers outbox telemetry envelopes to the control plane.

Talks to the same direct-ingest endpoint the control plane exposes for
watchdog processes: ``POST /api/v1/internal/events`` (see
``app.api.events_ingest``). Production uses the stdlib ``urllib`` transport;
tests inject a Flask-test-client-backed transport — the same seam pattern as
``DataflowRuntimeHost``'s ``_push_fn`` (app/runtime_host/server.py) — so the
real ingest/fencing contract runs without a live socket.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

DIRECT_INGEST_PATH = "/api/v1/internal/events"
DEFAULT_TIMEOUT_SECONDS = 5.0

# (envelope_dict, headers) -> (status_code, parsed_json_body_or_None).
# status_code is 0 when the transport never got an HTTP response at all
# (connection refused, DNS failure, timeout).
TransportFn = Callable[[dict, dict[str, str]], tuple[int, dict | None]]


class DeliveryOutcome(Enum):
    """What happened to one envelope's delivery attempt."""

    DELIVERED = "delivered"
    # Transient failure (network error, 5xx, unexpected status) — safe to
    # retry the same envelope later; it is left pending in the outbox.
    RETRYABLE = "retryable"
    # 409 — the control plane's active-watchdog fencing (StaleWatchdogReport)
    # rejected this watchdog_id. Retrying will never succeed: a respawned
    # watchdog process has already claimed the active identity.
    STALE = "stale"
    # 401 — bad/missing token. Retrying with the same token will never
    # succeed.
    UNAUTHORIZED = "unauthorized"
    # 400 — the control plane rejected the envelope itself (malformed, or a
    # dataflow_id/manifest_hash mismatch). Retrying the identical
    # envelope will never succeed either, but unlike STALE/UNAUTHORIZED this
    # is not necessarily a sign that *this* watchdog_id is no longer active.
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    status_code: int | None = None
    message: str | None = None

    @property
    def is_fatal(self) -> bool:
        """Fatal: the control plane will never accept this watchdog_id as
        active again, so the watchdog process must stop rather than retry."""
        return self.outcome in (DeliveryOutcome.STALE, DeliveryOutcome.UNAUTHORIZED)


class TelemetryClient:
    """Sends one telemetry envelope at a time to the control plane's direct-ingest endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: TransportFn | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token or None
        self._timeout_seconds = timeout_seconds
        # Testing seam; production uses the stdlib urllib path below.
        self._transport: TransportFn = transport if transport is not None else self._http_transport

    def send(self, envelope: WatchdogTelemetryEnvelope) -> DeliveryResult:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["X-Agent-Token"] = self._token
        status_code, body = self._transport(envelope.to_dict(), headers)
        return _classify(status_code, body)

    def _http_transport(self, envelope: dict, headers: dict[str, str]) -> tuple[int, dict | None]:
        body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        request_headers = {**headers, "Content-Length": str(len(body))}
        request = urllib.request.Request(
            self._base_url + DIRECT_INGEST_PATH,
            data=body,
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return response.status, _read_json(response)
        except urllib.error.HTTPError as exc:
            return exc.code, _read_json(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return 0, {"message": str(exc)}


def _read_json(response) -> dict | None:
    try:
        raw = response.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _classify(status_code: int, body: dict | None) -> DeliveryResult:
    message = body.get("message") if isinstance(body, dict) else None
    if status_code == 202:
        return DeliveryResult(DeliveryOutcome.DELIVERED, status_code=status_code, message=message)
    if status_code == 409:
        return DeliveryResult(DeliveryOutcome.STALE, status_code=status_code, message=message)
    if status_code == 401:
        return DeliveryResult(DeliveryOutcome.UNAUTHORIZED, status_code=status_code, message=message)
    if status_code == 400:
        return DeliveryResult(DeliveryOutcome.REJECTED, status_code=status_code, message=message)
    return DeliveryResult(
        DeliveryOutcome.RETRYABLE, status_code=status_code or None, message=message
    )


__all__ = [
    "DIRECT_INGEST_PATH",
    "DeliveryOutcome",
    "DeliveryResult",
    "TelemetryClient",
    "TransportFn",
]
