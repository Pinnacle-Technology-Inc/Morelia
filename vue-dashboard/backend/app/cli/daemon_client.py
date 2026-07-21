"""Stdlib HTTP client for north-bound CLI calls to the local daemon."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_config

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RESPONSE_BYTES = 65_536


class DaemonUnavailable(RuntimeError):
    """The local control-plane daemon could not be reached."""


_PROBLEM_CORE_FIELDS = {"type", "title", "status", "detail", "instance", "code", "errors"}


class DaemonError(RuntimeError):
    """The daemon returned a non-success response or invalid data.

    ``code`` and ``extensions`` surface the RFC 9457 problem body's
    machine-readable parts (app/errors.py) beyond title/detail — e.g. a
    SinkLocationExists conflict's ``suggested_location``/``nickname``, which
    a caller needs to retry intelligently rather than just display the error.
    """

    def __init__(
        self,
        title: str,
        detail: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        extensions: dict | None = None,
    ) -> None:
        self.title = title
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.extensions = dict(extensions) if extensions else {}
        super().__init__(f"{title}: {detail}")


@dataclass(frozen=True, slots=True)
class DaemonHttpResponse:
    """Transport-neutral HTTP response for daemon client tests and urllib."""

    status_code: int
    content_type: str
    body: bytes


class DaemonTransport(Protocol):
    def request_json(
        self,
        *,
        method: str,
        url: str,
        payload: Mapping[str, object] | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> DaemonHttpResponse: ...

    def request_lines(
        self,
        *,
        method: str,
        url: str,
        accept: str,
        timeout_seconds: float,
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[str]: ...


class UrllibDaemonTransport:
    """Small standard-library HTTP transport with bounded response reads."""

    def request_json(
        self,
        *,
        method: str,
        url: str,
        payload: Mapping[str, object] | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> DaemonHttpResponse:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=data, headers=headers, method=method)

        try:
            response = urlopen(request, timeout=timeout_seconds)
        except HTTPError as exc:
            try:
                return self._read_response(exc, max_response_bytes)
            finally:
                exc.close()

        with response:
            return self._read_response(response, max_response_bytes)

    def request_lines(
        self,
        *,
        method: str,
        url: str,
        accept: str,
        timeout_seconds: float,
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        request = Request(url, headers={"Accept": accept}, method=method)
        try:
            response = urlopen(request, timeout=timeout_seconds)
        except HTTPError as exc:
            try:
                body = exc.read(DEFAULT_MAX_RESPONSE_BYTES + 1)
                yield from self._error_lines(exc.status, exc.headers.get_content_type(), body)
                return
            finally:
                exc.close()

        with response:
            content_type = response.headers.get_content_type()
            if content_type != accept:
                raise DaemonError(
                    "Invalid daemon response",
                    f"Daemon response must be {accept}.",
                    status_code=response.status,
                )
            while True:
                if should_stop is not None and should_stop():
                    return
                try:
                    raw_line = response.readline()
                except TimeoutError:
                    continue
                if not raw_line:
                    return
                yield raw_line.decode("utf-8").rstrip("\r\n")

    @staticmethod
    def _error_lines(status_code: int, content_type: str, body: bytes) -> Iterator[str]:
        response = DaemonHttpResponse(
            status_code=status_code,
            content_type=content_type,
            body=body,
        )
        values = DaemonClient._parse_json_response(response)
        raise DaemonClient._daemon_error(response, values)

    @staticmethod
    def _read_response(response, max_response_bytes: int) -> DaemonHttpResponse:
        body = response.read(max_response_bytes + 1)
        content_type = response.headers.get_content_type()
        return DaemonHttpResponse(
            status_code=response.status,
            content_type=content_type,
            body=body,
        )


class DaemonClient:
    """Thin JSON client for the local Pinnacle daemon."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        transport: DaemonTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Daemon timeout must be greater than zero.")
        if max_response_bytes <= 0:
            raise ValueError("Daemon response size limit must be greater than zero.")

        self.base_url = (base_url or get_config().CONTROL_PLANE_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.transport = transport or UrllibDaemonTransport()

    def get(self, path: str) -> Any:
        return self._request("GET", path, None)

    def post(self, path: str, payload: Mapping[str, object]) -> Any:
        return self._request("POST", path, payload)

    def put(self, path: str, payload: Mapping[str, object]) -> Any:
        return self._request("PUT", path, payload)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path, None)

    def iter_lines(
        self,
        path: str,
        *,
        accept: str = "application/json",
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        url = self._url(path)
        try:
            yield from self.transport.request_lines(
                method="GET",
                url=url,
                accept=accept,
                timeout_seconds=self.timeout_seconds,
                should_stop=should_stop,
            )
        except URLError as exc:
            raise DaemonUnavailable(f"daemon not running at {self.base_url}") from exc
        except OSError as exc:
            raise DaemonUnavailable(f"daemon not running at {self.base_url}") from exc

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
    ) -> Any:
        url = self._url(path)
        try:
            response = self.transport.request_json(
                method=method,
                url=url,
                payload=payload,
                timeout_seconds=self.timeout_seconds,
                max_response_bytes=self.max_response_bytes,
            )
        except URLError as exc:
            raise DaemonUnavailable(f"daemon not running at {self.base_url}") from exc
        except OSError as exc:
            raise DaemonUnavailable(f"daemon not running at {self.base_url}") from exc

        if len(response.body) > self.max_response_bytes:
            raise DaemonError(
                "Invalid daemon response",
                "Daemon response exceeded the size limit.",
                status_code=response.status_code,
            )

        values = self._parse_json_response(response)
        if response.status_code >= 400:
            if not isinstance(values, Mapping):
                raise DaemonError(
                    "Daemon error",
                    f"Daemon returned HTTP {response.status_code}.",
                    status_code=response.status_code,
                )
            raise self._daemon_error(response, values)
        if not 200 <= response.status_code < 300:
            raise DaemonError(
                "Unexpected daemon response",
                f"Daemon returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        return values

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _parse_json_response(response: DaemonHttpResponse) -> Any:
        if response.content_type not in {"application/json", "application/problem+json"}:
            raise DaemonError(
                "Invalid daemon response",
                "Daemon response must be JSON.",
                status_code=response.status_code,
            )
        if not response.body:
            return {}
        try:
            values = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DaemonError(
                "Invalid daemon response",
                "Daemon returned invalid JSON.",
                status_code=response.status_code,
            ) from exc
        if not isinstance(values, dict | list):
            raise DaemonError(
                "Invalid daemon response",
                "Daemon response must be a JSON object or array.",
                status_code=response.status_code,
            )
        return values

    @staticmethod
    def _daemon_error(
        response: DaemonHttpResponse,
        values: Mapping[str, object],
    ) -> DaemonError:
        title = values.get("title")
        detail = values.get("detail")
        if not isinstance(title, str) or not title:
            title = "Daemon error"
        if not isinstance(detail, str) or not detail:
            detail = f"Daemon returned HTTP {response.status_code}."
        code = values.get("code")
        extensions = {k: v for k, v in values.items() if k not in _PROBLEM_CORE_FIELDS}
        return DaemonError(
            title,
            detail,
            status_code=response.status_code,
            code=code if isinstance(code, str) else None,
            extensions=extensions,
        )


__all__ = [
    "DaemonClient",
    "DaemonError",
    "DaemonHttpResponse",
    "DaemonTransport",
    "DaemonUnavailable",
    "UrllibDaemonTransport",
]
