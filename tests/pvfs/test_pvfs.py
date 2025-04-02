import os
import pytest
from datetime import datetime
from pvfs_tools.Core.pvfs_binding import PvfsFile, HighTime, StringVector
from pvfs_tools.Database.database import ExperimentDatabase
from pvfs_tools.Database.models import ExperimentInformation, ChannelInformation, Annotation
from pathlib import Path

@pytest.fixture
def file_name():
    """Fixture to provide the test file path."""
    # Get the directory containing this test file
    test_dir = Path(__file__).parent
    return str(test_dir / "test.pvfs")

@pytest.fixture
def vfs(file_name):
    """Fixture to provide a VFS instance for testing."""
    vfs_instance = None
    try:
        vfs_instance = PvfsFile.open(file_name)
        yield vfs_instance
    finally:
        # Close the VFS instance first
        if vfs_instance:
            try:
                vfs_instance.close()
            except Exception as e:
                print(f"Warning: Failed to close VFS instance: {e}")
        
        # Then clean up any temporary files
        temp_file = Path("temp.vfs")
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
    return "EEG10"

@pytest.fixture
def db(db_name):
    """Fixture to provide a database instance for testing."""
    try:
        db_instance = ExperimentDatabase(db_name)
        yield db_instance
    finally:
        db_instance.close()

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
        print(f"Found {len(files)} files:")
        for file in files:
            print(f"  - {file}")
        return True
    except Exception as e:
        print(f"Error getting file list: {e}")
        return False

def test_pvfs_extract_database(vfs, file_name):
    """Test extracting database from a VFS file."""
    print(f"\nTesting extract_database with file: {file_name}")
    try:
        # Extract database
        result = vfs.extract("experiment.db3", "extracted_database.db")
        print(f"Extraction result: {result}")
        return True
    except Exception as e:
        print(f"Error extracting database: {e}")
        return False

def test_pvfs_extract(vfs, file_name, in_file, out_file):
    print("\nTest PVFS Extract")
    try:
        # Open the file in the instance
        vfs.open(file_name)
        vfs.extract(in_file, out_file)
        print(f"File extracted successfully to {out_file}")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_pvfs_data_channel(vfs, file_name):
    """Test data channel operations."""
    print(f"\nTesting data channel operations with file: {file_name}")
    try:
        # Get channel list first
        channels = vfs.get_channel_list()
        if not channels:
            print("No channels found in VFS")
            return False

        # Try to open the first channel
        channel_name = channels[0]
        print(f"Opening data channel: {channel_name}")
        channel = vfs.open_data_channel(channel_name)
        
        # Try to read some data
        try:
            data = channel.read(1024)  # Read first 1024 bytes
            print(f"Read {len(data)} bytes from channel")
        except Exception as e:
            print(f"Error reading channel data: {e}")
        
        # Close the channel
        channel.close()
        return True
    except Exception as e:
        print(f"Error in data channel test: {e}")
        return False

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

def main():
    # Test file path - using Windows path format
    file_name = str(Path("E:/newPython/PVFS_test/test1.pvfs"))
    
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
        ("Data Channel Operations", test_pvfs_data_channel)
    ]

    print("\nStarting PVFS tests...")
    for test_name, test_func in tests:
        print(f"\nRunning test: {test_name}")
        success = test_func(vfs, file_name)
        print(f"Test {test_name}: {'PASSED' if success else 'FAILED'}")

if __name__ == "__main__":
    main()
