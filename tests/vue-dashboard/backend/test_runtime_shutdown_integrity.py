from types import SimpleNamespace

import pytest

import app.runtime_child.morelia as morelia_module
from app.runtime_child.driver import RuntimePhase
from app.runtime_child.morelia import MoreliaRuntime
from Morelia.Stream.shutdown import ShutdownAction, ShutdownOutcome, ShutdownPhase


def _runtime_with_watchdog(result):
    events = []

    class Monitor:
        def stop_dataflow(self, *, join_timeout_sec):
            events.append(("stop_dataflow", join_timeout_sec))
            return result

    class Watchdog:
        dataflow_monitor = Monitor()

        def stop(self):
            events.append(("watchdog_stop", None))

        def close(self):
            events.append(("watchdog_close", None))

    runtime = object.__new__(MoreliaRuntime)
    runtime._phase = RuntimePhase.RUNNING
    runtime._watchdog = Watchdog()
    runtime._watchdog_thread = None
    runtime._shutdown_timeout_sec = 15.0
    runtime._timeout_sec = 1.0
    runtime._manifest = SimpleNamespace(dataflow_id="df-shutdown-test")
    runtime._sinks = []
    runtime._close_sinks = lambda: events.append(("close_sinks", None))
    runtime._emit_all = lambda _status, *, phase, comms=None: setattr(runtime, "_phase", phase)
    return runtime, events


def _record(phase, action, sequence, *, outcome=ShutdownOutcome.ACKNOWLEDGED, worker_exitcode=None):
    return ShutdownAction(
        shutdown_id="shutdown-test",
        stream_index=0,
        actor="monitor" if phase in (ShutdownPhase.REQUESTED, ShutdownPhase.WORKER_EXITED, ShutdownPhase.COMPLETE) else "dataflow_worker",
        actor_pid=100,
        phase=phase,
        action=action,
        outcome=outcome,
        emitted_at_ns=sequence,
        action_seq=sequence,
        elapsed_ms=sequence,
        worker_exitcode=worker_exitcode,
    )


def test_stop_logs_each_action_once_then_one_summary(monkeypatch):
    records = (
        _record(ShutdownPhase.REQUESTED, "stop_requested", 1, outcome=ShutdownOutcome.STARTED),
        _record(ShutdownPhase.STOP_OBSERVED, "stop_event_observed", 2),
        _record(ShutdownPhase.SOURCE_STOPPED, "source_port_closed", 3),
        _record(ShutdownPhase.SINKS_FINALIZING, "sink_close_started", 4),
        _record(ShutdownPhase.SINKS_FINALIZED, "all_sinks_closed", 5),
        _record(ShutdownPhase.WORKER_EXITING, "worker_exit_started", 6),
        _record(ShutdownPhase.WORKER_EXITED, "worker_exit_observed", 7, outcome=ShutdownOutcome.COMPLETED, worker_exitcode=0),
        _record(ShutdownPhase.COMPLETE, "shutdown_completed", 8, outcome=ShutdownOutcome.COMPLETED),
    )
    runtime, events = _runtime_with_watchdog(
        {
            "ok": True,
            "stream_results": [{
                "ok": True,
                "stream_index": 0,
                "shutdown_id": "shutdown-test",
                "terminal_phase": "complete",
                "forced_termination": False,
                "worker_exitcode": 0,
                "missing_phases": [],
                "transcript": records,
            }],
        }
    )
    logs = []
    monkeypatch.setattr(morelia_module._log, "info", lambda event, **fields: logs.append((event, fields)))

    runtime.stop()

    assert [event for event, _fields in logs] == [
        "dataflow_shutdown_action",
    ] * len(records) + ["dataflow_shutdown_summary"]
    assert logs[-1][1]["action_count"] == len(records)
    assert events == [("watchdog_stop", None), ("stop_dataflow", 15.0), ("watchdog_close", None), ("close_sinks", None)]
    assert runtime.phase is RuntimePhase.STOPPED


def test_forced_shutdown_raises_and_never_reports_stopped(monkeypatch):
    runtime, events = _runtime_with_watchdog(
        {
            "ok": False,
            "stream_results": [{
                "ok": False,
                "stream_index": 0,
                "shutdown_id": "shutdown-failed",
                "terminal_phase": "failed",
                "forced_termination": True,
                "worker_exitcode": -15,
                "missing_phases": ["sinks_finalized"],
                "transcript": (),
            }],
        }
    )
    emitted = []
    runtime._emit_all = lambda *args, **kwargs: emitted.append((args, kwargs))

    with pytest.raises(RuntimeError, match="forced_termination=true"):
        runtime.stop()

    assert events[:3] == [("watchdog_stop", None), ("stop_dataflow", 15.0), ("watchdog_close", None)]
    assert not emitted
    assert runtime.phase is RuntimePhase.RUNNING
