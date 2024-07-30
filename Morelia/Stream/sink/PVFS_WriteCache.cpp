/*!***************************************************************************
*	FILE:
*		PVFS_IndexedDataFile.cpp
*
*	DESCRIPTION:
*		Handles reading/writing of data by writing all data to consecutive
*		locations and indexing it within another file

*
*	NOTES:
*
*
* \brief
*		Handles reading/writing of data.
*
* \file
*		PVFS_IndexedDataFile.h
*
* \author
*		Eric Akers
*
* \date
*		11/18/2010 9:00:00 AM
*
* Copyright (C) 2007 Pinnacle Technology, Inc
*//****************************************************************************/

/*-----------------------------------------------------------------------------
*                                 INCLUDE(FILES)
*-----------------------------------------------------------------------------*/
//#include <QtConcurrent/QtConcurrent>  // QT 5.2
#include <QtConcurrentRun>
#include <QFuture>

#include <algorithm>
#include <math.h>
#include <string.h>

#include <pinnacle.h>
#include <high_time.h>
#include <PALlib/PVFS/pvfs.h>
#include <PALlib/math/math.h>

#include <PALlib/datafile/linear/PVFS_WriteCache.h>

#include <LoggingMacros.h>

/*-----------------------------------------------------------------------------
*                                TYPES
*-----------------------------------------------------------------------------*/


/*-----------------------------------------------------------------------------
*                                CONSTANTS/MACROS
*-----------------------------------------------------------------------------*/


/*-----------------------------------------------------------------------------
*                                FUNCTIONS
*-----------------------------------------------------------------------------*/

using namespace pvfs;

/** PVFS_WriteCache.
  * \param seekToEnd
  *     If true, when writing data to the file, it will seek to the end before writing it.
  *     This is the default and is needed if doing both reading and writing at the same time.
  *     This should be false if no reading is being done while writing the file. Can be
  *     useful if trying to overwrite a file that already exists when seeking to the end
  *     will do the opposite of what you want.
  */
PVFS_WriteCache::PVFS_WriteCache ( uint32 blockSize, bool asynchronous, bool seekToEnd )
{
	m_BlockSize			= blockSize * 2; // For extra protection - double the size
	m_FlushBlockSize	= blockSize;
	m_CacheIndex		= 0;
	m_CurIndex			= 0;
	m_Cache [ 0 ]		= new uint8 [ m_BlockSize ];
	m_File				= nullptr;
	m_Asynchronous		= asynchronous;
	m_SeekToEnd         = seekToEnd;
	//m_Asynchronous		= false;


	if ( asynchronous )
	{
		// Only need double buffer if asynchronous mode
		m_Cache [ 1 ]		= new uint8 [ m_BlockSize ];
	}
}

