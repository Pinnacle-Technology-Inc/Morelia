"""Packet 25 — managed Quest sink: bounded delivery replay over QuestDB ILP.

These tests never open a real TCP socket to any QuestDB. The destination is a
controllable in-memory ``FakeQuestClient`` injected via ``client_factory``, and
the delivery buffer is a real (Flask-less) ``SinkDeliveryOutbox`` on ``tmp_path``.
They prove the three packet-25 acceptance criteria plus the factory wiring, and
mirror the sibling Influx adapter's test structure (packet 24) minus any
credential handling — Quest has no token.
"""

from __future__ import annotations

import pytest

from app.domain.enums import SinkType
from app.output.quest_sink import (
    ManagedQuestSink,
    QuestUnavailableError,
)
from app.output import quest_sink as quest_module
from app.runtime_child.sink_factory import RuntimeContext, build_sink
from app.runtime_host.manifest import SinkConfig
from app.watchdog_process.sink_delivery_outbox import SinkDeliveryOutbox


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeQuestClient:
    """In-memory ILP destination. ``up`` toggles a simulated outage."""

    def __init__(self, *, host=None, port=None, **_kwargs) -> None:
        self.host = host
        self.port = port
        self.up = True
        self.accepted: list[bytes] = []
        self.write_calls: list[bytes] = []
        self.closed = False
        self.schema_validated = False

    def ready(self) -> bool:
        return self.up

    def validate_schema(self, _table: str) -> None:
        self.schema_validated = True

    def write(self, payload: bytes) -> None:
        self.write_calls.append(payload)
        if not self.up:
            raise ConnectionError("quest destination refused the write")
        self.accepted.append(payload)

    def close(self) -> None:
        self.closed = True


def _client_factory(holder: dict):
    """A factory that records the destination binding and returns a shared fake."""

    def factory(*, host, port, measurement):
        client = FakeQuestClient(host=host, port=port)
        holder["client"] = client
        holder["host_seen"] = host
        holder["port_seen"] = port
        return client

    return factory


def _outbox(tmp_path, **kwargs) -> SinkDeliveryOutbox:
    return SinkDeliveryOutbox(tmp_path / "sink-delivery.sqlite3", **kwargs)


def _sink(tmp_path, holder, *, outbox=None, sink_id="quest-1", **overrides):
    return ManagedQuestSink(
        dataflow_id="df-1",
        device_id="pod8206hr:hw1",
        sink_id=sink_id,
        client_factory=_client_factory(holder),
        delivery_outbox=outbox if outbox is not None else _outbox(tmp_path),
        reconnect_min_interval_seconds=0.0,
        **overrides,
    )


def _row(**channels):
    return {"timestamp": 1_700_000_000, **channels}


# ---------------------------------------------------------------------------
# Construction / snapshot — side-effect-free, secret-free (SINK-21)
# ---------------------------------------------------------------------------


def test_construction_opens_nothing_and_snapshot_is_reconstructable(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder, host="qdb", port=9010, measurement="m1")
    # SINK-21: construction opens no socket and no client.
    assert sink.opened is False
    assert holder == {}
    d = sink.get_dict()
    assert d["dataflow_id"] == "df-1"
    assert d["host"] == "qdb"
    assert d["port"] == 9010
    assert d["measurement"] == "m1"
    assert d["sink_id"] == "quest-1"


# ---------------------------------------------------------------------------
# Acceptance criterion 1 — unreachable at start fails cleanly, closes client
# ---------------------------------------------------------------------------


def test_open_fails_when_destination_not_reachable_at_start(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder)

    def factory(*, host, port, measurement):
        client = FakeQuestClient(host=host, port=port)
        client.up = False  # reachability check will fail at start
        holder["client"] = client
        return client

    sink._client_factory = factory  # override for this test
    with pytest.raises(QuestUnavailableError) as excinfo:
        sink.open()
    assert excinfo.value.sink_id == "quest-1"
    assert not sink.opened
    assert holder["client"].closed  # start torn down atomically


def test_open_validates_quest_dedup_schema(tmp_path):
    holder: dict = {}
    sink = _sink(tmp_path, holder)

    sink.open()

    assert holder["client"].schema_validated is True


