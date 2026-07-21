"""Runtime multi-sink stack integration (packet 26).

Proves the runtime layer constructs every selected sink in manifest order,
attaches them to one source, injects the picklable worker-boundary seams
(secret resolver, sink-delivery outbox factory), and isolates sink failures
onto the per-sink report axis — never as source/stream health (design doc
section 6; gaps SINK-04/SINK-19/SINK-22/SINK-23).

No real Morelia/hardware/InfluxDB/QuestDB: a stub importer supplies fake
device/CSV/DataFlow/Watchdog classes exactly like the existing driver tests.
The managed EDF/PVFS/Influx/Quest adapters are *descriptor-only* (deferred
worker-side open), so building them in-process opens no file/socket/DB handle.
"""

from __future__ import annotations

import functools
import dataclasses
import pickle
import queue

import pytest

from app.domain.enums import DeviceType, PolicyMode, SinkType, StreamStatus
from app.runtime_child.driver import RuntimePhase, SinkDeliveryState, SinkHealth
from app.runtime_child.morelia import (
    MoreliaRuntime,
    _normalize_sink_error,
    _SinkErrorSender,
    open_sink_delivery_outbox,
    resolve_secret_from_env,
)
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)
from app.watchdog_process.sink_delivery_outbox import (
    SinkDeliveryOutbox,
    default_sink_delivery_outbox_path,
)

# ── Fakes standing in for the lazy Morelia import (order matches _import_morelia) ──


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
        self.closed = False

    def close_port(self):
        self.closed = True


class _FakeDataFlow:
    def __init__(self, network, on_sink_error=None):
        self.network = network
        self.on_sink_error = on_sink_error


class _FakeWatchdog:
    def __init__(self, *, flowgraph, failure_threshold, max_heartbeat_age_sec):
        self.flowgraph = flowgraph
        self.failure_threshold = failure_threshold
        self.max_heartbeat_age_sec = max_heartbeat_age_sec

    def preflight(self, *, timeout_sec):
        self.preflighted = True


def _importer():
    return (
        _FakeWatchdog,
        _FakePod8206HR,
        object,  # Pod8401HR (unused here)
        _FakeDataFlow,
        _FakeCsvSink,
        object,  # Preamp
        object,  # PrimaryChannelMode
        object,  # SecondaryChannelMode
    )


def _sink(sink_type: SinkType, name: str, params: dict) -> SinkConfig:
    return SinkConfig(
        sink_id=f"pod8206hr:1:{name}",
        name=name,
        type=sink_type,
        parameters=params,
    )


def _manifest(*, sinks, session_id: int | None = 77) -> Manifest:
    device_flow = DeviceFlow(
        device_id="pod8206hr:1",
        name="pod8206hr",
        nickname="bench-a",
        hardware_id="1",
        port="COM3",
        parameters={},
        sinks=tuple(sinks),
    )
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-multi",
        policy=PolicyMode.RECOMMEND,
        device_flows=(device_flow,),
        session_id=session_id,
    )


def _csv_only_manifest(tmp_path) -> Manifest:
    return _manifest(sinks=[_sink(SinkType.CSV, "csv", {"file_path": str(tmp_path / "a.csv")})])


def _runtime(manifest, **kwargs) -> MoreliaRuntime:
    return MoreliaRuntime(
        manifest=manifest,
        on_report=kwargs.pop("on_report", lambda report: None),
        importer=_importer,
        **kwargs,
    )


def test_stop_uses_graceful_dataflow_timeout_before_watchdog_close(tmp_path):
    calls = []

    class _Monitor:
        def stop_dataflow(self, *, join_timeout_sec):
            calls.append(("stop_dataflow", join_timeout_sec))
            return {"ok": True, "dataflow_status": "stopped"}

    class _Watchdog:
        dataflow_monitor = _Monitor()

        def stop(self):
            calls.append(("watchdog_stop", None))

        def close(self):
            calls.append(("watchdog_close", None))

    runtime = _runtime(
        _csv_only_manifest(tmp_path),
        shutdown_timeout_sec=15.0,
    )
    runtime._phase = RuntimePhase.RUNNING
    runtime._watchdog = _Watchdog()

    runtime.stop()

    assert calls == [
        ("watchdog_stop", None),
        ("stop_dataflow", 15.0),
        ("watchdog_close", None),
    ]
    assert runtime.phase is RuntimePhase.STOPPED


