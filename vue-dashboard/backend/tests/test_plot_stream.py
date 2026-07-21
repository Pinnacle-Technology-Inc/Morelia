"""Contract tests for the bounded live Plot data plane (packet 27).

Covers the three acceptance criteria plus the SINK-10 reconstruction fix:

* AC1 — an authorized subscription receives ordered, schema-versioned batches
  with rate/timestamp metadata for the selected sink only.
* AC2 — slow/disconnected consumers cause bounded, counted drops and clean
  teardown, never source/sibling backpressure or unbounded memory.
* AC3 — unauthorized or cross-session/cross-sink subscriptions are rejected, and
  payloads carry no credentials or non-Plot data.

Testing strategy mirrors ``test_events_sse.py``: the SSE generator is driven
directly (a live stream is infinite and would hang the Flask test client), while
the reject paths (which ``abort`` before streaming) go through the test client.
"""

from __future__ import annotations

import json
import types

import pytest

from app.api.plot_stream import (
    PLOT_SCHEMA_VERSION,
    InProcessPlotTransport,
    PlotBroker,
    _plot_sse_generator,
    mint_plot_token,
)
from app.domain.enums import SinkType
from app.output.plot_sink import (
    DEFAULT_MAX_DISPLAY_RATE,
    ManagedPlotSink,
    PlotSinkError,
)
from app.runtime_child.sink_factory import RuntimeContext, build_sink


# ── helpers ──────────────────────────────────────────────────────────────────


class _CapturingTransport:
    """A plot transport that records every published batch (in-process fake)."""

    def __init__(self) -> None:
        self.batches: list[dict] = []

    def publish(self, batch: dict) -> int:
        self.batches.append(batch)
        return 1


class _BrokenTransport:
    """A transport that always fails — models a disconnected/broken consumer."""

    def publish(self, batch: dict) -> int:
        raise ConnectionError("browser gone")


def _read_n_plot_frames(gen, n: int) -> list[dict]:
    """Consume up to n non-heartbeat frames, parse the data JSON, then close."""
    frames: list[dict] = []
    try:
        for frame in gen:
            if frame.startswith(":"):
                continue
            data_line = next(
                line for line in frame.split("\n") if line.startswith("data: ")
            )
            frames.append(json.loads(data_line[len("data: ") :]))
            if len(frames) >= n:
                break
    finally:
        gen.close()
    return frames


def _plot_sink_config(sink_id: str = "browser-plot", **params) -> types.SimpleNamespace:
    return types.SimpleNamespace(type=SinkType.PLOT, sink_id=sink_id, parameters=params)


# ── AC1: ordered, schema-versioned batches with metadata, selected sink only ──


def test_generator_yields_ordered_schema_versioned_batches():
    broker = PlotBroker()
    sub = broker.subscribe(1, "browser-plot", maxlen=64)
    for seq in range(3):
        broker.publish(1, "browser-plot", {"seq": seq, "schema": PLOT_SCHEMA_VERSION})

    gen = _plot_sse_generator(sub, poll_interval=0.0, heartbeat_interval=9999.0)
    frames = _read_n_plot_frames(gen, 3)

    assert [f["seq"] for f in frames] == [0, 1, 2]
    assert all(f["schema"] == PLOT_SCHEMA_VERSION for f in frames)


def test_batch_carries_rate_timestamp_and_channel_metadata():
    transport = _CapturingTransport()
    sink = ManagedPlotSink(
        dataflow_id="df1",
        device_id="dev1",
        sink_id="browser-plot",
        session_id=7,
        chunk_samples=2,
        max_display_rate=50.0,
        channel_names=["ch0", "ch1"],
        transport=transport,
    ).open()

    sink.write_row({"ch0": 1.0, "ch1": 2.0})
    sink.write_row({"ch0": 3.0, "ch1": 4.0})

    assert len(transport.batches) == 1
    batch = transport.batches[0]
    assert batch["schema"] == PLOT_SCHEMA_VERSION
    assert batch["session_id"] == 7
    assert batch["sink_id"] == "browser-plot"
    assert batch["sample_rate"] == 50.0
    assert batch["channels"] == ["ch0", "ch1"]
    assert batch["samples"] == [[1.0, 2.0], [3.0, 4.0]]
    assert isinstance(batch["timestamp"], float)


def test_cursor_filters_already_seen_batches():
    broker = PlotBroker()
    sub = broker.subscribe(1, "p", maxlen=64)
    for seq in range(3):
        broker.publish(1, "p", {"seq": seq})

    gen = _plot_sse_generator(sub, after_seq=0, poll_interval=0.0, heartbeat_interval=9999.0)
    frames = _read_n_plot_frames(gen, 2)

    # seq 0 (<= cursor) is skipped; only 1 and 2 are delivered.
    assert [f["seq"] for f in frames] == [1, 2]


