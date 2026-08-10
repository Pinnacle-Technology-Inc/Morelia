"""Send data to EDF file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert', 'Sean Gupta']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

from pyedflib import EdfWriter
try:
    from typing import Self
except ImportError:
    from typing_extensions import Self
import numpy as np
import functools as ft
import os

from Morelia.Stream.sink import SinkInterface
from Morelia.packet.data import DataPacket
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

from Morelia.ParamSchema.ParamSchema import ParamSchema

class EDFSink(SinkInterface):
    """Stream data to an EDF file.

    :param sample_rate: Sample rate of device being streamed from. Used in setting up EDF file.
    :param file_path: Path to CSV file to write to.
    :param pod: POD device data is being streamed from.
    :param observe_on_scheduler: If set (e.g. "thread_pool"), run flush() on that scheduler so the stream is not blocked by EDF I/O. Optional; queue is unbounded.
    """

    def __init__(self, file_path: str, pod: AcquisitionDevice, observe_on_scheduler: str | None = None) -> None:
        """ Class constructor."""
        self._file_path = file_path
        self._pod = pod
        self.observe_on_scheduler = observe_on_scheduler

        if isinstance(self._pod, Pod8206HR):
                self._channels = ('EEG1', 'EEG2', 'EEG3/EMG', 'TTL1', 'TTl2', 'TTL3', 'TTl4')

        elif isinstance(self._pod, Pod8401HR):

            preamp_channel_names: list[str] = Pod8401HR.get_channel_map_for_preamp_device(self._pod.preamp).values() if not self._pod.preamp is None else ['A', 'B', 'C', 'D']

            self._channels = tuple(preamp_channel_names) + ('EXT0', 'EXT1', 'TTL1', 'TTL2', 'TTL3', 'TTL4')

        elif isinstance(self._pod, Pod8274D):
                self._channels = ('Ch5', 'Ch6', 'Ch7')

        self._buffer = [ [] for _ in self._channels ]

    @property 
    def pod(self):
        return self._pod
    
    @pod.setter
    def pod(self, device: AcquisitionDevice):
        self._pod = value
    
    @property
    def file_path(self):
        return self._file_path

    def __enter__(self) -> Self:

        EDF_PHYSICAL_BOUND = 2046
        EDF_DIGITAL_MAX = 32767
        EDF_DIGITAL_MIN = -32768

        # Delete existing file if it exists to allow overwrite
        # EdfWriter may not handle existing files correctly, so we must delete first
        # Retry deletion in case file is locked (e.g., from previous run that didn't close properly)
        if os.path.exists(self._file_path):
            import time
            import sys
            max_retries = 10
            retry_delay = 0.1  # 100ms
            deleted = False
            for attempt in range(max_retries):
                try:
                    os.remove(self._file_path)
                    # Small delay to ensure filesystem has processed the deletion
                    time.sleep(0.05)
                    if not os.path.exists(self._file_path):
                        deleted = True
                        break
                except OSError as e:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        # Last attempt failed - log warning
                        print(f"Warning: Could not delete existing EDF file '{self._file_path}': {e}. "
                              f"File may be locked. Attempting to create writer anyway.", file=sys.stderr)
            
            # Final check - if file still exists, warn but continue
            if os.path.exists(self._file_path):
                import sys
                print(f"Warning: EDF file '{self._file_path}' still exists after deletion attempts. "
                      f"This may cause write errors. Please close any programs using this file.", file=sys.stderr)

        self._edf_writer = EdfWriter(self._file_path, len(self._channels))

        for idx, channel in enumerate(self._channels):
           self._edf_writer.setSignalHeader( idx, {
                'label'         :  channel,
                'dimension'     :  'uV',
                'sample_frequency'   :  self._pod.sample_rate,
                'physical_max'  :  EDF_PHYSICAL_BOUND,
                'physical_min'  : -EDF_PHYSICAL_BOUND,
                'digital_max'   :  EDF_DIGITAL_MAX,
                'digital_min'   :  EDF_DIGITAL_MIN,
                'transducer'    :  '',
                'prefilter'     :  ''
            } )

        return self

    def __exit__(self, *args, **kwargs) -> bool:

        self._write_buffer_to_edf()

        # Ensure file is properly closed
        if hasattr(self, '_edf_writer') and self._edf_writer is not None:
            try:
                self._edf_writer.close()
            except Exception as e:
                import sys
                print(f"Warning: Error closing EDF file: {type(e).__name__}: {e}", file=sys.stderr)
            finally:
                self._edf_writer = None

        return False


    #we have a "useless" timestamp paramater here so we implement the same function "interface".
    #TODO: check if sink is open
    def flush(self, timestamp: int, packet: DataPacket) -> None:
        """
        :meta private:
        """
        
        if isinstance(self._pod, Pod8206HR):
            try:
                # Validate channel values before appending
                ch0_val = float(packet.ch0) if not (np.isnan(packet.ch0) or np.isinf(packet.ch0)) else 0.0
                ch1_val = float(packet.ch1) if not (np.isnan(packet.ch1) or np.isinf(packet.ch1)) else 0.0
                ch2_val = float(packet.ch2) if not (np.isnan(packet.ch2) or np.isinf(packet.ch2)) else 0.0
                
                self._buffer[0].append(ch0_val)
                self._buffer[1].append(ch1_val)
                self._buffer[2].append(ch2_val)
                self._buffer[3].append(float(packet.ttl1))
                self._buffer[4].append(float(packet.ttl2))
                self._buffer[5].append(float(packet.ttl3))
                self._buffer[6].append(float(packet.ttl4))
            except (AttributeError, ValueError, TypeError) as e:
                # Skip this packet if it has invalid attributes or values
                import sys
                print(f"Warning: Skipping packet due to invalid data: {type(e).__name__}: {e}", file=sys.stderr)
                return

        elif isinstance(self._pod, Pod8401HR):
            self._buffer[0].append(packet.ch0)
            self._buffer[1].append(packet.ch1)
            self._buffer[2].append(packet.ch2)
            self._buffer[3].append(packet.ch3)
            self._buffer[4].append(float(packet.ext0))
            self._buffer[5].append(float(packet.ext1))
            self._buffer[6].append(float(packet.ttl1))
            self._buffer[7].append(float(packet.ttl2))
            self._buffer[8].append(float(packet.ttl3))
            self._buffer[9].append(float(packet.ttl4))

        elif isinstance(self._pod, Pod8274D):
            for (ch5, ch6, ch7) in zip(packet.ch5, packet.ch6, packet.ch7):
                self._buffer[0].append(ch5)
                self._buffer[1].append(ch6)
                self._buffer[2].append(ch7)

        if len(self._buffer[0]) >= self._pod.sample_rate:
            self._write_buffer_to_edf()

    def _write_buffer_to_edf(self) -> None:
        # Validate buffer before writing
        if not self._buffer or len(self._buffer) == 0:
            print("returned, nothing to write")
            return

        # Check that all buffers have the same length
        buffer_lengths = [len(b) for b in self._buffer]
        if not buffer_lengths or len(set(buffer_lengths)) != 1:
            import sys
            print(
                f"Warning: Skipping EDF write due to mismatched buffer lengths: {buffer_lengths}",
                file=sys.stderr
            )
            self._buffer = [[] for _ in self._channels]
            return

        # Validate data
        try:
            for buf in self._buffer:
                arr = np.array(buf, dtype=np.float64)

                if np.any(np.isnan(arr)) or np.any(np.isinf(arr)):
                    import sys
                    print(
                        "Warning: Skipping EDF write due to NaN/inf values in buffer",
                        file=sys.stderr
                    )
                    self._buffer = [[] for _ in self._channels]
                    return

            samples_per_record = self._pod.sample_rate

            # Write complete EDF records only
            while len(self._buffer[0]) >= samples_per_record:

                arrays = [
                    np.array(
                        buf[:samples_per_record],
                        dtype=np.float64
                    )
                    for buf in self._buffer
                ]

                self._edf_writer.writeSamples(arrays)

                # Remove written samples and keep overflow
                for i in range(len(self._buffer)):
                    self._buffer[i] = self._buffer[i][samples_per_record:]

        except OSError as e:
            import sys
            print(
                f"Warning: EDF write error (dropping buffer): {type(e).__name__}: {e}",
                file=sys.stderr
            )

        except Exception as e:
            import sys
            print(
                f"Warning: Unexpected error writing to EDF (dropping buffer): {type(e).__name__}: {e}",
                file=sys.stderr
            )

    def get_dict(self):
        return {
            'file_path': self.file_path,
            'observe_on_scheduler': self.observe_on_scheduler,
        }

    @property
    def param_schema(self) -> ParamSchema:
        return ParamSchema(
            required=frozenset(),
            optional=frozenset({"file_path", "observe_on_scheduler"}),
            validators={"observe_on_scheduler": self._check_observe_on_scheduler},
        )
