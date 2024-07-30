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
*		11/11/2010 9:00:00 AM
*
* Copyright (C) 2007 Pinnacle Technology, Inc
*//****************************************************************************/

/*-----------------------------------------------------------------------------
*                                 INCLUDE(FILES)
*-----------------------------------------------------------------------------*/
#include <QtConcurrentRun>
#include <QFuture>
#include <QByteArray>


#include <algorithm>
#include <math.h>

#include <pinnacle.h>
#include <high_time.h>
#include <PALlib/PALlib_Globals.h>
#include <Pvfs.h>
#include <PALlib/math/math.h>
#include <PALlib/datafile/linear/PVFS_IndexedDataFile.h>
#include <PALlib/database/experiment/ExperimentDatabase.h>
#include <Util/CRC32.h>


/*-----------------------------------------------------------------------------
*                                TYPES
*-----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                CONSTANTS/MACROS
*-----------------------------------------------------------------------------*/

const sint32	IndexedDataFileCache::ALL_POINTS						= -1;
const uint8		IndexedDataFileCache::UNIQUE_MARKER_BYTE				= 0xA5;



const uint32	PVFS_IndexedDataFile::DEFAULT_CACHE_SIZE = sizeof(float) * 10000;//2500;
const uint32	PVFS_IndexedDataFile::INDEXED_DATA_FILE_MAGIC_NUMBER	= 0XFF01FF01;
const uint32	PVFS_IndexedDataFile::INDEXED_DATA_FILE_VERSION			= 1;
const QString	PVFS_IndexedDataFile::INDEX_EXTENSION					= ".index";
const QString	PVFS_IndexedDataFile::DATA_EXTENSION					= ".idat";
const uint32	PVFS_IndexedDataFile::INDEX_HEADER_SIZE					= 1000;



/*-----------------------------------------------------------------------------
*                                FUNCTIONS
*-----------------------------------------------------------------------------*/




/*-----------------------------------------------------------------------------
*                                IndexedDataFileCache
*-----------------------------------------------------------------------------*/

using namespace pvfs;


/*!*****************************************************
*	PROCEDURE NAME:
*		IndexedDataFileCache
*
*	DESCRIPTION:
*		Constructor
*
*	\param indexFile The file handle to the index file
*	\param dataFile The file handle to the data file
*	\param seconds The time between time stamps
*	\param cacheSize The block size of the cache to use
*
*	\brief
*		Gets the data from the desired time span
*
*//******************************************************/
IndexedDataFileCache::IndexedDataFileCache(std::shared_ptr<pvfs::PvfsFileHandle> indexFile, std::shared_ptr<PvfsFileHandle> dataFile, uint32 cacheSize, bool async_cache, bool overwrite ):
    m_IndexFileWriteCache ( cacheSize, async_cache, overwrite ),
    m_DataFileWriteCache ( cacheSize, async_cache, overwrite ),
    m_IndexFileReadCache ( cacheSize, indexFile ),
    m_DataFileReadCache ( cacheSize, dataFile ),
    m_TimeStampInterval ( (sint64)10 ),
    m_PreviousTimeStamp ( -1, 0.0 ),
    m_NextTimeStamp ( -1, 0.0 )
{
    m_DataFile				= dataFile;
    m_IndexFile				= indexFile;

    m_TimeStampSize			= 44; // according to specs
    m_HeaderSize			= 1000; // according to specs
    m_DataChunkHeaderSize	= 36; // ditto
    m_DataChunkHeaderSizeBeforeData	= 32; // 32 bytes before data section

    m_DataFileIndex			= 0;
    m_StartTimeSet			= false;
    m_PreviousNAN			= false;
    m_Modified				= false;
    m_NeedsFirstTimeStamp	= true;

    m_DataRate				= 1;
    m_DeltaTime				= cpHighTime ( 1.0, 0.0 );
    m_MaxDelta				= cpHighTime ( 2.0 );

    // Set the files for the caches to use
    m_IndexFileWriteCache.SetFile ( m_IndexFile );
    m_DataFileWriteCache.SetFile ( m_DataFile );
}

IndexedDataFileCache::~IndexedDataFileCache()
{
    Close();
}



/*!*****************************************************
*	PROCEDURE NAME:
*		Close
*
*	DESCRIPTION:
*		Closes all the files used by the cache
*
*
*
*	\brief
*		Closes all the files used by the cache
*
*//******************************************************/
void IndexedDataFileCache::Close()
{
    //The file should not be closed at this point.  The problem is that IndexedDataFileCache and PVFS_IndexedDataFile both
    //contain member variables m_DataFile and m_IndexDataFile.  If we close the file here and null the pointers, then when
    //PVFS_IndexedDataFile close is executed, its version of m_DataFile and m_IndexedDataFile are not null, but the pointers
    //are no longer valid (segfault).  Commenting out the code below simply lets the file be closed when PVFS_IndexedDataFile
    //closes.  There is no change in behavior and no additional memory leaks for time segmented files that I can see - dj 5/2/19
    /*	if ( m_DataFile != nullptr )
    {
        PVFS_fclose ( m_DataFile );
        PVFS_fclose ( m_IndexFile );
        m_DataFile	= nullptr;
        m_IndexFile	= nullptr;
    } */
}



