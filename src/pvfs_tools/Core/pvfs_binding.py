import ctypes
import os
from pathlib import Path

# Load the shared library
def load_library():
    # Get the directory containing this script
    current_dir = Path(__file__).parent.absolute()
    
    # Try to load the library
    try:
        if os.name == 'nt':  # Windows
            lib_path = current_dir / "pvfs_wrapper.dll"
        else:  # Linux/Mac
            lib_path = current_dir / "libpvfs_wrapper.so"
        
        return ctypes.CDLL(str(lib_path))
    except Exception as e:
        raise RuntimeError(f"Failed to load PVFS wrapper library: {e}")

# Load the library
_lib = load_library()

# Define wrapper classes
class PvfsFileWrapper(ctypes.Structure):
    _fields_ = [
        ("ptr", ctypes.c_void_p)
    ]

class PvfsFileHandleWrapper(ctypes.Structure):
    _fields_ = [
        ("ptr", ctypes.c_void_p)
    ]

class StringVectorWrapper(ctypes.Structure):
    _fields_ = [
        ("strings", ctypes.POINTER(ctypes.c_char_p)),
        ("size", ctypes.c_size_t)
    ]

class PvfsFileEntryWrapper(ctypes.Structure):
    _fields_ = [
        ("startBlock", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("filename", ctypes.c_char * 256)
    ]

class PvfsLocationMapWrapper(ctypes.Structure):
    _fields_ = [
        ("startBlock", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("location", ctypes.c_char * 256)
    ]

class PvfsFileVersionWrapper(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_int32),
        ("timestamp", ctypes.c_int64),
        ("comment", ctypes.c_char * 256)
    ]

class PvfsBlockWrapper(ctypes.Structure):
    _fields_ = [
        ("offset", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("type", ctypes.c_int32)
    ]

class PvfsBlockDataWrapper(ctypes.Structure):
    _fields_ = [
        ("offset", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("data", ctypes.POINTER(ctypes.c_uint8))
    ]

class PvfsBlockTreeWrapper(ctypes.Structure):
    _fields_ = [
        ("offset", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("depth", ctypes.c_int32)
    ]

class PvfsBlockFileWrapper(ctypes.Structure):
    _fields_ = [
        ("offset", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("filename", ctypes.c_char * 256)
    ]

class PvfsIndexHeaderWrapper(ctypes.Structure):
    _fields_ = [
        ("magicNumber", ctypes.c_int32),
        ("version", ctypes.c_int32),
        ("dataType", ctypes.c_int32),
        ("datarate", ctypes.c_double),
        ("startTime", ctypes.c_int64),
        ("endTime", ctypes.c_int64)
    ]

class PvfsHighTimeWrapper(ctypes.Structure):
    _fields_ = [
        ("seconds", ctypes.c_int64),
        ("subseconds", ctypes.c_double)
    ]

class CWrapper(ctypes.Structure):
    _fields_ = [
        ("p1", ctypes.c_uint32),
        ("p2", ctypes.c_uint32)
    ]

# Set up function signatures
_lib.create_vfs.argtypes = [ctypes.c_uint32]
_lib.create_vfs.restype = ctypes.POINTER(PvfsFileWrapper)

_lib.open_vfs.argtypes = [ctypes.c_char_p]
_lib.open_vfs.restype = ctypes.POINTER(PvfsFileWrapper)

_lib.create_file.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p]
_lib.create_file.restype = ctypes.POINTER(PvfsFileHandleWrapper)

_lib.open_file.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p]
_lib.open_file.restype = ctypes.POINTER(PvfsFileHandleWrapper)

_lib.write_file.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
_lib.write_file.restype = ctypes.c_int32

_lib.read_file.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
_lib.read_file.restype = ctypes.c_int32

_lib.close_file.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper)]
_lib.close_file.restype = None

_lib.delete_vfs.argtypes = [ctypes.POINTER(PvfsFileWrapper)]
_lib.delete_vfs.restype = None

# String vector operations
_lib.create_string_vector.restype = ctypes.POINTER(StringVectorWrapper)
_lib.delete_string_vector.argtypes = [ctypes.POINTER(StringVectorWrapper)]
_lib.delete_string_vector.restype = None

_lib.get_channel_list.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.POINTER(StringVectorWrapper)]
_lib.get_channel_list.restype = ctypes.c_int32

_lib.get_file_list.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.POINTER(StringVectorWrapper)]
_lib.get_file_list.restype = ctypes.c_int32

_lib.extract.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p, ctypes.c_char_p]
_lib.extract.restype = ctypes.c_int32

