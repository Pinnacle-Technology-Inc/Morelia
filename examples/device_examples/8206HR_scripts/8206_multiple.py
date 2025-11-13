# import all of the classes
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import EDFSink, InfluxSink 
from Morelia.Stream.data_flow import DataFlow

# create 3 device objects on different ports (Linux)
pod_1 = Pod8206HR('/dev/ttyUSB0', 10)
pod_2 = Pod8206HR('/dev/ttyUSB1', 10)
pod_3 = Pod8206HR('/dev/ttyUSB2', 10)

# create 3 influx sinks, each corresponding to the pod devices above
influx_sink_1 = InfluxSink(pod_1)
influx_sink_2 = InfluxSink(pod_2)
influx_sink_3 = InfluxSink(pod_3)

# create 3 edf sinks, each corresponding to the pod devices above
# use edf files in directory to send to (does not exist in example)
edf_sink_1 = EDFSink('edf_dump1.edf', pod_1)
edf_sink_2 = EDFSink('edf_dump2.edf', pod_2)
edf_sink_3 = EDFSink('edf_dump3.edf', pod_3)

# map each pod device to its 2 respective sinks.
mapping = [(pod_1, [edf_sink_1, influx_sink_1]),
           (pod_2, [edf_sink_2, influx_sink_2]),
           (pod_3, [edf_sink_3, influx_sink_3])]

# create DataFlow object from mapping 
flowgraph = DataFlow(mapping)

# stream infinitely until flag is True
flag = False
with flowgraph:

    while True:

        if flag:

            break

