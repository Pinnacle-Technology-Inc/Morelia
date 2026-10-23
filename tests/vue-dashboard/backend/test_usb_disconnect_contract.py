from contextlib import contextmanager
import threading
import time
import unittest

from Morelia.Stream import source as legacy_source
from Morelia.Watchdog.watchdog import StreamWatcher

from app.runtime_child import pvfs_acquisition
from app.runtime_child.acknowledged_dataflow import _SourceLifecycleProxy


class Observer:
    def __init__(self):
        self.samples = 0
        self.completed = False

    def on_next(self, _packet):
        self.samples += 1

    def on_completed(self):
        self.completed = True


class Device:
    sample_rate = 2000
    port = "FAKE_NO_HARDWARE"
    device_name = "oracle-device"

    def __init__(self, stop, *, failures=None, stop_after=None, exit_error=None, close_error=None):
        self.stop = stop
        self.failures = failures
        self.stop_after = stop_after
        self.exit_error = exit_error
        self.close_error = close_error
        self.reads = self.closes = 0
        self.first_read = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        if self.exit_error is not None:
            raise self.exit_error

    def close_port(self):
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error

    def check_write_queue(self):
        pass

    def read_pod_packet_streaming(self, **_kwargs):
        self.reads += 1
        self.first_read.set()
        if self.stop_after == self.reads:
            self.stop.set()
        if self.failures is None or self.reads <= self.failures:
            raise OSError("Native FTDI read failed: IO_ERROR")
        time.sleep(.001)
        return object()


def _run_source(device, observer, duration=.12, *, pvfs=False):
    events = []
    device = _SourceLifecycleProxy(device, device.stop, None)
    if pvfs:
        subscribe = pvfs_acquisition._stream(device, duration, device.stop, events.append, 500, 1, None)
    else:
        subscribe = legacy_source._stream_from_pod_device(device, duration, device.stop, events.append)
    subscribe(observer, None)
    return events


class Monitor:
    def __init__(self, errors):
        self.errors = list(errors)
        self.restart_calls = 0
        self.state = {"state": "running"}

    def get_stream_status(self, _index):
        return {"worker_status": "missing", "worker_exitcode": None}

    def get_lifecycle_state(self, _index):
        return self.state

    def set_lifecycle_state(self, _index, state, **kwargs):
        self.state = {"state": state, **kwargs}
        return self.state

    @contextmanager
    def stream_lifecycle_guard(self, _index, **_kwargs):
        yield None

    def is_stream_port_present(self, _index):
        return True

    def is_stream_port_openable(self, _index):
        return True

    def restart_one_stream(self, _index):
        self.restart_calls += 1
        error = self.errors.pop(0) if self.errors else None
        return {"ok": error is None, "error": error}

    def poll_stream_queue_roundtrip(self, **_kwargs):
        return {"ok": True}


def watcher(monitor):
    return StreamWatcher(0, monitor, failure_threshold=3, max_heartbeat_age_sec=10,
                                     interval_sec=.01, timeout_sec=.01, recovery_policy="automate",
                                     max_auto_restart_attempts=3, publish=lambda *_args: None)


