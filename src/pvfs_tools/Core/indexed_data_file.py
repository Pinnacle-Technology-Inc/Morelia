from dataclasses import dataclass
from typing import List, Optional, Tuple
import ctypes
from pathlib import Path
import struct

from .pvfs_binding import PvfsFile, HighTime, _lib

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
            _lib.PVFS_fclose(self._index_file)
            self._index_file = None
            
        if self._data_file:
            _lib.PVFS_fclose(self._data_file)
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
            _lib.PVFS_seek(self._index_file, 0)
            _lib.PVFS_fwrite_uint32(self._index_file, header.magic_number)
            _lib.PVFS_fwrite_uint32(self._index_file, header.version)
            _lib.PVFS_fwrite_uint32(self._index_file, header.data_type)
            _lib.PVFS_fwrite_float(self._index_file, header.data_rate)
            _lib.PVFS_fwrite_sint64(self._index_file, header.start_time.seconds)
            _lib.PVFS_fwrite_double(self._index_file, header.start_time.subseconds)
            _lib.PVFS_fwrite_sint64(self._index_file, header.end_time.seconds)
            _lib.PVFS_fwrite_double(self._index_file, header.end_time.subseconds)
            _lib.PVFS_fwrite_uint32(self._index_file, header.timestamp_interval_seconds)
            _lib.PVFS_flush(self._index_file)
            return True
        finally:
            if lock:
                self._pvfs_file.unlock()

    def read_header(self) -> bool:
        """Read the header information from the file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        return self.read_header_data(self._header)

    def read_header_data(self, header: IndexedHeader) -> bool:
        """Read header data from the file.
        
        Args:
            header: Header object to store the data
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._index_file:
            return False
            
        self._pvfs_file.lock()
        try:
            _lib.PVFS_seek(self._index_file, 0)
            
            # Read header fields
            magic = ctypes.c_uint32()
            _lib.PVFS_fread_uint32(self._index_file, ctypes.byref(magic))
            header.magic_number = magic.value
            
            version = ctypes.c_uint32()
            _lib.PVFS_fread_uint32(self._index_file, ctypes.byref(version))
            header.version = version.value
            
            data_type = ctypes.c_uint32()
            _lib.PVFS_fread_uint32(self._index_file, ctypes.byref(data_type))
            header.data_type = data_type.value
            
            data_rate = ctypes.c_float()
            _lib.PVFS_fread_float(self._index_file, ctypes.byref(data_rate))
            header.data_rate = data_rate.value
            self._data_rate = data_rate.value
            
            start_seconds = ctypes.c_int64()
            _lib.PVFS_fread_sint64(self._index_file, ctypes.byref(start_seconds))
            
            start_subseconds = ctypes.c_double()
            _lib.PVFS_fread_double(self._index_file, ctypes.byref(start_subseconds))
            header.start_time = HighTime(start_seconds.value, start_subseconds.value)
            
            end_seconds = ctypes.c_int64()
            _lib.PVFS_fread_sint64(self._index_file, ctypes.byref(end_seconds))
            
            end_subseconds = ctypes.c_double()
            _lib.PVFS_fread_double(self._index_file, ctypes.byref(end_subseconds))
            header.end_time = HighTime(end_seconds.value, end_subseconds.value)
            
            interval = ctypes.c_uint32()
            _lib.PVFS_fread_uint32(self._index_file, ctypes.byref(interval))
            header.timestamp_interval_seconds = interval.value
            
            if header.timestamp_interval_seconds <= 0:
                header.timestamp_interval_seconds = 10
                
            # Set zero time and time range
            self._zero_time = HighTime(header.start_time.seconds, header.start_time.subseconds)
            self._start_time_set = True
            
            return True
        finally:
            self._pvfs_file.unlock()

    def _read_all_indices(self):
        """Read all index entries from the index file."""
        self._indices.clear()
        self._current_index = 0
        
        if not self._index_file:
            return
            
        # Calculate number of indices
        file_size = _lib.PVFS_get_file_size(self._index_file)
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
        """Read a timestamp from the index file.
        
        Args:
            location: File location to read from
            
        Returns:
            Tuple of (timestamp, data_location) or (None, 0) if failed
        """
        if not self._index_file:
            return None, 0
            
        self._pvfs_file.lock()
        try:
            _lib.PVFS_seek(self._index_file, location)
            
            # Read timestamp
            seconds = ctypes.c_int64()
            _lib.PVFS_fread_sint64(self._index_file, ctypes.byref(seconds))
            
            subseconds = ctypes.c_double()
            _lib.PVFS_fread_double(self._index_file, ctypes.byref(subseconds))
            
            # Read data location
            data_location = ctypes.c_int64()
            _lib.PVFS_fread_sint64(self._index_file, ctypes.byref(data_location))
            
            # Read unique marker
            marker = ctypes.c_uint8()
            _lib.PVFS_fread_uint8(self._index_file, ctypes.byref(marker))
            
            if marker.value == self.UNIQUE_MARKER_BYTE:
                return HighTime(seconds.value, subseconds.value), data_location.value
            else:
                return None, 0
        finally:
            self._pvfs_file.unlock()

    def _write_timestamp(self, time: HighTime) -> int:
        """Write a timestamp to the index file.
        
        Args:
            time: Timestamp to write
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._index_file:
            return -1
            
        self._pvfs_file.lock()
        try:
            # Get current position
            current_pos = _lib.PVFS_ftell(self._index_file)
            
            # Write timestamp
            _lib.PVFS_fwrite_sint64(self._index_file, time.seconds)
            _lib.PVFS_fwrite_double(self._index_file, time.subseconds)
            
            # Write data location
            _lib.PVFS_fwrite_sint64(self._index_file, self._data_file_index)
            
            # Write unique marker
            _lib.PVFS_fwrite_uint8(self._index_file, self.UNIQUE_MARKER_BYTE)
            
            return current_pos
        finally:
            self._pvfs_file.unlock()

    def _write_data(self, data: bytes, do_crc: bool = False) -> int:
        """Write data to the data file.
        
        Args:
            data: Data to write
            do_crc: Whether to calculate CRC
            
        Returns:
            int: 0 on success, -1 on failure
        """
        if not self._data_file:
            return -1
            
        self._pvfs_file.lock()
        try:
            # Write data
            for byte in data:
                _lib.PVFS_fwrite_uint8(self._data_file, byte)
            
            # Update data file index
            self._data_file_index += len(data)
            
            return 0
        finally:
            self._pvfs_file.unlock()

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
            
        # Find indices that overlap with the time range
        relevant_indices = []
        for entry in self._indices:
            if (entry.start_time <= end_time and entry.end_time >= start_time):
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
                _lib.PVFS_seek(self._data_file, data_location)
                
                # Read float value
                value_bytes = bytearray(4)
                for i in range(4):
                    byte_val = ctypes.c_uint8()
                    _lib.PVFS_fread_uint8(self._data_file, ctypes.byref(byte_val))
                    value_bytes[i] = byte_val.value
                
                value = struct.unpack('f', bytes(value_bytes))[0]
                
                # Add to results if within time range
                if start_time <= timestamp <= end_time:
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
            _lib.PVFS_flush(self._index_file)
            
        if self._data_file:
            _lib.PVFS_flush(self._data_file) 