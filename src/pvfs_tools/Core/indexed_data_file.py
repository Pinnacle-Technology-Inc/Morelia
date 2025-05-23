from dataclasses import dataclass
from typing import List, Optional, Tuple
import ctypes
from pathlib import Path
import math, struct
from typing import List, Optional, Tuple

from .pvfs_binding import PvfsFile, HighTime, PvfsFileHandle, PvfsFileHandleWrapper
from .CRC32 import CRC32

class PvfsError(Exception):
    """Exception raised for PVFS-related errors."""
    def __init__(self, error_code: int):
        self.error_code = error_code
        super().__init__(f"PVFS error: {error_code}")

@dataclass
class IndexedHeader:
    """Header structure for indexed data files."""
    magic_number: int = 0xFF01FF01
    version: int = 1
    data_type: int = 0
    data_rate: float = 1.0
    start_time: Optional[HighTime] = None
    end_time: Optional[HighTime] = None
    timestamp_interval_seconds: int = 10
    
    def __post_init__(self):
        """Initialize HighTime objects if they are None."""
        if self.start_time is None:
            self.start_time = HighTime(0, 0.0)
        if self.end_time is None:
            self.end_time = HighTime(0, 0.0)

@dataclass
class IndexEntry:
    """Structure for index entries in the index file."""
    start_time: HighTime
    end_time: HighTime
    my_location: int
    data_location: int

