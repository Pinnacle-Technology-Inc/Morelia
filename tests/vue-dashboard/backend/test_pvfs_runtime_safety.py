"""Runtime safety cases from the accepted PVFS disconnect and ownership contracts."""

import hashlib
import math
import multiprocessing as mp
import sys
import threading
import time
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from app import create_app
from app.database import db
from app.domain.enums import SinkType
from app.models.output_file import OutputFile
from app.output.managed_pvfs_sink import ManagedPvfsSink
from app.output.pvfs_merger import _read_channel
from app.runtime_child import pvfs_acquisition as acquisition
from app.runtime_child.acknowledged_dataflow import (
    AcknowledgedDataFlow,
    ShutdownReporter,
)
from app.runtime_child.acknowledged_monitor import AcknowledgedDataFlowMonitor
from app.runtime_child.driver import RuntimePhase
from app.runtime_child.morelia import MoreliaRuntime, _normalize_sink_error
from app.runtime_host.manifest import SinkConfig
from pvfs_tools.Core.pvfs_data_file import PvfsDataFile


class ScriptedHardware:
    sample_rate = 8
    _source_recovery_window_sec = 1.0
    _backend_managed = True
    _port_value = "COM3"
    _name = "COM3"
    device_name = "device"

    def __init__(self, script, clock, stop):
        self.script = iter(script)
        self.clock = clock
        self.stop = stop
        self._port = None
        self.addresses = []

    def open_port(self):
        self._port = object()
        self.addresses.append(self._port_value)

    def close_port(self):
        self._port = None

    def write_packet(self, *_):
        pass

    def check_write_queue(self):
        pass

    def obtain_read_queue(self):
        return Queue()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read_pod_packet_streaming(self, **_):
        at, value, final = next(self.script)
        self.clock[0] = at
        if final:
            self.stop.set()
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(ch0=value)


class OutageHardware:
    sample_rate = 8

    def __init__(self):
        self._port = None
        self._read_count = 0

    def get_dict(self):
        return {}

    def open_port(self):
        self._port = object()

    def close_port(self):
        self._port = None

    def obtain_read_queue(self):
        return Queue()

    def check_write_queue(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read_pod_packet_streaming(self, **_):
        self._read_count += 1
        time.sleep(0.025)
        if self._read_count > 1:
            raise OSError("hardware disconnected")
        return SimpleNamespace(ch0=11.0)


def scripted(monkeypatch, script):
    clock = [0.0]
    monkeypatch.setattr(
        acquisition,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            time_ns=lambda: int(clock[0] * 1e9),
        ),
    )
    stop = threading.Event()
    return ScriptedHardware(script, clock, stop), stop


@pytest.fixture
def app(tmp_path):
    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'outputs.sqlite'}",
        },
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.mark.parametrize("process", [False, True])
@pytest.mark.parametrize("scheduler", [None, "thread_pool", "new_thread"])
def test_brief_disconnect_keeps_native_segment_and_owner_dispatch(
    app, tmp_path, monkeypatch, process, scheduler
):
    pod, stop = scripted(
        monkeypatch,
        [
            (0.125, 11.0, False),
            (0.25, OSError("unplug"), False),
            (0.5, 22.0, False),
            (0.625, 33.0, True),
        ],
    )
    monkeypatch.setattr(acquisition, "current_connection_address", lambda *_: "COM7")
    path = tmp_path / f"brief-{process}-{scheduler}.pvfs"
    sink = ManagedPvfsSink(
        path=path,
        dataflow_id="runtime",
        channels=["EEG1"],
        units=["uV"],
        sample_rate=8,
        use_writer_process=process,
        observe_on_scheduler=scheduler,
    )
    statuses = []
    acquisition.get_data(
        10,
        stop,
        pod,
        [sink],
        on_source_error=statuses.append,
        reconnect_config=(object(), object()),
    )
    assert pod.addresses == ["COM3", "COM7"]
    assert [entry["state"] for entry in statuses] == ["degraded", "recovered"]
    rows = db.session.scalars(db.select(OutputFile)).all()
    assert len(rows) == 1
    reader = PvfsDataFile(read_only=True)
    assert reader.open(str(path))
    try:
        _, values = _read_channel(reader.open_channel("EEG1"))
        assert len(values) == 5
        assert [values[0], values[3], values[4]] == [11, 22, 33]
        assert all(math.isnan(value) for value in values[1:3])
    finally:
        reader.close()


