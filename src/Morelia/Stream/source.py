"""Functions for getting streaming data from a POD device using `ReactiveX (RxPy) <https://rxpy.readthedocs.io/en/latest/index.html>`_."""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

#environment imports
import signal
import sys
import traceback
import logging
from multiprocessing import Event
import threading
import time
from functools import partial
from contextlib import ExitStack

#local imports
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

from Morelia.packet import ControlPacket

import reactivex as rx
from reactivex import operators as ops
from reactivex.operators import do_action

_log = logging.getLogger(__name__)


class MissingSample:
    """Insert fill-in blank sample during source disconnect
    """

    is_missing_sample = True

    def __getattr__(self, name):
        # Legacy 8274 sinks iterate these packet fields; the other POD sinks
        # read scalar channel attributes. One marker always represents one
        # sample, regardless of device packet shape.
        if name in {"ch5", "ch6", "ch7"}:
            return (float("nan"),)
        return float("nan")


def _source_identity(pod) -> str:
    """Return the configured device name, or its class name when none is set."""
    name = getattr(pod, "device_name", None)
    if isinstance(name, str) and name:
        return name
    return type(pod).__name__


def _source_port(pod) -> str | None:
    """Return the configured port name without probing hardware."""
    for attr in ("port", "_port_name", "_name"):
        value = getattr(pod, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def _source_port_is_present(pod, source_port: str | None) -> bool | None:
    """Check whether the configured port appears in the operating system.

    Returns ``True`` when present, ``False`` when absent, and ``None`` when the
    port list cannot be read.
    """
    if source_port is None:
        return False
    expected = source_port.lower()
    try:
        if getattr(pod, "_use_d2xx", False):
            from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices

            for device in list_d2xx_devices():
                identifiers = {
                    str(device.get(key, "")).lower()
                    for key in ("index", "serial", "description")
                }
                if expected in identifiers:
                    return True
            return False

        import serial.tools.list_ports

        return any(
            str(port_info.device).lower() == expected
            for port_info in serial.tools.list_ports.comports()
        )
    except Exception:
        return None


def _sink_identity(sink) -> str:
    """Return a sink's configured ID, or its class name when no ID is set."""
    sink_id = getattr(sink, "sink_id", None)
    if isinstance(sink_id, str) and sink_id:
        return sink_id
    return type(sink).__name__


def _bounded_error_message(exc: BaseException, max_chars: int) -> str:
    """Convert an exception to text and truncate it to ``max_chars`` characters."""
    text = str(exc)
    if len(text) > max_chars:
        return text[:max_chars] + "...[truncated]"
    return text


def _build_sink_error(
    dispatch: "_SinkDispatch",
    exc: BaseException,
    state: str,
) -> dict[str, object]:
    """Describe one sink write failure using plain, process-safe values."""
    return {
        "source_id": dispatch.source_id,
        "sink_id": _sink_identity(dispatch.sink),
        "sink_class": type(dispatch.sink).__name__,
        "failure_kind": "sink_write",
        "exception_type": type(exc).__name__,
        "message": _bounded_error_message(exc, dispatch.max_error_message_chars),
        "state": state,
        "last_success_seq": dispatch.success_count,
        "timestamp_ns": time.time_ns(),
    }


def _emit_sink_error(on_sink_error, event: dict[str, object]) -> None:
    """Send a sink failure to its callback, or write it to the application log.

    Reporting errors are logged and swallowed so they cannot stop acquisition
    or interrupt healthy sinks.
    """
    if on_sink_error is None:
        _log.error(
            "sink write failed source=%s sink=%s (%s) %s: %s [state=%s last_success_seq=%s]",
            event["source_id"],
            event["sink_id"],
            event["sink_class"],
            event["exception_type"],
            event["message"],
            event["state"],
            event["last_success_seq"],
        )
        return
    try:
        on_sink_error(event)
    except Exception:
        _log.error(
            "on_sink_error callback raised for sink=%s; acquisition continues",
            event["sink_id"],
            exc_info=True,
        )


def _emit_source_status(on_source_error, event: dict[str, object]) -> None:
    """Send a source status update without intefering acquisition."""
    if on_source_error is None:
        log = _log.info if event["state"] == "recovered" else _log.warning
        log(
            "source read status source=%s port=%s state=%s error=%s failures=%s message=%s",
            event["source_id"],
            event["source_port"],
            event["state"],
            event["exception_type"],
            event["consecutive_failures"],
            event["message"],
        )
        return
    try:
        on_source_error(event)
    except Exception:
        _log.error(
            "on_source_error callback raised for source=%s; acquisition continues",
            event["source_id"],
            exc_info=True,
        )


class _SinkDispatch:
    """Deliver samples to one sink and isolate that sink if a write fails.

    Each source-to-sink pair has its own dispatch, so one failed sink does not
    interrupt the other sinks receiving data from the same source.
    """

    __slots__ = (
        "sink",
        "source_id",
        "max_error_message_chars",
        "_on_sink_error",
        "success_count",
        "failed",
    )

    def __init__(
        self,
        sink,
        source_id: str,
        on_sink_error,
        max_error_message_chars: int = 500,
    ) -> None:
        self.sink = sink
        self.source_id = source_id
        self.max_error_message_chars = max_error_message_chars
        self._on_sink_error = on_sink_error
        self.success_count = 0
        self.failed = False

    def send(self, args) -> None:
        """Write one timestamped sample unless this sink has already failed."""
        if self.failed:
            return
        if self._skip_missing_sample(args):
            return
        try:
            self.sink.flush(*args)
        except Exception as exc:
            self._handle_write_error(exc)
        else:
            self.success_count += 1

    def send_batch(self, batch) -> None:
        """Write a batch in order, stopping at the first sink failure."""
        if self.failed:
            return
        for args in batch:
            if self._skip_missing_sample(args):
                continue
            try:
                self.sink.flush(*args)
            except Exception as exc:
                self._handle_write_error(exc)
                return
            self.success_count += 1

    def _skip_missing_sample(self, args) -> bool:
        """Return whether this sink cannot represent the missing-sample marker."""
        if not isinstance(args, (tuple, list)) or len(args) < 2:
            return False
        packet = args[1]
        return bool(
            getattr(packet, "is_missing_sample", False)
            and not getattr(self.sink, "supports_missing_samples", False)
        )

    def _handle_write_error(self, exc: BaseException) -> None:
        """Disable this sink and report its first write failure."""
        self.failed = True
        _emit_sink_error(
            self._on_sink_error,
            _build_sink_error(self, exc, "terminal"),
        )

    def on_stream_error(self, exc: BaseException) -> None:
        """Log an upstream source error without misreporting it as a sink failure."""
        _log.error(
            "source stream error delivered to sink=%s source=%s: %s: %s",
            _sink_identity(self.sink),
            self.source_id,
            type(exc).__name__,
            _bounded_error_message(exc, self.max_error_message_chars),
        )


def _subscribe_sink(
    stream,
    sink,
    source_id: str,
    on_sink_error,
    batch_size: int,
    max_error_message_chars: int = 500,
) -> "_SinkDispatch":
    """Connect one sink to a stream with isolated write-failure reporting.
    """
    dispatch = _SinkDispatch(sink, source_id, on_sink_error, max_error_message_chars)
    s = stream
    scheduler_spec = getattr(sink, "observe_on_scheduler", None)
    if scheduler_spec is not None:
        scheduler = _scheduler_for(scheduler_spec)
        if scheduler is not None:
            s = s.pipe(
                ops.buffer_with_count(batch_size),
                ops.observe_on(scheduler),
            )
            s.subscribe(on_next=dispatch.send_batch, on_error=dispatch.on_stream_error)
            return dispatch
    s.subscribe(on_next=dispatch.send, on_error=dispatch.on_stream_error)
    return dispatch

# Optional: schedulers for observe_on (decouple slow sinks from emission thread)
def _scheduler_for(spec):  # noqa: C901
    """Return a scheduler for the given spec, or None. Used by sinks that set observe_on_scheduler."""
    if spec is None:
        return None
    if spec == "thread_pool":
        try:
            from reactivex.scheduler import ThreadPoolScheduler
            return ThreadPoolScheduler()
        except ImportError:
            return None
    if spec == "new_thread":
        try:
            from reactivex.scheduler import NewThreadScheduler
            return NewThreadScheduler()
        except ImportError:
            return None
    return None

#TODO: __all__ to tell us what to export.

#TODO: type hints
#reactivex operator to timestamp packets as we get them based on the average observed sample
#rate (# total packets/time elapsed). this way, our timestamps are more evenly distributed
#and more closely resemble the time at which they were read from the device (as opposed
#to things like transfer and buffering delays by the OS/USB messign with things.
def _timestamp_via_adjusted_sample_rate(starting_sample_rate: int):
    def _timestamp_via_adjusted_sample_rate_operator(source):
        def subscribe(observer, scheduler=None):

            # Ensure starting_sample_rate is valid (must be > 0)
            # Store a safe fallback value that won't be modified
            safe_sample_rate = starting_sample_rate if starting_sample_rate and starting_sample_rate > 0 else 1000
            
            observer.sample_rate = safe_sample_rate
            observer.time_at_last_update = time.perf_counter()
            observer.starting_time = time.perf_counter()
            observer.last_timestamp = time.time_ns()
            observer.packet_count = 0
            
            def on_next(value):
                if getattr(value, "is_missing_sample", False):
                    observer.last_timestamp = int(
                        observer.last_timestamp + (10**9 / observer.sample_rate)
                    )
                    observer.on_next((observer.last_timestamp, value))
                    return
                now_real_time_ns = time.time_ns()
                # Guard against division by zero if sample_rate is invalid
                if observer.sample_rate <= 0:
                    observer.sample_rate = safe_sample_rate  # Reset to safe fallback value
                
                # Ensure sample_rate is still valid before division
                if observer.sample_rate > 0:
                    predicted = int(observer.last_timestamp + (10**9 / observer.sample_rate))
                else:
                    predicted = now_real_time_ns  # Fallback if sample_rate is still invalid
                    
                drift = now_real_time_ns - predicted

                correction_factor = 0.005

                #add on a fraction of the sample rate to last timestamp, plus drift correction
                observer.last_timestamp = int(predicted + (drift * correction_factor))

                # timestamps used to be this, without correction factors:
                # observer.last_timestamp = int(observer.last_timestamp + (10**9 / observer.sample_rate))

                # if predicted time is greater than current time, reset time stamps
                if observer.last_timestamp > now_real_time_ns: 
                    observer.last_timestamp = now_real_time_ns

                observer.packet_count += 1

                # if it's been more than a second...
                if time.perf_counter() - observer.time_at_last_update >= 1:
                    
                    # adjust sample rate to be closer to what we are actually getting
                    # Guard against division by zero if time difference is too small
                    time_diff = time.perf_counter() - observer.starting_time
                    if time_diff > 0.001 and observer.packet_count > 0:  # At least 1ms elapsed and packets received
                        new_rate = observer.packet_count / time_diff
                        # Ensure calculated rate is valid (must be > 0)
                        if new_rate > 0:
                            observer.sample_rate = new_rate
                        else:
                            observer.sample_rate = safe_sample_rate  # Fallback if calculation gives invalid value
                    # If time_diff is too small or no packets, keep current sample_rate
                
                    observer.time_at_last_update = time.perf_counter()

                # send packet and timestamp on its way.
                observer.on_next((observer.last_timestamp, value))

            return source.subscribe(on_next,
                observer.on_error,
                observer.on_completed,
                scheduler=scheduler)
        return rx.create(subscribe)
    return(_timestamp_via_adjusted_sample_rate_operator)

#TODO: type hints
#function used by reactivex to create an observable from a packet stream from an acquisition device.
def _stream_from_pod_device(
    pod: AcquisitionDevice,
    duration: float,
    manual_stop_event: Event,
    on_source_error=None,
    max_error_message_chars: int = 500,
    source_error_emit_interval_sec: float = 1.0,
):
    # Prefer the whole-packet reader because it needs fewer serial reads per packet.
    read_fn = getattr(pod, "read_pod_packet_streaming", None)
    use_streaming = callable(read_fn)
    # Allow partial packets and normal USB delays while still noticing a stalled stream quickly.
    stream_timeout_sec = 0.2

    def _stream_from_pod_device_observable(observer, scheduler) -> None:
        source_id = _source_identity(pod)
        source_port = _source_port(pod)
        consecutive_failures = 0
        last_error_emitted_at = 0.0
        last_read_error = None
        failure_started_at = None
        missing_samples_emitted = 0
        last_reopen_attempt_at = 0.0
        recovery_window_expired = False
        recovery_window_sec = getattr(pod, "_source_recovery_window_sec", None)
        recovery_enabled = (
            isinstance(recovery_window_sec, (int, float))
            and recovery_window_sec > 0
        )
        sample_rate = float(getattr(pod, "sample_rate", 0) or 0)
        last_real_sample_at = time.monotonic()

        def emit_missing_samples(now: float) -> None:
            """Emit placeholders for samples expected since the disconnect began."""
            nonlocal missing_samples_emitted
            if failure_started_at is None or sample_rate <= 0:
                return
            elapsed = min(now - failure_started_at, recovery_window_sec)
            expected = max(0, int(elapsed * sample_rate))
            for _ in range(expected - missing_samples_emitted):
                observer.on_next(MissingSample())
            missing_samples_emitted = expected

        try:
            with pod:
                stream_start_time : float = time.perf_counter()
                while time.perf_counter()-stream_start_time < duration and not manual_stop_event.is_set():

                    try:
                        if use_streaming:
                            packet = read_fn(timeout_sec=stream_timeout_sec, validate_checksum=False)
                        else:
                            packet = pod.read_pod_packet()
                    except Exception as e:
                        consecutive_failures += 1
                        last_read_error = e
                        now = time.monotonic()
                        # A positive recovery window enables reconnect handling.
                        # Without one, read failures continue through the normal retry loop.
                        port_present = (
                            _source_port_is_present(pod, source_port)
                            if recovery_enabled
                            else None
                        )
                        if (
                            recovery_enabled
                            and failure_started_at is None
                            and port_present is False
                        ):
                            failure_started_at = now - stream_timeout_sec
                            missing_samples_emitted = 0
                        if failure_started_at is not None:
                            emit_missing_samples(now)
                        if (
                            failure_started_at is not None
                            and now - last_reopen_attempt_at >= 0.5
                            and port_present is True
                        ):
                            last_reopen_attempt_at = now
                            try:
                                pod.close_port()
                                pod.open_port()
                                pod.write_packet("STREAM", 1)
                            except Exception:
                                # A reconnected port may be listed before the OS
                                # allows it to open. Keep filling the gap and retry.
                                pass
                        if (
                            consecutive_failures == 1
                            or now - last_error_emitted_at
                            >= source_error_emit_interval_sec
                        ):
                            _emit_source_status(
                                on_source_error,
                                {
                                    "source_id": source_id,
                                    "source_port": source_port,
                                    "failure_kind": "source_read",
                                    "exception_type": type(e).__name__,
                                    "message": _bounded_error_message(e, max_error_message_chars),
                                    "state": "degraded",
                                    "consecutive_failures": consecutive_failures,
                                    "timestamp_ns": time.time_ns(),
                                },
                            )
                            last_error_emitted_at = now
                        if (
                            failure_started_at is not None
                            and now - last_real_sample_at >= recovery_window_sec
                        ):
                            _emit_source_status(
                                on_source_error,
                                {
                                    "source_id": source_id,
                                    "source_port": source_port,
                                    "failure_kind": "source_read",
                                    "exception_type": type(e).__name__,
                                    "message": _bounded_error_message(e, max_error_message_chars),
                                    "state": "recovery_window_expired",
                                    "consecutive_failures": consecutive_failures,
                                    "timestamp_ns": time.time_ns(),
                                },
                            )
                            recovery_window_expired = True
                            break
                        continue
                    if consecutive_failures:
                        _emit_source_status(
                            on_source_error,
                            {
                                "source_id": source_id,
                                "source_port": source_port,
                                "failure_kind": "source_read",
                                "exception_type": type(last_read_error).__name__,
                                "message": _bounded_error_message(
                                    last_read_error,
                                    max_error_message_chars,
                                ),
                                "state": "recovered",
                                "consecutive_failures": consecutive_failures,
                                "timestamp_ns": time.time_ns(),
                            },
                        )
                        consecutive_failures = 0
                        last_read_error = None
                        failure_started_at = None
                        missing_samples_emitted = 0
                    last_real_sample_at = time.monotonic()
                    observer.on_next(packet)
        except Exception:
            # An expired recovery window is a controlled stop. Unexpected errors
            # still propagate to the caller.
            if not recovery_window_expired:
                raise
        # After exiting "with pod": __exit__ has run (STREAM 0 sent, read buffer drained).
        # Now close the port so the USB/D2XX handle is released cleanly.
        pod.close_port()

        # tell the observer we are finished.
        observer.on_completed()
    return _stream_from_pod_device_observable

#function used by reactivex to place raw packets (binary) into the read queue
def make_packet_putter(read_queue):
    """Create a callback that copies control-packet bytes into ``read_queue``."""
    def put_read_packet(item):
        """Queue one control packet without blocking the acquisition thread."""
        if isinstance(item, ControlPacket):
            try:
                read_queue.put_nowait(item._raw_packet)
            except Exception as e:
                print(f"[!] Failed to queue control packet: {e}")
    return put_read_packet

def get_data(
    duration: float,
    manual_stop_event: Event,
    pod: AcquisitionDevice,
    sinks,
    on_sink_error=None,
    on_source_error=None,
    max_error_message_chars: int = 500,
    source_error_emit_interval_sec: float = 1.0,
) -> None:
    """Streams data from the POD device. The data drops about every 1 second.
    Streaming will continue until a "stop streaming" packet is recieved.

    :param duration: How long to stream data for.
    :param manual_stop_event: Used to synchronize multiple ``get_data`` operations in a flowgraph. When a flowgraph is told to stop collecting, \
            this event is set which stops the loop within the reactivex operator that is collecting data.
    :param pod: The device to collect data from.
    :param on_sink_error: Optional callback invoked once per failing sink with a structured, attributable event. 
        If ``None``, sink failures are logged. A failing sink never crashes acquisition or its healthy sibling sinks.
    """
    
    # Ensure port is open before we need it (e.g. sample_rate via write_read). D2XX defers open to first use.
    if pod._port is None:
        pod.open_port()

    #obtain read_queue from pod device
    read_queue = pod.obtain_read_queue()

    #obtain put read packet from the closure function
    put_read_packet = make_packet_putter(read_queue)

    # create an observable to stream from POD device.
    device = rx.create(
        _stream_from_pod_device(
            pod,
            duration,
            manual_stop_event,
            on_source_error=on_source_error,
            max_error_message_chars=max_error_message_chars,
            source_error_emit_interval_sec=source_error_emit_interval_sec,
        )
    )

    # create background queue 
    def background_writer(pod: AcquisitionDevice):
        """Process queued device commands while the main loop reads samples."""
        while True:
            if getattr(pod, "_port", None) is None:
                time.sleep(0.005)
                continue
            try:
                pod.check_write_queue()
            except Exception as e:
                # Catch any unexpected errors to prevent thread from crashing
                # This ensures the program remains interruptable
                import sys
                print(f"Warning: Error in background_writer thread: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(0.005) # sleep to avoid CPU performance issues

    threading.Thread(target=background_writer, args=(pod,), daemon=True).start()

    # pipe the packets from ``device`` into a filter that throws out control packets (eventually we don't want to do this, but have
    # a seperate place these get put so they can still be read during streaming to enable feedback.),
    # and them timestamp packets.
    
    data = device.pipe(
           do_action(lambda item: put_read_packet(item) if isinstance(item, ControlPacket) else None),
           ops.filter(lambda i: not isinstance(i, ControlPacket)), #todo: more strict filtering
           _timestamp_via_adjusted_sample_rate(pod.sample_rate)
       )
     
    # create a function that outputs a connectable observable.
    streamer = ops.publish()
    
    # create a connectable observable from the pipeline we constructed earlier.
    stream = streamer(data)
   
    # now, subscribe each sink to the connectable observable. Since sinks implment the context manager protocol, we can use an ExitStack.
    # Sinks that set observe_on_scheduler (e.g. "thread_pool") run their flush() on that scheduler, so the emission thread is not blocked by slow sinks.
    
    _OBSERVE_ON_BATCH_SIZE = 100

    source_id = _source_identity(pod)

    with ExitStack() as context_manager_stack:

        for sink in sinks:
            context_manager_stack.enter_context(sink)
            _subscribe_sink(
                stream,
                sink,
                source_id,
                on_sink_error,
                _OBSERVE_ON_BATCH_SIZE,
                max_error_message_chars,
            )  # Sink write failures are reported through ``on_sink_error`` instead of being printed.

        # start streaming data from the observable!
        stream.connect()
        print("[DataFlow worker] stream.connect() returned, exiting sinks...", flush=True)

# wrapper function for get_data which reconstructs pod devices and sources after the process is created
def get_data_wrapper(
    duration_sec,
    manual_stop_event,
    source_class,
    source_dict,
    sinks_list,
    on_sink_error=None,
    on_source_error=None,
    max_error_message_chars: int = 500,
    source_error_emit_interval_sec: float = 1.0,
):
    # Ignore SIGINT (Ctrl+C) in the worker so only the main process handles it. The main process
    # sets manual_stop_event and joins; the worker then exits the loop and runs sink __exit__.
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass  # Windows or unsupported

    # obtain the source class
    source = source_class(**source_dict)

    # create list of sinks to use based on sink class/sink dictionary pair in the list
    sinks = [sink_class(**{**sink_dict, "pod": source}) for sink_class, sink_dict in sinks_list]
    _bind_sink_error_callbacks(sinks, on_sink_error)

    # run get_data with the pod device and list of sinks
    # on Ctrl+C or shutdown (e.g. stop_collection), worker may get KeyboardInterrupt or I/O errors;
    # exit cleanly so we don't dump a traceback when the main process is stopping us
    try:
        get_data(
            duration_sec,
            manual_stop_event,
            source,
            sinks,
            on_sink_error=on_sink_error,
            on_source_error=on_source_error,
            max_error_message_chars=max_error_message_chars,
            source_error_emit_interval_sec=source_error_emit_interval_sec,
        )
    except (KeyboardInterrupt, OSError, BrokenPipeError):
        if manual_stop_event.is_set():
            sys.exit(0)
        raise
    except BaseException:
        if manual_stop_event.is_set():
            sys.exit(0)
        raise


def _bind_sink_error_callbacks(sinks, on_sink_error) -> None:
    """Give supported sinks the error callback created for this worker.

    Binding after worker reconstruction avoids storing the callback in each
    sink's serialized settings. Sinks without the optional hook are unchanged.
    """
    for sink in sinks:
        bind = getattr(sink, "bind_error_callback", None)
        if callable(bind):
            bind(on_sink_error)
