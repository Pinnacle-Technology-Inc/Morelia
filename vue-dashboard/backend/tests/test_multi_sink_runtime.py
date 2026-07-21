"""Packet 30 — cross-sink release gates (automated, no hardware).

Proves the five release-critical scenarios from the design audit with exact
sample/order/loss/state assertions and no secret leakage. These gates compose
already-landed adapters (runtime factory, delivery outbox, plot transport,
EDF merge, stop/restart identity) rather than re-implementing them.

Owning packets on failure: 13/26 (construction), 19/24/25 (outbox/service),
14/17 (EDF), 27/28 (plot), 29 (stop/restart). Do not weaken assertions here.
"""

from __future__ import annotations

import functools
import queue
from pathlib import Path

from pyedflib import EdfReader
from structlog.contextvars import bind_contextvars

from app.api.plot_stream import (
    PLOT_SCHEMA_VERSION,
    InProcessPlotTransport,
    PlotBroker,
    mint_plot_token,
)
from app.domain.enums import DeviceType, PolicyMode, SessionStatus, SinkType, StreamStatus
from app.models.output_file import OutputFile
from app.output.edf_merger import edf_merger
from app.output.managed_edf_sink import ManagedEdfSink
from app.output.managed_file import allocate_continuation
from app.output.managed_file import create as create_output_file
from app.output.plot_sink import ManagedPlotSink
from app.repositories.output_files import (
    ACQUISITION_COMPLETE,
    ARTIFACT_MERGE_PENDING,
    ComponentRef,
    OutputFilesRepository,
)
from app.runtime_child.driver import RuntimePhase, SinkDeliveryState, SinkHealth
from app.runtime_child.morelia import MoreliaRuntime, open_sink_delivery_outbox
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)
from app.services import sessions as session_service
from app.services.device_configs import create as create_device_config
from app.services.output_finalization import MergeRequest
from app.watchdog_process.sink_delivery_outbox import sink_delivery_key

# ── shared fakes (mirror packet 26; keep local so this gate stays hermetic) ──


class _FakeCsvSink:
    def __init__(self, *, path, dataflow_id, fieldnames, device_id, sink_id, schema_hash, pod):
        self.path = path
        self.dataflow_id = dataflow_id
        self.fieldnames = fieldnames
        self.device_id = device_id
        self.sink_id = sink_id
        self.schema_hash = schema_hash
        self.pod = pod
        self.closed = False

    def close(self):
        self.closed = True


class _FakePod8206HR:
    def __init__(self, port, preamp_gain, *, baudrate, device_name, use_d2xx, sample_rate):
        self.port = port
        self.preamp_gain = preamp_gain
        self.baudrate = baudrate
        self.device_name = device_name
        self.use_d2xx = use_d2xx
        self.sample_rate = sample_rate


class _FakeDataFlow:
    def __init__(self, network, on_sink_error=None):
        self.network = network
        self.on_sink_error = on_sink_error


class _FakeWatchdog:
    def __init__(self, *, flowgraph, failure_threshold, max_heartbeat_age_sec):
        self.flowgraph = flowgraph

    def preflight(self, *, timeout_sec):
        self.preflighted = True


class _FakeSupervisor:
    def __init__(self) -> None:
        self.spawned: list[tuple[int, str]] = []
        self.dispatched = []
        self.stopped = []

    def spawn(self, session, *, manifest=None):
        self.spawned.append((session.id, manifest.hash if manifest else ""))
        session.runtime_port = 43210
        session.runtime_token = "fake-runtime-token"
        return session.runtime_port

    def dispatch(self, session, envelope):
        self.dispatched.append(envelope)

    def stop(self, session, *, envelope=None):
        self.stopped.append(envelope)
        session.runtime_port = None
        session.runtime_token = None


def _importer():
    return (
        _FakeWatchdog,
        _FakePod8206HR,
        object,
        _FakeDataFlow,
        _FakeCsvSink,
        object,
        object,
        object,
    )


