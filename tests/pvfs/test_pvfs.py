import os
import pytest
from pvfs_tools.Core.pvfs_binding import PvfsFile, HighTime, StringVector
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
    try:
        vfs_instance = PvfsFile.open(file_name)
        yield vfs_instance
    finally:
        # Clean up if needed
        pass

def test_pvfs_get_channel_list(vfs, file_name):
    """Test getting channel list from a VFS file."""
    print(f"\nTesting get_channel_list with file: {file_name}")
    try:
        # Get channel list
        channels = vfs.get_channel_list()
        print(f"Found {len(channels)} channels:")
        for channel in channels:
            print(f"  - {channel}")
        return True
    except Exception as e:
        print(f"Error getting channel list: {e}")
        return False

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
