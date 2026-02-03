//////////////////////////////////////////////////////////////////////////////////
// pvfs.h
// Pinnacle Virtual File System
//
// A system independent virtual file system for creating archives of files.
// The file system lives inside a larger file.
//
/////////////////////////////////////////////////////////////////////////////////
//
// Note: These routines are not thread safe.  Thread safety is up to the user via
//
// PVFS_lock, PVFS_unlock.
//
/////////////////////////////////////////////////////////////////////////////////
//
// Example PVFS file in a hex editor
// Navigate to the table location - generally C - 13 (reverse order - little endian)
// Let's say that value is 0400.  Scroll down to 0400 in the hex file.
// This should be the first file block, denoted by the block type 3.
// The type will be followed by 3 8 byte pointers, previous, self and next.
// Previous = -1 (0xFFFFFFFF or PVFS_INVALID_LOCATION) indicates that this is the first file block.
// Self - should point to the location of this block, so 0x00000400.
// Next - will point to the next file block.  PVFS_INVALID_LOCATION in next indicates this is the only file block.
// This will be followed by a 4 byte count - how many files are stored in this virtual file system.
//
// This will be followed by a series of file entries and locations always in the form
// 8 byte start block
// 8 byte size
// file name.
//
// For any given file, go to the start block location and will find a tree block, denoted by the block type 2.
// Each tree block will start with 3 8 byte pointers, previous, self and next.  If previous is 0xFFFFFFFF (-1)
// then this is the first tree block in the file.  If next is 0xFFFFFFFF then there are no additional tree
// blocks in this file.
// This is followed by a 4 byte count of data blocks, an 8 byte up address and a series of PVFS location maps
// containing 2 8 byte addresses.
//
// Navigate to the block location to find a data block, denoted by the block type 1.
// Data blocks start with the familiar 8 byte previous, self, next addresses followed by
// a 4 byte data count and an 8 byte reference to the tree block that can be used to index all
// data blocks in the file.
//
/////////////////////////////////////////////////////////////////////////////////////////
// TODO:
//   Data blocks should be relatively large for efficiency, but tree and file blocks can be
//   much smaller.  Implement different block sizes for tree and file blocks.
//
//   In this implementation all blocks in a pvfs file and subfile must be the same size.
//   Some hooks are in place to allow different block sizes in the future, but this will
//   require a significant refactor.
//
//   There is some problematic signed/unsigned math that needs to be fixed i.e.
//   signed = unsigned - unsigned
/////////////////////////////////////////////////////////////////////////////////////////

#ifndef _PINNACLE_VIRTUAL_FILE_SYSTEM_H_
#define _PINNACLE_VIRTUAL_FILE_SYSTEM_H_

#include "pvfs_global.h"
#include <stdio.h>
#include <time.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <vector>
#include <memory>
#include <mutex>
#include <iostream>
#include <algorithm>

#ifdef _WIN32
    // Windows-specific includes
    #define NOMINMAX
    #include <windows.h>
    #include <stdint.h>
    #include <io.h>
#else
    // POSIX-specific includes for Linux and other Unix-like systems
    #include <unistd.h>
#endif

