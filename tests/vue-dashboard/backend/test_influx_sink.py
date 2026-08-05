"""Packet 24 — managed Influx sink: secret isolation + bounded delivery replay.

These tests never touch a live InfluxDB. The destination is a controllable
in-memory ``FakeInfluxClient`` injected via ``client_factory``, and the delivery
buffer is a real (Flask-less) ``SinkDeliveryOutbox`` on ``tmp_path``. They prove
the three packet-24 acceptance criteria plus the SINK-07 credential invariants
and the factory wiring.
"""

from __future__ import annotations

import pytest

from app.domain.enums import SinkType
from app.output.influx_sink import (
    InfluxCredentialError,
    InfluxUnavailableError,
    ManagedInfluxSink,
    redact_mapping,
)
from app.output import influx_sink as influx_module
from app.runtime_child.sink_factory import RuntimeContext, build_sink
from app.runtime_host.manifest import SinkConfig
from app.watchdog_process.sink_delivery_outbox import SinkDeliveryOutbox

_ENV = "PINNACLE_INFLUX_TOKEN"
_SECRET = "super-secret-token-value"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeInfluxClient:
    """In-memory destination. ``up`` toggles a simulated outage."""

    def __init__(self, *, token=None, **_kwargs) -> None:
        self.token = token
        self.up = True
        self.accepted: list[bytes] = []
        self.write_calls: list[bytes] = []
        self.closed = False

    def ready(self) -> bool:
        return self.up

    def write(self, payload: bytes) -> None:
        self.write_calls.append(payload)
        if not self.up:
            raise ConnectionError("influx destination refused the write")
        self.accepted.append(payload)

    def close(self) -> None:
        self.closed = True


def _client_factory(holder: dict):
    """A factory that records the resolved token and returns a shared fake."""

    def factory(*, url, token, org, bucket, measurement):
        client = FakeInfluxClient(token=token)
        holder["client"] = client
        holder["token_seen"] = token
        return client

    return factory


def _outbox(tmp_path, **kwargs) -> SinkDeliveryOutbox:
    return SinkDeliveryOutbox(tmp_path / "sink-delivery.sqlite3", **kwargs)


def _sink(tmp_path, holder, *, outbox=None, resolver=None, sink_id="influx-1", **overrides):
    return ManagedInfluxSink(
        api_token_env=_ENV,
        dataflow_id="df-1",
        device_id="pod8206hr:hw1",
        sink_id=sink_id,
        secret_resolver=resolver if resolver is not None else (lambda name: _SECRET),
        client_factory=_client_factory(holder),
        delivery_outbox=outbox if outbox is not None else _outbox(tmp_path),
        reconnect_min_interval_seconds=0.0,
        **overrides,
    )


def _row(**channels):
    return {"timestamp": 1_700_000_000, **channels}


# ---------------------------------------------------------------------------
# Acceptance criterion 1 — credential safety (SINK-07)
# ---------------------------------------------------------------------------


def test_missing_env_var_fails_open_with_variable_name_not_value(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder, resolver=lambda name: None)
    with pytest.raises(InfluxCredentialError) as excinfo:
        sink.open()
    err = excinfo.value
    assert err.sink_id == "influx-1"
    assert err.env_var == _ENV
    # The variable NAME appears; a value never does (none was resolved).
    assert _ENV in str(err)
    assert not sink.opened


def test_empty_env_var_fails_open(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder, resolver=lambda name: "")
    with pytest.raises(InfluxCredentialError):
        sink.open()


def test_resolver_receives_env_var_name_and_token_reaches_client_only(tmp_path):
    seen: list[str] = []
    holder: dict = {}
    sink = _sink(tmp_path, holder, resolver=lambda name: seen.append(name) or _SECRET)
    sink.open()
    # Worker-side resolution: resolver asked for the NAME, client got the value...
    assert seen == [_ENV]
    assert holder["token_seen"] == _SECRET
    # ...but the token is nowhere in the serialized snapshot.
    d = sink.get_dict()
    assert d["api_token_env"] == _ENV
    assert _SECRET not in repr(d)
    for banned in ("api_token", "token", "password", "secret"):
        assert banned not in d


def test_get_dict_is_reconstructable_and_secret_free(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder)
    d = sink.get_dict()
    # Reconstruction identity/config present...
    assert d["api_token_env"] == _ENV
    assert d["dataflow_id"] == "df-1"
    assert d["url"] == "http://localhost:8086"
    # ...and defensive redaction drops any secret-named field.
    poisoned = dict(d, api_token=_SECRET, password="p", secret="s", token="t")
    assert redact_mapping(poisoned) == d


