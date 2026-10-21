"""Publish optional recording counters without writing on the acquisition thread."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import weakref
from datetime import UTC, datetime
from pathlib import Path


class RecordingDiagnostics:
    """Keep one atomic snapshot per sink for an independent resource collector."""

    def __init__(self, sink, directory: Path):
        self._sink = weakref.ref(sink)
        self._directory = directory
        identity = f"{sink._dataflow_id}:{sink._sink_id}:{sink._base_path}"
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:16]
        self._path = directory / f"pvfs-{os.getpid()}-{suffix}.json"
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._identities = {}
        self._thread = threading.Thread(target=self._run, name="recording-diagnostics", daemon=True)

    @classmethod
    def start(cls, sink):
        """Enable snapshots only when an absolute diagnostics directory is configured."""
        value = os.environ.get("MORELIA_DIAGNOSTICS_DIR")
        if not value or not Path(value).is_absolute():
            return None
        try:
            reporter = cls(sink, Path(value))
            reporter._thread.start()
            return reporter
        except Exception:
            # A diagnostic allocation failure must not become a recording failure.
            return None

    def notify(self):
        self._wake.set()

    def stop(self):
        """Request a final snapshot without waiting for diagnostic disk I/O."""
        self._stop.set()
        self._wake.set()

    def _creation_time(self, pid):
        if pid is None:
            return None
        if pid not in self._identities:
            import psutil

            self._identities[pid] = psutil.Process(pid).create_time()
        return self._identities[pid]

    def _snapshot(self):
        sink = self._sink()
        if sink is None:
            return None
        if not sink._receipt_condition.acquire(timeout=0.01):
            return None
        try:
            accepted = sink._accepted_sequence
            confirmed = sink._samples_written
            consumed = sink._consumed_sequence if sink._use_writer_process else accepted
            writer_pid = getattr(sink._writer_proc, "pid", None)
            result = {
                "schema_version": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "observed_at": time.time(),
                "session_id": sink._session_id,
                "dataflow_id": sink._dataflow_id,
                "device_id": sink._device_id,
                "sink_id": sink._sink_id,
                "output_id": sink._segment_identity,
                "producer_pid": os.getpid(),
                "writer_pid": writer_pid,
                "sample_rate": sink._sample_rate,
                "accepted_frames": accepted,
                "consumed_frames_reported": consumed,
                "confirmed_frames": confirmed,
                "pending_confirmation_frames": max(0, accepted - confirmed),
                "closed": sink._closed,
                "terminal_error": str(sink._terminal_error)[:1024]
                if sink._terminal_error
                else None,
            }
        finally:
            sink._receipt_condition.release()
        for role in ("producer", "writer"):
            try:
                result[f"{role}_create_time"] = self._creation_time(result[f"{role}_pid"])
            except Exception as exc:
                result[f"{role}_create_time"] = None
                result[f"{role}_identity_error"] = type(exc).__name__
        return result

    def _run(self):
        while True:
            stopping = self._stop.is_set()
            try:
                snapshot = self._snapshot()
                if snapshot is not None:
                    self._directory.mkdir(parents=True, exist_ok=True)
                    temporary = self._path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(snapshot, allow_nan=False), encoding="utf-8")
                    os.replace(temporary, self._path)
            except Exception:
                # Missing or stale snapshots let the external collector report this outage.
                pass
            if stopping or self._sink() is None:
                return
            self._wake.wait(1.0)
            self._wake.clear()