namespace pvfs {

/////////////////////////////////////////////////////////////////////////
// CONSTANTS
/////////////////////////////////////////////////////////////////////////

// Version Information
constexpr int PVFS_VERSION_MAJOR	=		3;
constexpr int PVFS_VERSION_MINOR	=		1;
constexpr int PVFS_VERSION_REVISION	 =		1;

//													type			  +   next			   + prev			   + self			   + count
constexpr int PVFS_BLOCK_HEADER_SIZE	=	(sizeof ( uint8_t ) +  sizeof ( int64_t ) + sizeof ( int64_t ) + sizeof ( int64_t ) + sizeof ( int32_t ));

constexpr int PVFS_HEADER_SIZE		=	0x0400;		// 1k
constexpr int PVFS_DEFAULT_BLOCK_SIZE		= 0x4000 - PVFS_BLOCK_HEADER_SIZE; //16 k default block size
constexpr int PVFS_MAX_FILENAME_LENGTH =	0x0100;		// Max length of a filename.
constexpr int PVFS_MAX_HANDLES	=		0xFF;			// Maximum number of file pointers allowed into the virutal file.  (Mostly laziness, should be a data store...)
constexpr int PVFS_TIMESTAMP_SIZE   =   44;


// Free block table constants
constexpr int PVFS_FREE_BLOCK_TABLE_MAX_ENTRIES = 64;		// Maximum number of unique block sizes in free block table
constexpr int PVFS_FREE_BLOCK_TABLE_ENTRY_SIZE = 12;		// sizeof(uint32_t) + sizeof(int64_t) = 4 + 8
constexpr int PVFS_HEADER_FREE_BLOCK_TABLE_OFFSET = 20;		// After magic(4) + version(4) + blockSize(4) + tableLoc(8) = 20
constexpr int PVFS_HEADER_FREE_BLOCK_TABLE_COUNT_OFFSET = 20;	// 4 bytes for count
constexpr int PVFS_HEADER_FREE_BLOCK_TABLE_DATA_OFFSET = 24;	// After count (4 bytes)

// Block types.
constexpr int PVFS_BLOCK_TYPE_UNKNOWN	=	0;
constexpr int PVFS_BLOCK_TYPE_DATA	=	1;
constexpr int PVFS_BLOCK_TYPE_TREE	=	2;
constexpr int PVFS_BLOCK_TYPE_FILE	=	3;
constexpr int PVFS_BLOCK_TYPE_FREE	=	4;		// Marks a block as free/available for reuse
constexpr int PVFS_BLOCK_TYPE_EOF	=	0xFF;		// Marks the end of the file. A read with this as the block type is an error.

constexpr int PVFS_INVALID_LOCATION		=	-1;			//!< Represents either nothing beyond a block or an error.
constexpr int PVFS_INVALID_FD			=	-1;				//!< Invalid file descriptor.

constexpr int PVFS_OK			=		0;
constexpr int PVFS_ERROR		=		-1;
constexpr int PVFS_ARG_NULL		=		-2;			//!< A null value was passed as an argument.
constexpr int PVFS_EOF	=				-3;			//!< End of file, used for read and getc.
constexpr int PVFS_FILE_NOT_OPENED	=	-4;			//!< When trying to add/extract a file this error can occur.
constexpr int PVFS_CORRUPTION_DETECTED =	-5;		//!< Something awful happened.


// Dirty bit values
constexpr int PVFS_DIRTY		=			0;
constexpr int PVFS_CLEAN		=			1;

constexpr std::uint32_t    	PVFS_INDEX_DATA_FILE_MAGIC_NUMBER = 0XFF01FF01;
constexpr std::uint32_t    	PVFS_INDEX_DATA_FILE_VERSION = 2;
constexpr char          	PVFS_INDEX_EXTENSION[] = ".index";
constexpr char          	PVFS_DATA_EXTENSION[]  = ".idat";
constexpr std::uint32_t    	PVFS_INDEX_HEADER_SIZE = 0x0400;  //1024

/////////////////////////////////////////////////////////////////////////
// Types
/////////////////////////////////////////////////////////////////////////

//////////////////////////////
// PvfsFileEntry
//
// Information about a file stored within the vfs
struct PvfsFileEntry {
    std::int64_t startBlock;
    std::int64_t size;
    uint8_t filename[PVFS_MAX_FILENAME_LENGTH];

    PvfsFileEntry() : startBlock(0), size(0), filename{0} {}
};

//////////////////////////////
// PvfsLocationMap
//
// A way to convert from a seek with in virtual file to a seek in the real file.
// Basically points to the block where the data would be found if looking for the data
// at the location within the file.
// In a tree
struct PvfsLocationMap {
    std::int64_t address;
    std::int64_t blockLoc;

    PvfsLocationMap() : address(0), blockLoc(0) {}
};


struct PvfsFileVersion {
    uint8_t major;
    uint8_t minor;
    uint16_t revision;

    PvfsFileVersion() : major(0), minor(0), revision(0) {}
};

//////////////////////////////
// FreeBlockTableEntry
//
// Entry in the free block table for a specific block size
struct FreeBlockTableEntry {
    std::uint32_t blockSize;		// Block size (0 = empty entry)
    std::int64_t nextFreeBlock;		// Pointer to first free block of this size (PVFS_INVALID_LOCATION = empty chain)

    FreeBlockTableEntry() : blockSize(0), nextFreeBlock(PVFS_INVALID_LOCATION) {}
};

//////////////////////////////
// PvfsBlock;
//
// A basic block definition
// Can use this as a way of debugging the entire system.

struct PvfsBlock {
    uint8_t type;
    std::int64_t prev;
    std::int64_t self;
    std::int64_t next;
    std::int32_t count;
    std::vector<uint8_t> data;
    std::uint32_t size;