# ---------------------------------------------------------------------------
# Initial availability enforcement — fail start on refused destination
# ---------------------------------------------------------------------------


def test_open_fails_when_destination_not_ready_at_start(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder)

    def factory(*, url, token, org, bucket, measurement):
        client = FakeInfluxClient(token=token)
        client.up = False  # readiness check will fail at start
        holder["client"] = client
        return client

    sink._client_factory = factory  # override for this test
    with pytest.raises(InfluxUnavailableError):
        sink.open()
    assert not sink.opened
    assert holder["client"].closed  # start torn down atomically


def test_real_client_uses_synchronous_write_api(monkeypatch):
    marker = object()
    captured: dict = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def write_api(self, *, write_options):
            captured["write_options"] = write_options
            return object()

    monkeypatch.setattr("influxdb_client.InfluxDBClient", Client)
    monkeypatch.setattr("influxdb_client.client.write_api.SYNCHRONOUS", marker)

    influx_module._RealInfluxClient(
        url="http://influx", token="secret", org="org", bucket="bucket"
    )

    assert captured["write_options"] is marker


# ---------------------------------------------------------------------------
# Acceptance criterion 2 — outage: ordered buffer, replay, ack, no duplicates
# ---------------------------------------------------------------------------


def test_outage_buffers_in_order_then_replays_acks_without_duplicates(tmp_path):
    holder: dict = {}
    outbox = _outbox(tmp_path)
    sink = _sink(tmp_path, holder, outbox=outbox)
    sink.open()
    client = holder["client"]

    # Healthy: first point delivered directly.
    sink.write_row(_row(ch0=1.0))
    assert client.accepted and client.accepted[0] == sink._encode(1_700_000_000, {"ch0": 1.0})

    # Outage after start: acquisition continues, points buffer in order.
    client.up = False
    sink.write_row(_row(ch0=2.0))
    sink.write_row(_row(ch0=3.0))
    assert sink.delivery_degraded is True
    assert sink.is_degraded is True
    pending = outbox.pending(sink.sink_key)
    assert [r.payload for r in pending] == [
        sink._encode(1_700_000_000, {"ch0": 2.0}),
        sink._encode(1_700_000_000, {"ch0": 3.0}),
    ]

    # Reconnect: ordered drain, acked only after acceptance, buffer empties.
    client.up = True
    sink.replay()
    assert outbox.count_pending(sink.sink_key) == 0
    assert sink.delivery_degraded is False

    # No duplicate logical points: each buffered payload accepted exactly once,
    # and its line-protocol identity is byte-stable across buffer and replay.
    accepted_after = client.accepted
    assert accepted_after.count(sink._encode(1_700_000_000, {"ch0": 2.0})) == 1
    assert accepted_after.count(sink._encode(1_700_000_000, {"ch0": 3.0})) == 1


def test_replay_stops_and_preserves_order_if_destination_flaps(tmp_path):
    holder: dict = {}
    outbox = _outbox(tmp_path)
    sink = _sink(tmp_path, holder, outbox=outbox)
    sink.open()
    client = holder["client"]

    client.up = False
    sink.write_row(_row(ch0=10.0))
    sink.write_row(_row(ch0=11.0))
    assert outbox.count_pending(sink.sink_key) == 2

    # Destination accepts exactly one write then fails again mid-drain.
    accept_budget = {"n": 1}
    original_write = client.write

    def flaky_write(payload):
        if accept_budget["n"] <= 0:
            raise ConnectionError("flap")
        accept_budget["n"] -= 1
        client.accepted.append(payload)

    client.up = True
    client.write = flaky_write  # type: ignore[method-assign]
    sink.replay()

    # Oldest acked and removed; the rest stays buffered, still ordered.
    assert outbox.count_pending(sink.sink_key) == 1
    remaining = outbox.pending(sink.sink_key)
    assert remaining[0].payload == sink._encode(1_700_000_000, {"ch0": 11.0})
    assert sink.delivery_degraded is True


def test_reconstructed_sink_does_not_reuse_pending_record_identity(tmp_path):
    outbox = _outbox(tmp_path)
    sink_key = "df-1::influx-1"
    outbox.enqueue(sink_key, b"older", idempotency_key=f"{sink_key}#0")

    holder: dict = {}
    sink = _sink(tmp_path, holder, outbox=outbox)

    def factory(*, token, **_kwargs):
        client = FakeInfluxClient(token=token)

        def fail_write(_payload):
            raise ConnectionError("still unavailable")

        client.write = fail_write  # type: ignore[method-assign]
        holder["client"] = client
        return client

    sink._client_factory = factory
    sink.open()
    sink.write_row(_row(ch0=12.0))

    assert [record.payload for record in outbox.pending(sink_key)] == [
        b"older",
        sink._encode(1_700_000_000, {"ch0": 12.0}),
    ]


