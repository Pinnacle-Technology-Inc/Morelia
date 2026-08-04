import json
from collections.abc import Mapping
from urllib.error import URLError

import pytest

from app.cli.daemon_client import (
    DaemonClient,
    DaemonError,
    DaemonHttpResponse,
    DaemonUnavailable,
    UrllibDaemonTransport,
)


class FakeTransport:
    def __init__(
        self,
        response: DaemonHttpResponse | Exception,
        *,
        lines: list[str] | Exception | None = None,
    ) -> None:
        self.response = response
        self.lines = lines
        self.calls: list[dict[str, object]] = []

    def request_json(
        self,
        *,
        method: str,
        url: str,
        payload: Mapping[str, object] | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> DaemonHttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def request_lines(
        self,
        *,
        method: str,
        url: str,
        accept: str,
        timeout_seconds: float,
        should_stop=None,
    ):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "accept": accept,
                "timeout_seconds": timeout_seconds,
            }
        )
        if isinstance(self.lines, Exception):
            raise self.lines
        yield from self.lines or []


def json_response(status_code: int, payload: Mapping[str, object]) -> DaemonHttpResponse:
    return DaemonHttpResponse(
        status_code=status_code,
        content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )


def test_get_parses_json_response() -> None:
    transport = FakeTransport(json_response(200, {"ok": True}))
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    result = client.get("/health")

    assert result == {"ok": True}
    assert transport.calls == [
        {
            "method": "GET",
            "url": "http://127.0.0.1:5000/health",
            "payload": None,
            "timeout_seconds": 30.0,
            "max_response_bytes": 65_536,
        }
    ]


def test_constructor_uses_configured_control_plane_base_url(monkeypatch) -> None:
    from app.cli import daemon_client

    class Config:
        CONTROL_PLANE_BASE_URL = "http://127.0.0.1:5999"

    transport = FakeTransport(json_response(200, {"ok": True}))
    monkeypatch.setattr(daemon_client, "get_config", lambda: Config)

    result = DaemonClient(transport=transport).get("/health")

    assert result == {"ok": True}
    assert transport.calls[0]["url"] == "http://127.0.0.1:5999/health"


def test_post_sends_payload_and_parses_json_response() -> None:
    transport = FakeTransport(json_response(202, {"operation_id": "op-1"}))
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    result = client.post("/api/v1/sessions/1/start", {"force": True})

    assert result == {"operation_id": "op-1"}
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["payload"] == {"force": True}


def test_get_parses_json_array_response() -> None:
    response = DaemonHttpResponse(
        status_code=200,
        content_type="application/json",
        body=json.dumps([{"runtime_id": "rt-active"}]).encode("utf-8"),
    )
    transport = FakeTransport(response)
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    result = client.get("/api/v1/runtimes/")

    assert result == [{"runtime_id": "rt-active"}]


def test_delete_parses_json_response() -> None:
    transport = FakeTransport(json_response(200, {"deleted": True}))
    client = DaemonClient(base_url="http://127.0.0.1:5000/", transport=transport)

    result = client.delete("api/v1/devices/camera-1")

    assert result == {"deleted": True}
    assert transport.calls[0]["method"] == "DELETE"
    assert transport.calls[0]["url"] == "http://127.0.0.1:5000/api/v1/devices/camera-1"


def test_iter_lines_streams_text_event_stream_lines() -> None:
    transport = FakeTransport(json_response(200, {"unused": True}), lines=["id: 1", ""])
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    result = list(client.iter_lines("/api/v1/sessions/1/events", accept="text/event-stream"))

    assert result == ["id: 1", ""]
    assert transport.calls == [
        {
            "method": "GET",
            "url": "http://127.0.0.1:5000/api/v1/sessions/1/events",
            "accept": "text/event-stream",
            "timeout_seconds": 30.0,
        }
    ]


def test_cancellable_stream_uses_daemon_timeout_instead_of_short_socket_poll(
    monkeypatch,
) -> None:
    from app.cli import daemon_client

    timeouts: list[float] = []

    class Headers:
        @staticmethod
        def get_content_type() -> str:
            return "text/event-stream"

    class EmptyStreamResponse:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        @staticmethod
        def readline() -> bytes:
            return b""

    def fake_urlopen(request, timeout):  # noqa: ANN001 - matches urllib patch point
        timeouts.append(timeout)
        return EmptyStreamResponse()

    monkeypatch.setattr(daemon_client, "urlopen", fake_urlopen)
    client = DaemonClient(
        base_url="http://127.0.0.1:5000",
        timeout_seconds=12.0,
        transport=UrllibDaemonTransport(),
    )

    result = list(
        client.iter_lines(
            "/api/v1/sessions/1/events",
            accept="text/event-stream",
            should_stop=lambda: False,
        )
    )

    assert result == []
    assert timeouts == [12.0]


def test_connection_refusal_raises_daemon_unavailable() -> None:
    transport = FakeTransport(URLError(ConnectionRefusedError("refused")))
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    with pytest.raises(DaemonUnavailable) as exc_info:
        client.get("/health")

    assert str(exc_info.value) == "daemon not running at http://127.0.0.1:5000"


def test_iter_lines_connection_refusal_raises_daemon_unavailable() -> None:
    transport = FakeTransport(
        json_response(200, {"unused": True}),
        lines=URLError(ConnectionRefusedError("refused")),
    )
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    with pytest.raises(DaemonUnavailable) as exc_info:
        list(client.iter_lines("/api/v1/sessions/1/events", accept="text/event-stream"))

    assert str(exc_info.value) == "daemon not running at http://127.0.0.1:5000"


def test_problem_json_error_raises_daemon_error_with_title_and_detail() -> None:
    transport = FakeTransport(
        DaemonHttpResponse(
            status_code=409,
            content_type="application/problem+json",
            body=json.dumps(
                {
                    "title": "Conflict",
                    "detail": "Session already has a command in flight.",
                }
            ).encode("utf-8"),
        )
    )
    client = DaemonClient(base_url="http://127.0.0.1:5000", transport=transport)

    with pytest.raises(DaemonError) as exc_info:
        client.post("/api/v1/sessions/1/start", {})

    assert exc_info.value.title == "Conflict"
    assert exc_info.value.detail == "Session already has a command in flight."
    assert str(exc_info.value) == "Conflict: Session already has a command in flight."


def test_response_body_is_bounded() -> None:
    body = json.dumps({"ok": True}).encode("utf-8")
    transport = FakeTransport(
        DaemonHttpResponse(status_code=200, content_type="application/json", body=body)
    )
    client = DaemonClient(
        base_url="http://127.0.0.1:5000",
        max_response_bytes=len(body) - 1,
        transport=transport,
    )

    with pytest.raises(DaemonError) as exc_info:
        client.get("/health")

    assert exc_info.value.title == "Invalid daemon response"
    assert exc_info.value.detail == "Daemon response exceeded the size limit."
