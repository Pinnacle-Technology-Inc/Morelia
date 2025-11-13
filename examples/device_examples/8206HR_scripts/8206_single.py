# import all of the classes
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import InfluxSink 
from Morelia.Stream.data_flow import DataFlow

# create POD device from port ttyUSB0 (Linux), and set preamp gain to 10
pod_1 = Pod8206HR('/dev/ttyUSB0', 10)

# create influx sink instance with default values
influx_sink_1 = InfluxSink(pod_1)

# map the pod device to a single sink 
mapping = [(pod_1, [influx_sink_1])]

# create the flowgraph object to stream with using the mapping
flowgraph = DataFlow(mapping)

# stream infinitely, until flag is True
flag = False

with flowgraph:

    while True:

        if flag:
            break