    PvfsBlock() : type(0), prev(0), self(0), next(0), count(0), size(0) {}
};


/////////////////////////////
// PvfsBlockData
//
// Simplest of the blocks, contains just raw data.
struct PvfsBlockData {
    uint8_t type;
    std::int64_t prev;
    std::int64_t self;
    std::int64_t next;
    std::int32_t count;
    std::int64_t tree;
    std::vector<uint8_t> data;
    std::int32_t maxCount;

    PvfsBlockData() : type(0), prev(0), self(0), next(0), count(0), tree(0), maxCount(0) {}
};

//////////////////////////////
// PvfsBlockTree
//
// A block that contains a mapping for finding data blocks
// or other tree blocks.

struct PvfsBlockTree {
    uint8_t type;
    std::int64_t prev;
    std::int64_t self;
    std::int64_t next;
    std::int32_t count;
    std::int64_t up;
    std::int32_t maxMappings;
    std::vector<PvfsLocationMap> mappings;

    PvfsBlockTree() : type(0), prev(0), self(0), next(0), count(0), up(0), maxMappings(0) {}
};



//////////////////////////////
// PvfsBlockFile
//
// A block of files entries.
// The next pointer allows the block to list all of the files.

struct PvfsBlockFile {
    uint8_t type;
    std::int64_t prev;
    std::int64_t self;
    std::int64_t next;
    std::int32_t count;  // Unused in memory - count is derived from files.size() when writing to disk. Kept for backward compatibility with disk format.
    std::int32_t maxFiles;
    std::vector<PvfsFileEntry> files;

    PvfsBlockFile() : type(0), prev(0), self(0), next(0), count(0), maxFiles(0) {}
};

//////////////////////////////
// PvfsFileHandle
//
struct PvfsFile; //forward declaration

struct PvfsFileHandle {
    std::shared_ptr<PvfsFile> vfs;
    PvfsFileEntry info;  // start location, filename and last byte written (i.e. total size of the file in bytes)
    std::shared_ptr<PvfsBlock> block;
    std::int64_t currentAddress;
    uint8_t dirty;
    std::shared_ptr<PvfsBlockData> data;
    std::int32_t dataAddress;
    std::shared_ptr<PvfsBlockTree> tree;
    std::int64_t tableBlock;
    std::int32_t tableIndex;
    std::int32_t error;
    std::mutex lock;

    PvfsFileHandle() : currentAddress(0), dirty(0), dataAddress(0), tableBlock(0), tableIndex(0), error(0) {}
};

////////////////////////////////////
//	PVFSFile;
// This is the main structure for tracking the file system.

struct PvfsFile {
    int fd;
    PvfsFileVersion version;
    std::int32_t blockSize; //For now blockSize and block->size are the same. Having both definitions
                            //may be useful for future implementations where different block sizes are allowed.
    std::int64_t tableLoc;
    std::int64_t nextBlock;
    std::shared_ptr<PvfsBlock> block;
    std::shared_ptr<PvfsBlockFile> fileBlock;
    std::shared_ptr<PvfsFileHandle> fileHandles[PVFS_MAX_HANDLES];
    std::uint32_t fileMaxCount;
    std::uint32_t treeMaxCount;
    std::shared_ptr<PvfsBlockFile> fileBlockTemp;
    std::shared_ptr<PvfsBlockTree> treeBlockTemp;
    std::shared_ptr<PvfsBlockData> dataBlockTemp;
    std::mutex lock;

    PvfsFile() : fd(-1), blockSize(0), tableLoc(0), nextBlock(0), fileMaxCount(0), treeMaxCount(0) {}
    ~PvfsFile();  // Close fd so the .pvfs file is released (e.g. for test cleanup on Windows)
};


struct HighTime {
    std::int64_t seconds;
    double subSeconds;

    HighTime() : seconds(0), subSeconds(0.0) {}
    HighTime(std::int64_t sec, double subSec) : seconds(sec), subSeconds(subSec) {}
};

struct PvfsIndexHeader
{
    std::uint32_t		magicNumber;
    std::uint32_t		version;
    std::uint32_t		dataType;
    float		        datarate;
    pvfs::HighTime	    startTime;
    pvfs::HighTime	    endTime;
    std::uint32_t		timeStampIntervalSeconds;

