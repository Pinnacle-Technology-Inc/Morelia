"""Send data to InfluxDB."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'
 
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.write_api_async import WriteApiAsync
from influxdb_client import Point, WritePrecision
import pandas as pd

from Morelia.Stream.sink import SinkInterface
from Morelia.Packets import Packet
from Morelia.Stream.PodHandler import DrainDeviceHandler
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D

class InfluxSink(SinkInterface):
    """Stream data to InfluxDB for real-time monitoring.

            :param url: URL that points to an InfluxDB server.
            :type url: str
            :param api_token: API token to authenticate to InfluxDB. Needs write permissions.
            :type api_token: str
            :param org: Organization within InfluxDB to write data to.
            :type org:
            :param bucket: Bucket within InfluxDB to write data to.
            :type bucket: str
            :param measurement: Measurement within InfluxDB to write data to.
            :type measurement: str
            :param pod: 8206-HR/8401-HR/8274D POD device you are streaming data from.
            :type pod: :class: Pod8206HR | Pod8401HR | Pod8274D
    """

    def __init__(self, url: str, api_token: str, org: str, bucket: str, measurement: str, pod: Pod8206HR | Pod8274D | Pod8401HR) -> None:
        """Set instance variables."""

        self.__api_token: str = api_token
        self._url: str = url

        self.org: str = org
        self.bucket: str = bucket
        self.measurement: str = measurement

        self._dev_handler: Drain8206HR | Drain8274D | Drain8401HR = SinkInterface.get_device_handler(pod)
   
    #since api_token is immutable, we also want url to be immutable.
    @property
    def url(self) -> str:
        return self._url

    async def flush(self, timestamps: list[float], raw_data: list[Packet|None]) -> None:
        """Send a drop of data to InfluxDB.

        :param timestamps: A list of timestamps for data.
        :type timestamps: list[float]
        :param raw_data: A list of data packets from a device.
        :type raw_data: list[:class: Packet|None]
        """
        structured_data: pd.DataFrame = self._dev_handler.DropToDf(timestamps,raw_data).set_index('Time')

        async with InfluxDBClientAsync(url=self.url, token=self.__api_token, org=self.org) as client:
            writer: WriteApiAsync = client.write_api()
            for time, data in structured_data.iterrows():
                points: list[Point]  = [ Point(self.measurement).time(time).tag('channel', channel).field('value', data_point) for channel, data_point in data.items() ]
                await writer.write(bucket=self.bucket, org=self.org, record=points)