def test_broker_delivers_only_to_matching_session_and_sink():
    broker = PlotBroker()
    mine = broker.subscribe(1, "a", maxlen=8)
    other_sink = broker.subscribe(1, "b", maxlen=8)
    other_session = broker.subscribe(2, "a", maxlen=8)

    broker.publish(1, "a", {"seq": 0})

    assert mine.pending() == 1
    assert other_sink.pending() == 0
    assert other_session.pending() == 0


# ── AC2: bounded drops, no unbounded memory, clean teardown ───────────────────


def test_subscriber_buffer_is_bounded_and_counts_drops():
    broker = PlotBroker()
    sub = broker.subscribe(1, "p", maxlen=3)

    for seq in range(10):
        broker.publish(1, "p", {"seq": seq})

    # Never exceeds the bound; the 7 oldest were dropped with an explicit count.
    assert sub.pending() == 3
    assert sub.dropped == 7
    # The freshest batches survived (drop-oldest).
    assert [b["seq"] for b in sub.drain()] == [7, 8, 9]


def test_frame_reports_subscriber_drop_count():
    broker = PlotBroker()
    sub = broker.subscribe(1, "p", maxlen=2)
    for seq in range(5):  # overflow: 3 dropped, 2 retained
        broker.publish(1, "p", {"seq": seq})

    gen = _plot_sse_generator(sub, poll_interval=0.0, heartbeat_interval=9999.0)
    frames = _read_n_plot_frames(gen, 1)

    assert frames[0]["dropped"] == 3


def test_generator_close_unsubscribes_from_broker():
    broker = PlotBroker()
    sub = broker.subscribe(1, "p", maxlen=8)
    assert broker.subscriber_count(1, "p") == 1

    gen = _plot_sse_generator(sub, poll_interval=0.0, heartbeat_interval=0.0)
    next(gen)  # start it (a heartbeat, since no data)
    gen.close()  # simulate browser disconnect

    assert broker.subscriber_count(1, "p") == 0


def test_disconnected_transport_drops_without_raising():
    sink = ManagedPlotSink(
        dataflow_id="df",
        sink_id="p",
        chunk_samples=2,
        max_display_rate=1000.0,
        channel_names=["ch0"],
        transport=_BrokenTransport(),
    ).open()

    sink.write_row({"ch0": 1.0})
    sink.write_row({"ch0": 2.0})  # completes a chunk -> publish fails -> drop

    assert sink.dropped_batches == 1
    assert sink.emitted_batches == 0
    assert sink.is_degraded is True
    assert sink.presentation_connected is False


def test_no_transport_runs_in_bounded_drop_mode():
    sink = ManagedPlotSink(
        dataflow_id="df", sink_id="p", chunk_samples=1, max_display_rate=1000.0
    ).open()

    sink.write_row({"ch0": 1.0})
    sink.write_row({"ch0": 2.0})

    assert sink.dropped_batches == 2
    assert sink.pending_count() == 0  # buffer always cleared -> bounded memory


def test_rate_throttle_decimates_bursts():
    transport = _CapturingTransport()
    # A tiny display rate makes the min emit interval huge, so only the first
    # chunk publishes and subsequent immediate chunks are decimated (dropped).
    sink = ManagedPlotSink(
        dataflow_id="df",
        sink_id="p",
        chunk_samples=1,
        max_display_rate=0.0001,
        channel_names=["ch0"],
        transport=transport,
    ).open()

    for value in range(5):
        sink.write_row({"ch0": float(value)})

    assert sink.emitted_batches == 1
    assert sink.dropped_batches == 4
    assert len(transport.batches) == 1


# ── AC3: auth — unauthorized / cross-scope rejected, no secrets in payload ────


def test_missing_token_is_unauthorized(client):
    resp = client.get("/api/v1/sessions/1/plot/browser-plot/stream")
    assert resp.status_code == 401


def test_tampered_token_is_unauthorized(client):
    resp = client.get("/api/v1/sessions/1/plot/browser-plot/stream?token=not-a-real-token")
    assert resp.status_code == 401


def test_cross_session_token_is_forbidden(app, client):
    with app.app_context():
        token = mint_plot_token(1, "browser-plot")
    # Same token, different session in the URL.
    resp = client.get(f"/api/v1/sessions/2/plot/browser-plot/stream?token={token}")
    assert resp.status_code == 403


