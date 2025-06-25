from typing import Optional, Tuple, List
import numpy as np
from .pvfs_binding import PvfsFile, HighTime
import struct
from PIL import Image
import io

class VideoDataFile:
    """Python implementation for accessing video data stored in a PVFS file.
    
    This class provides access to video data stored in a PVFS file.
    The video data is stored in two files within the PVFS:
    - {stream_name}_frames: Contains the actual video frame data
    - {stream_name}_index: Contains the index information for each frame
    
    The video frames are compressed using VPX (VP8/VP9) codec.
    """
    
    # Constants
    INDEX_HEADER_SIZE = 1024
    FRAME_ENTRY_SIZE = 24  # Size of frame entry in bytes (8 + 8 + 8 for timestamp and location)
    FRAME_HEADER_SIZE = 24  # Size of frame header in bytes (same as FRAME_ENTRY_SIZE)
    UNIQUE_MARKER_BYTE = 0xA5
    
    def __init__(self, vfs: PvfsFile, stream_name: str):
        """Initialize the video data file.
        
        Args:
            vfs: The PVFS file object
            stream_name: The name of the video stream (without _frames/_index suffixes)
        """
        self._vfs = vfs
        self._stream_name = stream_name
        self._frames_file = None
        self._index_file = None
        self._header = None
        self._frame_count = 0
        self._frame_rate = 0.0
        self._width = 0
        self._height = 0
        self._start_time = None
        self._end_time = None
        self._version = (1, 0, 3)  # Major, minor, release
        self._compression_type = 0
        self._differencing_frame_number = 0
        self._current_frame_index = -1
        self._last_frame_index = -1
        self._frame_buffer = {}  # Cache for decoded frames
        
        self._open()
        
    def _open(self) -> None:
        """Open the video stream files and read header information."""
        # Close any existing handles first
        self.close()
        
        # Open the frames file
        frames_name = f"{self._stream_name}_frames"
        self._frames_file = self._vfs.open_file(frames_name)
        if not self._frames_file:
            raise RuntimeError(f"Failed to open frames file: {frames_name}")
            
        # Open the index file
        index_name = f"{self._stream_name}_index"
        self._index_file = self._vfs.open_file(index_name)
        if not self._index_file:
            # Close frames file if index file fails to open
            self._frames_file.close()
            self._frames_file = None
            raise RuntimeError(f"Failed to open index file: {index_name}")
            
        # Read header information
        self._read_header()
        
    def _read_header(self) -> None:
        """Read the header information from the index file."""
        if not self._index_file:
            return
            
        print("Reading header...")
        # Read magic bytes ("PVID")
        magic = self._index_file.read(4)
        if magic != b'PVID':
            raise RuntimeError(f"Invalid magic bytes: {magic.hex()}")
            
        # Read version
        major = self._index_file.fread_uint8()
        minor = self._index_file.fread_uint8()
        release = self._index_file.fread_uint16()
        self._version = (major, minor, release)
        
        # Read dimensions
        self._height = self._index_file.fread_uint32()
        self._width = self._index_file.fread_uint32()
        
        # Read compression type
        self._compression_type = self._index_file.fread_uint16()
        
        # Read differencing frame number
        self._differencing_frame_number = self._index_file.fread_uint8()
        
        # Skip remaining header bytes
        current_pos = self._index_file.tell()
        if current_pos < self.INDEX_HEADER_SIZE:
            self._index_file.seek(self.INDEX_HEADER_SIZE)
        
        # Read frame count from file size
        info = self._index_file.get_file_info()
        self._frame_count = (info.size - self.INDEX_HEADER_SIZE) // self.FRAME_ENTRY_SIZE
                    
        # Set start and end times
        if self._frame_count > 1:
            print("Reading start and end times...")
            self._start_time, _ = self._read_frame_header(0)  # First frame
            print(f"Start time: {self._start_time}")
            self._end_time, _ = self._read_frame_header(self._frame_count - 1)  # Last frame
            print(f"End time: {self._end_time}")

            if self._start_time and self._end_time:
                dt = (self._end_time.seconds + self._end_time.subseconds) - (self._start_time.seconds + self._start_time.subseconds)
                if dt > 0:
                    self._frame_rate = (self._frame_count - 1) / dt

            print(f"Frame rate {self._frame_rate}")
            
    def close(self) -> None:
        """Close the video stream files."""
        if self._frames_file:
            try:
                self._frames_file.close()
            except Exception as e:
                print(f"Warning: Failed to close frames file: {e}")
            self._frames_file = None
            
        if self._index_file:
            try:
                self._index_file.close()
            except Exception as e:
                print(f"Warning: Failed to close index file: {e}")
            self._index_file = None
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def get_start_time(self) -> HighTime:
        """Get the start time of the video stream."""
        return self._start_time
        
    def get_end_time(self) -> HighTime:
        """Get the end time of the video stream."""
        return self._end_time
        
    def get_frame_rate(self) -> float:
        """Get the frame rate of the video stream."""
        return self._frame_rate
        
    def get_frame_count(self) -> int:
        """Get the total number of frames in the video stream."""
        return self._frame_count
        
    def get_frame_size(self) -> Tuple[int, int]:
        """Get the dimensions of the video frames (width, height)."""
        return self._width, self._height
        
    def _read_frame_header(self, frame_index: int) -> Tuple[Optional[HighTime], int]:
        """Read a frame header from the specified frame index.
        
        Args:
            frame_index: Index of the frame to read
            
        Returns:
            Tuple[Optional[HighTime], int]: The timestamp and frame location, or (None, -1) if error
        """
        if not self._index_file or frame_index < 0 or frame_index >= self._frame_count:
            return None, -1
            
        try:
            # Calculate location in file
            location = self.INDEX_HEADER_SIZE + frame_index * self.FRAME_ENTRY_SIZE
            self._index_file.seek(location)
            
            # Check marker bytes
