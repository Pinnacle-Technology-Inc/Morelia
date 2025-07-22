import os
import pytest
from datetime import datetime

try:
    import av
except ImportError:
    pytest.skip("PyAV not installed, skipping pvfs tests.", allow_module_level =True)
    
from pvfs_tools.Core.pvfs_binding import PvfsFile, HighTime, StringVector, _lib
from pvfs_tools.Database.database import ExperimentDatabase
from pvfs_tools.Database.models import ExperimentInformation, ChannelInformation, Annotation
from pvfs_tools.Core.indexed_data_file import IndexedDataFile
from pathlib import Path
import time
import math
import gc
import struct

@pytest.fixture
def file_name():
    """Fixture to provide the test file path."""
    # Get the directory containing this test file
    test_dir = Path(__file__).parent
    return str(test_dir / "sine.pvfs")

@pytest.fixture
def vfs(file_name):
    """Fixture to provide a VFS instance for testing."""
    vfs_instance = None
    try:
        vfs_instance = PvfsFile.open(file_name)
        yield vfs_instance
    finally:
        # Clean up any temporary files first
        temp_file = Path("temp.vfs")
 
        # First ensure the VFS instance is properly cleaned up
        if vfs_instance:
            # Close any open file handles and the VFS instance
            try:
                vfs_instance.close()
            except Exception as e:
                print(f"Warning: Failed to close VFS: {e}")
            # Garbage collect and give the system a moment to release the file
            gc.collect()
            time.sleep(0.2)
            
            # Now try to delete the temp file
            if temp_file.exists():
                try:
                    temp_file.unlink()

                except Exception as e:
                    print(f"Warning: Failed to delete temp.vfs: {e}")

@pytest.fixture
def db_name():
    """Fixture to provide the database file path."""
    test_dir = Path(__file__).parent
    return str(test_dir / "test.db3")

@pytest.fixture
def channel_name():
    """Fixture to provide the test channel name."""
    return "CH C"

@pytest.fixture
def channel_file_name():
    """Fixture to provide the test channel name."""
    return "CH C2"

@pytest.fixture
def db(db_name):
    """Fixture to provide a database instance for testing."""
    try:
        db_instance = ExperimentDatabase(db_name)
        yield db_instance
    finally:
        db_instance.close()

@pytest.fixture
def in_file():
    """Fixture to provide the input file name for extraction tests."""
    return "experiment.db3"

@pytest.fixture
def out_file():
    """Fixture to provide the output file path for extraction tests.
    The file will be created in the directory from which the test is being run."""
    test_dir = Path.cwd()  # Get the current working directory
    return str(test_dir / "test.db3")

def test_pvfs_get_channel_list(vfs, file_name):
    """Test getting channel list from a VFS file."""
    print(f"\nTesting get_channel_list with file: {file_name}")
    try:
        # Get channel list
        channels = vfs.get_channel_list()
        assert channels is not None, "Failed to get channel list"
        print(f"Found {len(channels)} channels:")
        for channel in channels:
            print(f"  - {channel}")
    except Exception as e:
        print(f"Error getting channel list: {e}")
        raise

def test_pvfs_get_file_list(vfs, file_name):
    """Test getting file list from a VFS file."""
    print(f"\nTesting get_file_list with file: {file_name}")
    try:
        # Get file list
        files = vfs.get_file_list()
        assert files is not None, "Failed to get file list"
        print(f"Found {len(files)} files:")
        for file in files:
            print(f"  - {file}")
    except Exception as e:
        print(f"Error getting file list: {e}")
        raise

def test_pvfs_extract_database(vfs, file_name):
    """Test extracting database from a VFS file."""
    print(f"\nTesting extract_database with file: {file_name}")
    try:
        # Extract database
        result = vfs.extract("experiment.db3", "extracted_database.db")
        assert result == 0, f"Extraction failed with result: {result}"
        print(f"Extraction result: {result}")
    except Exception as e:
        print(f"Error extracting database: {e}")
        raise

# def test_pvfs_extract(vfs, file_name, in_file, out_file):
#     """Test extracting a file from the VFS."""
#     print("\nTest PVFS Extract")
#     try:
#         # Open the file in the instance
#         vfs.open(file_name)
#         result = vfs.extract(in_file, out_file)
#         assert result == 0, f"Extraction failed with result: {result}"
#         print(f"File extracted successfully to {out_file}")
#     except Exception as e:
#         print(f"Error: {e}")
#         raise