    PvfsIndexHeader() : magicNumber(pvfs::PVFS_INDEX_DATA_FILE_MAGIC_NUMBER), version(pvfs::PVFS_INDEX_DATA_FILE_VERSION), dataType{0} {}
};

//Index Entry
struct PvfsIndexEntry {
    pvfs::HighTime	    startTime;
    pvfs::HighTime	    endTime;
    std::int64_t	    myLocation;
    std::int64_t	    dataLocation;

    PvfsIndexEntry()
        : myLocation(0), dataLocation(0) {}
};


/////////////////////////////////////////////////////////////////////////
// Function Prototypes
/////////////////////////////////////////////////////////////////////////

/////////////////
// A few constructors/deconstructor.

//Template forward declaration
template<typename BlockType>
std::shared_ptr<BlockType> createBlock(uint32_t size);
template<typename BlockType>
std::int32_t clearBlock(std::shared_ptr<BlockType> &block, std::uint32_t size);

//templates
//These are only useful for data and base blocks - tree and file have different struct naming
//
template<typename BlockType>
std::shared_ptr<BlockType> createBlock(std::uint32_t size)
{
    try {
        auto block = std::make_shared<BlockType>();
        std::int32_t err = PVFS_ARG_NULL;
        if(block)err = pvfs::clearBlock<BlockType>(block, size);
        if((!block) || (err != PVFS_OK))return nullptr;
        else return block;
    } catch (const std::bad_alloc& e) {
        std::cerr << "Block Memory allocation failed: " << e.what() << '\n';
        return nullptr;
    }
}

template<typename BlockType>
std::int32_t clearBlock(std::shared_ptr<BlockType> &block, std::uint32_t size)
{
    if (!block) return pvfs::PVFS_ARG_NULL;

    block->next  = pvfs::PVFS_INVALID_LOCATION;
    block->prev  = pvfs::PVFS_INVALID_LOCATION;
    block->count = 0;
    block->data.clear();
    // Allocate space in data and set all values to zero.
    if(size > 0)block->data.resize(size, 0);
    return PVFS_OK;
}

PVFS_EXPORT std::shared_ptr<PvfsFile> createVFS(uint32_t block_size = PVFS_DEFAULT_BLOCK_SIZE);
PVFS_EXPORT std::shared_ptr<PvfsFile> create_PVFS_file_structure ( uint32_t block_size = PVFS_DEFAULT_BLOCK_SIZE );

PVFS_EXPORT void PVFS_file_set_blockSize ( std::shared_ptr<PvfsFile> &vfs, uint32_t block_size = PVFS_DEFAULT_BLOCK_SIZE);

PVFS_EXPORT std::shared_ptr<PvfsBlock> create_PVFS_block ( std::shared_ptr<PvfsFile> &vfs );
PVFS_EXPORT std::int64_t PVFS_read_block ( int fd, int64_t address, std::shared_ptr<PvfsBlock> &block );
PVFS_EXPORT std::int64_t PVFS_write_block ( int fd, int64_t address, std::shared_ptr<PvfsBlock> &block );

PVFS_EXPORT std::shared_ptr<PvfsBlockData> create_PVFS_block_data ( std::shared_ptr<PvfsFile> &vfs );
PVFS_EXPORT std::shared_ptr<PvfsBlockTree> create_PVFS_block_tree ( std::shared_ptr<PvfsFile> &vfs );
PVFS_EXPORT std::shared_ptr<PvfsBlockFile> create_PVFS_block_file ( std::shared_ptr<PvfsFile> &vfs );
// So that things copy properly.
PVFS_EXPORT std::int32_t PVFS_cast_block_to_data ( std::shared_ptr<PvfsBlock> &block, std::shared_ptr<PvfsBlockData> &data );
PVFS_EXPORT std::int32_t PVFS_cast_block_to_tree ( std::shared_ptr<PvfsBlock> &block, std::shared_ptr<PvfsBlockTree> &tree );
PVFS_EXPORT std::int32_t PVFS_cast_block_to_file ( std::shared_ptr<PvfsBlock> &block, std::shared_ptr<PvfsBlockFile> &file );
PVFS_EXPORT std::int32_t PVFS_cast_data_to_block ( std::shared_ptr<PvfsBlockData> &data, std::shared_ptr<PvfsBlock> &block );
PVFS_EXPORT std::int32_t PVFS_cast_tree_to_block ( std::shared_ptr<PvfsBlockTree> &tree, std::shared_ptr<PvfsBlock> &block );
PVFS_EXPORT std::int32_t PVFS_cast_file_to_block ( std::shared_ptr<PvfsBlockFile> &file, std::shared_ptr<PvfsBlock> &block );

PVFS_EXPORT std::int64_t PVFS_read_block_file ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockFile> &block );
PVFS_EXPORT std::int64_t PVFS_read_block_tree ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockTree> &block );
PVFS_EXPORT std::int64_t PVFS_read_block_data ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockData> &block );
PVFS_EXPORT std::int64_t PVFS_write_block_file ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockFile> &block );
PVFS_EXPORT std::int64_t PVFS_write_block_tree ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockTree> &block );
PVFS_EXPORT std::int64_t PVFS_write_block_data ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockData> &block );

