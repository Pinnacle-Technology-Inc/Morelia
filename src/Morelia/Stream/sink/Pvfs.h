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
//   There is some problematic signed/unsigned math that needs to be fixed i.e.
//   signed = unsigned - unsigned
/////////////////////////////////////////////////////////////////////////////////////////

#ifndef _PINNACLE_VIRTUAL_FILE_SYSTEM_H_
#define _PINNACLE_VIRTUAL_FILE_SYSTEM_H_

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
constexpr int PVFS_VERSION_MAJOR	=		2;
constexpr int PVFS_VERSION_MINOR	=		0;
constexpr int PVFS_VERSION_REVISION	 =		2;

//													type			  +   next			   + prev			   + self			   + count
constexpr int PVFS_BLOCK_HEADER_SIZE	=	(sizeof ( uint8_t ) +  sizeof ( int64_t ) + sizeof ( int64_t ) + sizeof ( int64_t ) + sizeof ( int32_t ));

constexpr int PVFS_HEADER_SIZE		=	0x0400;		// 1k
constexpr int PVFS_DEFAULT_BLOCK_SIZE		= 0x4000 - PVFS_BLOCK_HEADER_SIZE; //16 k default block size
constexpr int PVFS_MAX_FILENAME_LENGTH =	0x0100;		// Max length of a filename.
constexpr int PVFS_MAX_HANDLES	=		0xFF;			// Maximum number of file pointers allowed into the virutal file.  (Mostly laziness, should be a data store...)
constexpr int PVFS_TIMESTAMP_SIZE   =   44;

// Block types.
constexpr int PVFS_BLOCK_TYPE_UNKNOWN	=	0;
constexpr int PVFS_BLOCK_TYPE_DATA	=	1;
constexpr int PVFS_BLOCK_TYPE_TREE	=	2;
constexpr int PVFS_BLOCK_TYPE_FILE	=	3;
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
    std::int32_t count;
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

    PvfsFileHandle() : currentAddress(0), dirty(0), dataAddress(0), tableBlock(0), tableIndex(0), error(0) {}
};

////////////////////////////////////
//	PVFSFile;
// This is the main structure for tracking the file system.

struct PvfsFile {
    int fd;
    PvfsFileVersion version;
    std::int32_t blockSize;
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

std::shared_ptr<PvfsFile> createVFS(uint32_t block_size = PVFS_DEFAULT_BLOCK_SIZE);
std::shared_ptr<PvfsFile> create_PVFS_file_structure ( uint32_t block_size = PVFS_DEFAULT_BLOCK_SIZE );

void PVFS_file_set_blockSize ( std::shared_ptr<PvfsFile> &vfs, uint32_t block_size = PVFS_DEFAULT_BLOCK_SIZE);

std::shared_ptr<PvfsBlock> create_PVFS_block ( std::shared_ptr<PvfsFile> &vfs );
std::int64_t PVFS_read_block ( int fd, int64_t address, std::shared_ptr<PvfsBlock> &block );
std::int64_t PVFS_write_block ( int fd, int64_t address, std::shared_ptr<PvfsBlock> &block );

std::shared_ptr<PvfsBlockData> create_PVFS_block_data ( std::shared_ptr<PvfsFile> &vfs );
std::shared_ptr<PvfsBlockTree> create_PVFS_block_tree ( std::shared_ptr<PvfsFile> &vfs );
std::shared_ptr<PvfsBlockFile> create_PVFS_block_file ( std::shared_ptr<PvfsFile> &vfs );
// So that things copy properly.
std::int32_t PVFS_cast_block_to_data ( std::shared_ptr<PvfsBlock> &block, std::shared_ptr<PvfsBlockData> &data );
std::int32_t PVFS_cast_block_to_tree ( std::shared_ptr<PvfsBlock> &block, std::shared_ptr<PvfsBlockTree> &tree );
std::int32_t PVFS_cast_block_to_file ( std::shared_ptr<PvfsBlock> &block, std::shared_ptr<PvfsBlockFile> &file );
std::int32_t PVFS_cast_data_to_block ( std::shared_ptr<PvfsBlockData> &data, std::shared_ptr<PvfsBlock> &block );
std::int32_t PVFS_cast_tree_to_block ( std::shared_ptr<PvfsBlockTree> &tree, std::shared_ptr<PvfsBlock> &block );
std::int32_t PVFS_cast_file_to_block ( std::shared_ptr<PvfsBlockFile> &file, std::shared_ptr<PvfsBlock> &block );

std::int64_t PVFS_read_block_file ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockFile> &block );
std::int64_t PVFS_read_block_tree ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockTree> &block );
std::int64_t PVFS_read_block_data ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockData> &block );
std::int64_t PVFS_write_block_file ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockFile> &block );
std::int64_t PVFS_write_block_tree ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockTree> &block );
std::int64_t PVFS_write_block_data ( std::shared_ptr<PvfsFile> &vfs, std::int64_t address, std::shared_ptr<PvfsBlockData> &block );