# ── Acceptance criterion 1: every selected sink builds in manifest order, one ──
# ── source owns them all, and the worker-boundary injectables land correctly. ──


def test_all_selected_sinks_attach_to_one_source_in_manifest_order(tmp_path):
    outbox_factory = functools.partial(open_sink_delivery_outbox, str(tmp_path / "wd-sink.sqlite3"))
    manifest = _manifest(
        sinks=[
            _sink(SinkType.CSV, "csv", {"file_path": str(tmp_path / "a.csv")}),
            _sink(SinkType.EDF, "edf", {"file_path": str(tmp_path / "b.edf")}),
            _sink(SinkType.PVFS, "pvfs", {"file_path": str(tmp_path / "c.pvfs")}),
            _sink(SinkType.INFLUX, "influx", {"api_token_env": "INFLUX_TOKEN"}),
            _sink(SinkType.QUEST, "quest", {"host": "localhost", "port": 9009}),
        ]
    )
    runtime = _runtime(manifest, sink_delivery_outbox_factory=outbox_factory)

    runtime._build_stack()

    # One source owns the whole ordered sink collection.
    network = runtime._flowgraph.network
    assert len(network) == 1
    pod, sinks = network[0]
    assert isinstance(pod, _FakePod8206HR)
    assert [type(s).__name__ for s in sinks] == [
        "_FakeCsvSink",
        "ManagedEdfSink",
        "ManagedPvfsSink",
        "ManagedInfluxSink",
        "ManagedQuestSink",
    ]

    csv_sink, edf_sink, pvfs_sink, influx_sink, quest_sink = sinks

    # Influx resolves its token via the picklable env resolver; Influx + Quest
    # receive the delivery-outbox FACTORY. File sinks receive neither.
    assert influx_sink._secret_resolver is resolve_secret_from_env
    assert influx_sink._outbox_factory is outbox_factory
    assert quest_sink._outbox_factory is outbox_factory
    assert getattr(edf_sink, "_outbox_factory", None) is None
    assert getattr(pvfs_sink, "_outbox_factory", None) is None
    assert not hasattr(csv_sink, "_outbox_factory")

    # Session identity flows to every managed adapter that persists segments/gaps.
    assert influx_sink._session_id == 77
    assert edf_sink._session_id == 77


def test_file_only_stack_opens_no_delivery_outbox(tmp_path):
    """Contract: the SinkDeliveryOutbox is opened only by a selected Influx/Quest
    worker. A CSV/file-only stack must never materialize one."""
    outbox_path = tmp_path / "should-not-exist-sink.sqlite3"
    outbox_factory = functools.partial(open_sink_delivery_outbox, str(outbox_path))
    runtime = _runtime(_csv_only_manifest(tmp_path), sink_delivery_outbox_factory=outbox_factory)

    runtime._build_stack()

    assert not outbox_path.exists()


def test_runtime_context_injects_picklable_worker_boundary_seams(tmp_path):
    outbox_factory = functools.partial(open_sink_delivery_outbox, str(tmp_path / "x.sqlite3"))
    runtime = _runtime(_csv_only_manifest(tmp_path), sink_delivery_outbox_factory=outbox_factory)
    device_flow = runtime._manifest.device_flows[0]

    ctx = runtime._runtime_context(_FakeCsvSink, device_flow, DeviceType.POD8206HR, pod=object())

    assert ctx.secret_resolver is resolve_secret_from_env
    assert ctx.sink_delivery_outbox_factory is outbox_factory
    assert ctx.plot_transport is None
    assert ctx.session_id == 77
    # Everything crossing into the DataFlow worker must be picklable by reference.
    assert pickle.loads(pickle.dumps(ctx.secret_resolver)) is resolve_secret_from_env
    pickle.dumps(ctx.sink_delivery_outbox_factory)


