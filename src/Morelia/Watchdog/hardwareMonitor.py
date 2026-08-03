
class HardwareMonitor:
    """
    Watchdog for serial hardware devices (e.g. Pod8206HR): detects dropped
    connections by pinging, and automatically rebuilds the device object to
    recover.

    Status values: 
    - "unknown": never polled
    - "connected"/"reconnected": lasts one poll, then becomes "connected"
    - "ping failed": failing but below threshold
    - "disconnected": threshold reached, handle is None

    Notes
    -------------------
    - The constructor kwargs are snapshotted ONCE, at watch() time. If the
      device is reconfigured afterwards, a reconnect will rebuild it with
      the ORIGINAL settings. Re-call watch() to refresh the snapshot.
    - failure_threshold counts consecutive failed POLLS (each poll = one
      ping + one full reconnect attempt), not raw pings.
    - Polling is synchronous and serial: worst case one poll blocks about
      n_devices * 2 * timeout_sec (failed ping + failed reconnect ping),
      plus device construction time.
    - Device objects must provide: .port, .get_dict() (constructor kwargs),
      .write_read("PING", timeout_sec=...), and .close_port().
    """
    def __init__(self, failure_threshold: int):
        #Single source of truth: each device is one complete record keyed by name
        self.tracked_devices = {}
        #Number of consecutive failed polls before a device is declared disconnected
        self.failure_threshold = failure_threshold

    def watch(self, device, name=None):
        """
        Register an already-connected device for monitoring.

        Stores the live device plus everything needed to rebuild it later
        (class + constructor kwargs from device.get_dict()). The kwargs are
        snapshotted NOW — if the device's configuration changes afterwards,
        call watch() again so reconnects use the new settings.

        Re-watching an existing name overwrites the record and resets its
        failure state to a clean slate.

        :param device: Live device object (e.g. an initiated Pod8206HR)
        :param name: Optional display name; defaults to the device's port
        """
        device_name = name or str(device.port)
        self.tracked_devices[device_name] = {
            "device": device,           #live handle we ping; set to None once declared disconnected
            "device_class": type(device),
            "device_kwargs": device.get_dict(),  #recipe for rebuilding the device on reconnect
            "state": {
                "consecutive_failures": 0,      #failed polls in a row; reset to 0 on any success
                "last_error": None,             #message from the most recent failure, None when healthy
                "status": "unknown",            #see class docstring for the full set of values
            },
        }

    def get_devices(self):
        """
        Return (name, live_device) pairs for every tracked device.

        Note: the device is None for anything currently declared
        disconnected, so callers must None-check before using it.
        """
        return [(name, record["device"]) for name, record in self.tracked_devices.items()]

    def _ping_source_once(self, source, timeout_sec=1.0):
        """
        Send one PING to a device and report (ping_ok, error_message).

        error_message is None on success, otherwise a human-readable string.
        Never raises — any exception from the device is caught and returned
        as the error string. A None source (already declared disconnected)
        fails immediately without touching hardware.
        """
        if source is None:
            return False, "Device is not connected"
        try:
            source.write_read("PING", timeout_sec=timeout_sec)
            return True, None
        except Exception as error:
            return False, str(error)

    def poll_device_health_once(self, timeout_sec = 1.0):
        """
        Run one health-check pass over every tracked device. Call this
        periodically (e.g. from a timer loop) — each call is one "tick" of
        the watchdog state machine described in the class docstring.

        Per device: ping it; on failure, immediately try one full reconnect
        (close + rebuild + ping). Only a poll where BOTH fail counts toward
        failure_threshold. Reaching the threshold marks the device
        "disconnected" and drops its handle (record["device"] = None), but
        future polls keep retrying the rebuild, so recovery is automatic.

        Blocking: serial, worst case ~2 * timeout_sec per failing device.

        Output: dict(dict)
        "device_name": {
            - "status": str ("connected" | "reconnected" |"ping failed" | "disconnected")
            - "consecutive_failures": int, 
            - "last_error": str or None, message from the most recent failure
            }
        """
        results = {}
        #Loop through one dictionary; each record holds its own device + state
        for device_name, record in self.tracked_devices.items():
            device = record["device"]
            state = record["state"]

            #Start checking health
            ping_ok, error = self._ping_source_once(device, timeout_sec = timeout_sec)

            state["last_error"] = None if ping_ok else error

            if ping_ok:
                state["consecutive_failures"] = 0
                state["status"] = "connected"

            else: #ping failed -> don't wait, attempt a full reconnect this same poll
                reconnect_ok, new_device, reconnect_error = self.reconnect_device(record, timeout_sec=timeout_sec)
                if reconnect_ok:
                    #Recovered within the same poll: swap in the rebuilt device
                    record["device"] = new_device
                    state["status"] = "reconnected"
                    state["consecutive_failures"] = 0
                    state["last_error"] = None
                else:
                    #Both ping AND reconnect failed -> this poll counts toward the threshold
                    state["consecutive_failures"] += 1
                    state["last_error"] = reconnect_error

                    if state["consecutive_failures"] >= self.failure_threshold:
                        #Officially dead: drop the handle so callers see None.
                        #Still tracked though — next poll will retry the rebuild.
                        record["device"] = None
                        state["status"] = "disconnected"
                        state["last_error"] = reconnect_error
                    else:
                        state["status"] = "ping failed"
                
            results[device_name] = dict(state)
        return results        

                
    def _safe_close_device(self, device):
        """Best-effort close. Never let close errors crash reconnect logic."""
        if device is None:
            return
        try:
            device.close_port()
        except Exception:
            pass

    def _create_device(self, record):
        """
        Build a brand-new device from the recipe captured at watch() time
        (stored class called with the stored get_dict() kwargs). May raise —
        the caller (reconnect_device) handles failures.
        """
        device_class = record["device_class"]
        device_kwargs = record["device_kwargs"]
        return device_class(**device_kwargs)

    def reconnect_device(self, record, timeout_sec = 1.0):
        """
        One full reconnect attempt: close the old device, rebuild it from
        the stored recipe, and verify the new one answers a ping.

        Does NOT modify the record or its state — the caller decides what
        to do with the result (poll_device_health_once swaps in the new
        device on success). Note the old device's port is closed regardless
        of outcome, so on failure the record is left holding a dead handle
        until the threshold logic clears it.

        :return: (True, new_device, None) on success,
                 (False, None, error_message) on failure (a new device that
                 was built but failed its ping is closed before returning).
        """
        self._safe_close_device(record["device"])
        new_device = None

        try:
            new_device = self._create_device(record)
        except Exception as error:
            return False, None, f"Failed to recreate device: {error}"

        ping_ok, error = self._ping_source_once(new_device, timeout_sec = timeout_sec)

        if not ping_ok:
            self._safe_close_device(new_device)
            return False, None, error

        return True, new_device, None

    def reset_streaming_device(self, device, max_reset_sec= 3.0 , idle_gap_sec= 1.0):
        """
        Stop leftover streaming on a device and drain its buffer so the next control handshake isn't buried in stale data
        """
        import time
        opened_here = getattr(device, "_port", None) is None
        try:
            if opened_here:
                # A just-stopped worker may not have released the port yet, so
                # retry the open briefly before giving up.
                for _ in range(5):
                    try:
                        device.open_port()
                        break
                    except Exception:
                        time.sleep(0.2)
                else:
                    return {"ok": False, "error": "open_port_failed_after_retries"}
            device.write_packet("STREAM", 0)
            drained, went_quiet, errs = 0, False, 0
            deadline = time.time() + max_reset_sec
            while time.time() < deadline:
                try:
                    device.read_pod_packet(validate_checksum=False, timeout_sec=idle_gap_sec)
                    drained += 1
                    errs = 0
                except TimeoutError:
                    went_quiet = True
                    break
                except Exception:
                    errs += 1
                    if errs >= 5: 
                        break
                    continue
            return {"ok": True, "drained_packets": drained, "device_quiet": went_quiet}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            if opened_here:
                self._safe_close_device(device) 

    @staticmethod
    def _cache_verified_sample_rate(device, verify_cmd, response):
        """Cache a sample rate verified while the device is quiet."""
        if str(verify_cmd).strip().upper() != "GET SAMPLE RATE":
            return

        try:
            payload = response.payload
            sample_rate = int(payload[0])
        except (AttributeError, IndexError, TypeError, ValueError) as error:
            raise ValueError("Invalid GET SAMPLE RATE response payload.") from error

        if sample_rate <= 0:
            raise ValueError("GET SAMPLE RATE returned a non-positive value.")

        # AcquisitionDevice.sample_rate stores the response payload in this
        # exact shape. Keeping it here lets legacy get_dict() implementations
        # carry the verified value into replacement workers without changing
        # the device or stream layers.
        device._sample_rate = payload

    def preflight_device(self, device, attempts=3, timeout_sec=5.0, verify_cmd="GET SAMPLE RATE"):
        """Clean-slate a device and confirm it answers a control command, resetting
        between attempts. Device-level readiness gate — valid whether or not the
        device will ever join a DataFlow. Never raises."""
        opened_here = getattr(device, "_port", None) is None
        if opened_here:
            try:
                device.open_port()
            except Exception as e:
                return {"ok": False, "attempts_used": 0, "error": f"open_port: {e}"}
        try:
            last_error = None
            for attempt in range(attempts):
                reset = self.reset_streaming_device(device)        # port already open -> no-op open
                try:
                    response = device.write_read(cmd=verify_cmd, timeout_sec=timeout_sec)
                    ping_ok, error = True, None
                    self._cache_verified_sample_rate(device, verify_cmd, response)
                except Exception as e:
                    ping_ok, error = False, str(e)
                if ping_ok:
                    return {"ok": True, "attempts_used": attempt + 1, "reset": reset}
                last_error = error if reset.get("ok") else f"{error}; reset: {reset.get('error')}" 
            return {"ok": False, "attempts_used": attempts, "error": last_error}
        finally:
            if opened_here:
                self._safe_close_device(device)