std::int32_t PVFS_copy_fileEntry ( PvfsFileEntry* dest, PvfsFileEntry *src );

std::shared_ptr<PvfsFileHandle> create_PVFS_file_handle ( std::shared_ptr<PvfsFile> &vfs );

std::shared_ptr<PvfsFile> PVFS_create ( const char * filename );
std::shared_ptr<PvfsFile> PVFS_create_size ( const char * filename, std::uint32_t block_size );
std::shared_ptr<PvfsFile> PVFS_open ( const char * filename );
std::shared_ptr<PvfsFile> PVFS_open_readonly ( const char * filename );
int PVFS_close(int fd);

// Create a empty block, grabs the next space in the disk file system.
std::int64_t PVFS_allocate_block(std::shared_ptr<PvfsFile> &pvfs);

// File Creatation
std::shared_ptr<PvfsFileHandle> PVFS_fcreate ( std::shared_ptr<PvfsFile> &vfs, const char * filename );

std::shared_ptr<PvfsFileHandle> PVFS_fopen ( std::shared_ptr<PvfsFile> &vfs, const char * filename );

// returns true if the filename is in the pvfs.
bool PVFS_has_file ( std::shared_ptr<PvfsFile> &vfs, const char * filename );

//"Deletes" the file by setting the filename to all zeroes ("", not "00000")
//Note this does not free space in the file - TODO::  Mark all blocks associated with the file for later defragmentation
std::int32_t PVFS_delete_file(std::shared_ptr<PvfsFile> &vfs, const char* filename);

// Lists the files in the pvfs
std::uint32_t PVFS_get_file_list ( std::shared_ptr<PvfsFile> &vfs, std::vector<std::string> &filenames );

std::int64_t PVFS_tell ( std::shared_ptr<PvfsFileHandle> &vf );
std::int64_t PVFS_seek ( std::shared_ptr<PvfsFileHandle> &vf, std::int64_t address );
std::int32_t PVFS_write ( std::shared_ptr<PvfsFileHandle> &vf, const std::uint8_t * buffer, std::uint32_t size );
std::int32_t PVFS_read ( std::shared_ptr<PvfsFileHandle> &vf, std::uint8_t * buffer, std::uint32_t size );
std::int32_t PVFS_fclose ( std::shared_ptr<PvfsFileHandle> &vf );
std::int32_t PVFS_flush ( std::shared_ptr<PvfsFileHandle> &vf, bool commit = false );

// Adds a mapping to a tree, if neccessary alters the root tree of the file.
std::int32_t PVFS_tree_add ( std::shared_ptr<PvfsFileHandle> &vf, std::shared_ptr<PvfsBlockTree> &tree, std::shared_ptr<PvfsLocationMap> &map );
std::int32_t PVFS_tree_add_data ( std::shared_ptr<PvfsFileHandle> &vf, std::shared_ptr<PvfsBlockTree> &tree, std::shared_ptr<PvfsLocationMap> &map, std::shared_ptr<PvfsBlockData> &data );