def _sink(sink_type: SinkType, name: str, params: dict) -> SinkConfig:
    return SinkConfig(
        sink_id=f"pod8206hr:1:{name}",
        name=name,
        type=sink_type,
        parameters=params,
    )


def _manifest(*, sinks, session_id: int | None = 30) -> Manifest:
    device_flow = DeviceFlow(
        device_id="pod8206hr:1",
        name="pod8206hr",
        nickname="gate-a",
        hardware_id="1",
        port="COM3",
        parameters={},
        sinks=tuple(sinks),
    )
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-release-gate",
        policy=PolicyMode.RECOMMEND,
        device_flows=(device_flow,),
        session_id=session_id,
    )


def _runtime(manifest, **kwargs) -> MoreliaRuntime:
    return MoreliaRuntime(
        manifest=manifest,
        on_report=kwargs.pop("on_report", lambda report: None),
        importer=_importer,
        **kwargs,
    )


def _session_flow(tmp_path):
    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id="GAT01",
        port="COM9",
        parameters={"preamp_gain": 10},
    )
    return {
        "device_config_id": config.id,
        "sink_type": "csv",
        "sink_location": str(tmp_path / "gate-out.csv"),
    }


# ── Scenario 1: first start for a multi-sink source ──────────────────────────


def test_scenario_first_start_constructs_ordered_unique_multi_sink_stack(tmp_path, monkeypatch):
    monkeypatch.setenv("INFLUX_TOKEN", "gate-secret-never-persist")
    outbox_factory = functools.partial(
        open_sink_delivery_outbox, str(tmp_path / "wd-sink.sqlite3")
    )
    sinks = [
        _sink(SinkType.CSV, "csv", {"file_path": str(tmp_path / "a.csv")}),
        _sink(SinkType.EDF, "edf", {"file_path": str(tmp_path / "b.edf")}),
        _sink(SinkType.INFLUX, "influx", {"api_token_env": "INFLUX_TOKEN"}),
        _sink(SinkType.QUEST, "quest", {"host": "127.0.0.1", "port": 9009}),
        _sink(SinkType.PLOT, "plot", {"max_display_rate": 15.0}),
    ]
    runtime = _runtime(_manifest(sinks=sinks), sink_delivery_outbox_factory=outbox_factory)
    runtime._build_stack()

    network = runtime._flowgraph.network
    assert len(network) == 1
    _pod, built = network[0]
    assert [type(s).__name__ for s in built] == [
        "_FakeCsvSink",
        "ManagedEdfSink",
        "ManagedInfluxSink",
        "ManagedQuestSink",
        "ManagedPlotSink",
    ]
    ids = [getattr(s, "sink_id", None) or s.get_dict().get("sink_id") for s in built]
    assert ids == [s.sink_id for s in sinks]
    assert len(set(ids)) == len(ids)

    influx = built[2]
    redacted = influx.get_dict()
    blob = str(redacted)
    assert "gate-secret-never-persist" not in blob
    assert redacted.get("api_token_env") == "INFLUX_TOKEN"
    assert "api_token" not in redacted
    assert "token" not in redacted


# ── Scenario 2: sink-isolated failure while siblings continue ────────────────


def test_scenario_sink_failure_isolates_from_siblings_and_source(tmp_path):
    reports = []
    runtime = _runtime(
        _manifest(
            sinks=[
                _sink(SinkType.CSV, "csv", {"file_path": str(tmp_path / "a.csv")}),
                _sink(SinkType.PLOT, "plot", {"chunk_samples": 1}),
            ]
        ),
        on_report=reports.append,
        sink_error_queue_factory=queue.Queue,
    )
    runtime._build_stack()
    sender = runtime._flowgraph.on_sink_error
    assert sender is not None

    sender(
        {
            "source_id": "pod8206hr",
            "sink_id": "pod8206hr:1:plot",
            "sink_class": "ManagedPlotSink",
            "failure_kind": "sink_write",
            "exception_type": "ConnectionError",
            "message": "presentation disconnected",
            "state": "terminal",
            "last_success_seq": 7,
            "timestamp_ns": 1_700_000_000_000_000_000,
        }
    )
    runtime._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.PREFLIGHT)

    report = reports[-1]
    assert all(d.stream_status is StreamStatus.HEALTHY for d in report.devices)
    assert len(report.sinks) == 1
    sink = report.sinks[0]
    assert sink.sink_id == "pod8206hr:1:plot"
    assert sink.health is SinkHealth.FAILED
    assert sink.delivery is SinkDeliveryState.FAILED
    assert "presentation disconnected" in sink.message


