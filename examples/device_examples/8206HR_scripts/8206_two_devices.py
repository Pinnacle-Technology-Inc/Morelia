"""Record two 8206HR devices to separate CSV files for each run."""

import time

from Morelia.Devices import Pod8206HR
from Morelia.Stream.data_flow import DataFlow
from Morelia.Stream.sink import CSVSink


# Required for multiprocessing on Windows.
if __name__ == "__main__":
    sample_rate = 2000
    duration_seconds = 60
    runs = 3
    preamp_gain = 10  # Same as the existing 8206 example; use 100 for a 100x preamp.

    try:
        for i in range(runs):
            pods = []
            mapping = []
            try:
                for port in ("COM19", "COM20"):
                    pod = Pod8206HR(
                        port=port,
                        preamp_gain=preamp_gain,
                        baudrate=115200,
                        device_name=port,
                    )
                    pods.append(pod)
                    pod.sample_rate = sample_rate

                    csv_sink = CSVSink(f"8206_{port}_run{i+1}.csv", pod)
                    mapping.append((pod, [csv_sink]))

                flowgraph = DataFlow(mapping)
                with flowgraph:
                    print(f"Recording COM3-COM4 at {sample_rate} Hz, run {i+1}. "
                          "Press Ctrl+C to stop early.")
                    time.sleep(duration_seconds)
            finally:
                for pod in pods:
                    pod.cleanup()
    except KeyboardInterrupt:
        print("Recording stopped.")