PVFS_WriteCache::~PVFS_WriteCache ()
{
	delete [] m_Cache [ 0 ];
	if ( m_Asynchronous )
	{
		delete [] m_Cache [ 1 ];
	}
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Tell
*
*	DESCRIPTION:
*		Tells the location of the next byte to be written (added)
*		in the cache. This number is useful for determining the index
*		of the next item added in some file. The value must be added
*		to the size of the file it will be added to.
*
*		NOTE: If the cache is currently being written to the same file,
*		the size of the file could be (and probably is) incorrect. You can solve
*		this by calling Wait before Tell, then getting the size of the file,
*		or first make sure it is not writing by calling IsWriting(), or keep track
*		some other method.
*
*	\return The location in the cache of the next byte to be written (added)
*
*	\brief
*		Returns the location in the cache of the next byte to be written (added)
*
*//******************************************************/
sint64 PVFS_WriteCache::Tell()
{
	return m_CurIndex;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		IsWriting
*
*	DESCRIPTION:
*		Tells whether a thread is currently writing the cache
*
*	\brief
*		Tells whether a thread is currently writing the cache
*
*//******************************************************/
bool PVFS_WriteCache::IsWriting() const
{
	return m_Result.isRunning();
}


/*!*****************************************************
*	PROCEDURE NAME:
*		AddValue
*
*	DESCRIPTION:
*		Adds a value to the cache
*
*	\param value The value to add
*	\return OK: No errors
*		FULL: Add was successful, but the cache is now full
*		FAIL: The add was unsuccessful, the value is not in the cache
*
*	\brief
*		Adds a value to the cache
*
*//******************************************************/
PVFS_WriteCache::Result PVFS_WriteCache::AddValue ( const uint8 * data, uint32 size )
{
	uint32 newSize = size + m_CurIndex;
	if ( newSize >= m_BlockSize )
	{
		return PVFS_WriteCache::FAIL;
	}

	m_Mutex.lock();

	// Copy the data
	memcpy ( &(m_Cache[ m_CacheIndex ][ m_CurIndex ]), data, size );

	// Update the index
	m_CurIndex = newSize;

	m_Mutex.unlock();

	if ( newSize >= m_FlushBlockSize )
	{
		return PVFS_WriteCache::FULL;
	}
	else
	{
		return PVFS_WriteCache::SUCCESS;
	}
}



/*!*****************************************************
*	PROCEDURE NAME:
*		Write
*
*	DESCRIPTION:
*		Write data to the cache and wait if necessary for the operation
*		to finish. Waiting only occurs when both caches are full.
*
*		NOTE:	In order to use this function, the file to write to must
*				already be set using SetFile function.
*
*	\param value The buffer to write
*	\param size The size of the buffer
*	\param cache Which cache to write to
*	\return True if the cache had to be flushed, false otherwise
*
*	\brief
*		Write data to the cache and wait if necessary
*	\sa SetFile()
*
*//******************************************************/
bool PVFS_WriteCache::Write ( const uint8 * value, uint32 size )
{

	switch ( AddValue ( value, size ) )
	{
	case PVFS_WriteCache::SUCCESS:
		break; // Hopefully this one happens more than the others

	case PVFS_WriteCache::FULL:

		// Write the cache and move on. If it returns an error because it is already
		// writing the cache, then we still have space in the cache to try again
		// next time
		if ( WriteCacheToFile () == PVFS_WriteCache::SUCCESS )
		{
			return true;
		}
		else
		{
			return false;
		}

	case PVFS_WriteCache::FAIL:
		// This is no good, we must wait until it is finished writing
		m_Mutex.lock();
		{
			Wait(); // If something is wrong, this could hang. Oh well, it would have to die somewhere
		}m_Mutex.unlock();

		WriteCacheToFile ();

		// Try again
		Write ( value, size );
		return true;
	}

	return false;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		PVFS_WriteCacheToFile
*
*	DESCRIPTION:
*		Writes the cache to the file at the end of the file.  Clears
*		the cache. The file must be set with the SetFile function.
*
*	\return SUCCESS: Everything okee dokee
*		FAIL: Write could not occur because the previous cache has not been written yet
*
*	\brief
*		Writes the cache
*
*//******************************************************/
PVFS_WriteCache::Result PVFS_WriteCache::WriteCacheToFile ()
{
	return WriteCacheToFile ( m_File );
}


/*!*****************************************************
*	PROCEDURE NAME:
*		PVFS_WriteCacheToFile
*
*	DESCRIPTION:
*		Writes the cache to the given file at the end of the file.  Clears
*		the cache
*
*	\param file The PVFS file to write to
*	\return SUCCESS: Everything okee dokee
*		FAIL: Write could not occur because the previous cache has not been written yet
*
*	\brief
*		Writes the cache to the given file
*
*//******************************************************/
PVFS_WriteCache::Result PVFS_WriteCache::WriteCacheToFile ( PVFS_file_handle_t * file )
{
	Result result;

	m_Mutex.lock();
	{
		result	= DoWriteCacheToFile ( file );
	}m_Mutex.unlock();

	return result;
}


PVFS_WriteCache::Result PVFS_WriteCache::DoWriteCacheToFile ( PVFS_file_handle_t * file )
{
	uint32 size;


	if ( IsWriting() || file == nullptr )
	{
		return FAIL;
	}

	size		= m_CurIndex;
	m_CurIndex	= 0;

	uint8 oldCacheIndex = m_CacheIndex;
	if ( m_Asynchronous )
	{
		// Non-asynchronous only uses one of the buffers
		if ( m_CacheIndex == 0 )
		{
			m_CacheIndex = 1;
		}
		else
		{
			m_CacheIndex = 0;
		}

		m_Result =
				QtConcurrent::run ( PVFS_WriteCache::WriteCacheAsync,
									file, m_Cache[oldCacheIndex], size, m_SeekToEnd );
	}
	else
	{
		// Just write it directly without bothering with the thread
		WriteCacheAsync ( file, m_Cache [ oldCacheIndex ], size, m_SeekToEnd );
	}

	return SUCCESS;
}

// Separate Thread function
void PVFS_WriteCache::WriteCacheAsync ( PVFS_file_handle_t * file, uint8 * cache, uint32 size, bool seekToEnd )
{
	sint64 rv;
	if(file != nullptr){
		PVFS_lock ( file->vfs );
		//PVFS_lock_file ( file );

		if ( seekToEnd )
		{
			rv = PVFS_seek ( file, file->info.size );	// Jump to the end of the file.
			if ( rv < 0 )
			{
				GFLOG_E(QString("PVFS_seek failed: rv = [%1]").arg(rv));
			}
		}

		if ( (rv = PVFS_write ( file, cache, size )) <= 0 && size > 0 )
		{
			GFLOG_E(QString("Error writing cache: size = [%1]; wrote = [%2]").arg(size).arg(rv));
		}

		// Flush the file here so we can keep track of exactly where we are in the file
		PVFS_flush ( file );

		//PVFS_unlock_file ( file );
		PVFS_unlock ( file->vfs );
	}
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Wait
*
*	DESCRIPTION:
*		Blocks until the asynchronous write is finished.
*		Useful if PVFS_WriteCache returned fail, which means that the cache
*		is already being written.
*
*
*	\brief
*		Blocks until the asynchronous write is finished
*
*//******************************************************/
void PVFS_WriteCache::Wait()
{
	//m_Mutex->Lock();

	if ( m_Result.isFinished() == false )
	{
		m_Result.waitForFinished();
	}
	//m_Mutex->UnLock();
}

/*!*****************************************************
*	PROCEDURE NAME:
*		Flush
*
*	DESCRIPTION:
*		Flushes all buffers of the cache to the file
*
*
*	\brief
*		Flushes all buffers of the cache to the file
*
*//******************************************************/
bool PVFS_WriteCache::Flush (bool waitForFinish)
{
	if ( m_File == nullptr ) return false;
	if ( m_CurIndex == 0 )
	{
		return true;
	}

	m_Mutex.lock();
	{
		// Just in case we are already writing
		Wait();
	}m_Mutex.unlock();

	WriteCacheToFile ();

	if ( waitForFinish )
	{
		m_Mutex.lock();
		{
			Wait();
		}m_Mutex.unlock();
	}

	return true;
}
