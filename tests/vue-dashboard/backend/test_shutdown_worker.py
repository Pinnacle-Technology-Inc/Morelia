from queue import Queue

import pytest

import Morelia.Stream.source as source_module
from Morelia.shutdown import ShutdownPhase, ShutdownOutcome
from app.runtime_child.acknowledged_dataflow import ShutdownReporter, _SourceLifecycleProxy, acknowledged_get_data_wrapper


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
        _event.value = True  # Stop an entered acquisition, not a cancelled launch.
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
        FakeEvent(),
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
    def failing_get_data(_duration, event, *_args, **_kwargs):
        event.value = True
        raise RuntimeError("sink close failed")

    monkeypatch.setattr(source_module, "get_data", failing_get_data)

    with pytest.raises(RuntimeError, match="sink close failed"):
        acknowledged_get_data_wrapper(
            1.0,
            FakeEvent(),
            FakeSource,
            {},
            [],
        )


@pytest.mark.parametrize("failure", [None, "enter", "body", "exit"])
def test_source_proxy_closes_before_caller_finalizes_sinks(failure):
    events = []
    queue = Queue()

    class Device:
        def __enter__(self):
            if failure == "enter":
                raise OSError("enter failed")
            return self

        def __exit__(self, *_):
            if failure == "exit":
                raise OSError("exit failed")

        def close_port(self):
            events.append("port closed")

    proxy = _SourceLifecycleProxy(Device(), FakeEvent(True), ShutdownReporter(queue, "close", 0))
    error = None
    try:
        with proxy:
            if failure == "body":
                raise OSError("body failed")
    except OSError as exc:
        error = str(exc)
    finally:
        events.append("sinks finalizing")
    assert error == (f"{failure} failed" if failure else None)
    proxy.close_port()
    assert events == ["port closed", "sinks finalizing"]
    assert [queue.get_nowait().phase for _ in range(queue.qsize())] == [
        ShutdownPhase.STOP_OBSERVED, ShutdownPhase.SOURCE_STOPPED,
    ]


def test_source_proxy_reopen_restores_close_responsibility():
    events = []

    class Device(FakeSource):
        def open_port(self):
            events.append("open")

        def close_port(self):
            events.append("close")

    proxy = _SourceLifecycleProxy(Device(), FakeEvent(), None)
    with proxy:
        proxy.close_port()
        proxy.close_port()
        proxy.open_port()
    proxy.close_port()
    assert events == ["close", "open", "close"]


@pytest.mark.parametrize("failed_phase", [ShutdownPhase.STOP_OBSERVED, ShutdownPhase.SOURCE_STOPPED])
def test_reporting_failure_does_not_skip_port_closure(failed_phase):
    device = FakeSource()

    class BrokenReporter:
        def emit(self, phase, *_):
            if phase is failed_phase:
                raise OSError("report channel failed")

    proxy = _SourceLifecycleProxy(device, FakeEvent(True), BrokenReporter())
    with pytest.raises(OSError, match="report channel failed"):
        with proxy:
            pass
    assert device.closed


@pytest.mark.parametrize("entry_fails", [False, True])
def test_source_proxy_close_failure_is_visible_and_never_acknowledged(entry_fails):
    queue = Queue()

    class Device(FakeSource):
        def __enter__(self):
            if entry_fails:
                raise OSError("enter failed")
            return self

        def close_port(self):
            raise OSError("close failed")

    proxy = _SourceLifecycleProxy(Device(), FakeEvent(True), ShutdownReporter(queue, "close", 0))
    with pytest.raises(OSError, match="close failed"):
        with proxy:
            pass
    assert ShutdownPhase.SOURCE_STOPPED not in [queue.get_nowait().phase for _ in range(queue.qsize())]


def test_failed_final_close_cannot_be_hidden_by_a_second_close():
    class Device(FakeSource):
        closes = 0

        def close_port(self):
            self.closes += 1
            if self.closes == 1:
                raise OSError("first close failed")

        def open_port(self):
            pass

    device = Device()
    proxy = _SourceLifecycleProxy(device, FakeEvent(), None)
    with pytest.raises(OSError, match="first close failed"):
        with proxy:
            pass
    with pytest.raises(OSError, match="first close failed"):
        proxy.close_port()
    assert device.closes == 1
    proxy.open_port()
    proxy.close_port()
    assert device.closes == 2
