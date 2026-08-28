import time
from pprint import pprint

from Morelia.Devices import Pod8206HR
from Morelia.Stream.data_flow import DataFlow
from Morelia.Stream.sink.csv_sink import CSVSink
from Morelia.Watchdog import Watchdog


if __name__ == "__main__":
    port_8206_0 = "COM4"  # change to the first 8206HR's port
    port_8206_1 = "COM5"  # change to the second 8206HR's port

    pod_8206_0 = Pod8206HR(port_8206_0, 10, sample_rate=2000)

    pod_8206_1 = Pod8206HR(port_8206_1, 10, sample_rate=2000)

    # Each stream gets its own destination sink.
    sink_8206_0 = CSVSink(file_path="stream0_8206.csv", pod=pod_8206_0)
    sink_8206_1 = CSVSink(file_path="stream1_8206.csv", pod=pod_8206_1)

    # Two sources -> two workers in the same flowgraph.
    flowgraph = DataFlow([
        (pod_8206_0, [sink_8206_0]),
        (pod_8206_1, [sink_8206_1]),
    ])

    # The Watchdog builds its own DataFlowMonitor over both streams; it watches
    # every worker in the flowgraph, not just the first.
    watchdog = Watchdog(flowgraph=flowgraph, max_heartbeat_age_sec=15.0)
    diag = None

    try:
        watchdog.preflight()
        flowgraph.collect()
        time.sleep(2)

        watchdog.run(
            report_interval_sec=15.0,
            stream_interval=15.0,
            timeout_sec=15.0,
            on_result=lambda r: (print("\nWatchdog result:"), pprint(r, sort_dicts=False)),
            verbose=True,
        )
    finally:
        # Stops every worker through the monitor's None-safe stop_stream and
        # shuts the status Manager. CSVSink flushes/closes its file as the
        # workers are torn down.
        watchdog.close()
