"""Wire-level capture of real northbound ingest traffic.

``RecordingMiddleware`` is a WSGI shim installed *in front of* the Flask app.
It tees the raw request bytes for POSTs to the ingest path into a JSONL file,
then hands the request on unchanged. Two deliberate design choices:

- **Raw bytes, before Flask parses them.** A before_request hook only sees
  requests that already deserialized — it would silently miss the two crash
  cases we most care about recording: a malformed body, and an *old-but-valid*
  watchdog build talking to a new plane (mixed-version fleet). The middleware
  records what actually crossed the socket, warts and all.

- **Zero production-code change.** The middleware wraps ``app.wsgi_app`` only
  in the checkpoint harness; production never installs it. Capture is a
  property of the test rig, not of the server under test.

Each recorded line is one JSON object:

    {"ts": "<iso8601>", "remote_addr": "127.0.0.1",
     "had_token": true, "status": 202, "raw": "<verbatim request body>"}

``raw`` is the verbatim body string — replay feeds it back byte-for-byte so the
fixture cannot drift from what the watchdog really sent.
"""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INGEST_PATH = "/api/v1/internal/events"


class RecordingMiddleware:
    """Tee raw ingest request bodies to a JSONL sink, then pass through."""

    def __init__(
        self,
        wsgi_app: Any,
        sink_path: str | Path,
        *,
        match_path: str = INGEST_PATH,
    ) -> None:
        self._wsgi_app = wsgi_app
        self._sink_path = Path(sink_path)
        self._sink_path.parent.mkdir(parents=True, exist_ok=True)
        self._match_path = match_path
        self._lock = threading.Lock()

    def __call__(self, environ: dict, start_response: Any) -> Any:
        should_record = (
            environ.get("PATH_INFO") == self._match_path
            and environ.get("REQUEST_METHOD") == "POST"
        )
        if not should_record:
            return self._wsgi_app(environ, start_response)

        # Drain wsgi.input so we can both record it and let Flask read it. The
        # stream is single-pass, so we must put a fresh copy back on environ.
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            length = 0
        body = environ["wsgi.input"].read(length) if length > 0 else b""
        environ["wsgi.input"] = io.BytesIO(body)

        # Capture the status the plane returned, so a fixture line records both
        # the stimulus (raw body) and the observed response — a mismatch there
        # is itself a finding (e.g. a valid old-shape body rejected 400).
        captured_status: dict[str, int] = {}

        def _recording_start_response(status: str, headers: list, exc_info=None):
            try:
                captured_status["code"] = int(status.split(" ", 1)[0])
            except (ValueError, IndexError):
                captured_status["code"] = -1
            return start_response(status, headers, exc_info)

        result = self._wsgi_app(environ, _recording_start_response)
        self._record(environ, body, captured_status.get("code", -1))
        return result

    def _record(self, environ: dict, body: bytes, status: int) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(),
            "remote_addr": environ.get("REMOTE_ADDR"),
            "had_token": "HTTP_X_AGENT_TOKEN" in environ,
            "status": status,
            "raw": body.decode("utf-8", errors="replace"),
        }
        with self._lock:
            with self._sink_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")


# ── Replay helpers ────────────────────────────────────────────────────────────


def load_captures(sink_path: str | Path) -> list[dict]:
    """Load every recorded line from a capture file (skips blank lines)."""
    path = Path(sink_path)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def iter_envelopes(captures: list[dict]) -> Iterator[dict]:
    """Yield each capture's parsed envelope body, skipping unparseable ones.

    A body that does not parse as a JSON object is exactly the malformed /
    mixed-version case we recorded on purpose; the replay layer decides what to
    do with it, so this just skips it here rather than raising.
    """
    for cap in captures:
        raw = cap.get("raw", "")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            yield parsed
