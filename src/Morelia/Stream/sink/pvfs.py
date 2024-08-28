
# Python Wrapper for Pvfs.h


__author__      = 'Sree Kondi'
__maintainer__  = 'Sree Kondi'
__credits__     = ['Sree Kondi', 'James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Sree Kondi'
__email__       = 'sales@pinnaclet.com'

from threading import Lock
import cppyy
from typing import Optional, List, Union
import os


class Pvfs():
    path = os.path.dirname(os.path.abspath(__file__))
    pvfs_h_path = os.path.join(path, 'Pvfs.h')
    cppyy.include(pvfs_h_path)
    libtest_h_path = os.path.join(path, 'libtest.dll')
    cppyy.load_library(libtest_h_path)
    print("Library loaded successfully")
    file_path = '/mnt/c/Users/skondi/Desktop/test/test.pvfs'

    PVFS_VERSION_MAJOR = 2
    PVFS_VERSION_MINOR = 0
    PVFS_VERSION_REVISION = 2

    SIZE_UINT8_T = 1     # uint8_t is 1 byte
    SIZE_INT32_T = 4     # int32_t is 4 bytes
    SIZE_INT64_T = 8     # int64_t is 8 bytes

    PVFS_BLOCK_HEADER_SIZE = (
        SIZE_UINT8_T +    # sizeof(uint8_t)
        3 * SIZE_INT64_T +  # 3 * sizeof(int64_t)
        SIZE_INT32_T     # sizeof(int32_t)
    )

    PVFS_HEADER_SIZE = 0x0400
    PVFS_DEFAULT_BLOCK_SIZE = 0x4000 - PVFS_BLOCK_HEADER_SIZE # 16 k default block size
    PVFS_MAX_FILENAME_LENGTH = 0x0100 # Max length of a filename.
    PVFS_MAX_HANDLES = 0xFF # Maximum number of file pointers allowed into the virtual file.
    PVFS_TIMESTAMP_SIZE = 44

    PVFS_BLOCK_TYPE_UNKNOWN = 0
    PVFS_BLOCK_TYPE_DATA = 1
    PVFS_BLOCK_TYPE_TREE = 2
    PVFS_BLOCK_TYPE_FILE = 3
    PVFS_BLOCK_TYPE_EOF = 0xFF

    PVFS_INVALID_LOCATION = -1
    PVFS_INVALID_FD = -1

    PVFS_OK = 0
    PVFS_ERROR = -1
    PVFS_ARG_NULL = -2
    PVFS_EOF = -3
    PVFS_FILE_NOT_OPENED = -4
    PVFS_CORRUPTION_DETECTED = -5

    PVFS_DIRTY = 0
    PVFS_CLEAN = 1

    PVFS_INDEX_DATA_FILE_MAGIC_NUMBER = 0XFF01FF01
    PVFS_INDEX_DATA_FILE_VERSION = 2
    PVFS_INDEX_EXTENSION = ".index"
    PVFS_DATA_EXTENSION = ".idat"
    PVFS_INDEX_HEADER_SIZE = 0x4000

    def __init__(self):
        pass


    @staticmethod
    def p_write(fd: int, buf: Union[bytes, bytearray]) -> int:
        try:
            return os.write(fd, buf)
        except OSError as e:
            print(f"Error writing to file descriptor {fd}: {e}")
            return -1
    
    @staticmethod
    def pvfs_write_uint8(fd: int, value: int) -> int:
        if not (0 <= value <= 255):
            raise ValueError("Value must be between 0 and 255 inclusive.")
        
        # Convert the integer to a single byte
        byte_value = value.to_bytes(1, byteorder='little', signed=False)
        
        return Pvfs.p_write(fd, byte_value)
    
        
    @staticmethod
    def pvfs_write_uint16(fd: int, value: int) -> int:
        if not (0 <= value <= 0xFFFF):
            raise ValueError("Value must be between 0 and 65535 inclusive.")
        
        # Convert the value to a 2-byte (unsigned 16-bit) representation
        byte_value = value.to_bytes(2, byteorder='little', signed=False)
        
        # Write the bytes to the file descriptor using p_write
        return Pvfs.p_write(fd, byte_value)


    @staticmethod
    def pvfs_write_sint32(fd: int, value: int) -> int:
        if not (-0x80000000 <= value <= 0x7FFFFFFF):
            raise ValueError("Value must be between -2147483648 and 2147483647 inclusive.")
        
        # Convert the value to a 4-byte (signed 32-bit) representation
        byte_value = value.to_bytes(4, byteorder='little', signed=True)
        
        # Write the bytes to the file descriptor using p_write
        return Pvfs.p_write(fd, byte_value)


    @staticmethod
    def pvfs_write_sint64(fd: int, value: int) -> int:
        if not (-0x8000000000000000 <= value <= 0x7FFFFFFFFFFFFFFF):
            raise ValueError("Value must be between -9223372036854775808 and 9223372036854775807 inclusive.")

        # Convert the value to an 8-byte (signed 64-bit) representation
        byte_value = value.to_bytes(8, byteorder='little', signed=True)

        # Write the bytes to the file descriptor using p_write
        return Pvfs.p_write(fd, byte_value, 8)
        

    def createVFS(self, block_size):
        try:
            result = cppyy.gbl.pvfs.PVFS_create(self.file_path) 
        except MemoryError as e:
            print(f"VFS Memory allocation failed: {e}")
            return None
        
    def createBlock(self, BlockType, size):
        try:
            # Create an instance of BlockType
            block = BlockType()
            # Call a method to clear and initialize the block
            err = self.clearBlock(block, size)
            if err != Pvfs.PVFS_OK:
                return None
            return block
        except Exception as e:
            print(f"Block Memory allocation failed: {e}")
            return None
    

    def clearBlock(self, block, size):
        if block is None:
            return Pvfs.PVFS_ARG_NULL

        # Reset block attributes
        block.next = Pvfs.PVFS_INVALID_LOCATION
        block.prev = Pvfs.PVFS_INVALID_LOCATION
        block.count = 0
        
        # Clear the data and resize it to the specified size, filling with zeros
        block.data = bytearray(size)  # Allocate space and set all values to zero
        return Pvfs.PVFS_OK
        
    
    def create_PVFS_block(self, vfs) :
        if vfs is None:
            return None
        
        # Create a PvfsBlock instance with a block size
        block = self.createBlock(Pvfs.PvfsBlock, vfs.blockSize)
        if block is None:
            return None

        # Initialize block attributes
        block.type = Pvfs.PVFS_BLOCK_TYPE_UNKNOWN
        block.next = Pvfs.PVFS_INVALID_LOCATION
        block.prev = Pvfs.PVFS_INVALID_LOCATION
        block.self_value = Pvfs.PVFS_INVALID_LOCATION
        block.count = 0
        block.size = vfs.blockSize
        print("&&&", block)
        return block

    print("LINE")   
    def create_PVFS_block_file (self, vfs) :
        block = self.PvfsBlockFile() 
        if block is None:
            return None
        block.type = Pvfs.PVFS_BLOCK_TYPE_FILE
        block.prev = Pvfs.PVFS_INVALID_LOCATION
        block.self_value = Pvfs.PVFS_INVALID_LOCATION
        block.next = Pvfs.PVFS_INVALID_LOCATION
        block.count = 0
        block.maxFiles = vfs.file


    def create_PVFS_file_structure(self, block_size ):
        vfs = self.createVFS(block_size)
        if vfs is None:
            return None

        # Initialize attributes
        vfs.fd = Pvfs.PVFS_INVALID_FD
        vfs.tableLoc = Pvfs.PVFS_HEADER_SIZE
        vfs.fileBlock = None
        vfs.blockSize = Pvfs.PVFS_DEFAULT_BLOCK_SIZE
        vfs.fileMaxCount = 0
        vfs.treeMaxCount = 0
        vfs.block = None
        vfs.fileBlock = None
        vfs.nextBlock = Pvfs.PVFS_HEADER_SIZE

        vfs.fileHandles = [None] * Pvfs.PVFS_MAX_HANDLES

        vfs.fileMaxCount = (block_size) // (
            Pvfs.PVFS_MAX_FILENAME_LENGTH + 2 * Pvfs.SIZE_INT64_T
        )
        vfs.treeMaxCount = (
            (block_size - 2 * Pvfs.SIZE_INT64_T) // (2 * Pvfs.SIZE_INT64_T)
        )
        print("***")
        # Create and assign block objects
        vfs.block = self.create_PVFS_block(vfs)
        # vfs.fileBlock = self.create_PVFS_block_file(vfs)
        # vfs.fileBlockTemp = self.create_PVFS_block_file(vfs)
        # vfs.treeBlockTemp = self.create_PVFS_block_tree(vfs)
        # vfs.dataBlockTemp = self.create_PVFS_block_data(vfs)

        return vfs
    



    # Define inner classes
    class HighTime:
        def __init__(self, seconds: int = 0, subSeconds: float = 0.0):
            self.seconds = seconds
            self.subSeconds = subSeconds

    class PvfsIndexEntry:
        def __init__(self, StartTime, endTime, myLocation=0, dataLocation=0):
            self.StartTime = StartTime
            self.endTime = endTime
            self.myLocation = myLocation
            self.dataLocation = dataLocation

    # this needs change
    class PvfsFileEntry:
        def __init__(self, start_block=0, size=0, filename=""):
            self.start_block = start_block
            self.size = size
            self.filename = filename[:Pvfs.PVFS_MAX_FILENAME_LENGTH].encode('utf-8')

    class PvfsLocationMap:
        def __init__(self, address=0, blockLoc=0):
            self.address = address
            self.blockLoc = blockLoc

    class PvfsFileVersion:
        def __init__(self, major=0, minor=0, revision=0):
            self.major = major
            self.minor = minor
            self.revision = revision

    class PvfsBlock:
        def __init__(self, type=0, prev=0, self_value=0, next=0, count=0, size=0, data=b''):
            self.type = type
            self.prev = prev
            self.self_value = self_value
            self.next = next
            self.count = count
            self.data = b''
            self.size = size

    class PvfsBlockData:
        def __init__(self, type=0, prev=0, self_value=0, next=0, count=0, tree=0, maxcount=0, data=b''):
            self.type = type
            self.prev = prev
            self.self_value = self_value
            self.next = next
            self.count = count
            self.tree = tree
            self.data = b''
            self.maxcount = maxcount

    class PvfsBlockTree:
        def __init__(self, self_value=0, type=0, prev=0, next=0, count=0, up=0, maxMappings=0, mappings=[]):
            self.type = type
            self.prev = prev
            self.self_value = self_value
            self.next = next
            self.count = count
            self.up = up
            self.maxMappings = maxMappings
            #self.mappings = mappings(Pvfs.PvfsLocationMap)
            #self.mappings = [Pvfs.PvfsLocationMap(address, blockLoc) for address, blockLoc in mappings] if mappings is not None else []
            self.mappings = mappings

    class PvfsBlockFile:
        def __init__(self, self_value=0, type=0, prev=0, next=0, count=0, maxFiles=0):
            self.type = type
            self.prev = prev
            self.self_value = self_value
            self.next = next
            self.count = count
            self.maxFiles = maxFiles
            self.files = Pvfs.PvfsFileEntry()

    class PvfsFileHandle:
        def __init__(self, vfs, info, block, data, currentAddress=0, dirty=0, tableBlock=0, tableIndex=0, error=0):
            self.vfs = vfs
            self.info = info
            self.block = block
            self.currentAddress = currentAddress
            self.dirty = dirty
            self.data = data
            self.tableBlock = tableBlock
            self.tableIndex = tableIndex
            self.error = error

    class PvfsFile:
        def __init__(self, fd=-1, blockSize=0, tableLoc=0, nextBlock=0, fileMaxCount=0, treeMaxCount=0):
            self.fd = fd
            self.version = Pvfs.PvfsFileVersion()
            self.blockSize = blockSize
            self.tableLoc = tableLoc
            self.nextBlock = nextBlock
            self.block: Optional[Pvfs.PvfsBlock] = None
            self.fileBlock: Optional[Pvfs.PvfsBlockFile] = None
            self.fileHandles: List[Optional[Pvfs.PvfsFileHandle]] = [None] * (Pvfs.PVFS_MAX_HANDLES)
            self.fileMaxCount = fileMaxCount
            self.treeMaxCount = treeMaxCount
            self.fileBlockTemp: Optional[Pvfs.PvfsBlockFile] = None
            self.treeBlockTemp: Optional[Pvfs.PvfsBlockTree] = None
            self.dataBlockTemp: Optional[Pvfs.PvfsBlockData] = None
            self.lock = Lock()

    class PvfsIndexHeader:
        def __init__(self, datarate, startTime, endTime, timeStampIntervalSeconds, magicNumber=0XFF01FF01, version=2, dataType=0):
            self.magicNumber = magicNumber
            self.version = version
            self.dataType = dataType
            self.datarate = datarate
            self.startTime = startTime
            self.endTime = endTime
            self.timeStampIntervalSeconds = timeStampIntervalSeconds

    

# # Create an instance of the Pvfs class
pvfs_instance = Pvfs()
result = pvfs_instance.createVFS(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)
print("HELLO", result)
if result:
    print("createVFS test passed")
else:
    print("createVFS failed")


result = pvfs_instance.create_PVFS_file_structure(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)
print("HELLO", result)
if result:
    print("create_PVFS_file_structure test passed")
else:
    print("create_PVFS_file_structure failed")

# # Access inner classes using the class attributes of the Pvfs instance
# HighTime = pvfs_instance.HighTime
# PvfsIndexEntry = pvfs_instance.PvfsIndexEntry

# # Create instances of HighTime and PvfsIndexEntry
# start_time = HighTime(10, 0.5)
# end_time = HighTime(20, 0.75)
# index_entry = PvfsIndexEntry(start_time, end_time, myLocation=100, dataLocation=200)

# print(index_entry.StartTime.seconds)  # Output: 10
# print(index_entry.endTime.subSeconds)  # Output: 0.75