# ── Picklable worker-boundary callables ──────────────────────────────────────


def test_secret_resolver_reads_token_name_from_environment(monkeypatch):
    monkeypatch.setenv("INFLUX_TOKEN", "s3cr3t-value")
    assert resolve_secret_from_env("INFLUX_TOKEN") == "s3cr3t-value"
    monkeypatch.delenv("INFLUX_TOKEN", raising=False)
    assert resolve_secret_from_env("INFLUX_TOKEN") is None


def test_sink_delivery_outbox_factory_is_picklable_and_opens_by_path(tmp_path):
    path = tmp_path / "wd-7-sink-delivery.sqlite3"
    factory = functools.partial(open_sink_delivery_outbox, str(path))

    restored = pickle.loads(pickle.dumps(factory))  # module-level func + str arg
    outbox = restored()
    try:
        assert isinstance(outbox, SinkDeliveryOutbox)
        assert path.exists()
    finally:
        outbox.close()


# ── Acceptance criterion 2: a sink failure is reported on the per-sink axis, ──
# ── never as source/stream health, while siblings/source stay healthy. ───────


def test_sink_error_sender_is_picklable_without_capturing_a_closure():
    sender = _SinkErrorSender(_PicklableQueue())
    restored = pickle.loads(pickle.dumps(sender))
    restored({"source_id": "s", "sink_id": "k", "sink_class": "InfluxSink", "state": "terminal"})
    assert restored._queue.items[0]["sink_id"] == "k"


class _PicklableQueue:
    """A trivial, picklable stand-in queue proving _SinkErrorSender holds no closure."""

    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def test_terminal_sink_write_failure_reaches_the_per_sink_report_axis(tmp_path):
    reports = []
    runtime = _runtime(
        _csv_only_manifest(tmp_path),
        on_report=reports.append,
        sink_error_queue_factory=queue.Queue,
    )
    runtime._build_stack()
    sender = runtime._flowgraph.on_sink_error

    sender(
        {
            "source_id": "pod8206hr",
            "sink_id": "pod8206hr:1:csv",
            "sink_class": "ManagedCsvSink",
            "failure_kind": "sink_write",
            "exception_type": "OSError",
            "message": "disk full",
            "state": "terminal",
            "last_success_seq": 41,
            "timestamp_ns": 1_700_000_000_000_000_000,
        }
    )
    runtime._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.PREFLIGHT)

    report = reports[-1]
    # Source/stream health is untouched — the failure lives ONLY on the sink axis.
    assert all(d.stream_status is StreamStatus.HEALTHY for d in report.devices)
    assert len(report.sinks) == 1
    sink = report.sinks[0]
    assert (sink.source_id, sink.sink_id) == ("pod8206hr", "pod8206hr:1:csv")
    assert sink.health is SinkHealth.FAILED
    assert sink.delivery is SinkDeliveryState.FAILED
    assert sink.failure_kind == "sink_write"
    assert sink.exception_type == "OSError"
    assert sink.message == "disk full"
    assert sink.last_success_seq == 41


def test_degraded_state_maps_to_degraded_health_and_bounds_the_message(tmp_path):
    reports = []
    runtime = _runtime(
        _csv_only_manifest(tmp_path),
        on_report=reports.append,
        sink_error_queue_factory=queue.Queue,
    )
    runtime._build_stack()

    runtime._flowgraph.on_sink_error(
        {
            "source_id": "pod8206hr",
            "sink_id": "pod8206hr:1:influx",
            "sink_class": "ManagedInfluxSink",
            "message": "x" * 900,  # worker may over-truncate; report re-bounds to 500
            "state": "degraded",
        }
    )
    runtime._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.PREFLIGHT)

    sink = reports[-1].sinks[0]
    assert sink.health is SinkHealth.DEGRADED
    assert sink.delivery is SinkDeliveryState.DEGRADED
    assert len(sink.message) == 500


