# Python Wrapper for Pvfs.h


__author__      = 'Sree Kondi'
__maintainer__  = 'Sree Kondi'
__credits__     = ['Sree Kondi','James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Sree Kondi'
__email__       = 'sales@pinnaclet.com'

from threading import Thread, Lock
import cppyy
import os

class Pvfs:
    def __init__(self):

        self. PVFS_VERSION_MAJOR    = 2
        self.PVFS_VERSION_MINOR     = 0
        self.PVFS_VERSION_REVISION  = 2

        SIZE_UINT8_T = 1     # uint8_t is 1 byte
        SIZE_INT32_T = 4     # int32_t is 4 bytes
        SIZE_INT64_T = 8     # int64_t is 8 bytes
        

        self.PVFS_BLOCK_HEADER_SIZE = (
            SIZE_UINT8_T +    # sizeof(uint8_t)
            3 * SIZE_INT64_T +  # 3 * sizeof(int64_t)
            SIZE_INT32_T     # sizeof(int32_t)
        )

        self.PVFS_HEADER_SIZE		        =	0x0400
        self.PVFS_DEFAULT_BLOCK_SIZE		=   0x4000 - self.PVFS_BLOCK_HEADER_SIZE #16 k default block size
        self.PVFS_MAX_FILENAME_LENGTH       =	0x0100		# Max length of a filename.
        self.PVFS_MAX_HANDLES	            =   0xFF			# Maximum number of file pointers allowed into the virutal file.  (Mostly laziness, should be a data store...)
        self.PVFS_TIMESTAMP_SIZE            =   44

        self.PVFS_BLOCK_TYPE_UNKNOWN	    =	0
        self.PVFS_BLOCK_TYPE_DATA	        =	1 
        self.PVFS_BLOCK_TYPE_TREE	        =	2
        self.PVFS_BLOCK_TYPE_FILE	        =	3
        self.PVFS_BLOCK_TYPE_EOF	        =	0xFF

        self.PVFS_INVALID_LOCATION          =   -1
        self.PVFS_INVALID_FD			    =	-1

        self.PVFS_OK			            =   0
        self.PVFS_ERROR		                =   -1
        self.PVFS_ARG_NULL		            =	-2			#!< A null value was passed as an argument.
        self.PVFS_EOF	                    =	-3			#!< End of file, used for read and getc.
        self.PVFS_FILE_NOT_OPENED	        =	-4			#!< When trying to add/extract a file this error can occur.
        self.PVFS_CORRUPTION_DETECTED       =	-5

        self.PVFS_DIRTY		                =	0
        self.PVFS_CLEAN		                =	1

        self.PVFS_INDEX_DATA_FILE_MAGIC_NUMBER = 0XFF01FF01
        self.PVFS_INDEX_DATA_FILE_VERSION      = 2
        self.PVFS_INDEX_EXTENSION              = ".index"
        self.PVFS_DATA_EXTENSION               = ".idat"
        self.PVFS_INDEX_HEADER_SIZE            = 0x4000

    
        class PvfsFileEntry:
            def __init__(self, start_block = 0, size = 0, filename = 0):
                self.start_block = start_block
                self.size = size
                self.filename = filename


        class PvfsLocationMap :
            def __init__(self, address = 0, blockLoc = 0) :
                self.address = address
                self.blockLoc = blockLoc
         
        class PvfsFileVersion :
            def __init__(self, major = 0, minor = 0, revision = 0) :
                self.major = major
                self.minor = minor
                self.revision = revision
        
        class PvfsBlock :
            def __init__(self, type=0, prev=0, self_value=0, next=0, count=0, size=0, data=b'') :
                self.type = type
                self.prev = prev 
                self.self_value = self_value 
                self.next = next
                self.count = count
                self.data = data
                self.size = size
                

        class PvfsBlockData :
            def __init__(self, type=0, prev=0, self_value=0, next=0, count=0, tree=0, maxcount=0, data=b'') :
                self.type = type
                self.prev = prev
                self.self_value = self_value
                self.next = next
                self.count = count
                self.tree = tree
                self.data = data
                self.maxcount = maxcount

        # ---------------------------------------
        class PvfsBlockTree :
            def __init__(self, self_value=0, type = 0, prev = 0, next = 0, count = 0, up = 0, maxMappings = 0) :
                self.type = type
                self.prev = prev
                self.self_value = self_value
                self.next = next
                self.count = count
                self.up = up
                self.maxcount = maxMappings

        # ---------------------------------------
        class PvfsBlockFile :
            def __init__(self, self_value=0, type = 0, prev = 0, next = 0, count = 0, maxFiles = 0) :
                self.type = type
                self.prev = prev
                self.self_value = self_value
                self.next = next
                self.count = count
                self.maxcount = maxFiles

        # ---------------------------------------
        class PvfsFileHandle :
            def __init(self, vfs, info, block, data, currentAddress = 0, dirty = 0, tableBlock = 0, tableIndex = 0, error = 0) :
                self.vfs = vfs
                self.info = info
                self.block = block
                self.currentAddress = currentAddress
                self.dirty = dirty
                self.data = data
                self.tableBlock = tableBlock
                self.tableIndex = tableIndex
                self.error = error

        #-------------------------------------------
        #   possibly have to change
        class PvfsFile  :
            def __init__(self, lock, version, fd = -1, first = 0,blockSize = 0, tableLoc = 0, nextBlock = 0, fileMaxCount = 0, treeMaxCount = 0) :
                self.fd = fd
                self.version = version
                self.blockSize = blockSize
                self.tableLoc = tableLoc
                self.nextBlock = nextBlock
                self.fileMaxCount = fileMaxCount
                self.treeMaxCount = treeMaxCount
                self.lock = Lock()
         
    
        #----------------------------------------------

        class HighTime :
            def __init__(self, seconds: int = 0, subSeconds = 0.0) :
                self.seconds = seconds
                self.subSeconds = subSeconds
        #----------------------------------------------

        class PvfsIndexHeader :
            def __init__(self, datarate, startTime, endTime, timeStampIntervalSeconds, magicNumber = self.PVFS_INDEX_DATA_FILE_MAGIC_NUMBER, version = self.PVFS_INDEX_DATA_FILE_VERSION, dataType = 0) :
                self.magicNumber = magicNumber
                self.version = version
                self.dataType = dataType
                self.datarate = datarate
                self.startTime = startTime
                self.endTime = endTime
                self.timeStampIntervalSeconds = timeStampIntervalSeconds

        #----------------------------------------------
        # possibly need to change the HighTime stuff
        class PvfsIndexEntry :
            def __init__(self, StartTime: HighTime, endTime: HighTime, myLocation = 0, dataLocation = 0) :
                self.StartTime = StartTime
                self.endTime = endTime
                self.myLocation = myLocation
                self.dataLocation = dataLocation 

        #----------------------------------------------
        



        
        







                   

        
        


        





            


        


            
                




    