PVFS_EXPORT std::int32_t PVFS_copy_fileEntry ( PvfsFileEntry* dest, PvfsFileEntry *src );

PVFS_EXPORT std::shared_ptr<PvfsFileHandle> create_PVFS_file_handle ( std::shared_ptr<PvfsFile> &vfs );

PVFS_EXPORT std::shared_ptr<PvfsFile> PVFS_create ( const char * filename );
PVFS_EXPORT std::shared_ptr<PvfsFile> PVFS_create_size ( const char * filename, std::uint32_t block_size );
PVFS_EXPORT std::shared_ptr<PvfsFile> PVFS_open ( const char * filename );
PVFS_EXPORT std::shared_ptr<PvfsFile> PVFS_open_readonly ( const char * filename );
PVFS_EXPORT int PVFS_close(int fd);

// Create a empty block, grabs the next space in the disk file system.
// Checks free block table first when PVFS_ENABLE_BLOCK_REUSE is 1 (default); else always appends at end.
PVFS_EXPORT std::int64_t PVFS_allocate_block(std::shared_ptr<PvfsFile> &pvfs);

// Free block table management functions
PVFS_EXPORT std::int32_t PVFS_read_free_block_table(std::shared_ptr<PvfsFile> &vfs, std::vector<FreeBlockTableEntry> &table);
PVFS_EXPORT std::int32_t PVFS_write_free_block_table(std::shared_ptr<PvfsFile> &vfs, const std::vector<FreeBlockTableEntry> &table);
PVFS_EXPORT std::int32_t PVFS_add_free_block(std::shared_ptr<PvfsFile> &vfs, std::int64_t blockAddress, std::uint32_t blockSize);
PVFS_EXPORT std::int64_t PVFS_get_free_block(std::shared_ptr<PvfsFile> &vfs, std::uint32_t blockSize);

// File Creatation
PVFS_EXPORT std::shared_ptr<PvfsFileHandle> PVFS_fcreate ( std::shared_ptr<PvfsFile> &vfs, const char * filename );

PVFS_EXPORT std::shared_ptr<PvfsFileHandle> PVFS_fopen ( std::shared_ptr<PvfsFile> &vfs, const char * filename );

// returns true if the filename is in the pvfs.
PVFS_EXPORT bool PVFS_has_file (std::shared_ptr<PvfsFile> vfs, const char * filename );

// Deletes the file and frees all associated blocks (tree and data blocks)
// Marks all blocks as FREE for potential reuse
// Zeros the file entry slot in place (filename, startBlock, size); PVFS_fcreate reuses
// such slots when creating a new file, so overwrites do not grow the file block chain
PVFS_EXPORT std::int32_t PVFS_delete_file(std::shared_ptr<PvfsFile> &vfs, const char* filename);

// Helper function to recursively collect all blocks (tree and data) for a file
// Used internally by PVFS_delete_file
PVFS_EXPORT std::int32_t PVFS_collect_file_blocks(std::shared_ptr<PvfsFile> &vfs, std::int64_t startBlock, std::vector<std::int64_t> &treeBlocks, std::vector<std::int64_t> &dataBlocks);

// Lists the files in the pvfs
PVFS_EXPORT std::uint32_t PVFS_get_file_list ( std::shared_ptr<PvfsFile> &vfs, std::vector<std::string> &filenames );

