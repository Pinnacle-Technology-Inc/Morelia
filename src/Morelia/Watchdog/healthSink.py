"""Sink that reports a rich data-health status from the worker to the main process."""

import time
from functools import partial

from Morelia.ParamSchema.ParamSchema import ParamSchema
from Morelia.Stream.sink import SinkInterface

from Morelia.ParamSchema.ParamSchema import ParamSchema


class HealthSink(SinkInterface):
    """Pass-through sink that stamps shared status when data flows.

    One per stream to monitor the dataflow health and sample rate.

    :param shared_status: Dictionary shared between the worker and the main process.
    :param stream_name: Name that prefixes this stream's keys so statuses do not collide.
    :param pod: Device object. Unused here, but every sink must accept it.
    :param min_interval_sec: Do not update the shared status more often than this.
    :param rate_window_sec: How long to average packets when estimating sample rate.
    :param samples_per_packet: How many samples each packet carries (turns packet
        rate into sample rate).
    """

    def __init__(self, shared_status, stream_name: str, pod=None,
                 min_interval_sec: float = 0.25,
                 rate_window_sec: float = 5.0,
                 samples_per_packet: int = 1) -> None:
        self._shared_status = shared_status
        self._stream_name = stream_name
        self._min_interval_sec = min_interval_sec
        self._rate_window_sec = rate_window_sec
        self._samples_per_packet = samples_per_packet
        self._last_stamp = 0.0
        self._packet_count = int(self._shared_status.get(f"{self._stream_name}.packet_count",0))
        # Opened by the first packet rather than here: a worker that is slow to
        # produce its first packet would otherwise fold that startup delay into
        # the first window and report an artificially low rate.
        self._window_start = None
        self._window_start_count = self._packet_count

    # get_data() enters every sink through an ExitStack, so the context
    # manager protocol is required even though there is nothing to open.
    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        return False

    def flush(self, timestamp: int, packet) -> None:
        if getattr(packet, "is_missing_sample", False):
            return
        # timestamp is the stream's nanosecond sample clock; last_data_time
        # uses wall time instead so the monitor can compare against now.
        self._packet_count += 1
        now = time.time()
        if self._window_start is None:
            self._window_start = now
            self._window_start_count = self._packet_count
        if now - self._last_stamp >= self._min_interval_sec:
            prefix = self._stream_name
            self._shared_status[f'{prefix}.last_data_time'] = now
            self._shared_status[f'{prefix}.last_stream_timestamp'] = timestamp
            self._shared_status[f'{prefix}.data_flowing'] = True
            self._shared_status[f"{prefix}.packet_count"] = self._packet_count
            self._last_stamp = now

            # Publish an observed sample rate once per rate window. Riding
            # inside the throttled branch keeps the per-packet cost to the
            # window_start check above; the arithmetic runs ~once per 5s.
            elapsed = now - self._window_start
            if elapsed >= self._rate_window_sec:
                packets = self._packet_count - self._window_start_count
                self._shared_status[f"{prefix}.measured_sample_rate"] = (
                    packets * self._samples_per_packet / elapsed
                )
                self._window_start = now
                self._window_start_count = self._packet_count

    def get_dict(self) -> dict:
        # The shared Manager dict rides along in the snapshot, so sinks
        # rebuilt by restart_one_stream / restart_all_stream keep writing to
        # the SAME shared status -- no re-registration needed after a
        # restart. ``pod`` is omitted on purpose; get_data_wrapper injects it.
        return {
            "shared_status": self._shared_status,
            "stream_name": self._stream_name,
            "min_interval_sec": self._min_interval_sec,
            "rate_window_sec": self._rate_window_sec,
            "samples_per_packet": self._samples_per_packet,
        }

    @property
    def param_schema(self):
        return ParamSchema(
            required=frozenset(),
            optional=frozenset({
                "shared_status",
                "stream_name",
                "min_interval_sec",
                "rate_window_sec",
                "samples_per_packet",
            }),
            validators={},
        ),