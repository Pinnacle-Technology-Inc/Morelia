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
from dataclasses import dataclass
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

# failure_kind vocabulary
SINK_FAILURE_WRITE = "sink_write"
SOURCE_FAILURE_READ = "source_read"
# state vocabulary
SINK_STATE_TERMINAL = "terminal"
SINK_STATE_DEGRADED = "degraded"
SOURCE_STATE_DEGRADED = "degraded"
SOURCE_STATE_RECOVERED = "recovered"
# Bound so a hostile/huge exception message cannot blow up durable telemetry.
_MAX_SINK_ERROR_MESSAGE = 500
_MAX_SOURCE_ERROR_MESSAGE = 500
_SOURCE_ERROR_EMIT_INTERVAL_SEC = 1.0


@dataclass(frozen=True)
class SinkError:
    """One attributable sink-write failure event.

    :param source_id: Stable identity of the source feeding the sink.
    :param sink_id: Stable identity of the failing sink 
    :param sink_class: Concrete sink class name.
    :param failure_kind: One of the ``SINK_FAILURE_*`` vocabulary.
    :param exception_type: ``type(exc).__name__`` of the raised exception.
    :param message: Bounded/redacted ``str(exc)``.
    :param state: One of the ``SINK_STATE_*`` vocabulary.
    :param last_success_seq: Count of successful ``flush`` calls before this
        failure (the last successful delivery/write), or ``None`` if unknown.
    :param timestamp_ns: ``time.time_ns()`` when the event was created.
    """

    source_id: str
    sink_id: str
    sink_class: str
    failure_kind: str
    exception_type: str
    message: str
    state: str
    last_success_seq: int | None
    timestamp_ns: int


@dataclass(frozen=True)
class SourceReadStatus:
    """One bounded source-read state transition or periodic failure update."""

    source_id: str
    source_port: str | None
    failure_kind: str
    exception_type: str | None
    message: str | None
    state: str
    consecutive_failures: int
    timestamp_ns: int


def _source_identity(pod) -> str:
    """Return a stable source identity string for telemetry."""
    name = getattr(pod, "device_name", None)
    if isinstance(name, str) and name:
        return name
    return type(pod).__name__


