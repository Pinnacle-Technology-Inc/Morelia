#ifndef PVFS_INDEXEDDATAFILE_H
#define PVFS_INDEXEDDATAFILE_H


/*-----------------------------------------------------------------------------
*                                 INCLUDE(FILES)
*-----------------------------------------------------------------------------*/
#include <QMutex>
#include <QList>


#include <pinnacle.h>
#include <cpHighTime.h>
#include <PALlib/datafile/linear/LinearDataFileInterface.h>
#include <Pvfs.h>
#include <ComplexMathArray.h>

#include <PALlib/datafile/linear/PVFS_ReadCache.h>
#include <PALlib/datafile/linear/PVFS_WriteCache.h>
#include <PALlib/database/experiment/ExperimentDatabase.h>
#include <PALlib/database/experiment/ExperimentChannelInformation.h>
#include <stream/DataStream.h>
#include <Util/CRC32.h>


/*-----------------------------------------------------------------------------
*                                LITERAL CONSTANTS
*-----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                GLOBALS
*----------------------------------------------------------------------------*/

/*-----------------------------------------------------------------------------
*                                TYPES
*-----------------------------------------------------------------------------*/
typedef struct _indexed_header_t
{
    uint32		magicNumber;
    uint32		version;
    uint32		dataType;
    float		datarate;
    high_time_t	startTime;
    high_time_t	endTime;
    uint32		timeStampIntervalSeconds;
} indexed_header_t;




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
|		IndexedDataFileReadCache
|
|	DESCRIPTION:
|		Handles the reading of data given from the data file. Uses the
|		the index file to determine where in the data file to read
|	\brief
|	    Caches data from a file for reading
|
*//*--------------------------------------------------------*/
class IndexedDataFileCache
{
public:
    IndexedDataFileCache( std::shared_ptr<pvfs::PvfsFileHandle> indexFile, std::shared_ptr<pvfs::PvfsFileHandle> dataFile, uint32 cacheSize, bool async_cache = false, bool overwrite = false );
    virtual ~IndexedDataFileCache();

    static const int PID_SETTLING_TIME = 0;  //Very bad idea for high datarates

    void Close();

    void SetTimeStampInterval ( const cpHighTime & interval );
    cpHighTime GetTimeStampInterval () const;

    void SetDataRate ( float dataRate );
    float GetDataRate() const { return m_DataRate; }

    void SetTimeRange ( const cpHighTime & startTime, const cpHighTime & endTime );

    bool GetStartTime ( cpHighTime & start ) const;
    bool GetLastIndexTimeStamp ( cpHighTime & lastTime ) const;

    void SetZeroTime ( const cpHighTime & zeroTime );
    cpHighTime GetZeroTime () const;

    cpHighTime FinalizeTimeStamps();

    virtual sint32 GetData ( const cpHighTime &start_time, const cpHighTime &end_time, ComplexMathArray &t_data, ComplexMathArray &y_data, sint32 channel = 0, sint32 max_points = -1 );

    bool IsModified() const;

    // For going through the file in sequence
    virtual bool Start ( const cpHighTime & startTime );
    virtual sint32 GetNextPoint ( cpHighTime & timeStamp, float & value );
    sint32 GetNextChunk ( cpHighTime & start, cpHighTime & end, QList<float> & data );

    sint64 GetNextChunkDS ( cpHighTime & start, cpHighTime & end, QList<float> &float_ds );

    // Writing data
    virtual sint32 Append (const cpHighTime &time, const double value , bool consolidate = false);

    sint32 AppendBlock(const cpHighTime & start_time, const ComplexMathArray& data_values);
    sint32 AppendBlock(const cpHighTime &start_time, const float* data_values, size_t size);

    // Flush all the buffers
    void Flush ( bool waitForFlush = false );

public:

    static const sint32		ALL_POINTS;//	= -1;
    static const uint8		UNIQUE_MARKER_BYTE;//				= 0xA5;


//protected:
    // Sequential index file access
    void Start ( sint64 location );
    sint64 GetNextTimeStamp ( cpHighTime & timeStamp, sint64 & dataIndex, bool forward = true );
    sint64 GetNextTimeStamp_old ( cpHighTime & timeStamp, sint64 & dataIndex, bool forward = true );
    bool StartNextSequence();

