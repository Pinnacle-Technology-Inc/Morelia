"""Arrival timing uses real HealthSink behavior with a controlled wall clock."""
from datetime import UTC, datetime
from queue import Queue
from types import SimpleNamespace

from Morelia.Watchdog import healthSink
from app.runtime_child.acknowledged_dataflow import ArrivalHealthSink, _bind_sink_callbacks


def test_output_sink_does_not_receive_health_arrival_binding(tmp_path):
    from app.output.managed_csv_sink import ManagedCsvSink
    output = ManagedCsvSink(path=tmp_path / "samples.csv", dataflow_id="arrival",
                            fieldnames=["time", "value"], device_id="pod", sink_id="csv")
    health, events = ArrivalHealthSink({}, "stream0"), Queue()
    _bind_sink_callbacks([output, health], None, None, events)
    assert output._recording_callback == events.put
    assert health._arrival_callback == events.put


def test_first_real_health_packet_uses_receipt_time_not_legacy_sample_time(monkeypatch):
    status, events = {}, Queue()
    sink = ArrivalHealthSink(status, "stream0")
    _bind_sink_callbacks([sink], None, None, events)
    now = 1_790_164_800.0
    monkeypatch.setattr(healthSink.time, "time", lambda: now)
    sink.flush(100, SimpleNamespace(is_missing_sample=True))
    assert events.empty() and status == {}
    sink.flush(100, SimpleNamespace())
    assert events.get_nowait() == {
        "event_type": "first_data", "arrived_at": datetime.fromtimestamp(now, UTC).isoformat(),
    }
    assert status["stream0.last_data_time"] == now
    assert status["stream0.last_stream_timestamp"] == 100
    now += 10
    sink.flush(200, SimpleNamespace())
    assert events.empty(), "Subsequent heartbeats cannot reset the timer"
    assert status["stream0.last_data_time"] == now


def test_replacement_health_sink_reports_new_receipt_not_stale_shared_state(monkeypatch):
    now = 1_790_164_810.0
    monkeypatch.setattr(healthSink.time, "time", lambda: now)
    status = {"stream0.last_data_time": now - 30, "stream0.packet_count": 100}
    events = Queue()
    sink = ArrivalHealthSink(status, "stream0")
    sink.bind_arrival_callback(events.put)
    sink.flush(100, SimpleNamespace())
    assert events.get_nowait()["arrived_at"] == datetime.fromtimestamp(now, UTC).isoformat()
    assert status["stream0.packet_count"] == 101
