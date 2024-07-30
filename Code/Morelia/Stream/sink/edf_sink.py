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
from Morelia.Packets import Packet, PacketBinary4
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AquisitionDevice

class EDFSink(SinkInterface):
    """Stream data to an EDF file.

    :param sample_rate: Sample rate of device being streamed from. Used in
    setting up EDF file.
    :type sample_rate: int

    :param file_path: Path to CSV file to write to.
    :type file_path: str

    :param pod: POD device data is being streamed from.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """

    def __init__(self, file_path: str, pod: AquisitionDevice ) -> None:
        """ Class constructor."""
        self._file_path = file_path
        self._pod = pod

        if isinstance(self._pod, Pod8206HR):
                self._channels = ('EEG1', 'EEG2', 'EEG3/EMG')

        elif isinstance(self._pod, Pod8401HR):

            preamp_channel_names: list[str] = Pod8401HR.GetChannelMapForPreampDevice(self._pod.preamp).values() if not self._pod.preamp is None else ['A', 'B', 'C', 'D']

            self._channels = tuple(preamp_channel_names) + ('aEXT0', 'aEXT1', 'aTTL1', 'aTTL2', 'aTTL3', 'aTTL4')

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

        #for idx, channel in enumerate(self._buffer):
        #    while len(self._buffer[idx]) < self._pod.sample_rate:
        #        channel.append(0.0)
        #        #self._buffer[idx] = np.append(channel, [0])
        #    #    print(len(self._buffer[idx]))

        self._write_buffer_to_edf()
        print(self._edf_writer.counter)

        self._edf_writer.close()
        del self._edf_writer

        return False


    #we have a "useless" timestamp paramater here so we implement the same function "interface".
    #TODO: typhint packet
    #TODO: check if sink is open
    #TODO: 8274
    def flush(self, timestamp: int, packet) -> None:
        
        if isinstance(self._pod, Pod8206HR):
            for idx, val in enumerate((packet.Ch(0), packet.Ch(1), packet.Ch(2))):
                self._buffer[idx].append(round(val * 1E6, 12))

        elif isinstance(self._pod, Pod8401HR):

            channel_data = (packet.Channel('A'), packet.Channel('B'), packet.Channel('C'), packet.Channel('D'))
            aext_data = (packet.AnalogEXT(0), packet.AnalogEXT(1))
            attl_data = (packet.AnalogTTL(1), packet.AnalogTTL(2), packet.AnalogTTL(3), packet.AnalogTTL(4))
        
            for idx, val in enumerate(aext_data + attl_data + channel_data):
                self._buffer[idx].append(round(val * 1E6, 12))

        if len(self._buffer[0]) > self._pod.sample_rate:
            self._write_buffer_to_edf()

    def _write_buffer_to_edf(self) -> None:
        self._edf_writer.writeSamples(list(map(np.array, self._buffer)))
        self._buffer = [ [] for _ in self._channels ]