class IndexedDataFile:
    """Python implementation of PVFS_IndexedDataFile.
    
    This class provides access to indexed data files within a PVFS virtual file system.
    It handles reading and writing of data with timestamps, similar to the C++ implementation
    but without the caching functionality.
    """
    
    # Constants from C++ implementation
    INDEXED_DATA_FILE_MAGIC_NUMBER = 0xFF01FF01
    INDEXED_DATA_FILE_VERSION = 1
    INDEX_EXTENSION = ".index"
    DATA_EXTENSION = ".idat"
    INDEX_HEADER_SIZE = 1000
    TIMESTAMP_SIZE = 44  # Size of timestamp entry in bytes
    DATA_CHUNK_HEADER_SIZE = 36  # Size of data chunk header
    DATA_CHUNK_HEADER_SIZE_BEFORE_DATA = 32  # Bytes before data section
    UNIQUE_MARKER_BYTE = 0xA5

    def __init__(self, pvfs_file: PvfsFile, filename: str, seconds: int = 10, 
                 create: bool = False, async_cache: bool = False,
                 overwrite: bool = False):
        """Initialize the indexed data file.
        
        Args:
            pvfs_file: The PVFS file instance
            filename: Name of the file to open/create
            seconds: Time interval between timestamps
            create: Whether to create a new file
            async_cache: Whether to use async caching (not used in Python implementation)
            overwrite: Whether to overwrite existing file
        """
        self._pvfs_file = pvfs_file
        self._filename = filename
        self._channel_name = filename
        self._header = IndexedHeader()
        self._header.timestamp_interval_seconds = seconds
        
        self._index_file = None
        self._data_file = None
        
        # Data file position tracking
        self._data_file_index = 0
        
        # Index entries
        self._indices = []
        self._current_index = 0
        
        # Time tracking
        self._zero_time = HighTime(0, 0.0)
        self._start_time_set = False
        self._previous_timestamp = HighTime(-1.0)
        self._next_timestamp = HighTime(-1.0)
        self._delta_time = HighTime(1.0)
        self._max_delta = HighTime(2.0)
        
        # Data rate
        self._data_rate = 1.0
        
        if create:
            self.create(pvfs_file, filename, overwrite)
        
        self.open(pvfs_file, filename, async_cache, overwrite)

    def create(self, pvfs_file: PvfsFile, filename: str, overwrite: bool) -> bool:
        """Create a new indexed data file.
        
        Args:
            pvfs_file: PVFS file instance
            filename: Base filename without extension
            async_cache: Whether to use async caching (not used in Python implementation)
            overwrite: Whether to overwrite existing files
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Check if files already exist
        index_name = filename + self.INDEX_EXTENSION
        data_name = filename + self.DATA_EXTENSION
        
        # Try to open the files to check if they exist
        try:
            file_handle = pvfs_file.open_file(filename)
            if file_handle and not overwrite:
                return False
        except:
            pass
            
        # Create the files
        self._index_file = pvfs_file.create_file(index_name)
        self._data_file = pvfs_file.create_file(data_name)
        
        if not self._index_file or not self._data_file:
            return False
            
        # Initialize header
        self._header = IndexedHeader()
        self._header.magic_number = self.INDEXED_DATA_FILE_MAGIC_NUMBER
        self._header.version = 1
        self._header.data_type = 0
        self._header.data_rate = 0.0
        self._header.start_time = HighTime(0, 0.0)
        self._header.end_time = HighTime(0, 0.0)
        self._header.timestamp_interval_seconds = 10
        
        # Write header
        return self.write_header(self._header)

    def open(self, pvfs_file: PvfsFile, filename: str, async_cache: bool = True,
             overwrite: bool = False) -> bool:
        """Open an existing indexed data file.
        
        Args:
            pvfs_file: PVFS file instance
            filename: Base filename without extension
            async_cache: Whether to use async caching (not used in Python implementation)
            overwrite: Whether to overwrite existing files
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Construct filenames
        index_name = filename + self.INDEX_EXTENSION
        data_name = filename + self.DATA_EXTENSION
        
        # Lock the VFS during file operations
        pvfs_file.lock()
        try:
            # Open the index file
            self._index_file = pvfs_file.open_file(index_name)
            if not self._index_file:
                return False
                
            # Open the data file
            self._data_file = pvfs_file.open_file(data_name)
            if not self._data_file:
                return False
                
            # Read header and indices
            self._header = IndexedHeader()
            if not self.read_header():
                return False
                
            self._read_all_indices()
            return True
        finally:
            pvfs_file.unlock()

    def close(self):
        """Close the indexed data file."""
        if self._index_file:
            self._index_file.close()
            self._index_file = None
            
        if self._data_file:
            self._data_file.close()
            self._data_file = None

    def write_header(self, lock: bool = True) -> bool:
        """Write the header information to the file.
        
        Args:
            lock: Whether to lock the file during write
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.write_header_data(self._header, lock)

    def write_header_data(self, header: IndexedHeader, lock: bool = True) -> bool:
        """Write header data to the file.
        
        Args:
            header: Header data to write
            lock: Whether to lock the file during write
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._index_file:
            return False
            
        if lock:
            self._pvfs_file.lock()
            
        try:
            self._index_file.seek(0)
            self._index_file.fwrite_uint32(header.magic_number)
            self._index_file.fwrite_uint32(header.version)
            self._index_file.fwrite_uint32(header.data_type)
            self._index_file.fwrite_float(header.data_rate)
            self._index_file.fwrite_int64(header.start_time.seconds)
            self._index_file.fwrite_double(header.start_time.subseconds)
            self._index_file.fwrite_int64(header.end_time.seconds)
            self._index_file.fwrite_double(header.end_time.subseconds)
            self._index_file.fwrite_uint32(header.timestamp_interval_seconds)
            self._index_file.flush()
            return True
        finally:
            if lock:
                self._pvfs_file.unlock()

    def read_header(self) -> bool:
        """Read the header information from the file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        return self.read_header_data()

    def read_header_data(self) -> bool:
        """Read the header data from the index file."""
        if not self._index_file:
            return False
            
        try:
            # Read magic number
            magic_number = self._index_file.fread_uint32()
            if magic_number != 0xFF01FF01:
                print(f"Invalid magic number: {magic_number}")
                return False
                
            # Read version
            version = self._index_file.fread_uint32()
            if version != 1:
                print(f"Unsupported version: {version}")
                return False
                
            # Read data type
            data_type = self._index_file.fread_uint32()
            
            # Read data rate
            data_rate = self._index_file.fread_float()
            
            # Read start time
            start_seconds = self._index_file.fread_int64()
            start_subseconds = self._index_file.fread_double()
            start_time = HighTime(start_seconds, start_subseconds)
            
            # Read end time
            end_seconds = self._index_file.fread_int64()
            end_subseconds = self._index_file.fread_double()
            end_time = HighTime(end_seconds, end_subseconds)
            
            # Read timestamp interval
            timestamp_interval = self._index_file.fread_uint32()
            
            # Update header with new values
            self._header.magic_number = magic_number
            self._header.version = version
            self._header.data_type = data_type
            self._header.data_rate = data_rate
            self._header.start_time = start_time
            self._header.end_time = end_time
            self._header.timestamp_interval_seconds = timestamp_interval
            
            return True
            
        except Exception as e:
            print(f"Error reading header: {e}")
            return False

    def _read_all_indices(self):
        """Read all index entries from the index file."""
        self._indices.clear()
        self._current_index = 0
        
        if not self._index_file:
            return
            
        # Calculate number of indices
        info = self._index_file.get_file_info()
        file_size = info.size
        n = (file_size - self.INDEX_HEADER_SIZE) // self.TIMESTAMP_SIZE
        
        read_location = self.INDEX_HEADER_SIZE
        last_read_location = read_location
        last_data_location = 0
        last_time = None
        count = 0
        
        for i in range(n):
            # Read timestamp and data location
            timestamp, data_location = self._read_timestamp(read_location)
            
            if timestamp is not None:
                count += 1
                if count > 1 and last_time is not None:
                    # Create index entry
                    entry = IndexEntry(
                        start_time=last_time,
                        end_time=timestamp,
                        my_location=last_read_location,
                        data_location=last_data_location
                    )
                    self._indices.append(entry)
                
                last_time = timestamp
                last_read_location = read_location
                last_data_location = data_location
            
            read_location += self.TIMESTAMP_SIZE
        
        # Add the last entry if we have at least one
        if count > 1 and last_time is not None:
            entry = IndexEntry(
                start_time=last_time,
                end_time=self._header.end_time,
                my_location=last_read_location,
                data_location=last_data_location
            )
            self._indices.append(entry)


    def _read_timestamp(self, location: int) -> Tuple[Optional[HighTime], int]:
        """Read a timestamp from the specified location, with CRC verification.
        
        Args:
            location: File position to read from
            
        Returns:
            Tuple[Optional[HighTime], int]: The timestamp and data location, or (None, -1) if error
        """
        if not self._index_file:
            return None, -1
            
        try:
            self._index_file.seek(location)

            # Check marker bytes
            for _ in range(8):
                marker = self._index_file.fread_uint8()
                if marker != self.UNIQUE_MARKER_BYTE:
                    return None, -1

            # Typed reads
            seconds = self._index_file.fread_int64()
            subseconds = self._index_file.fread_double()
            reserved = self._index_file.fread_int64()
            data_location = self._index_file.fread_int64()
            crc_stored = self._index_file.fread_uint32()

            # Reconstruct bytes for CRC calculation
            seconds_bytes = struct.pack('<q', seconds)            # int64_t -> 8 bytes
            subseconds_bytes = struct.pack('<d', subseconds)      # double -> 8 bytes
            reserved_bytes = struct.pack('<q', reserved)          # int64_t -> 8 bytes
            data_location_bytes = struct.pack('<q', data_location)# int64_t -> 8 bytes

            crc_input = seconds_bytes + subseconds_bytes + reserved_bytes + data_location_bytes
            crc_calculated = CRC32.calculate_crc32(crc_input)

            if crc_calculated != crc_stored:
                print(f"CRC mismatch at location {location}: expected {hex(crc_stored)}, got {hex(crc_calculated)}")
#                return None, -1

            return HighTime(seconds, subseconds), data_location

        except Exception as e:
            print(f"Error reading timestamp: {e}")
        return None, -1


    def _write_timestamp(self, time: HighTime) -> int:
        """Write a timestamp to the file.
        
        Args:
            time: The timestamp to write
            
        Returns:
            int: The location where the timestamp was written, or -1 if error
        """
        if not self._index_file:
            return -1
            
        try:
            location = self._index_file.tell()
            for i in range(8):
                self._index_file.fwrite_uint8(self.UNIQUE_MARKER_BYTE)
            self._index_file.fwrite_int64(time.seconds)
            self._index_file.fwrite_double(time.subseconds)
            self._index_file.fwrite_int64(self._data_file.tell())
            self._index_file.flush()
            return location
        except Exception as e:
            print(f"Error writing timestamp: {e}")
            return -1

    def _write_data(self, data: bytes, do_crc: bool = False) -> int:
        """Write data to the file.
        
        Args:
            data: The data to write
            do_crc: Whether to calculate CRC (not implemented)
            
        Returns:
            int: The location where the data was written, or -1 if error
        """
        if not self._data_file:
            return -1
            
        try:
            location = self._data_file.tell()
            self._data_file.fwrite_uint8(self.UNIQUE_MARKER_BYTE)
            self._data_file.fwrite_uint32(len(data))
            self._data_file.write(data, len(data))
            self._data_file.flush()
            return location
        except Exception as e:
            print(f"Error writing data: {e}")
            return -1

    def _write_timestamp_and_data(self, time: HighTime, value: float) -> int:
        """Write a timestamp and data value.
        
        Args:
            time: Timestamp
            value: Data value
            
        Returns:
            int: 0 on success, -1 on failure
        """
        # Write timestamp to index file
        index_pos = self._write_timestamp(time)
        if index_pos < 0:
            return -1
            
        # Write data to data file
        data_bytes = struct.pack('f', value)
        return self._write_data(data_bytes, True)


    def get_data(self,
                start_time: HighTime,
                end_time: HighTime,
                max_points: int = -1
                ) -> Tuple[List[HighTime], List[float]]:
        import math, struct

        BYTES_PER_FLOAT = 4
        CHUNK_SAMPS = 10000
        TIMESTAMP_MARKER = b"\xA5" * 8
        TIMESTAMP_STRUCT = struct.Struct('<q d q q I')  # secs:int64, sub:double, reserved:int64, idx:int64, CRC:uint32
        MARKER_SIZE = len(TIMESTAMP_MARKER)             # 8
        HEADER_SIZE = MARKER_SIZE + TIMESTAMP_STRUCT.size  # 8 + 36 = 44 bytes

        timestamps: List[HighTime] = []
        values_out: List[float] = []
        if not self._index_file or not self._data_file:
            return timestamps, values_out

        # convert times to float seconds
        start_f = start_time.seconds + start_time.subseconds
        end_f   = end_time.seconds   + end_time.subseconds
        if end_f <= start_f:
            return timestamps, values_out

        sample_rate = self.get_data_rate()
        if sample_rate <= 0:
            return timestamps, values_out

        # find first block covering start_f
        first_entry = next(
            (e for e in self._indices
            if (e.end_time.seconds + e.end_time.subseconds) >= start_f),
            None
        )
        if first_entry is None:
            return timestamps, values_out

        entry_start_f = first_entry.start_time.seconds + first_entry.start_time.subseconds
        needed_samps = math.ceil((end_f - entry_start_f) * sample_rate)

        all_raw: List[float] = []
        markers:    List[Tuple[int, float]] = []
        raw_buffer = b''
        crc_calculator = CRC32()  # Create CRC32 instance for accumulating CRC

        # preserve up to (HEADER_SIZE-1) bytes to catch split headers
        preserve = HEADER_SIZE - 1

        self._data_file.seek(first_entry.data_location)
        self._pvfs_file.lock()
        try:
            while len(all_raw) < needed_samps:
                data = self._data_file.read(CHUNK_SAMPS * BYTES_PER_FLOAT)
                if not data:
                    break
                raw_buffer += data
                ptr = 0

                # scan for full 8-byte markers at 4-byte alignment
                while True:
                    idx = raw_buffer.find(TIMESTAMP_MARKER, ptr)
                    if idx < 0:
                        # No marker found, accumulate CRC only for the new data
                        # Only add data from current read that hasn't been processed
                        new_data = raw_buffer[ptr:ptr + len(data)]
                        crc_calculator.append_bytes(new_data)
                        break
                    # require marker to align on float boundary
                    if idx % BYTES_PER_FLOAT != 0:
                        # Accumulate CRC only up to the misaligned marker
                        crc_calculator.append_bytes(raw_buffer[ptr:idx])
                        ptr = idx + 1
                        continue
                    # need full header in buffer
                    if len(raw_buffer) < idx + HEADER_SIZE:
                        # Accumulate CRC only for the new data
                        new_data = raw_buffer[ptr:ptr + len(data)]
                        crc_calculator.append_bytes(new_data)
                        break

                    # Process data segment between markers
                    n_pre = (idx - ptr - 4) // BYTES_PER_FLOAT  # 4 bytes before timestamp is the CRC
                    if n_pre > 0:
                        end_off = ptr + n_pre * BYTES_PER_FLOAT
                        # Read stored CRC first
                        crc_stored = struct.unpack('<I', raw_buffer[end_off:end_off + 4])[0]
                        
                        # Accumulate CRC for data up to CRC bytes (excluding the CRC bytes themselves)
                        crc_calculator.append_bytes(raw_buffer[ptr:end_off])
                        
                        # Get calculated CRC and compare
                        crc_calculated = crc_calculator.get_crc()
                        print(f"Data segment CRC at location {ptr}: expected {hex(crc_stored)}, got {hex(crc_calculated)}")
                        
                        if crc_calculated != crc_stored:
                            print(f"Data segment CRC mismatch at location {ptr}: expected {hex(crc_stored)}, got {hex(crc_calculated)}")
                            # Continue processing but log the error
                        
                        # Reset CRC calculator for next segment
                        crc_calculator.reset()
                        
                        # Unpack and add the values
                        vals = struct.unpack(f'<{n_pre}f', raw_buffer[ptr:end_off])
                        all_raw.extend(vals)

                    # read timestamp struct (ignoring CRC)
                    hdr_off = idx + MARKER_SIZE
                    sec, sub, _, _, _ = TIMESTAMP_STRUCT.unpack(
                        raw_buffer[hdr_off:hdr_off + TIMESTAMP_STRUCT.size]
                    )
                    markers.append((len(all_raw), sec + sub))

                    # advance past header
                    ptr = idx + HEADER_SIZE

                # unpack any floats after last header, but leave up to 'preserve' bytes
                tail_bytes = len(raw_buffer) - ptr
                to_consume = tail_bytes - preserve
                if to_consume > 0:
                    n_tail = to_consume // BYTES_PER_FLOAT
                    if n_tail > 0:
                        start_off = ptr
                        end_off = ptr + n_tail * BYTES_PER_FLOAT
                        # Add any remaining data to CRC before unpacking
                        crc_calculator.append_bytes(raw_buffer[start_off:end_off])
                        vals = struct.unpack(f'<{n_tail}f', raw_buffer[start_off:end_off])
                        all_raw.extend(vals)
                        ptr = end_off

                # drop processed bytes, keep the last 'preserve' bytes
                raw_buffer = raw_buffer[ptr:]
        finally:
            self._pvfs_file.unlock()

        timestamps.clear()
        values_out.clear()

        # Segment-based interpolation
        if len(markers) >= 2:
            dt_tolerance = 0.01  # 1% deviation allowed

            # Precompute and validate per-segment dt
            for (i0, t0), (i1, t1) in zip(markers[:-1], markers[1:]):
                if i1 <= i0:
                    continue  # skip bad segment
                segment_dt = (t1 - t0) / (i1 - i0)
                expected_dt = 1.0 / sample_rate
                if abs(segment_dt - expected_dt) / expected_dt > dt_tolerance:
                    segment_dt = expected_dt

                for i in range(i0, i1):
                    if i >= len(all_raw):
                        break  # sanity check
                    t = t0 + (i - i0) * segment_dt
                    if t < start_f:
                        continue
                    if t > end_f:
                        break
                    sec = int(t)
                    sub = t - sec
                    timestamps.append(HighTime(sec, sub))
                    values_out.append(all_raw[i])
                    if 0 < max_points == len(timestamps):
                        return timestamps, values_out

            # handle tail if needed
            last_i, last_t = markers[-1]
            expected_dt = 1.0 / sample_rate
            for i in range(last_i, len(all_raw)):
                t = last_t + (i - last_i) * expected_dt
                if t > end_f:
                    break
                sec = int(t)
                sub = t - sec
                timestamps.append(HighTime(sec, sub))
                values_out.append(all_raw[i])
                if 0 < max_points == len(timestamps):
                    return timestamps, values_out

        else:
            # Fallback: no reliable markers
            dt = 1.0 / sample_rate
            for i, val in enumerate(all_raw):
                t = entry_start_f + i * dt
                if t < start_f:
                    continue
                if t > end_f:
                    break
                sec = int(t)
                sub = t - sec
                timestamps.append(HighTime(sec, sub))
                values_out.append(val)
                if 0 < max_points == len(timestamps):
                    break

        return timestamps, values_out

    def append(self, time: HighTime, value: float, consolidate: bool = False) -> int:
        """Append a single data point.
        
        Args:
            time: Timestamp for the data point
            value: Data value
            consolidate: Whether to consolidate with existing data
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._index_file or not self._data_file:
            return -1
            
        # Write timestamp and data
        result = self._write_timestamp_and_data(time, value)
        
        # Update header end time if needed
        if result == 0 and time > self._header.end_time:
            self._header.end_time = time
            self.write_header()
            
        return result

    def append_block(self, start_time: HighTime, data_values: List[float]) -> int:
        """Append a block of data points.
        
        Args:
            start_time: Start time for the data block
            data_values: List of data values
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._index_file or not self._data_file or not data_values:
            return -1
            
        # Write first timestamp and value
        current_time = start_time
        result = self._write_timestamp_and_data(current_time, data_values[0])
        if result < 0:
            return -1
            
        # Write remaining values
        for i in range(1, len(data_values)):
            # Calculate next timestamp
            current_time = HighTime(
                current_time.seconds + int(self._delta_time.seconds),
                current_time.subseconds + self._delta_time.subseconds
            )
            
            # Write data
            data_bytes = struct.pack('f', data_values[i])
            result = self._write_data(data_bytes, True)
            if result < 0:
                return -1
                
            # Write timestamp
            result = self._write_timestamp(current_time)
            if result < 0:
                return -1
        
        # Update header end time if needed
        if current_time > self._header.end_time:
            self._header.end_time = current_time
            self.write_header()
            
        return 0

    def get_data_rate(self) -> float:
        """Get the data rate.
        
        Returns:
            float: Data rate in Hz
        """
        return self._header.data_rate

    def set_data_rate(self, data_rate: float):
        """Set the data rate.
        
        Args:
            data_rate: New data rate in Hz
        """
        self._header.data_rate = data_rate
        self._data_rate = data_rate
        self.write_header()

    def get_channel_name(self) -> str:
        """Get the channel name.
        
        Returns:
            str: Channel name
        """
        return self._channel_name

    def set_channel_name(self, name: str):
        """Set the channel name.
        
        Args:
            name: New channel name
        """
        self._channel_name = name

    def get_start_time(self) -> HighTime:
        """Get the start time.
        
        Returns:
            HighTime: Start time
        """
        return self._header.start_time

    def get_end_time(self) -> HighTime:
        """Get the end time.
        
        Returns:
            HighTime: End time
        """
        return self._header.end_time
        
    def set_zero_time(self, zero_time: HighTime):
        """Set the zero time.
        
        Args:
            zero_time: New zero time
        """
        self._zero_time = zero_time
        
    def get_zero_time(self) -> HighTime:
        """Get the zero time.
        
        Returns:
            HighTime: Zero time
        """
        return self._zero_time
        
    def flush(self, synchronous: bool = False):
        """Flush data to disk.
        
        Args:
            synchronous: Whether to wait for flush to complete
        """
        if self._index_file:
            self._index_file.flush()
            
        if self._data_file:
            self._data_file.flush() 