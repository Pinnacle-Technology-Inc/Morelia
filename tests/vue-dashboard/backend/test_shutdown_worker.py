from queue import Queue

import pytest

import Morelia.Stream.source as source_module
from Morelia.shutdown import ShutdownPhase, ShutdownOutcome
from app.runtime_child.acknowledged_dataflow import ShutdownReporter, acknowledged_get_data_wrapper


class FakeEvent:
    def __init__(self, value=False):
        self.value = value

    def is_set(self):
        return self.value


class FakeSource:
    def __init__(self, **_kwargs):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close_port(self):
        self.closed = True


class FakeSink:
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_shutdown_reporter_emits_picklable_action_records():
    queue = Queue()
    reporter = ShutdownReporter(queue, "shutdown-1", 2)

    reporter.emit(ShutdownPhase.STOP_OBSERVED, "stop_event_observed")

    record = queue.get_nowait()
    assert record.shutdown_id == "shutdown-1"
    assert record.stream_index == 2
    assert record.actor == "dataflow_worker"
    assert record.actor_pid > 0
    assert record.phase is ShutdownPhase.STOP_OBSERVED
    assert record.outcome is ShutdownOutcome.ACKNOWLEDGED


def test_backend_worker_emits_legacy_teardown_transcript(monkeypatch):
    queue = Queue()

    def fake_get_data(_duration, _event, pod, sinks, **_kwargs):
        with pod:
            pass
        pod.close_port()
        entered = []
        for sink in sinks:
            entered.append(sink.__enter__())
        for sink in reversed(entered):
            sink.__exit__(None, None, None)

    monkeypatch.setattr(source_module, "get_data", fake_get_data)

    acknowledged_get_data_wrapper(
        1.0,
        FakeEvent(True),
        FakeSource,
        {},
        [(FakeSink, {})],
        shutdown_queue=queue,
        shutdown_id="shutdown-2",
        stream_index=0,
    )

    records = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [record.phase for record in records] == [
        ShutdownPhase.STOP_OBSERVED,
        ShutdownPhase.SOURCE_STOPPED,
        ShutdownPhase.SINKS_FINALIZING,
        ShutdownPhase.SINKS_FINALIZED,
        ShutdownPhase.WORKER_EXITING,
    ]


def test_backend_worker_preserves_teardown_failures(monkeypatch):
    def failing_get_data(*_args, **_kwargs):
        raise RuntimeError("sink close failed")

    monkeypatch.setattr(source_module, "get_data", failing_get_data)

    with pytest.raises(RuntimeError, match="sink close failed"):
        acknowledged_get_data_wrapper(
            1.0,
            FakeEvent(True),
            FakeSource,
            {},
            [],
        )
