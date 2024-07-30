#ifndef PVFS_WRITECACHE_H
#define PVFS_WRITECACHE_H


/*-----------------------------------------------------------------------------
*                                 INCLUDE(FILES)
*-----------------------------------------------------------------------------*/
#include <QMutex>
#include <QThread>
#include <QFuture>



#include <pinnacle.h>
#include <cpHighTime.h>
#include <PALlib/datafile/linear/LinearDataFileInterface.h>
#include <PALlib/PVFS/pvfs.h>
#include <ComplexMathArray.h>


/*-----------------------------------------------------------------------------
*                                LITERAL CONSTANTS
*-----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                GLOBALS
*----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                TYPES
*-----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                MACROS
*-----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                FUNCTIONS
*-----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                CLASSES
*-----------------------------------------------------------------------------*/

/*!-------------------------------------------------------
|	\class
|	CLASS NAME:
|		WriteCache
|
|	DESCRIPTION:
|	\brief
|	    Acts as a write cache for the data used
|	    in the PVFS_IndexedDataFile. Is double buffered.
|	    Handles the writing to the pvfs file. Write is asynchronous.
|	    NOTE: Object is not thread safe
|
*//*--------------------------------------------------------*/
class PVFS_WriteCache
{
public:

	enum Result { SUCCESS, FULL, FAIL };

	PVFS_WriteCache ( uint32 blockSize, bool asynchronous = true, bool seekToEnd = true );
	virtual ~PVFS_WriteCache ();

	// Return the location in the cache of the next data to be written
	sint64 Tell();

	// Tells whether the thread is currently writing the data or not
	bool IsWriting() const;

	// Add a value to the cache
	Result AddValue ( const uint8 * data, uint32 size );
	bool Write ( const uint8 * data, uint32 size );

	template <typename T>
	bool Write ( const T & data )
	{
		return Write ( (uint8*)&data, sizeof ( T ) );
	}

	// Flush all buffers

	// Sets the file to write to
	void SetFile ( PVFS_file_handle_t * file ) { m_File = file; }

	// Write the data to the given file
	Result WriteCacheToFile ( PVFS_file_handle_t * file );
	Result WriteCacheToFile ();

	bool Flush ( bool waitForFinish = false );
	sint64 GetSpaceBeforeFlush() const { return m_FlushBlockSize - m_CurIndex; }

	// Waits for the previous write to finish
	void Wait();

protected:
	// Separate Thread function
	static void WriteCacheAsync ( PVFS_file_handle_t * file, uint8 * cache, uint32 size, bool seekToEnd );

	Result DoWriteCacheToFile ( PVFS_file_handle_t * file );

private:
	uint8 *		m_Cache [ 2 ];	    //!< The double buffered cache
	uint8		m_CacheIndex;	    //!< Which cache are we writing to
	uint32		m_FlushBlockSize;   //!< The size at which the cache is flushed
	uint32		m_BlockSize;	    //!< Keep track of the block size
	uint32		m_CurIndex;	    //!< Keep track of where we are within the cache
	QMutex		m_Mutex;
	PVFS_file_handle_t *	m_File;
	QFuture<void>	m_Result;	    //!< Information on the thread progress
	bool		m_Asynchronous;		//!< Flag for asynchronous writes
	bool        m_SeekToEnd;        //!< seek to end of file before writing data
};

#endif // PVFS_WRITECACHE_H
