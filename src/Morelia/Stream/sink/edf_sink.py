"""Send data to EDF file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

from pyedflib import EdfWriter
from typing import Self
import numpy as np
import functools as ft

from Morelia.Stream.sink import SinkInterface
from Morelia.packet.data import DataPacket
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

class EDFSink(SinkInterface):
    """Stream data to an EDF file.

    :param sample_rate: Sample rate of device being streamed from. Used in setting up EDF file.
    :param file_path: Path to CSV file to write to.
    :param pod: POD device data is being streamed from.
    """

    def __init__(self, file_path: str, pod: AcquisitionDevice ) -> None:
        """ Class constructor."""
        self._file_path = file_path
        self._pod = pod

        if isinstance(self._pod, Pod8206HR):
                self._channels = ('EEG1', 'EEG2', 'EEG3/EMG', 'TTL1', 'TTl2', 'TTL3', 'TTl4')

        elif isinstance(self._pod, Pod8401HR):

            preamp_channel_names: list[str] = Pod8401HR.get_channel_map_for_preamp_device(self._pod.preamp).values() if not self._pod.preamp is None else ['A', 'B', 'C', 'D']

            self._channels = tuple(preamp_channel_names) + ('EXT0', 'EXT1', 'TTL1', 'TTL2', 'TTL3', 'TTL4')

        elif isinstance(self._pod, Pod8274D):
                self._channels('length_in_bytes', 'data')


        self._buffer = [ [] for _ in self._channels ]

    def __enter__(self) -> Self:

        EDF_PHYSICAL_BOUND = 2046
        EDF_DIGITAL_MAX = 32767
        EDF_DIGITAL_MIN = -32768

        self._edf_writer = EdfWriter(self._file_path, len(self._channels))

        for idx, channel in enumerate(self._channels):
           self._edf_writer.setSignalHeader( idx, {
                'label'         :  channel,
                'dimension'     :  'uV',
                'sample_frequency'   :  self._pod.sample_rate,
                'physical_max'  :  EDF_PHYSICAL_BOUND,
                'physical_min'  : -EDF_PHYSICAL_BOUND,
                'digital_max'   :  EDF_DIGITAL_MAX,
                'digital_min'   :  EDF_DIGITAL_MIN,
                'transducer'    :  '',
                'prefilter'     :  ''
            } )

        return self

    def __exit__(self, *args, **kwargs) -> bool:

        self._write_buffer_to_edf()

        self._edf_writer.close()
        del self._edf_writer

        return False


    #we have a "useless" timestamp paramater here so we implement the same function "interface".
    #TODO: check if sink is open
    #TODO: 8274
    def flush(self, timestamp: int, packet: DataPacket) -> None:
        """
        :meta private:
        """
        
        if isinstance(self._pod, Pod8206HR):
            self._buffer[0].append(packet.ch0)
            self._buffer[1].append(packet.ch1)
            self._buffer[2].append(packet.ch2)
            self._buffer[3].append(float(packet.ttl1))
            self._buffer[4].append(float(packet.ttl2))
            self._buffer[5].append(float(packet.ttl3))
            self._buffer[6].append(float(packet.ttl4))

        elif isinstance(self._pod, Pod8401HR):
            self._buffer[0].append(packet.ch0)
            self._buffer[1].append(packet.ch1)
            self._buffer[2].append(packet.ch2)
            self._buffer[3].append(packet.ch3)
            self._buffer[4].append(float(packet.ext0))
            self._buffer[5].append(float(packet.ext1))
            self._buffer[6].append(float(packet.ttl1))
            self._buffer[7].append(float(packet.ttl2))
            self._buffer[8].append(float(packet.ttl3))
            self._buffer[9].append(float(packet.ttl4))

        if len(self._buffer[0]) >= self._pod.sample_rate:
            self._write_buffer_to_edf()

    def _write_buffer_to_edf(self) -> None:
        self._edf_writer.writeSamples(list(map(np.array, self._buffer)))
        self._buffer = [ [] for _ in self._channels ]
