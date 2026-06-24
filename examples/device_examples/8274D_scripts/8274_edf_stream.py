from Morelia.Devices import Pod8274D
from Morelia.Stream.sink import EDFSink
from Morelia.Stream.data_flow import DataFlow

# Required for multiprocessing
if __name__ == "__main__":
    # Connect to an 8274D.
    pod = Pod8274D(
        port="COM4",
        # TODO: Replace this with your device's serial number. It is printed on the top of the device.
        device_serial_number='YOUR_DEVICE_SERIAL_NUMBER',
        sample_rate=1024
        )

    # Create CSV sinks
    edf_dump = EDFSink("8274D_data.edf", pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [edf_dump]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a time period.
    flowgraph.collect_for_seconds(duration_sec=30)