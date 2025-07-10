"""Send data to QuestDB."""

__author__      = 'Josselyn Bui'
__maintainer__  = 'Josselyn Bui'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert', 'Andrew Huang', 'Josselyn Bui']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2025, Josselyn Bui'
__email__       = 'sales@pinnaclet.com'

import socket
import reactivex as rx
import reactivex.operators as ops
from typing import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import Pod8206HR, Pod8401HR, AcquisitionDevice
from Morelia.packet.data import DataPacket


class QuestSink(SinkInterface):
    """Stream data to QuestDB for real-time monitoring.

        :param host: Specifies the source of data. For local hosting use "localhost".
        :param port: Default QuestDB port is 9009 for ILP TCP service (InfluxDB Line Protocol).
        :param measurement: Measurement within QuestDB to write data to.
        :param pod: 8206-HR/8401-HR/8274D POD device you are streaming data from.
    """
    def __init__(self, pod: AcquisitionDevice, host: str = "localhost", port: int = "9009", measurement: str = "default_measurement") -> None:
        """Set instance variables"""
        self._host = host
        self._port = port
        self._measurement = measurement
        self._pod = pod

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
        else:
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
            ops.buffer_with_count(self._pod.sample_rate // 2),
            ops.map(lambda x: b'\n'.join(x))
        )

    def __enter__(self) -> Self:
        self._sock = socket.create_connection((self._host, self._port))
        self._data.subscribe(lambda data: self._sock.sendall(data + b'\n'))
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        self._sock.close()
        del self._sock
        return False

    def open(self) -> None:
        self.__enter__()

    def close(self) -> None:
        self.__exit__()

    def flush(self, timestamp: int, packet: DataPacket) -> None:
        if not hasattr(self, '_sock'):
            raise RuntimeError("Sink must be opened before flushing.")
        self._subject.on_next((timestamp, packet))
