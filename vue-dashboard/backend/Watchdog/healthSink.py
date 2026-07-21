"""Sink that reports a rich data-health status from the worker to the main process."""

import time

from Morelia.Stream.sink import SinkInterface


class HealthSink(SinkInterface):
    """
    Pass-through sink that stamps shared status whenever data flows.

    Append one per stream so the watchdog can tell "worker is receiving
    samples" apart from "worker only answers PINGs". The worker writes the
    status; the main process reads it back out of the same shared dict.

    Unlike a single-float heartbeat, this records several namespaced fields
    per stream (last wall-clock time data arrived, the stream's own sample
    timestamp, and a flowing flag), so one shared object can serve many
    streams at once.

    :param shared_status: a ``multiprocessing.Manager().dict()`` created by
        the main process. It MUST be a Manager dict, not a plain ``dict`` --
        a plain dict pickled into the worker becomes a private copy and the
        main process never sees the writes. The Manager proxy crosses the
        process boundary through mp.Process args (same pattern BufferSink
        uses for its shared buffer) and both sides see updates.
    :param stream_name: key prefix identifying which stream this sink
        monitors, e.g. ``"pod8206hr.A"``. Lets one shared_status hold the
        status of every stream without collisions.
    :param pod: POD device data is being streamed from. Unused here, but
        every sink must accept it because get_data_wrapper injects it
        when rebuilding sinks inside the worker.
    :param min_interval_sec: Stamp at most this often, so the per-sample
        cost stays negligible at kHz sample rates. Each write is an IPC
        round-trip over the Manager proxy, so throttling matters even more
        here than for a plain shared Value.
    """

    def __init__(self, shared_status, stream_name: str, pod=None,
                 min_interval_sec: float = 0.25) -> None:
        self._shared_status = shared_status
        self._stream_name = stream_name
        self._min_interval_sec = min_interval_sec
        self._last_stamp = 0.0
        self._packet_count = int(self._shared_status.get(f"{self._stream_name}.packet_count",0))

    # get_data() enters every sink through an ExitStack, so the context
    # manager protocol is required even though there is nothing to open.
    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        return False

    def flush(self, timestamp: int, packet) -> None:
        # timestamp is the stream's nanosecond sample clock; last_data_time
        # uses wall time instead so the monitor can compare against now.
        self._packet_count += 1
        now = time.time()
        if now - self._last_stamp >= self._min_interval_sec:
            prefix = self._stream_name
            self._shared_status[f'{prefix}.last_data_time'] = now
            self._shared_status[f'{prefix}.last_stream_timestamp'] = timestamp
            self._shared_status[f'{prefix}.data_flowing'] = True
            self._shared_status[f"{prefix}.packet_count"] = self._packet_count
            self._last_stamp = now

    def get_dict(self) -> dict:
        # The shared Manager dict rides along in the snapshot, so sinks
        # rebuilt by restart_one_stream / restart_all_stream keep writing to
        # the SAME shared status -- no re-registration needed after a
        # restart. ``pod`` is omitted on purpose; get_data_wrapper injects it.
        return {
            "shared_status": self._shared_status,
            "stream_name": self._stream_name,
            "min_interval_sec": self._min_interval_sec,
        }
