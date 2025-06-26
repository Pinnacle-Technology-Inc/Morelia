import ctypes
import os
from pathlib import Path

from datetime import datetime, timezone

"""
PVFS Python Bindings Legend
==========================

Wrapped Structures:
------------------
PvfsFileWrapper:           pvfs::PvfsFile
PvfsFileHandleWrapper:     pvfs::PvfsFileHandle
StringVectorWrapper:       std::vector<std::string>
PvfsFileEntryWrapper:      pvfs::PvfsFileEntry
PvfsLocationMapWrapper:    pvfs::PvfsLocationMap
PvfsFileVersionWrapper:    pvfs::PvfsFileVersion
PvfsBlockWrapper:          pvfs::PvfsBlock
PvfsBlockDataWrapper:      pvfs::PvfsBlockData
PvfsBlockTreeWrapper:      pvfs::PvfsBlockTree
PvfsBlockFileWrapper:      pvfs::PvfsBlockFile
PvfsIndexHeaderWrapper:    pvfs::PvfsIndexHeader
PvfsHighTimeWrapper:       pvfs::HighTime

Wrapped Functions:
-----------------
create_vfs(block_size: int) -> PvfsFileWrapper:           PVFS_create_size(filename, block_size)
open_vfs(filename: str) -> PvfsFileWrapper:               PVFS_open(filename)
create_file(vfs: PvfsFileWrapper, filename: str) -> PvfsFileHandleWrapper:  PVFS_add(vfs, filename, filename)
open_file(vfs: PvfsFileWrapper, filename: str) -> PvfsFileHandleWrapper:    PVFS_open_file(vfs, filename)
write_file(handle: PvfsFileHandleWrapper, buffer: bytes, size: int) -> int: PVFS_write(handle, buffer, size)
read_file(handle: PvfsFileHandleWrapper, buffer: bytes, size: int) -> int:  PVFS_read(handle, buffer, size)
close_file(handle: PvfsFileHandleWrapper) -> None:        PVFS_close_file(handle)
delete_vfs(vfs: PvfsFileWrapper) -> None:                 PVFS_delete(vfs)
pvfs_close(fd: int) -> int:                              PVFS_close(fd)

Type-Specific Write Operations:
-----------------------------
write_uint8(handle: PvfsFileHandleWrapper, value: int) -> int:    PVFS_write_uint8(handle, value)
write_int8(handle: PvfsFileHandleWrapper, value: int) -> int:     PVFS_write_sint8(handle, value)
write_int16(handle: PvfsFileHandleWrapper, value: int) -> int:    PVFS_write_sint16(handle, value)
write_uint16(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_write_uint16(handle, value)
write_int32(handle: PvfsFileHandleWrapper, value: int) -> int:    PVFS_write_sint32(handle, value)
write_uint32(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_write_uint32(handle, value)
write_int64(handle: PvfsFileHandleWrapper, value: int) -> int:    PVFS_write_sint64(handle, value)
write_uint64(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_write_uint64(handle, value)

Type-Specific Read Operations:
----------------------------
read_uint8(handle: PvfsFileHandleWrapper) -> int:         PVFS_read_uint8(handle, value)
read_int8(handle: PvfsFileHandleWrapper) -> int:          PVFS_read_sint8(handle, value)
read_int16(handle: PvfsFileHandleWrapper) -> int:         PVFS_read_sint16(handle, value)
read_uint16(handle: PvfsFileHandleWrapper) -> int:        PVFS_read_uint16(handle, value)
read_int32(handle: PvfsFileHandleWrapper) -> int:         PVFS_read_sint32(handle, value)
read_uint32(handle: PvfsFileHandleWrapper) -> int:        PVFS_read_uint32(handle, value)
read_int64(handle: PvfsFileHandleWrapper) -> int:         PVFS_read_sint64(handle, value)
read_uint64(handle: PvfsFileHandleWrapper) -> int:        PVFS_read_uint64(handle, value)

File-Specific Type Operations:
---------------------------
fwrite_uint8(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_fwrite_uint8(handle, value)
fwrite_int8(handle: PvfsFileHandleWrapper, value: int) -> int:    PVFS_fwrite_sint8(handle, value)
fwrite_uint16(handle: PvfsFileHandleWrapper, value: int) -> int:  PVFS_fwrite_uint16(handle, value)
fwrite_int16(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_fwrite_sint16(handle, value)
fwrite_uint32(handle: PvfsFileHandleWrapper, value: int) -> int:  PVFS_fwrite_uint32(handle, value)
fwrite_int32(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_fwrite_sint32(handle, value)
fwrite_int64(handle: PvfsFileHandleWrapper, value: int) -> int:   PVFS_fwrite_sint64(handle, value)
fwrite_float(handle: PvfsFileHandleWrapper, value: float) -> int: PVFS_fwrite_float(handle, value)
fwrite_double(handle: PvfsFileHandleWrapper, value: float) -> int: PVFS_fwrite_double(handle, value)

fread_uint8(handle: PvfsFileHandleWrapper) -> int:        PVFS_fread_uint8(handle, value)
fread_int8(handle: PvfsFileHandleWrapper) -> int:         PVFS_fread_sint8(handle, value)
fread_uint16(handle: PvfsFileHandleWrapper) -> int:       PVFS_fread_uint16(handle, value)
fread_int16(handle: PvfsFileHandleWrapper) -> int:        PVFS_fread_sint16(handle, value)
fread_uint32(handle: PvfsFileHandleWrapper) -> int:       PVFS_fread_uint32(handle, value)
fread_int32(handle: PvfsFileHandleWrapper) -> int:        PVFS_fread_sint32(handle, value)
fread_int64(handle: PvfsFileHandleWrapper) -> int:        PVFS_fread_sint64(handle, value)
fread_float(handle: PvfsFileHandleWrapper) -> float:      PVFS_fread_float(handle, value)
fread_double(handle: PvfsFileHandleWrapper) -> float:     PVFS_fread_double(handle, value)

Low-Level File Operations:
-------------------------
tell(handle: PvfsFileHandleWrapper) -> int:              PVFS_tell(handle)
seek(handle: PvfsFileHandleWrapper, offset: int, whence: int) -> int:  PVFS_seek(handle, offset, whence)
write(handle: PvfsFileHandleWrapper, buffer: bytes, size: int) -> int: PVFS_write(handle, buffer, size)
read(handle: PvfsFileHandleWrapper, buffer: bytes, size: int) -> int:  PVFS_read(handle, buffer, size)

File Operations:
---------------
fclose(handle: PvfsFileHandleWrapper) -> int:            PVFS_fclose(handle)
flush(handle: PvfsFileHandleWrapper) -> int:             PVFS_flush(handle)
fcreate(vfs: PvfsFileWrapper, filename: str) -> PvfsFileHandleWrapper:  PVFS_fcreate(vfs, filename)
fopen(vfs: PvfsFileWrapper, filename: str) -> PvfsFileHandleWrapper:    PVFS_fopen(vfs, filename)
has_file(vfs: PvfsFileWrapper, filename: str) -> int:    PVFS_has_file(vfs, filename)
delete_file(vfs: PvfsFileWrapper, filename: str) -> int: PVFS_delete_file(vfs, filename)

String Vector Operations:
------------------------
create_string_vector() -> StringVectorWrapper:            create_string_vector()
delete_string_vector(vec: StringVectorWrapper) -> None:   delete_string_vector(vec)
get_string_at(vec: StringVectorWrapper, index: int) -> str: get_string_at(vec, index)
get_string_vector_size(vec: StringVectorWrapper) -> int:  get_string_vector_size(vec)

File Operations:
---------------
get_channel_list(vfs: PvfsFileWrapper, names: StringVectorWrapper) -> int:  PVFS_get_channel_list(vfs, names)
get_file_list(vfs: PvfsFileWrapper, names: StringVectorWrapper) -> int:     PVFS_get_file_list(vfs, names)
extract(vfs: PvfsFileWrapper, in_file: str, out_file: str) -> int:          PVFS_extract(vfs, in_file, out_file)

Index File Operations:
---------------------
read_index_file_header(handle: PvfsFileHandleWrapper, header: PvfsIndexHeaderWrapper) -> int:  PVFS_read_index_file_header(handle, header)
write_index_file_header(handle: PvfsFileHandleWrapper, header: PvfsIndexHeaderWrapper) -> int: PVFS_write_index_file_header(handle, header)
open_data_channel(vfs: PvfsFileWrapper, channel_name: str) -> PvfsFileHandleWrapper:           PVFS_open_data_channel(vfs, channel_name)

HighTime Operations:
-------------------
create_high_time(seconds: int, subseconds: float) -> PvfsHighTimeWrapper:   create_high_time(seconds, subseconds)
delete_high_time(time: PvfsHighTimeWrapper) -> None:                       delete_high_time(time)
get_high_time_seconds(time: PvfsHighTimeWrapper) -> int:                   get_high_time_seconds(time)
get_high_time_subseconds(time: PvfsHighTimeWrapper) -> float:              get_high_time_subseconds(time)

Lock Operations:
---------------
lock_vfs(vfs: PvfsFileWrapper) -> None:                   PVFS_lock(vfs)
unlock_vfs(vfs: PvfsFileWrapper) -> None:                 PVFS_unlock(vfs)
"""

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

