"""Launch failure contract from the user-approved shared scan recovery behavior.

Exercise the real service and job synchronization. Only the OS thread launch,
hardware provider, and persistence boundary are replaced.
"""

from threading import Event, Thread
from time import monotonic

import pytest
from app.services import discovery


class RecordingRepository:
    def __init__(self):
        self.scan_ids = []

    def record_scan(self, scan_id, devices):
        self.scan_ids.append(scan_id)


def test_launch_failure_is_retained_and_next_start_creates_a_fresh_job(monkeypatch):
    repository = RecordingRepository()
    service = discovery.DeviceDiscoveryService(
        discovery.FakeDiscoveryProvider([]), device_seen_repository=repository,
    )
    failure = RuntimeError("can't start new thread")

    class FailedLaunch(Thread):
        def start(self):
            raise failure

    with monkeypatch.context() as patch:
        patch.setattr(discovery, "Thread", FailedLaunch)
        with pytest.raises(RuntimeError) as raised:
            service.start()

    assert raised.value is failure
    failed_job = service._active
    assert failed_job.done.is_set(), "failed launch left the shared job pending"
    assert failed_job.error is failure
    failed = service.snapshot(failed_job.snapshot.scan_id)
    assert failed.state == "failed"
    assert failed.error == str(failure)
    assert failed.revision == 1
    assert failed.finished_at is not None
    assert failed.finished_at >= failed.scanned_at
    assert repository.scan_ids == []

    restarted = service.start()
    assert restarted.scan_id != failed.scan_id
    assert service._active.done.wait(2)
    assert service.snapshot(restarted.scan_id).state == "complete"
    assert repository.scan_ids == [restarted.scan_id]
    assert service.snapshot(failed.scan_id) == failed


def test_launch_failure_releases_a_concurrent_legacy_scan_waiter(monkeypatch):
    repository = RecordingRepository()
    service = discovery.DeviceDiscoveryService(
        discovery.FakeDiscoveryProvider([]), device_seen_repository=repository,
    )
    launch_entered, release_launch = Event(), Event()
    starter_finished, waiter_finished = Event(), Event()
    failure = RuntimeError("can't start new thread")
    errors = {}

    class BlockedFailedLaunch(Thread):
        def start(self):
            launch_entered.set()
            assert release_launch.wait(5), "test did not release the thread launch"
            raise failure

    monkeypatch.setattr(discovery, "Thread", BlockedFailedLaunch)

    def call_service(name, call, finished):
        try:
            call()
        except Exception as exc:
            errors[name] = exc
        finally:
            finished.set()

    starter = Thread(target=call_service, args=("starter", service.start, starter_finished),
                     daemon=True)
    waiter = Thread(target=call_service, args=("waiter", service.scan, waiter_finished),
                    daemon=True)
    starter.start()
    try:
        assert launch_entered.wait(2)
        pending = service.start()
        assert pending.state == "enumerating"
        job = service._active
        waiter.start()
        # Observe the real Event's condition to prove scan() is already waiting.
        # No service method or synchronization primitive is replaced.
        deadline = monotonic() + 2
        waiting = False
        while monotonic() < deadline:
            with job.done._cond:
                waiting = bool(job.done._cond._waiters)
            if waiting:
                break
            waiter_finished.wait(0.005)
        assert waiting, "legacy scan caller never joined the pending job"
        release_launch.set()
        assert starter_finished.wait(2)
        assert waiter_finished.wait(2), "legacy scan caller remained blocked after launch failure"
        assert errors == {"starter": failure, "waiter": failure}
        assert service.snapshot(pending.scan_id).state == "failed"
        assert repository.scan_ids == []
    finally:
        release_launch.set()
        starter.join(2)
        # Also terminate the waiter under the deliberately broken negative control.
        if service._active is not None:
            service._active.done.set()
        if waiter.ident is not None:
            waiter.join(2)
