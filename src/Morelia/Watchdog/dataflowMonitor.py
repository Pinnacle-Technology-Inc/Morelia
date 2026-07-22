import time
import gc
import multiprocessing as mp
import sys
import serial
import serial.tools.list_ports
from contextlib import contextmanager
from threading import Lock, RLock
from Morelia.Stream.data_flow import DataFlow
from Morelia.Stream.source import get_data_wrapper
from Morelia.Watchdog.healthSink import HealthSink
from Morelia.Watchdog.hardwareMonitor import HardwareMonitor

class DataFlowMonitor: 
    """
    Monitor and manage a DataFlow lifecycle.

    Responsibilities:
    - Attach to an existing DataFlow.
    - Capture enough DataFlow metadata to rebuild streams later.
    - Poll each source/sinks stream through the shared queue path.
    - Track overall DataFlow status.
    - Detect failed workers.
    - Restart one failed stream or the whole DataFlow when needed.

    Index mapping:
    - flowgraph._network[stream_index] contains (source, sinks)
    - flowgraph._workers[stream_index] contains the worker process
    - flowgraph._manual_stop_events[stream_index] contains the stop event
    - snapshot_config[stream_index] contains rebuild metadata
    """

    def __init__(self, flowgraph:DataFlow = None, reconstruction_hook=None):
        self.flowgraph = None
        self.snapshot_config = None
        self._reconstruction_hook = reconstruction_hook
        self.dataflow_status = "detached" # Overall DataFlow status.
        # Expected values:
        # - detached: no DataFlow attached
        # - attached: DataFlow attached, but not necessarily started
        # - not_started: DataFlow has no worker processes yet
        # - running: all workers are alive and polls are passing
        # - degraded: some workers or stream polls failed
        # - failed: all workers or all stream polls failed
        # - restarting: recovery is currently being attempted
        # - restart_failed: recovery was attempted and failed
        # - starting/stopping/stopped/start_failed/stop_failed: whole DataFlow commands

        self.last_error = None
        # Captured from the attached DataFlow so watchdog-restarted workers keep
        # reporting sink failures. Without this, a sink that fails after an
        # auto-restart goes silent -- data loss with no observer.
        self._on_sink_error = None
        self._poll_locks= {} #Internal lock to make sure only one command sending to read_queue at a time
        self._status_manager = None
        self._shared_status = None
        self._lifecycle_locks = {} #Protect stream data reads and mutations
        self._command_locks = {} #Reserve lifecycle commands without holding data locks
        self._lifecycle_busy = {}
        self._lifecycle_states = {}
        self._hw = HardwareMonitor(failure_threshold=1)  # device-level reset helper (failure_threshold unused here)
        if flowgraph is not None:
            self.attach(flowgraph)

    def attach(self, flowgraph):
        """
        Attach a running or configured DataFlow and save its rebuild snapshot.
        """
        self.flowgraph = flowgraph
        # Capture the app's sink-error callback so restarted workers can keep
        # reporting sink failures (a full flowgraph rebuild would otherwise drop
        # it). Held on the monitor, not read from self.flowgraph each time, so it
        # survives restart_all replacing the flowgraph.
        self._on_sink_error = getattr(flowgraph, "_on_sink_error", None)
        self._inject_health_sinks(flowgraph)
        self.snapshot_config = self._capture_dataflow_info(flowgraph)
        self.dataflow_status = "attached"
        # One lock per source/sinks stream.
        self._poll_locks = {
            index: RLock()
            for index, _ in enumerate(flowgraph._network)
        }
        #Also init the external command control lock
        self._lifecycle_locks = {
            index: RLock() for index, _ in enumerate(flowgraph._network)
        }
        self._command_locks = {
            index: RLock() for index, _ in enumerate(flowgraph._network)
        }
        self._lifecycle_busy = {
            index: None for index, _ in enumerate(flowgraph._network)
        }
        self._lifecycle_states = {
            index: {
                "state": "running",
                "reason": None,
                "updated_at": time.time(),
                "requested_by": None,
                "command": None,
            }
            for index, _ in enumerate(flowgraph._network)
        }
    
    ######################
    # HEALTH SINK HELPER #
    ######################
    def _inject_health_sinks(self, flowgraph):
        """Guarantee every stream carries a HealthSink so the watchdog can read a
        real data heartbeat (not just "worker process alive").

        Idempotent: a stream that already has a HealthSink-like sink is left as-is.
        MUST run before flowgraph.collect() so the spawned workers include it.
        """
        if self._status_manager is None:
            self._status_manager = mp.Manager()
            self._shared_status = self._status_manager.dict()
        for stream_index, (source, sinks) in enumerate(flowgraph._network):
            if any(hasattr(s, "_shared_status") and hasattr(s, "_stream_name") for s in sinks):
                continue
            health = HealthSink(
                self._shared_status,
                stream_name=f"stream{stream_index}",
                pod=source,
            )
            flowgraph._network[stream_index] = (source, [*sinks, health])

    def _find_health_sink(self, stream_index):
        """Return the stream's HealthSink (duck-typed), or None."""
        if self.flowgraph is None:
            return None
        _source, sinks = self.flowgraph._network[stream_index]
        for sink in sinks:
            if hasattr(sink, "_shared_status") and hasattr(sink, "_stream_name"):
                return sink
        return None

    def _ensure_health_sink_for_rebuild(self, stream_index, source, sinks):
        """Return sinks with a HealthSink attached when the hook omitted one."""
        if any(hasattr(s, "_shared_status") and hasattr(s, "_stream_name") for s in sinks):
            return sinks
        if self._status_manager is None:
            self._status_manager = mp.Manager()
            self._shared_status = self._status_manager.dict()
        health = HealthSink(
            self._shared_status,
            stream_name=f"stream{stream_index}",
            pod=source,
        )
        return [*sinks, health]

    def clear_stream_heartbeat(self, stream_index):
        """Remove a stream's previous-worker heartbeat before rebuilding it."""
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            return self._clear_stream_heartbeat_unlocked(stream_index)

    def _clear_stream_heartbeat_unlocked(self, stream_index):
        """Clear heartbeat fields while the caller owns the stream lock."""
        sink = self._find_health_sink(stream_index)
        if sink is None:
            return {
                "ok": False,
                "stream_index": stream_index,
                "reason": "no_health_sink_attached",
            }

        prefix = sink._stream_name
        shared = sink._shared_status
        keys = (
            f"{prefix}.last_data_time",
            f"{prefix}.last_stream_timestamp",
            f"{prefix}.data_flowing",
            f"{prefix}.packet_count",
        )
        cleared = []
        try:
            for key in keys:
                if key in shared:
                    del shared[key]
                    cleared.append(key)
        except Exception as error:
            return {
                "ok": False,
                "stream_index": stream_index,
                "reason": f"{type(error).__name__}: {error}",
                "cleared_keys": cleared,
            }

        return {
            "ok": True,
            "stream_index": stream_index,
            "cleared_keys": cleared,
        }

    def get_stream_heartbeat(self, stream_index, max_age_sec=2.0):
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            return self._get_stream_heartbeat_unlocked(stream_index, max_age_sec)

    def _get_stream_heartbeat_unlocked(self, stream_index, max_age_sec=2.0):
        """Read a stream's data heartbeat from its HealthSink shared status.

        Distinguishes "samples are flowing" from "worker merely alive".
        state is one of: "fresh" | "stale" | "missing".
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)

        sink = self._find_health_sink(stream_index)
        if sink is None:
            return {"state": "missing", "reason": "no_health_sink_attached",
                    "last_data_at": None, "age_sec": None,
                    "max_age_sec": max_age_sec, "packet_count": None}

        prefix = sink._stream_name
        shared = sink._shared_status
        last_data_at = shared.get(f"{prefix}.last_data_time")
        packet_count = int(shared.get(f"{prefix}.packet_count", 0) or 0)

        if last_data_at is None:
            return {"state": "missing", "reason": "no_data_seen_yet",
                    "last_data_at": None, "age_sec": None,
                    "max_age_sec": max_age_sec, "packet_count": packet_count}

        age_sec = time.time() - last_data_at
        state = "fresh" if age_sec <= max_age_sec else "stale"
        return {"state": state,
                "reason": None if state == "fresh" else "data_older_than_max_age",
                "last_data_at": last_data_at, "age_sec": age_sec,
                "max_age_sec": max_age_sec, "packet_count": packet_count}
    
    ####################################
    #  STREAM STATUS RETRIEVAL HELPERS #
    ####################################
    def get_worker_status(self, worker):
        """
        Classify a single worker process slot.

        worker_status is exactly one of:
        - "alive":   the worker process exists and is_alive()
        - "dead":    the worker process exists but has exited (carries a
                     worker_pid and worker_exitcode you can inspect)
        - "missing": the slot is None -- no process object (never spawned,
                     or cleared by stop_stream)

        Note: "detached" is NOT a worker_status. It is a dataflow_status
        ("no DataFlow attached") and a poll_status (see
        poll_stream_queue_roundtrip); do not conflate the axes.

        Output: dict{worker_status, worker_pid, worker_exitcode}
        """
        if worker is None:
            return {
                "worker_status": "missing",
                "worker_pid": None,
                "worker_exitcode": None,
            }
        if worker.is_alive():
            return {
                "worker_status": "alive",
                "worker_pid": worker.pid,
                "worker_exitcode": worker.exitcode,
            }

        return {
            "worker_status": "dead",
            "worker_pid": worker.pid,
            "worker_exitcode": worker.exitcode,
        }

    def get_stream_status(self, stream_index):
        """
        Return status for one specific stream in the DataFlow.
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            return self._get_stream_status_unlocked(stream_index)

    def _get_stream_status_unlocked(self, stream_index):
        if self.flowgraph is None:
            return []
        source, sinks = self.flowgraph._network[stream_index]
        workers = getattr(self.flowgraph, "_workers", [])
        worker = workers[stream_index] if stream_index < len(workers) else None
        worker_info = self.get_worker_status(worker)

        return {
            "stream_index": stream_index,
            "source_class": type(source).__name__,
            "sink_classes": [type(sink).__name__ for sink in sinks],
            **worker_info,
        }        

    def get_all_stream_status(self):
        """
        Return run time status of everystream in the DataFlow.
        """
        if self.flowgraph is None:
            return []
        with self._all_streams_lock():
            return self._get_all_stream_status_unlocked()

    def _get_all_stream_status_unlocked(self):
        network = self.flowgraph._network
        status = []
        for stream_index, _ in enumerate(network):
            status.append(self._get_stream_status_unlocked(stream_index))
        return status
  
    def update_dataflow_status_from_workers(self):
        """
        Update overall DataFlow status based only on worker process state.
        """
        if self.flowgraph is None:
            self.dataflow_status = "detached"
            return self.dataflow_status

        with self._all_streams_lock():
            return self._update_dataflow_status_from_workers_unlocked()

    def _update_dataflow_status_from_workers_unlocked(self):
        """Update aggregate status while every stream lifecycle lock is held."""
        stream_statuses = self._get_all_stream_status_unlocked()

        if not stream_statuses:
            self.dataflow_status = "not_started"
            return self.dataflow_status

        alive_count = sum(
            status["worker_status"] == "alive"
            for status in stream_statuses
        )

        if alive_count == len(stream_statuses):
            self.dataflow_status = "running"
        elif alive_count == 0:
            self.dataflow_status = "failed"
        else:
            self.dataflow_status = "degraded"

        return self.dataflow_status
    
    def poll_stream_queue_roundtrip(self, stream_index, cmd="PING", payload=None, timeout_sec=1.0):
        """Poll one stream without observing a partially replaced network entry."""
        try:
            self._require_flowgraph()
            self._validate_stream_index(stream_index)
        except (RuntimeError, IndexError) as error:
            return {
                "ok": False,
                "stream_index": stream_index,
                "poll_status": "detached" if isinstance(error, RuntimeError) else "invalid_stream_index",
                "error": str(error),
            }

        with self._stream_lock(stream_index):
            return self._poll_stream_queue_roundtrip_unlocked(
                stream_index, cmd=cmd, payload=payload, timeout_sec=timeout_sec
            )

    def _poll_stream_queue_roundtrip_unlocked(self, stream_index, cmd="PING", payload=None, timeout_sec=1.0):
        """
        Poll one source/sinks stream through the normal Pod control path.
        This method checks one stream only.
        """
        #Validate input
        try:
            self._require_flowgraph()
            self._validate_stream_index(stream_index)
        except (RuntimeError) as e:
            return {
                "ok": False,
                "stream_index": stream_index,
                "poll_status": "detached",
                "error": str(e),
            }
        except (IndexError) as e:
            return{
                "ok": False,
                "stream_index": stream_index,
                "poll_status": "invalid_stream_index",
                "error": str(e),
            }

        source, _ = self.flowgraph._network[stream_index]
        stream_status = self.get_stream_status(stream_index)
        worker_status = stream_status["worker_status"]

        if worker_status != "alive":
            return {
                "ok": False,
                "poll_status": f"worker_{worker_status}",
                **stream_status,
                "error": (
                    "Worker is not alive, so it cannot drain the shared write queue."
                ),
            }

        port_open_in_main = getattr(source, "_port", None) is not None #boolean value checking if current main process own the port or not
        routed_through_queue = not port_open_in_main #If dataflow worker own the port, route request to the read_queue instead.

        lock = self._poll_locks.setdefault(stream_index, Lock())
        with lock:#write while only owning lock
            start = time.time()
            try:
                if payload is None:
                    response = source.write_read(cmd = cmd, timeout_sec = timeout_sec)
                else:
                    response = source.write_read(cmd = cmd, payload=payload, timeout_sec = timeout_sec)
                
                return {
                    "ok": True,
                    "poll_status": "queue_roundtrip_ok" if routed_through_queue else "direct_roundtrip_ok",
                    **stream_status,
                    "routed_through_queue": routed_through_queue,
                    "port_open_in_main": port_open_in_main,
                    "elapsed_sec": time.time() - start,
                    "response_type": type(response).__name__,
                    "response_command_number": getattr(response, "command_number", None)
                    }
            except TimeoutError as e:
                return {
                    "ok": False,
                    "poll_status": "queue_roundtrip_timeout" if routed_through_queue else "direct_roundtrip_timeout",
                    **stream_status,
                    "routed_through_queue": routed_through_queue,
                    "port_open_in_main": port_open_in_main,
                    "error": str(e)
                }
            except Exception as e:
                return {
                    "ok": False,
                    "poll_status": "roundtrip_error",
                    **stream_status,
                    "routed_through_queue": routed_through_queue,
                    "port_open_in_main": port_open_in_main,
                    "error": f"{type(e).__name__}: {e}",
                }
        
    def poll_all_streams(self, cmd="PING", timeout_sec=1.0):
        """
        Poll every stream in the DataFlow (aggregate polling method).
        """
        self._require_flowgraph()

        results = []

        for stream_index, _ in enumerate(self.flowgraph._network):
            result = self.poll_stream_queue_roundtrip(
                stream_index=stream_index,
                cmd=cmd,
                timeout_sec=timeout_sec,
            )
            results.append(result)

        return results    
    
    def get_all_streams_index(self):
        """Stable list of stream indexes (one StreamWatcher will own each)."""
        self._require_flowgraph()
        return list(range(len(self.snapshot_config)))
    #################################
    #  STREAM PORT/ DEVICES HELPERS #
    #################################
    def get_stream_port(self, stream_index):
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            return self._get_stream_port_unlocked(stream_index)

    def _get_stream_port_unlocked(self, stream_index):
        source, _ = self.flowgraph._network[stream_index]

        # Try common source attributes first.
        for attr in ("port", "_port_name", "_name", "device_name"):
            if hasattr(source, attr):
                value = getattr(source, attr)
                if value is not None:
                    return str(value)

        # Fall back to source.get_dict() snapshot.
        source_dict = self.snapshot_config[stream_index]["source"]["source_dict"]

        for key in ("port", "port_name", "device_name", "_name"):
            if key in source_dict and source_dict[key] is not None:
                return str(source_dict[key])

        raise KeyError(
            f"Could not find port for stream_index {stream_index}."
        )
    
    def get_port_owner(self, stream_index):
        """Report who currently holds the stream's serial port.

        Output: "main" | "worker" | "none"
        - main:   the main-process source object has an open _port (e.g. during
                startup configuration, before the worker takes over).
        - worker: the worker process is alive and streaming, so it owns the port
                and the main-process source's _port is None.
        - none:   neither side currently holds the port.
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            source, _ = self.flowgraph._network[stream_index]
            if getattr(source, "_port", None) is not None:
                return "main"
            if self.get_stream_status(stream_index).get("worker_status") == "alive":
                return "worker"
            return "none"

    def is_stream_port_present(self, stream_index):
        """
        Return True if the stream's serial port appears in the OS port list.

        This only means the port exists.
        It does not guarantee the port is ready to open.
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            expected_port = self._get_stream_port_unlocked(stream_index).lower()

            for port_info in serial.tools.list_ports.comports():
                if str(port_info.device).lower() == expected_port:
                    return True

            return False

    def is_stream_port_openable(self, stream_index, timeout_sec=0.25, attempts=3, retry_delay_sec=0.2):
        """
        Return True if the stream's serial port can be opened by this process.

        Call this only after stopping the failed DataFlow stream worker.
        If the worker is still alive, it may still own the port and this method
        can return False because of 'Access is denied'.

        A freshly replugged USB serial device (or one whose worker just released
        the handle) can list as present yet transiently refuse to open for a few
        hundred milliseconds while the OS settles the port. To avoid reporting a
        premature "not openable" during that settle window, the open is retried
        up to `attempts` times with `retry_delay_sec` between tries; the port is
        only declared un-openable after every attempt has failed.
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            port_name = self._get_stream_port_unlocked(stream_index)

            for attempt in range(attempts):
                try:
                    ser = serial.Serial(
                        port=port_name,
                        timeout=timeout_sec,
                        write_timeout=timeout_sec,
                    )
                    ser.close()
                    return True

                except Exception:
                    # Give the OS a moment to finish releasing/enumerating the
                    # port before the next probe; skip the wait after the last.
                    if attempt + 1 < attempts:
                        time.sleep(retry_delay_sec)

            return False

    #######################
    #  VALIDATION HELPERS #
    #######################
    def _require_flowgraph(self):
        if self.flowgraph is None:
            raise RuntimeError("No DataFlow attached.")
        return self.flowgraph

    def _validate_stream_index(self, stream_index):
        if self.snapshot_config is None:
            raise RuntimeError("No DataFlow snapshot available.")

        if stream_index < 0 or stream_index >= len(self.snapshot_config):
            raise IndexError(f"stream_index {stream_index} is out of range.")

        return stream_index

    @contextmanager
    def _stream_command_lock(self, stream_index):
        """Reserve one stream command, including direct API calls."""
        lock = self._command_locks.setdefault(stream_index, RLock())
        with lock:
            yield

    @contextmanager
    def _all_command_locks(self):
        """Reserve every stream command in stable index order."""
        acquired = []
        try:
            for stream_index in self.get_all_streams_index():
                lock = self._command_locks.setdefault(stream_index, RLock())
                lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    @contextmanager
    def _stream_lock(self, stream_index):
        """Serialize all reads and lifecycle mutations for one stream."""
        lock = self._lifecycle_locks.setdefault(stream_index, RLock())
        with lock:
            yield

    @contextmanager
    def _all_streams_lock(self):
        """Acquire stream locks in stable order for whole-flowgraph changes."""
        acquired = []
        try:
            for stream_index in self.get_all_streams_index():
                lock = self._lifecycle_locks.setdefault(stream_index, RLock())
                lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    #################
    # STREAM ACTION #
    #################
    def stop_stream(self, stream_index, join_timeout_sec=5.0):
        """
        Stop one stream worker without tearing down its source or queue server.
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)

        with self._stream_command_lock(stream_index):
            return self._stop_stream_reserved(stream_index, join_timeout_sec)

    def _stop_stream_reserved(self, stream_index, join_timeout_sec):
        with self._stream_lock(stream_index):
            result = self._stop_stream_unlocked(
                stream_index,
                join_timeout_sec,
            )

        result["dataflow_status"] = self.update_dataflow_status_from_workers()
        return result

    def _stop_stream_unlocked(self, stream_index, join_timeout_sec):
        workers = self.flowgraph._workers
        worker = workers[stream_index] if stream_index < len(workers) else None

        stop_events= self.flowgraph._manual_stop_events
        stop_event = (
            stop_events[stream_index]
            if stream_index < len(stop_events)
            else None
        )

        if stop_event is not None:
            stop_event.set()

        if worker is not None:
            worker.join(timeout=join_timeout_sec)

            if worker.is_alive():
                worker.terminate()
                worker.join(timeout = 1.0)
            
            try:
                worker.close()
            except Exception:
                pass

        if stream_index < len(workers):
            workers[stream_index] = None

        return {
            "ok": True,
            "stream_index": stream_index,
            "worker_status": "missing",
        }

    def start_stream(self, stream_index, duration_sec= float("inf")):
        self._require_flowgraph()
        self._validate_stream_index(stream_index)

        with self._stream_command_lock(stream_index):
            return self._start_stream_reserved(stream_index, duration_sec)

    def _start_stream_reserved(self, stream_index, duration_sec):
        with self._stream_lock(stream_index):
            result = self._start_stream_unlocked(
                stream_index,
                duration_sec=duration_sec,
            )

        result["dataflow_status"] = self.update_dataflow_status_from_workers()
        return result

    def _start_stream_unlocked(self, stream_index, duration_sec=float("inf")):
        # Validate the current worker slot before creating a replacement.

        workers = self.flowgraph._workers
        while len(workers) <= stream_index:
            workers.append(None)
        stop_events = self.flowgraph._manual_stop_events
        while len(stop_events) <= stream_index:
            stop_events.append(None)

        current_worker = workers[stream_index]
        if current_worker is not None and current_worker.is_alive():
            stream_status = self._get_stream_status_unlocked(stream_index)
            return {
                "ok": True,
                "stream_index": stream_index,
                "status": "already_running",
                **stream_status,
            }

        source, sinks = self._rebuild_dataflow(stream_index)
        manual_stop_event = mp.Event()

        # Match DataFlow behavior:
        if hasattr(source, "_port"):
            source.close_port()
            gc.collect()

        worker = self._make_worker(
            duration_sec=duration_sec,
            manual_stop_event=manual_stop_event,
            source=source,
            sinks=sinks,
        )

        worker.start()

        self.flowgraph._network[stream_index] = (source, sinks)
        stop_events[stream_index] = manual_stop_event
        workers[stream_index] = worker

        self._poll_locks[stream_index] = Lock()

        return {
            "ok": True,
            "stream_index": stream_index,
            "worker_status": "alive",
            "worker_pid": worker.pid,
            "source_class": type(source).__name__,
            "sink_classes": [type(sink).__name__ for sink in sinks],
        }

    def reset_stream_device(self, stream_index):
        """Clean-slate the stream's device before re-streaming. Resolves the
        source, then defers the device work to the hardware layer.

        No openability probe here: reset_streaming_device already retries the
        open to ride out the port-release lag after stop_stream, so a second
        test-open would only risk perturbing the device (e.g. toggling DTR)."""
        self._require_flowgraph()
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            source, _ = self.flowgraph._network[stream_index]
            result = self._hw.reset_streaming_device(source)
            if isinstance(result, dict):
                result["stream_index"] = stream_index
            return result

    def restart_one_stream(self, stream_index, join_timeout_sec=5.0):
        """
        Restart only one failed source/sinks stream.
        """
        self._require_flowgraph()
        self._validate_stream_index(stream_index)

        with self._stream_command_lock(stream_index):
            return self._restart_one_stream_reserved(
                stream_index,
                join_timeout_sec,
            )

    def _restart_one_stream_reserved(self, stream_index, join_timeout_sec):
        with self._stream_lock(stream_index):
            self.dataflow_status = "restarting"

            try:
                # Keep the old source alive through reset: reset_streaming_device
                # may need to reopen it after the worker has released the port.
                self._stop_stream_unlocked(
                    stream_index,
                    join_timeout_sec=join_timeout_sec,
                )
                reset_result = self.reset_stream_device(stream_index)
                heartbeat_reset = self._clear_stream_heartbeat_unlocked(stream_index)
                result = self._start_stream_unlocked(stream_index)
                if isinstance(result, dict):
                    result["reset_result"] = reset_result
                    result["heartbeat_reset"] = heartbeat_reset
                self.last_error = None

            except Exception as e:
                self.dataflow_status = "restart_failed"
                self.last_error = f"{type(e).__name__}: {e}"

                return {
                    "ok": False,
                    "stream_index": stream_index,
                    "error": self.last_error,
                    "dataflow_status": self.dataflow_status,
                }

        result["dataflow_status"] = self.update_dataflow_status_from_workers()
        return result
    
    def restart_all_stream(self):
        """
        Stop, rebuild, and restart the entire DataFlow.

        Use this when all streams failed, or when targeted stream restart is not safe.
        """
        self._require_flowgraph()
        with self._all_command_locks():
            return self._restart_all_streams_reserved()

    def _restart_all_streams_reserved(self):
        with self._all_streams_lock():
            self.dataflow_status = "restarting"

            try:
                for stream_index in range(len(self.snapshot_config)):
                    self._stop_stream_unlocked(
                        stream_index,
                        join_timeout_sec=5.0,
                    )

                for stream_index in range(len(self.snapshot_config)):
                    self.reset_stream_device(stream_index)

                mapping = []
                for stream_index in range(len(self.snapshot_config)):
                    source, sinks = self._rebuild_dataflow(stream_index)
                    mapping.append((source, sinks))

                new_flowgraph = DataFlow(mapping)
                new_flowgraph.collect()

                self.flowgraph = new_flowgraph

                self._poll_locks = {
                    stream_index: Lock()
                    for stream_index, _ in enumerate(self.flowgraph._network)
                }

                self.last_error = None
                self._update_dataflow_status_from_workers_unlocked()

                return {
                    "ok": True,
                    "dataflow_status": self.dataflow_status,
                    "stream_statuses": self._get_all_stream_status_unlocked(),
                    "flowgraph": self.flowgraph,
                }

            except Exception as e:
                self.dataflow_status = "restart_failed"
                self.last_error = f"{type(e).__name__}: {e}"

                return {
                    "ok": False,
                    "error": self.last_error,
                    "dataflow_status": self.dataflow_status,
                }

    def close(self):
        """Shut the status Manager. Safe to call repeatedly; never raises."""
        if self._status_manager is not None:
            try:
                self._status_manager.shutdown()
            except Exception:
                pass
            self._status_manager = None
            self._shared_status = None

    def stop_dataflow(self, join_timeout_sec=15.0):
        """
        Stop the whole DataFlow via DataFlow.stop_collection().
        """
        self._require_flowgraph()
        with self._all_command_locks():
            return self._stop_dataflow_reserved(join_timeout_sec)

    def _stop_dataflow_reserved(self, join_timeout_sec):
        with self._all_streams_lock():
            self.dataflow_status = "stopping"
            try:
                for stream_index in range(len(self.snapshot_config)):
                    self._stop_stream_unlocked(
                        stream_index,
                        join_timeout_sec=join_timeout_sec,
                    )
                self.flowgraph._manual_stop_events = []
                self.flowgraph._workers = []
                self.last_error = None
                self.dataflow_status = "stopped"
                return {
                    "ok": True,
                    "dataflow_status": self.dataflow_status,
                    "stream_statuses": self._get_all_stream_status_unlocked(),
                }
            except Exception as e:
                self.dataflow_status = "stop_failed"
                self.last_error = f"{type(e).__name__}: {e}"
                return {
                    "ok": False,
                    "error": self.last_error,
                    "dataflow_status": self.dataflow_status,
                }

    def start_dataflow(self):
        """
        Start the whole DataFlow via DataFlow.collect().
        """
        self._require_flowgraph()
        with self._all_command_locks():
            return self._start_dataflow_reserved()

    def _start_dataflow_reserved(self):
        with self._all_streams_lock():
            return self._start_dataflow_unlocked()

    def _start_dataflow_unlocked(self):

        workers = getattr(self.flowgraph, "_workers", [])
        if any(worker is not None and worker.is_alive() for worker in workers):
            self._update_dataflow_status_from_workers_unlocked()
            stream_statuses = self._get_all_stream_status_unlocked()
            all_running = all(
                status["worker_status"] == "alive"
                for status in stream_statuses
            )
            return {
                "ok": all_running,
                "status": (
                    "already_running"
                    if all_running
                    else "partially_running"
                ),
                "dataflow_status": self.dataflow_status,
                "stream_statuses": stream_statuses,
            }

        for worker in workers:
            if worker is None:
                continue
            try:
                worker.close()
            except Exception:
                pass

        self.flowgraph._workers = []
        self.flowgraph._manual_stop_events = []
        self.dataflow_status = "starting"

        try:
            self.flowgraph.collect()
            self._poll_locks = {
                stream_index: Lock()
                for stream_index, _ in enumerate(self.flowgraph._network)
            }
            self.last_error = None
            self._update_dataflow_status_from_workers_unlocked()
            return {
                "ok": True,
                "dataflow_status": self.dataflow_status,
                "stream_statuses": self._get_all_stream_status_unlocked(),
            }
        except Exception as e:
            self.dataflow_status = "start_failed"
            self.last_error = f"{type(e).__name__}: {e}"
            return {
                "ok": False,
                "error": self.last_error,
                "dataflow_status": self.dataflow_status,
            }

    def get_lifecycle_state(self, stream_index):
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            return dict(self._lifecycle_states.setdefault(stream_index, {
                "state": "running",
                "reason": None,
                "updated_at": time.time(),
                "requested_by": None,
                "command": None,
            }))

    def set_lifecycle_state(self, stream_index, state, *, reason=None, requested_by=None, command=None):
        self._validate_stream_index(stream_index)
        with self._stream_lock(stream_index):
            return self._set_lifecycle_state_unlocked(
                stream_index,
                state,
                reason=reason,
                requested_by=requested_by,
                command=command,
            )

    def _set_lifecycle_state_unlocked(self, stream_index, state, *, reason=None, requested_by=None, command=None):
        state_record = {
            "state": state,
            "reason": reason,
            "updated_at": time.time(),
            "requested_by": requested_by,
            "command": command,
        }
        self._lifecycle_states[stream_index] = state_record
        return dict(state_record)

    def set_all_lifecycle_states(self, state, *, reason=None, requested_by=None, command=None):
        states = {}
        with self._all_streams_lock():
            for stream_index in self.get_all_streams_index():
                states[stream_index] = self._set_lifecycle_state_unlocked(
                    stream_index,
                    state,
                    reason=reason,
                    requested_by=requested_by,
                    command=command,
                )
        return states

    def sync_lifecycle_states_from_workers(self, *, reason, requested_by, command):
        """Reconcile per-stream lifecycle states with one locked worker snapshot."""
        states = {}
        with self._all_streams_lock():
            for status in self._get_all_stream_status_unlocked():
                stream_index = status["stream_index"]
                state = (
                    "running"
                    if status["worker_status"] == "alive"
                    else "stopped"
                )
                states[stream_index] = self._set_lifecycle_state_unlocked(
                    stream_index,
                    state,
                    reason=reason,
                    requested_by=requested_by,
                    command=command,
                )
        return states

    def guarded_stop_dataflow(self, requested_by, blocking):
        with self.dataflow_lifecycle_guard(
            command="stop",
            requested_by=requested_by,
            blocking=blocking,
        ) as busy:
            if busy is not None:
                return busy

            result = self.stop_dataflow()
            if result.get("ok"):
                self.set_all_lifecycle_states(
                    "stopped",
                    reason="manual_stop",
                    requested_by=requested_by,
                    command="stop",
                )
            else:
                self.sync_lifecycle_states_from_workers(
                    reason="stop_failed",
                    requested_by=requested_by,
                    command="stop",
                )

            return {
                "ok": bool(result.get("ok")),
                "stream_index": None,
                "command": "stop",
                "requested_by": requested_by,
                "result": result,
            }

    def guarded_start_dataflow(self, requested_by, blocking):
        with self.dataflow_lifecycle_guard(
            command="start",
            requested_by=requested_by,
            blocking=blocking,
        ) as busy:
            if busy is not None:
                return busy

            result = self.start_dataflow()
            if result.get("ok"):
                self.set_all_lifecycle_states(
                    "running",
                    reason=None,
                    requested_by=requested_by,
                    command="start",
                )
            else:
                self.sync_lifecycle_states_from_workers(
                    reason=result.get("status", "start_failed"),
                    requested_by=requested_by,
                    command="start",
                )

            return {
                "ok": bool(result.get("ok")),
                "stream_index": None,
                "command": "start",
                "requested_by": requested_by,
                "result": result,
            }

    def guarded_restart_one_stream(self, stream_index, requested_by, blocking):
        with self.stream_lifecycle_guard(
            stream_index,
            command="restart_stream",
            requested_by=requested_by,
            blocking=blocking,
        ) as busy:
            if busy is not None:
                return busy

            result = self.restart_one_stream(stream_index)
            if result.get("ok"):
                self.set_lifecycle_state(
                    stream_index,
                    "running",
                    reason=None,
                    requested_by=requested_by,
                    command="restart_stream",
                )

            return {
                "ok": bool(result.get("ok")),
                "stream_index": stream_index,
                "command": "restart_stream",
                "requested_by": requested_by,
                "result": result,
            }

    def guarded_restart_session(self, stream_index, requested_by, blocking):
        self._validate_stream_index(stream_index)
        with self.dataflow_lifecycle_guard(
            command="restart_session",
            requested_by=requested_by,
            blocking=blocking,
        ) as busy:
            if busy is not None:
                return busy

            result = self.restart_all_stream()
            if result.get("ok"):
                self.set_all_lifecycle_states(
                    "running",
                    reason=None,
                    requested_by=requested_by,
                    command="restart_session",
                )

            return {
                "ok": bool(result.get("ok")),
                "stream_index": stream_index,
                "command": "restart_session",
                "requested_by": requested_by,
                "result": result,
            }

    @contextmanager
    def dataflow_lifecycle_guard(self, *, command: str, requested_by: str, blocking: bool = False):
        self._require_flowgraph()
        stream_indexes = self.get_all_streams_index()
        acquired_indexes = []

        try:
            for stream_index in stream_indexes:
                lock = self._command_locks.setdefault(stream_index, RLock())
                acquired = lock.acquire(blocking=blocking)
                if not acquired:
                    yield {
                        "ok": False,
                        "stream_index": None,
                        "command": command,
                        "requested_by": requested_by,
                        "status": "busy",
                        "busy": self._lifecycle_busy.get(stream_index),
                        "busy_stream_index": stream_index,
                    }
                    return
                acquired_indexes.append(stream_index)
                self._lifecycle_busy[stream_index] = {
                    "command": command,
                    "requested_by": requested_by,
                    "started_at": time.time(),
                }

            yield None
        finally:
            for stream_index in reversed(acquired_indexes):
                self._lifecycle_busy[stream_index] = None
                self._command_locks[stream_index].release()

    @contextmanager
    def stream_lifecycle_guard(self, stream_index, *, command:str, requested_by: str, blocking: bool = False):
        self._require_flowgraph()
        self._validate_stream_index(stream_index)

        lock = self._command_locks.setdefault(stream_index, RLock())
        acquired = lock.acquire(blocking=blocking) #check the stream index lock to see if anything is running

        if not acquired: #if can't acquire lock/ system is busy
            yield { #return with busy reason
                "ok": False,
                "stream_index": stream_index,
                "command": command,
                "requested_by": requested_by,
                "status": "busy",
                "busy": self._lifecycle_busy.get(stream_index),
            }
            return
        self._lifecycle_busy[stream_index]= { #if not busy, record what is running
            "command": command,
            "requested_by": requested_by,
            "started_at": time.time(),
        }
        try: #let the caller do the operation
            yield None
        finally: #clean up the dictionary that we appended, and release lock
            self._lifecycle_busy[stream_index] = None
            lock.release()

    #############################
    #  DATAFLOW REBUILD HELPERS #
    #############################
    @staticmethod
    def _capture_dataflow_info(flowgraph: DataFlow):
        """
        Extract the information from current flowgraph for future reconnect
        """
        config = [] #Initiate a list of stream dictionary
        for source, sinks in flowgraph._network:
            # save sink class and sink.get_dict()
            sink_list = []
            for sink in sinks:
                sink_list.append({
                    "sink_class": type(sink),
                    "sink_class_name": type(sink).__name__,
                    "sink_class_path":f"{type(sink).__module__}.{type(sink).__qualname__}",
                    "sink_dict": sink.get_dict()
                })  
            # save source class and source.get_dict()
            stream_config = {
                "source": {
                    "source_class": type(source),
                    "source_class_name": type(source).__name__,
                    "source_class_path": f"{type(source).__module__}.{type(source).__qualname__}",
                    "source_dict": source.get_dict()
                }, 
                "sinks": sink_list
            }
            config.append(stream_config)
        return config
    
    def _rebuild_dataflow(self, stream_index):
        """Build one stream for reconnection."""
        self._validate_stream_index(stream_index)

        if self._reconstruction_hook is not None:
            return self._rebuild_dataflow_from_hook(stream_index)

        stream_config = self.snapshot_config[stream_index]

        source_class = stream_config["source"]["source_class"]
        source_dict = stream_config["source"]["source_dict"]
        source = source_class(**source_dict)

        sinks = []
        for sink_config in stream_config["sinks"]:
            sink_class = sink_config["sink_class"]
            sink_dict = sink_config["sink_dict"]
            sinks.append(sink_class(**{**sink_dict,"pod": source}))
        return source, sinks

    def _rebuild_dataflow_from_hook(self, stream_index):
        """
        Rebuild one stream using an optional application-owned reconstruction hook.

        The hook lets a runtime host rebuild from an immutable manifest while
        standalone Morelia users keep the default get_dict() snapshot path.
        """
        rebuilt = self._reconstruction_hook(stream_index)
        if not isinstance(rebuilt, tuple) or len(rebuilt) != 2:
            raise TypeError(
                "reconstruction_hook must return (source, sinks)."
            )

        source, sinks = rebuilt
        if isinstance(sinks, tuple):
            sinks = list(sinks)
        if not isinstance(sinks, list):
            raise TypeError(
                "reconstruction_hook must return sinks as a list or tuple."
            )

        return source, self._ensure_health_sink_for_rebuild(stream_index, source, sinks)

    def _make_worker(self, duration_sec, manual_stop_event, source, sinks):
        """Build only one source/sinks pair to manually only reconnect the one that is failing"""
        source_class = type(source)
        source_dict = source.get_dict()

        sinks_list = [
            (type(sink), sink.get_dict()) for sink in sinks
        ]
        # Forward on_sink_error (mirrors DataFlow.collect) so a sink that fails
        # after an auto-restart still reports instead of dropping data silently.
        # on_source_error is intentionally left at its default (None): its read
        # status is redundant telemetry the watchdog already infers from the
        # heartbeat, so it is not threaded through the restart path.
        args = (
            duration_sec,
            manual_stop_event,
            source_class,
            source_dict,
            sinks_list,
            self._on_sink_error,
        )
        if sys.platform != "win32":
            try:
                return mp.Process(
                    target=get_data_wrapper,
                    args=args,
                    start_new_session=True,
                )
            except TypeError:
                pass

        return mp.Process(
            target=get_data_wrapper,
            args=args,
        )
