"""Authenticated live Plot data plane — GET /api/v1/sessions/<id>/plot/<sink_id>/stream.

This is the backend half of the browser Plot contract (gaps SINK-09/SINK-10,
design doc section 6 "Plot"): a bounded, worker->watchdog->backend->browser
sample path that is *live presentation*, never durable recording. A slow or
disconnected browser must never stall acquisition or grow memory without bound —
it is a *dropped consumer*, not an error.

Data plane shape
----------------
* :class:`PlotBroker` — an in-process fan-out registry keyed by
  ``(session_id, sink_id)``. Each browser subscription gets its own bounded
  buffer (:class:`_PlotSubscriber`); the producer never blocks on a slow
  subscriber, and overflow drops the *oldest* plot-only batch with an explicit
  per-subscriber counter (bounded memory, explicit loss). The broker only ever
  fans a batch to subscribers of the *same* ``(session_id, sink_id)`` key, so a
  subscription can never observe another session's or another sink's samples.
* :class:`InProcessPlotTransport` — the sink-facing publish handle. The managed
  plot sink (:class:`~app.output.plot_sink.ManagedPlotSink`) calls
  ``transport.publish(batch)``; in-process this forwards to the broker. Across a
  real worker/backend process boundary the parent wires a picklable transport
  *factory* that reconnects to this broker's publish path (the sink resolves its
  transport worker-side at ``open()``); nothing here requires a live, unpicklable
  handle to cross that boundary.

Authorization
-------------
The browser subscription is authenticated with a signed, session/sink-scoped
token (itsdangerous over the app ``SECRET_KEY``). :func:`mint_plot_token` binds a
token to one ``(session_id, sink_id)`` pair; a token minted for a different
session or sink is rejected (403) and a missing/tampered/expired token is
rejected (401) *before* any stream is opened. The token is opaque and carries no
credential; batch payloads carry only plot samples and presentation metadata,
never secrets or non-Plot sink data.

Frozen wire contract (packet 28 — Vue live plot)
------------------------------------------------
* URL:   ``GET /api/v1/sessions/<int:session_id>/plot/<sink_id>/stream``
* Auth:  ``?token=<t>`` query param, or ``Authorization: Bearer <t>`` header.
* Cursor: ``?after=<seq>`` query or ``Last-Event-ID`` reconnect header — only
  batches with a producer ``seq`` greater than the cursor are delivered.
* Frames (SSE): ``id: <seq>`` / ``event: plot`` / ``data: <json>`` / blank line,
  with ``: heartbeat`` comment frames when idle.
* Batch JSON (``PLOT_SCHEMA_VERSION == "plot.samples.v1"``)::

      {"schema": "plot.samples.v1", "session_id": <int>, "sink_id": <str>,
       "device_id": <str|null>, "seq": <int>, "timestamp": <float>,
       "sample_rate": <float>, "channels": [<str>...],
       "samples": [[<num>...]...], "dropped": <int>}

  ``seq`` is the producer's monotonic batch counter (gap detection); ``dropped``
  is this subscriber's cumulative drop count (its own lag/backpressure state).

Registered directly on the Flask app (not the OpenAPI ``api`` object) because the
response type is ``text/event-stream``, outside the JSON-centric OpenAPI spec.
"""

from __future__ import annotations

import collections
import json
import threading
import time
from collections.abc import Generator
from typing import Any

from flask import Blueprint, Response, current_app, request, stream_with_context
from flask_smorest import abort
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

__all__ = [
    "PLOT_SCHEMA_VERSION",
    "InProcessPlotTransport",
    "PlotBroker",
    "blp",
    "mint_plot_token",
]

blp = Blueprint("plot_stream", __name__, url_prefix="/api/v1/sessions")

#: Wire schema version stamped on every batch payload (frozen for packet 28).
PLOT_SCHEMA_VERSION = "plot.samples.v1"

#: itsdangerous salt namespacing the plot-subscription token signature.
_TOKEN_SALT = "plot-stream"

# Bounds/timeouts — all read from config with a safe default so this packet
# needs no config.py change; a deployment can still tune them.
_DEFAULT_MAX_QUEUE = 256  # batches buffered per browser subscription
_DEFAULT_POLL_INTERVAL = 0.5  # seconds between drains when idle
_DEFAULT_HEARTBEAT_INTERVAL = 15.0  # seconds between keep-alive comments
_DEFAULT_TOKEN_MAX_AGE = 3600  # seconds a subscription token stays valid


# ---------------------------------------------------------------------------
# Bounded in-process broker
# ---------------------------------------------------------------------------


