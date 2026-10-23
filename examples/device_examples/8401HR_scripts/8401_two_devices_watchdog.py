"""Stream two 8401HR devices and print selected Watchdog health signals."""

import json
import multiprocessing
import os
import time
import uuid
from datetime import datetime, timezone
from pprint import pprint

from Morelia.Devices import Pod8401HR, Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.Stream.data_flow import DataFlow
from Morelia.Watchdog.watchdog import Watchdog


# Edit these settings before running. Preamp settings match 8401_multiple.py.
PORTS = ("COM8", "COM13")
SAMPLE_RATE = 2000
BAUDRATE = 115200
PREAMP = Preamp.Preamp8406_SE4
PREAMP_GAIN = (100, 100, 100, 100)
SS_GAIN = (5, 5, 5, 5)
DURATION_SEC = 300  # Set to 0 to run until Ctrl+C.
REPORT_INTERVAL_SEC = 1.0
STREAM_INTERVAL_SEC = 1.0
TIMEOUT_SEC = 5.0
MAX_HEARTBEAT_AGE_SEC = 10.0
RECOVERY_POLICY = "automate"  # Use "automate" to enable automatic rebuilds.
TRACE_SERIAL_CONNECTIONS = True  # Print native handles on open/close and source errors.


def print_serial_trace(event, **fields):
    if TRACE_SERIAL_CONNECTIONS:
        print(json.dumps({
            "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            "pid": os.getpid(),
            "process": multiprocessing.current_process().name,
            **fields,
        }, default=str), flush=True)


class TracedPod8401HR(Pod8401HR):
    """Observe the existing serial handle; never open an extra diagnostic handle."""

    def open_port(self):
        try:
            super().open_port()
        except Exception as error:
            print_serial_trace("serial_open_failed", port=self._port_value, error=repr(error))
            raise
        serial_port = getattr(self._port, "_serial_inst", None)
        handle = getattr(serial_port, "_port_handle", None)
        handle = getattr(handle, "value", handle)
        # This UUID is our per-open correlation marker, NOT a Windows device ID.
        self._trace_connection = {
            "port": self._port_value,
            "open_id": uuid.uuid4().hex,
            "win32_handle": handle,
            "win32_handle_hex": hex(handle) if isinstance(handle, int) else None,
        }
        self._trace_read_failed = False
        print_serial_trace("serial_open", **self._trace_connection)

    def close_port(self):
        was_open = getattr(self, "_port", None) is not None
        connection = getattr(self, "_trace_connection", {"port": self._port_value})
        try:
            super().close_port()
        except Exception as error:
            print_serial_trace("serial_close_failed", **connection, error=repr(error))
            raise
        if was_open:
            print_serial_trace("serial_close", **connection)

    def read_pod_packet_streaming(self, timeout_sec=0.1, validate_checksum=True):
        # The subclass is reconstructed on recovery, so this tracing survives
        # worker replacement. Print only the first failure and the next success.
        connection = getattr(self, "_trace_connection", {"port": self._port_value})
        try:
            packet = super().read_pod_packet_streaming(
                timeout_sec=timeout_sec, validate_checksum=validate_checksum,
            )
        except Exception as error:
            if not getattr(self, "_trace_read_failed", False):
                print_serial_trace(
                    "serial_read_failed", **connection,
                    error_type=type(error).__name__, error=repr(error),
                )
            self._trace_read_failed = True
            raise
        if getattr(self, "_trace_read_failed", False):
            print_serial_trace("serial_read_resumed", **connection)
            self._trace_read_failed = False
        return packet


def print_stream_table(report):
    def number(value, decimals=0):
        return "-" if value is None else f"{value:.{decimals}f}"

    row_format = "{:<6} {:<10} {:<9} {:>7} {:>9} {:>10} {:>7}  {}"
    print(row_format.format(
        "Stream", "Health", "Heartbeat", "Age(s)", "Rate(Hz)", "Packets", "Fails", "Rule",
    ))
    details = []
    for stream in report.get("streams", []):
        signals = stream.get("signals", {})
        heartbeat = signals.get("heartbeat", {})
        failure = signals.get("failure", {})
        index = stream.get("stream_index", "-")
        failures = f"{number(failure.get('count'))}/{number(failure.get('threshold'))}"
        print(row_format.format(
            index,
            stream.get("stream_health") or "-",
            heartbeat.get("status") or "-",
            number(heartbeat.get("age_sec"), 3),
            number(heartbeat.get("measured_sample_rate"), 1),
            number(heartbeat.get("packet_count")),
            failures,
            stream.get("rule") or "-",
        ))
        if heartbeat.get("reason"):
            details.append(f"  Stream {index} heartbeat reason: {heartbeat['reason']!r}")
        if failure.get("last_error"):
            details.append(f"  Stream {index} last error: {failure['last_error']!r}")
    for detail in details:
        print(detail)
    print(flush=True)


def main():
    pods = []
    watchdog = None

    try:
        for port in PORTS:
            pod = TracedPod8401HR(
                port=port,
                preamp=PREAMP,
                primary_channel_modes=(PrimaryChannelMode.EEG_EMG,) * 4,
                secondary_channel_modes=(SecondaryChannelMode.ANALOG,) * 2
                + (SecondaryChannelMode.DIGITAL,) * 4,
                preamp_gain=PREAMP_GAIN,
                ss_gain=SS_GAIN,
                baudrate=BAUDRATE,
                device_name=port,
                sample_rate=SAMPLE_RATE,
            )
            pods.append(pod)

        # Watchdog adds a HealthSink to each stream before workers are started.
        # No raw samples are printed or saved to files.
        flowgraph = DataFlow([(pod, []) for pod in pods])
        watchdog = Watchdog(
            flowgraph=flowgraph,
            sample_rates=[SAMPLE_RATE] * len(pods),
            failure_threshold=3,
            max_heartbeat_age_sec=MAX_HEARTBEAT_AGE_SEC,
            recovery_policy=RECOVERY_POLICY,
        )

        preflight = watchdog.preflight(timeout_sec=TIMEOUT_SEC, require_ready=False)
        if not preflight["ok"]:
            pprint(preflight, sort_dicts=False)
            raise RuntimeError("Preflight failed; collection was not started.")
        print("\nWatchdog preflight passed.", flush=True)

        flowgraph.collect()
        started_at = time.monotonic()
        print(
            f"\nMonitoring two 8401HR devices: stream 0={PORTS[0]}, stream 1={PORTS[1]}.\n"
            "Measured rate appears after about 5 seconds; stale heartbeats may retain an old rate.\n"
            "Press Ctrl+C to stop.",
            flush=True,
        )

        def print_report(report):
            elapsed = time.monotonic() - started_at
            print(f"\nWatchdog report at +{elapsed:.3f}s:", flush=True)
            print_stream_table(report)
            if DURATION_SEC > 0 and elapsed >= DURATION_SEC:
                watchdog.stop()

        watchdog.run(
            report_interval_sec=REPORT_INTERVAL_SEC,
            stream_interval=STREAM_INTERVAL_SEC,
            timeout_sec=TIMEOUT_SEC,
            on_result=print_report,
            verbose=True,
        )
    except KeyboardInterrupt:
        print("\nStopping both streams...", flush=True)
    finally:
        if watchdog is not None:
            watchdog.close()
        for pod in pods:
            try:
                pod.close_port()
            except Exception as error:
                print(f"Could not close device port: {error}", flush=True)
        print("Done.", flush=True)


# Required for multiprocessing on Windows.
if __name__ == "__main__":
    main()
