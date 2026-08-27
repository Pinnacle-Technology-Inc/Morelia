"""Send data to CSV file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert', 'Sean Gupta']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.Devices import AcquisitionDevice, Pod8274D, Pod8206HR, Pod8401HR
from Morelia.packet.data import DataPacket

class BufferSink(SinkInterface):
    """Stream data to a buffer.

    When using a multiprocessing Manager list, set batch_size > 1 to append samples in chunks
    and reduce IPC (one extend per batch instead of one append per sample).

    :param buffer: Target list to append (timestamp, data) rows to; supports list and manager.list().
    :param pod: POD device data is being streamed from.
    :param batch_size: Flush to buffer every this many samples (default 100). Use 1 for no batching.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """

    def __init__(self, buffer, pod: AcquisitionDevice, batch_size: int = 100) -> None:
        """Class constructor."""
        self._pod = pod
        self._buffer = buffer
        self._batch_size = max(1, int(batch_size))
        self._batch: list = []

    @property
    def buffer(self):
        return self._buffer

    def __enter__(self) -> Self:
        self._batch = []
        if isinstance(self._pod, Pod8206HR):
            self._buffer.append(('Time', 'EEG1', 'EEG2', 'EEG3/EMG'))

        elif isinstance(self._pod, Pod8401HR):
            preamp_channel_names: list[str] = Pod8401HR.get_channel_map_for_preamp_device(self._pod.preamp).values() if not self._pod.preamp is None else ['A', 'B', 'C', 'D']

            self._buffer.append(('Time',) + tuple(preamp_channel_names) + ('aEXT0', 'aEXT1', 'aTTL1', 'aTTL2', 'aTTL3', 'aTTL4'))

        elif isinstance(self._pod, Pod8274D):
            self._buffer.append(('Time', 'Ch5 Batch', 'Ch6 Batch', 'Ch7 Batch'))

        else:
            raise ValueError(f'Device "{self._pod.device_name}" cannot be streamed from!')
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        if self._batch:
            self._buffer.extend(self._batch)
            self._batch = []
        return False

    def _flush_batch_if_full(self) -> None:
        """Push batch to shared buffer when it reaches batch_size (reduces IPC for manager.list())."""
        if len(self._batch) >= self._batch_size:
            self._buffer.extend(self._batch)
            self._batch.clear()

    #TODO: check that sink is open
    def flush(self, timestamp: int, packet: DataPacket) -> None:

        if isinstance(self._pod, Pod8206HR):
            row = (timestamp, (packet.ch0, packet.ch1, packet.ch2, packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4))
        elif isinstance(self._pod, Pod8401HR):
            channel_data = (packet.ch0, packet.ch1, packet.ch2, packet.ch3)
            aext_data = (packet.ext0, packet.ext1)
            attl_data = (packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4)
            row = (timestamp, (channel_data + aext_data + attl_data))
        elif isinstance(self._pod, Pod8274D):
            row = (timestamp, (packet.ch5, packet.ch6, packet.ch7))
        else:
            return

        self._batch.append(row)
        self._flush_batch_if_full()
    
    def get_dict(self):
        return {
            'buffer': self.buffer,
            'batch_size': self._batch_size,
        }