"""Stream data to a PVFS (Pinnacle Virtual File System) file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import math
import sys
import time
from typing import Self

from Morelia.Stream.sink import SinkInterface
from Morelia.packet.data import DataPacket
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

try:
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile
    from pvfs_tools.Core.pvfs_binding import HighTime
    _PVFS_AVAILABLE = True
except (ImportError, RuntimeError):
    _PVFS_AVAILABLE = False
    PvfsDataFile = None  # type: ignore
    HighTime = None  # type: ignore


class PvfsSink(SinkInterface):
    """Stream data to a PVFS file compatible with Sirenia data format.

    Creates a PVFS file with experiment.db3 and indexed channel files (.index / .idat).
    Index timestamps are written in absolute time (seconds since epoch).
    Supports Pod8206HR (EEG1, EEG2, EEG3/EMG) and Pod8401HR (preamp channels only).

    :param file_path: Path to the .pvfs file to create.
    :param pod: POD device data is being streamed from.
    :param observe_on_scheduler: If set (e.g. "thread_pool"), run flush() on that scheduler so the stream is not blocked by PVFS I/O. Use with multi-sink flows to avoid slowing other sinks. Queue is unbounded; slow sinks can increase memory use.
    """

    def __init__(
        self,
        file_path: str,
        pod: AcquisitionDevice,
        observe_on_scheduler: str | None = None,
    ) -> None:
        if not _PVFS_AVAILABLE:
            raise RuntimeError(
                "pvfs_tools is not available, or the PVFS native library failed to load for this platform. "
                "Ensure pvfs_tools is installed and that you are on Windows or Linux with the correct binaries."
            )
        self._file_path = file_path
        self._pod = pod

        if isinstance(self._pod, Pod8206HR):
            self._channels = ('EEG1', 'EEG2', 'EEG3/EMG')
            self._units = ('uV', 'uV', 'uV')
        elif isinstance(self._pod, Pod8401HR):
            preamp_channel_names = (
                list(Pod8401HR.get_channel_map_for_preamp_device(self._pod.preamp).values())
                if self._pod.preamp is not None
                else ['A', 'B', 'C', 'D']
            )
            self._channels = tuple(preamp_channel_names)
            self._units = ('uV',) * len(preamp_channel_names)
        elif isinstance(self._pod, Pod8274D):
            self._channels = ('length_in_bytes', 'data')
            self._units = ('', '')
        else:
            raise ValueError(f'Device "{self._pod.device_name}" is not supported by PvfsSink.')

        self._buffer = [ [] for _ in self._channels ]
        self._pvfs_data: PvfsDataFile | None = None
        self._start_time: HighTime | None = None
        self._samples_written = 0
        self.observe_on_scheduler = observe_on_scheduler

    @property
    def pod(self) -> AcquisitionDevice:
        return self._pod

    @pod.setter
    def pod(self, device: AcquisitionDevice) -> None:
        self._pod = device

    @property
    def file_path(self) -> str:
        return self._file_path

    def __enter__(self) -> Self:
        self._pvfs_data = PvfsDataFile()
        ok = self._pvfs_data.create(self._file_path)
        if not ok:
            raise RuntimeError(f"PvfsDataFile.create failed for {self._file_path}")

        self._start_time = HighTime.from_seconds(time.time())
        self._pvfs_data.set_experiment_info(
            name="Morelia PVFS recording",
            description="Streamed data from Morelia data collection",
            start_time=self._start_time,
        )

        sample_rate = float(self._pod.sample_rate) if self._pod.sample_rate else 400.0
        for ch_name, unit in zip(self._channels, self._units):
            idf = self._pvfs_data.create_channel(
                ch_name, data_rate=sample_rate, unit=unit or "uV"
            )
            if idf is None:
                raise RuntimeError(f"Failed to create PVFS channel {ch_name}")
            idf._delta_time = HighTime(0, 1.0 / sample_rate)

        self._samples_written = 0
        return self

    def __exit__(self, *args, **kwargs) -> bool:
        # Flush any remaining buffered samples
        self._write_buffer_to_pvfs()

        if self._pvfs_data is not None:
            try:
                # Write closing timestamp (end-timestamp block) for each channel so
                # each indexed file has at least two index entries and correct end time
                for idf in self._pvfs_data._indexed_data_files.values():
                    if idf is not None:
                        idf.flush(synchronous=True)
                # Sync DB with channel times and save database into PVFS, then close
                self._pvfs_data.flush(synchronous=True)
                self._pvfs_data.close()
            except Exception as e:
                print(f"Warning: Error closing PVFS file: {type(e).__name__}: {e}", file=sys.stderr)
            finally:
                self._pvfs_data = None
        return False

    def flush(self, timestamp: int, packet: DataPacket) -> None:
        """Append one sample per channel to the buffer; write blocks when buffer reaches 1 second."""
        if self._pvfs_data is None:
            return

        sample_rate = float(self._pod.sample_rate) if self._pod.sample_rate else 400.0

        if isinstance(self._pod, Pod8206HR):
            ch0_val = float(packet.ch0)
            ch1_val = float(packet.ch1)
            ch2_val = float(packet.ch2)
            if math.isnan(ch0_val) or math.isinf(ch0_val):
                ch0_val = 0.0
            if math.isnan(ch1_val) or math.isinf(ch1_val):
                ch1_val = 0.0
            if math.isnan(ch2_val) or math.isinf(ch2_val):
                ch2_val = 0.0
            self._buffer[0].append(ch0_val)
            self._buffer[1].append(ch1_val)
            self._buffer[2].append(ch2_val)
        elif isinstance(self._pod, Pod8401HR):
            self._buffer[0].append(float(packet.ch0))
            self._buffer[1].append(float(packet.ch1))
            self._buffer[2].append(float(packet.ch2))
            self._buffer[3].append(float(packet.ch3))
        # Pod8274D not implemented for PVFS streaming

        if len(self._buffer[0]) >= int(sample_rate):
            self._write_buffer_to_pvfs()

    def _write_buffer_to_pvfs(self) -> None:
        if self._pvfs_data is None or self._start_time is None:
            return
        if not self._buffer or not self._buffer[0]:
            return

        lengths = [len(b) for b in self._buffer]
        if len(set(lengths)) != 1:
            print(
                f"Warning: PvfsSink skipping write due to mismatched buffer lengths: {lengths}",
                file=sys.stderr,
            )
            self._buffer = [ [] for _ in self._channels ]
            return

        sample_rate = float(self._pod.sample_rate) if self._pod.sample_rate else 400.0
        n = lengths[0]
        block_start = HighTime.from_seconds(
            self._start_time.to_seconds() + self._samples_written / sample_rate
        )

        for ch_name, buf in zip(self._channels, self._buffer):
            idf = self._pvfs_data._indexed_data_files.get(ch_name)
            if idf is None:
                continue
            values = [float(x) for x in buf]
            result = idf.append_block(block_start, values)
            if result != 0:
                print(
                    f"Warning: PvfsSink append_block({ch_name}) returned {result}",
                    file=sys.stderr,
                )

        self._samples_written += n
        self._buffer = [ [] for _ in self._channels ]

    def get_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "observe_on_scheduler": self.observe_on_scheduler,
        }
