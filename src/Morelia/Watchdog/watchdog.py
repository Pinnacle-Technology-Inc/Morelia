from Morelia.Watchdog.hardwareMonitor import HardwareMonitor
from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor
from Morelia.Stream.data_flow import DataFlow
import time
import multiprocessing as mp
import threading
# Wall-clock epoch captured when this module is first imported (≈ program
# start). Every timestamp emitted in a watchdog report is expressed as
# seconds relative to this, so reports read as "time since startup" rather
# than raw epoch seconds. Epoch (not monotonic) is used on purpose: it keeps
# these on the same scale as last_data_at, which is stamped with time.time()
# in the worker process.
_PROGRAM_START = time.time()


def _now_rel():
    """Current time as seconds since program start."""
    return time.time() - _PROGRAM_START


def _to_rel(epoch_sec):
    """Convert an absolute epoch timestamp to seconds since program start.
    Passes None through unchanged."""
    return None if epoch_sec is None else epoch_sec - _PROGRAM_START

def _resolve_interval(spec, key, default):
    """spec may be a float (shared by all) or a dict {key: float} (per item).
    Falls back to `default` for keys absent from a dict, or when spec is None."""
    if spec is None:
        return default
    if isinstance(spec, dict):
        return spec.get(key, default)
    return spec   # scalar -> shared

# Short compact-report phrasings per assessment rule. Rules not listed here
# fall back to the full assessment reason.
_COMPACT_REASONS = {
    "worker_alive_heartbeat_fresh": "ok",
    "worker_not_alive": "worker not alive",
    "worker_alive_heartbeat_stale_below_threshold": "heartbeat stale, below threshold",
    "worker_alive_heartbeat_stale_threshold_reached": "heartbeat stale, threshold reached",
    "heartbeat_missing": "heartbeat missing",
    "no_data_below_threshold": "no data yet, below threshold",
    "no_data_threshold_reached": "no data, threshold reached",
    "stream_reconnecting": "reconnecting",
}

# Failure reasons emitted by the reconnect path while a stream is actively
# recovering. These are retry-in-progress states, not terminal errors, so they
# assess as "suspect" even though the worker is (intentionally) not alive.
_RECONNECT_FAILURE_REASONS = {
    "port_check_failed",
    "waiting_for_port",
    "waiting_for_port_release",
    "restart_failed",
    "restart_completed_worker_not_response",
}

_HARDWARE_HEALTH = {
    "connected":"healthy",
    "reconnected":"healthy", 
    "ping_failed":"suspect",
    "disconnected":"unhealthy"
}

