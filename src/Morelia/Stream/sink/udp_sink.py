"""Send data to CSV file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import socket
from typing import Self


from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import AcquisitionDevice, Pod8274D, Pod8206HR, Pod8401HR
from Morelia.packet.data import DataPacket

class UDPSink(SinkInterface):
    """Stream data to a buffer

    :param pod: POD device data is being streamed from.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """

    def __init__(self, port, pod: AcquisitionDevice) -> None:
        """Class constructor."""
        self._pod = pod
        self._port = port
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(('', self._port)) # pass '' as hostname, so that we can accept any connection
        self._socket.listen()
        self._connection, self._address = self._socket.listen()
        self._counter = 0
   
    #def __enter__(self) -> Self:
        
        # if isinstance(self._pod, Pod8206HR):
        #     self._buffer.append(('time', 'EEG1', 'EEG2', 'EEG3/EMG'))

        # elif isinstance(self._pod, Pod8401HR):

        #     preamp_channel_names: list[str] = Pod8401HR.GetChannelMapForPreampDevice(self._pod.preamp).values() if not self._pod.preamp is None else ['A', 'B', 'C', 'D']

        #     self._buffer.append(('time',) + tuple(preamp_channel_names) + ('aEXT0', 'aEXT1', 'aTTL1', 'aTTL2', 'aTTL3', 'aTTL4'))

        # elif isinstance(self._pod, Pod8274D):
        #     self._buffer.append(('time', 'length_in_bytes', 'data'))

        # else:
        #     raise ValueError(f'Device "{self._pod.device_name}" cannot be streamed from!')

    def __exit__(self, *args, **kwargs) -> bool:
        return False
    
    #TODO: check that sink is open
    def flush(self, timestamp: int, packet: DataPacket) -> None:

        if isinstance(self._pod, Pod8206HR):
            #self._buffer.append( (timestamp, (packet.ch0, packet.ch1, packet.ch2, packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4)) )
            self._socket.send(self._counter)
        elif isinstance(self._pod, Pod8401HR):
            channel_data = (packet.ch0, packet.ch1, packet.ch2, packet.ch3)
            aext_data = (packet.ext0, packet.ext1)
            attl_data = (packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4)
            self._buffer.append( timestamp,  (channel_data + aext_data + attl_data))

        #TODO: 8274D