    sint64 GetDataFileIndices ( const cpHighTime & startTime, const cpHighTime & endTime );
    sint64 GetLastTimeStamp ( cpHighTime & timeStamp );

    sint64 ReadTimeStamp ( sint64 location, high_time_t & time, sint64 & dataIndex );
    sint64 ReadTimeStamp ( sint64 location, high_time_t & time );
    sint64 FindTimeStampIndex_old ( const cpHighTime & timeStamp );
    sint64 FindTimeStampIndex ( const cpHighTime & timeStamp );

    sint8 WriteTimeStamp ( const cpHighTime & time );
    sint8 WriteTimeStampAndData ( const cpHighTime & time, float value );

    sint8 WriteData ( const uint8 * data, uint32 length, bool doCRC = false );
    template <typename T>
    sint8 WriteData ( T data, bool doCRC = false )
    {
        return WriteData ( (uint8*)&data, sizeof ( T ), doCRC );
    }

    // Used with the binary search
    sint64 GetConsectutiveTimeStamps ( sint64 & firstLoc, cpHighTime & firstTime, cpHighTime & secondTime );
    sint64 CalcMiddlePoint ( const sint64 & firstLoc, const sint64 & lastLoc );
    sint8 GetInitialBoundary ( const cpHighTime & searchTime, sint64 & firstLoc, cpHighTime & firstTime, sint64 & secondLoc, cpHighTime & secondTime );



    bool Write ( const uint8 * value, uint32 size, PVFS_WriteCache & cache );

    template <typename T>
    bool Write ( T data, PVFS_WriteCache & cache )
    {
        return Write ( (uint8*)&data, sizeof(T), cache );
    }

    void WriteUniqueMarker ( PVFS_WriteCache & cache );
    sint32 ReadUniqueMarker ( PVFS_ReadCache * cache, sint64 location );

    void ReadAllIndii();

protected:
    PVFS_WriteCache			m_IndexFileWriteCache;	//!< Cache for writing to the index file
    PVFS_WriteCache			m_DataFileWriteCache;	//!< Cache for writing to the data file

    PVFS_ReadCache			m_IndexFileReadCache;	//!< Cache for reading the index file
    PVFS_ReadCache			m_DataFileReadCache;	//!< Cache for reading from the data file

    std::shared_ptr<pvfs::PvfsFileHandle>	m_IndexFile;			//!< Index file pointer
    std::shared_ptr<pvfs::PvfsFileHandle>	m_DataFile;				//!< Data file pointer

    cpHighTime				m_TimeStampInterval;	//!< Time between time stamps
    size_t					m_TimeStampSize;		//!< How many bytes in a time stamp
    size_t					m_HeaderSize;			//!< Index file Header size
    size_t					m_DataChunkHeaderSize;	//!< Size of a data chunk header not including the data
    size_t					m_DataChunkHeaderSizeBeforeData;

    cpHighTime				m_StartTime;			//!< The start time in the file
    cpHighTime				m_EndTime;				//!< The end time we can search through
    cpHighTime				m_ZeroTime;				//!< Different from file start time - used to synchronize across devices
    bool					m_StartTimeSet;			//!< Flag tells is we have an initial time stamp yet

    cpHighTime				m_PreviousTimeStamp;	//!< Used in append
    cpHighTime				m_LastIndexTimeStamp;	//!< The last time used for a time stamp in the index file - the current end of file

    sint64					m_DataFileIndex;		//!< Location in the data file

    sint64					m_SequentialIndex;		//!< Used for sequential access
    uint32					m_NumPointsInSequence;	//!< Record keeping in sequence traversing
    uint32					m_CurPointInSequence;	//!< Record keeping in sequence traversing
    cpHighTime				m_SequenceDeltaTime;	//!< The time between points in the sequence
    cpHighTime				m_CurTimeInSequence;	//!< Keep track of where we are
    sint64					m_DataFileSequenceIndex;//!< Keep track of where we are in the data file
    cpHighTime				m_NextTimeStamp;		//!< The starting point of the next sequence
    sint64					m_NextTimeStampIndex;	//!< The data index pointed to by the next time stamp