# Add PVFS_close function binding
_lib.pvfs_close.argtypes = [ctypes.c_int32]
_lib.pvfs_close.restype = ctypes.c_int32

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

# Add new file operation bindings
_lib.pvfs_fclose.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper)]
_lib.pvfs_fclose.restype = ctypes.c_int32

_lib.pvfs_flush.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper)]
_lib.pvfs_flush.restype = ctypes.c_int32

_lib.pvfs_fcreate.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p]
_lib.pvfs_fcreate.restype = ctypes.POINTER(PvfsFileHandleWrapper)

_lib.pvfs_fopen.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p]
_lib.pvfs_fopen.restype = ctypes.POINTER(PvfsFileHandleWrapper)

_lib.pvfs_delete_file.argtypes = [ctypes.POINTER(PvfsFileWrapper), ctypes.c_char_p]
_lib.pvfs_delete_file.restype = ctypes.c_int32

# Add low-level file operation bindings
_lib.pvfs_tell.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper)]
_lib.pvfs_tell.restype = ctypes.c_int64

_lib.pvfs_seek.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int64]
_lib.pvfs_seek.restype = ctypes.c_int64

_lib.pvfs_write.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
_lib.pvfs_write.restype = ctypes.c_int32

_lib.pvfs_read.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
_lib.pvfs_read.restype = ctypes.c_int32

