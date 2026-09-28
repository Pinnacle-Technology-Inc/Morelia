"""Helper to help keep track of the first and last sample under a file to see how long 
have we been running one session. Use for reviewing past session
"""
from datetime import UTC, datetime, timedelta
import time


def sample_time(value):
    """Morelia sample times are integer Unix nanoseconds, not flush wall time."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        seconds, nanos = divmod(value, 1_000_000_000)
        return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanos // 1000)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    raise TypeError("Recorded sample timestamp must be Unix nanoseconds or a UTC datetime")


def bind_recording(sink, callback):
    sink._recording_callback = callback
    sink._recording_pending = None
    sink._recording_started = False
    sink._recording_last_report = 0.0


def buffer_sample_time(sink, timestamp):
    if getattr(sink, "_recording_callback", None) is None:
        return
    value = sample_time(timestamp)
    if value is None:
        return
    pending = getattr(sink, "_recording_pending", None)
    sink._recording_pending = (min(pending[0], value), max(pending[1], value)) if pending else (value, value)


def acknowledge_recording(sink, *, coalesce=False):
    pending = getattr(sink, "_recording_pending", None)
    callback = getattr(sink, "_recording_callback", None)
    if pending is None or callback is None:
        return
    now = time.monotonic()
    if coalesce and sink._recording_started and now - sink._recording_last_report < 1.0:
        return
    callback({
        "source_id": sink._device_id,
        "sink_id": sink._sink_id,
        "first_sample_at": pending[0].isoformat(),
        "last_sample_at": pending[1].isoformat(),
    })
    sink._recording_started = True
    sink._recording_last_report = now
    sink._recording_pending = None