PVFS_EXPORT std::int64_t PVFS_tell ( std::shared_ptr<PvfsFileHandle> &vf );
PVFS_EXPORT std::int64_t PVFS_seek ( std::shared_ptr<PvfsFileHandle> &vf, std::int64_t address );
PVFS_EXPORT std::int32_t PVFS_write ( std::shared_ptr<PvfsFileHandle> &vf, const std::uint8_t * buffer, std::uint32_t size );
PVFS_EXPORT std::int32_t PVFS_read ( std::shared_ptr<PvfsFileHandle> &vf, std::uint8_t * buffer, std::uint32_t size );
PVFS_EXPORT std::int32_t PVFS_fclose ( std::shared_ptr<PvfsFileHandle> &vf );
PVFS_EXPORT std::int32_t PVFS_flush ( std::shared_ptr<PvfsFileHandle> &vf, bool commit = false );

// Adds a mapping to a tree, if neccessary alters the root tree of the file.
PVFS_EXPORT std::int32_t PVFS_tree_add ( std::shared_ptr<PvfsFileHandle> &vf, std::shared_ptr<PvfsBlockTree> &tree, std::shared_ptr<PvfsLocationMap> &map );
PVFS_EXPORT std::int32_t PVFS_tree_add_data ( std::shared_ptr<PvfsFileHandle> &vf, std::shared_ptr<PvfsBlockTree> &tree, std::shared_ptr<PvfsLocationMap> &map, std::shared_ptr<PvfsBlockData> &data );

// Utilities for quick file adding and removing for viewing.
PVFS_EXPORT std::int32_t PVFS_add ( std::shared_ptr<PvfsFile> &vfs, const char * filename, const char * in_filename );
PVFS_EXPORT std::int32_t PVFS_extract ( std::shared_ptr<PvfsFile> &vfs, const char * filename, const char * out_filename );
PVFS_EXPORT std::int32_t PVFS_overwrite ( std::shared_ptr<PvfsFile> &vfs, const char * vfs_filename, const char * disk_filename );

PVFS_EXPORT std::int32_t PVFS_get_channel_list(std::shared_ptr<PvfsFile> &vfs, std::vector<std::string> &names);
PVFS_EXPORT std::int32_t PVFS_read_index_file_header ( std::shared_ptr<PvfsFileHandle> &file_handle, PvfsIndexHeader &header );
PVFS_EXPORT std::int32_t PVFS_write_index_file_header ( std::shared_ptr<PvfsFileHandle> &file_handle, PvfsIndexHeader &header );

PVFS_EXPORT std::int64_t p_write(int fd, void *buf, size_t count);
PVFS_EXPORT std::int64_t p_read(int fd, void *buf, size_t count);

PVFS_EXPORT std::int64_t PVFS_write_uint8 ( int fd, std::uint8_t value );
PVFS_EXPORT std::int64_t PVFS_read_uint8 ( int fd, std::uint8_t & value );
PVFS_EXPORT std::int64_t PVFS_write_sint8 ( int fd, std::int8_t value );
PVFS_EXPORT std::int64_t PVFS_read_sint8 ( int fd, std::int8_t & value );
PVFS_EXPORT std::int64_t PVFS_write_uint16 ( int fd, std::uint16_t value );
PVFS_EXPORT std::int64_t PVFS_read_uint16 ( int fd, std::uint16_t & value );
PVFS_EXPORT std::int64_t PVFS_write_sint16 ( int fd, std::int16_t value );
PVFS_EXPORT std::int64_t PVFS_read_sint16 ( int fd, std::int16_t & value );
PVFS_EXPORT std::int64_t PVFS_write_uint32 ( int fd, std::uint32_t value ) ;
PVFS_EXPORT std::int64_t PVFS_read_uint32 ( int fd, std::uint32_t & value );
PVFS_EXPORT std::int64_t PVFS_write_sint32 ( int fd, std::int32_t value );
PVFS_EXPORT std::int64_t PVFS_read_sint32 ( int fd, std::int32_t & value );
PVFS_EXPORT std::int64_t PVFS_write_sint64 ( int fd, std::int64_t value );
PVFS_EXPORT std::int64_t PVFS_read_sint64 ( int fd, std::int64_t & value );


