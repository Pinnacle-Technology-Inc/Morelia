"""Worker-only CSV handle ownership (packet 12 / gap SINK-21).

These tests prove the process/ownership boundary for managed CSV sinks:

1. Building the runtime stack in the parent watchdog process creates NO file,
   NO ``output_files`` row, NO database handle, and NO CSV writer — the sinks
   are deferred-open descriptors only.
2. The worker (standing in via ``open()``) opens exactly one CSV handle, writes
   one row per delivered sample, and closes it exactly once — with no second
   handle or duplicate row appearing beside the parent's descriptor.
3. ``MoreliaRuntime`` builds each CSV sink from a resolved ``SinkConfig`` and
   still rejects non-CSV sink types (deferred to later packets).
4. A failure after allocation (header write) closes the handle and marks the
   component a writer failure instead of pretending acquisition started.
"""

from types import SimpleNamespace

import pytest

from app.domain.enums import DeviceType, PolicyMode, SinkType
from app.models.output_file import OutputFile
from app.output.managed_csv_sink import ManagedCsvSink, ManagedCsvSinkError
from app.runtime_child.morelia import MoreliaRuntime
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)


# ---------------------------------------------------------------------------
# Fakes injected in place of the real Morelia classes (no hardware, no Morelia).
# ---------------------------------------------------------------------------


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


class _FakeWatchdog:
    def __init__(self, *, flowgraph, failure_threshold, max_heartbeat_age_sec):
        self.flowgraph = flowgraph
        self.failure_threshold = failure_threshold
        self.max_heartbeat_age_sec = max_heartbeat_age_sec

    def preflight(self, *, timeout_sec):
        self.preflighted = True


def _fake_importer():
    # (Watchdog, Pod8206HR, Pod8401HR, DataFlow, CSVSink, Preamp, PrimaryMode, SecondaryMode)
    return (
        _FakeWatchdog,
        _FakePod8206HR,
        object,
        _FakeDataFlow,
        ManagedCsvSink,  # the REAL sink — its ownership is what we are testing
        object,
        object,
        object,
    )


class _Packet8206:
    ch0 = 1
    ch1 = 2
    ch2 = 3
    ttl1 = 0
    ttl2 = 1
    ttl3 = 0
    ttl4 = 1


_FIELDS_8206 = ["time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"]


def _manifest(csv_path: str) -> Manifest:
    device_id = "pod8206hr:hw1"
    flow = DeviceFlow(
        device_id=device_id,
        name="pod8206hr",
        nickname=None,
        hardware_id="hw1",
        port="COM3",
        parameters={},
        sinks=(
            SinkConfig(
                sink_id=f"{device_id}:main",
                name="main",
                type=SinkType.CSV,
                parameters={"file_path": csv_path},
            ),
        ),
    )
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-ownership",
        policy=PolicyMode.RECOMMEND,
        device_flows=(flow,),
        session_id=None,
    )


def _runtime(manifest) -> MoreliaRuntime:
    return MoreliaRuntime(
        manifest=manifest,
        on_report=lambda report: None,
        importer=_fake_importer,
    )


# ---------------------------------------------------------------------------
# Acceptance 1: parent stack build is side-effect free.
# ---------------------------------------------------------------------------


def test_parent_build_stack_creates_no_file_row_or_handle(tmp_path, app):
    csv_path = tmp_path / "stream.csv"
    manifest = _manifest(str(csv_path))
    runtime = _runtime(manifest)

    with app.app_context():
        runtime._build_stack()

        # No side effects on disk or in the database.
        assert not csv_path.exists(), "parent must not create the CSV file"
        assert OutputFile.query.count() == 0, "parent must not create an output row"

        # The parent holds exactly one deferred-open CSV descriptor per sink.
        assert len(runtime._sinks) == 1
        sink = runtime._sinks[0]
        assert isinstance(sink, ManagedCsvSink)
        assert sink.opened is False, "parent-built sink must not be open"
        assert sink.managed is None, "parent-built sink owns no live handle"

        # It is wired into the (fake) flowgraph as a per-source sink list.
        assert runtime._flowgraph.network[0][1] == [sink]

        # get_dict() from the unopened parent descriptor carries no output_id, so
        # the reconstructing worker opens/resumes rather than reopening a row the
        # parent never allocated.
        assert sink.get_dict()["output_id"] is None