class _DisconnectContract:
    pvfs = False

    def run_source(self, device, observer, duration=.12):
        return _run_source(device, observer, duration, pvfs=self.pvfs)

    def test_immediate_error_retry_is_bounded(self):
        device = Device(threading.Event())
        self.run_source(device, Observer())
        self.assertLessEqual(device.reads, 100, "100 retries in120ms already allows far more than a settling USB device needs")

    def test_stop_interrupts_retry_and_other_source_continues(self):
        failed = Device(threading.Event())
        healthy = Device(threading.Event(), failures=0)
        healthy_observer = Observer()
        errors = []

        def acquire(device, observer):
            try:
                self.run_source(device, observer, 2)
            except BaseException as error:
                errors.append(error)

        failed_thread = threading.Thread(target=acquire, args=(failed, Observer()), daemon=True)
        healthy_thread = threading.Thread(target=acquire, args=(healthy, healthy_observer), daemon=True)
        failed_thread.start()
        healthy_thread.start()
        try:
            self.assertTrue(failed.first_read.wait(.5))
            deadline = time.monotonic() + .5
            while healthy_observer.samples < 5 and time.monotonic() < deadline:
                time.sleep(.002)
            self.assertGreaterEqual(healthy_observer.samples, 5)
            before = healthy_observer.samples
            started = time.monotonic()
            failed.stop.set()
            failed_thread.join(.5)
            self.assertFalse(failed_thread.is_alive())
            self.assertLess(time.monotonic() - started, .5)
            time.sleep(.02)
            self.assertGreater(healthy_observer.samples, before)
            self.assertFalse(errors)
        finally:
            failed.stop.set()
            healthy.stop.set()
            failed_thread.join(.5)
            healthy_thread.join(.5)

    def test_source_resumes_after_transient_io_errors(self):
        device = Device(threading.Event(), failures=2, stop_after=4)
        observer = Observer()
        events = self.run_source(device, observer, 1)
        self.assertEqual(observer.samples, 2)
        self.assertTrue(observer.completed)
        self.assertIn("recovered", [event["state"] for event in events])
        self.assertEqual(device.closes, 1)

    def test_successful_exit_closes_port(self):
        device = Device(threading.Event(), failures=0, stop_after=1)
        self.run_source(device, Observer(), 1)
        self.assertEqual(device.closes, 1)

    def test_exit_error_still_closes_port(self):
        device = Device(threading.Event(), stop_after=1, exit_error=OSError("Native FTDI write failed: IO_ERROR"))
        try:
            self.run_source(device, Observer(), 1)
        except OSError:
            pass
        self.assertEqual(device.closes, 1)

    def test_close_failure_is_visible(self):
        device = Device(threading.Event(), stop_after=1, close_error=OSError("close ownership unresolved"))
        with self.assertRaisesRegex(OSError, "close ownership unresolved"):
            self.run_source(device, Observer(), 1)

    def test_exit_and_close_failure_preserve_close_error(self):
        device = Device(threading.Event(), stop_after=1,
                        exit_error=OSError("Native FTDI write failed: IO_ERROR"),
                        close_error=OSError("close ownership unresolved"))
        with self.assertRaisesRegex(OSError, "close ownership unresolved"):
            self.run_source(device, Observer(), 1)
        self.assertEqual(device.closes, 1)

    def test_native_io_error_matches_permissionerror_recovery(self):
        outcomes = []
        for message in ("DeviceError: IO_ERROR", "OSError: Native FTDI read failed: IO_ERROR", "PermissionError: Access is denied"):
            monitor = Monitor([message] * 5)
            subject = watcher(monitor)
            results = []
            for _tick in range(25):
                result = subject._try_reconnect()
                results.append(result)
                if result["ok"]:
                    break
            self.assertTrue(results[-1]["ok"], message)
            self.assertEqual(results[-1]["action"], "connection_restored")
            self.assertNotIn("needs_action", [result["action"] for result in results])
            self.assertEqual(monitor.restart_calls, 6)
            self.assertEqual(subject._recovery_attempt_count, 0)
            outcomes.append(monitor.state["state"])
        self.assertEqual(outcomes, ["running"] * 3)

    def test_unrelated_restart_errors_exhaust_budget(self):
        for message in ("RuntimeError: database is corrupt", "DeviceError: INVALID_PARAMETER", "RuntimeError: IO_ERROR_COUNTER invalid", "RuntimeError: not IO_ERROR"):
            with self.subTest(message=message):
                monitor = Monitor([message] * 8)
                subject = watcher(monitor)
                results = [subject._try_reconnect() for _ in range(4)]
                self.assertEqual(results[-1]["action"], "needs_action")
                self.assertEqual(monitor.restart_calls, 3)


class TestDashboardDefaultUsbDisconnect(_DisconnectContract, unittest.TestCase):
    pass


class TestManagedPvfsUsbDisconnect(_DisconnectContract, unittest.TestCase):
    pvfs = True