# ---------------------------------------------------------------------------
# Acceptance criterion 3 — overflow loss reporting; healthy sibling continues
# ---------------------------------------------------------------------------


def test_overflow_reports_exact_loss_while_sibling_sink_continues(tmp_path):
    # A tiny per-sink byte cap forces eviction of the oldest buffered records.
    outbox = _outbox(tmp_path, max_bytes_per_sink=120, max_total_bytes=10_000)

    holder_a: dict = {}
    sink_a = _sink(tmp_path, holder_a, outbox=outbox, sink_id="influx-a")
    sink_a.open()
    client_a = holder_a["client"]

    holder_b: dict = {}
    sink_b = _sink(tmp_path, holder_b, outbox=outbox, sink_id="influx-b")
    sink_b.open()
    client_b = holder_b["client"]

    # Sink A's destination goes down and it buffers past its byte cap.
    client_a.up = False
    for value in range(1, 12):
        sink_a.write_row(_row(ch0=float(value)))

    loss = sink_a.loss_report()
    assert loss.lost_records > 0
    assert loss.lost_bytes > 0
    assert loss.lost_samples > 0
    assert loss.lost_time_start is not None and loss.lost_time_end is not None
    assert loss.lost_time_start <= loss.lost_time_end
    # Overflow eviction is permanent loss -> still degraded even though buffering.
    assert sink_a.is_degraded is True

    # Healthy sibling B keeps delivering directly, unaffected by A's overflow.
    sink_b.write_row(_row(ch0=42.0))
    assert sink_b.delivery_degraded is False
    assert client_b.accepted[-1] == sink_b._encode(1_700_000_000, {"ch0": 42.0})
    assert outbox.count_pending(sink_b.sink_key) == 0
    assert sink_b.loss_report().lost_records == 0


def test_bound_callback_reports_buffering_loss_and_recovery(tmp_path):
    reports: list[dict] = []
    holder: dict = {}
    outbox = _outbox(tmp_path, max_bytes_per_sink=120, max_total_bytes=10_000)
    sink = _sink(tmp_path, holder, outbox=outbox)
    sink.bind_error_callback(reports.append)
    sink.open()
    client = holder["client"]

    client.up = False
    sink.write_row(_row(ch0=7.0))
    degraded = reports[-1]
    assert degraded["state"] == "degraded"
    assert degraded["buffered_samples"] >= 0
    assert degraded["buffered_bytes"] >= 0
    assert degraded["sample_loss"] >= 0
    assert degraded["byte_loss"] >= 0

    client.up = True
    sink.replay()
    assert reports[-1]["state"] == "recovered"


# ---------------------------------------------------------------------------
# Factory wiring — INFLUX branch builds the managed adapter, deferred-open
# ---------------------------------------------------------------------------


def _influx_config(sink_id="pod8206hr:hw1:influx"):
    return SinkConfig(
        sink_id=sink_id,
        name="influx",
        type=SinkType.INFLUX,
        parameters={"api_token_env": _ENV, "bucket": "b1", "measurement": "m1"},
    )


def _ctx(**overrides):
    base = dict(dataflow_id="df-1", device_id="pod8206hr:hw1", schema_hash="h")
    base.update(overrides)
    return RuntimeContext(**base)


def test_factory_builds_managed_influx_sink_deferred_open():
    resolver_calls: list[str] = []
    ctx = _ctx(secret_resolver=lambda name: resolver_calls.append(name) or _SECRET)
    sink = build_sink(_influx_config(), object(), ctx)

    assert isinstance(sink, ManagedInfluxSink)
    assert sink.opened is False  # SINK-21: construction opens nothing
    # secret_resolver threaded through from the RuntimeContext hook.
    assert sink._secret_resolver is ctx.secret_resolver
    d = sink.get_dict()
    assert d["api_token_env"] == _ENV
    assert d["bucket"] == "b1"
    assert d["measurement"] == "m1"
    assert d["sink_id"] == "pod8206hr:hw1:influx"
    # No credential is resolved or exposed by construction.
    assert resolver_calls == []
    assert _SECRET not in repr(d)
