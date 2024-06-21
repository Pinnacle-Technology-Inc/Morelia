import aiofiles

from PodApi.Stream.Sink import SinkInterface
from PodApi.Stream.PodHandler import DrainDeviceHandler
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D
from PodApi.Packets import Packet

# authorship
__author__      = "James Hurd"
__maintainer__  = "Thresa Kelly"
__credits__     = ["James Hurd", "Sam Groth", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2024, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class CsvSink(SinkInterface):
    """Stream data to a CSV file, truncates the destination file each time.
    
    :param file_path: Path to CSV file to write to.
    :type file_path: str

    :param pod: POD device data is being streamed from.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """

    def __init__(self, file_path: str, pod: Pod8206HR | Pod8401HR | Pod8274D) -> None:
        """Class constructor."""

        self._file_path = file_path
        
        self._dev_handler: DrainDeviceHandler = SinkInterface.get_device_handler(pod)

        with open(self._file_path, 'w') as f:
            f.write(self._dev_handler.GetDeviceColNames())
   
    #make filepath an immutable attribute, changing this could cause problems with
    #data being split across files...
    @property
    def file_path(self) -> str:
        return self._file_path

    async def flush(self, timestamps: list[float], raw_data: list[Packet|None]) -> None:
        """Write a drop of data to CSV.

        :param timestamps: A list of timestamps for data.
        :type timestamps: list[float]
        :param raw_data: A list of data packets from a device.
        :type raw_data: list[:class: Packet|None]
        """
        async with aiofiles.open(self._file_path, 'w') as f:
            structured_data: pd.DataFrame = self._dev_handler.DropToDf(timestamps,raw_data)
            await f.write(structured_data.to_csv(index=False).split('\n',1) [1] )