/*!*****************************************************
*	PROCEDURE NAME:
*		FinalizeTimeStamps
*
*	DESCRIPTION:
*		Finalizes the time stamps in the index file. This
*		requires placing the final time stamp where it should be
*		with a NAN value for the data. If this is not called, the
*		index file could be in an undetermined state and may lose
*		data points
*
*
*
*	\brief
*		Finalizes the time stamps in the index file
*
*//******************************************************/
cpHighTime IndexedDataFileCache::FinalizeTimeStamps()
{
    cpHighTime lastTime = m_PreviousTimeStamp + m_DeltaTime;
    m_BlockLog = true;
    Append ( lastTime, NAN );
    m_BlockLog = false;

    return lastTime;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		IsModified
*
*	DESCRIPTION:
*		Tells whether the file has been modified (written to) or not
*
*
*	\return true if the file has been modified, false otherwise
*
*	\brief
*		Tells whether the file has been modified (written to) or not
*
*//******************************************************/
bool IndexedDataFileCache::IsModified() const
{
    return m_Modified;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		SetTimeRange
*
*	DESCRIPTION:
*		Sets the start and end time of the file
*
*
*	\param startTime The start time of the file
*	\param endTime The end time of the file
*
*	\brief
*		Sets the start and end time of the file
*
*//******************************************************/
void IndexedDataFileCache::SetTimeRange ( const cpHighTime & startTime, const cpHighTime & endTime )
{
    m_StartTime				= startTime;
    m_EndTime				= endTime;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		SetZeroTime
*		GetZeroTime
*
*	DESCRIPTION:
*		Sets/Gets the zero time of the file. Zero Time is used when retrieving
*		data as an offset to modify the time stamp of data by. This allows
*		multiple devices to use the same zero time.
*
*		Default zero time is 0.0
*
*	\param zeroTime The time to use as zero time
*
*	\brief
*		Sets/Gets the zero time of the file
*
*//******************************************************/
void IndexedDataFileCache::SetZeroTime ( const cpHighTime & zeroTime )
{
    m_ZeroTime = zeroTime;
}

cpHighTime IndexedDataFileCache::GetZeroTime () const
{
    return m_ZeroTime;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetStartTime
*
*	DESCRIPTION:
*		Returns the start time of the file
*
*	\param start Stores the start time of the file
*	\return true if a start time has been set in which case start will contain the time,
*			false otherwise
*
*	\brief
*		Returns the start time of the file
*
*//******************************************************/
bool IndexedDataFileCache::GetStartTime( cpHighTime & start ) const
{
    if ( m_StartTimeSet )
    {
        start = m_StartTime;
    }

    return m_StartTimeSet;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetLastIndexTimeStamp
*
*	DESCRIPTION:
*		Returns the last time written to the index file.
*		When acquiring data, this is essentially the current end time
*		of the file.
*
*	\param lastTime
*			The last time stamp written to the index file
*	\return
*			true if a time has been set in which case lastTime will contain the time,
*			false otherwise
*
*	\brief
*		Returns the last time written to the index file
*
*//******************************************************/
bool IndexedDataFileCache::GetLastIndexTimeStamp ( cpHighTime & lastTime ) const
{
    // If a start time has been set, then we also have a last time, because it gets set
    // at the same time
    if ( m_StartTimeSet )
    {
        lastTime	= m_PreviousTimeStamp + m_DeltaTime;
    }

    return m_StartTimeSet;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		SetDataRate
*
*	DESCRIPTION:
*		Sets the data rate
*
*
*	\brief
*		Sets the data rate
*
*//******************************************************/
void IndexedDataFileCache::SetDataRate ( float dataRate )
{
    if(dataRate == 0.)return; //Bio Channels sometimes return datarate = 0;
    m_DataRate = dataRate;
    m_DeltaTime = 1.0 / dataRate;
    m_MaxDelta = m_DeltaTime * 2.0;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Flush
*
*	DESCRIPTION:
*		Flushes all the write caches
*
*	\brief
*		This sets the start position to read from in the file (cache)
*//******************************************************/
void IndexedDataFileCache::Flush(bool waitForFlush)
{
    m_WriteMutex.lock ();

    // The write caches are double buffered - so make sure to get both
    m_IndexFileWriteCache.Flush ( waitForFlush );
    m_DataFileWriteCache.Flush ( waitForFlush );

    m_WriteMutex.unlock ();
}



/*!*****************************************************
*	PROCEDURE NAME:
*		SetTimeStampInterval
*		GetTimeStampInterval
*
*	DESCRIPTION:
*		Sets/Gets the interval between time stamps
*
*	\brief
*		Sets/Gets the interval between time stamps
*//******************************************************/
void IndexedDataFileCache::SetTimeStampInterval ( const cpHighTime & interval )
{
    m_TimeStampInterval = interval;
}

cpHighTime IndexedDataFileCache::GetTimeStampInterval () const
{
    return m_TimeStampInterval;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		Start
*
*	DESCRIPTION:
*		Used for traversing the file in sequence. This sets the start position
*		to read from in the file (cache)
*
*	\param startTime The time stamp of the point to start at. The point found
*					 will not be less than the given time
*	\return True if the starting point could be found, false otherwise
*
*	\brief
*		This sets the start position to read from in the file (cache)
*//******************************************************/
bool IndexedDataFileCache::Start ( const cpHighTime & startTime )
{
    uint32 offset		=	0;

    sint64 indexFileLoc = FindTimeStampIndex ( startTime );
    if ( indexFileLoc < 0 )
    {
        return false;
    }

    // Start the index file traversing
    Start ( indexFileLoc );

    // Retrieve the first time stamp
    GetNextTimeStamp ( m_NextTimeStamp, m_NextTimeStampIndex ); // Assume this works - it should

    // Use this to do the dirty work
    if ( StartNextSequence() )
    {
        // We are currently at the start of time stamp sequence, not necessarily
        // the time we want. We might need to shift over to the right
        if ( m_CurTimeInSequence < startTime )
        {
            offset = ceil((startTime - m_CurTimeInSequence).ToRational() / m_SequenceDeltaTime.ToRational());
            m_CurPointInSequence = offset;
            m_CurTimeInSequence += m_SequenceDeltaTime * offset;
            m_DataFileSequenceIndex += offset * sizeof ( float );
        }
        return true;
    }
    else
    {
        return false;
    }
}


/*!*****************************************************
*	PROCEDURE NAME:
*		StartNextSequence
*
*	DESCRIPTION:
*		Used for traversing the file in sequence. This sets the start position
*		to read from in the file (cache)
*
*	\return true if the starting point could be found, false otherwise
*
*	\brief
*		This sets the start position to read from in the file (cache)
*//******************************************************/
bool IndexedDataFileCache::StartNextSequence ()
{
    sint64 dataFileIndex2		=	0; // Stores the location of the data file index
    cpHighTime timeStamp2; // Stores the time of the next time stamps
    cpHighTime tmp;

    // Determine the next time stamp
    if ( GetNextTimeStamp ( timeStamp2, dataFileIndex2 ) < 0 )
    {
        return false;
    }

    // Determine the number of points in this sequence
    if ( dataFileIndex2 > m_DataChunkHeaderSize + m_NextTimeStampIndex )
    {
        m_NumPointsInSequence = (dataFileIndex2 - m_NextTimeStampIndex - m_DataChunkHeaderSize) / sizeof ( float );
    }
    else
    {
        m_NumPointsInSequence = 0;
    }
    m_CurPointInSequence = 0;

    // Determine the delta time between the points
    tmp					= timeStamp2 - m_NextTimeStamp;
    m_SequenceDeltaTime	= tmp / m_NumPointsInSequence;


    // Reset the next time stamp info
    m_CurTimeInSequence = m_NextTimeStamp;
    m_DataFileSequenceIndex = m_NextTimeStampIndex + m_DataChunkHeaderSizeBeforeData;
    m_NextTimeStamp = timeStamp2;
    m_NextTimeStampIndex = dataFileIndex2;

    return true;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetNextPoint
*
*	DESCRIPTION:
*		Gets the next point in the sequence. Start must be called before
*		a sequence can be started
*
*	\param timeStamp Stores the time of the point just read
*	\param value Stores the value of the point read
*	\return The next index in the data file on success, negative values indicating error
*
*	\brief
*		Gets the next point in the sequence
*//******************************************************/
sint32 IndexedDataFileCache::GetNextPoint ( cpHighTime & timeStamp, float & value )
{
    if ( m_CurPointInSequence >= m_NumPointsInSequence )
    {
        // Start the next sequence
        if ( !StartNextSequence() )
        {
            return -1;
        }
    }

    // Increment the current point. This must be done after StartNextSequence is called
    m_CurPointInSequence++;

    // Read the data value
    if ( m_DataFileReadCache.ReadItem<float> ( m_DataFile, m_DataFileSequenceIndex, value ) <= 0 )
    {
        // This should not occur unless something has gone badly - maybe the data cache has
        // not been flushed?
        m_NumPointsInSequence = 0;
        m_CurPointInSequence = 0;
        return -1;
    }

    // Update the time value
    timeStamp = m_CurTimeInSequence;
    m_CurTimeInSequence += m_SequenceDeltaTime;

    // Don't forget to update the location in the index file
    m_DataFileSequenceIndex += sizeof ( float );

    return m_DataFileSequenceIndex;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetNextChunk
*
*	DESCRIPTION:
*		Gets the next chunk of points in the sequence. Start must be called before
*		a sequence can be started. The chunk size is determined by the time stamps,
*		a chunk is an entire set of points within two time stamps.
*
*	\param start Stores the start time of the chunk
*	\param end Stores the end time of the chunk
*	\param data The list from which to store the data values
*	\return The next index in the data file on success, negative values indicating error
*
*	\brief
*		Gets the next point in the sequence
*//******************************************************/
sint32 IndexedDataFileCache::GetNextChunk ( cpHighTime & start, cpHighTime & end, QList<float> & data )
{
    if ( m_CurPointInSequence >= m_NumPointsInSequence )
    {
        // Start the next sequence
        if ( !StartNextSequence() )
        {
            return -1;
        }
    }


    // Read the number of points left in the sequence
    uint32 numPoints = m_NumPointsInSequence - m_CurPointInSequence;
    if ( m_DataFileReadCache.ReadMultipleItems ( m_DataFile, m_DataFileSequenceIndex, numPoints, data ) < 0 )
    {
        // This should not occur unless something has gone badly - maybe the data cache has
        // not been flushed?
        m_NumPointsInSequence = 0;
        m_CurPointInSequence = 0;
        return -1;
    }

    // Set the start and end times of the chunk
    start	= m_CurTimeInSequence;
    end		= m_CurTimeInSequence + m_SequenceDeltaTime * ( numPoints - 1 );

    // Update the items for the next sequence
    m_CurPointInSequence = m_NumPointsInSequence;

    return m_DataFileSequenceIndex + ( numPoints * sizeof( float ) );
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetNextChunkDS
*
*	DESCRIPTION:
*		Gets the next chunk of points in the sequence. Start must be called before
*		a sequence can be started. The chunk size is determined by the time stamps,
*		a chunk is an entire set of points within two time stamps.
*
*	\param start Stores the start time of the chunk
*	\param end Stores the end time of the chunk
*	\param data The list from which to store the data values
*	\return The next index in the data file on success, negative values indicating error
*
*	\brief
*		Gets the next point in the sequence
*//******************************************************/
sint64 IndexedDataFileCache::GetNextChunkDS (cpHighTime & start, cpHighTime & end, QList<float>& data )
{
    if ( m_CurPointInSequence >= m_NumPointsInSequence )
    {
        // Start the next sequence
        if ( !StartNextSequence() )
        {
            return -1;
        }
    }


    // Read the number of points left in the sequence
    uint32 numPoints = m_NumPointsInSequence - m_CurPointInSequence;
    if ( m_DataFileReadCache.ReadSomeFloats( m_DataFile, m_DataFileSequenceIndex, numPoints, data ) < 0 )
    {
        // This should not occur unless something has gone badly - maybe the data cache has
        // not been flushed?
        m_NumPointsInSequence = 0;
        m_CurPointInSequence = 0;
        return -1;
    }

    // Set the start and end times of the chunk
    start	= m_CurTimeInSequence;
    end		= m_CurTimeInSequence + m_SequenceDeltaTime * ( numPoints - 1 );

    // Update the items for the next sequence
    m_CurPointInSequence = m_NumPointsInSequence;

    return m_DataFileSequenceIndex + ( numPoints * sizeof( float ) );
}



/*!*****************************************************
*	PROCEDURE NAME:
*		GetData
*
*	DESCRIPTION:
*		Gets the data from the desired time span
*
*
*	\brief
*		Gets the data from the desired time span
*
*//******************************************************/
sint32 IndexedDataFileCache::GetData ( const cpHighTime &start_time, const cpHighTime &end_time, ComplexMathArray &tData, ComplexMathArray &yData, sint32 channel, sint32 points )
{
    double			actualEndTime2		=	0.0;
    double			curTime2			=	0.0;
    sint64			rv					=	0;
    REAL			dt;
    double			di					=	1.0;
    uint			idi;
    uint32_t		chunk_size;
    COMPLEX *		y_ptr				=	nullptr;
    COMPLEX *		t_ptr				=	nullptr;
    uint			i					=	0;
    uint32			count				=	0;

    // Initialize everything.
    yData.Clear();
    tData.Clear();

    // Input error handling.
    if ( start_time > end_time ) return -1;
    if ( start_time > m_EndTime ) return -1;
    if ( end_time < m_StartTime ) return -1;
    if ( points == 0 ) return -1;

    m_ReadMutex.lock();
    {
        // Correct some things.
        m_actualStartTime	= start_time;
        m_actualEndTime     = end_time;
        if ( start_time < m_StartTime )
        {
            m_actualStartTime = m_StartTime;
        }
        if ( end_time > m_EndTime )
        {
            m_actualEndTime	= m_EndTime;
        }

        // Check so that we do not read more points than necessary.
        if ( points != ALL_POINTS )
        {
            m_readTimeSpan = m_actualEndTime - m_actualStartTime;

            // If di < 1 then we should just plot all of the points.
            di = ( m_readTimeSpan.ToRational() * m_DataRate ) / ((double) points );
            if ( di < 1 )
            {
                di = 1.0;
            }
            else
            {
                // We need this to be an integer value here
                // This rounding is baised towards rounding up - less total points
                di	= floor ( di + 0.5 );
            }
        }
        idi = static_cast<uint>(di);  //just to be sure

        // Start the sequential access of points at the start time
        //{
        if ( Start ( m_actualStartTime ) == false )
        {
            m_ReadMutex.unlock();
            return -1;
        }

        rv = GetNextChunkDS ( m_chunkStart, m_chunkEnd, m_FloatDS );

        // Expand to as close as possible.
        double num_chunks = (m_actualEndTime - m_actualStartTime).ToRational() / ( m_chunkEnd - m_chunkStart ).ToRational();

        if(rv == -1){
            m_ReadMutex.unlock ();
            return -1;
        }


//		chunk_size = m_FloatDS.count();
//		if ( chunk_size < 10 ) chunk_size = 10;
//		sint64 total_points = (num_chunks+1) * chunk_size;
//		if ( total_points > points )
//		{
//			total_points = points;
//		}
        int single_point_chunk_count = 0;
        while ( m_chunkStart < m_actualEndTime && rv >= 0 )
        {
            // Determine the delta between the points

            chunk_size = m_FloatDS.count();
            if ( chunk_size > 1 )
            {
                dt = (m_chunkEnd - m_chunkStart).ToRational() / (chunk_size - 1);
                dt *= di;
            }
            else
            {
                // There is only a single point in the chunk (NAN or forced timestamp)
                dt = 0.0;
                if(++single_point_chunk_count < idi)
                {
                    rv = GetNextChunkDS ( m_chunkStart, m_chunkEnd, m_FloatDS );
                    if(rv == -1){
                        m_ReadMutex.unlock();
                        return -1;
                    }
                    continue;
                }
                else
                {
                    single_point_chunk_count = 0;
                }
            }

            m_curTime = m_chunkStart;

            curTime2 = (m_curTime - m_ZeroTime).ToRational();

            actualEndTime2 = (m_actualEndTime - m_ZeroTime).ToRational();



            count = 0;
            for ( i=0; i < chunk_size; i += idi )
            {
                if ( curTime2 >= actualEndTime2 )	// Drop the last point.
                {
                    break;
                }
                COMPLEX y_val;
                y_val.r = m_FloatDS[ i ];
                y_val.i = 0;
                yData.Append(y_val);

                COMPLEX t_val;
                t_val.r = curTime2;
                t_val.i = 0;
                tData.Append(t_val);

                curTime2 += dt;
            }


            rv = GetNextChunkDS ( m_chunkStart, m_chunkEnd, m_FloatDS );
            if(rv == -1){
                m_ReadMutex.unlock();
                return -1;
            }
        }
    }m_ReadMutex.unlock();

    return 0;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		Start
*
*	DESCRIPTION:
*		Used for traversing the index file in sequence. This sets the start position
*		from which to read in the file (read cache)
*		NOTE: The location must be at the start of an index - otherwise
*		this will break (with much fireworks)
*
*
*	\brief
*		This sets the start position to read from in the file (cache)
*//******************************************************/
void IndexedDataFileCache::Start ( sint64 location )
{
    m_SequentialIndex = location;
}

sint64 IndexedDataFileCache::GetNextTimeStamp_old ( cpHighTime & timeStamp, sint64 & dataIndex, bool forward )
{
    // Read the time stamp at the given index
    high_time_t curTime;
    if ( ReadTimeStamp ( m_SequentialIndex, curTime, dataIndex ) < 0 )
    {
        return -1;
    }

    // Save the current time
    timeStamp = curTime;

    // Update the index to read from next time
    sint64 curIndex = m_SequentialIndex;
    if ( forward )
    {
        m_SequentialIndex += m_TimeStampSize;
    }
    else
    {
        m_SequentialIndex -= m_TimeStampSize;
    }

    return curIndex;
}

sint64 IndexedDataFileCache::GetNextTimeStamp ( cpHighTime & timeStamp, sint64 & dataIndex, bool forward )
{
    if ( m_CurrentIndex >= m_Indii.count()) return -1;

    m_IndexEntry		= m_Indii [ m_CurrentIndex ];
    timeStamp			= m_IndexEntry.start_time;
    dataIndex			= m_IndexEntry.data_location;

    if ( forward )
    {
        m_CurrentIndex++;
    }
    else
    {
        m_CurrentIndex--;
        if ( m_CurrentIndex < 0 )
        {
            m_CurrentIndex = 0;
        }
    }
    return m_IndexEntry.my_location;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetConsectutiveTimeStamps
*
*	DESCRIPTION:
*		Gets two consecutive time stamp from the given location.
*		Checks to make sure both time stamps are within range of the file.
*		If the second time stamp is out of the file, the first time stamp will
*		be moved back.
*
*
*	\param firstLoc The location in the file to read the first time stamp from -
*					must be at a valid time stamp location. If the second time stamp
*					is not within the file, this will be changed to the location read
*	\param firstTime The time stamp at the given location to store
*	\param secondTime The second time stamp to store
*	\return Zero on success, non-zero otherwise
*
*	\brief
*		Gets two consecutive time stamp from the given location.
*//******************************************************/
sint64 IndexedDataFileCache:: GetConsectutiveTimeStamps ( sint64 & firstLoc, cpHighTime & firstTime, cpHighTime & secondTime )
{
    if(m_IndexFile == nullptr)	return -1;
    high_time_t curTime;
    sint64 secondLoc	=	0;
    if ( firstLoc < m_HeaderSize )
    {
        firstLoc = m_HeaderSize;
    }

    secondLoc = firstLoc + m_TimeStampSize;
    if ( secondLoc >= m_IndexFile->info.size )
    {
        // We need to back up the first index
        secondLoc = firstLoc;
        firstLoc -= m_TimeStampSize;
        if ( firstLoc < m_HeaderSize )
        {
            // We do not yet have enough time stamps in the index file
            return -1;
        }
    }

    ReadTimeStamp ( firstLoc, curTime );
    firstTime = curTime;

    ReadTimeStamp ( secondLoc, curTime );
    secondTime = curTime;

    return secondLoc;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		GetLastTimeStamp
*
*	DESCRIPTION:
*		Returns the last time stamp in the index file
*
*
*	\param timeStamp The location to store the last time stamp
*	\return Location of last time stamp on success, negative values on error
*
*	\brief
*		Returns the last time stamp in the index file
*//******************************************************/
sint64 IndexedDataFileCache::GetLastTimeStamp ( cpHighTime & timeStamp )
{
    high_time_t curTime;
    if(m_IndexFile == nullptr)	return -1;
    sint64 loc = (m_IndexFile->info.size - m_HeaderSize) % m_TimeStampSize;
    loc = m_IndexFile->info.size - m_TimeStampSize - loc;

    ReadTimeStamp ( loc, curTime );

    if ( loc < m_HeaderSize )
    {
        return -1;
    }
    else
    {
        timeStamp = curTime;
        return loc;
    }
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetInitialBoundary
*
*	DESCRIPTION:
*		Finds the starting boundary time stamps to perform a binary search on the index file.
*		On return, the first and second parameters will be set to the initial search boundary.
*		The first may or may not be changed, but it must be initialized to the initial guess.
*		NOTE: This function assumes that both the searchTime and firstTime are valid locations
*		that can be found within the current file size.
*
*	\param searchTime The time we are looking for
*	\param firstLoc Initial guess location of the time stamp - must be initialized
*	\param firstTime Initial time found of first guess - must be initialized
*	\param secondLoc Where to store the second guess location - not initialized
*	\param secondTime Where to store the time of the second guess - not initialized
*	\return Zero on succes, non-zero otherwise
*
*	\brief
*		Finds the starting boundary time stamps to perform a binary search on the index file
*//******************************************************/
sint8 IndexedDataFileCache::GetInitialBoundary ( const cpHighTime & searchTime, sint64 & firstLoc, cpHighTime & firstTime, sint64 & secondLoc, cpHighTime & secondTime )
{
    sint64		diffTime	=	0;
    sint64		rv			=	0;
    high_time_t	hTime;
    cpHighTime	prevTime;

    // Must be initialized to the same as firstLoc, see the do-while loop
    secondLoc	= firstLoc;
    secondTime	= firstTime;

    // The finding of the boundary for being either to the left or right of where
    // we want to be is different enough to warrent doing it in separate chunks of
    // code, hence the if statement below. This is a bit more error prone, but I do
    // not know of a better way
    if ( firstTime <= searchTime )
    {
        diffTime = (searchTime - firstTime).ToRational() / m_TimeStampInterval.ToRational();
        if ( diffTime <= 0 )
        {
            diffTime = 1;
        }

        do
        {
            // If we have made a guess for the second location that is still
            // less than the search time, it means both boundaries are less
            // than the time we are looking for, but the current secondLoc
            // will be closer than the firstLoc, so we change firstLoc here.
            // This means that secondLoc and secondTime must be initialized
            // to the first before getting here
            firstLoc	= secondLoc;
            firstTime	= secondTime;

            // Make a new guess
            secondLoc	= diffTime * m_TimeStampSize + firstLoc;
            if(m_IndexFile == nullptr)	return -1;
            if ( (secondLoc + m_TimeStampSize) >= m_IndexFile->info.size )
            {
                secondLoc = GetLastTimeStamp ( secondTime );
                if ( secondTime < searchTime )
                {
                    return -1;
                }
            }
            else
            {
                rv = ReadTimeStamp ( secondLoc, hTime );
                if ( rv < 0 )
                {
                    // The time stamp should fit within the file, so this is a weird error
                    return -1;
                }
                secondTime = hTime;
            }

            // Increase diff time to find the next time stamp for the next go around
            diffTime *= 2;
        } while ( secondTime < searchTime );
    }
    else
    {
        diffTime	= (searchTime - firstTime).ToRational() / m_TimeStampInterval.ToRational();
        prevTime	= firstTime; // To make sure we do not get into infinite loop
        if ( diffTime >= 0 )
        {
            diffTime	= -1;
        }
        do
        {
            // If we have made a guess for the second location that is still
            // greater than the search time, it means both boundaries are greater
            // than the time we are looking for, but the current secondLoc
            // will be closer than the firstLoc, so we change firstLoc here.
            // This means that secondLoc and secondTime must be initialized
            // to the first values before getting here
            firstLoc	= secondLoc;
            firstTime	= secondTime;

            // Make a new guess
            secondLoc	= diffTime * m_TimeStampSize + firstLoc;
            if ( secondLoc < m_HeaderSize )
            {
                secondLoc	= m_HeaderSize;
            }

            rv = ReadTimeStamp ( secondLoc, hTime );
            if ( rv < 0 )
            {
                return -1; // Do not know why this would happen and I hope it doesn't
            }

            secondTime	= hTime;
            if ( prevTime < secondTime )
            {
                // Bad things man
                return -1;
            }
            prevTime	= secondTime;

            // Increase diff time to find the next time stamp
            diffTime *= 2;
        } while ( secondTime > searchTime );

        // The first and last time stamps are reversed in this case
        std::swap ( secondLoc, firstLoc );
        std::swap ( secondTime, firstTime );
    }

    return 0;
}


sint64 IndexedDataFileCache::CalcMiddlePoint ( const sint64 & firstLoc, const sint64 & secondLoc )
{
    sint64 middleLoc = secondLoc - firstLoc; // Number of stamps between the two
    middleLoc >>= 1; // Divide by two (midway point)
    middleLoc /= m_TimeStampSize; // Must make sure it fits on the boundary
    middleLoc = firstLoc + middleLoc * m_TimeStampSize;

    return middleLoc;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		FindTimeStampIndex
*
*	DESCRIPTION:
*		Finds the index of the given time stamp in the index file. This
*		is used as a precursor to finding points in the data file. The time
*		time stamp found will always be before the given time, so the point
*		requested will be somewhere between the found time stamp and the next
*		time stamp
*
*	\param timeStamp The time of the time stamp to look for
*	\return Index where time stamp exists within the index file, less than zero indicating error
*
*	\brief
*		Finds the index of the given time stamp in the index file.
*//******************************************************/
sint64 IndexedDataFileCache::FindTimeStampIndex_old ( const cpHighTime & timeStamp )
{
    // Make sure the requested time is within the file
    if ( timeStamp < m_StartTime || timeStamp > m_EndTime )
    {
        return -1;
    }

    sint64		firstLoc	=	0; // Left location in binary search
    sint64		secondLoc	=	0; // Right location in binary search
    sint64		middleLoc	=	0; // You guessed it, the middle point!
    sint64		temp		=	-1;

    cpHighTime	firstTime;
    cpHighTime	secondTime;
    cpHighTime	middleTime;
    cpHighTime	tempTime;

    high_time_t	hTime; // Used for reading time stamps

    // Guesstimate where we think the time stamp is
    sint64 diffTime			=	0;

    diffTime	= (timeStamp - m_StartTime).ToRational() / m_TimeStampInterval.ToRational();
    firstLoc	= diffTime * m_TimeStampSize + m_HeaderSize;
    if(m_IndexFile == nullptr)	return -1;
    if ( firstLoc >= m_IndexFile->info.size )
    {
        // Guess is too large - find the second to last (or more) time stamp
        temp		= firstLoc - m_IndexFile->info.size;
        // Number of time stamps to move to get to the second to last. It is calculated
        // this way because there may be junk at the end of the index file if something
        // went wrong. Otherwise, the size of the file minus time stamp size tells
        // me where to go
        temp		= (sint64)ceil ( temp / m_TimeStampSize ) + 2; // plus 2 so we go two more into the past
        firstLoc	-= temp * m_TimeStampSize;
    }

    // Create the two consecutive time stamps that represent where we think the item is
    secondLoc = GetConsectutiveTimeStamps ( firstLoc, firstTime, secondTime );
    if ( secondLoc < 0 )
    {
        // Not enough time stamps in the file
        return -1;
    }
    if ( firstTime <= timeStamp && secondTime >= timeStamp )
    {
        // Our initial guess was perfect
        return firstLoc;
    }

    // Use the first time stamp as one of the boundaries, but find a second time stamp
    // that is close since we know we are close
    if ( GetInitialBoundary ( timeStamp, firstLoc, firstTime, secondLoc, secondTime ) < 0 )
    {
        return -1;
    }

    // Use a binary like search through the time stamps to find the
    // time stamp we are looking for. We pick our initial spots better
    // than the basic binary search, then do a normal search
    while ( true )
    {
        // Get the new middle location to read
        middleLoc = CalcMiddlePoint ( firstLoc, secondLoc );
        if ( middleLoc == temp )
        {
            // The middle location did not change from previous
            return -1;
        }

        // Get the middle time stamps. Do not use GetConsecutiveTimeStamps,
        // it checks to make sure both are within bounds, which we know to
        // be true already
        temp = ReadTimeStamp ( middleLoc, hTime );
        if ( temp < 0 )
        {
            return -1;
        }

        middleTime = hTime;
        temp = ReadTimeStamp ( temp, hTime );
        if ( temp < 0 )
        {
            return -1;
        }
        tempTime = hTime;

        if ( middleTime <= timeStamp && tempTime >= timeStamp )
        {
            // The middle is the stamp we are looking for, and the crowd rejoiced
            return middleLoc;
        }

        // Calculate the new boundaries
        temp = middleLoc;
        if ( middleTime > timeStamp )
        {
            // First location is the same
            secondLoc = middleLoc;
        }
        else
        {
            firstLoc = middleLoc;
        }
    }
}

sint64 IndexedDataFileCache::FindTimeStampIndex ( const cpHighTime & timeStamp )
{
    IndexEntry	entry;
    IndexEntry  last;
    sint64		mid	=	0;
    sint64		beg	=	0;
    sint64		end	=	0;
    sint64		n	=	0;

    // Make sure the requested time is within the file
    if ( m_Indii.isEmpty () ) return -1;

    entry   = m_Indii.first ();
    last    = m_Indii.last ();
    if ( timeStamp < entry.start_time || timeStamp > last.end_time )
    {
        return -1;
    }

    // Full binary search
    beg		= 0;
    n		= m_Indii.count();
    mid		= n/2;
    end		= n+1;

    while ( beg <= end )
    {
        if (mid < m_Indii.count())
        {
            entry = m_Indii [ mid ];
        }
        else
        {
            entry = m_Indii [ m_Indii.count() - 1 ];
        }
        if ( timeStamp.IsBetween(entry.start_time,entry.end_time))
        {
            m_CurrentIndex = mid;
            return entry.my_location;
        }
        else
        {
            if ( timeStamp < entry.start_time )
            {
                end		= mid;
            }
            else
            {
                beg		= mid + 1;
            }
            n		= n/2;
            mid		= beg + n/2;
        }
    }
    m_CurrentIndex = mid;
    return entry.my_location;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		ReadTimeStamp
*
*	DESCRIPTION:
*		Reads the time stamp from the cache at the given location,
*		without also reading the index it points to.  This is useful
*		if you do not need the index data because you are searing for
*		a specific time stamp.
*
*		NOTE: This does not search for the given time stamp, it reads only
*		from the exact location in the file given and assumes the location
*		is the start of a time stamp. If you need to search for a given time,
*		use GetTimeStampIndex
*
*	\param index The index into the index file to read from
*	\param time Where to store the time of the time stamp read
*	\return Location of next timestamp on success, less than zero on failure
*
*	\brief
*		Reads the time stamp from the cache
*//******************************************************/
sint64 IndexedDataFileCache::ReadTimeStamp ( sint64 location, high_time_t & time )
{
    sint32 rv		=	0;
    sint64 curLoc	=	location;

    rv	= ReadUniqueMarker ( &m_IndexFileReadCache, curLoc );
    if ( rv < 0 )
    {
        return rv;
    }
    curLoc += rv;

    rv = m_IndexFileReadCache.ReadItem ( m_IndexFile, curLoc, time.seconds );
    if ( rv < 0 )
    {
        return -1;
    }

    curLoc += rv; // The next item to read will be at this location
    rv = m_IndexFileReadCache.ReadItem ( m_IndexFile, curLoc, time.sub_seconds );
    if ( rv < 0 )
    {
        return -1;
    }

    // Return the index to the next time stamp
    return location + m_TimeStampSize; // We skipped reading the index part of the time stamp
}

/*!*****************************************************
*	PROCEDURE NAME:
*		ReadTimeStamp
*
*	DESCRIPTION:
*		Reads the full time stamp (time and data file index)
*		from the index file cache. Useful when you know where the
*		time stamp is you are looking for.
*
*		NOTE: This does not search for the given time stamp, it reads only
*		from the exact location in the file given and assumes the location
*		is the start of a time stamp. If you need to search for a given time,
*		use GetTimeStampIndex
*
*	\param location The location into the index file to read from
*	\param time Where to store the time of the time stamp read
*	\param dataIndex Where to store the index into the data file
*					 pointed to in the current time stamp
*	\return
*		The index of the next time stamp in the file, or a value less than
*		zero if an error occurred.
*
*	\brief
*		Reads the time stamp from the cache
*//******************************************************/
sint64 IndexedDataFileCache::ReadTimeStamp ( sint64 location, high_time_t & time, sint64 & dataIndex )
{
    sint32 rv		=	0;
    sint64 reserved	=	0;		// Reserved space for later
    uint32 crcFile	=	0;			// crc32 value read from file
    uint32 crcCalc	=	0;			// crc32 calculated from data read from file

    m_CRC32.Reset();

    /* The order is set by the specs - Check the specs for updates on this
      *		Unique Marker -		8 bytes
      *		Time Stamp -		16 bytes
      *		Reserved -			8 bytes
      *		Data File Index -	8 bytes
      *		CRC -				4 bytes
      */

    rv	= ReadUniqueMarker ( &m_IndexFileReadCache, location );
    if ( rv < 0 )
    {
        return rv;
    }
    location += rv;


    // Time stamp
    rv  = m_IndexFileReadCache.ReadItem ( m_IndexFile, location, time.seconds );
    if ( rv < 0 )
    {
        return rv;
    }
    location += rv;

    rv	= m_IndexFileReadCache.ReadItem ( m_IndexFile, location, time.sub_seconds );
    if ( rv < 0 )
    {
        return rv;
    }
    location += rv;

    // Reserved Space
    rv	= m_IndexFileReadCache.ReadItem ( m_IndexFile, location, reserved );
    if ( rv < 0 )
    {
        return rv;
    }
    location += rv;

    // Data Index
    rv	= m_IndexFileReadCache.ReadItem ( m_IndexFile, location, dataIndex );
    if ( rv < 0 )
    {
        return rv;
    }
    location += rv;

    // CRC
    rv	= m_IndexFileReadCache.ReadItem ( m_IndexFile, location, crcFile );
    if ( rv < 0 )
    {
        return rv;
    }
    location += rv;

    // Calculate the CRC from the values read and compare it
    m_CRC32.AppendBytes ( (uint8*)&time.seconds, sizeof(time.seconds) );
    m_CRC32.AppendBytes ( (uint8*)&time.sub_seconds, sizeof(time.sub_seconds) );
    m_CRC32.AppendBytes ( (uint8*)&reserved, sizeof(reserved) );
    crcCalc	= m_CRC32.AppendBytes ( (uint8*)&dataIndex, sizeof(dataIndex) );

    if ( crcCalc != crcFile )
    {
        // Bad crc, do something smart
        return -1; // Smarter than this --- alert the authorities
    }

    return location;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		ReadUniqueMarker
*
*	DESCRIPTION:
*		Checks for the existence of the unique marker at the given location
*
*	\param cache
*		The read cache to get the data from
*	\param location
*		The location to start looking at
*	\return The number of bytes read on success, or less than zero on error
*
*	\brief
*		Checks for the existence of the unique marker at the given location
*//******************************************************/
sint32 IndexedDataFileCache::ReadUniqueMarker ( PVFS_ReadCache * cache, sint64 location )
{
    uint8 byte	=	0;
    if(cache == nullptr)	return -1;
    for ( uint32 i=0; i<8; i++ )
    {
        cache->ReadItem ( location, byte );
        if ( byte != UNIQUE_MARKER_BYTE )
        {
            return -1;
        }
    }

    return 8;
}

void IndexedDataFileCache::ReadAllIndii()
{
    IndexEntry	entry;
    cpHighTime	time;
    cpHighTime	last_time;
    sint64		location				=	0;
    sint64		data_location			=	0;
    sint64		read_location			=	0;
    sint64		last_read_location		=	0;
    sint64		last_data_location		=	0;
    sint64		n						=	0;
    sint64		i						=	0;
    sint64		count					=	0;

    m_Indii.clear();
    m_CurrentIndex	= 0;

    if(m_IndexFile != nullptr){
        n				= (m_IndexFile->info.size - m_HeaderSize) / m_TimeStampSize;
        read_location	= m_HeaderSize;
        last_read_location = read_location;
        last_data_location = 0;
        for ( i = 0 ; i < n; i++, read_location += m_TimeStampSize )
        {
            location = ReadTimeStamp(read_location, time.m_Time, data_location );
            if ( location != - 1 )
            {
                count++;
                if ( count != 1 )
                {
                    entry.start_time		= last_time;
                    entry.end_time			= time;
                    entry.data_location		= last_data_location;
                    entry.my_location		= last_read_location;
                    m_Indii.push_back(entry);
                }
                last_time = time;
                last_read_location = read_location;
                last_data_location = data_location;
            }
        }
        // Make sure we get the last entry in.
        if ( count != 1 )
        {
            entry.start_time		= last_time;
            entry.end_time			= m_EndTime;
            entry.data_location		= last_data_location;
            entry.my_location		= last_read_location;
            m_Indii.push_back(entry);
        }
        QString msg = QString("Number of indicies %1.").arg(m_Indii.size());
        if(m_Indii.size() > 1)PLOG_W(msg);
    }else{
        gpftm("IndexedDataFileCache::ReadAllIndii()  m_IndexFile is nullptr");
    }

}


/*!*****************************************************
*	PROCEDURE NAME:
*		WriteData
*
*	DESCRIPTION:
*		Writes data to the data file and updates file size information
*		and CRC values.
*
*	\param data
*		The data to write
*	\param length
*		The number of bytes in the data
*	\param doCRC
*		True to use 'data' as part of the CRC calculation, flase otherwise
*	\return Zero on success, non-zero otherwise
*
*	\brief
*		Writes data to the data file
*//******************************************************/
sint8 IndexedDataFileCache::WriteData ( const uint8 * data, uint32 length, bool doCRC )
{
    m_DataFileIndex += length; // Keep track of file location

    if ( doCRC )
    {
        m_DataChunkCRC.AppendBytes ( data, length );
    }

    if ( Write ( data, length, m_DataFileWriteCache ) )
    {
        // The data file filled up, we should flush the index file as well
        // Do not wait on the index file though, as this does not cause large problems
        m_IndexFileWriteCache.WriteCacheToFile();
    }

    m_Modified = true;
    return 0;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		WriteUniqueMarker
*
*	DESCRIPTION:
*		Convienence function that writes the unique marker
*		(from specifications) to the given cache.
*
*	\param cache The write cache to write the unique marker to
*
*	\brief
*		Writes the unique marker (from specifications) to the given file
*//******************************************************/
void IndexedDataFileCache::WriteUniqueMarker ( PVFS_WriteCache & cache )
{
    static uint8 markerByte	= UNIQUE_MARKER_BYTE;

    for ( int i=0; i<8; i++ )
    {
        Write ( markerByte, cache );
    }
}

/*!*****************************************************
*	PROCEDURE NAME:
*		WriteTimeStamp
*
*	DESCRIPTION:
*		Writes a time stamp to the index file
*
*	\return Zero on success, non-zero otherwise
*
*	\brief
*		Writes a time stamp to the index file
*//******************************************************/
sint8 IndexedDataFileCache::WriteTimeStamp ( const cpHighTime & time )
{
    sint64		reservedData	= 0;
    bool		flush			= false;
    high_time_t	tmpTime;
    QByteArray	crcBytes;
    uint32		crc				= 0;

    if ( m_IndexFileWriteCache.GetSpaceBeforeFlush() < m_TimeStampSize )
    {
        // We need to perform a flush of both the data file and index file
        flush = true;
    }

    // Order of writing from specifications
    // Unique marker first
    WriteUniqueMarker ( m_IndexFileWriteCache );

    // Write the next bytes in the array for simplified crc checking then
    // write the array into the file
    tmpTime	= time.GetHighTime();
    crcBytes.append ( (char*)&tmpTime.seconds, sizeof(tmpTime.seconds) );
    crcBytes.append ( (char*)&tmpTime.sub_seconds, sizeof(tmpTime.sub_seconds) );
    crcBytes.append ( (char*)&reservedData, sizeof(reservedData) );
    crcBytes.append ( (char*)&m_DataFileIndex, sizeof(m_DataFileIndex) );

    // Calculate the crc and append it to the bytes as well
    crc		= m_DataChunkCRC.CalculateCRC32 ( (uint8*)crcBytes.constData(), crcBytes.size() );
    crcBytes.append ( (char*)&crc, sizeof(crc) );

    Write ( (uint8*)crcBytes.constData(), crcBytes.size(), m_IndexFileWriteCache );

    if ( flush )
    {
        m_DataFileWriteCache.WriteCacheToFile ();
        m_IndexFileWriteCache.WriteCacheToFile ();

        // We need to wait for the operation to finish. We can't have a time
        // stamp without data inside the file
        m_DataFileWriteCache.Wait();
    }

    // Make sure the start time is set
    if ( !m_StartTimeSet )
    {
        m_StartTimeSet		= true;
        m_StartTime			= time;
    }

    // Always set the ending time stamp
    m_EndTime				= time;
    m_PreviousTimeStamp		= time;
    m_LastIndexTimeStamp	= time; // Stores the current end time of the file
    m_NextTimeStamp			= m_PreviousTimeStamp + m_TimeStampInterval;

    return 0;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		WriteTimeStampAndData
*
*	DESCRIPTION:
*		Writes a time stamp to the index file and data to the dat file.
*
*
*	\return Zero on success, non-zero otherwise
*
*	\brief
*		Writes a time stamp to the index file and data to the dat file.
*//******************************************************/
sint8 IndexedDataFileCache::WriteTimeStampAndData ( const cpHighTime & time, float value )
{
    sint64 reservedSpace	= 0;
    sint64 seconds			= 0;
    double subseconds		= 0.0;

    // We must end the current data chunk which requires a crc value unless this
    // is the first byte in the file
    // NOTE: This must be done before writing the next time stamp, because this
    // is part of the previous data chunk and must be accounted for in the
    // data file index
    if ( m_DataFileIndex > 0 )
    {
        uint32 crc = m_DataChunkCRC.GetCRC();
        WriteData ( crc );
    }

    // Writes must occur in this order because it needs the index this data will be
    // written to, and writing the data first will change the index
    WriteTimeStamp ( time );

    // Write the data chunk info (according to the specs)

    // Unique Marker
    for ( uint32 i=0; i<8; i++ )
    {
        WriteData ( UNIQUE_MARKER_BYTE );
    }

    // Time stamp within the chunk
    seconds		= time.GetSeconds();
    subseconds	= time.GetSubSeconds();
    WriteData ( seconds );
    WriteData ( subseconds );

    // Reserved Data
    WriteData ( reservedSpace ); // Reserved 8 bytes

    // Start new crc calculation for this time chunk
    m_DataChunkCRC.Reset();
    WriteData ( value, true ); // Will calculate CRC as well

    return 0;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Write
*
*	DESCRIPTION:
*		Write data to the given cache and waits if necessary
*
*	\param value The buffer to write
*	\param size The size of the buffer
*	\param cache Which cache to write to
*	\return True if the cache had to be flushed, false otherwise
*
*	\brief
*		Write data to the given cache and waits if necessary
*
*//******************************************************/
bool IndexedDataFileCache::Write ( const uint8 * value, uint32 size, PVFS_WriteCache & cache )
{
    return cache.Write ( value, size );
}




/*!*****************************************************
*	PROCEDURE NAME:
*		Append
*
*	DESCRIPTION:
*		Appends the given data to the data file and writes time stamps
*		as necessary. This handles all time stamp and data writing.
*
*	\brief
*		Appends the given data to the data file
*
*//******************************************************/
sint32 IndexedDataFileCache::Append ( const cpHighTime &time, const double value, bool consolidate )
{

    m_WriteMutex.lock();

    // Make sure we have not gone backwards
    if ( time < m_PreviousTimeStamp )
    {
        // This could happen after the stream stops temporarily and
        // the framerate calculator is trying to determine where to put
        // this value
        m_WriteMutex.unlock();
        return 0; // May want to be smarter about this
    }

    /* Few checks to determine if need timestamp:
     * 1. If time between last time stamp is >= time stamp interval
     * 2. If previous value was a nan and this value is not
     * 3. If time between previous point and this point is too great
     */

    float data = (float)value;

    cpHighTime st = cpHighTime::Now();
    GetStartTime( st );

    if ( m_NeedsFirstTimeStamp || ((time - st).GetSeconds() < PID_SETTLING_TIME)) //store timestamps for the first minute
    {
        m_NeedsFirstTimeStamp = false;
        WriteTimeStampAndData ( time, data );
    }
    else if ( isnan ( value )  && !consolidate )
    {
        // Time stamps do not matter in this case - only whether previous item
        // had a time stamp
        if ( !m_PreviousNAN )
        {
            if(!m_BlockLog)GLOG_E(QString("IndexedDataFileCache::Append: Writing a NAN. %1").arg(time.GetSeconds()));
            // The first NAN of the sequence
            m_PreviousNAN = true;

            m_cpTimeTmp = m_PreviousTimeStamp + m_DeltaTime;
            if ( m_cpTimeTmp < time )
            {
                // We apparently had a gap of data followed by a
                WriteTimeStampAndData ( m_cpTimeTmp, NAN );
            }

            // Write the data to the file and time stamp it
            WriteTimeStampAndData ( time, NAN );
        }
    }
    else
    {
        //Strongly suspect that the code block below is causing problems.  Throttling the log message may have
        //made the issue worse.  This message shows up often when there is a time segmented recording problem
        //in 24 hour files.  With the log throttling on,  anecdotal evidence suggests a rapid onset memory leak
        //under some conditions, long into a TS recording.  Rolling back to the original log message for now with
        //an additional time printout.

        //This is definitely causing issues for consolidate.  Adding a flag to turn it off during consolidation.

        if ( !consolidate && ((time - m_PreviousTimeStamp) > m_MaxDelta ))
        {
            GLOG_E(QString("IndexedDataFileCache::Append: Timeout - Writing a NAN. %1 %2 %3 %4").arg(time.GetSeconds()).arg(time.GetSubSeconds())
                                                                                                .arg(m_PreviousTimeStamp.GetSeconds()).arg(m_PreviousTimeStamp.GetSubSeconds()));

            // Put a time stamp and NAN where it should have gone
            m_cpTimeTmp = m_PreviousTimeStamp + m_DeltaTime;
            if ( m_cpTimeTmp < time )
            {
                WriteTimeStampAndData ( m_cpTimeTmp, NAN );
            }

            // Now write the new data
            WriteTimeStampAndData ( time, data );
        }
        else if ( m_PreviousNAN || (time >= m_NextTimeStamp) )
        {
            // Either the previous value was a NAN or
            // The desired time between time stamps has occured
            WriteTimeStampAndData ( time, data );
        }
        else
        {
            // What's this, no issues with anything? Cache it. Ca ching!
            WriteData ( data, true ); // Perform CRC calculation as well
        }

        m_PreviousNAN = false;
    }

    // Always set the time of the previous data
    m_PreviousTimeStamp = time;

    m_WriteMutex.unlock();

    return 0;
}

sint32 IndexedDataFileCache::AppendBlock(const cpHighTime& start_time, const ComplexMathArray& data_values)
{
    // assumes data_values contains <= a block's worth of data- could be trouble, otherwise
    QMutexLocker write_lock(&m_WriteMutex);

    if(data_values.Count() == 0){
        return -1;
    }


    WriteTimeStampAndData(start_time,(float)data_values.Get(0).r);
    m_PreviousTimeStamp = start_time;

    for(int i=1; i<data_values.Count(); i++){
        WriteData((float)data_values.Get(i).r, true);
        m_PreviousTimeStamp += m_DeltaTime;
    }

    for(int i=1; i<data_values.Count(); i++){
        WriteData((float)data_values.Get(i).r, true);
        m_PreviousTimeStamp += m_DeltaTime;
    }
    return 0;
}

sint32 IndexedDataFileCache::AppendBlock(const cpHighTime& start_time, const float* data_values, size_t size)
{
    // assumes data_values contains <= a block's worth of data- could be trouble, otherwise
    QMutexLocker write_lock(&m_WriteMutex);

    if(size <1) return -1;

    WriteTimeStampAndData(start_time,data_values[0]);
    m_PreviousTimeStamp = start_time;

    for(int i=1; i<size; i++){
        WriteData(data_values[i], true);
        m_PreviousTimeStamp += m_DeltaTime;
    }

    return 0;

}




/*-----------------------------------------------------------------------------
*                                PVFS_IndexedDataFile
*-----------------------------------------------------------------------------*/



/*!*****************************************************
*	PROCEDURE NAME:
*		PVFS_IndexedDataFile
*
*	DESCRIPTION:
*		Default Constructor.
*
*	\param pvfs The PVFS file structure within which this file fits
*	\param filename The name of the file to open
*	\param seconds A desired interval between time stamps
*	\param create True to create a new file, false to open an existing file
*   \param overwrite Overwrite the file if it exists.
*
*   \note
*       Overwriting a file means that it cannot be read from at the same time
*       unless great care is taken to not change the writing position because
*       each write will be added to the current location in the file, not
*       at the end.
*
*	\brief
*		Default Constructor.
*
*//******************************************************/
PVFS_IndexedDataFile::PVFS_IndexedDataFile ( std::shared_ptr<pvfs::PvfsFile> pvfsFile, const QString & filename, uint32 cacheSize, uint32 seconds, bool create, bool async_cache, bool overwrite ):
    m_CacheSize ( cacheSize )
{
    m_DataFileType = DataFileInterface::PVFS_INDEXED_FILE;

    Init();
    m_Header.timeStampIntervalSeconds	= seconds;
    m_PVFSFile                          = pvfsFile;
    m_AsyncCache                        = async_cache;

    if ( create )
    {
        Create ( pvfsFile, filename, overwrite );
    }

    Open ( pvfsFile, filename, async_cache, overwrite );
}

PVFS_IndexedDataFile::PVFS_IndexedDataFile ():
    m_CacheSize ( DEFAULT_CACHE_SIZE )
{
    m_DataFileType = DataFileInterface::PVFS_INDEXED_FILE;
    Init();
    m_AsyncCache                        = false;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		~PVFS_IndexedDataFile
*
*	DESCRIPTION:
*		Deconstrutor.
*
*	\brief
*		Deconstrutor.
*
*//******************************************************/
PVFS_IndexedDataFile::~PVFS_IndexedDataFile()
{
    // Put in a final time stamp of a nullptr value and close the connection
    // Note: The data sink is shut off by this time, hopefully
    Close();
}

sint32 PVFS_IndexedDataFile::DeleteChannelByName(const QString& name)
{
    sint32 ret=0;
    if(this->GetChannelName().compare(name)==0){
        if(m_PVFSFile){
            if(m_IndexFile){
                ret = PVFS_delete_file(m_PVFSFile,(char*)m_IndexFile->info.filename);
            }
            if(m_DataFile){
                ret = PVFS_delete_file(m_PVFSFile,(char*)m_DataFile->info.filename);
            }
        }

    }
    return ret;

}


/*!*****************************************************
*	PROCEDURE NAME:
*		Init
*
*	DESCRIPTION:
*		Setup initial values.
*
*	\brief
*		Setup initial values.
*
*//******************************************************/
void PVFS_IndexedDataFile::Init()
{
    m_PVFSFile				= nullptr;
    m_IndexFile				= nullptr;
    m_DataFile				= nullptr;
    m_Cache					= nullptr;
    m_Database				= nullptr;
    m_ChannelId				= -1;

    m_Header.magicNumber				= INDEXED_DATA_FILE_MAGIC_NUMBER;
    m_Header.version					= INDEXED_DATA_FILE_VERSION;
    m_Header.datarate					= 1;
    m_Header.dataType					= DataStream::BIO;
    m_Header.startTime					= get_high_time();
    m_Header.endTime					= m_Header.startTime;
    m_Header.timeStampIntervalSeconds	= 10;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Create
*
*	DESCRIPTION:
*		Create both an index and data file. The two file names are:
*			'filename'.index, and 'filename'.idat
*
*	\brief
*		Create the file of the given file name.
*
*//******************************************************/
bool PVFS_IndexedDataFile::Create ( std::shared_ptr<pvfs::PvfsFile>& pvfsFile, const QString & filename, bool overwrite )
{
    if ( filename.isEmpty() )
    {
        m_Filename.clear();
        return false;
    }
    if ( !pvfsFile )
    {
        return false;
    }

    m_Filename			= filename;
    m_ChannelName		= filename;
    QString indexName	= filename + INDEX_EXTENSION;
    QString dataName	= filename + DATA_EXTENSION;

    m_IndexFile = CheckAndCreateFile ( pvfsFile, indexName, overwrite );
    if ( m_IndexFile == nullptr )
    {
        return false;
    }
    m_DataFile = CheckAndCreateFile ( pvfsFile, dataName, overwrite );
    if ( m_DataFile == nullptr )
    {
        return false;
    }

    PVFS_lock ( pvfsFile );
    {
        // The full header size is 1Kbyte, so write all the zeros now
        // to simply things for later
        for ( uint32 i=0; i<INDEX_HEADER_SIZE; i++ )
        {
            PVFS_fwrite_uint8 ( m_IndexFile, 0 );
        }

        WriteHeader(false);

        PVFS_fclose ( m_IndexFile );
        PVFS_fclose ( m_DataFile );
    } PVFS_unlock ( pvfsFile );

    m_IndexFile = nullptr;
    m_DataFile	= nullptr;

    return true;
}

/** CheckAndCreateFile
  * Used to create a file that does not exist. If the file does exist, the file is opened
  * and set to be overwritten.
  */
std::shared_ptr<PvfsFileHandle> PVFS_IndexedDataFile::CheckAndCreateFile(std::shared_ptr<PvfsFile>& pvfsFile, const QString & filename, bool overwrite )
{
    std::shared_ptr<pvfs::PvfsFileHandle>    file;

    PVFS_lock(pvfsFile);
    file    = PVFS_fopen ( pvfsFile, filename.toLatin1 ().constData () );

    if ( file == nullptr )
    {
        // Creating is not a problem because the file does not exist
        file    = PVFS_fcreate ( pvfsFile, filename.toLatin1().constData () );
    }
    else
    {
        if ( overwrite )
        {
            // The file exists and we wish to overwrite it
            PVFS_seek ( file, 0 );
        }
        else
        {
            // We do not wish to overwrite the file
            PVFS_fclose ( file );
        }
    }
    PVFS_unlock ( pvfsFile );
    return file;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Open
*
*	DESCRIPTION:
*		Opens a file for reading and writing
*
*	\brief
*		Opens a file for reading and writing
*
*//******************************************************/
bool PVFS_IndexedDataFile::Open (std::shared_ptr<PvfsFile>& pvfsFile, const QString & filename, bool async_cache, bool overwrite )
{
    if ( filename.isEmpty() )
    {
        m_Filename.clear();
        return false;
    }
    if ( !pvfsFile )
    {
        return false;
    }

    m_Filename = filename; // Temporary crap

    QString indexName	= filename + INDEX_EXTENSION;
    QString dataName	= filename + DATA_EXTENSION;

    PVFS_lock(pvfsFile);
    m_IndexFile = PVFS_fopen ( pvfsFile, indexName.toLatin1().constData () );
    PVFS_unlock(pvfsFile);

    if ( m_IndexFile == nullptr )
    {
        return false;
    }

    PVFS_lock(pvfsFile);
    m_DataFile = PVFS_fopen ( pvfsFile, dataName.toLatin1().constData () );
    PVFS_unlock(pvfsFile);
    if ( m_DataFile == nullptr )
    {
        PVFS_lock(pvfsFile);
        PVFS_fclose ( m_IndexFile );
        PVFS_unlock(pvfsFile);
        m_IndexFile = nullptr;
        return false;
    }

    // Overwrite is the opposite of the seek to end -
    // If overwriting, do not seek to end and vice versa
    m_Cache = new IndexedDataFileCache ( m_IndexFile, m_DataFile, m_CacheSize, async_cache, !overwrite );
    if(m_Cache == nullptr){
        return false;
    }


    bool rv = ReadHeader();
    m_Cache->ReadAllIndii();
    return rv;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		Close
*
*	DESCRIPTION:
*		Close the file.
*
*	\brief
*		Close the file.
*
*//******************************************************/
void PVFS_IndexedDataFile::Close()
{
    if ( m_IndexFile )
    {
        if( m_Cache ){
            if ( m_Cache->IsModified() )
            {
                cpHighTime tmpTime				= m_Cache->FinalizeTimeStamps();

                m_Cache->Flush ( true );

                m_Header.endTime.seconds		= tmpTime.GetSeconds();
                m_Header.endTime.sub_seconds	= tmpTime.GetSubSeconds();
                if ( m_Database != nullptr )
                {
                    // Update the end time
                    m_Database->UpdateChannelEndTime ( m_ChannelId, tmpTime );
                }

                // We need to make sure the start time is correct in the header,
                // otherwise opening the file can be off a bit
                m_Cache->GetStartTime( tmpTime );
                m_Header.startTime.seconds		= tmpTime.GetSeconds();
                m_Header.startTime.sub_seconds	= tmpTime.GetSubSeconds();
                Flush ();
            }

            delete m_Cache;
            m_Cache = nullptr;
        }

        if(m_IndexFile != nullptr)
        {
            PVFS_fclose(m_IndexFile);
            m_IndexFile = nullptr;
        }

        if(m_DataFile != nullptr)
        {
            PVFS_fclose(m_DataFile);
            m_DataFile = nullptr;
        }

    }
}


/*!*****************************************************
*	PROCEDURE NAME:
*		Flush
*
*	DESCRIPTION:
*		Flush the data to file.
*
*	\brief
*		Flush the data to file.
*
*//******************************************************/
void PVFS_IndexedDataFile::Flush(bool synchronous)
{
    if ( !m_Cache ) return;

    m_FileMutex.lock();
    {
        cpHighTime tmp;

        // Put a final time stamp in the index file
        // Update the end time of the experiment
        // Flush the index file
        // Flush the data file
        // Update the end time
        m_Cache->Flush ( synchronous );
        if ( m_Database != nullptr && m_Cache->IsModified () )
        {
            tmp     = GetEndTime ();
            m_Database->UpdateChannelEndTime ( m_ChannelId, tmp );
        }

        PVFS_lock_file ( m_IndexFile );
        {
            // Must change the start/end times for the header before flushing it - sucka foo!
            if  ( m_Cache->GetStartTime ( tmp ))
            {
                m_Header.startTime.seconds		= tmp.GetSeconds();
                m_Header.startTime.sub_seconds	= tmp.GetSubSeconds();
            }
            if ( m_Cache->GetLastIndexTimeStamp ( tmp ) )
            {
                m_Header.endTime.seconds		= tmp.GetSeconds();
                m_Header.endTime.sub_seconds	= tmp.GetSubSeconds();
            }
        } PVFS_unlock_file ( m_IndexFile );

        WriteHeader();
    } m_FileMutex.unlock();
}

/** Closes the file and reopens it for reading. This is useful is the file has just
  * been created.
  */
bool PVFS_IndexedDataFile::ReOpen()
{
    Close ();
    return Open ( m_PVFSFile, m_Filename, m_AsyncCache, false );
}


/*!*****************************************************
*	PROCEDURE NAME:
*		WriteHeader
*
*	DESCRIPTION:
*		Writes the current header information to the file.
*
*	\brief
*		Writes the current header information to the file.
*
*//******************************************************/
bool PVFS_IndexedDataFile::WriteHeader(bool lock)
{
    return WriteHeader ( m_Header, lock );
}

/*!*****************************************************
*	PROCEDURE NAME:
*		WriteHeader
*
*	DESCRIPTION:
*		Writes header information to the file.
*
*	\brief
*		Writes header information to the file.
*
*//******************************************************/
bool PVFS_IndexedDataFile::WriteHeader ( indexed_header_t &header, bool lock )
{
    if ( !m_IndexFile )
    {
        return false;
    }

    if ( lock )
    {
        PVFS_lock_file ( m_IndexFile );
    }
    {
        PVFS_seek ( m_IndexFile, 0 );
        PVFS_fwrite_uint32 ( m_IndexFile, header.magicNumber );
        PVFS_fwrite_uint32 ( m_IndexFile, header.version );
        PVFS_fwrite_uint32 ( m_IndexFile, header.dataType );
        PVFS_fwrite_float  ( m_IndexFile, header.datarate );
        PVFS_fwrite_sint64 ( m_IndexFile, header.startTime.seconds );
        PVFS_fwrite_double ( m_IndexFile, header.startTime.sub_seconds );
        PVFS_fwrite_sint64 ( m_IndexFile, header.endTime.seconds );
        PVFS_fwrite_double ( m_IndexFile, header.endTime.sub_seconds );
        PVFS_fwrite_uint32 ( m_IndexFile, header.timeStampIntervalSeconds );
        PVFS_flush ( m_IndexFile );
    }
    if ( lock )
    {
        PVFS_unlock_file ( m_IndexFile );
    }

    return true;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		ReadHeader
*
*	DESCRIPTION:
*		Reads the header information from the file.
*
*	\brief
*		Reads the header information from the file.
*
*//******************************************************/
bool PVFS_IndexedDataFile::ReadHeader()
{
    return ReadHeader ( m_Header );
}

/*!*****************************************************
*	PROCEDURE NAME:
*		ReadHeader
*
*	DESCRIPTION:
*		Reads the header information for this file.
*
*	\brief
*		Reads the header information for this file.
*
*//******************************************************/
bool PVFS_IndexedDataFile::ReadHeader ( indexed_header_t &header )
{
    if ( !m_IndexFile )
    {
        return false;
    }

    m_FileMutex.lock();
    PVFS_lock_file ( m_IndexFile );
    {
        PVFS_seek ( m_IndexFile, 0 );
        std::uint32_t tmp = static_cast<std::uint32_t>( header.magicNumber );
        PVFS_fread_uint32 ( m_IndexFile, &tmp );
        tmp = static_cast<std::uint32_t>( header.version );
        PVFS_fread_uint32 ( m_IndexFile, &tmp );
        tmp = static_cast<std::uint32_t>( header.dataType );
        PVFS_fread_uint32 ( m_IndexFile, &tmp );
        PVFS_fread_float  ( m_IndexFile, &header.datarate );
        PVFS_fread_sint64 ( m_IndexFile, &header.startTime.seconds );
        PVFS_fread_double ( m_IndexFile, &header.startTime.sub_seconds );
        PVFS_fread_sint64 ( m_IndexFile, &header.endTime.seconds );
        PVFS_fread_double ( m_IndexFile, &header.endTime.sub_seconds );
        tmp = static_cast<std::uint32_t>( header.timeStampIntervalSeconds );
        PVFS_fread_uint32 ( m_IndexFile, &tmp );
    } PVFS_unlock_file ( m_IndexFile );
    m_FileMutex.unlock();

    if ( header.timeStampIntervalSeconds <= 0 )
    {
        // Non crappy - good default value
        header.timeStampIntervalSeconds	= 10;
    }

    if(m_Cache == nullptr){
        gpftm("PVFS_IndexedDataFile::ReadHeader m_Cache is nullptr");
        return false;
    }
    m_Cache->SetZeroTime ( cpHighTime ( header.startTime ) );
    m_Cache->SetTimeRange ( header.startTime, header.endTime );
    m_Cache->SetDataRate ( header.datarate );
    m_Cache->SetTimeStampInterval ( (sint64)header.timeStampIntervalSeconds );

    return true;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		HasAnnotations
*
*	DESCRIPTION:
*		Reads whether the datafile can contain annotations or not.
*		This is based on whether a database has been set with the
*		SetDatabase member function or not
*
*	\sa SetDatabase
*
*	\brief
*		Reads whether the datafile can contain annotations or not
*
*//******************************************************/
bool PVFS_IndexedDataFile::HasAnnotations () const
{
    return m_Database != nullptr;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetAnnotations
*
*	DESCRIPTION:
*		Returns the annotations for a specific time range.
*
*	\param start_time The start time to grab annotations for
*	\param end_time	The last time to grab annotations for
*	\param annotations Where the annotations are stored
*	\param channel Ignored - only returns annotations for this channel
*
*	\sa SetDatabase
*
*	\brief
*		Returns the annotations for a specific time range
*
*//******************************************************/
sint32 PVFS_IndexedDataFile::GetAnnotations (  const cpHighTime &start_time, const cpHighTime &end_time, QList<ExperimentAnnotation> &annotations, sint32 channel, bool include_all ) const
{
    if ( m_Database == nullptr )
    {
        return -1;
    }

    // Annotations from this channel
    m_Database->GetAnnotations ( annotations, m_ChannelId, start_time, end_time );

    // Public annotations, or can be disrupted by changing channel number.
    if ( channel == ExperimentAnnotation::ALL_CHANNELS && include_all )
    {
        m_Database->GetAnnotations ( annotations, ExperimentAnnotation::ALL_CHANNELS, start_time, end_time );
    }

    return annotations.count();
}


/*!*****************************************************
*	PROCEDURE NAME:
*		AddAnnotation
*
*	DESCRIPTION:
*		Adds an annotation
*
*	\param annotation The annotation to add
*
*	\sa SetDatabase
*
*	\brief
*		Adds an annotation
*
*//******************************************************/
bool PVFS_IndexedDataFile::AddAnnotation ( const ExperimentAnnotation &annotation )
{
    if ( m_Database == nullptr )
    {
        return false;
    }

    return m_Database->AddAnnotation ( annotation );
}

/*!*****************************************************
*	PROCEDURE NAME:
*		RemoveAnnotation
*
*	DESCRIPTION:
*		Removes an annotation
*
*	\param annotation The annotation to remove
*
*	\sa SetDatabase
*
*	\brief
*		Removes an annotation
*
*//******************************************************/
bool PVFS_IndexedDataFile::RemoveAnnotation ( const ExperimentAnnotation &annotation )
{
    if ( m_Database == nullptr )
    {
        return false;
    }

    return m_Database->DeleteAnnotation ( annotation );
}

/*!*****************************************************
*	PROCEDURE NAME:
*		EditAnnotation
*
*	DESCRIPTION:
*		Replaces an annotation
*
*	\param annotation The annotation to replace
*
*	\sa SetDatabase
*
*	\brief
*		Replaces an annotation
*
*//******************************************************/
bool PVFS_IndexedDataFile::EditAnnotation ( const ExperimentAnnotation &old_annotation, const ExperimentAnnotation &new_annotation )
{
    if ( m_Database == nullptr )
    {
        return false;
    }

    return m_Database->EditAnnotation ( old_annotation, new_annotation );
}


/*!*****************************************************
*	PROCEDURE NAME:
*		SetDatabase
*
*	DESCRIPTION:
*		Sets the database to use to store annotations.
*		NOTE: Must be called in order to use annotations
*
*	\param db The database to use
*	\param id The channel id of this channel
*
*
*	\brief
*		Sets the database to use to store annotations
*
*//******************************************************/
void PVFS_IndexedDataFile::SetDatabase ( ExperimentDatabase * db, sint32 id )
{
    QString name = "nullptr";
    if (db) {
        if (QSqlDatabase* sql_db = db->GetDatabase()) {
            name = QString("{sql_db: {\"connectionName\": \"%1\", \"databaseName\": \"%2\"}}")
                   .arg(sql_db->connectionName())
                   .arg(sql_db->databaseName());
        }
    }
    m_Database	= db;
    if(!c_NoDecrement)
    {
        m_ChannelId	= id - 1;
    }
    else
    {
        m_ChannelId = id;
    }
}



ExperimentDatabase * PVFS_IndexedDataFile::GetDatabase()
{
    return m_Database;
}

sint32 PVFS_IndexedDataFile::GetChannelId ( )
{
    // This is the id to index into the database which is one less than the pvfs file
    // so we need to add one
    return m_ChannelId + 1;
}




/*!*****************************************************
*	PROCEDURE NAME:
*		GetFileName
*
*	DESCRIPTION:
*		Gets the name of the file.
*
*	\brief
*		Gets the name of the file.
*
*//******************************************************/
QString PVFS_IndexedDataFile::GetFileName() const
{
    return m_Filename;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		SetTimeStampInterval
*
*	DESCRIPTION:
*		Sets the desired amount of time between time stamps
*
*	\brief
*		Sets the size of data chunk.
*
*//******************************************************/
void PVFS_IndexedDataFile::SetTimeStampInterval( uint32 seconds )
{
    soft_assert ( seconds > 0 );
    if(m_Cache != nullptr)
        m_Cache->SetTimeStampInterval ( (sint64)seconds );
}

/*!*****************************************************
*	PROCEDURE NAME:
*		SetZeroTime
*
*	DESCRIPTION:
*		Sets the zero time for the data. Default is 0.0. The
*		data returned from GetData is offset by zero
*
*	\brief
*		Sets the zero time for the data.
*
*//******************************************************/
void PVFS_IndexedDataFile::SetZeroTime ( const cpHighTime & zeroTime )
{
    if(m_Cache != nullptr)
        m_Cache->SetZeroTime ( zeroTime );
}


/*!*****************************************************
*	PROCEDURE NAME:
*		1. GetDataType, 2. SetDataType
*
*	DESCRIPTION:
*		1. Returns the stream data type
*		2. Sets the stream data type
*
*	\brief
*		Returns the stream data type
*		Sets the stream data type
*
*//******************************************************/
DataStream::StreamType PVFS_IndexedDataFile::GetDataType ( sint32 channel ) const
{
    return m_DataType;
}

void PVFS_IndexedDataFile::SetDataType ( DataStream::StreamType type )
{
    m_DataType = type;
}



/*!*****************************************************
*	PROCEDURE NAME:
*		GetChannelName
*
*	DESCRIPTION:
*		Returns the channel name for this channel.
*		Note: This file contains only a single channel, the channel
*		parameter is ignored.
*
*	\brief
*		Returns the channel name for this channel.
*
*//******************************************************/
QString PVFS_IndexedDataFile::GetChannelName( uint32 channel ) const
{
    return m_ChannelName;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		SetChannelName
*
*	DESCRIPTION:
*		Sets the channel name for this channel.
*
*	\brief
*		Sets the channel name for this channel.
*
*//******************************************************/
void PVFS_IndexedDataFile::SetChannelName ( const QString & name )
{
    m_ChannelName = name;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetChannelIndex
*
*	DESCRIPTION:
*		Gets the index that corresponds to the channel name
*		NOTE: THese files contains only a single index
*
*	\brief
*		Gets the index that corresponds to the channel name
*
*//******************************************************/
sint32 PVFS_IndexedDataFile::GetChannelIndex ( const QString & name ) const
{
    if ( name == m_Filename )
    {
        return 0;
    }
    return -1;
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetStartTime
*		SetStartTime
*
*	DESCRIPTION:
*		Gets/Sets the start time of the recording.
*
*	\brief
*		Gets/Sets the start time of the recording.
*
*//******************************************************/
cpHighTime PVFS_IndexedDataFile::GetStartTime() const
{
    //cpHighTime startTime ( m_Header.startTime );
    //return startTime;
    return m_Header.startTime;
}


void PVFS_IndexedDataFile::SetStartTime ( const cpHighTime & startTime )
{
    m_Header.startTime.seconds      = startTime.GetSeconds();
    m_Header.startTime.sub_seconds  = startTime.GetSubSeconds();
    if ( m_Cache != nullptr )
    {
        m_Cache->SetZeroTime ( startTime );
    }
}

/*!*****************************************************
*	PROCEDURE NAME:
*		GetEndTime
*
*	DESCRIPTION:
*		Gets the end time of the file.
*
*	\brief
*		Gets the end time of the file.
*
*//******************************************************/
cpHighTime PVFS_IndexedDataFile::GetEndTime() const
{
    if ( m_Cache == nullptr ) return cpHighTime::Now();

    if ( m_Cache->IsModified() )
    {
        cpHighTime tmpEndTime;
        if ( m_Cache->GetLastIndexTimeStamp ( tmpEndTime ) )
        {
            return tmpEndTime;
        }
    }

    return cpHighTime ( m_Header.endTime );
}

void PVFS_IndexedDataFile::SetEndTime(const cpHighTime &endTime)
{
    m_Header.endTime.seconds        = endTime.GetSeconds();
    m_Header.endTime.sub_seconds    = endTime.GetSubSeconds();
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetDataFileProxy
*
*	DESCRIPTION:
*		Returns the DataFileInteface
*
*	\brief
*		Returns the DataFileInteface
*
*//******************************************************/
DataFileInterface * PVFS_IndexedDataFile::GetDataFileProxy ( sint32 channel )
{
    return this;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetDataRate
*
*	DESCRIPTION:
*		Returns the datarate
*
*	\brief
*		Returns the datarate
*
*//******************************************************/
float PVFS_IndexedDataFile::GetDataRate( uint32 channel ) const
{
    return m_Header.datarate;
}

void PVFS_IndexedDataFile::SetDataRate ( float dataRate )
{
    m_Header.datarate = dataRate;
    if(m_Cache)
        m_Cache->SetDataRate ( dataRate );
}

void PVFS_IndexedDataFile::SetUnit ( const QString &unit )
{
    m_Unit = unit;
}

QString PVFS_IndexedDataFile::GetUnit ( uint32 channel ) const
{
    return m_Unit;
}


/*!*****************************************************
*	PROCEDURE NAME:
*		GetData
*
*	DESCRIPTION:
*		Gets the data from the desired time span
*
*
*	\brief
*		Gets the data from the desired time span
*
*//******************************************************/
sint32 PVFS_IndexedDataFile::GetData ( const cpHighTime &start_time, const cpHighTime &end_time, ComplexMathArray &t_data, ComplexMathArray &y_data, sint32 channel, sint32 max_points )
{
    sint32 rv = 0;
    if( !m_Cache )	return false;

    m_Mutex.lock();
    rv = m_Cache->GetData ( start_time, end_time, t_data, y_data, channel, max_points );
    m_Mutex.unlock();

    return rv;
}




/*!*****************************************************
*	PROCEDURE NAME:
*		Append
*
*	DESCRIPTION:
*		Appends the given data to the data file
*
*	\brief
*		Appends the given data to the data file
*
*//******************************************************/
sint32 PVFS_IndexedDataFile::Append ( const cpHighTime &time, const double value, sint32 channel, bool consolidate)
{	// Let the cache handle it. Ca ching!
    if(!m_Cache) return -1;
    return m_Cache->Append ( time, value, consolidate );
}

sint32 PVFS_IndexedDataFile::AppendBlock(const cpHighTime& start_time, const ComplexMathArray& data_values)
{
    if(m_Cache){
        return m_Cache->AppendBlock(start_time, data_values);
    }
    return -1;
}

sint32 PVFS_IndexedDataFile::AppendBlock(const cpHighTime& start_time, const float* data_values, size_t size)
{
    if(m_Cache){
        return m_Cache->AppendBlock(start_time, data_values, size);
    }
    return -1;
}