def test_cross_sink_token_is_forbidden(app, client):
    with app.app_context():
        token = mint_plot_token(1, "browser-plot")
    resp = client.get(f"/api/v1/sessions/1/plot/other-sink/stream?token={token}")
    assert resp.status_code == 403


def test_valid_token_opens_event_stream(app):
    from app.api.plot_stream import stream_plot

    with app.app_context():
        token = mint_plot_token(3, "browser-plot")
    url = f"/api/v1/sessions/3/plot/browser-plot/stream?token={token}"
    with app.test_request_context(url):
        resp = stream_plot(3, "browser-plot")
        assert "text/event-stream" in resp.content_type
        resp.response.close()  # do not consume the infinite body


def test_bearer_header_is_accepted(app):
    from app.api.plot_stream import stream_plot

    with app.app_context():
        token = mint_plot_token(3, "browser-plot")
    url = "/api/v1/sessions/3/plot/browser-plot/stream"
    with app.test_request_context(url, headers={"Authorization": f"Bearer {token}"}):
        resp = stream_plot(3, "browser-plot")
        assert "text/event-stream" in resp.content_type
        resp.response.close()


def test_get_dict_carries_no_credential_keys():
    sink = ManagedPlotSink(dataflow_id="df", sink_id="p", max_display_rate=5.0)
    keys = set(sink.get_dict())
    # Plot has no secret; assert none of the credential-ish keys ever appear.
    assert not (keys & {"token", "api_token", "api_token_env", "secret", "password"})


# ── SINK-10: reconstruction preserves the configured display rate ─────────────


def test_get_dict_preserves_non_default_display_rate():
    sink = ManagedPlotSink(
        dataflow_id="df", sink_id="p", max_display_rate=7.5, chunk_samples=42
    )
    reconstructed = sink.get_dict()
    assert reconstructed["max_display_rate"] == 7.5  # NOT the default
    assert reconstructed["max_display_rate"] != DEFAULT_MAX_DISPLAY_RATE
    assert reconstructed["chunk_samples"] == 42

    # Round-trips: reconstructing from get_dict() keeps the configured rate.
    twin = ManagedPlotSink(**reconstructed)
    assert twin.get_dict()["max_display_rate"] == 7.5


def test_default_display_rate_when_unset():
    sink = ManagedPlotSink(dataflow_id="df", sink_id="p")
    assert sink.get_dict()["max_display_rate"] == DEFAULT_MAX_DISPLAY_RATE


def test_invalid_config_is_rejected():
    with pytest.raises(PlotSinkError):
        ManagedPlotSink(dataflow_id="df", sink_id="p", chunk_samples=0)
    with pytest.raises(PlotSinkError):
        ManagedPlotSink(dataflow_id="df", sink_id="p", max_display_rate=0)


# ── factory branch: descriptor-only, deferred open, no dependency raise ───────


def test_factory_builds_deferred_plot_descriptor():
    ctx = RuntimeContext(dataflow_id="df", device_id="dev", session_id=5)
    sink_config = _plot_sink_config(chunk_samples=64, max_display_rate=12.0)

    sink = build_sink(sink_config, pod=None, runtime_context=ctx)

    assert isinstance(sink, ManagedPlotSink)
    assert sink.opened is False  # SINK-21: construction opens nothing
    assert sink.get_dict()["max_display_rate"] == 12.0
    assert sink.sink_id == "browser-plot"


def test_factory_passes_transport_through_to_worker_open():
    transport = _CapturingTransport()
    ctx = RuntimeContext(
        dataflow_id="df", device_id="dev", session_id=5, plot_transport=transport
    )
    sink_config = _plot_sink_config(chunk_samples=1, max_display_rate=1000.0)

    sink = build_sink(sink_config, pod=None, runtime_context=ctx)
    sink.open()
    sink.write_row({"ch0": 1.0})

    assert len(transport.batches) == 1


def test_in_process_transport_bridges_sink_to_broker():
    broker = PlotBroker()
    sub = broker.subscribe(9, "browser-plot", maxlen=8)
    transport = InProcessPlotTransport(broker, session_id=9, sink_id="browser-plot")

    sink = ManagedPlotSink(
        dataflow_id="df",
        sink_id="browser-plot",
        session_id=9,
        chunk_samples=1,
        max_display_rate=1000.0,
        channel_names=["ch0"],
        transport=transport,
    ).open()
    sink.write_row({"ch0": 42.0})

    delivered = sub.drain()
    assert len(delivered) == 1
    assert delivered[0]["samples"] == [[42.0]]
