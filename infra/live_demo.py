"""
Welcome to the live demo! Below is a simple script that will allow you to stream from pod devices and view the data from a Grafana dashboard in real time! 
"""

# Import the proper classes
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import InfluxSink, EDFSink
from Morelia.Stream.data_flow import DataFlow

# Inital live demo set up
print("Starting the live demo...")

# Connect to 8206HR devices on /dev/ttyUSB0-2 and set the preamplifer gain to 10.
print(f"Connecting to pod device on /dev/ttyUSB0 and setting the preamp gain to 10")
pod_1 = Pod8206HR('/dev/ttyUSB0', 10)

# Confirm there is one device and create InfluxDB Sink for that device
# And change the mapping to include only that device
influx_sink = InfluxSink(pod_1)
mapping = [(pod_1, [influx_sink])]

# Write your own dump for the second Pod device here! 

flowgraph = DataFlow(mapping)

print("Start of data collection!")
flowgraph.collect_for_seconds(60)

print("End of data collection!")