    sint64					m_LastTimeLocation;		//!< Stores the location of the last time stamp

    bool					m_PreviousNAN;			//!< Used in append to determine if previous item was NAN
    cpHighTime				m_cpTimeTmp;			//!< Temporary to reduce allocations

    float					m_DataRate;				//!< Data Rate for the file
    cpHighTime				m_DeltaTime;			//!< Correct delta time given the datarate
    cpHighTime				m_MaxDelta;				//!< The max time between points without a time stamp

    bool					m_Modified;				//!< Keeps track if the file has been modified
    bool					m_NeedsFirstTimeStamp;	//!< Says we need an initial time stamp

    QMutex					m_ReadMutex;			//!< Mutex to lock the reading of data
    QMutex					m_WriteMutex;			//!< Mutex to lock the writing of data

    CRC32					m_DataChunkCRC;			//!< Calculates the crc for each data chunk

    QList<float>			m_ReadDataChunk;		//!< Here to remove the need to recreate  during get data.
    QList<float>			m_FloatDS;

    // Temp classes to help reduce allcoations.
    // For GetData.
    cpHighTime		m_actualStartTime;
    cpHighTime		m_actualEndTime;

    cpHighTime		m_readTimeSpan;
    cpHighTime		m_curTime;

    cpHighTime		m_chunkStart;
    cpHighTime		m_chunkEnd;

    CRC32			m_CRC32;

    // Playing around code.
    class IndexEntry
    {
    public:
        cpHighTime	start_time;
        cpHighTime	end_time;
        sint64		my_location;
        sint64		data_location;
    };
    QList<IndexEntry>	m_Indii;
    sint64				m_CurrentIndex;
    IndexEntry			m_IndexEntry;
    bool				m_BlockLog {false};
};



/*!-------------------------------------------------------
|	\class
|	CLASS NAME:
|		PVFS_IndexedDataFile
|
|	DESCRIPTION:
|	\brief
|	    A linear data file for saving one channel of EEG/EMG/BIO data
|	    using an indexed method to hopefully make access time very fast
*//*--------------------------------------------------------*/

class PVFS_IndexedDataFile : public LinearDataFileInterface
{


public:

    static const uint32		DEFAULT_CACHE_SIZE;
    static const uint32		INDEXED_DATA_FILE_MAGIC_NUMBER;//	= 0XFF01FF01;
    static const uint32		INDEXED_DATA_FILE_VERSION;//		= 1;
    static const QString	INDEX_EXTENSION;//					= ".index";
    static const QString	DATA_EXTENSION;//					= ".idat";
    static const uint32		INDEX_HEADER_SIZE;//				= 1000;

    enum ACCESS { READ = 1, WRITE = 2 };

    PVFS_IndexedDataFile ( std::shared_ptr<pvfs::PvfsFile> pvfs, const QString & filename, uint32 cacheSize = DEFAULT_CACHE_SIZE, uint32 seconds = 10, bool create = false, bool async_cache = false, bool overwrite = false );
    PVFS_IndexedDataFile ( );

    virtual ~PVFS_IndexedDataFile();

    virtual sint32 DeleteChannelByName(const QString &name);

    QString GetFileName() const;


    bool Create ( std::shared_ptr<pvfs::PvfsFile>& pvfs, const QString & filename, bool overwrite );
    bool Open ( std::shared_ptr<pvfs::PvfsFile>& pvfs, const QString & filename, bool async_cache = true, bool overwrite = false);
    void Close();
    void Flush ( bool synchronous = false );

    bool ReOpen();

    void SetTimeStampInterval ( uint32 seconds );
    void SetZeroTime ( const cpHighTime & zeroTime );


    bool WriteHeader(bool lock = true);
    bool WriteHeader ( indexed_header_t & header, bool lock = true );
    bool ReadHeader();
    bool ReadHeader ( indexed_header_t & header );