@pytest.mark.parametrize("last_at", [1.125, 1.25])
def test_threshold_expires_before_accepting_returning_packet(monkeypatch, last_at):
    pod, stop = scripted(
        monkeypatch,
        [
            (0.125, 11.0, False),
            (0.25, OSError("unplug"), False),
            (last_at, 22.0, True),
        ],
    )
    values, statuses = [], []
    observer = SimpleNamespace(on_next=values.append, on_completed=lambda: None)
    acquisition._stream(pod, 10, stop, statuses.append, 500, 1, None)(observer, None)
    assert len(values) == 9
    assert values[0].ch0 == 11
    assert all(getattr(value, "is_missing_sample", False) for value in values[1:])
    assert statuses[-1]["state"] == "recovery_window_expired"
    assert pod._port is None


def test_shared_shutdown_budget_can_only_shorten():
    flow = AcknowledgedDataFlow([])
    deadline = mp.Value("d", 0.0)
    flow._shutdown_deadlines[0] = deadline
    reporter = ShutdownReporter(Queue(), "stop", 0, deadline)
    assert reporter.shutdown_deadline is None
    flow.publish_shutdown_deadline(100)
    flow.publish_shutdown_deadline(150)
    assert reporter.shutdown_deadline == 100
    flow.publish_shutdown_deadline(90, 0)
    assert reporter.shutdown_deadline == 90


@pytest.mark.parametrize("policy, expected", [("automate", 1), ("recommend", 0)])
def test_terminal_sink_error_triggers_policy_even_without_heartbeat_failure(
    policy, expected
):
    runtime = MoreliaRuntime.__new__(MoreliaRuntime)
    runtime._sink_error_queue = Queue()
    runtime._sink_reports = {}
    runtime._sink_seq = {}
    runtime._sink_recovery_attempted = set()
    runtime._failed_output_ids = set()
    runtime._local_cancel = threading.Event()
    runtime._phase = RuntimePhase.RUNNING
    runtime._stream_by_device = {"device": 0, "other-device": 1}
    runtime._manifest = SimpleNamespace(
        policy=policy,
        device_flows=[
            SimpleNamespace(
                device_id="device",
                sinks=[
                    SinkConfig(
                        sink_id="sink",
                        name="sink",
                        type=SinkType.PVFS,
                        parameters={"file_path": "recording.pvfs"},
                    )
                ],
            )
        ],
    )
    runtime._manifest.device_flows.append(
        SimpleNamespace(
            device_id="other-device",
            sinks=runtime._manifest.device_flows[0].sinks,
        )
    )
    calls = []
    runtime._watchdog = SimpleNamespace(
        stream_command=lambda *a, **kw: calls.append((a, kw)) or {"ok": True}
    )
    event = {
        "source_id": "device",
        "sink_id": "sink",
        "sink_class": "ManagedPvfsSink",
        "state": "terminal",
        "output_id": "first",
    }
    runtime._sink_error_queue.put(event)
    runtime._drain_sink_errors()
    runtime._sink_error_queue.put(event)
    runtime._sink_error_queue.put({**event, "output_id": "failed-replacement"})
    runtime._drain_sink_errors()
    assert len(calls) == expected
    if calls:
        assert calls[0][0] == (0,)
        assert calls[0][1]["command"] == "restart_stream"


def test_reconstruction_requires_worker_exit_before_importing_devices():
    runtime = MoreliaRuntime.__new__(MoreliaRuntime)
    runtime._flowgraph = SimpleNamespace(
        _shutdown_results={0: {"teardown_confirmed": False}}
    )
    runtime._watchdog = None
    with pytest.raises(RuntimeError, match="acquisition worker exits"):
        runtime._reconstruct_stream(0)