// Utilities for quick file adding and removing for viewing.
std::int32_t PVFS_add ( std::shared_ptr<PvfsFile> &vfs, const char * filename, const char * in_filename );
std::int32_t PVFS_extract ( std::shared_ptr<PvfsFile> &vfs, const char * filename, const char * out_filename );

std::int32_t PVFS_get_channel_list(std::shared_ptr<PvfsFile> &vfs, std::vector<std::string> &names);
std::int32_t PVFS_read_index_file_header ( std::shared_ptr<PvfsFileHandle> &file_handle, PvfsIndexHeader &header );
std::int32_t PVFS_write_index_file_header ( std::shared_ptr<PvfsFileHandle> &file_handle, PvfsIndexHeader &header );

std::int64_t p_write(int fd, void *buf, size_t count);
std::int64_t p_read(int fd, void *buf, size_t count);

std::int64_t PVFS_write_uint8 ( int fd, std::uint8_t value );
std::int64_t PVFS_read_uint8 ( int fd, std::uint8_t & value );
std::int64_t PVFS_write_sint8 ( int fd, std::int8_t value );
std::int64_t PVFS_read_sint8 ( int fd, std::int8_t & value );
std::int64_t PVFS_write_uint16 ( int fd, std::uint16_t value );
std::int64_t PVFS_read_uint16 ( int fd, std::uint16_t & value );
std::int64_t PVFS_write_sint16 ( int fd, std::int16_t value );
std::int64_t PVFS_read_sint16 ( int fd, std::int16_t & value );
std::int64_t PVFS_write_uint32 ( int fd, std::uint32_t value ) ;
std::int64_t PVFS_read_uint32 ( int fd, std::uint32_t & value );
std::int64_t PVFS_write_sint32 ( int fd, std::int32_t value );
std::int64_t PVFS_read_sint32 ( int fd, std::int32_t & value );
std::int64_t PVFS_write_sint64 ( int fd, std::int64_t value );
std::int64_t PVFS_read_sint64 ( int fd, std::int64_t & value );


std::int64_t PVFS_fwrite_uint8 ( std::shared_ptr<PvfsFileHandle> &file, std::uint8_t value );
std::int64_t PVFS_fread_uint8 ( std::shared_ptr<PvfsFileHandle> &file, std::uint8_t * value );
std::int64_t PVFS_fwrite_sint8 ( std::shared_ptr<PvfsFileHandle> &file, std::int8_t value );
std::int64_t PVFS_fread_sint8 ( std::shared_ptr<PvfsFileHandle> &file, std::int8_t * value );
std::int64_t PVFS_fwrite_uint16 ( std::shared_ptr<PvfsFileHandle> &file, std::uint16_t value );
std::int64_t PVFS_fread_uint16 ( std::shared_ptr<PvfsFileHandle> &file, std::uint16_t * value );
std::int64_t PVFS_fwrite_sint16 ( std::shared_ptr<PvfsFileHandle> &file, std::int16_t value );
std::int64_t PVFS_fread_sint16 ( std::shared_ptr<PvfsFileHandle> &file, std::int16_t * value );
std::int64_t PVFS_fwrite_uint32 ( std::shared_ptr<PvfsFileHandle> &file, std::uint32_t value );
std::int64_t PVFS_fread_uint32 ( std::shared_ptr<PvfsFileHandle> &file, std::uint32_t * value );
std::int64_t PVFS_fwrite_sint32 ( std::shared_ptr<PvfsFileHandle> &file, std::int32_t value );
std::int64_t PVFS_fread_sint32 ( std::shared_ptr<PvfsFileHandle> &file, std::int32_t * value );
std::int64_t PVFS_fwrite_sint64 ( std::shared_ptr<PvfsFileHandle> &file, std::int64_t value );
std::int64_t PVFS_fread_sint64 ( std::shared_ptr<PvfsFileHandle> &file, std::int64_t * value );
std::int64_t PVFS_fwrite_float ( std::shared_ptr<PvfsFileHandle> &file, float value );
std::int64_t PVFS_fread_float ( std::shared_ptr<PvfsFileHandle> &file, float * value );
std::int64_t PVFS_fwrite_double ( std::shared_ptr<PvfsFileHandle> &file, double value );
std::int64_t PVFS_fread_double ( std::shared_ptr<PvfsFileHandle> &file, double * value );