# ── Scenario 3: EDF continuation merge preserves exact ordered samples ───────


def test_scenario_edf_fallback_merge_preserves_components_and_order(tmp_path, app):
    channels = ["EEG1", "EEG2"]
    rate = 8
    with app.app_context():
        base = tmp_path / "gate.edf"
        sink = ManagedEdfSink(
            path=base, dataflow_id="df-gate-edf", channels=channels, sample_rate=rate
        )
        sink.open()
        logical = sink.record.logical_sink_id
        for seg in range(2):
            for i in range(rate):
                sink.write_frame([float(seg * 100 + i)] * len(channels))
            if seg == 0:
                prior_path = Path(sink.record.path)
                sink.recover()
                # Component 0 is closed+immutable after recover; capture its
                # bytes now and assert they stay unchanged after segment 1 writes.
                prior_bytes = prior_path.read_bytes()
            else:
                sink.close()
                assert prior_path.read_bytes() == prior_bytes

        rows = (
            OutputFile.query.filter_by(logical_sink_id=logical)
            .order_by(OutputFile.segment_index)
            .all()
        )
        assert [r.segment_index for r in rows] == [0, 1]
        refs = tuple(
            ComponentRef(
                output_id=r.output_id,
                segment_index=r.segment_index,
                path=r.path,
                previous_output_id=r.previous_output_id,
                sink_type=r.sink_type,
                schema_hash=r.schema_hash,
                byte_offset=r.byte_offset,
                row_offset=r.row_offset,
                acquisition_state=r.acquisition_state,
                termination_reason=r.termination_reason,
            )
            for r in rows
        )
        request = MergeRequest(
            logical_sink_id=logical,
            finalization_id="gate-edf-1",
            fence_token=1,
            sink_type="edf",
            base_path=refs[0].path,
            temp_dir=str(tmp_path / "finalizer-temp"),
            components=refs,
        )
        result = edf_merger(request)
        component_paths = [r.path for r in rows]

    assert result.ok is True
    assert result.published_path
    assert Path(result.published_path).exists()
    for path in component_paths:
        assert Path(path).exists()

    import numpy as np

    with EdfReader(result.published_path) as reader:
        samples = reader.readSignal(0)
    expected = np.concatenate(
        [np.arange(seg * 100, seg * 100 + rate, dtype=float) for seg in range(2)]
    )
    np.testing.assert_allclose(samples, expected, atol=0.1)


# ── Scenario 4: clean stop then later start → new identities ─────────────────


def test_scenario_stop_then_restart_allocates_new_output_identity(tmp_path, app):
    with app.app_context():
        supervisor = _FakeSupervisor()
        session = session_service.create(
            {"name": "gate-stop-restart", "device_flows": [_session_flow(tmp_path)]}
        )
        bind_contextvars(request_id="gate-start-1")
        started = session_service.start_managed(session.id, supervisor)

        head = create_output_file(
            tmp_path / "run-a.bin",
            dataflow_id=started.dataflow_id,
            sink_type=SinkType.CSV,
            session_id=started.id,
        )
        head.write(b"seg0")
        logical_a = head.record.logical_sink_id
        head.close()
        cont = allocate_continuation(head.record)
        cont.write(b"seg1")
        cont.close()

        bind_contextvars(request_id="gate-stop-1")
        stopped = session_service.stop_managed(started.id, supervisor)
        assert stopped.status == SessionStatus.COMPLETED

        repo = OutputFilesRepository()
        components = repo.list_components(logical_a)
        assert components[-1].acquisition_state == ACQUISITION_COMPLETE
        assert components[0].artifact_state == ARTIFACT_MERGE_PENDING

        new_run = create_output_file(
            tmp_path / "run-b.bin",
            dataflow_id=started.dataflow_id,
            sink_type=SinkType.CSV,
            session_id=started.id,
        )
        assert new_run.record.logical_sink_id != logical_a
        assert new_run.record.path != components[0].path
        assert new_run.record.previous_output_id is None
        assert Path(components[0].path).read_bytes() == b"seg0"


