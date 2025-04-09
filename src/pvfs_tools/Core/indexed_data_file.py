from dataclasses import dataclass
from typing import List, Optional, Tuple
import ctypes
from pathlib import Path
import struct

from .pvfs_binding import PvfsFile, HighTime, PvfsFileHandle, PvfsFileHandleWrapper

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
        self._previous_timestamp = HighTime(-1, 0.0)
        self._next_timestamp = HighTime(-1, 0.0)
        self._delta_time = HighTime(1.0, 0.0)
        self._max_delta = HighTime(2.0, 0.0)
        
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
        """Read a timestamp from the specified location.
        
        Args:
            location: File position to read from
            
        Returns:
            Tuple[Optional[HighTime], int]: The timestamp and data location, or (None, -1) if error
        """
        if not self._index_file:
            return None, -1
            
        try:
            self._index_file.seek(location)
            marker = self._index_file.fread_uint8()
            if marker != self.UNIQUE_MARKER_BYTE:
                return None, -1
                
            seconds = self._index_file.fread_int64()
            subseconds = self._index_file.fread_double()
            data_location = self._index_file.fread_int64()
            
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

    def get_data(self, start_time: HighTime, end_time: HighTime, max_points: int = -1) -> Tuple[List[HighTime], List[float]]:
        """Get data within the specified time range.
        
        Args:
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            max_points: Maximum number of points to return (-1 for all)
            
        Returns:
            Tuple of (timestamps, values)
        """
        timestamps = []
        values = []
        
        if not self._index_file or not self._data_file:
            return timestamps, values

        print(f"index length: {len(self._indices)}")  
        # Find indices that overlap with the time range
        relevant_indices = []
        for entry in self._indices:
            print(f"{abs(entry.start_time.seconds)}  {abs(start_time.seconds)}  {abs(entry.end_time.seconds)} {abs(end_time.seconds)}")
            if (entry.start_time.seconds <= end_time.seconds and entry.end_time.seconds >= start_time.seconds):
                relevant_indices.append(entry)
        
        if not relevant_indices:
            return timestamps, values
            
        # Read data from each relevant index
        for entry in relevant_indices:
            # Read timestamp and data from this index
            timestamp, data_location = self._read_timestamp(entry.my_location)
            if timestamp is None:
                continue
                
            # Read data value
            self._pvfs_file.lock()
            try:
                self._data_file.seek(data_location)
                
                # Read float value
                value_bytes = bytearray(4)
                for i in range(4):
                    byte_val = ctypes.c_uint8()
                    byte_val = self._data_file.fread_uint8()
                    value_bytes[i] = byte_val
                
                value = struct.unpack('f', bytes(value_bytes))[0]
                
                # Add to results if within time range
                if start_time.seconds <= timestamp.seconds <= end_time.seconds:
                    timestamps.append(timestamp)
                    values.append(value)
                    
                    # Check if we've reached max_points
                    if max_points > 0 and len(timestamps) >= max_points:
                        break
            finally:
                self._pvfs_file.unlock()
        
        return timestamps, values

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