//Mutex locking
void PVFS_lock(std::shared_ptr<pvfs::PvfsFile> &vfs);
void PVFS_unlock(std::shared_ptr<pvfs::PvfsFile> &vfs);
}

// helper functions
namespace CRC32
{
	void Reset ();
	std::uint32_t AppendBytes ( const std::uint8_t * bytes, std::uint32_t length );

	std::uint32_t GetCRC ();


	std::uint32_t CalculateCRC32 ( const std::uint8_t * buffer, std::uint32_t length );

	inline std::uint32_t	m_CRC {0xFFFFFFFF};					            //!< Stored crc value

const std::uint32_t m_InitialCRC32Value	= 0xFFFFFFFF;

const std::uint32_t m_CRC32Table [ 256 ] =
{
	0x00000000, 0x77073096, 0xEE0E612C, 0x990951BA,
	0x076DC419, 0x706AF48F, 0xE963A535, 0x9E6495A3,
	0x0EDB8832, 0x79DCB8A4, 0xE0D5E91E, 0x97D2D988,
	0x09B64C2B, 0x7EB17CBD, 0xE7B82D07, 0x90BF1D91,
	0x1DB71064, 0x6AB020F2, 0xF3B97148, 0x84BE41DE,
	0x1ADAD47D, 0x6DDDE4EB, 0xF4D4B551, 0x83D385C7,
	0x136C9856, 0x646BA8C0, 0xFD62F97A, 0x8A65C9EC,
	0x14015C4F, 0x63066CD9, 0xFA0F3D63, 0x8D080DF5,
	0x3B6E20C8, 0x4C69105E, 0xD56041E4, 0xA2677172,
	0x3C03E4D1, 0x4B04D447, 0xD20D85FD, 0xA50AB56B,
	0x35B5A8FA, 0x42B2986C, 0xDBBBC9D6, 0xACBCF940,
	0x32D86CE3, 0x45DF5C75, 0xDCD60DCF, 0xABD13D59,
	0x26D930AC, 0x51DE003A, 0xC8D75180, 0xBFD06116,
	0x21B4F4B5, 0x56B3C423, 0xCFBA9599, 0xB8BDA50F,
	0x2802B89E, 0x5F058808, 0xC60CD9B2, 0xB10BE924,
	0x2F6F7C87, 0x58684C11, 0xC1611DAB, 0xB6662D3D,
	0x76DC4190, 0x01DB7106, 0x98D220BC, 0xEFD5102A,
	0x71B18589, 0x06B6B51F, 0x9FBFE4A5, 0xE8B8D433,
	0x7807C9A2, 0x0F00F934, 0x9609A88E, 0xE10E9818,
	0x7F6A0DBB, 0x086D3D2D, 0x91646C97, 0xE6635C01,
	0x6B6B51F4, 0x1C6C6162, 0x856530D8, 0xF262004E,
	0x6C0695ED, 0x1B01A57B, 0x8208F4C1, 0xF50FC457,
	0x65B0D9C6, 0x12B7E950, 0x8BBEB8EA, 0xFCB9887C,
	0x62DD1DDF, 0x15DA2D49, 0x8CD37CF3, 0xFBD44C65,
	0x4DB26158, 0x3AB551CE, 0xA3BC0074, 0xD4BB30E2,
	0x4ADFA541, 0x3DD895D7, 0xA4D1C46D, 0xD3D6F4FB,
	0x4369E96A, 0x346ED9FC, 0xAD678846, 0xDA60B8D0,
	0x44042D73, 0x33031DE5, 0xAA0A4C5F, 0xDD0D7CC9,
	0x5005713C, 0x270241AA, 0xBE0B1010, 0xC90C2086,
	0x5768B525, 0x206F85B3, 0xB966D409, 0xCE61E49F,
	0x5EDEF90E, 0x29D9C998, 0xB0D09822, 0xC7D7A8B4,
	0x59B33D17, 0x2EB40D81, 0xB7BD5C3B, 0xC0BA6CAD,
	0xEDB88320, 0x9ABFB3B6, 0x03B6E20C, 0x74B1D29A,
	0xEAD54739, 0x9DD277AF, 0x04DB2615, 0x73DC1683,
	0xE3630B12, 0x94643B84, 0x0D6D6A3E, 0x7A6A5AA8,
	0xE40ECF0B, 0x9309FF9D, 0x0A00AE27, 0x7D079EB1,
	0xF00F9344, 0x8708A3D2, 0x1E01F268, 0x6906C2FE,
	0xF762575D, 0x806567CB, 0x196C3671, 0x6E6B06E7,
	0xFED41B76, 0x89D32BE0, 0x10DA7A5A, 0x67DD4ACC,
	0xF9B9DF6F, 0x8EBEEFF9, 0x17B7BE43, 0x60B08ED5,
	0xD6D6A3E8, 0xA1D1937E, 0x38D8C2C4, 0x4FDFF252,
	0xD1BB67F1, 0xA6BC5767, 0x3FB506DD, 0x48B2364B,
	0xD80D2BDA, 0xAF0A1B4C, 0x36034AF6, 0x41047A60,
	0xDF60EFC3, 0xA867DF55, 0x316E8EEF, 0x4669BE79,
	0xCB61B38C, 0xBC66831A, 0x256FD2A0, 0x5268E236,
	0xCC0C7795, 0xBB0B4703, 0x220216B9, 0x5505262F,
	0xC5BA3BBE, 0xB2BD0B28, 0x2BB45A92, 0x5CB36A04,
	0xC2D7FFA7, 0xB5D0CF31, 0x2CD99E8B, 0x5BDEAE1D,
	0x9B64C2B0, 0xEC63F226, 0x756AA39C, 0x026D930A,
	0x9C0906A9, 0xEB0E363F, 0x72076785, 0x05005713,
	0x95BF4A82, 0xE2B87A14, 0x7BB12BAE, 0x0CB61B38,
	0x92D28E9B, 0xE5D5BE0D, 0x7CDCEFB7, 0x0BDBDF21,
	0x86D3D2D4, 0xF1D4E242, 0x68DDB3F8, 0x1FDA836E,
	0x81BE16CD, 0xF6B9265B, 0x6FB077E1, 0x18B74777,
	0x88085AE6, 0xFF0F6A70, 0x66063BCA, 0x11010B5C,
	0x8F659EFF, 0xF862AE69, 0x616BFFD3, 0x166CCF45,
	0xA00AE278, 0xD70DD2EE, 0x4E048354, 0x3903B3C2,
	0xA7672661, 0xD06016F7, 0x4969474D, 0x3E6E77DB,
	0xAED16A4A, 0xD9D65ADC, 0x40DF0B66, 0x37D83BF0,
	0xA9BCAE53, 0xDEBB9EC5, 0x47B2CF7F, 0x30B5FFE9,
	0xBDBDF21C, 0xCABAC28A, 0x53B39330, 0x24B4A3A6,
	0xBAD03605, 0xCDD70693, 0x54DE5729, 0x23D967BF,
	0xB3667A2E, 0xC4614AB8, 0x5D681B02, 0x2A6F2B94,
	0xB40BBE37, 0xC30C8EA1, 0x5A05DF1B, 0x2D02EF8D
};
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