def test_recovered_state_maps_counters_to_healthy_delivered_report(tmp_path):
    reports = []
    runtime = _runtime(
        _csv_only_manifest(tmp_path),
        on_report=reports.append,
        sink_error_queue_factory=queue.Queue,
    )
    runtime._build_stack()

    runtime._flowgraph.on_sink_error(
        {
            "source_id": "pod8206hr",
            "sink_id": "pod8206hr:1:influx",
            "sink_class": "ManagedInfluxSink",
            "state": "recovered",
            "buffered_samples": 0,
            "buffered_bytes": 0,
            "sample_loss": 3,
            "byte_loss": 120,
        }
    )
    runtime._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.PREFLIGHT)

    sink = reports[-1].sinks[0]
    assert sink.health is SinkHealth.HEALTHY
    assert sink.delivery is SinkDeliveryState.DELIVERED
    assert sink.sample_loss == 3
    assert sink.byte_loss == 120


def test_sink_reports_accumulate_per_identity_with_monotonic_sequence(tmp_path):
    reports = []
    runtime = _runtime(
        _csv_only_manifest(tmp_path),
        on_report=reports.append,
        sink_error_queue_factory=queue.Queue,
    )
    runtime._build_stack()
    sender = runtime._flowgraph.on_sink_error

    for _ in range(2):
        sender({"source_id": "src", "sink_id": "k", "sink_class": "C", "state": "terminal"})
        runtime._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.PREFLIGHT)

    sinks = reports[-1].sinks
    assert len(sinks) == 1  # same identity collapses to one latest report
    assert sinks[0].sequence == 1  # second event advanced the per-sink sequence


# ── Acceptance criterion 3: partial construction aborts before acquisition ───


def test_partial_construction_failure_aborts_before_hardware_and_watchdog(tmp_path, monkeypatch):
    import app.runtime_child.morelia as morelia_mod

    def _boom(sink_configs, pod, runtime_context):
        raise RuntimeError("sink construction failed")

    monkeypatch.setattr(morelia_mod, "build_sinks", _boom)
    runtime = _runtime(_csv_only_manifest(tmp_path))

    with pytest.raises(RuntimeError, match="sink construction failed"):
        runtime.preflight()

    # No DataFlow, no Watchdog, no sink-error channel, and acquisition never began.
    assert runtime._flowgraph is None
    assert runtime._watchdog is None
    assert runtime._sink_error_queue is None
    assert runtime.phase is RuntimePhase.IDLE


def test_second_source_construction_failure_rolls_back_first_source(tmp_path, monkeypatch):
    import app.runtime_child.morelia as morelia_mod

    class _ClosableSink:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    first_sink = _ClosableSink()
    calls = 0
    seen_pods = []

    def _build(sink_configs, pod, runtime_context):
        nonlocal calls
        calls += 1
        seen_pods.append(pod)
        if calls == 2:
            raise RuntimeError("second source failed")
        return [first_sink]

    monkeypatch.setattr(morelia_mod, "build_sinks", _build)
    original = _csv_only_manifest(tmp_path)
    second = dataclasses.replace(
        original.device_flows[0],
        device_id="pod8206hr:2",
        hardware_id="2",
        port="COM4",
        sinks=(
            _sink(
                SinkType.CSV,
                "csv-second",
                {"file_path": str(tmp_path / "b.csv")},
            ),
        ),
    )
    manifest = dataclasses.replace(
        original, device_flows=(original.device_flows[0], second)
    )
    runtime = _runtime(manifest)

    with pytest.raises(RuntimeError, match="second source failed"):
        runtime._build_stack()

    assert first_sink.closed is True
    assert all(pod.closed for pod in seen_pods)
    assert runtime._pods == []
    assert runtime._sinks == []
    assert runtime._flowgraph is None
    assert runtime._watchdog is None


def test_normalize_sink_error_accepts_a_dataclass_like_event():
    class _Event:
        source_id = "s"
        sink_id = "k"
        sink_class = "InfluxSink"
        failure_kind = "sink_write"
        exception_type = "ConnectionError"
        message = "refused"
        state = "terminal"
        last_success_seq = 3
        timestamp_ns = 123

    payload = _normalize_sink_error(_Event())
    assert payload["sink_id"] == "k"
    assert payload["state"] == "terminal"
    assert payload["last_success_seq"] == 3