def test_restart_does_not_reset_or_rebuild_before_worker_exit():
    from contextlib import nullcontext

    monitor = AcknowledgedDataFlowMonitor(flowgraph=None)
    monitor.flowgraph = SimpleNamespace(_workers=[None])
    monitor._stream_lock = lambda _: nullcontext()
    monitor._stop_stream_unlocked = lambda *_: {"teardown_confirmed": False}
    forbidden = []
    monitor.reset_stream_device = lambda _: forbidden.append("reset")
    monitor._start_stream_unlocked = lambda _: forbidden.append("start")
    result = monitor._restart_one_stream_reserved(0, 1)
    assert result["ok"] is False
    assert "worker exit is unconfirmed" in result["error"]
    assert forbidden == []


@pytest.mark.parametrize("process", [False, True])
def test_runtime_cleans_native_sink_whose_enter_raises(
    app, tmp_path, monkeypatch, process
):
    class FailedEnter(ManagedPvfsSink):
        def __enter__(self):
            super().__enter__()
            raise RuntimeError("injected startup failure after native open")

    pod, stop = scripted(monkeypatch, [])
    sink = FailedEnter(
        path=tmp_path / "failed-start.pvfs",
        dataflow_id="runtime",
        channels=["EEG1"],
        sample_rate=8,
        use_writer_process=process,
    )
    with pytest.raises(RuntimeError, match="injected startup failure"):
        acquisition.get_data(10, stop, pod, [sink])
    assert sink._ownership_released()
    assert pod._port is None


def test_control_packets_do_not_extend_disconnect_window(monkeypatch):
    class Control:
        pass

    monkeypatch.setattr(acquisition, "ControlPacket", Control)
    pod, stop = scripted(
        monkeypatch, [(0.125, 11.0, False), (0.25, OSError("unplug"), False)]
    )
    original = pod.read_pod_packet_streaming
    calls = [0]

    def read(**kwargs):
        calls[0] += 1
        if calls[0] <= 2:
            return original(**kwargs)
        pod.clock[0] = 1.125
        return Control()

    pod.read_pod_packet_streaming = read
    values, statuses = [], []
    observer = SimpleNamespace(on_next=values.append, on_completed=lambda: None)
    acquisition._stream(pod, 10, stop, statuses.append, 500, 1, None)(observer, None)
    assert len(values) == 9
    assert statuses[-1]["state"] == "recovery_window_expired"


@pytest.mark.parametrize("process", [False, True])
def test_long_disconnect_records_gap_and_preserves_finalized_source(
    app, tmp_path, monkeypatch, process
):
    pod, stop = scripted(
        monkeypatch,
        [
            (0.125, 11.0, False),
            (0.25, OSError("unplug"), False),
            (1.125, 22.0, True),
        ],
    )
    path = tmp_path / "long.pvfs"
    sink = ManagedPvfsSink(
        path=path,
        dataflow_id="runtime",
        channels=["EEG1"],
        sample_rate=8,
        use_writer_process=process,
    )
    acquisition.get_data(10, stop, pod, [sink])
    old = db.session.scalars(db.select(OutputFile)).one()
    assert old.acquisition_state == "interrupted"
    assert old.termination_reason == "source_disconnect"
    assert old.row_offset == 9
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    successor = ManagedPvfsSink(**sink.get_dict())
    with successor:
        successor.write_frame([77.0])
    rows = db.session.scalars(
        db.select(OutputFile).order_by(OutputFile.segment_index)
    ).all()
    assert len(rows) == 2
    assert rows[1].previous_output_id == old.output_id
    assert rows[1].segment_index == old.segment_index + 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_recommend_terminal_event_commits_gap_while_worker_keeps_running(app, tmp_path):
    sink = ManagedPvfsSink(
        path=tmp_path / "recommend-gap.pvfs",
        dataflow_id="runtime",
        channels=["EEG1"],
        sample_rate=8,
        use_writer_process=False,
    )
    with sink:
        sink.write_frame([11.0])
        sink.flush()
        runtime = MoreliaRuntime.__new__(MoreliaRuntime)
        runtime._database_config = {
            "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"]
        }
        runtime._sink_error_queue = Queue()
        runtime._sink_reports = {}
        runtime._sink_seq = {}
        runtime._failed_output_ids = set()
        runtime._manifest = SimpleNamespace(
            policy="recommend",
            device_flows=[
                SimpleNamespace(
                    device_id="device",
                    sinks=[
                        SinkConfig(
                            sink_id="sink",
                            name="sink",
                            type=SinkType.PVFS,
                            parameters={"file_path": "recommend-gap.pvfs"},
                        )
                    ],
                )
            ],
        )
        runtime._sink_error_queue.put(
            _normalize_sink_error(
                {
                    "source_id": "device",
                    "sink_id": "sink",
                    "sink_class": "ManagedPvfsSink",
                    "state": "terminal",
                    "output_id": sink._record.output_id,
                    "confirmed_samples": 1,
                }
            )
        )
        runtime._drain_sink_errors()
        import sqlite3

        with sqlite3.connect(tmp_path / "outputs.sqlite") as connection:
            row = connection.execute(
                "SELECT status, acquisition_state, termination_reason, row_offset "
                "FROM output_files WHERE output_id = ?",
                (sink._record.output_id,),
            ).fetchone()
        assert row == ("open", "interrupted", "writer_failure", 1)