    indexed_header_t GetHeader () const { return m_Header; }




    // ----- Linear Data File Interface Functions
    virtual sint32 GetData ( const cpHighTime &start_time, const cpHighTime &end_time, ComplexMathArray &t_data, ComplexMathArray &y_data, sint32 channel = 0, sint32 max_points = -1 );
    virtual sint32 Append (const cpHighTime &time, const double value, sint32 channel = 0 , bool consolidate = false);
    sint32 AppendBlock(const cpHighTime & start_time, const ComplexMathArray& data_values);
    sint32 AppendBlock(const cpHighTime &start_time, const float* data_values, size_t size);
    virtual float GetDataRate( uint32 channel = 0 ) const;

    // Setter for data rate - not in linear data file interface
    void SetDataRate ( float dataRate );


    // ----- Data File Interface Functions
    virtual DataFileInterface * GetDataFileProxy ( sint32 channel );
    virtual uint32 GetNumChannels () const { return 1; }

    virtual DataStream::StreamType GetDataType( sint32 channel = 0 ) const;
    virtual void SetDataType ( DataStream::StreamType type ); // ***

    virtual QString GetChannelName( uint32 channel = 0 ) const;
    virtual void SetChannelName ( const QString & name ); // ***
    virtual sint32 GetChannelIndex ( const QString & name ) const;

    virtual cpHighTime GetStartTime() const;
    virtual void SetStartTime ( const cpHighTime & startTime );
    virtual cpHighTime GetEndTime() const;
    virtual void SetEndTime ( const cpHighTime & endTime );

    // Annotations
    virtual bool HasAnnotations () const;
    virtual sint32 GetAnnotations (  const cpHighTime &start_time, const cpHighTime &end_time, QList<ExperimentAnnotation> &annotations, sint32 channel = ExperimentAnnotation::ALL_CHANNELS, bool include_all = true ) const;
    virtual bool AddAnnotation ( const ExperimentAnnotation &annotation );
    bool RemoveAnnotation ( const ExperimentAnnotation &annotation );
    bool EditAnnotation ( const ExperimentAnnotation &old_annotation, const ExperimentAnnotation &new_annotation );

    void SetUnit ( const QString &unit );
    QString GetUnit ( uint32 channel = 0 ) const;

    void SetDatabase ( ExperimentDatabase * db, sint32 id );

    ExperimentDatabase * GetDatabase();
    sint32 GetChannelId ( );
    cpHighTime FinalizeTimeStamps() {
        if(m_Cache)return m_Cache->FinalizeTimeStamps();
        else return cpHighTime(0, 0.);
    }

protected:

    void Init();
    std::shared_ptr<pvfs::PvfsFileHandle> CheckAndCreateFile ( std::shared_ptr<pvfs::PvfsFile>& pvfsFile, const QString & filename, bool overwrite );


protected:

    IndexedDataFileCache *		m_Cache;		//!< Writes data, reads data, everything!
    uint32						m_CacheSize;	//!< The size of each cache
    bool                        m_AsyncCache;

    indexed_header_t			m_Header;		//!< The file header to write

    DataStream::StreamType		m_DataType;		//!< The data type of the stream

    std::shared_ptr<pvfs::PvfsFile>				m_PVFSFile;		//!< PVFS file
    std::shared_ptr<pvfs::PvfsFileHandle>		m_IndexFile;	//!< File to store the time stamps
    std::shared_ptr<pvfs::PvfsFileHandle>		m_DataFile;		//!< File to store the data

    QString						m_Filename;		//!< Filename of this file within the PVFS and name of stream/channel
    QString						m_ChannelName;

    QMutex						m_FileMutex;	//!< Locks read/write access to the file

    QString						m_Unit;			//!< Unit of the data in the file.

    ExperimentDatabase *		m_Database;
    sint32						m_ChannelId;    //!< Channel inside db.

    QMutex						m_Mutex;

    ExperimentChannelInformation    m_ChanInfo; //!< Updating end time in database

private:


};


#endif // PVFS_INDEXEDDATAFILE_H
