"""Runtime and test adapters for the versioned localhost Watchdog API."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.watchdog.messages import (
    WATCHDOG_COMMAND_PATH,
    WATCHDOG_PROTOCOL_VERSION,
    CommandEnvelope,
)

DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_MAX_RESPONSE_BYTES = 65_536
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class WatchdogAdapterError(RuntimeError):
    """Base class for safe failures at the Watchdog boundary."""


class WatchdogTimeoutError(WatchdogAdapterError):
    """The Watchdog did not respond before the configured deadline."""


class WatchdogUnavailableError(WatchdogAdapterError):
    """The Watchdog could not be reached or returned a non-success status."""


class WatchdogInvalidResponseError(WatchdogAdapterError):
    """The Watchdog returned data outside the declared response schema."""


class WatchdogUnsupportedProtocolError(WatchdogInvalidResponseError):
    """The Watchdog spoke a protocol version this backend does not support."""


@dataclass(frozen=True, slots=True)
class CommandAcknowledgement:
    """Strict response schema for an accepted Watchdog command."""

    status: str
    command_id: str
    watchdog_id: str

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> CommandAcknowledgement:
        allowed_fields = {
            "protocol_version",
            "status",
            "command_id",
            "watchdog_id",
        }
        unknown_fields = set(values) - allowed_fields
        if unknown_fields:
            raise WatchdogInvalidResponseError("Watchdog response has unknown fields.")

        protocol_version = values.get("protocol_version")
        if protocol_version != WATCHDOG_PROTOCOL_VERSION:
            raise WatchdogUnsupportedProtocolError(
                f"Watchdog returned unsupported protocol version {protocol_version!r}."
            )

        status = values.get("status")
        command_id = values.get("command_id")
        watchdog_id = values.get("watchdog_id")
        if status != "accepted":
            raise WatchdogInvalidResponseError("Watchdog response status must be 'accepted'.")
        if not isinstance(command_id, str) or not command_id:
            raise WatchdogInvalidResponseError(
                "Watchdog response command_id must be a non-empty string."
            )
        if not isinstance(watchdog_id, str) or not watchdog_id:
            raise WatchdogInvalidResponseError(
                "Watchdog response watchdog_id must be a non-empty string."
            )

        return cls(status=status, command_id=command_id, watchdog_id=watchdog_id)

    def to_dict(self) -> dict[str, str]:
        return {
            "protocol_version": WATCHDOG_PROTOCOL_VERSION,
            "status": self.status,
            "command_id": self.command_id,
            "watchdog_id": self.watchdog_id,
        }


@dataclass(frozen=True, slots=True)
class WatchdogHttpResponse:
    """Transport-neutral HTTP response used by the adapter and its tests."""

    status_code: int
    content_type: str
    body: bytes

    @classmethod
    def json(cls, *, status_code: int, payload: Mapping[str, object]):
        return cls(
            status_code=status_code,
            content_type="application/json",
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        )


class WatchdogTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> WatchdogHttpResponse: ...


class UrllibWatchdogTransport:
    """Small standard-library HTTP transport with bounded response reads."""

    def __init__(self, *, token: str | None = None) -> None:
        self._token = token

    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> WatchdogHttpResponse:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._token:
            headers["X-Agent-Token"] = self._token
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            response = urlopen(request, timeout=timeout_seconds)
        except HTTPError as exc:
            try:
                return self._read_response(exc, max_response_bytes)
            finally:
                exc.close()
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError from exc
            raise ConnectionError from exc

        with response:
            return self._read_response(response, max_response_bytes)

    @staticmethod
    def _read_response(response, max_response_bytes: int) -> WatchdogHttpResponse:
        body = response.read(max_response_bytes + 1)
        if len(body) > max_response_bytes:
            raise WatchdogInvalidResponseError("Watchdog response exceeded the size limit.")
        return WatchdogHttpResponse(
            status_code=response.status,
            content_type=response.headers.get_content_type(),
            body=body,
        )


class HttpWatchdogAdapter:
    """Send commands to one fixed, local Watchdog HTTP endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        token: str | None = None,
        transport: WatchdogTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(
                "Watchdog base URL must be a valid HTTP localhost origin."
            ) from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in _LOCAL_HOSTS
            or (port is not None and not 1 <= port <= 65_535)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Watchdog base URL must be a valid HTTP localhost origin.")
        if timeout_seconds <= 0:
            raise ValueError("Watchdog timeout must be greater than zero.")
        if max_response_bytes <= 0:
            raise ValueError("Watchdog response size limit must be greater than zero.")

        self.command_url = f"{base_url.rstrip('/')}{WATCHDOG_COMMAND_PATH}"
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.transport = transport or UrllibWatchdogTransport(token=token)

    def dispatch(self, envelope: CommandEnvelope) -> CommandAcknowledgement:
        try:
            response = self.transport.post_json(
                url=self.command_url,
                payload=envelope.to_dict(),
                timeout_seconds=self.timeout_seconds,
                max_response_bytes=self.max_response_bytes,
            )
        except WatchdogAdapterError:
            raise
        except TimeoutError as exc:
            raise WatchdogTimeoutError("Watchdog request timed out.") from exc
        except (OSError, URLError) as exc:
            raise WatchdogUnavailableError("Watchdog is unavailable.") from exc

        if response.status_code != 202:
            raise WatchdogUnavailableError("Watchdog did not accept the command.")
        if response.content_type != "application/json":
            raise WatchdogInvalidResponseError("Watchdog response must be application/json.")

        try:
            values = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WatchdogInvalidResponseError("Watchdog returned invalid JSON.") from exc
        if not isinstance(values, Mapping):
            raise WatchdogInvalidResponseError("Watchdog response must be a JSON object.")

        acknowledgement = CommandAcknowledgement.from_dict(values)
        _validate_acknowledgement(acknowledgement, envelope)
        return acknowledgement


class FakeWatchdogAdapter:
    """Deterministic in-memory adapter for backend tests without hardware."""

    def __init__(self) -> None:
        self.messages: list[CommandEnvelope] = []
        self._outcomes: deque[CommandAcknowledgement | WatchdogAdapterError] = deque()

    def queue_response(self, acknowledgement: CommandAcknowledgement) -> None:
        self._outcomes.append(acknowledgement)

    def queue_error(self, error: WatchdogAdapterError) -> None:
        self._outcomes.append(error)

    def dispatch(self, envelope: CommandEnvelope) -> CommandAcknowledgement:
        serialized = envelope.to_dict()
        received = CommandEnvelope.from_dict(serialized)
        self.messages.append(received)

        if self._outcomes:
            outcome = self._outcomes.popleft()
            if isinstance(outcome, WatchdogAdapterError):
                raise outcome
            acknowledgement = outcome
        else:
            acknowledgement = CommandAcknowledgement(
                status="accepted",
                command_id=received.correlation.command_id,
                watchdog_id=received.correlation.watchdog_id,
            )

        acknowledgement = CommandAcknowledgement.from_dict(acknowledgement.to_dict())
        _validate_acknowledgement(acknowledgement, received)
        return acknowledgement


def _validate_acknowledgement(
    acknowledgement: CommandAcknowledgement,
    envelope: CommandEnvelope,
) -> None:
    if acknowledgement.command_id != envelope.correlation.command_id:
        raise WatchdogInvalidResponseError("Watchdog response command_id did not match.")
    if acknowledgement.watchdog_id != envelope.correlation.watchdog_id:
        raise WatchdogInvalidResponseError("Watchdog response watchdog_id did not match.")