#            for i in range(8):
#                marker = self._index_file.fread_uint8()
#                print(f"{marker:02x}")
#                if marker != self.UNIQUE_MARKER_BYTE:
#                    print(f"Invalid marker byte at position {i}: {marker}")
#                    return None, -1
                    
            # Read timestamp
            seconds = self._index_file.fread_int64()
            subseconds = self._index_file.fread_double()
#            print(f"timestamp {seconds}  {subseconds}")
            timestamp = HighTime(seconds, subseconds)
            
            # Read frame location
            frame_location = self._index_file.fread_int64()
#            print(f"frame location {frame_location}")
            
            return timestamp, frame_location
            
        except Exception as e:
            print(f"Error reading frame header: {e}")
            return None, -1
        
    @staticmethod
    def check_vp8_header(frame_data: bytes) -> bool:
        if len(frame_data) < 10:
            print("Too short to be valid VP8")
            return False

        # Parse the first 3 bytes (Frame Tag)
        b0, b1, b2 = frame_data[0], frame_data[1], frame_data[2]
        frame_type = b0 & 0x01  # LSB is 0 for key frame
        version = (b0 >> 1) & 0x07
        show_frame = (b0 >> 4) & 0x01
        first_partition_size = ((b0 >> 5) | (b1 << 3) | (b2 << 11)) & 0x7FFFF

#        print(f"Frame type: {'key' if frame_type == 0 else 'inter'}")
#        print(f"Version: {version}")
#        print(f"Show Frame: {show_frame}")
#        print(f"First partition size: {first_partition_size}")

        # If it's a key frame, check for the magic number
        if frame_type == 0:
            if frame_data[3:6] != b'\x9D\x01\x2A':
#                print("Missing VP8 sync code")
                return False
#            else:
#                print("Valid VP8 keyframe header")
#        else:
#            print("Non-keyframe — sync code not required")

        return True
            
    def _read_frame_data(self, location: int) -> Optional[bytes]:
        """Read frame data from the specified location.
        
        Args:
            location: File position to read from
            
        Returns:
            The frame data as bytes, or None if error
        """
        if not self._frames_file:
            return None
            
        try:
#            location  = 101807
            self._frames_file.seek(location)
            
            # Check marker byte
#            marker = self._frames_file.fread_uint8()
#            if marker != self.UNIQUE_MARKER_BYTE:
#                print(f"Invalid marker byte at location {location}: {marker:02x}")
#                return None
                
            # Read frame size
            frame_size = self._frames_file.fread_uint32()
