
# Python Wrapper for Pvfs.h using cppyy Python-C++ binding.
 


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

    def createVFS(self, block_size):
        try:
            result = cppyy.gbl.pvfs.createVFS(block_size) 
            return result
        except MemoryError as e:
            print(f"VFS Memory allocation failed: {e}")
            return None

    def create_PVFS_file_structure(self, block_size ):
        try:
            result = cppyy.gbl.pvfs.create_PVFS_file_structure(block_size) 
            return result
        except Exception as e:
            print(f"create_PVFS_file_structure failed{e}")
            return None
        
    
    def PVFS_file_set_blockSize(self, vfs, block_size ):
        try:
            result = cppyy.gbl.pvfs.PVFS_file_set_blockSize(vfs, block_size) 
            return result
        except Exception as e:
            print(f"PVFS_file_set_blockSize failed {e}")
            return None
        

    def create_PVFS_block(self, vfs):
        try:
            result = cppyy.gbl.pvfs.create_PVFS_block(vfs) 
            return result
        except Exception as e:
            print(f"create_PVFS_block failed {e}")
            return None
    
    def PVFS_read_block(self, fd, address, block) :
        try:
            result = cppyy.gbl.pvfs.PVFS_read_block(fd, address, block) 
            return result
        except Exception as e:
            print(f"PVFS_read_block failed {e}")
            return None
        
    def PVFS_write_block(self, fd, address, block) :
        try:
            result = cppyy.gbl.pvfs.PVFS_write_block(fd, address, block) 
            return result
        except Exception as e:
            print(f"PVFS_write_block failed {e}")
            return None

    def create_PVFS_block_data(self, vfs) :
        try:
            result = cppyy.gbl.pvfs.create_PVFS_block_data(vfs) 
            return result
        except Exception as e:
            print(f"create_PVFS_block_data failed {e}")
            return None
    
    def create_PVFS_block_tree(self, vfs) :
        try:
            result = cppyy.gbl.pvfs.create_PVFS_block_tree(vfs) 
            return result
        except Exception as e:
            print(f"create_PVFS_block_tree failed {e}")
            return None
        
    def create_PVFS_block_file(self, vfs) :
        try:
            result = cppyy.gbl.pvfs.create_PVFS_block_file(vfs) 
            return result
        except Exception as e:
            print(f"create_PVFS_block_file failed {e}")
            return None
    
    def PVFS_cast_block_to_data(self, block, block_data) :
        try:
            result = cppyy.gbl.pvfs.PVFS_cast_block_to_data(block, block_data) 
            return result
        except Exception as e:
            print(f"PVFS_cast_block_to_data failed {e}")
            return None
    
    def PVFS_cast_block_to_tree(self, block, block_tree) :
        try:
            result = cppyy.gbl.pvfs.PVFS_cast_block_to_tree(block, block_tree) 
            return result
        except Exception as e:
            print(f"PVFS_cast_block_to_tree failed {e}")
            return None
    
    def PVFS_cast_block_to_file(self, block, block_file) :
        try:
            result = cppyy.gbl.pvfs.PVFS_cast_block_to_file(block, block_file) 
            return result
        except Exception as e:
            print(f"PVFS_cast_block_to_file failed {e}")
            return None
    
    def PVFS_cast_data_to_block(self, block_data, block) :
        try:
            result = cppyy.gbl.pvfs.PVFS_cast_data_to_block(block_data, block) 
            return result
        except Exception as e:
            print(f"PVFS_cast_data_to_block failed {e}")
            return None
    
    def PVFS_cast_tree_to_block(self, block_tree, block) :
        try:
            result = cppyy.gbl.pvfs.PVFS_cast_tree_to_block(block_tree, block) 
            return result
        except Exception as e:
            print(f"PVFS_cast_tree_to_block failed {e}")
            return None
    
    def PVFS_cast_file_to_block(self, block_file, block) :
        try:
            result = cppyy.gbl.pvfs.PVFS_cast_file_to_block(block_file, block) 
            return result
        except Exception as e:
            print(f"PVFS_cast_file_to_block failed {e}")
            return None
        
    def PVFS_read_block_file (self, vfs, address, block_file) :
        try:
            result = cppyy.gbl.pvfs.PVFS_read_block_file(vfs, address, block_file) 
            return result
        except Exception as e:
            print(f"PVFS_read_block_file failed {e}")
            return None
    
    def PVFS_read_block_tree (self, vfs, address, block_tree) :
        try:
            result = cppyy.gbl.pvfs.PVFS_read_block_tree(vfs, address, block_tree) 
            return result
        except Exception as e:
            print(f"PVFS_read_block_tree failed {e}")
            return None
        
    def PVFS_read_block_data (self, vfs, address, block_data) :
        try:
            result = cppyy.gbl.pvfs.PVFS_read_block_data(vfs, address, block_data) 
            return result
        except Exception as e:
            print(f"PVFS_read_block_data failed {e}")
            return None
    
    def PVFS_write_block_file (self, vfs, address, block_file) :
        try:
            result = cppyy.gbl.pvfs.PVFS_write_block_file(vfs, address, block_file) 
            return result
        except Exception as e:
            print(f"PVFS_write_block_file failed {e}")
            return None
        
    def PVFS_write_block_tree (self, vfs, address, block_tree) :
        try:
            result = cppyy.gbl.pvfs.PVFS_write_block_tree(vfs, address, block_tree) 
            return result
        except Exception as e:
            print(f"PVFS_write_block_tree failed {e}")
            return None
    
    def PVFS_write_block_data (self, vfs, address, block_data) :
        try:
            result = cppyy.gbl.pvfs.PVFS_write_block_data(vfs, address, block_data) 
            return result
        except Exception as e:
            print(f"PVFS_write_block_data failed {e}")
            return None

    

