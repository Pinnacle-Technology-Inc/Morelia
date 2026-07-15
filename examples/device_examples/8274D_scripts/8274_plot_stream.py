import multiprocessing as mp
import threading

from Morelia.Devices import Pod8274D
from Morelia.Stream.sink import PlotSink, PlotDisplay
from Morelia.Stream.data_flow import DataFlow

# Required for multiprocessing.
if __name__ == "__main__":
    # Connect to an 8274.
    pod = Pod8274D(
        # TODO: replace with your serial port (e.g. COM4 or /dev/ttyUSB0)
        port="REPLACE_WITH_PORT",
        # TODO: Replace this with your device's serial number. It is printed on the top of the device.
        device_serial_number='YOUR_DEVICE_SERIAL_NUMBER',
        sample_rate=1024
        )

    # Create queue
    queue = mp.Queue(maxsize=2048)

    # Create plot sink.
    plot_sink = PlotSink(queue, pod)

    # create mapping
    mapping = [(pod, [plot_sink])]

    # Create display
    display = PlotDisplay(queue)

    # Create flowgraph
    flowgraph = DataFlow(mapping)

    # Run plotting in main thread
    t = threading.Thread(target=flowgraph.collect)
    t.start()

    # Run
    display.run()
