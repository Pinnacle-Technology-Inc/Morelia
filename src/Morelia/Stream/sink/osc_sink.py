"""Stream OSC packets over UDP to a configurable host/port."""

__author__      = 'Sean Gupta'
__maintainer__  = ''
__credits__     = []
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2026'
__email__       = 'sales@pinnaclet.com'

import sys
from pythonosc.udp_client import SimpleUDPClient
try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import AcquisitionDevice, Pod8206HR, Pod8401HR, Pod8274D
from Morelia.packet.data import DataPacket

class OSCSink(SinkInterface):    
    """
    Streams acquisition data as Open Sound Control (OSC) messages over UDP.

    This sink converts packets produced by a supported acquisition device into
    OSC messages and transmits them to a configurable host and port using the
    python-osc library. The OSC address and message payload are determined by
    the connected device type.

    Supported devices:
        - Pod8206HR
        - Pod8401HR
        - Pod8274D

    Packet format:
        - Pod8206HR:
            /pod8206HR [timestamp, ch0, ch1, ch2]

        - Pod8401HR:
            /pod8401HR [timestamp, ch0, ch1, ch2, ch3]

        - Pod8274D:
            /pod8274D [timestamp, ch5..., ch6..., ch7...]

    The sink is intended for real-time streaming to applications that support
    OSC, such as Bonsai or other OSC-compatible software.
    """
    
    def __init__(
        self,
        port: int,
        pod: AcquisitionDevice,
        host: str = "127.0.0.1",
        observe_on_scheduler: str | None = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._pod = pod
        self.observe_on_scheduler = observe_on_scheduler

        self._client: SimpleUDPClient | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def __enter__(self) -> Self:
        self._client = SimpleUDPClient(self._host, self._port)
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        self._client = None
        return False

    def flush(self, timestamp: int, packet: DataPacket) -> None:
        if self._client is None:
            return

        try:
            if isinstance(self._pod, Pod8206HR):
                self._client.send_message(
                    "/pod8206HR",
                    [
                        int(timestamp),
                        float(packet.ch0),
                        float(packet.ch1),
                        float(packet.ch2),
                    ],
                )

            elif isinstance(self._pod, Pod8401HR):
                self._client.send_message(
                    "/pod8401HR",
                    [
                        int(timestamp),
                        float(packet.ch0),
                        float(packet.ch1),
                        float(packet.ch2),
                        float(packet.ch3),
                    ],
                )

            elif isinstance(self._pod, Pod8274D):
                self._client.send_message(
                    "/pod8274D",
                    [
                        int(timestamp),
                        *[float(x) for x in packet.ch5],
                        *[float(x) for x in packet.ch6],
                        *[float(x) for x in packet.ch7],
                    ],
                )

        except Exception as e:
            print(f"UDPSink flush error: {e}", file=sys.stderr)

    def get_dict(self) -> dict:
        return {
            'host': self._host,
            'port': self._port,
            'observe_on_scheduler': self.observe_on_scheduler,
        }
