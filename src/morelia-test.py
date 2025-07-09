
from Morelia.Devices import Pod8206HR
from Morelia.Devices import PodATD
from Morelia.packet.data import DataPacket
from Morelia.Stream.sink import UDPSink
import Morelia.Stream.data_flow as data_flow


# Connect to an 8206HR device
pod = Pod8206HR('/dev/ttyUSB0', 10)
# have to do this until sample rate property is fixed
if isinstance(pod.sample_rate, tuple):
    pod.sample_rate = pod.sample_rate[0]

udp_stream = UDPSink(12345, pod)
mapping = [(pod, [udp_stream])]
flowgraph = data_flow.DataFlow(mapping)
flowgraph.collect_for_seconds(5)