def test_pvfs_high_time():
    print("\nTest PVFS HighTime")
    try:
        # Create a HighTime instance
        time = HighTime(1609459200, 0.5)  # Jan 1, 2021, 00:00:00.5
        print(f"Seconds: {time.seconds}")
        print(f"Subseconds: {time.subseconds}")
    except Exception as e:
        print(f"Error: {e}")

def test_pvfs_locking(vfs, file_name):
    print("\nTest PVFS Locking")
    try:
        # Open the file in the instance
        vfs.open(file_name)
        # Lock the VFS
        vfs.lock()
        print("VFS locked successfully")
        
        # Do some operations...
        
        # Unlock the VFS
        vfs.unlock()
        print("VFS unlocked successfully")
    except Exception as e:
        print(f"Error: {e}")

def test_db_get_experiment_info(db):
    """Test retrieving experiment information from database."""
    print("\nTesting database experiment information retrieval")
    try:
        info = db.get_information()
        assert info is not None, "Failed to retrieve experiment information"
        print(f"\nRetrieved experiment information:")
        print(f"Name: {info.name}")
        print(f"Description: {info.description}")
        if info.start_time:
            print(f"Start time: {datetime.fromtimestamp(info.start_time.seconds)}")
        if info.end_time:
            print(f"End time: {datetime.fromtimestamp(info.end_time.seconds)}")
    except Exception as e:
        print(f"Error retrieving experiment information: {e}")
        raise

def test_db_get_channel_names(db):
    """Test getting all channel names from database."""
    print("\nTesting database channel names retrieval")
    try:
        channel_names = db.get_channel_names()
        assert channel_names is not None, "Failed to retrieve channel names"
        print(f"\nFound {len(channel_names)} channels:")
        for name in channel_names:
            print(f"- {name}")
    except Exception as e:
        print(f"Error getting channel names: {e}")
        raise

def test_db_get_channel_info(db, channel_name):
    """Test getting detailed information for a specific channel."""
    print(f"\nTesting database channel info retrieval for {channel_name}")
    try:
        # First get all available channels
        all_channels = db.get_channel_names()
        print("\nAvailable channels in database:")
        for name in all_channels:
            print(f"- {name}")
            
        # Check if the channel exists in the list
        if channel_name not in all_channels:
            print(f"\nWarning: Channel '{channel_name}' not found in available channels")
            return
            
        channel_info = db.get_channel_info(channel_name)
        if channel_info is None:
            print(f"\nWarning: Channel '{channel_name}' exists but info retrieval failed")
            return
            
        print("\nChannel Information:")
        print(f"Name: {channel_info.name}")
        print(f"ID: {channel_info.id}")
        print(f"Type: {channel_info.type}")
        print(f"Unit: {channel_info.unit}")
        print(f"Data Rate: {channel_info.data_rate} Hz")
        print(f"Device: {channel_info.device_name}")
        if channel_info.start_time:
            print(f"Start time: {datetime.fromtimestamp(channel_info.start_time.seconds)}")
        if channel_info.end_time:
            print(f"End time: {datetime.fromtimestamp(channel_info.end_time.seconds)}")
        if channel_info.comments:
            print(f"Comments: {channel_info.comments}")
    except Exception as e:
        print(f"Error getting channel info: {e}")
        raise

def test_db_get_channel_annotations(db, channel_name):
    """Test getting annotations for a specific channel."""
    print(f"\nTesting database channel annotations retrieval for {channel_name}")
    try:
        # First get all available channels
        all_channels = db.get_channel_names()
        print("\nAvailable channels in database:")
        for name in all_channels:
            print(f"- {name}")
            
        # Check if the channel exists in the list
        if channel_name not in all_channels:
            print(f"\nWarning: Channel '{channel_name}' not found in available channels")
            return
            
        channel_info = db.get_channel_info(channel_name)
        if channel_info is None:
            print(f"\nWarning: Channel '{channel_name}' exists but info retrieval failed")
            return
            
        annotations = db.get_channel_annotations(channel_info.id)
        if annotations is None:
            print(f"\nWarning: Failed to retrieve annotations for channel '{channel_name}'")
            return
            
        print(f"\nFound {len(annotations)} annotations:")
        for annotation in annotations:
            print(f"\nAnnotation {annotation.unique_id}:")
            print(f"Type: {annotation.type}")
            if annotation.start_time:
                print(f"Start time: {datetime.fromtimestamp(annotation.start_time.seconds)}")
            if annotation.end_time:
                print(f"End time: {datetime.fromtimestamp(annotation.end_time.seconds)}")
            if annotation.comment:
                print(f"Comment: {annotation.comment}")
            if annotation.creator:
                print(f"Created by: {annotation.creator}")
            if annotation.last_edited:
                print(f"Last edited: {annotation.last_edited}")
    except Exception as e:
        print(f"Error getting channel annotations: {e}")
        raise