class _PlotSubscriber:
    """One browser subscription's bounded, drop-oldest buffer.

    Thread-safe: the producer (a plot transport, possibly on another thread)
    calls :meth:`offer`; the SSE generator calls :meth:`drain`. The buffer never
    holds more than ``maxlen`` batches — on overflow the oldest plot-only batch is
    discarded and :attr:`dropped` is incremented, so a slow consumer loses old
    frames (explicit, bounded) rather than growing memory or back-pressuring the
    producer.
    """

    def __init__(self, broker: PlotBroker, key: tuple[int, str], maxlen: int) -> None:
        self._broker = broker
        self._key = key
        self._maxlen = max(1, int(maxlen))
        self._buf: collections.deque[dict[str, Any]] = collections.deque()
        self._lock = threading.Lock()
        self.dropped = 0
        self._closed = False

    @property
    def key(self) -> tuple[int, str]:
        return self._key

    def offer(self, batch: dict[str, Any]) -> None:
        """Producer side: enqueue a batch, dropping the oldest if full."""
        with self._lock:
            if self._closed:
                return
            if len(self._buf) >= self._maxlen:
                self._buf.popleft()
                self.dropped += 1
            self._buf.append(batch)

    def drain(self) -> list[dict[str, Any]]:
        """Consumer side: remove and return all buffered batches in order."""
        with self._lock:
            if not self._buf:
                return []
            items = list(self._buf)
            self._buf.clear()
            return items

    def pending(self) -> int:
        with self._lock:
            return len(self._buf)

    def close(self) -> None:
        """Detach from the broker; idempotent. Called on client disconnect."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._buf.clear()
        self._broker._remove(self)


class PlotBroker:
    """Fan-out registry of live plot subscriptions, keyed by session+sink.

    A batch published for ``(session_id, sink_id)`` reaches only the subscribers
    of that exact key — the structural guarantee that a subscription can never see
    another session's or another sink's samples. Publishing is non-blocking: each
    subscriber owns its bounded buffer and absorbs backpressure by dropping its own
    oldest batches, so one slow browser cannot slow the producer or its siblings.
    """

    def __init__(self, default_maxlen: int = _DEFAULT_MAX_QUEUE) -> None:
        self._subs: dict[tuple[int, str], set[_PlotSubscriber]] = {}
        self._lock = threading.Lock()
        self._default_maxlen = max(1, int(default_maxlen))

    def subscribe(
        self, session_id: int, sink_id: str, maxlen: int | None = None
    ) -> _PlotSubscriber:
        key = (int(session_id), str(sink_id))
        sub = _PlotSubscriber(self, key, maxlen or self._default_maxlen)
        with self._lock:
            self._subs.setdefault(key, set()).add(sub)
        return sub

    def publish(self, session_id: int, sink_id: str, batch: dict[str, Any]) -> int:
        """Deliver a batch to every subscriber of this key; return their count.

        Never raises for a missing key (no consumer connected == a no-op drop) and
        never blocks (each subscriber's :meth:`_PlotSubscriber.offer` is bounded).
        """
        key = (int(session_id), str(sink_id))
        with self._lock:
            targets = list(self._subs.get(key, ()))
        for sub in targets:
            sub.offer(batch)
        return len(targets)

    def subscriber_count(self, session_id: int, sink_id: str) -> int:
        key = (int(session_id), str(sink_id))
        with self._lock:
            return len(self._subs.get(key, ()))

    def _remove(self, sub: _PlotSubscriber) -> None:
        with self._lock:
            group = self._subs.get(sub.key)
            if group is None:
                return
            group.discard(sub)
            if not group:
                del self._subs[sub.key]


class InProcessPlotTransport:
    """Sink-facing publish handle bridging a managed plot sink to a broker.

    The managed plot sink calls ``publish(batch)``; this forwards to the broker's
    keyed fan-out. This is the in-process transport (tests, single-process runs).
    Across a real worker/backend process boundary the parent injects a picklable
    transport *factory* that reconstructs an equivalent publish path worker-side —
    this class deliberately stays a thin, duck-typed ``publish`` provider so the
    sink never depends on the broker type.
    """

    def __init__(self, broker: PlotBroker, session_id: int, sink_id: str) -> None:
        self._broker = broker
        self._session_id = int(session_id)
        self._sink_id = str(sink_id)

    def publish(self, batch: dict[str, Any]) -> int:
        return self._broker.publish(self._session_id, self._sink_id, batch)


# ---------------------------------------------------------------------------
# Subscription token (session/sink-scoped, signed, credential-free)
# ---------------------------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_TOKEN_SALT)


def mint_plot_token(session_id: int, sink_id: str) -> str:
    """Mint a signed token authorizing a live plot subscription to one sink.

    The token binds exactly one ``(session_id, sink_id)`` pair and carries no
    credential; it is validated by :func:`_authorize` before a stream opens.
    """
    return _serializer().dumps({"session_id": int(session_id), "sink_id": str(sink_id)})


def _bearer_token() -> str | None:
    """Return the token from ``?token=`` or an ``Authorization: Bearer`` header."""
    query = request.args.get("token")
    if query:
        return query
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :].strip() or None
    return None


def _authorize(session_id: int, sink_id: str) -> None:
    """Reject an unauthorized or cross-scope subscription before streaming.

    401 for a missing/tampered/expired token; 403 for a validly signed token
    minted for a *different* session or sink (cross-session/cross-sink attempt).
    """
    token = _bearer_token()
    if not token:
        abort(401, message="A plot subscription token is required.")

    max_age = int(current_app.config.get("PLOT_STREAM_TOKEN_MAX_AGE", _DEFAULT_TOKEN_MAX_AGE))
    try:
        claims = _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        abort(401, message="Plot subscription token has expired.")
    except BadSignature:
        abort(401, message="Plot subscription token is invalid.")

    if not isinstance(claims, dict):
        abort(401, message="Plot subscription token is malformed.")
    if int(claims.get("session_id", -1)) != int(session_id) or str(
        claims.get("sink_id")
    ) != str(sink_id):
        abort(403, message="Token is not authorized for this session/sink.")


# ---------------------------------------------------------------------------
# SSE generator + route
# ---------------------------------------------------------------------------


def _plot_sse_generator(
    subscriber: _PlotSubscriber,
    *,
    after_seq: int = -1,
    poll_interval: float,
    heartbeat_interval: float,
) -> Generator[str, None, None]:
    """Yield SSE frames from one bounded subscription.

    Exposed at module level so tests can drive it directly (a live SSE stream is
    infinite; the Flask test client would hang consuming it). Cleans up the
    subscription on client disconnect (``GeneratorExit``) via ``finally`` so a
    dropped browser releases its broker slot with no leak.
    """
    last_hb = time.monotonic()
    try:
        while True:
            for batch in subscriber.drain():
                if int(batch.get("seq", 0)) <= after_seq:
                    continue
                payload = dict(batch)
                # The subscriber's own lag/backpressure state travels with the
                # frame — a browser can see how many old batches it missed.
                payload["dropped"] = subscriber.dropped
                yield (
                    f"id: {batch.get('seq', 0)}\n"
                    f"event: plot\n"
                    f"data: {json.dumps(payload)}\n\n"
                )

            now = time.monotonic()
            if now - last_hb >= heartbeat_interval:
                yield ": heartbeat\n\n"
                last_hb = now

            if poll_interval:
                time.sleep(poll_interval)
    except GeneratorExit:
        pass  # client disconnected — exit cleanly
    finally:
        subscriber.close()


def _request_after_seq() -> int:
    """Resolve the reconnect cursor from ``?after=`` or ``Last-Event-ID``.

    Returns ``-1`` when no valid cursor is supplied — a fresh subscriber then
    receives every batch (including ``seq 0``); a reconnect with cursor ``N``
    receives only batches with ``seq > N``.
    """
    for raw in (request.args.get("after"), request.headers.get("Last-Event-ID")):
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return -1


def get_plot_broker() -> PlotBroker:
    """Return the app's shared broker, creating it lazily if absent.

    Stored on ``app.extensions`` so each app instance (each test) owns an
    isolated broker with no cross-instance state bleed.
    """
    broker = current_app.extensions.get("plot_broker")
    if broker is None:
        broker = PlotBroker()
        current_app.extensions["plot_broker"] = broker
    return broker


@blp.route("/<int:session_id>/plot/<sink_id>/stream")
def stream_plot(session_id: int, sink_id: str):
    """Stream bounded live plot batches for one authorized session/sink as SSE."""
    _authorize(session_id, sink_id)

    broker = get_plot_broker()
    maxlen = int(current_app.config.get("PLOT_STREAM_MAX_QUEUE", _DEFAULT_MAX_QUEUE))
    poll_interval = float(
        current_app.config.get(
            "PLOT_STREAM_POLL_INTERVAL",
            current_app.config.get("SSE_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL),
        )
    )
    heartbeat_interval = float(
        current_app.config.get(
            "PLOT_STREAM_HEARTBEAT_INTERVAL",
            current_app.config.get("SSE_HEARTBEAT_INTERVAL", _DEFAULT_HEARTBEAT_INTERVAL),
        )
    )

    subscriber = broker.subscribe(session_id, sink_id, maxlen=maxlen)
    return Response(
        stream_with_context(
            _plot_sse_generator(
                subscriber,
                after_seq=_request_after_seq(),
                poll_interval=poll_interval,
                heartbeat_interval=heartbeat_interval,
            )
        ),
        content_type="text/event-stream",
    )