def _source_port(pod) -> str | None:
    """Return the configured source port without exposing a live handle."""
    for attr in ("port", "_port_name", "_name"):
        value = getattr(pod, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def _sink_identity(sink) -> str:
    """Prefer an explicit ``sink_id`` (set by managed backend sinks); else the class name."""
    sink_id = getattr(sink, "sink_id", None)
    if isinstance(sink_id, str) and sink_id:
        return sink_id
    return type(sink).__name__


def _redact_sink_message(exc: BaseException) -> str:
    """Bound the exception message so a single event stays small and safe to persist."""
    text = str(exc)
    if len(text) > _MAX_SINK_ERROR_MESSAGE:
        return text[:_MAX_SINK_ERROR_MESSAGE] + "...[truncated]"
    return text


def _redact_source_message(exc: BaseException) -> str:
    """Bound source exception text before it crosses the worker boundary."""
    text = str(exc)
    if len(text) > _MAX_SOURCE_ERROR_MESSAGE:
        return text[:_MAX_SOURCE_ERROR_MESSAGE] + "...[truncated]"
    return text


def _build_sink_error(dispatch: "_SinkDispatch", exc: BaseException, state: str) -> SinkError:
    """Construct the structured event for a sink dispatch that just failed."""
    return SinkError(
        source_id=dispatch.source_id,
        sink_id=_sink_identity(dispatch.sink),
        sink_class=type(dispatch.sink).__name__,
        failure_kind=SINK_FAILURE_WRITE,
        exception_type=type(exc).__name__,
        message=_redact_sink_message(exc),
        state=state,
        last_success_seq=dispatch.success_count,
        timestamp_ns=time.time_ns(),
    )


def _emit_sink_error(on_sink_error, event: SinkError) -> None:
    """Deliver ``event`` without ever letting reporting crash acquisition.

    With no callback configured, the failure is logged so tests do not depend on stdout text. 
    If the callback itself raises, the exception is swallowed and logged: acquisition and healthy 
    sibling sinks keep running.
    """
    if on_sink_error is None:
        _log.error(
            "sink write failed source=%s sink=%s (%s) %s: %s [state=%s last_success_seq=%s]",
            event.source_id,
            event.sink_id,
            event.sink_class,
            event.exception_type,
            event.message,
            event.state,
            event.last_success_seq,
        )
        return
    try:
        on_sink_error(event)
    except Exception:
        _log.error(
            "on_sink_error callback raised for sink=%s; acquisition continues",
            event.sink_id,
            exc_info=True,
        )


def _emit_source_status(on_source_error, event: SourceReadStatus) -> None:
    """Deliver source-read telemetry without allowing reporting to stop acquisition."""
    if on_source_error is None:
        log = _log.info if event.state == SOURCE_STATE_RECOVERED else _log.warning
        log(
            "source read status source=%s port=%s state=%s error=%s failures=%s message=%s",
            event.source_id,
            event.source_port,
            event.state,
            event.exception_type,
            event.consecutive_failures,
            event.message,
        )
        return
    try:
        on_source_error(event)
    except Exception:
        _log.error(
            "on_source_error callback raised for source=%s; acquisition continues",
            event.source_id,
            exc_info=True,
        )


class _SinkDispatch:
    """Deliver source data to one sink and turn write failures into one event.
    
    This process is indendpent per source to sink pair, so sibling sink will not be
    interrupted
    """

    __slots__ = ("sink", "source_id", "_on_sink_error", "success_count", "failed")

    def __init__(self, sink, source_id: str, on_sink_error) -> None:
        self.sink = sink
        self.source_id = source_id
        self._on_sink_error = on_sink_error
        self.success_count = 0
        self.failed = False

    def send(self, args) -> None:
        if self.failed:
            return
        try:
            self.sink.flush(*args)
        except Exception as exc:
            self._handle_write_error(exc)
        else:
            self.success_count += 1

    def send_batch(self, batch) -> None:
        if self.failed:
            return
        for args in batch:
            try:
                self.sink.flush(*args)
            except Exception as exc:
                self._handle_write_error(exc)
                return
            self.success_count += 1

    def _handle_write_error(self, exc: BaseException) -> None:
        self.failed = True
        _emit_sink_error(self._on_sink_error, _build_sink_error(self, exc, SINK_STATE_TERMINAL))

    def on_stream_error(self, exc: BaseException) -> None:
        """Handle a source/upstream stream error routed to this subscription.

        """
        _log.error(
            "source stream error delivered to sink=%s source=%s: %s: %s",
            _sink_identity(self.sink),
            self.source_id,
            type(exc).__name__,
            _redact_sink_message(exc),
        )


def _subscribe_sink(stream, sink, source_id: str, on_sink_error, batch_size: int) -> "_SinkDispatch":
    """Subscribe one sink to ``stream`` with structured error reporting based on the old report code.

    Returns the dispatch so callers/tests can inspect delivery state.
    """
    dispatch = _SinkDispatch(sink, source_id, on_sink_error)
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
):
    # Use fixed-size streaming read when available (1-2 read() per packet instead of many) for higher throughput
    read_fn = getattr(pod, "read_pod_packet_streaming", None)
    use_streaming = callable(read_fn)
    stream_timeout_sec = 0.2  # allow time for partial reads (e.g. 8206) and USB scheduling; still detects stall

    def _stream_from_pod_device_observable(observer, scheduler) -> None:
        source_id = _source_identity(pod)
        source_port = _source_port(pod)
        consecutive_failures = 0
        last_error_emitted_at = 0.0
        last_read_error = None
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
                    if (
                        consecutive_failures == 1
                        or now - last_error_emitted_at >= _SOURCE_ERROR_EMIT_INTERVAL_SEC
                    ):
                        _emit_source_status(
                            on_source_error,
                            SourceReadStatus(
                                source_id=source_id,
                                source_port=source_port,
                                failure_kind=SOURCE_FAILURE_READ,
                                exception_type=type(e).__name__,
                                message=_redact_source_message(e),
                                state=SOURCE_STATE_DEGRADED,
                                consecutive_failures=consecutive_failures,
                                timestamp_ns=time.time_ns(),
                            ),
                        )
                        last_error_emitted_at = now
                    continue
                if consecutive_failures:
                    _emit_source_status(
                        on_source_error,
                        SourceReadStatus(
                            source_id=source_id,
                            source_port=source_port,
                            failure_kind=SOURCE_FAILURE_READ,
                            exception_type=type(last_read_error).__name__,
                            message=_redact_source_message(last_read_error),
                            state=SOURCE_STATE_RECOVERED,
                            consecutive_failures=consecutive_failures,
                            timestamp_ns=time.time_ns(),
                        ),
                    )
                    consecutive_failures = 0
                    last_read_error = None
                observer.on_next(packet)
        # After exiting "with pod": __exit__ has run (STREAM 0 sent, read buffer drained).
        # Now close the port so the USB/D2XX handle is released cleanly.
        pod.close_port()

        # tell the observer we are finished.
        observer.on_completed()
    return _stream_from_pod_device_observable

#function used by reactivex to place raw packets (binary) into the read queue
def make_packet_putter(read_queue):
    def put_read_packet(item):
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
        )
    )

    # create background queue 
    def background_writer(pod: AcquisitionDevice):
        while True:
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
            _subscribe_sink(stream, sink, source_id, on_sink_error, _OBSERVE_ON_BATCH_SIZE) # Sink write failures are reported through ``on_sink_error``instead of being printed. 

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
    """Bind the worker-local reporter to sinks that expose the optional hook.

    Binding happens only after multiprocessing reconstruction, so callbacks do
    not need to be serialized inside sink dictionaries. Legacy sinks without
    the hook retain their existing behavior.
    """
    for sink in sinks:
        bind = getattr(sink, "bind_error_callback", None)
        if callable(bind):
            bind(on_sink_error)
