"""Send data to CSV file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import csv
from typing import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import AcquisitionDevice, Pod8274D, Pod8206HR, Pod8401HR
from Morelia.packet.data import DataPacket

class CSVSink(SinkInterface):
    """Stream data to a CSV file, truncates the destination file each time.
    
    :param file_path: Path to CSV file to write to.

    :param pod: POD device data is being streamed from.
    """

    def __init__(self, file_path: str, pod: AcquisitionDevice) -> None:
        """Class constructor."""
        self._file_path = file_path
        
        self._pod = pod
   
    def __enter__(self) -> Self:
        self._file_handle = open(self._file_path, 'w', newline='') 
        self._csv_writer = csv.writer(self._file_handle)

        if isinstance(self._pod, Pod8206HR):
                self._csv_writer.writerow(('time', 'EEG1', 'EEG2', 'EEG3/EMG'))

        elif isinstance(self._pod, Pod8401HR):

            preamp_channel_names: list[str] = Pod8401HR.get_channel_map_for_preamp_device(self._pod.preamp).values() if not self._pod.preamp is None else ['A', 'B', 'C', 'D']

            self._csv_writer.writerow(('time',) + tuple(preamp_channel_names) + ('aEXT0', 'aEXT1', 'aTTL1', 'aTTL2', 'aTTL3', 'aTTL4'))

        elif isinstance(self._pod, Pod8274D):
                self._csv_writer.writerow(('time', 'length_in_bytes', 'data'))

        else:
            raise ValueError(f'Device "{self._pod.device_name}" cannot be streamed from!')

    def __exit__(self, *args, **kwargs) -> bool:
        self._file_handle.close()
        del self._csv_writer
        del self._file_handle
        return False

    #TODO: check that sink is open
    def flush(self, timestamp: int, packet: DataPacket) -> None:
        """
        :meta private:
        """

        if isinstance(self._pod, Pod8206HR):
            self._csv_writer.writerow((timestamp,) + (packet.ch0, packet.ch1, packet.ch2, packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4))

        elif isinstance(self._pod, Pod8401HR):
            channel_data = (packet.ch0, packet.ch1, packet.ch2, packet.ch3)
            aext_data = (packet.ext0, packet.ext1)
            attl_data = (packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4)
            self._csv_writer.writerow((timestamp,) + channel_data + aext_data + attl_data)
        
        #TODO: 8274D