class Watchdog:
    """
    Build watchdog reports for hardware-only devices or DataFlow streams.

    Responsibilities:
    - Poll stream/worker/heartbeat signals.
    - Track consecutive stream failures.
    - Assess stream health.
    - Return compact or verbose watchdog dictionaries.
    """
    def __init__(self, flowgraph:DataFlow = None, devices=(), failure_threshold:int = 3, max_heartbeat_age_sec:float = 2.0 ):
        #Input validation
        if flowgraph is None and not devices: 
            raise ValueError("Watchdog needs a flowgraph, devices, or both.")
        
        #Set default value
        self.failure_threshold = failure_threshold
        self.max_heartbeat_age_sec = max_heartbeat_age_sec
        
        #Setup dataflow monitor
        self.dataflow_monitor = DataFlowMonitor(flowgraph) if flowgraph is not None else None
        
        #Setup hardware device monitor
        self._standalone_devices = self._filter_standalone_devices(devices)

        self._stream_watchers = {}      # stream_index -> StreamWatcher
        self._device_watchers = {}      # device_key   -> DeviceWatcher
        self._stream_results = {}
        self._device_results = {}
        self._results_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._on_stream_result = None
        self._on_device_result = None

    def preflight(self, *, attempts=3, timeout_sec=5.0, require_ready=True):
        if self.dataflow_monitor is not None and getattr(self.dataflow_monitor.flowgraph, "_workers", []):
            raise RuntimeError(
                "preflight() must run before flowgraph.collect() — workers already own the ports.")
        hw = HardwareMonitor(failure_threshold=self.failure_threshold)
        results = {}
        sources = []
        if self.dataflow_monitor is not None:
            sources += [src for src, _ in self.dataflow_monitor.flowgraph._network]
        sources += list(self._standalone_devices)
        for dev in sources:
            results[str(getattr(dev, "port", id(dev)))] = hw.preflight_device(
                dev, attempts=attempts, timeout_sec=timeout_sec)
        not_ready = [k for k, r in results.items() if not r["ok"]]
        if require_ready and not_ready:
            raise RuntimeError(f"preflight failed for {not_ready}")
        return {"ok": not not_ready, "devices": results}

    def spawn_threads(self, *, stream_interval, device_interval, timeout_sec, on_stream_result, on_device_result):
        """
        Spawn one thread per stream and one per standalone device. Non-blocking.

        stream_interval / device_interval: float (shared) or {key: float} (per item).
        """
        self._stop_event.clear()
        self._on_stream_result = on_stream_result
        self._on_device_result = on_device_result

        if self.dataflow_monitor is not None:
            for idx in self.dataflow_monitor.get_all_streams_index(): #Iterate through stream list and spawn StreamWatcher
                with self._results_lock:#acquire the lock
                    self._stream_results[idx] = {
                        "stream_index": idx, 
                        "stream_health": "unknown",
                        "summary": "starting", 
                        "signals": {},
                        "rule": "starting",
                        "action": {"taken": "none", "detail": None}}
                w = StreamWatcher(idx, self.dataflow_monitor,
                              failure_threshold=self.failure_threshold,
                              max_heartbeat_age_sec=self.max_heartbeat_age_sec,
                              interval_sec=_resolve_interval(stream_interval, idx, 30), timeout_sec=timeout_sec,
                              publish=self._publish_stream)
                self._stream_watchers[idx] = w
                w.start()

        for device in self._standalone_devices:
            key = DeviceWatcher._device_key(device)
            w = DeviceWatcher(
                device, failure_threshold=self.failure_threshold,
                interval_sec=_resolve_interval(device_interval, key, 30),
                timeout_sec=timeout_sec,
                publish=self._publish_device)
            with self._results_lock:
                self._device_results[key] = {"status": "starting"}
            self._device_watchers[key] = w
            w.start() 

    def stop(self):
        """
        Signal a running run() to exit.
        
        Does not stop the workers or release resources — call close()
        for that.
        """
        self._stop_event.set()
        watchers = (*self._stream_watchers.values(), *self._device_watchers.values())
        for w in watchers:
            w.stop()
        for w in watchers:
            w.join(timeout=10.0)

    def get_report(self, verbose=False):
        with self._results_lock:
            streams = [self._stream_results[i] for i in sorted(self._stream_results)]
            devices = dict(self._device_results)
        if not verbose:
            streams = [self.build_compact_stream_report(s) for s in streams]
        health = [s.get("stream_health") for s in streams]
        health += [_HARDWARE_HEALTH.get(d.get("status"), "suspect")
                   for d in devices.values()]
        return {"watchdog_status": self._summarize_watchdog_health(health),
                "checked_at": _now_rel(), "streams": streams, "devices": devices} 

    def run(self, *, report_interval_sec=30.0, stream_interval=30.0, device_interval=30.0, timeout_sec=10.0, on_result=None, on_stream_result=None, on_device_result=None, verbose=False):
        """Blocking convenience entry. Start every watcher, then emit a combined
        snapshot every report_interval_sec until stop(). Per-item callbacks fire
        independently from inside each watcher thread."""
        self.spawn_threads(stream_interval=stream_interval, device_interval=device_interval,
                   timeout_sec=timeout_sec, on_stream_result=on_stream_result,
                   on_device_result=on_device_result)
        while not self._stop_event.is_set():
            if on_result is not None:
                on_result(self.get_report(verbose=verbose))
            self._stop_event.wait(report_interval_sec)

    def close(self):
        """Stop every watched stream worker and release monitor resources.

        Safe to call repeatedly and never raises. Each step is isolated so a
        failure in one does not skip the others — otherwise a half-torn-down
        multiprocessing state can hang the interpreter at exit.

        Workers are stopped via the monitor's None-safe stop_stream rather
        than flowgraph.stop_collection(): once the watchdog has stopped a
        stream, flowgraph._workers holds None in that slot, and
        stop_collection() calls worker.join() unconditionally (crashing on
        the None).
        """
        self.stop()
        if self.dataflow_monitor is not None:
            for i in self.dataflow_monitor.get_all_streams_index():
                try: self.dataflow_monitor.stop_stream(i)
                except Exception: pass
            try: self.dataflow_monitor.close()      # shuts the status Manager
            except Exception: pass
            self._cleanup_sources()
        for child in mp.active_children():           # backstop (unchanged)
            try: child.terminate()
            except Exception: pass
        for child in mp.active_children():
            try: child.join(timeout=2.0)
            except Exception: pass

    def _filter_standalone_devices(self, devices: list):
        """
        Helper function: Go through all devices list and filter out any devices that has already been used by dataflow
        Output: list[Device object]
        """
        if self.dataflow_monitor is None: 
            return list(devices)
        
        stream_ports = set()
        for status in self.dataflow_monitor.get_all_stream_status(): 
            try:                                            
                port = self.dataflow_monitor.get_stream_port(status["stream_index"])
            except Exception:
                port = None
            if port is not None:
                stream_ports.add(str(port).lower())
        
        standalone = []
        for device in devices:
            device_port = str(getattr(device, "port", "")).lower()
            if device_port and device_port in stream_ports:
                continue 
            standalone.append(device)
        return standalone
    
    def _summarize_watchdog_health(self, health_values: list):
        """
        Determine the current status of watchdog based on all accumulated status between dataflow and devices
        Output: str (unknown | ok | failed | degraded)
        """
        if not health_values:
            return "unknown"
        if all(h == "healthy" for h in health_values):
            return "ok"
        if all(h == "unhealthy" for h in health_values):
            return "failed"
        return "degraded"

    @staticmethod
    def build_compact_stream_report(verbose_stream):
        """Reduce one verbose stream report to the compact stream shape."""
        signals = verbose_stream["signals"]
        return {
            "stream_index": verbose_stream.get("stream_index"),
            "port": verbose_stream.get("port"),
            "port_owner": verbose_stream.get("port_owner"),
            "stream_health": verbose_stream.get("stream_health"),
            "worker_status": signals.get("worker", {}).get("status"),
            "heartbeat": signals.get("heartbeat", {}).get("status"),
            "failure_count": signals.get("failure", {}).get("count"),
            "action": verbose_stream.get("action", {}).get("taken"),
            "reason": _COMPACT_REASONS.get(verbose_stream.get("rule"), verbose_stream.get("summary")),
        }
        
    def _publish_stream(self, stream_index, report):
        with self._results_lock:
            self._stream_results[stream_index] = report
        if self._on_stream_result is not None:
            try:
                self._on_stream_result(stream_index, report)
            except Exception:
                pass   # a bad user callback must not kill the watcher thread

    def _publish_device(self, key, report):
        with self._results_lock:
            self._device_results[key] = report
        if self._on_device_result is not None:
            try:
                self._on_device_result(key, report)
            except Exception:
                pass

    def _cleanup_sources(self):
        """Run each source device's own cleanup() so Morelia's serial
        queue_server subprocess is torn down deterministically.

        pod._manager (a PacketManager) launches queue_server.py and is the only
        thing that can stop it, but Morelia only calls its cleanup() from
        __del__ — which doesn't run on an abrupt/Ctrl-C exit, so the server
        orphans and keeps holding the port. _manager survives collect()
        (close_port() nulls _port, not _manager) and the main process is the one
        that started the server, so calling cleanup() here actually terminates it.
        """
        if self.dataflow_monitor is None or self.dataflow_monitor.flowgraph is None:
            return
        for source, _sinks in self.dataflow_monitor.flowgraph._network:
            cleanup = getattr(source, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass


class StreamWatcher (threading.Thread):
    """Independent watchdog thread for a single (source, sinks) stream.

    Owns ALL mutable state for its stream (failure count, disconnected flag),
    so a slow reconnect or a crash here cannot touch any other stream.
    """   
    def __init__(self, stream_index: int, monitor: DataFlowMonitor, *, failure_threshold: int, max_heartbeat_age_sec: float, interval_sec: float, timeout_sec: float, publish):
        super().__init__(name=f"stream-watcher-{stream_index}", daemon=True)
        self.stream_index = stream_index
        self._monitor = monitor #shared dataflow monitor handed to each thread
        self._failure_threshold = failure_threshold
        self._max_heartbeat_age_sec = max_heartbeat_age_sec
        self._interval_sec = interval_sec
        self._timeout_sec = timeout_sec
        self._publish = publish                #fire-and-forget to report back what it got

        self._stop_event = threading.Event()
        self._failure_count = 0               
        self._disconnected = False            

    # ------------------------------------------------------------------ #
    # Thread lifecycle                                                   #
    # ------------------------------------------------------------------ #
    def run(self):
        "A thread monitoring one worker (pair of source - sinks). Running forever until the self._stop_event is set"
        while not self._stop_event.is_set():
            checked_at = _now_rel()
            try:
                action_result = self._watch_stream()
            except Exception as error:
                # The loop must never die -- publish an error report and keep going.
                action_result = {
                    "stream_index": self.stream_index,
                    "action": "check_failed",
                    "failure_reason": "watcher_error",
                    "error": f"{type(error).__name__}: {error}",
                }
            report = self._build_verbose_stream_report(checked_at, action_result)
            self._publish(self.stream_index, report)
            # wait() returns immediately when stop() fires -> responsive shutdown.
            self._stop_event.wait(self._interval_sec)

    def stop(self):
        """Signal the loop to exit. Safe from any thread, more than once."""
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Thread's 2 action paths: Detect & get info or recover disconnected  #
    # ------------------------------------------------------------------ #

    #Helper for per-stream logic
    def _watch_stream(self):
        """
        If stream disconnected, try to reconnect, else return information
        """
        try:
            if self._disconnected:
                return self._try_reconnect() 
            return self._get_live_stream_info() 
        except Exception as error:
            return {
                "ok": False, "stream_index": self.stream_index,
                "action": "check_failed", "failure_reason": "check_failed",
                "error": f"{type(error).__name__}: {error}",
            }
            
    def _get_live_stream_info(self):
        m = self._monitor
        stream_status = m.get_stream_status(self.stream_index)
        heartbeat= self._get_heartbeat()
        base = {"stream_index":self.stream_index, "stream_status": stream_status, "heartbeat":heartbeat}
        
        #Checking if the stream worker is doing good
        failure_reason = self._classify_stream_failure(stream_status, heartbeat) 
        if failure_reason is None:
            self._failure_count = 0
            return {
                **base,
                "ok": True,
                "action": "none",
                "failure_reason": None,
                "failure_count": 0,
            }

        #If the stream worker is in unknown-state, counting up for 3 times
        self._failure_count += 1
        worker_failed = failure_reason in ("worker_dead", "worker_missing")
        escalates = worker_failed or failure_reason in ("heartbeat_stale", "data_never_started")
        if not escalates or (not worker_failed and self._failure_count < self._failure_threshold):
            return {
                **base,
                "ok": False,
                "action": "none",
                "failure_reason": failure_reason,
                "failure_count": self._failure_count,
            }

        #If not from above cases, escalate immediately by stopping the stream and mark disconnect
        m.stop_stream(self.stream_index)
        self._disconnected = True
        return {
            **base,
            "ok": False,
            "action": "stopped_stream_waiting_for_reconnect",
            "failure_reason": failure_reason,
            "failure_count": self._failure_count,
        }
    
    def _try_reconnect(self):
        """
        If stream disconnected, check port availability and access, reconnect if possible and verify with 1 PING
        Retry forever
        """
        m = self._monitor
        base = {
            "stream_index": self.stream_index,
            "failure_count": self._failure_count,
            "stream_status": self._safe_get_stream_status(),
        }
        
        #Check if any port is available
        try:
            port_present = m.is_stream_port_present(self.stream_index)
        except Exception as error:
            return {#if anything goes wrong when doing port check
                **base,
                "ok": False,
                "action": "port_check_failed",
                "failure_reason": "port_check_failed",
                "error": f"{type(error).__name__}: {error}",
            }  
        #if port is unavailable, wait
        if not port_present:
            return {
                **base,
                "ok": False,
                "action": "waiting_for_port",
                "failure_reason": "waiting_for_port",
            }
        #if port exist but cant be opened, wait until next tick and retry
        if not m.is_stream_port_openable(self.stream_index):
            return {
                **base,
                "ok": False,
                "action": "waiting_for_port_release",
                "failure_reason": "waiting_for_port_release",
            }
        #if port exist and can be opened, restart stream
        restart_result = m.restart_one_stream(self.stream_index)
        if not restart_result["ok"]: #If restart status is bad
            return {
                **base,
                "ok": False,
                "action": "restart_failed",
                "failure_reason": "restart_failed",
                "restart_result": restart_result,
            }

        #if we successfully restart stream, ping the worker to verify that it's working
        verify_result = m.poll_stream_queue_roundtrip(
            stream_index=self.stream_index,
            cmd="PING",
            timeout_sec=self._timeout_sec,
        )
        if verify_result["ok"]:#If the worker responsed
            self._disconnected= False
            self._failure_count = 0
            return {
                "stream_index": self.stream_index,
                "ok": True,
                "action": "reconnected",
                "failure_reason": None,
                "failure_count": 0,
                "stream_status": self._safe_get_stream_status(),
                "restart_result": restart_result,
                "verify_result": verify_result,
            }
        
        #if we restarted but the worker did not respond, stop the stream so we don't loop forever
        try:
            m.stop_stream(self.stream_index)
        except Exception as error:
            return {
                **base,
                "ok": False,
                "action": "reconnect_failed_stop_stream_failed",
                "failure_reason": "restart_completed_worker_not_response",
                "restart_result": restart_result,
                "verify_result": verify_result,
                "error": f"{type(error).__name__}: {error}",
            }

        return {
            **base,
            "ok": False,
            "action": "reconnect_failed_stop_stream_completed",
            "failure_reason": "restart_completed_worker_not_response",
            "restart_result": restart_result,
            "verify_result": verify_result,
        }
    
    # ------------------------------------------------------------------ #
    # Signal readers (need self._monitor -> instance methods)            #
    # ------------------------------------------------------------------ #

    def _get_heartbeat(self):
        try:
            hb = self._monitor.get_stream_heartbeat(self.stream_index, self._max_heartbeat_age_sec)
            return {
                "status": hb.get("state"),
                "last_data_at": _to_rel(hb.get("last_data_at")),   # _to_rel is already module-level
                "reason": hb.get("reason"),
                "age_sec": hb.get("age_sec"),
                "max_age_sec": hb.get("max_age_sec"),
                "packet_count": hb.get("packet_count"),
            }
        except Exception as error:
            return {
                "status": "missing",
                "reason": f"heartbeat_check_failed: {type(error).__name__}: {error}",
                "last_data_at": None, "age_sec": None,
                "max_age_sec": self._max_heartbeat_age_sec, "packet_count": None,
            }
    
    def _safe_get_stream_status(self):
        try:
            return self._monitor.get_stream_status(self.stream_index)
        except Exception as error:
            return {
                "stream_index": self.stream_index, "source_class": None,
                "sink_classes": [], "worker_status": "unknown",
                "worker_pid": None, "worker_exitcode": None,
                "error": f"{type(error).__name__}: {error}",
            }

    def _safe_get_stream_port(self):
        """
        Return the stream port, or None if it cannot be resolved.

        Output: str or None
        """
        try:
            return self._monitor.get_stream_port(self.stream_index)
        except Exception:
            return None     

    def _safe_get_port_owner(self):
        """
        Return who owns the stream port.

        Output: "main" | "worker" | "none" | None
        """
        try:
            return self._monitor.get_port_owner(self.stream_index)
        except Exception:
            return None  
 
    def _extract_stream_status_for_report(self, action_result):
        """
        Extract the information already fetched from get_stream_status() function above
        """
        stream_status = action_result.get("stream_status")
        if isinstance(stream_status, dict) and "worker_status" in stream_status:
            return stream_status          # reuse what the action already read
        return self._safe_get_stream_status()  # fall back to a fresh, safe read
    
    # ------------------------------------------------------------------ #
    # Verdict + report building                                          #
    # ------------------------------------------------------------------ #    

    def _classify_stream_failure(self,stream_status, heartbeat):
        """
        Reduce this pass's signals to a single failure reason.

        Output: reason str, or None when the stream is healthy this pass.
        """
        if stream_status.get("worker_status") != "alive":
            return f"worker_{stream_status.get('worker_status')}"      
        hb = heartbeat.get("status")
        if hb == "stale":
            return "heartbeat_stale"  
        if  hb == "missing":
            if heartbeat.get("reason") == "no_data_seen_yet":
                return "data_never_started"
            return "heartbeat_missing"                           
        return None    
    
    def _build_verbose_stream_report(self, checked_at, action_result):
        """
        Build the verbose per-stream watchdog dictionary.

        Output: dict with identity fields, a flattened verdict
        (stream_health / rule / summary), the action taken, and the raw
        signals (worker / heartbeat / failure).
        """
        #Setup information
        stream_status = self._extract_stream_status_for_report(action_result)
        worker = {
            "status": stream_status.get("worker_status"),
            "pid": stream_status.get("worker_pid"),
            "exitcode": stream_status.get("worker_exitcode"),
        }
        heartbeat = action_result.get("heartbeat") or self._get_heartbeat()
        failure_reason = action_result.get("failure_reason")
        failure_count = action_result.get("failure_count", 0)
        error = self._extract_action_error(action_result)

        signals = {
            "worker": worker,
            "heartbeat": heartbeat,
            "failure": {
                "count": failure_count,
                "threshold": self._failure_threshold,
                "last_error": error,
                "last_error_at": checked_at if error is not None else None,
            },
        }

        assessment = self._assess_stream(
            worker=worker,
            heartbeat=heartbeat,
            failure_reason=failure_reason,
            count=failure_count,
            threshold=self._failure_threshold,
        )

        return {
            "stream_index": self.stream_index,
            "source_class": stream_status.get("source_class"),
            "sink_classes": stream_status.get("sink_classes", []),
            "stream_health": assessment["stream_health"],
            "summary": assessment["summary"],
            "port": self._safe_get_stream_port(),
            "port_owner": self._safe_get_port_owner(),
            "checked_at": checked_at,
            "rule": assessment["rule"],
            "action": self._build_action_signal(action_result),
            "signals": signals,
        }
    
    def _assess_stream(self, worker, heartbeat, failure_reason, count, threshold):
        """
        Convert this pass's signals and failure count into a health verdict.

        Output: dict
        - stream_health:
             healthy: Nothing is wrong
           | suspect: System is in retry attempts from failures
           | unhealthy: System found error
        - rule: stable machine key for the verdict
        - summary: human-readable explanation
        """
        worker_status = worker["status"]
        hb_status = heartbeat.get("status")

        if failure_reason is None:
            return {
                "stream_health": "healthy",
                "rule": "worker_alive_heartbeat_fresh",
                "summary": "Worker is alive and heartbeat is fresh.",
            }

        # Recovery states come before the worker-not-alive check: the worker is
        # intentionally stopped while reconnecting, so it's "suspect" (retrying),
        # not "unhealthy".
        if failure_reason in _RECONNECT_FAILURE_REASONS:
            return {
                "stream_health": "suspect",
                "rule": "stream_reconnecting",
                "summary": (
                    f"Stream is recovering ({failure_reason}). "
                    f"Failure count is {count}/{threshold}."
                ),
            }

        if worker_status != "alive":
            return {
                "stream_health": "unhealthy",
                "rule": "worker_not_alive",
                "summary": f"Worker is {worker_status}. Failure count is {count}/{threshold}.",
            }

        if hb_status == "stale":
            age_sec = heartbeat.get("age_sec")
            age_text = f"{age_sec:.1f}s" if age_sec is not None else "unknown"
            if count < threshold:
                return {
                    "stream_health": "suspect",
                    "rule": "worker_alive_heartbeat_stale_below_threshold",
                    "summary": (
                        f"Worker is alive, but heartbeat is stale for {age_text}. "
                        f"Failure count is {count}/{threshold}."
                    ),
                }
            return {
                "stream_health": "unhealthy",
                "rule": "worker_alive_heartbeat_stale_threshold_reached",
                "summary": (
                    f"Worker is alive, but heartbeat is stale for {age_text}. "
                    f"Failure threshold reached at {count}/{threshold}."
                ),
            }

        if hb_status == "missing":
            if failure_reason == "data_never_started":
                if count < threshold:
                    return {"stream_health": "suspect",
                            "rule": "no_data_below_threshold",
                            "summary": f"HealthSink attached but no packet seen yet. "
                                    f"Failure count is {count}/{threshold}."}
                return {"stream_health": "unhealthy",
                        "rule": "no_data_threshold_reached",
                        "summary": f"HealthSink attached but no packet ever arrived. "
                                f"Failure threshold reached at {count}/{threshold}."}
            return {"stream_health": "suspect",
                    "rule": "heartbeat_missing",
                    "summary": f"Heartbeat is missing ({heartbeat.get('reason')}). "
                            f"Failure count is {count}/{threshold}."}

        return {
            "stream_health": "suspect",
            "rule": "action_failure",
            "summary": f"{failure_reason}. Failure count is {count}/{threshold}.",
        }
    
    @staticmethod
    def _extract_action_error(action_result):
        if action_result.get("error"):
            return action_result["error"]
        for key in ("verify_result", "restart_result"):
            result = action_result.get(key)
            if isinstance(result, dict) and result.get("error"):
                return result["error"]
        return None 
    
    @staticmethod
    def _build_action_signal(action_result):
        action_taken = action_result.get("action", "none")
        if action_taken == "none":
            return {"taken": "none", "detail": None}
        # stream_status and heartbeat are surfaced under signals already, so
        # keep them out of detail to avoid duplicating raw copies.
        detail = {k: v for k, v in action_result.items()
                  if k not in {"action", "stream_index", "stream_status", "heartbeat"}}
        return {"taken": action_taken, "detail": detail or None}
    
class DeviceWatcher(threading.Thread):
    """Independent watchdog thread for one standalone (non-DataFlow) device."""
    @staticmethod
    def _device_key(device):
        for attr in ("port", "device_name", "_name"):
            v = getattr(device, attr, None)
            if v:
                return str(v)
        return f"device-{id(device)}"
    
    def __init__(self, device, *, failure_threshold, interval_sec, timeout_sec,
                 publish):
        self._key = self._device_key(device)
        super().__init__(name=f"device-watcher-{self._key}", daemon=True)
        self._hw = HardwareMonitor(failure_threshold=failure_threshold)
        self._hw.watch(device)                 # this thread owns just this device
        self._interval_sec = interval_sec
        self._timeout_sec = timeout_sec
        self._publish = publish
        self._stop_event = threading.Event()

    @property
    def key(self):
        return self._key

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            try:
                states = self._hw.poll_device_health_once(self._timeout_sec)
                report = next(iter(states.values()), {"status": "unknown"})
            except Exception as error:
                report = {"status": "suspect",
                          "error": f"{type(error).__name__}: {error}"}
            report = {**report, "checked_at": _now_rel()}
            self._publish(self._key, report)
            self._stop_event.wait(self._interval_sec)
    