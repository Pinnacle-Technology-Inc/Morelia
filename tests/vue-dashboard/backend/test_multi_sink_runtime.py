from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import queue

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
from app.runtime_child.morelia import MoreliaRuntime
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)
from app.services import sessions as session_service
from app.services.output_finalization import MergeRequest

from uuid import uuid4

from app.domain.enums import DeviceType, SessionStatus
from app.services import device_configs
from app.services import session_templates
from app.services.sessions import create as create_session
from app.services import device_templates


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
    from Morelia.Stream.data_flow import DataFlow
    from Morelia.Watchdog.watchdog import Watchdog
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR
    from app.output.managed_csv_sink import ManagedCsvSink

    return (
        Watchdog,
        MockPod8206HR,
        object,
        DataFlow,
        ManagedCsvSink,
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
        hardware_id="002",
        port="COM3",
        parameters={"sample_rate": 2_000},
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


def _create_device_config(
    *,
    hardware_id="001",
    port="COM3",
):
    """Create a device config suitable for a session/template test."""
    return device_configs.create(
        device_type=DeviceType.POD8206HR,
        hardware_id=hardware_id,
        port=port,
        parameters={"preamp_gain": 10},
    )


def _create_template(*, tmp_path, name="bench-rig"):
    """Create a real device template and register a session template from it."""

    unique_name = f"{name}-{uuid4().hex[:8]}"

    device_template = device_templates.create(
        name,
        {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10},
        },
    )

    return session_templates.create(
        f"{unique_name}-session",
        {
            "policy": "recommend",
            "device_flows": [
                {
                    "device_template_path": device_template.file_path,
                    "sinks": [
                        {
                            "sink_type": "csv",
                            "sink_location": "test_output/out.csv",
                        }
                    ],
                }
            ],
        },
    )

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

    try:
        sender = runtime._flowgraph._on_sink_error
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

        assert all(
            d.stream_status is StreamStatus.HEALTHY
            for d in report.devices
        )

        assert len(report.sinks) == 1

        sink = report.sinks[0]

        assert sink.sink_id == "pod8206hr:1:plot"
        assert sink.health is SinkHealth.FAILED
        assert sink.delivery is SinkDeliveryState.FAILED
        assert "presentation disconnected" in sink.message

    finally:
        runtime.close()


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

        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        session = create_session(
            {
                "source_template_id": template.template_id,
                "expected_template_hash": template.registered_hash,
                "assignments": [
                    {
                        "flow_index": 0,
                        "device_config_id": config.id,
                        "sink_locations": [
                            {
                                "sink_index": 0,
                                "sink_location": str(tmp_path / "output.csv"),
                            }
                        ],
                    }
                ],
            }
        )
        session_id = session.id
        
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
        assert stopped.status == SessionStatus.STOPPED

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

    sub = broker.subscribe(
        30,
        "browser-plot",
        maxlen=3,
    )

    transport = InProcessPlotTransport(
        broker,
        session_id=30,
        sink_id="browser-plot",
    )

    sink = ManagedPlotSink(
        dataflow_id="df-gate",
        sink_id="browser-plot",
        session_id=30,
        chunk_samples=1,
        max_display_rate=1000.0,
        channel_names=["ch0"],
        transport=transport,
    )

    sink.open()

    try:
        sink.write_row({"ch0": 0.0})

        assert sub.pending() == 1

        sub.drain()

        for seq in range(10):
            broker.publish(
                30,
                "browser-plot",
                {
                    "schema": PLOT_SCHEMA_VERSION,
                    "seq": seq,
                    "samples": [[float(seq)]],
                },
            )

        assert sub.pending() == 3
        assert sub.dropped == 7

        drained = sub.drain()

        assert [b["seq"] for b in drained] == [7, 8, 9]

        assert all(
            b["schema"] == PLOT_SCHEMA_VERSION
            for b in drained
        )

        with app.app_context():
            other = mint_plot_token(
                99,
                "browser-plot",
            )

        client = app.test_client()

        resp = client.get(
            f"/api/v1/sessions/30/plot/browser-plot/stream?token={other}"
        )

        assert resp.status_code == 403

    finally:
        sink.close()