# Add type-specific write function bindings
_lib.pvfs_write_uint8.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_uint8]
_lib.pvfs_write_uint8.restype = ctypes.c_int64

_lib.pvfs_write_sint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int16]
_lib.pvfs_write_sint16.restype = ctypes.c_int64

_lib.pvfs_write_uint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_uint16]
_lib.pvfs_write_uint16.restype = ctypes.c_int64

_lib.pvfs_write_sint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int32]
_lib.pvfs_write_sint32.restype = ctypes.c_int64

_lib.pvfs_write_uint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_uint32]
_lib.pvfs_write_uint32.restype = ctypes.c_int64

_lib.pvfs_write_sint64.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int64]
_lib.pvfs_write_sint64.restype = ctypes.c_int64

# Add type-specific read function bindings
_lib.pvfs_read_uint8.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint8)]
_lib.pvfs_read_uint8.restype = ctypes.c_int64

_lib.pvfs_read_sint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int16)]
_lib.pvfs_read_sint16.restype = ctypes.c_int64

_lib.pvfs_read_uint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint16)]
_lib.pvfs_read_uint16.restype = ctypes.c_int64

_lib.pvfs_read_sint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int32)]
_lib.pvfs_read_sint32.restype = ctypes.c_int64

_lib.pvfs_read_uint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint32)]
_lib.pvfs_read_uint32.restype = ctypes.c_int64

_lib.pvfs_read_sint64.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int64)]
_lib.pvfs_read_sint64.restype = ctypes.c_int64

# Add read/write operation bindings
_lib.pvfs_fread_uint8.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint8)]
_lib.pvfs_fread_uint8.restype = ctypes.c_int64

_lib.pvfs_fwrite_uint8.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_uint8]
_lib.pvfs_fwrite_uint8.restype = ctypes.c_int64

