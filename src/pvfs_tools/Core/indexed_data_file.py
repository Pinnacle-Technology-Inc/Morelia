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
                 overwrite: bool = False, channel_name: Optional[str] = None):
        """Initialize the indexed data file.
        
        Args:
            pvfs_file: The PVFS file instance
            filename: Base name for .index/.idat files in PVFS (e.g. EEG00)
            seconds: Time interval between timestamps
            create: Whether to create a new file
            async_cache: Whether to use async caching (not used in Python implementation)
            overwrite: Whether to overwrite existing file
            channel_name: Display name for the channel (e.g. EEG0); if None, uses filename
        """
        self._pvfs_file = pvfs_file
        self._filename = filename
        self._channel_name = channel_name if channel_name is not None else filename
        self._header = IndexedHeader()
        self._header.timestamp_interval_seconds = seconds
        
        self._index_file = None
        self._data_file = None
        
        # Data file position tracking
        self._data_file_index = 0
        # CRC of previous block's float data (written at start of next block in .idat)
        self._pending_block_crc: Optional[int] = None
        # True after writing the final end-timestamp block (ensures at least 2 index entries per channel)
        self._end_timestamp_block_written = False
        # True if append_block was called this session (so we may need to write end-timestamp block on flush)
        self._has_appended_this_session = False
        
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
            
        # Create empty files in the VFS (fcreate; create_file/PVFS_add expects a disk file to add)
        self._index_file = pvfs_file.fcreate(index_name)
        self._data_file = pvfs_file.fcreate(data_name)
        
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
        self._end_timestamp_block_written = False
        self._has_appended_this_session = False
        
        # Write header
        if not self.write_header(self._header):
            return False
        # Reader expects timestamp entries to start at INDEX_HEADER_SIZE (1000)
        self._index_file.seek(self.INDEX_HEADER_SIZE)
        return True

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
            # Pad to INDEX_HEADER_SIZE (C++ writes full 1K header)
            pos = self._index_file.tell()
            if pos < self.INDEX_HEADER_SIZE:
                pad = self.INDEX_HEADER_SIZE - pos
                self._index_file.write(b"\x00" * pad, pad)
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
        """Read all index entries from the index file.
        Layout (matches sine.pvfs / C++): 1K header then 44-byte entries (8 marker, 8 sec, 8 subsec, 8 reserved, 8 data_location, 4 CRC). Each entry points to a block in .idat (32-byte header + N floats; optional 4-byte CRC before non-first blocks).
        """
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

        # Add the last (or only) block entry so single-block files get one entry (count >= 1)
        if count >= 1 and last_time is not None:
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
        
        Format must match _read_timestamp: 8 marker bytes, int64 seconds, double
        subseconds, int64 reserved, int64 data_location, uint32 CRC.
        
        Args:
            time: The timestamp to write
            
        Returns:
            int: The location where the timestamp was written, or -1 if error
        """
        if not self._index_file:
            return -1
            
        try:
            # Append after existing entries. After write_header() we are at INDEX_HEADER_SIZE,
            # so we would overwrite the first entry. Seek to end of file to append instead.
            info = self._index_file.get_file_info()
            append_pos = info.size
            if append_pos < self.INDEX_HEADER_SIZE:
                append_pos = self.INDEX_HEADER_SIZE
            self._index_file.seek(append_pos)
            location = self._index_file.tell()
            reserved = 0
            data_location = self._data_file.tell()
            for i in range(8):
                self._index_file.fwrite_uint8(self.UNIQUE_MARKER_BYTE)
            self._index_file.fwrite_int64(time.seconds)
            self._index_file.fwrite_double(time.subseconds)
            self._index_file.fwrite_int64(reserved)
            self._index_file.fwrite_int64(data_location)
            crc_input = struct.pack('<q', time.seconds) + struct.pack('<d', time.subseconds) + struct.pack('<q', reserved) + struct.pack('<q', data_location)
            crc = CRC32.calculate_crc32(crc_input)
            self._index_file.fwrite_uint32(crc)
            self._index_file.flush()
            return location
        except Exception as e:
            print(f"Error writing timestamp: {e}")
            return -1

    def _write_block_to_idat(self, start_time: HighTime, float_list: List[float]) -> int:
        """Write one block to the .idat file (C++ layout).
        
        Index file: one 44-byte timestamp entry with (start_time, data_location).
        Data file: [optional 4-byte CRC of previous block] [32-byte header] [N floats].
        data_location points to the start of the 32-byte header.
        float_list may be empty for an end-timestamp-only block (still creates index entry + 32-byte header).
        
        Args:
            start_time: Block start timestamp
            float_list: All float values in this block (may be empty for end-timestamp block)
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._data_file or not self._index_file:
            return -1
        try:
            # 1) If not first block, write previous block's CRC to .idat (C++ order)
            if self._data_file.tell() > 0 and self._pending_block_crc is not None:
                self._data_file.fwrite_uint32(self._pending_block_crc)

            # 2) Write index entry (data_location = current .idat position = start of 32-byte header)
            if self._write_timestamp(start_time) < 0:
                return -1

            # 3) Write 32-byte block header: 8 marker, 8 sec, 8 subsec, 8 reserved
            for _ in range(8):
                self._data_file.fwrite_uint8(self.UNIQUE_MARKER_BYTE)
            self._data_file.fwrite_int64(start_time.seconds)
            self._data_file.fwrite_double(start_time.subseconds)
            self._data_file.fwrite_int64(0)  # reserved

            # 4) Write all floats and accumulate CRC for this block (written at start of next block)
            crc_calc = CRC32()
            for v in float_list:
                data_bytes = struct.pack('<f', v)
                crc_calc.append_bytes(data_bytes)
                self._data_file.write(data_bytes, 4)
            self._pending_block_crc = crc_calc.get_crc()
            self._data_file.flush()
            return 0
        except Exception as e:
            print(f"Error writing block to idat: {e}")
            return -1


    def get_data(self,
                start_time: HighTime,
                end_time: HighTime,
                max_points: int = -1
                ) -> Tuple[List[HighTime], List[float]]:
        """Read data using index; procedure matches C++ IndexedDataFileCache::GetData and Python write.

        Write sequence (_write_block_to_idat): [optional 4-byte CRC] then index entry (data_location =
        current .idat position) then [32-byte header][N floats]. So on disk: block 0 = [32][N0 floats],
        block 1 = [4 CRC][32][N1 floats], ...; index entry k has data_location = start of that block's
        32-byte header (0 for block 0, 36+N0*4 for block 1, etc.). Read uses the same layout:

        1. Clamp [start_time, end_time] to file range (C++ m_actualStartTime/m_actualEndTime).
        2. Iterate index entries that overlap [start_f, end_f] (C++ Start -> FindTimeStampIndex).
        3. For each block: N = (next_data_loc - data_loc - 36) / 4 (36 = 32-byte header + 4-byte CRC
           before next block; matches _write_block_to_idat). Last block: N = (idat_size - data_loc - 32) / 4.
        4. Seek to data_loc, skip 32-byte header, read N floats (data starts at data_loc + 32).
        5. Timestamp for sample j = block_start + j * (1/data_rate).
        6. Emit only samples with t in [start_f, end_f]; stop at max_points if set.
        """
        BYTES_PER_FLOAT = 4
        # C++ m_DataChunkHeaderSizeBeforeData = 32, m_DataChunkHeaderSize = 36 (32 + 4 for CRC before next block)
        HEADER_BEFORE_DATA = 32
        CHUNK_HEADER_SIZE = 36  # 32 + 4; used in N = (next_loc - data_loc - 36) / 4

        timestamps: List[HighTime] = []
        values_out: List[float] = []
        if not self._index_file or not self._data_file:
            return timestamps, values_out

        start_f = start_time.to_seconds()
        end_f = end_time.to_seconds()
        if end_f <= start_f:
            return timestamps, values_out

        sample_rate = self.get_data_rate()
        if sample_rate <= 0:
            return timestamps, values_out
        delta = 1.0 / sample_rate

        if not self._indices:
            return timestamps, values_out

        # Clamp to file range (C++: m_actualStartTime/m_actualEndTime)
        file_start_f = self._header.start_time.to_seconds()
        file_end_f = self._header.end_time.to_seconds()
        start_f = max(start_f, file_start_f)
        end_f = min(end_f, file_end_f)
        if end_f <= start_f:
            return timestamps, values_out

        idat_info = self._data_file.get_file_info()
        idat_size = idat_info.size

        self._pvfs_file.lock()
        try:
            for i, entry in enumerate(self._indices):
                block_start_f = entry.start_time.to_seconds()
                block_end_f = entry.end_time.to_seconds()
                if block_end_f <= start_f or block_start_f >= end_f:
                    continue

                data_loc = entry.data_location
                # Same as C++ StartNextSequence: N = (next_data_loc - data_loc - CHUNK_HEADER_SIZE) / sizeof(float)
                if i + 1 < len(self._indices):
                    next_loc = self._indices[i + 1].data_location
                    n_floats = (next_loc - data_loc - CHUNK_HEADER_SIZE) // BYTES_PER_FLOAT
                else:
                    n_floats = (idat_size - data_loc - HEADER_BEFORE_DATA) // BYTES_PER_FLOAT
                if n_floats <= 0:
                    continue

                # Data starts at data_loc + 32 (C++ m_DataFileSequenceIndex = m_NextTimeStampIndex + m_DataChunkHeaderSizeBeforeData)
                self._data_file.seek(data_loc)
                self._data_file.read(HEADER_BEFORE_DATA)
                raw = self._data_file.read(n_floats * BYTES_PER_FLOAT)
                if len(raw) != n_floats * BYTES_PER_FLOAT:
                    continue
                vals = struct.unpack(f'<{n_floats}f', raw)

                for j, v in enumerate(vals):
                    t = block_start_f + j * delta
                    if t < start_f:
                        continue
                    if t > end_f:
                        break
                    sec = int(t)
                    sub = t - sec
                    timestamps.append(HighTime(sec, sub))
                    values_out.append(v)
                    if 0 < max_points == len(timestamps):
                        return timestamps, values_out
        finally:
            self._pvfs_file.unlock()

        return timestamps, values_out

    def append(self, time: HighTime, value: float, consolidate: bool = False) -> int:
        """Append a single data point (one block of one sample).
        
        Args:
            time: Timestamp for the data point
            value: Data value
            consolidate: Whether to consolidate with existing data (not used)
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._index_file or not self._data_file:
            return -1
        self._has_appended_this_session = True
        result = self._write_block_to_idat(time, [value])
        if result == 0 and time > self._header.end_time:
            self._header.end_time = time
            self.write_header()
        return result

    def append_block(self, start_time: HighTime, data_values: List[float]) -> int:
        """Append a block of data points (one index entry, one .idat block).
        
        C++ layout: index entry points to block start in .idat; block = 32-byte header + N floats.
        
        Args:
            start_time: Start time for the data block
            data_values: List of data values
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._index_file or not self._data_file or not data_values:
            return -1

        no_data_yet = (
            self._header.end_time.seconds == 0 and self._header.end_time.subseconds == 0.0
        )
        # End time = start + (N-1) * delta
        last_time = HighTime.from_seconds(
            start_time.to_seconds() + (len(data_values) - 1) * self._delta_time.to_seconds()
        )
        if no_data_yet:
            self._header.start_time = start_time
        if last_time > self._header.end_time:
            self._header.end_time = last_time

        # Write header FIRST (at position 0) so we don't rely on seek(0) after appending;
        # some PVFS modes may not allow backward seek, so header would never get updated.
        self.write_header()

        self._has_appended_this_session = True
        result = self._write_block_to_idat(start_time, data_values)
        if result < 0:
            return -1
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
        
        Ensures at least two index entries per channel by writing an end-timestamp block
        (a datablock with no samples, containing only the end timestamp) when data has
        been appended and that block has not yet been written.
        
        Args:
            synchronous: Whether to wait for flush to complete
        """
        if self._has_appended_this_session and not self._end_timestamp_block_written:
            end_time = self._header.end_time
            if end_time is not None and (end_time.seconds != 0 or end_time.subseconds != 0.0):
                if self._write_block_to_idat(end_time, []) == 0:
                    self._end_timestamp_block_written = True
                    self.write_header()
        if self._index_file:
            self._index_file.flush()
        if self._data_file:
            self._data_file.flush() 