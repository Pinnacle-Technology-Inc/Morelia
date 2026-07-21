"""Contract tests for the runtime report shape (Stage 2.1, types only).

These prove the boundary serializes round-trip and rejects malformed data
*before* any driver behavior exists — the same discipline as the watchdog
message tests.
"""

import pytest

from app.domain.enums import CommsStatus, StreamStatus
from app.runtime_child.driver import (
    DeviceReport,
    RuntimePhase,
    RuntimeReport,
    SinkDeliveryState,
    SinkFinalization,
    SinkHealth,
    SinkReport,
)


def _report() -> RuntimeReport:
    return RuntimeReport(
        dataflow_id="dataflow-1",
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.CURRENT,
        devices=(
            DeviceReport(device_id="dev-1", stream_status=StreamStatus.HEALTHY),
            DeviceReport(device_id="dev-2", stream_status=StreamStatus.SUSPECT),
        ),
        sequence=3,
    )


def _sink(
    *,
    sink_id: str = "dev-1:csv",
    source_id: str = "dev-1",
    health: SinkHealth = SinkHealth.HEALTHY,
    delivery: SinkDeliveryState = SinkDeliveryState.DELIVERED,
    sequence: int = 7,
    state_timestamp_ns: int = 1_700_000_000_000_000_000,
    **overrides: object,
) -> SinkReport:
    values: dict[str, object] = {
        "sink_id": sink_id,
        "source_id": source_id,
        "sink_class": "csv",
        "health": health,
        "delivery": delivery,
        "sequence": sequence,
        "state_timestamp_ns": state_timestamp_ns,
    }
    values.update(overrides)
    return SinkReport(**values)  # type: ignore[arg-type]


def test_runtime_report_round_trips_through_its_wire_form():
    report = _report()

    assert RuntimeReport.from_dict(report.to_dict()) == report


def test_runtime_report_carries_sequence_not_a_timestamp():
    # The control plane stamps UTC on receipt; the report itself only orders
    # itself with a monotonic counter. Guard that no timestamp field leaks in.
    wire = _report().to_dict()

    assert wire["sequence"] == 3
    assert "timestamp" not in wire and "time" not in wire


def test_recovery_id_is_omitted_instead_of_sent_as_null():
    assert "recovery_id" not in _report().to_dict()

    recovering = RuntimeReport(
        dataflow_id="dataflow-1",
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.DELAYED,
        devices=(DeviceReport(device_id="dev-1", stream_status=StreamStatus.UNHEALTHY),),
        sequence=4,
        recovery_id="recovery-1",
    )

    assert recovering.to_dict()["recovery_id"] == "recovery-1"


def test_report_boundary_rejects_unknown_fields():
    wire = _report().to_dict()
    wire["unexpected"] = "smuggled"

    with pytest.raises(ValueError, match="unknown runtime report fields"):
        RuntimeReport.from_dict(wire)


def test_report_boundary_rejects_unknown_stream_status():
    with pytest.raises(ValueError, match="'haunted'"):
        DeviceReport.from_dict({"device_id": "dev-1", "stream_status": "haunted"})


def test_sequence_must_be_a_non_negative_int_not_a_bool():
    # bool is a subclass of int in Python; a sloppy check would let True == 1
    # slip through as a sequence number. Guard it explicitly.
    with pytest.raises(ValueError, match="sequence must be an int"):
        RuntimeReport(
            dataflow_id="dataflow-1",
            phase=RuntimePhase.IDLE,
            comms=CommsStatus.CURRENT,
            devices=(),
            sequence=True,
        )


# ── Per-sink report wire contract (packet 20) ────────────────────────────────


def test_sink_report_round_trips_through_its_wire_form():
    sink = _sink(
        health=SinkHealth.DEGRADED,
        delivery=SinkDeliveryState.DELIVERING,
        buffered_samples=128,
        buffered_bytes=4096,
        sample_loss=3,
        byte_loss=96,
        component="influx-client",
        finalization=SinkFinalization.NONE,
        failure_kind="sink_write",
        exception_type="ConnectionError",
        message="destination refused connection",
        last_success_seq=5,
    )

    assert SinkReport.from_dict(sink.to_dict()) == sink


def test_report_carries_many_sinks_on_a_separate_axis_from_source_health():
    # Two sinks on one source: one healthy, one failed. Source stream health is
    # untouched — a failed sink is NOT a sick source (SINK-08/SINK-19/SINK-23).
    report = RuntimeReport(
        dataflow_id="dataflow-1",
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.CURRENT,
        devices=(DeviceReport(device_id="dev-1", stream_status=StreamStatus.HEALTHY),),
        sequence=9,
        sinks=(
            _sink(sink_id="dev-1:csv", health=SinkHealth.HEALTHY),
            _sink(
                sink_id="dev-1:influx",
                sink_class="influx",
                health=SinkHealth.FAILED,
                delivery=SinkDeliveryState.FAILED,
                failure_kind="sink_write",
                message="token rejected",
            ),
        ),
    )

    wire = report.to_dict()

    # Source health axis is unchanged and independent of the failing sink.
    assert wire["devices"] == [{"device_id": "dev-1", "stream_status": "healthy"}]
    assert len(wire["sinks"]) == 2
    assert {s["sink_id"]: s["health"] for s in wire["sinks"]} == {
        "dev-1:csv": "healthy",
        "dev-1:influx": "failed",
    }
    assert RuntimeReport.from_dict(wire) == report