# ── Scenario 5: live Plot lag is bounded; slow browser cannot backpressure ───


def test_scenario_plot_slow_browser_drops_oldest_without_blocking(app):
    broker = PlotBroker(default_maxlen=3)
    sub = broker.subscribe(30, "browser-plot", maxlen=3)
    transport = InProcessPlotTransport(broker, session_id=30, sink_id="browser-plot")
    sink = ManagedPlotSink(
        dataflow_id="df-gate",
        sink_id="browser-plot",
        session_id=30,
        chunk_samples=1,
        max_display_rate=1000.0,
        channel_names=["ch0"],
        transport=transport,
    ).open()

    # Prove the sink→broker bridge with one batch, then flood the broker directly
    # (rate-decimation is a separate sink-local policy; the release gate here is
    # that a slow browser's bounded queue drop-oldest cannot backpressure).
    sink.write_row({"ch0": 0.0})
    assert sub.pending() == 1
    sub.drain()

    for seq in range(10):
        broker.publish(
            30,
            "browser-plot",
            {"schema": PLOT_SCHEMA_VERSION, "seq": seq, "samples": [[float(seq)]]},
        )

    assert sub.pending() == 3
    assert sub.dropped == 7
    drained = sub.drain()
    assert [b["seq"] for b in drained] == [7, 8, 9]
    assert all(b["schema"] == PLOT_SCHEMA_VERSION for b in drained)

    with app.app_context():
        other = mint_plot_token(99, "browser-plot")
    client = app.test_client()
    resp = client.get(f"/api/v1/sessions/30/plot/browser-plot/stream?token={other}")
    assert resp.status_code == 403


# ── Mixed CSV + Influx + Plot: one destination fails, siblings keep identity ─


def test_mixed_sink_identity_preserved_when_service_path_degrades(tmp_path, monkeypatch):
    monkeypatch.setenv("INFLUX_TOKEN", "mixed-secret")
    outbox_path = tmp_path / "mixed-delivery.sqlite3"
    outbox_factory = functools.partial(open_sink_delivery_outbox, str(outbox_path))
    runtime = _runtime(
        _manifest(
            sinks=[
                _sink(SinkType.CSV, "csv", {"file_path": str(tmp_path / "m.csv")}),
                _sink(SinkType.INFLUX, "influx", {"api_token_env": "INFLUX_TOKEN"}),
                _sink(SinkType.PLOT, "plot", {}),
            ]
        ),
        sink_delivery_outbox_factory=outbox_factory,
    )
    runtime._build_stack()
    _pod, sinks = runtime._flowgraph.network[0]
    csv_sink, influx_sink, plot_sink = sinks

    assert csv_sink.sink_id == "pod8206hr:1:csv"
    assert influx_sink.get_dict()["sink_id"] == "pod8206hr:1:influx"
    assert plot_sink.sink_id == "pod8206hr:1:plot"

    outbox = outbox_factory()
    try:
        key = sink_delivery_key(
            acquisition_id="acq-1",
            logical_sink_id=influx_sink.get_dict()["sink_id"],
        )
        assert outbox.enqueue(key, b"line=1i", idempotency_key="i1") is True
        pending = outbox.pending(key)
        assert [r.idempotency_key for r in pending] == ["i1"]
        assert b"mixed-secret" not in pending[0].payload
        assert "mixed-secret" not in str(influx_sink.get_dict())
    finally:
        outbox.close()

    assert csv_sink.closed is False
    plot_sink.open()
    assert plot_sink.opened is True
    plot_sink.close()
    csv_sink.close()
    assert csv_sink.closed is True
