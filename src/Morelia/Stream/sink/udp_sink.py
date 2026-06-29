"""Stream data over UDP to a configurable host/port."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert', 'Sean Gupta']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import socket
import struct
import sys
try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import AcquisitionDevice, Pod8206HR, Pod8401HR, Pod8274D
from Morelia.packet.data import DataPacket


class UDPSink(SinkInterface):    
    """Stream data over UDP to a destination host/port.

    Send-only UDP sink: one datagram per sample (or per batch for batch-capable
    devices). Payload is a simple binary format (little-endian):

    - Pod8206HR: 8-byte timestamp followed by 3 channel floats
    - Pod8401HR: 8-byte timestamp followed by 4 channel floats
    - Pod8274D: 8-byte timestamp + 16-bit sample count + batch of 40, 3 channel floats

    Works on Windows, WSL, and Linux.

    PACKET FORMATS:
    Pod8206HR:
        <Qfff>
        - Q: uint64 timestamp (8 bytes)
        - fff: 3 float32 channel values
        Total: 20 bytes

    Pod8401HR:
        <Qffff>
        - Q: uint64 timestamp (8 bytes)
        - ffff: 4 float32 channel values
        Total: 24 bytes

    Pod8274D (batch of 40 samples, 3 channels per sample):
        <QH + N × (fff)>
        - Q: uint64 timestamp (8 bytes)
        - H: uint16 sample count (40)
        - fff: 3 float32 channel values per sample (channels 5–7)
        Total: 490 bytes

        Each batch is formed by zipping channel lists:
            (ch5[i], ch6[i], ch7[i]) for i in range(N)

    BEHAVIOR:
    - One UDP datagram is emitted per flush().
    - UDP is connectionless and does not guarantee delivery or ordering.
    - No retransmission or buffering is performed.
    - Intended for low-latency streaming of acquisition data.

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
        elif isinstance(self._pod, Pod8274D):
            header = struct.pack("<QH", timestamp, len(packet.ch5))

            body = b"".join(
                struct.pack("<fff", ch5, ch6, ch7)
                for (ch5, ch6, ch7) in zip(packet.ch5, packet.ch6, packet.ch7)
            )

            return header + body
        
        return None

    def get_dict(self) -> dict:
        return {
            'host': self._host,
            'port': self._port,
            'observe_on_scheduler': self.observe_on_scheduler,
        }