def test_segment_resume_keeps_devices_with_the_same_sink_name_separate(app, tmp_path):
    for device, segment in [("first", 2), ("second", 7)]:
        db.session.add(
            OutputFile(
                output_id=f"{device}-output",
                logical_sink_id=f"{device}-logical",
                dataflow_id="runtime",
                device_id=device,
                sink_id="recording",
                sink_type="pvfs",
                segment_index=segment,
                path=str(tmp_path / f"{device}.pvfs"),
                status="closed",
            )
        )
    db.session.commit()
    runtime = MoreliaRuntime.__new__(MoreliaRuntime)
    runtime._database_config = None
    runtime._manifest = SimpleNamespace(dataflow_id="runtime")
    for device, segment in [("first", 2), ("second", 7)]:
        resumed = runtime._segment_resume(
            SimpleNamespace(
                device_id=device,
                sinks=[SimpleNamespace(sink_id="recording")],
            )
        )
        assert resumed == {
            "recording": {
                "output_id": f"{device}-output",
                "logical_sink_id": f"{device}-logical",
                "segment_index": segment,
            }
        }


@pytest.mark.parametrize("process", [False, True])
def test_spawned_outage_expiry_records_complete_shutdown_transcript(
    app, tmp_path, process
):
    module_name = "test_pvfs_runtime_safety"
    sys.modules.setdefault(module_name, sys.modules[__name__])
    if str(Path(__file__).parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent))
    OutageHardware.__module__ = module_name
    sink = ManagedPvfsSink(
        path=tmp_path / "outage-worker.pvfs",
        dataflow_id="runtime",
        channels=["EEG1"],
        sample_rate=8,
        use_writer_process=process,
    )
    flow = AcknowledgedDataFlow(
        [(OutageHardware(), [sink])], source_recovery_window_sec=0.25
    )
    try:
        flow.collect()
        worker = flow._workers[0]
        worker.join(20)
        assert not worker.is_alive()
        assert flow._manual_stop_events[0].is_set()
        result = flow.stop_collection()
        assert result["ok"] is True
        assert result["teardown_confirmed"] is True
        actions = [
            record.action for record in result["stream_results"][0]["transcript"]
        ]
        assert "stop_event_observed" in actions
        assert "source_port_closed" in actions
        row = db.session.scalars(db.select(OutputFile)).one()
        assert row.status == "closed"
        assert row.acquisition_state == "interrupted"
        assert row.termination_reason == "source_disconnect"
    finally:
        if any(worker is not None for worker in flow._workers):
            flow.stop_collection()
