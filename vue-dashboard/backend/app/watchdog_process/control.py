"""Authenticated loopback control channel for a standalone watchdog process."""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

import structlog

from app.config import get_config

_log = structlog.get_logger(__name__)

_TOKEN_HEADER = "X-Watchdog-Control-Token"
_MAX_BODY_BYTES = 16 * 1024


class WatchdogControlError(RuntimeError):
    pass


class WatchdogControlAuthenticationError(WatchdogControlError):
    pass


class _Identity(Protocol):
    runtime_id: str
    watchdog_id: str


class _Manifest(Protocol):
    dataflow_id: str
    hash: str


class ControllableWatchdog(Protocol):
    identity: _Identity
    manifest: _Manifest

    def rebind_runtime(self, runtime_id: str) -> None: ...


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        *,
        process: ControllableWatchdog,
        token: str,
        hardware_lease_keys: tuple[str, ...],
        request_stop: Callable[[], None],
        port: int,
    ) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.process = process
        self.token = token
        self.hardware_lease_keys = hardware_lease_keys
        self.request_stop = request_stop
        self.process_started_at = datetime.now(UTC).isoformat()
        self.stop_context: dict[str, str] = {}


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        try:
            is_loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            is_loopback = False
        supplied = self.headers.get(_TOKEN_HEADER, "")
        return is_loopback and hmac.compare_digest(supplied, self.server.token)

    def _send(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def _read_json(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_BODY_BYTES:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid body length"})
            return None
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return None
        if not isinstance(value, dict):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "body must be an object"})
            return None
        return value

    @staticmethod
    def _required_id(payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if isinstance(value, str) and 0 < len(value) <= 128:
            return value
        return None

    @staticmethod
    def _optional_id(payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if isinstance(value, str) and 0 < len(value) <= 128:
            return value
        return None

    def do_GET(self) -> None:
        if self.path != "/probe":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._require_auth():
            return
        identity = self.server.process.identity
        manifest = self.server.process.manifest
        self._send(
            HTTPStatus.OK,
            {
                "runtime_id": identity.runtime_id,
                "watchdog_id": identity.watchdog_id,
                "dataflow_id": manifest.dataflow_id,
                "manifest_hash": manifest.hash,
                "pid": os.getpid(),
                "process_started_at": self.server.process_started_at,
                "hardware_leases": list(self.server.hardware_lease_keys),
            },
        )

    def do_POST(self) -> None:
        if self.path not in {"/adopt", "/stop"}:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._require_auth():
            return
        payload = self._read_json()
        if payload is None:
            return
        recovery_id = self._required_id(payload, "recovery_id")
        if recovery_id is None:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid recovery_id"})
            return
        allowed = (
            {"recovery_id", "runtime_id"}
            if self.path == "/adopt"
            else {"recovery_id", "command_id", "request_id"}
        )
        if set(payload) - allowed:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "unknown correlation field"})
            return
        command_id = self._optional_id(payload, "command_id")
        request_id = self._optional_id(payload, "request_id")
        if ("command_id" in payload and command_id is None) or (
            "request_id" in payload and request_id is None
        ):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid correlation id"})
            return
        if self.path == "/adopt":
            runtime_id = self._required_id(payload, "runtime_id")
            if runtime_id is None:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid runtime_id"})
                return
            self.server.process.rebind_runtime(runtime_id)
            _log.info(
                "watchdog_adoption_confirmed",
                recovery_id=recovery_id,
                runtime_id=runtime_id,
                watchdog_id=self.server.process.identity.watchdog_id,
                dataflow_id=self.server.process.manifest.dataflow_id,
                outcome="adopted",
            )
            self._send(HTTPStatus.OK, {"status": "adopted", "recovery_id": recovery_id})
            return
        _log.info(
            "watchdog_stop_accepted",
            recovery_id=recovery_id,
            shutdown_id=recovery_id,
            command_id=command_id,
            request_id=request_id,
            watchdog_id=self.server.process.identity.watchdog_id,
            runtime_id=self.server.process.identity.runtime_id,
            dataflow_id=self.server.process.manifest.dataflow_id,
            outcome="accepted",
        )
        self.server.stop_context = {
            key: value
            for key, value in {
                "recovery_id": recovery_id,
                "shutdown_id": recovery_id,
                "command_id": command_id,
                "request_id": request_id,
            }.items()
            if value is not None
        }
        self._send(HTTPStatus.ACCEPTED, {"status": "stopping", "recovery_id": recovery_id})
        self.server.request_stop()


class WatchdogControlServer:
    def __init__(
        self,
        *,
        process: ControllableWatchdog,
        token: str,
        hardware_lease_keys: tuple[str, ...],
        request_stop: Callable[[], None],
        port: int = 0,
    ) -> None:
        if not token:
            raise ValueError("watchdog control token is required")
        self._server = _Server(
            process=process,
            token=token,
            hardware_lease_keys=hardware_lease_keys,
            request_stop=request_stop,
            port=port,
        )
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def stop_context(self) -> dict[str, str]:
        return dict(self._server.stop_context)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="watchdog-control",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(
            timeout=get_config().WATCHDOG_CONTROL_SERVER_STOP_TIMEOUT_SECONDS
        )
        self._thread = None


class WatchdogControlClient:
    def __init__(
        self, *, port: int, token: str, timeout_seconds: float | None = None
    ) -> None:
        self._base_url = f"http://127.0.0.1:{int(port)}"
        self._token = token
        self._timeout_seconds = (
            get_config().WATCHDOG_CONTROL_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        )

    def probe(self) -> dict[str, object]:
        return self._request("GET", "/probe")

    def adopt(self, *, new_runtime_id: str, recovery_id: str) -> dict[str, object]:
        return self._request(
            "POST",
            "/adopt",
            {"runtime_id": new_runtime_id, "recovery_id": recovery_id},
        )

    def stop_watchdog(
        self,
        *,
        recovery_id: str,
        command_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, object]:
        payload = {"recovery_id": recovery_id}
        if command_id:
            payload["command_id"] = command_id
        if request_id:
            payload["request_id"] = request_id
        return self._request("POST", "/stop", payload)

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self._base_url + path,
            data=body,
            method=method,
            headers={
                _TOKEN_HEADER: self._token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                value = json.loads(response.read(_MAX_BODY_BYTES + 1))
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.UNAUTHORIZED:
                raise WatchdogControlAuthenticationError(
                    "watchdog control authentication failed"
                ) from exc
            raise WatchdogControlError(f"watchdog control returned HTTP {exc.code}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise WatchdogControlError("watchdog control request failed") from exc
        if not isinstance(value, dict):
            raise WatchdogControlError("watchdog control response must be an object")
        return value


__all__ = [
    "WatchdogControlAuthenticationError",
    "WatchdogControlClient",
    "WatchdogControlError",
    "WatchdogControlServer",
]