def test_db_get_all_annotations(db):
    """Test getting all annotations from the database."""
    print("\nTesting database all annotations retrieval")
    try:
        all_annotations = db.get_all_annotations()
        assert all_annotations is not None, "Failed to retrieve all annotations"
        print(f"\nFound {len(all_annotations)} total annotations:")
        for annotation in all_annotations:
            print(f"\nAnnotation {annotation.unique_id} (Channel {annotation.channel_id}):")
            print(f"Type: {annotation.type}")
            if annotation.start_time:
                print(f"Start time: {datetime.fromtimestamp(annotation.start_time.seconds)}")
            if annotation.end_time:
                print(f"End time: {datetime.fromtimestamp(annotation.end_time.seconds)}")
            if annotation.comment:
                print(f"Comment: {annotation.comment}")
    except Exception as e:
        print(f"Error getting all annotations: {e}")
        raise


def test_indexed_data_file(vfs, file_name):
    """Unit test for IndexedDataFile class using CH C2 channel."""
    
    # Get and validate channel list
    channels = vfs.get_channel_list()
    assert channels is not None and "CH C2.index" in channels

    # Open data file
    indexed_file = IndexedDataFile(vfs, "CH C2")
    assert indexed_file is not None

    # Validate header
    header = indexed_file._header
    assert header is not None
    assert header.data_rate > 0

    # Get time bounds
    start_time = indexed_file.get_start_time()
    end_time = indexed_file.get_end_time()
    assert start_time.to_seconds() < end_time.to_seconds()

    # Validate channel name
    assert indexed_file.get_channel_name() == "CH C2"

    # Retrieve a short data segment from known region
    segment_start = start_time
    segment_stop = start_time + 2  # 2 seconds worth of data
    timestamps, values = indexed_file.get_data(segment_start, segment_stop)

    # Check structure
    assert isinstance(timestamps, list)
    assert isinstance(values, list)
    assert len(timestamps) == len(values)
    assert len(values) > 0

    # Known reference value check (index 0)
    t0 = timestamps[0].to_seconds()
    v0 = values[0]
    assert math.isclose(t0, 1746557173.796519995, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(v0, 298.7197265625, rel_tol=0, abs_tol=1e-6)

    # Close file
    indexed_file.close()


def test_file_handle_get_info(vfs, file_name):
    """
    Test retrieving the info (startBlock, size, filename) from a PvfsFileHandle.
    """
    print(f"\nTesting file handle get_file_info with file: {file_name}")

    try:
        # Open a known file inside the VFS (adjust filename if needed)
        handle = vfs.open_file("CH A0.index")
        
        # Call the new get_file_info method (which must be implemented in the binding)
        info = handle.get_file_info()
        
        # Print out the info (similar to the python snippet)
        filename_str = info.filename.decode("utf-8", errors="ignore").rstrip("\x00")
        print(f"Start Block: {info.startBlock}")
        print(f"Size:       {info.size}")
        print(f"Filename:   {filename_str}")

        # Optionally add some simple assertions:
        assert info.startBlock >= 0, "startBlock should be non-negative"
        assert info.size >= 0, "size should be non-negative"
        assert len(filename_str) > 0, "filename should not be empty"

        
    except Exception as e:
        print(f"Error in test_file_handle_get_info: {e}")
        raise


def main():
    # Test file path - using Windows path format
    file_name = str(Path("E:/newPython/PVFS_test/sine.pvfs"))
    
    # Create a single VFS instance for all tests
    try:
        print(f"Opening VFS file: {file_name}")
        vfs = PvfsFile.open(file_name)
        print("Successfully opened VFS")
    except Exception as e:
        print(f"Failed to open VFS: {e}")
        return

    # Run all tests with the same VFS instance
    tests = [
        ("Get Channel List", test_pvfs_get_channel_list),
        ("Get File List", test_pvfs_get_file_list),
        ("Extract Database", test_pvfs_extract_database),
 #       ("Data Channel Operations", test_pvfs_data_channel),
 #       ("Indexed Data File", test_indexed_data_file)
    ]

    print("\nStarting PVFS tests...")
    for test_name, test_func in tests:
        print(f"\nRunning test: {test_name}")
        success = test_func(vfs, file_name)
        print(f"Test {test_name}: {'PASSED' if success else 'FAILED'}")

if __name__ == "__main__":
    main()
