from queue import Queue

import pytest

import Morelia.Stream.source as source_module
from Morelia.Stream.shutdown import ShutdownPhase, ShutdownOutcome
from Morelia.Stream.source import _ShutdownReporter, get_data_wrapper


class FakeEvent:
    def __init__(self, value=False):
        self.value = value

    def is_set(self):
        return self.value


class FakeSource:
    def __init__(self, **_kwargs):
        pass


class FakeSink:
    def __init__(self, **_kwargs):
        pass


def test_shutdown_reporter_emits_picklable_action_records():
    queue = Queue()
    reporter = _ShutdownReporter(queue, "shutdown-1", 2)

    reporter.emit(ShutdownPhase.STOP_OBSERVED, "stop_event_observed")

    record = queue.get_nowait()
    assert record.shutdown_id == "shutdown-1"
    assert record.stream_index == 2
    assert record.actor == "dataflow_worker"
    assert record.actor_pid > 0
    assert record.phase is ShutdownPhase.STOP_OBSERVED
    assert record.outcome is ShutdownOutcome.ACKNOWLEDGED


def test_wrapper_emits_worker_exiting_after_clean_get_data(monkeypatch):
    queue = Queue()
    events = []

    def fake_get_data(*_args, shutdown_reporter=None, **_kwargs):
        events.append(shutdown_reporter)
        shutdown_reporter.emit(ShutdownPhase.STOP_OBSERVED, "stop_event_observed")
        shutdown_reporter.emit(ShutdownPhase.SOURCE_STOPPED, "source_port_closed")
        shutdown_reporter.emit(ShutdownPhase.SINKS_FINALIZING, "sink_close_started")
        shutdown_reporter.emit(ShutdownPhase.SINKS_FINALIZED, "all_sinks_closed")

    monkeypatch.setattr(source_module, "get_data", fake_get_data)

    get_data_wrapper(
        1.0,
        FakeEvent(True),
        FakeSource,
        {},
        [(FakeSink, {})],
        shutdown_queue=queue,
        shutdown_id="shutdown-2",
        stream_index=0,
    )

    assert events and events[0].finalization_started is True
    records = [queue.get_nowait() for _ in range(queue.qsize())]
    assert records[-1].phase is ShutdownPhase.WORKER_EXITING
    assert records[-1].action == "worker_exit_started"


def test_shutdown_exception_after_stop_is_not_converted_to_zero(monkeypatch):
    def failing_get_data(*_args, **_kwargs):
        raise RuntimeError("sink close failed")

    monkeypatch.setattr(source_module, "get_data", failing_get_data)

    with pytest.raises(RuntimeError, match="sink close failed"):
        get_data_wrapper(
            1.0,
            FakeEvent(True),
            FakeSource,
            {},
            [],
        )


def test_wrapper_without_reporter_keeps_legacy_call_shape(monkeypatch):
    called = []

    def fake_get_data(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr(source_module, "get_data", fake_get_data)

    get_data_wrapper(1.0, FakeEvent(False), FakeSource, {}, [])

    assert called
    assert called[0][1]["shutdown_reporter"] is None