_lib.get_string_at.argtypes = [ctypes.POINTER(StringVectorWrapper), ctypes.c_size_t]
_lib.get_string_at.restype = ctypes.c_char_p

_lib.get_string_vector_size.argtypes = [ctypes.POINTER(StringVectorWrapper)]
_lib.get_string_vector_size.restype = ctypes.c_size_t

# Index file operations
_lib.read_index_file_header.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(PvfsIndexHeaderWrapper)]
_lib.read_index_file_header.restype = ctypes.c_int32

_lib.write_index_file_header.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(PvfsIndexHeaderWrapper)]
_lib.write_index_file_header.restype = ctypes.c_int32

_lib.open_data_channel.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p]
_lib.open_data_channel.restype = ctypes.POINTER(PvfsFileHandleWrapper)

# HighTime operations
_lib.create_high_time.argtypes = [ctypes.c_int64, ctypes.c_double]
_lib.create_high_time.restype = ctypes.POINTER(PvfsHighTimeWrapper)

_lib.delete_high_time.argtypes = [ctypes.POINTER(PvfsHighTimeWrapper)]
_lib.delete_high_time.restype = None

_lib.get_high_time_seconds.argtypes = [ctypes.POINTER(PvfsHighTimeWrapper)]
_lib.get_high_time_seconds.restype = ctypes.c_int64

_lib.get_high_time_subseconds.argtypes = [ctypes.POINTER(PvfsHighTimeWrapper)]
_lib.get_high_time_subseconds.restype = ctypes.c_double

# Lock operations
_lib.lock_vfs.argtypes = [ctypes.POINTER(PvfsFileWrapper)]
_lib.lock_vfs.restype = None

_lib.unlock_vfs.argtypes = [ctypes.POINTER(PvfsFileWrapper)]
_lib.unlock_vfs.restype = None

_lib.test_modify_header_wrapper.argtypes = [ctypes.POINTER(CWrapper)]
_lib.test_modify_header_wrapper.restype = None

class StringVector:
    def __init__(self):
        """Create a new string vector."""
        self._vec = _lib.create_string_vector()
        if not self._vec:
            print("Python: Failed to create string vector")
            raise RuntimeError("Failed to create string vector")

    def __del__(self):
        """Clean up the string vector."""
        if hasattr(self, '_vec') and self._vec:
            print("Python: Cleaning up StringVector")
            try:
                _lib.delete_string_vector(self._vec)
            except Exception as e:
                print(f"Python: Error cleaning up StringVector: {e}")
            finally:
                self._vec = None

    def __len__(self):
        """Get the number of strings in the vector."""
        if not self._vec:
            print("Python: StringVector is not initialized")
            return 0
        try:
            size = _lib.get_string_vector_size(self._vec)
            return size
        except Exception as e:
            print(f"Python: Error getting StringVector size: {e}")
            return 0

    def __getitem__(self, index):
        """Get a string at the specified index."""
        if not self._vec:
            print("Python: StringVector is not initialized")
            raise RuntimeError("String vector is not initialized")
        if not 0 <= index < len(self):
            print(f"Python: Index {index} out of range")
            raise IndexError("Index out of range")
        try:
            result = _lib.get_string_at(self._vec, index)
            if not result:
                print(f"Python: Failed to get string at index {index}")
                raise RuntimeError(f"Failed to get string at index {index}")
            return result.decode('utf-8')
        except Exception as e:
            print(f"Python: Error getting string at index {index}: {e}")
            raise

    def __iter__(self):
        """Iterate over the strings in the vector."""
        if not self._vec:
            print("Python: StringVector is not initialized")
            return
        try:
            for i in range(len(self)):
                yield self[i]
        except Exception as e:
            print(f"Python: Error iterating over StringVector: {e}")
            raise

class HighTime:
    def __init__(self, seconds, subseconds):
        self._time = _lib.create_high_time(seconds, subseconds)
        if not self._time:
            raise RuntimeError("Failed to create HighTime")

    def __del__(self):
        if self._time:
            _lib.delete_high_time(self._time)

    @property
    def seconds(self):
        return _lib.get_high_time_seconds(self._time)

    @property
    def subseconds(self):
        return _lib.get_high_time_subseconds(self._time)