_lib.pvfs_fread_sint8.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int8)]
_lib.pvfs_fread_sint8.restype = ctypes.c_int64

_lib.pvfs_fwrite_sint8.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int8]
_lib.pvfs_fwrite_sint8.restype = ctypes.c_int64

_lib.pvfs_fread_uint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint16)]
_lib.pvfs_fread_uint16.restype = ctypes.c_int64

_lib.pvfs_fwrite_uint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_uint16]
_lib.pvfs_fwrite_uint16.restype = ctypes.c_int64

_lib.pvfs_fread_sint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int16)]
_lib.pvfs_fread_sint16.restype = ctypes.c_int64

_lib.pvfs_fwrite_sint16.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int16]
_lib.pvfs_fwrite_sint16.restype = ctypes.c_int64

_lib.pvfs_fread_uint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_uint32)]
_lib.pvfs_fread_uint32.restype = ctypes.c_int64

_lib.pvfs_fwrite_uint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_uint32]
_lib.pvfs_fwrite_uint32.restype = ctypes.c_int64

_lib.pvfs_fread_sint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int32)]
_lib.pvfs_fread_sint32.restype = ctypes.c_int64

_lib.pvfs_fwrite_sint32.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int32]
_lib.pvfs_fwrite_sint32.restype = ctypes.c_int64

_lib.pvfs_fread_sint64.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_int64)]
_lib.pvfs_fread_sint64.restype = ctypes.c_int64

_lib.pvfs_fwrite_sint64.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_int64]
_lib.pvfs_fwrite_sint64.restype = ctypes.c_int64

_lib.pvfs_fread_float.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_float)]
_lib.pvfs_fread_float.restype = ctypes.c_int64

_lib.pvfs_fwrite_float.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_float]
_lib.pvfs_fwrite_float.restype = ctypes.c_int64

_lib.pvfs_fread_double.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.POINTER(ctypes.c_double)]
_lib.pvfs_fread_double.restype = ctypes.c_int64

_lib.pvfs_fwrite_double.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper), ctypes.c_double]
_lib.pvfs_fwrite_double.restype = ctypes.c_int64

_lib.get_file_info.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper)]
_lib.get_file_info.restype  = PvfsFileEntryWrapper

_lib.pvfs_close_file_handle.argtypes = [ctypes.POINTER(PvfsFileHandleWrapper)]
_lib.pvfs_close_file_handle.restype = None

_lib.pvfs_close_vfs.argtypes = [ctypes.POINTER(PvfsFileWrapper)]
_lib.pvfs_close_vfs.restype = None

def pvfs_close(fd):
    """Close a file descriptor using PVFS_close.
    
    Args:
        fd (int): The file descriptor to close
        
    Returns:
        int: 0 on success, -1 on error
    """
    return _lib.pvfs_close(fd)

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
            try:
                # Don't print during cleanup as the Python runtime might be shutting down
                _lib.delete_string_vector(self._vec)
            except:
                pass  # Ignore all errors during cleanup
            finally:
                self._vec = None

    def __len__(self):
        """Get the number of strings in the vector."""
        if not self._vec:
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
            raise RuntimeError("String vector is not initialized")
        if not 0 <= index < len(self):
            raise IndexError("Index out of range")
        try:
            result = _lib.get_string_at(self._vec, index)
            if not result:
                raise RuntimeError(f"Failed to get string at index {index}")
            return result.decode('utf-8')
        except Exception as e:
            print(f"Python: Error getting string at index {index}: {e}")
            raise

    def __iter__(self):
        """Iterate over the strings in the vector."""
        if not self._vec:
            return
        try:
            for i in range(len(self)):
                yield self[i]
        except Exception as e:
            print(f"Python: Error iterating over StringVector: {e}")
            raise

