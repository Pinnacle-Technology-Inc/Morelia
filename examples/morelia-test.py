
from Morelia.Devices import Pod8206HR
from Morelia.packet.data import DataPacket
from Morelia.Stream.sink import EDFSink
import Morelia.Stream.data_flow as data_flow


# Connect to an 8206HR device
pod = Pod8206HR('COM5', 100)
# have to do this until sample rate property is fixed
if isinstance(pod.sample_rate, tuple):
    pod.sample_rate = pod.sample_rate[0]

edf_dump = EDFSink('test.edf', pod)
mapping = [(pod, [edf_dump])]
flowgraph = data_flow.DataFlow(mapping)
flowgraph.collect_for_seconds(1)

