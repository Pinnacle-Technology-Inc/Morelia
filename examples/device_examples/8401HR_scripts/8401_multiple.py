"""Record four 8401HR devices with 8406-SE4 preamps to separate CSV files."""

import time

from Morelia.Devices import Pod8401HR, Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.Stream.data_flow import DataFlow
from Morelia.Stream.sink import CSVSink


# Required for multiprocessing on Windows.
if __name__ == "__main__":
    sample_rate = 2000
    duration_seconds = 60*5
    runs = 3
    pods = []
    mapping = []

    try:
        for i in range(runs):
            pods = []
            mapping = []
            for port in ("COM4",):
                pod = Pod8401HR(
                    port=port,
                    preamp=Preamp.Preamp8406_SE4,
                    primary_channel_modes=(PrimaryChannelMode.EEG_EMG,) * 4,
                    secondary_channel_modes=(SecondaryChannelMode.ANALOG,) * 2
                    + (SecondaryChannelMode.DIGITAL,) * 4,
                    preamp_gain=(100, 100, 100, 100),
                    ss_gain=(5, 5, 5, 5),
                    baudrate=115200,
                    device_name=port,
                )
                pod.sample_rate = sample_rate
                pods.append(pod)
                csv_sink = CSVSink(f"8401_{port}_run{i+1}.csv", pod)
                mapping.append((pod, [csv_sink]))

            # One acquisition process per device, as in 8206_multiple.py.
            flowgraph = DataFlow(mapping)
            with flowgraph:
                print(f"Recording COM3 at 2000 Hz ar run {i+1}. Press Ctrl+C to stop early.")
                time.sleep(duration_seconds)
    except KeyboardInterrupt:
        print("Recording stopped.")
    finally:
        for pod in pods:
            pod.cleanup()