# # Create an instance of the Pvfs class
pvfs_instance = Pvfs()
vfs = pvfs_instance.createVFS(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)

vfs = pvfs_instance.create_PVFS_file_structure(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)

#doesn't return anything
result = pvfs_instance.PVFS_file_set_blockSize(vfs,Pvfs.PVFS_DEFAULT_BLOCK_SIZE)

block = pvfs_instance.create_PVFS_block(vfs) #returns an instance of create_PVFS_block
if block:
    print("SUCCESS")



file_descriptor = vfs.fd
print("!!", file_descriptor)
read_block = pvfs_instance.PVFS_read_block(file_descriptor, 0, block)


write_block = pvfs_instance.PVFS_write_block(file_descriptor, 0, block)


block_data = pvfs_instance.create_PVFS_block_data(vfs)

block_tree = pvfs_instance.create_PVFS_block_tree(vfs)

block_file = pvfs_instance.create_PVFS_block_file(vfs)

pvfs_instance.PVFS_cast_block_to_data(block, block_data)
pvfs_instance.PVFS_cast_block_to_tree(block, block_tree)
pvfs_instance.PVFS_cast_block_to_file(block, block_file)
pvfs_instance.PVFS_cast_data_to_block(block_data, block)
pvfs_instance.PVFS_cast_tree_to_block(block_tree, block)
pvfs_instance.PVFS_cast_file_to_block(block_file, block)

pvfs_instance.PVFS_read_block_file(vfs, 0, block_file)
pvfs_instance.PVFS_read_block_tree(vfs, 0, block_tree)
pvfs_instance.PVFS_read_block_data(vfs, 0, block_data)
pvfs_instance.PVFS_write_block_file(vfs, 0, block_file)
pvfs_instance.PVFS_write_block_tree(vfs, 0, block_tree)
pvfs_instance.PVFS_write_block_data(vfs, 0, block_data)









#result = pvfs_instance.PVFS_file_set_blockSize(result)

# result = pvfs_instance.create_PVFS_file_structure(Pvfs.PVFS_DEFAULT_BLOCK_SIZE)
# print("HELLO", result)
# if result:
#     print("create_PVFS_file_structure test passed")
# else:
#     print("create_PVFS_file_structure failed")

# # Access inner classes using the class attributes of the Pvfs instance
# HighTime = pvfs_instance.HighTime
# PvfsIndexEntry = pvfs_instance.PvfsIndexEntry

# # Create instances of HighTime and PvfsIndexEntry
# start_time = HighTime(10, 0.5)
# end_time = HighTime(20, 0.75)
# index_entry = PvfsIndexEntry(start_time, end_time, myLocation=100, dataLocation=200)

# print(index_entry.StartTime.seconds)  # Output: 10
# print(index_entry.endTime.subSeconds)  # Output: 0.75