def test_sink_sequence_and_state_timestamp_are_preserved_monotonically():
    sinks = (
        _sink(sink_id="dev-1:csv", sequence=10, state_timestamp_ns=100),
        _sink(sink_id="dev-1:edf", sink_class="edf", sequence=11, state_timestamp_ns=200),
    )
    report = RuntimeReport(
        dataflow_id="dataflow-1",
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.CURRENT,
        devices=(),
        sequence=1,
        sinks=sinks,
    )

    decoded = RuntimeReport.from_dict(report.to_dict())

    assert [s.sequence for s in decoded.sinks] == [10, 11]
    assert [s.state_timestamp_ns for s in decoded.sinks] == [100, 200]


def test_report_without_sinks_omits_the_key_and_decodes_prior_shape():
    # A report predating the per-sink contract has no "sinks" key; the decoder
    # translates it to zero sinks rather than rejecting it (acceptance 3).
    wire = _report().to_dict()

    assert "sinks" not in wire
    assert RuntimeReport.from_dict(wire).sinks == ()


def test_degraded_buffering_loss_state_carries_bounded_counters_and_diagnostics():
    sink = _sink(
        health=SinkHealth.DEGRADED,
        delivery=SinkDeliveryState.DEGRADED,
        buffered_samples=64,
        buffered_bytes=2048,
        sample_loss=12,
        byte_loss=384,
        failure_kind="sink_write",
        exception_type="TimeoutError",
        message="write timed out; buffering",
    )

    wire = sink.to_dict()

    assert wire["buffered_samples"] == 64 and wire["buffered_bytes"] == 2048
    assert wire["sample_loss"] == 12 and wire["byte_loss"] == 384
    assert wire["message"] == "write timed out; buffering"
    assert SinkReport.from_dict(wire) == sink


def test_recovered_sink_keeps_residual_loss_counters_while_health_is_healthy():
    # "Recovered" = health back to HEALTHY and delivering again, but the durable
    # permanent-loss counters from the outage remain visible.
    sink = _sink(
        health=SinkHealth.HEALTHY,
        delivery=SinkDeliveryState.DELIVERING,
        sample_loss=40,
        byte_loss=1280,
        last_success_seq=99,
    )

    decoded = SinkReport.from_dict(sink.to_dict())

    assert decoded.health is SinkHealth.HEALTHY
    assert decoded.sample_loss == 40 and decoded.byte_loss == 1280


def test_sink_report_boundary_rejects_unknown_fields():
    wire = _sink().to_dict()
    wire["secret_token"] = "smuggled"

    with pytest.raises(ValueError, match="unknown sink report fields"):
        SinkReport.from_dict(wire)


def test_sink_report_boundary_rejects_missing_required_fields():
    wire = _sink().to_dict()
    del wire["health"]

    with pytest.raises(ValueError, match="missing sink report fields"):
        SinkReport.from_dict(wire)


def test_sink_report_rejects_unknown_health_and_delivery_vocab():
    healthy_wire = _sink().to_dict()
    healthy_wire["health"] = "haunted"
    with pytest.raises(ValueError):
        SinkReport.from_dict(healthy_wire)

    delivery_wire = _sink().to_dict()
    delivery_wire["delivery"] = "teleported"
    with pytest.raises(ValueError):
        SinkReport.from_dict(delivery_wire)


def test_sink_report_rejects_oversized_message():
    with pytest.raises(ValueError, match="message must be <= 500"):
        _sink(message="x" * 501)


def test_sink_report_sequence_must_be_non_negative_int_not_bool():
    with pytest.raises(ValueError, match="sequence must be an int"):
        _sink(sequence=True)
    with pytest.raises(ValueError, match="state_timestamp_ns must be non-negative"):
        _sink(state_timestamp_ns=-1)


def test_report_rejects_duplicate_sink_identity():
    # Two sinks sharing (source_id, sink_id) would let one sink's state obscure
    # a sibling's — the exact SINK-23 hazard. Reject at construction.
    with pytest.raises(ValueError, match="duplicate sink identity"):
        RuntimeReport(
            dataflow_id="dataflow-1",
            phase=RuntimePhase.RUNNING,
            comms=CommsStatus.CURRENT,
            devices=(),
            sequence=1,
            sinks=(_sink(sink_id="dev-1:csv"), _sink(sink_id="dev-1:csv")),
        )


def test_report_rejects_a_malformed_sink_entry_wholesale():
    # One bad sink dict must fail the whole decode — no partial/ambiguous accept.
    wire = _report().to_dict()
    wire["sinks"] = [_sink().to_dict(), {"sink_id": "dev-1:edf"}]  # second is incomplete

    with pytest.raises(ValueError, match="missing sink report fields"):
        RuntimeReport.from_dict(wire)


def test_report_rejects_non_list_sinks():
    wire = _report().to_dict()
    wire["sinks"] = {"sink_id": "dev-1:csv"}

    with pytest.raises(ValueError, match="sinks must be a list"):
        RuntimeReport.from_dict(wire)