class HighTime:

    def __init__(self, seconds: int | float, subseconds: float = None):
        if subseconds is None:
            if not isinstance(seconds, (int, float)):
                raise TypeError(f"Expected int or float, got {type(seconds).__name__}")
            total = float(seconds)
            secs = int(total)
            sub = total - secs
        else:
            if not isinstance(seconds, int):
                raise TypeError(f"When using two arguments, seconds must be int, got {type(seconds).__name__}")
            if not isinstance(subseconds, float):
                raise TypeError(f"When using two arguments, subseconds must be float, got {type(subseconds).__name__}")
            secs = seconds
            sub = subseconds

        self._time = _lib.create_high_time(secs, sub)
        if not self._time:
            raise RuntimeError("Failed to create HighTime")

    def __del__(self):
        if hasattr(self, '_time') and self._time:
            try:
                self._time = None
            except:
                pass

    @property
    def seconds(self):
        if not hasattr(self, '_time') or not self._time:
            return 0
        return _lib.get_high_time_seconds(self._time)

    @property
    def subseconds(self):
        if not hasattr(self, '_time') or not self._time:
            return 0.0
        return _lib.get_high_time_subseconds(self._time)

    def to_seconds(self):
        return float(self.seconds) + self.subseconds
    
    def print_local(self):
        timestamp = self.seconds + self.subseconds
        utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        local_time = utc_time.astimezone()
        subsec = int((timestamp % 1) * 1e2)
        print("Local Time:", local_time.strftime('%Y-%m-%d %H:%M:%S.')  + f"{subsec:02d}")

    def to_string_local(self) -> str:
        """Return a string representation of the HighTime in local timezone."""
        timestamp = self.seconds + self.subseconds
        utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        local_time = utc_time.astimezone()
        subsec = int((timestamp % 1) * 1e2)
        return local_time.strftime('%Y-%m-%d %H:%M:%S.') + f"{subsec:02d}"

    def to_string(self, precision: int = 9) -> str:
        """Return a string representation of the HighTime, e.g., '1746557173.798020601'."""
        # Combine parts and format subseconds to given precision
        subsec_str = f"{self.subseconds:.{precision}f}".split('.')[1].rstrip('0')
        if subsec_str:
            return f"{self.seconds}.{subsec_str}"
        else:
            return str(self.seconds)

    @classmethod
    def from_seconds(cls, total_seconds: float):
        secs = int(total_seconds)
        subsecs = float(total_seconds - secs)
        return cls(secs, subsecs)

    def __add__(self, other):
        if isinstance(other, (int, float)):
            return HighTime.from_seconds(self.to_seconds() + other)
        elif isinstance(other, HighTime):
            return HighTime.from_seconds(self.to_seconds() + other.to_seconds())
        return NotImplemented

    def __radd__(self, other):
        return self.__add__(other)

    def __lt__(self, other):
        if isinstance(other, (int, float)):
            return self.to_seconds() < other
        elif isinstance(other, HighTime):
            return self.to_seconds() < other.to_seconds()
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, (int, float)):
            return self.to_seconds() <= other
        elif isinstance(other, HighTime):
            return self.to_seconds() <= other.to_seconds()
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, (int, float)):
            return self.to_seconds() > other
        elif isinstance(other, HighTime):
            return self.to_seconds() > other.to_seconds()
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, (int, float)):
            return self.to_seconds() >= other
        elif isinstance(other, HighTime):
            return self.to_seconds() >= other.to_seconds()
        return NotImplemented

    def __eq__(self, other):
        if isinstance(other, (int, float)):
            return self.to_seconds() == other
        elif isinstance(other, HighTime):
            return self.to_seconds() == other.to_seconds()
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, (int, float)):
            return self.to_seconds() != other
        elif isinstance(other, HighTime):
            return self.to_seconds() != other.to_seconds()
        return NotImplemented

    def __repr__(self):
        return f"HighTime(seconds={self.seconds}, subseconds={self.subseconds})"



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

    def close(self):
        """Close the VFS instance and release all resources."""
        if hasattr(self, '_wrapper'):
            try:
                # First close any open file handles
                if hasattr(self, '_fd'):
                    _lib.pvfs_close_vfs(self._wrapper)
                    _lib.PVFS_close(self._fd)
                # Then delete the VFS instance
                _lib.delete_vfs(self._wrapper)
                self._wrapper = None
            except Exception as e:
                print(f"Warning: Failed to close VFS: {e}")

    def __del__(self):
        """Cleanup when the object is destroyed."""
        self.close()

    def fcreate(self, filename):
        """Create a new file in the VFS using PVFS_fcreate."""
        handle = _lib.pvfs_fcreate(self._wrapper, filename.encode('utf-8'))
        if not handle:
            raise RuntimeError(f"Failed to create file: {filename}")
        return PvfsFileHandle(handle, self)

    def fopen(self, filename):
        """Open a file in the VFS using PVFS_fopen."""
        handle = _lib.pvfs_fopen(self._wrapper, filename.encode('utf-8'))
        if not handle:
            raise RuntimeError(f"Failed to open file: {filename}")
        return PvfsFileHandle(handle, self)

    def delete_file(self, filename):
        """Delete a file from the VFS using PVFS_delete_file."""
        result = _lib.pvfs_delete_file(self._wrapper, filename.encode('utf-8'))
        if result < 0:
            raise RuntimeError(f"Failed to delete file: {result}")
        return result

