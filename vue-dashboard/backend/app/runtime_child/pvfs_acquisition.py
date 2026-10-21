"""Keep PVFS native writes on the acquisition worker while a device reconnects."""

import math
import time
from contextlib import ExitStack, suppress

import reactivex as rx
from Morelia.packet import ControlPacket
from Morelia.Stream import source as legacy_source
from reactivex import operators as ops

from app.runtime_child.device_connection import current_connection_address


def _is_managed_pvfs(sink):
    return any(cls.__module__ == "app.output.managed_pvfs_sink" for cls in type(sink).__mro__)


def _refresh_source(pod, reconnect_config):
    """Resolve the same physical device before replacing its released port handle."""
    if reconnect_config is None:
        return False
    device_flow, device_type = reconnect_config
    address = current_connection_address(device_flow, device_type)
    source = getattr(pod, "_source", pod)
    if not getattr(source, "_backend_managed", False):
        raise RuntimeError("Device address refresh requires a backend-managed source")
    source.close_port()
    source._port_value = address
    source._name = address
    source.open_port()
    source.write_packet("STREAM", 1)
    return True


def _stream(
    pod,
    duration,
    stop_event,
    on_source_error,
    max_error_message_chars,
    source_error_emit_interval_sec,
    reconnect_config,
):
    def subscribe(observer, _scheduler):
        rate = float(pod.sample_rate)
        window = getattr(pod, "_source_recovery_window_sec", None)
        enabled = isinstance(window, (float, int)) and math.isfinite(window) and window > 0
        source_id = legacy_source._source_identity(pod)
        if reconnect_config is not None:
            source_id = getattr(reconnect_config[0], "device_id", source_id)
        started = last_real = time.monotonic()
        failure_start = None
        placeholders = failures = 0
        last_status = last_reconnect = float("-inf")
        read = getattr(pod, "read_pod_packet_streaming", None)

        def report(state, exc, now):
            legacy_source._emit_source_status(
                on_source_error,
                {
                    "source_id": source_id,
                    "source_port": legacy_source._source_port(pod),
                    "failure_kind": "source_read",
                    "exception_type": type(exc).__name__,
                    "message": legacy_source._bounded_error_message(exc, max_error_message_chars),
                    "state": state,
                    "consecutive_failures": failures,
                    "timestamp_ns": time.time_ns(),
                    "disconnect_elapsed_seconds": max(0.0, now - last_real),
                },
            )

        def fill(now, *, resumed=False):
            nonlocal placeholders
            positions = min(now - failure_start, window) * rate
            expected = max(
                placeholders, max(0, math.ceil(positions) - 1 if resumed else int(positions))
            )
            for _ in range(expected - placeholders):
                observer.on_next(legacy_source.MissingSample())
            placeholders = expected

        try:
            with pod:
                started = last_real = time.monotonic()
                while time.monotonic() - started < duration and not stop_event.is_set():
                    # Device commands and port replacement share this owning thread.
                    try:
                        pod.check_write_queue()
                        packet = (
                            read(timeout_sec=0.2, validate_checksum=False)
                            if callable(read)
                            else pod.read_pod_packet()
                        )
                    except Exception as exc:
                        now = time.monotonic()
                        failures += 1
                        if enabled:
                            if failure_start is None:
                                failure_start = last_real
                            fill(now)
                            if now - failure_start >= window:
                                report("recovery_window_expired", exc, now)
                                stop_event.set()
                                break
                            if now - last_reconnect >= 0.5:
                                last_reconnect = now
                                with suppress(Exception):
                                    _refresh_source(pod, reconnect_config)
                        if failures == 1 or now - last_status >= source_error_emit_interval_sec:
                            report("degraded", exc, now)
                            last_status = now
                        # Unplugged drivers can fail immediately; Stop must interrupt the retry wait.
                        stop_event.wait(0.1)
                        continue
                    now = time.monotonic()
                    if failure_start is not None and now - failure_start >= window:
                        fill(now)
                        report(
                            "recovery_window_expired",
                            TimeoutError("device recovery window expired"),
                            now,
                        )
                        stop_event.set()
                        break
                    if isinstance(packet, ControlPacket):
                        if failure_start is not None:
                            fill(now)
                        observer.on_next(packet)
                        continue
                    if failure_start is not None:
                        fill(now, resumed=True)
                    if failures:
                        report("recovered", RuntimeError("source read resumed"), now)
                    failures = placeholders = 0
                    failure_start = None
                    last_real = now
                    observer.on_next(packet)
        finally:
            pod.close_port()
        observer.on_completed()

    return subscribe


def get_data(
    duration,
    manual_stop_event,
    pod,
    sinks,
    *,
    on_sink_error=None,
    on_source_error=None,
    max_error_message_chars=500,
    source_error_emit_interval_sec=1.0,
    reconnect_config=None,
):
    """Dispatch PVFS on its owner thread and retain the writer during brief outages."""
    if pod._port is None:
        pod.open_port()
    disconnected = False

    def source_status(event):
        nonlocal disconnected
        if event.get("state") == "recovery_window_expired":
            disconnected = True
        legacy_source._emit_source_status(on_source_error, event)

    def close_pvfs(sink, exc_type, exc, traceback):
        if not disconnected:
            return sink.__exit__(exc_type, exc, traceback)
        sink.close(termination_reason="source_disconnect")
        return False

    put_control = legacy_source.make_packet_putter(pod.obtain_read_queue())
    stream = rx.create(
        _stream(
            pod,
            duration,
            manual_stop_event,
            source_status,
            max_error_message_chars,
            source_error_emit_interval_sec,
            reconnect_config,
        )
    ).pipe(
        ops.do_action(
            lambda packet: put_control(packet) if isinstance(packet, ControlPacket) else None
        ),
        ops.filter(lambda packet: not isinstance(packet, ControlPacket)),
        legacy_source._timestamp_via_adjusted_sample_rate(pod.sample_rate),
        ops.publish(),
    )
    source_id = legacy_source._source_identity(pod)
    with ExitStack() as stack:
        stack.callback(pod.close_port)
        for sink in sinks:
            try:
                sink.__enter__()
            except BaseException as startup_error:
                close = getattr(sink, "close", None)
                if callable(close):
                    try:
                        close()
                    except BaseException as cleanup_error:
                        raise startup_error from cleanup_error
                raise
            if _is_managed_pvfs(sink):
                stack.push(lambda *args, sink=sink: close_pvfs(sink, *args))
                # Native handles and SQLAlchemy sessions stay on the worker thread.
                dispatch = legacy_source._SinkDispatch(
                    sink, source_id, on_sink_error, max_error_message_chars
                )
                stream.subscribe(on_next=dispatch.send, on_error=dispatch.on_stream_error)
            else:
                stack.push(sink)
                legacy_source._subscribe_sink(
                    stream, sink, source_id, on_sink_error, 100, max_error_message_chars
                )
        stream.connect()
