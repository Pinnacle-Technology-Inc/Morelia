"""
Welcome to the live demo! Below is a simple script that will allow you to stream from pod devices and view the data from a Grafana dashboard in real time! 
"""

# Import the proper classes
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import InfluxSink, EDFSink
from Morelia.Stream.data_flow import DataFlow
import sys

# Pass the array of devices from the wsl-setup.sh script
devices = sys.argv[1:]

# Inital live demo set up
print("Starting the live demo...")

# Create an array to store pod devices 
pods = {}

# Connect to 8206HR devices on /dev/ttyUSB0-2 and set the preamplifer gain to 10.
for idx, device in enumerate(devices):
    print(f"Connecting to pod device on {device} and setting the preamp gain to 10")
    pods[idx] = Pod8206HR(device, 10)

print(f"Devices available for connection: {pods} ")

# Confirm there is one device and create InfluxDB Sink for that device
# And change the mapping to include only that device
influx_sink = InfluxSink(pods[0])
mapping = [(pods[0], [influx_sink])]

# Write your own dump for the second Pod device here! 

flowgraph = DataFlow(mapping)

print("Start of data collection!")
flowgraph.collect_for_seconds(60)

print("End of data collection!")