#            print(f"Frame size {frame_size}")
            if frame_size <= 0 or frame_size > 1024 * 1024 * 10:  # Sanity check: max 10MB per frame
                print(f"Invalid frame size at location {location}: {frame_size}")
                return None
            
            # Read frame data
            frame_data = self._frames_file.read(frame_size)

            if frame_data:
                is_valid = self.check_vp8_header(frame_data)
#                print(f"VP8 header valid: {is_valid}")

            if len(frame_data) != frame_size:
                print(f"Failed to read complete frame data. Expected {frame_size} bytes, got {len(frame_data)}")
                return None
                
            return frame_data
            
        except Exception as e:
            print(f"Error reading frame data at location {location}: {e}")
            return None

    def get_frame(self, frame_index: int) -> Optional[np.ndarray]:
        """Get a specific frame by index.
        
        Args:
            frame_index: The index of the frame to retrieve
            
        Returns:
            The frame data as a numpy array, or None if the frame couldn't be read
        """
        if frame_index < 0 or frame_index >= self._frame_count:
            return None
            
        # Check frame buffer first
        if frame_index in self._frame_buffer:
            return self._frame_buffer[frame_index]
            
        # Calculate frame header location using FRAME_ENTRY_SIZE
#        frame_index = self.INDEX_HEADER_SIZE + frame_index * self.FRAME_ENTRY_SIZE
        
        # Read frame header
        _, frame_location = self._read_frame_header(frame_index)
        if frame_location < 0:
            return None
#        print(f"frame index and location {frame_index}  {frame_location}")
            
        # Read frame data
        self._current_frame_index = frame_index
        frame_data = self._read_frame_data(frame_location)
        if not frame_data:
            return None
            
        frame = np.array(frame_data)
        return frame
            
    def get_frame_at_time(self, time: HighTime) -> Optional[np.ndarray]:
        """Get the frame closest to the specified time.
        
        Args:
            time: The time to get the frame for
            
        Returns:
            The frame data as a numpy array, or None if no frame could be found
        """
        if not self._start_time or not self._end_time:
            return None
            
        # Convert time to frame index
        time_seconds = time.seconds + time.subseconds
        start_seconds = self._start_time.seconds + self._start_time.subseconds
        frame_index = int((time_seconds - start_seconds) * self._frame_rate)
        
        # Clamp frame index
        frame_index = max(0, min(frame_index, self._frame_count - 1))
        
        return self.get_frame(frame_index)
        
    def get_frames(self, start_time: HighTime, end_time: HighTime) -> List[np.ndarray]:
        """Get all frames between the specified times.
        
        Args:
            start_time: The start time
            end_time: The end time
            
        Returns:
            A list of frames as numpy arrays
        """
        frames = []
        current_time = start_time
        
        while current_time < end_time:
            frame = self.get_frame_at_time(current_time)
            if frame is not None:
                frames.append(frame)
            current_time = current_time + 1/self._frame_rate
            
        return frames
        
    def is_valid(self) -> bool:
        """Check if the video stream is valid."""
        print(f"frames_file: {self._frames_file}")
        print(f"index_file: {self._index_file}")
        print(f"start_time: {self._start_time}")
        print(f"end_time: {self._end_time}")
        return (self._frames_file is not None and 
                self._index_file is not None and 
                self._start_time is not None and 
                self._end_time is not None) 

    def find_nearest_keyframe_indices(video, start_index: int, end_index: int) -> Tuple[int, int]:
        adjusted_start = start_index
        adjusted_end = end_index

            # Move forward from start_index to find the next keyframe (inclusive)
        for i in range(start_index, video.get_frame_count()):
            ts, loc = video._read_frame_header(i)
            data = video._read_frame_data(loc)
            if video.check_vp8_header(data) and (data[0] & 0x01 == 0):  # keyframe
                adjusted_start = i
                break

        # Move backward from end_index to find the previous keyframe (inclusive)
        for i in range(end_index, -1, -1):
            ts, loc = video._read_frame_header(i)
            data = video._read_frame_data(loc)
            if video.check_vp8_header(data) and (data[0] & 0x01 == 0):  # keyframe
                adjusted_end = i
                break

        return adjusted_start, adjusted_end