class PvfsFile:
    def __init__(self, block_size=0x4000):
        """Initialize a new VFS instance."""
        self._wrapper = _lib.create_vfs(block_size)
        if not self._wrapper:
            raise RuntimeError(f"Failed to create VFS with block size {block_size}")

    @classmethod
    def open(cls, filename):
        """Open an existing VFS file."""
        print(f"Python: Opening VFS file: {filename}")
        try:
            # Check if file exists
            if not os.path.exists(filename):
                raise FileNotFoundError(f"VFS file does not exist: {filename}")
            
            # Try to open the file
            wrapper = _lib.open_vfs(filename.encode('utf-8'))
            if not wrapper:
                raise RuntimeError(f"Failed to open VFS file: {filename}")
            
            instance = cls()
            instance._wrapper = wrapper
            print("Python: Successfully opened VFS")
            return instance
        except Exception as e:
            print(f"Python: Error opening VFS: {str(e)}")
            raise

    def create_file(self, filename):
        handle = _lib.create_file(self._wrapper, filename.encode('utf-8'))
        if not handle:
            raise RuntimeError(f"Failed to create file: {filename}")
        return PvfsFileHandle(handle, self)

    def open_file(self, filename):
        handle = _lib.open_file(self._wrapper, filename.encode('utf-8'))
        if not handle:
            raise RuntimeError(f"Failed to open file: {filename}")
        return PvfsFileHandle(handle, self)

    def get_channel_list(self):
        """Get list of channels in the VFS."""
        try:
            names = StringVector()
            result = _lib.get_channel_list(self._wrapper, names._vec)
            if result < 0:
                error_msg = f"Failed to get channel list: {result}"
                print(f"Python: {error_msg}")
                raise RuntimeError(error_msg)
            return names
        except Exception as e:
            print(f"Python: Exception in get_channel_list: {str(e)}")
            raise

    def get_file_list(self):
        names = StringVector()
        result = _lib.get_file_list(self._wrapper, names._vec)
        if result < 0:
            raise RuntimeError(f"Failed to get file list: {result}")
        return names

    def extract(self, in_file, out_file):
        result = _lib.extract(self._wrapper, in_file.encode('utf-8'), out_file.encode('utf-8'))
        if result < 0:
            raise RuntimeError(f"Failed to extract file: {result}")
        return result

    def open_data_channel(self, channel_name):
        handle = _lib.open_data_channel(self._wrapper, channel_name.encode('utf-8'))
        if not handle:
            raise RuntimeError(f"Failed to open data channel: {channel_name}")
        return PvfsFileHandle(handle, self)

    def lock(self):
        _lib.lock_vfs(self._wrapper)

    def unlock(self):
        _lib.unlock_vfs(self._wrapper)

    def __del__(self):
        if hasattr(self, '_wrapper') and self._wrapper:
            _lib.delete_vfs(self._wrapper)
            self._wrapper = None

class PvfsFileHandle:
    def __init__(self, handle, vfs):
        self._handle = handle
        self._vfs = vfs

    def write(self, data):
        if not isinstance(data, bytes):
            data = bytes(data)
        buffer = (ctypes.c_uint8 * len(data))(*data)
        result = _lib.write_file(self._handle, buffer, len(data))
        if result < 0:
            raise RuntimeError(f"Failed to write data: {result}")
        return result

    def read(self, size):
        buffer = (ctypes.c_uint8 * size)()
        result = _lib.read_file(self._handle, buffer, size)
        if result < 0:
            raise RuntimeError(f"Failed to read data: {result}")
        return bytes(buffer[:result])

    def read_index_file_header(self):
        header = PvfsIndexHeaderWrapper()
        result = _lib.read_index_file_header(self._handle, ctypes.byref(header))
        if result < 0:
            raise RuntimeError(f"Failed to read index file header: {result}")
        return header

    def write_index_file_header(self, header):
        result = _lib.write_index_file_header(self._handle, ctypes.byref(header))
        if result < 0:
            raise RuntimeError(f"Failed to write index file header: {result}")
        return result

    def close(self):
        if hasattr(self, '_handle') and self._handle:
            _lib.close_file(self._handle)
            self._handle = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def create_vfs(block_size):
    """Create a new VFS with the specified block size."""
    return PvfsFile(block_size)

class C:
    def __init__(self):
        self._wrapper = CWrapper()
        self._wrapper.p1 = 0
        self._wrapper.p2 = 0

    @property
    def p1(self):
        return self._wrapper.p1

    @p1.setter
    def p1(self, value):
        self._wrapper.p1 = value

    @property
    def p2(self):
        return self._wrapper.p2

    @p2.setter
    def p2(self, value):
        self._wrapper.p2 = value

def test_modify_header(header):
    _lib.test_modify_header_wrapper(ctypes.byref(header._wrapper)) 