from Morelia.Devices import Pod8274D
from Morelia.Stream.sink import UDPSink
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

    # Create udp sink.
    udp_sink = UDPSink(
        port=9000,
        pod=pod,
        host="127.0.0.1"
        )

    # List that defines how sources map to sink.
    mapping = [ (pod, [udp_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a 5 minute time period.
    flowgraph.collect_for_seconds(duration_sec=60*5)