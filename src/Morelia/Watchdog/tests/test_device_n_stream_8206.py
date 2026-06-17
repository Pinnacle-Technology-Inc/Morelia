"""
Static mixed 8206HR Watchdog test.

COM4 streams through DataFlow. COM5 is monitored only as a standalone
hardware device through Watchdog(devices=[...]).
"""

import threading
from pprint import pprint

from Morelia.Devices import Pod8206HR
from Morelia.Stream.data_flow import DataFlow
from Morelia.Stream.sink.csv_sink import CSVSink

from Morelia.Watchdog import Watchdog


DATAFLOW_PORT = "COM4"
HARDWARE_ONLY_PORT = "COM5"
GAIN = 10
SAMPLE_RATE = 2000
CSV_PATH = "stream0_8206_dataflow.csv"

DURATION_SEC = 600.0
REPORT_INTERVAL_SEC = 3.0
STREAM_INTERVAL_SEC = 1.0
DEVICE_INTERVAL_SEC = 1.0
TIMEOUT_SEC = 5.0
FAILURE_THRESHOLD = 3
MAX_HEARTBEAT_AGE_SEC = 10.0

if __name__ == "__main__":
    dataflow_pod = Pod8206HR(DATAFLOW_PORT, GAIN)
    dataflow_pod.sample_rate = SAMPLE_RATE

    hardware_only_pod = Pod8206HR(HARDWARE_ONLY_PORT, GAIN)
    hardware_only_pod.sample_rate = SAMPLE_RATE

    flowgraph = DataFlow([
        (dataflow_pod, [CSVSink(file_path=CSV_PATH, pod=dataflow_pod)]),
    ])

    watchdog = Watchdog(
        flowgraph=flowgraph,
        devices=[hardware_only_pod],
        failure_threshold=FAILURE_THRESHOLD,
        max_heartbeat_age_sec=MAX_HEARTBEAT_AGE_SEC,
    )

    stop_timer = None
    try:
        print(
            "\nMixed Watchdog test: "
            f"DataFlow 8206={DATAFLOW_PORT}, "
            f"hardware-only 8206={HARDWARE_ONLY_PORT}",
            flush=True,
        )

        print("\nWatchdog preflight:")
        pprint(watchdog.preflight(timeout_sec=TIMEOUT_SEC), sort_dicts=False)

        flowgraph.collect()

        if DURATION_SEC > 0:
            stop_timer = threading.Timer(DURATION_SEC, watchdog.stop)
            stop_timer.daemon = True
            stop_timer.start()

        watchdog.run(
            report_interval_sec=REPORT_INTERVAL_SEC,
            stream_interval=STREAM_INTERVAL_SEC,
            device_interval=DEVICE_INTERVAL_SEC,
            timeout_sec=TIMEOUT_SEC,
            on_result=lambda report: pprint(report, sort_dicts=False),
            verbose=True,
        )
    except KeyboardInterrupt:
        print("\nStopping mixed Watchdog test...", flush=True)
    finally:
        if stop_timer is not None:
            stop_timer.cancel()
        watchdog.close()
        for pod in (dataflow_pod, hardware_only_pod):
            try:
                pod.close_port()
            except Exception:
                pass
        print("Done.", flush=True)
