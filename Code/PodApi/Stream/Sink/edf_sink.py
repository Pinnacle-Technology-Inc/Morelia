from pyedflib import EdfWriter
import asyncio

from PodApi.Stream.Sink import SinkInterface
from PodApi.Packets import Packet
from PodApi.Stream.PodHandler import DrainDeviceHandler
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D

class EdfSink(SinkInterface):
    """Stream data to an EDF file.

    :param sample_rate: Sample rate of device being streamed from. Used in
    setting up EDF file.
    :type sample_rate: int

    :param file_path: Path to CSV file to write to.
    :type file_path: str

    :param pod: POD device data is being streamed from.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """

    def __init__(self, sample_rate: int, file_path: str, pod: Pod8206HR | Pod8401HR | Pod8274D ) -> None:
        """ Class constructor."""
        self._file_path = file_path
        self._dev_handler = SinkInterface.get_device_handler(pod)

        EDF_PHYSICAL_BOUND = 2046
        EDF_DIGITAL_MAX = 32767
        EDF_DIGITAL_MIN = -32768

        channels = [x for x in self._dev_handler.GetDeviceColNamesList(includeTime=False) if x !='NC']

        self._edf_writer = EdfWriter(self._file_path, len(channels))

        for idx, channel in enumerate(channels):
           self._edf_writer.setSignalHeader( idx, {
                'label'         :  channel,
                'dimension'     :  'uV',
                'sample_rate'   :  sample_rate,
                'physical_max'  :  EDF_PHYSICAL_BOUND,
                'physical_min'  : -EDF_PHYSICAL_BOUND,
                'digital_max'   :  EDF_DIGITAL_MAX,
                'digital_min'   :  EDF_DIGITAL_MIN,
                'transducer'    :  '',
                'prefilter'     :  ''
            } )

    #make filepath an immutable attribute, changing this could cause problems with
    #data being split across files...
    @property
    def file_path(self) -> str:
        return self._file_path

    #we have a "useless" timestamps paramater here so we implement the same function "interface".
    async def flush(self, timestamps: list[float], raw_data: list[Packet|None]) -> None:
        """Save a drop of data to EDF.

        :param timestamps: A list of timestamps for data.
        :type timestamps: list[float]
        :param raw_data: A list of data packets from a device.
        :type raw_data: list[:class: Packet|None]
        """
        data = self._dev_handler.DropToListOfArrays(raw_data)
        await asyncio.to_thread(self._edf_writer.writeSamples, data)
