from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.write_api_async import WriteApiAsync
from influxdb_client import Point, WritePrecision
import pandas as pd

from PodApi.Stream.Sink import SinkInterface
from PodApi.Packets import Packet
from PodApi.Stream.PodHandler import DrainDeviceHandler
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D

# authorship
__author__      = "James Hurd"
__maintainer__  = "Thresa Kelly"
__credits__     = ["James Hurd", "Sam Groth", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2024, Thresa Kelly"
__email__       = "sales@pinnaclet.com"
 
class InfluxSink(SinkInterface):
    """Stream data to InfluxDB for real-time monitoring."""

    def __init__(self, url: str, api_token: str, org: str, bucket: str, measurement: str, pod: Pod8206HR | Pod8274D | Pod8401HR) -> None:
        """Set instance variables.

        Args:
            url str: URL that points to an InfluxDB server.
            api_token str: API token to authenticate to InfluxDB. Needs write permissions.
            org str: Organization within InfluxDB to write data to.
            bucket: Bucket within InfluxDB to write data to.
            measurement: Measurement within InfluxDB to write data to.
            pod (Pod8206HR | Pod8401HR | Pod8274D): 8206-HR/8401-HR/8274D POD device you are streaming data from.
        """

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

        Args:
            timestamps list[float]: A list of timestamps for data.
            raw data list[Packet|None]: A list of data packets from a device.
        """
        structured_data: pd.DataFrame = self._dev_handler.DropToDf(timestamps,raw_data).set_index('Time')

        async with InfluxDBClientAsync(url=self.url, token=self.__api_token, org=self.org) as client:
            writer: WriteApiAsync = client.write_api()
            for time, data in structured_data.iterrows():
                points: list[Point]  = [ Point(self.measurement).time(time).tag('channel', channel).field('value', data_point) for channel, data_point in data.items() ]
                await writer.write(bucket=self.bucket, org=self.org, record=points)