PVFS_EXPORT std::int64_t PVFS_fwrite_uint8 ( std::shared_ptr<PvfsFileHandle> &file, std::uint8_t value );
PVFS_EXPORT std::int64_t PVFS_fread_uint8 ( std::shared_ptr<PvfsFileHandle> &file, std::uint8_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_sint8 ( std::shared_ptr<PvfsFileHandle> &file, std::int8_t value );
PVFS_EXPORT std::int64_t PVFS_fread_sint8 ( std::shared_ptr<PvfsFileHandle> &file, std::int8_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_uint16 ( std::shared_ptr<PvfsFileHandle> &file, std::uint16_t value );
PVFS_EXPORT std::int64_t PVFS_fread_uint16 ( std::shared_ptr<PvfsFileHandle> &file, std::uint16_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_sint16 ( std::shared_ptr<PvfsFileHandle> &file, std::int16_t value );
PVFS_EXPORT std::int64_t PVFS_fread_sint16 ( std::shared_ptr<PvfsFileHandle> &file, std::int16_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_uint32 ( std::shared_ptr<PvfsFileHandle> &file, std::uint32_t value );
PVFS_EXPORT std::int64_t PVFS_fread_uint32 ( std::shared_ptr<PvfsFileHandle> &file, std::uint32_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_sint32 ( std::shared_ptr<PvfsFileHandle> &file, std::int32_t value );
PVFS_EXPORT std::int64_t PVFS_fread_sint32 ( std::shared_ptr<PvfsFileHandle> &file, std::int32_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_sint64 ( std::shared_ptr<PvfsFileHandle> &file, std::int64_t value );
PVFS_EXPORT std::int64_t PVFS_fread_sint64 ( std::shared_ptr<PvfsFileHandle> &file, std::int64_t * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_float ( std::shared_ptr<PvfsFileHandle> &file, float value );
PVFS_EXPORT std::int64_t PVFS_fread_float ( std::shared_ptr<PvfsFileHandle> &file, float * value );
PVFS_EXPORT std::int64_t PVFS_fwrite_double ( std::shared_ptr<PvfsFileHandle> &file, double value );
PVFS_EXPORT std::int64_t PVFS_fread_double ( std::shared_ptr<PvfsFileHandle> &file, double * value );

//Mutex locking
PVFS_EXPORT void PVFS_lock(std::shared_ptr<pvfs::PvfsFile> &vfs);
PVFS_EXPORT void PVFS_unlock(std::shared_ptr<pvfs::PvfsFile> &vfs);
PVFS_EXPORT void PVFS_lock_file(std::shared_ptr<pvfs::PvfsFileHandle> &vf);
PVFS_EXPORT void PVFS_unlock_file(std::shared_ptr<pvfs::PvfsFileHandle> &vf);
}

/* Notes for future improvements - Direct windows API disk I/O calls*/
/*
File Creation and Opening

C Library: int fd = open(const char *pathname, int flags, mode_t mode);
Windows API: HANDLE CreateFile(LPCTSTR lpFileName, DWORD dwDesiredAccess, DWORD dwShareMode, LPSECURITY_ATTRIBUTES lpSecurityAttributes, DWORD dwCreationDisposition, DWORD dwFlagsAndAttributes, HANDLE hTemplateFile);
Read

C Library: ssize_t read(int fd, void *buf, size_t count);
Windows API: BOOL ReadFile(HANDLE hFile, LPVOID lpBuffer, DWORD nNumberOfBytesToRead, LPDWORD lpNumberOfBytesRead, LPOVERLAPPED lpOverlapped);
Write

C Library: ssize_t write(int fd, const void *buf, size_t count);
Windows API: BOOL WriteFile(HANDLE hFile, LPCVOID lpBuffer, DWORD nNumberOfBytesToWrite, LPDWORD lpNumberOfBytesWritten, LPOVERLAPPED lpOverlapped);
Close

C Library: int close(int fd);
Windows API: BOOL CloseHandle(HANDLE hObject);

Example:
#ifdef _WIN32
    #ifdef _PVFS_FAST_IO
        // Example for Write using Windows API
        HANDLE hFile = CreateFile(...); // Proper arguments needed
        if (hFile != INVALID_HANDLE_VALUE) {
            DWORD written;
            BOOL result = WriteFile(hFile, buffer, (DWORD)rv, &written, NULL);
            if (!result) {
                // Handle error
            }
            CloseHandle(hFile);
        }
    #else
        _write(fd, buffer, rv);
    #endif
#else
    write(fd, buffer, rv);
#endif
*/

#endif // _PINNACLE_VIRTUAL_FILE_SYSTEM_H_

