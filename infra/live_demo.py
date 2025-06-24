"""
Welcome to the live demo! Below is a simple script that will allow you to stream from pod devices and view the data from a Grafana dashboard in real time! 
"""

# Import the proper classes
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import InfluxSink
from Morelia.Stream.data_flow import DataFlow

# Recieve the correct device ID from the user for the live demo
id = str(input("What was your device id#? (/dev/ttyUSB<id#>): "))

# Connect to 8206HR devices on on /dev/ttyUSB0-2 and set the preamplifer gain to 10.
pod_influxdb = Pod8206HR(f'/dev/ttyUSB{id}', 10)

# Create InfluxDB Sink
influx_sink = InfluxSink(pod_influxdb)

mapping = [(pod_influxdb, [influx_sink])]

flowgraph = DataFlow(mapping)

print("Start of data collection!")
flowgraph.collect_for_seconds(3*60)

print("End of data collection!")