# ---------------------------------------------------------------------------
# Acceptance 2: the worker owns the single live handle end-to-end.
# ---------------------------------------------------------------------------


def test_worker_opens_one_handle_writes_per_sample_and_closes_once(tmp_path, app):
    csv_path = tmp_path / "stream.csv"
    manifest = _manifest(str(csv_path))
    runtime = _runtime(manifest)

    with app.app_context():
        runtime._build_stack()
        parent_sink = runtime._sinks[0]

        # Reconstruct exactly as Morelia's get_data_wrapper does in the worker.
        descriptor = parent_sink.get_dict()
        worker_sink = ManagedCsvSink(**{**descriptor, "pod": object()})

        # Worker-side open is the sole point a live handle/row/header appears.
        worker_sink.open()
        assert csv_path.exists()
        assert OutputFile.query.count() == 1, "exactly one component, worker-owned"
        row = OutputFile.query.one()
        assert row.sink_id == f"{manifest.device_flows[0].device_id}:main"

        # One row per delivered sample.
        for _ in range(3):
            worker_sink.flush(123, _Packet8206())

        worker_sink.close()
        assert worker_sink.managed._handle.closed is True

        # close() is idempotent across normal/error paths — no double close.
        worker_sink.close()

        # Still exactly one output row — no second handle or duplicate component
        # was created beside the parent descriptor (the SINK-21 defect).
        assert OutputFile.query.count() == 1

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(_FIELDS_8206)
    assert lines[1:] == ["123,1,2,3,0,1,0,1"] * 3


# ---------------------------------------------------------------------------
# Acceptance 3: SinkConfig-driven construction; non-CSV stays rejected.
# ---------------------------------------------------------------------------


def test_build_csv_sink_uses_sinkconfig_identity_and_path(tmp_path, app):
    csv_path = tmp_path / "from-config.csv"
    runtime = _runtime(_manifest(str(csv_path)))
    sink_config = SimpleNamespace(
        type=SinkType.CSV,
        sink_id="pod8206hr:hw1:extra",
        parameters={"file_path": str(csv_path)},
    )
    device_flow = SimpleNamespace(device_id="pod8206hr:hw1")

    sink = runtime._build_csv_sink(
        ManagedCsvSink, device_flow, sink_config, DeviceType.POD8206HR, pod=object()
    )

    d = sink.get_dict()
    assert d["path"] == str(csv_path)
    assert d["sink_id"] == "pod8206hr:hw1:extra"
    assert sink.opened is False


def test_build_csv_sink_rejects_non_csv_sink_type(tmp_path):
    runtime = _runtime(_manifest(str(tmp_path / "x.csv")))
    non_csv = SimpleNamespace(
        type=SinkType.EDF,
        sink_id="pod8206hr:hw1:edf",
        parameters={"file_path": str(tmp_path / "y.edf")},
    )
    device_flow = SimpleNamespace(device_id="pod8206hr:hw1")

    with pytest.raises(ValueError, match="unsupported Morelia sink type"):
        runtime._build_csv_sink(
            ManagedCsvSink, device_flow, non_csv, DeviceType.POD8206HR, pod=object()
        )


# ---------------------------------------------------------------------------
# Failure handling: allocation succeeded, header write failed.
# ---------------------------------------------------------------------------


def test_open_failure_after_allocation_marks_writer_failure(tmp_path, app):
    csv_path = tmp_path / "doomed.csv"
    with app.app_context():
        sink = ManagedCsvSink(path=csv_path, dataflow_id="df-fail", fieldnames=_FIELDS_8206)

        def _boom() -> bytes:
            raise RuntimeError("disk full during header")

        sink._header_bytes = _boom  # force failure after create() allocates the row

        with pytest.raises(RuntimeError, match="disk full during header"):
            sink.open()

        assert sink.opened is False, "a failed open must not report success"

        row = OutputFile.query.one()
        assert row.status == "closed", "the half-open handle must be closed"
        assert row.termination_reason == "writer_failure"
        # Never claim the acquisition started/completed successfully.
        assert row.acquisition_state == "open"
        assert sink.managed._handle.closed is True
