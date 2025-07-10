"""Send data to InfluxDB."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'
 
from influxdb_client import InfluxDBClient, WriteApi, WriteOptions
import reactivex as rx
import reactivex.operators as ops
from typing import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice
from Morelia.packet.data import DataPacket


class InfluxSink(SinkInterface):
    """Stream data to InfluxDB for real-time monitoring.

            :param url: URL that points to an InfluxDB server.
            :param api_token: API token to authenticate to InfluxDB. Needs write permissions.
            :param org: Organization within InfluxDB to write data to.
            :param bucket: Bucket within InfluxDB to write data to.
            :param measurement: Measurement within InfluxDB to write data to.
            :param pod: 8206-HR/8401-HR/8274D POD device you are streaming data from.
    """

    def __init__(self, pod: AcquisitionDevice, url: str = "http://localhost:8086", api_token: str = 'admin-token', org: str = 'default-org', bucket: str = 'influx_dump', measurement: str = 'default-measurement')  -> None:
        """Set instance variables."""

        self.__api_token: str = api_token
        self._url: str = url 
        self._pod: AcquisitionDevice = pod

        self._org: str = org
        self._bucket: str = bucket
        self._measurement: str = measurement
         
        if isinstance(self._pod, Pod8401HR):
            def _line_protocol_factory(timestamp, packet) -> str:
                return f"""{self._measurement},channel=CHA,name={self._pod.device_name} value={packet.ch0} {timestamp}
                       {self._measurement},channel=CHB,name={self._pod.device_name} value={packet.ch1} {timestamp}
                       {self._measurement},channel=CHC,name={self._pod.device_name} value={packet.ch2} {timestamp}
                       {self._measurement},channel=CHD,name={self._pod.device_name} value={packet.ch3} {timestamp}
                       {self._measurement},channel=aEXT0,name={self._pod.device_name} value={packet.ext0} {timestamp}
                       {self._measurement},channel=aEXT1,name={self._pod.device_name} value={packet.ext1} {timestamp}
                       {self._measurement},channel=TTL1,name={self._pod.device_name} value={packet.ttl1} {timestamp}
                       {self._measurement},channel=TTL2,name={self._pod.device_name} value={packet.ttl2} {timestamp}
                       {self._measurement},channel=TTL3,name={self._pod.device_name} value={packet.ttl3} {timestamp}
                       {self._measurement},channel=TTL4,name={self._pod.device_name} value={packet.ttl4} {timestamp}""".encode('utf-8')

        elif isinstance(self._pod, Pod8206HR):
            def _line_protocol_factory(timestamp, packet) -> str:
                return f"""{self._measurement},channel=CH0,name={self._pod.device_name} value={packet.ch0} {timestamp}
                       {self._measurement},channel=CH1,name={self._pod.device_name} value={packet.ch1} {timestamp}
                       {self._measurement},channel=CH2,name={self._pod.device_name} value={packet.ch2} {timestamp}
                       {self._measurement},channel=TTL1,name={self._pod.device_name} value={packet.ttl1} {timestamp}
                       {self._measurement},channel=TTL2,name={self._pod.device_name} value={packet.ttl2} {timestamp}
                       {self._measurement},channel=TTL3,name={self._pod.device_name} value={packet.ttl3} {timestamp}
                       {self._measurement},channel=TTL4,name={self._pod.device_name} value={packet.ttl4} {timestamp}""".encode('utf-8')
        
        self._subject = rx.Subject()
        self._data = self._subject.pipe(
            ops.starmap(_line_protocol_factory),
            ops.buffer_with_count(self._pod.sample_rate//2),
            ops.map(lambda x: b'\n'.join(x))
        )
    #the following two methods implement the context manager protocol to allow
    #this sink to work within a `with` block. To illuminate why these methods are the
    #they are, see the relevent section of the python manual:
    # https://docs.python.org/3/library/stdtypes.html#context-manager-types

    def __enter__(self) -> Self:
        self._client: InfluxDBClient = InfluxDBClient(url=self._url, token=self.__api_token, org=self._org)
        self._writer: WriteApi = self._client.write_api(write_options=WriteOptions(batch_size=1)) 
        self._writer.write(bucket=self._bucket, org=self._org, record=self._data)

        #bind the sink to the variable in the "as" part of the context manager.
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        self._writer.close()
        self._client.close()
        
        #delete these entirely so that the sink is detected as closed by 
        #any later calls to ``flush`` if it isn't reopened prior.
        del self._writer
        del self._client
       
        #signal to the context manager to propagate exceptions upwards.
        #we technically don't need to return this, as if we return None python
        #will interpreted it false-y (https://docs.python.org/3/library/stdtypes.html#truth-value-testing), 
        #but it's good to be explicit ;) 
        return False

    def open(self) -> None:
        """Wrapper around ``self.__enter__`` for use outside of a context manager."""
        self.__enter__()
    
    def close(self) -> None:
        """Wrapper around ``self.__exit__`` for use outside of a context manager."""
        self.__exit__()
    
    def flush(self, timestamp: int, packet: DataPacket) -> None:
        """Write data to InfluxDB.
        :meta private:
        """
        #with Profile() as prof:         
            #can't send data if no influx client/writer.
        if not hasattr(self, '_client') or not hasattr(self, '_writer'):
            raise RuntimeError('Must open sink before using.')

            #TODO: handle 8274D
            #TODO: handle 8401 preamp channel names
        #self._writer.write(bucket='pinnacle', org='pinnacle', record=self._line_protocol_factory(timestamp, packet))
        self._subject.on_next((timestamp, packet))
            #Stats(prof).strip_dirs().sort_stats('tottime').print_stats()