class PvfsFileHandle:
    def __init__(self, handle, vfs=None):
        self.handle = handle
        self._vfs = vfs
        self._closed = False

    def __del__(self):
        """Clean up the file handle when the object is destroyed."""
        if not self._closed and hasattr(self, 'handle') and self.handle:
            try:
                # Don't try to access _lib during cleanup as it might be gone
                # Just mark the handle as closed
                self._closed = True
                self.handle = None
            except:
                pass  # Ignore all errors during cleanup

    def close(self):
        """Close the file handle."""
        if self._closed:
            return
            
        if not hasattr(self, 'handle') or not self.handle:
            self._closed = True
            return
            
        try:
            # First try to flush any pending changes
            if self._vfs:
                try:
                    _lib.pvfs_flush(self.handle)
                except Exception as e:
                    print(f"Warning: Failed to flush file handle: {e}")
            
            # Then close the handle
            try:
                _lib.pvfs_close_file_handle(self.handle)
                result = _lib.pvfs_fclose(self.handle)
                if result < 0:
                    print(f"Warning: Failed to close file handle: {result}")
            except Exception as e:
                print(f"Warning: Failed to close file handle: {e}")
        finally:
            self._closed = True
            self.handle = None

    def read(self, size):
        """Read data from the file using PVFS_read."""
        if not self.handle:
            raise RuntimeError("File handle is closed")
        
        # Create a buffer to hold the data
        buffer = (ctypes.c_uint8 * size)()
        result = _lib.pvfs_read(self.handle, buffer, size)
        if result < 0:
            raise RuntimeError(f"Failed to read data: {result}")
        return bytes(buffer[:result])

    def tell(self):
        """Get the current file position using PVFS_tell."""
        if not self.handle:
            return -2  # PVFS_ARG_NULL
        return _lib.pvfs_tell(self.handle)

    def seek(self, offset):
        """Set the file position using PVFS_seek."""
        if not self.handle:
            return -2  # PVFS_ARG_NULL
        return _lib.pvfs_seek(self.handle, offset)

    def write(self, buffer, size):
        """Write data to the file using PVFS_write."""
        if not self.handle:
            return -2  # PVFS_ARG_NULL
        return _lib.pvfs_write(self.handle, buffer, size)

    def read_index_file_header(self):
        header = PvfsIndexHeaderWrapper()
        result = _lib.read_index_file_header(self.handle, ctypes.byref(header))
        if result < 0:
            raise RuntimeError(f"Failed to read index file header: {result}")
        return header

    def write_index_file_header(self, header):
        result = _lib.write_index_file_header(self.handle, ctypes.byref(header))
        if result < 0:
            raise RuntimeError(f"Failed to write index file header: {result}")
        return result

    def flush(self):
        """Flush any pending changes to disk using PVFS_flush."""
        if not self.handle:
            return -2  # PVFS_ARG_NULL
        result = _lib.pvfs_flush(self.handle)
        if result < 0:
            raise RuntimeError(f"Failed to flush file: {result}")
        return result

    # Type-specific write methods
    def write_uint8(self, value: int) -> int:
        """Write an unsigned 8-bit integer."""
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("Value must be an integer between 0 and 255")
        return _lib.pvfs_write_uint8(self.handle, value)
    
    def write_int8(self, value: int) -> int:
        """Write a signed 8-bit integer."""
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("Value must be an integer between 0 and 255")
        return _lib.pvfs_write_sint8(self.handle, value)

    def write_int16(self, value: int) -> int:
        """Write a signed 16-bit integer."""
        if not isinstance(value, int) or not -32768 <= value <= 32767:
            raise ValueError("Value must be an integer between -32768 and 32767")
        return _lib.pvfs_write_sint16(self.handle, value)

    def write_uint16(self, value: int) -> int:
        """Write an unsigned 16-bit integer."""
        if not isinstance(value, int) or not 0 <= value <= 65535:
            raise ValueError("Value must be an integer between 0 and 65535")
        return _lib.pvfs_write_uint16(self.handle, value)

    def write_int32(self, value: int) -> int:
        """Write a signed 32-bit integer."""
        if not isinstance(value, int) or not -2147483648 <= value <= 2147483647:
            raise ValueError("Value must be an integer between -2147483648 and 2147483647")
        return _lib.pvfs_write_sint32(self.handle, value)

    def write_uint32(self, value: int) -> int:
        """Write an unsigned 32-bit integer."""
        if not isinstance(value, int) or not 0 <= value <= 4294967295:
            raise ValueError("Value must be an integer between 0 and 4294967295")
        return _lib.pvfs_write_uint32(self.handle, value)

    def write_int64(self, value: int) -> int:
        """Write a signed 64-bit integer."""
        if not isinstance(value, int):
            raise ValueError("Value must be an integer")
        return _lib.pvfs_write_sint64(self.handle, value)

    def write_uint64(self, value: int) -> int:
        """Write an unsigned 64-bit integer."""
        if not isinstance(value, int) or value < 0:
            raise ValueError("Value must be a non-negative integer")
        return _lib.pvfs_write_uint64(self.handle, value)

    def write_float(self, value: float) -> int:
        """Write a 32-bit floating point number."""
        if not isinstance(value, (int, float)):
            raise ValueError("Value must be a number")
        return _lib.pvfs_write_float(self.handle, float(value))

    def write_double(self, value: float) -> int:
        """Write a 64-bit floating point number."""
        if not isinstance(value, (int, float)):
            raise ValueError("Value must be a number")
        return _lib.pvfs_write_double(self.handle, float(value))

    # Type-specific read methods
    def read_uint8(self) -> int:
        """Read an unsigned 8-bit integer."""
        value = ctypes.c_uint8()
        result = _lib.pvfs_read_uint8(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read uint8: {result}")
        return value.value
    
    def read_int8(self) -> int:
        """Read a signed 8-bit integer."""
        value = ctypes.c_int8()
        result = _lib.pvfs_read_sint8(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int8: {result}")
        return value.value

    def read_int16(self) -> int:
        """Read a signed 16-bit integer."""
        value = ctypes.c_int16()
        result = _lib.pvfs_read_sint16(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int16: {result}")
        return value.value

    def read_uint16(self) -> int:
        """Read an unsigned 16-bit integer."""
        value = ctypes.c_uint16()
        result = _lib.pvfs_read_uint16(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read uint16: {result}")
        return value.value

    def read_int32(self) -> int:
        """Read a signed 32-bit integer."""
        value = ctypes.c_int32()
        result = _lib.pvfs_read_sint32(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int32: {result}")
        return value.value

    def read_uint32(self) -> int:
        """Read an unsigned 32-bit integer."""
        value = ctypes.c_uint32()
        result = _lib.pvfs_read_uint32(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read uint32: {result}")
        return value.value

    def read_int64(self) -> int:
        """Read a signed 64-bit integer."""
        value = ctypes.c_int64()
        result = _lib.pvfs_read_sint64(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int64: {result}")
        return value.value

    def fwrite_uint8(self, value: int) -> int:
        """Write an unsigned 8-bit integer to the file."""
        if not 0 <= value <= 255:
            raise ValueError("Value must be between 0 and 255")
        return _lib.pvfs_fwrite_uint8(self.handle, value)

    def fwrite_int8(self, value: int) -> int:
        """Write a signed 8-bit integer to the file."""
        if not -128 <= value <= 127:
            raise ValueError("Value must be between -128 and 127")
        return _lib.pvfs_fwrite_sint8(self.handle, value)

    def fwrite_uint16(self, value: int) -> int:
        """Write an unsigned 16-bit integer to the file."""
        if not 0 <= value <= 65535:
            raise ValueError("Value must be between 0 and 65535")
        return _lib.pvfs_fwrite_uint16(self.handle, value)

    def fwrite_int16(self, value: int) -> int:
        """Write a signed 16-bit integer to the file."""
        if not -32768 <= value <= 32767:
            raise ValueError("Value must be between -32768 and 32767")
        return _lib.pvfs_fwrite_sint16(self.handle, value)

    def fwrite_uint32(self, value: int) -> int:
        """Write an unsigned 32-bit integer to the file."""
        if not 0 <= value <= 4294967295:
            raise ValueError("Value must be between 0 and 4294967295")
        return _lib.pvfs_fwrite_uint32(self.handle, value)

    def fwrite_int32(self, value: int) -> int:
        """Write a signed 32-bit integer to the file."""
        if not -2147483648 <= value <= 2147483647:
            raise ValueError("Value must be between -2147483648 and 2147483647")
        return _lib.pvfs_fwrite_sint32(self.handle, value)

    def fwrite_int64(self, value: int) -> int:
        """Write a signed 64-bit integer to the file."""
        return _lib.pvfs_fwrite_sint64(self.handle, value)

    def fwrite_uint64(self, value: int) -> int:
        """Write an unsigned 64-bit integer to the file."""
        if value < 0:
            raise ValueError("Value must be non-negative")
        return _lib.pvfs_fwrite_uint64(self.handle, value)

    def fwrite_float(self, value: float) -> int:
        """Write a 32-bit float to the file."""
        return _lib.pvfs_fwrite_float(self.handle, value)

    def fwrite_double(self, value: float) -> int:
        """Write a 64-bit double to the file."""
        return _lib.pvfs_fwrite_double(self.handle, value)

    def fread_uint8(self) -> int:
        """Read an unsigned 8-bit integer from the file."""
        value = ctypes.c_uint8()
        result = _lib.pvfs_fread_uint8(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read uint8: {result}")
        return value.value

    def fread_int8(self) -> int:
        """Read a signed 8-bit integer from the file."""
        value = ctypes.c_int8()
        result = _lib.pvfs_fread_sint8(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int8: {result}")
        return value.value

    def fread_uint16(self) -> int:
        """Read an unsigned 16-bit integer from the file."""
        value = ctypes.c_uint16()
        result = _lib.pvfs_fread_uint16(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read uint16: {result}")
        return value.value

    def fread_int16(self) -> int:
        """Read a signed 16-bit integer from the file."""
        value = ctypes.c_int16()
        result = _lib.pvfs_fread_sint16(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int16: {result}")
        return value.value

    def fread_uint32(self) -> int:
        """Read an unsigned 32-bit integer from the file."""
        value = ctypes.c_uint32()
        result = _lib.pvfs_fread_uint32(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read uint32: {result}")
        return value.value

    def fread_int32(self) -> int:
        """Read a signed 32-bit integer from the file."""
        value = ctypes.c_int32()
        result = _lib.pvfs_fread_sint32(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int32: {result}")
        return value.value

    def fread_int64(self) -> int:
        """Read a signed 64-bit integer from the file."""
        value = ctypes.c_int64()
        result = _lib.pvfs_fread_sint64(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read int64: {result}")
        return value.value

    def fread_float(self) -> float:
        """Read a 32-bit float from the file."""
        value = ctypes.c_float()
        result = _lib.pvfs_fread_float(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read float: {result}")
        return value.value

    def fread_double(self) -> float:
        """Read a 64-bit double from the file."""
        value = ctypes.c_double()
        result = _lib.pvfs_fread_double(self.handle, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"Failed to read double: {result}")
        return value.value
    
    def get_file_info(self):
        """Retrieve the PvfsFileEntry (info) from the underlying C++ handle."""
        # Call the new function, which returns a PvfsFileEntryWrapper by value
        info_struct = _lib.get_file_info(self.handle)
        return info_struct

def create_vfs(block_size):
    """Create a new VFS with the specified block size."""
    return PvfsFile(block_size) 