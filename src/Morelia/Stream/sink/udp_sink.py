"""Stream data over UDP to a configurable host/port."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import socket
import struct
import sys
from typing import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import AcquisitionDevice, Pod8206HR, Pod8401HR, Pod8274D
from Morelia.packet.data import DataPacket


class UDPSink(SinkInterface):
    """Stream data over UDP to a destination host/port.

    Send-only UDP sink: one datagram per sample. Payload is a simple binary format
    (little-endian): 8-byte timestamp (nanoseconds) followed by channel floats.
    Works on Windows, WSL, and Linux.

    :param port: Destination port (required).
    :param pod: POD device data is being streamed from.
    :param host: Destination host (default 127.0.0.1 for local use).
    :param observe_on_scheduler: If set (e.g. "thread_pool"), run flush() on that scheduler. Optional; queue is unbounded.
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
        self._socket: socket.socket | None = None
        self.observe_on_scheduler = observe_on_scheduler

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def __enter__(self) -> Self:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(('', 0))
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        return False

    def flush(self, timestamp: int, packet: DataPacket) -> None:
        if self._socket is None:
            return
        try:
            payload = self._pack_payload(timestamp, packet)
            if payload is not None:
                self._socket.sendto(payload, (self._host, self._port))
        except OSError as e:
            print(f"UDPSink sendto failed: {e}", file=sys.stderr)
        except Exception as e:
            print(f"UDPSink flush error: {e}", file=sys.stderr)

    def _pack_payload(self, timestamp: int, packet: DataPacket) -> bytes | None:
        """Pack (timestamp, packet) into little-endian bytes. One datagram per sample."""
        if isinstance(self._pod, Pod8206HR):
            return struct.pack(
                '<Qfff',
                timestamp,
                float(packet.ch0),
                float(packet.ch1),
                float(packet.ch2),
            )
        if isinstance(self._pod, Pod8401HR):
            return struct.pack(
                '<Qffff',
                timestamp,
                float(packet.ch0),
                float(packet.ch1),
                float(packet.ch2),
                float(packet.ch3),
            )
        # Pod8274D: TODO if needed
        return None

    def get_dict(self) -> dict:
        return {
            'host': self._host,
            'port': self._port,
            'observe_on_scheduler': self.observe_on_scheduler,
        }
