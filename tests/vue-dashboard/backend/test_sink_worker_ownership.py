import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

import pytest

from Morelia.Stream.data_flow import DataFlow
from Morelia.Watchdog.watchdog import Watchdog
from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR
from app.output.managed_csv_sink import ManagedCsvSink

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

def _importer():

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

_FIELDS_8206 = ["time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"]


def _manifest(csv_path: str) -> Manifest:
    device_id = "pod8206hr:001"
    flow = DeviceFlow(
        device_id=device_id,
        name="pod8206hr",
        nickname=None,
        hardware_id="001",
        port="COM3",
        parameters={"sample_rate": 2_000},
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
        importer=_importer,
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

        # get_dict() from the unopened parent descriptor carries no output_id, so
        # the reconstructing worker opens/resumes rather than reopening a row the
        # parent never allocated.
        assert sink.get_dict()["output_id"] is None


# ---------------------------------------------------------------------------
# Acceptance 3: SinkConfig-driven construction; non-CSV stays rejected.
# ---------------------------------------------------------------------------


def test_build_csv_sink_uses_sinkconfig_identity_and_path(tmp_path, app):
    csv_path = tmp_path / "from-config.csv"
    runtime = _runtime(_manifest(str(csv_path)))
    sink_config = SimpleNamespace(
        type=SinkType.CSV,
        sink_id="pod8206hr:001:extra",
        parameters={"file_path": str(csv_path)},
    )
    device_flow = SimpleNamespace(device_id="pod8206hr:001")

    sink = runtime._build_csv_sink(
        ManagedCsvSink, device_flow, sink_config, DeviceType.POD8206HR, pod=object()
    )

    d = sink.get_dict()
    assert d["path"] == str(csv_path)
    assert d["sink_id"] == "pod8206hr:001:extra"
    assert sink.opened is False


def test_build_csv_sink_rejects_non_csv_sink_type(tmp_path):
    runtime = _runtime(_manifest(str(tmp_path / "x.csv")))
    non_csv = SimpleNamespace(
        type=SinkType.EDF,
        sink_id="pod8206hr:001:edf",
        parameters={"file_path": str(tmp_path / "y.edf")},
    )
    device_flow = SimpleNamespace(device_id="pod8206hr:001")

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