def test_real_client_flushes_structured_rows_over_http_transactionally():
    class Buffer:
        def __init__(self):
            self.rows = []

        def row(self, table, *, symbols, columns, at):
            self.rows.append((table, symbols, columns, at))

    class Sender:
        def __init__(self):
            self.buffer = Buffer()
            self.flushed = None

        def new_buffer(self):
            return self.buffer

        def flush(self, buffer, *, transactional):
            self.flushed = (buffer, transactional)

    client = quest_module._RealQuestClient.__new__(quest_module._RealQuestClient)
    client._sender = Sender()
    client._timestamp_nanos = lambda value: ("ns", value)
    payload = quest_module._encode_quest_payload(
        table="measurements",
        acquisition_id="acq-1",
        sink_id="quest-1",
        device_name="pod, one",
        timestamp=123,
        fields={"ch 0": 7.5},
    )

    client.write(payload)

    assert client._sender.buffer.rows == [
        (
            "measurements",
            {
                "acquisition_id": "acq-1",
                "sink_id": "quest-1",
                "channel": "ch 0",
                "name": "pod, one",
            },
            {"value": 7.5},
            ("ns", 123),
        )
    ]
    assert client._sender.flushed == (client._sender.buffer, True)


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
    sink_key = "df-1::quest-1"
    outbox.enqueue(sink_key, b"older", idempotency_key=f"{sink_key}#0")

    holder: dict = {}
    sink = _sink(tmp_path, holder, outbox=outbox)

    def factory(**_kwargs):
        client = FakeQuestClient()

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
    outbox = _outbox(tmp_path, max_bytes_per_sink=400, max_total_bytes=10_000)

    holder_a: dict = {}
    sink_a = _sink(tmp_path, holder_a, outbox=outbox, sink_id="quest-a")
    sink_a.open()
    client_a = holder_a["client"]

    holder_b: dict = {}
    sink_b = _sink(tmp_path, holder_b, outbox=outbox, sink_id="quest-b")
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


# ---------------------------------------------------------------------------
# Destination-failure report (packet 23 shape) — redacted, no samples, "quest"
# ---------------------------------------------------------------------------


def test_sink_error_report_shape_on_outage(tmp_path):
    reports: list[dict] = []
    holder: dict = {}
    sink = _sink(tmp_path, holder, on_sink_error=reports.append)
    sink.open()
    client = holder["client"]

    client.up = False
    sink.write_row(_row(ch0=7.0))

    assert reports, "an outage must emit a destination-failure report"
    report = reports[-1]
    assert report["sink_class"] == "quest"
    assert report["failure_kind"] == "sink_write"
    assert report["sink_id"] == "quest-1"
    assert report["state"] == "degraded"
    assert len(report["message"]) <= 500
    # Never carries a raw sample payload.
    assert "value=7.0" not in report["message"]


# ---------------------------------------------------------------------------
# Factory wiring — QUEST branch builds the managed adapter, deferred-open
# ---------------------------------------------------------------------------


def _quest_config(sink_id="pod8206hr:hw1:quest"):
    return SinkConfig(
        sink_id=sink_id,
        name="quest",
        type=SinkType.QUEST,
        parameters={"host": "qdb", "port": 9010, "measurement": "m1"},
    )


def _ctx(**overrides):
    base = dict(dataflow_id="df-1", device_id="pod8206hr:hw1", schema_hash="h")
    base.update(overrides)
    return RuntimeContext(**base)


def test_factory_builds_managed_quest_sink_deferred_open():
    sink = build_sink(_quest_config(), object(), _ctx())

    assert isinstance(sink, ManagedQuestSink)
    assert sink.opened is False  # SINK-21: construction opens nothing
    d = sink.get_dict()
    assert d["host"] == "qdb"
    assert d["port"] == 9010
    assert d["measurement"] == "m1"
    assert d["sink_id"] == "pod8206hr:hw1:quest"
    # No credential field ever appears in a Quest snapshot.
    for banned in ("api_token", "api_token_env", "token", "password", "secret"):
        assert banned not in d


def test_factory_quest_defaults_from_morelia():
    config = SinkConfig(
        sink_id="pod8206hr:hw1:quest",
        name="quest",
        type=SinkType.QUEST,
        parameters={},
    )
    sink = build_sink(config, object(), _ctx())
    d = sink.get_dict()
    assert d["host"] == "localhost"
    assert d["port"] == 9000
    assert d["measurement"] == "default_measurement"
