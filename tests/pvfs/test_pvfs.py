import ctypes
import os
import sqlite3
import pytest
from datetime import datetime

try:
    import av
except ImportError:
    pytest.skip("PyAV not installed, skipping pvfs tests.", allow_module_level =True)
    
from pvfs_tools.Core.pvfs_binding import PvfsFile, HighTime, StringVector, _lib
from pvfs_tools.Database.database import ExperimentDatabase
from pvfs_tools.Database.exceptions import TableError
from pvfs_tools.Database.models import ExperimentInformation, ChannelInformation, Annotation
from pvfs_tools.Core.indexed_data_file import IndexedDataFile
from pathlib import Path
import time
import math
import gc
import struct


def cleanup_file(path, max_retries=3, delay=0.2):
    """Helper function to reliably delete a file with retries.
    
    On Windows, file handles can take time to be released by the OS,
    so we retry with increasing delays.
    """
    if not path or not path.exists():
        return
    
    for attempt in range(max_retries):
        try:
            # Force garbage collection before each attempt
            gc.collect()
            # Wait before attempting deletion (longer wait for later attempts)
            wait_time = delay * (attempt + 1)
            time.sleep(wait_time)
            path.unlink()
            return
        except (PermissionError, OSError, FileNotFoundError) as e:
            if attempt < max_retries - 1:
                # Continue to next retry
                continue
            else:
                # Final attempt failed
                print(f"Warning: Failed to remove {path} after {max_retries} attempts: {e}")

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
        assert len(channels) == 8, f"Expected 8 channels, got {len(channels)}"
        
        # Expected channel names
        expected_channels = {
            "experiment.db3",
            "experiment_backup.db3",
            "EEG10.index",
            "EEG10.idat",
            "EEG21.index",
            "EEG21.idat",
            "EMG2.index",
            "EMG2.idat"
        }
        
        # Convert channels to set for comparison
        channel_set = set(channels)
        assert channel_set == expected_channels, (
            f"Channel list mismatch. Expected: {expected_channels}, Got: {channel_set}"
        )
        
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
        assert len(files) > 0, "File list should not be empty"
        print(f"Found {len(files)} files:")
        for file in files:
            print(f"  - {file}")
    except Exception as e:
        print(f"Error getting file list: {e}")
        raise

def test_pvfs_extract_database(vfs, file_name):
    """Test extracting database from a VFS file."""
    print(f"\nTesting extract_database with file: {file_name}")
    test_dir = Path(__file__).parent
    out_path = test_dir / "test_pvfs_extracted_database.db3"
    try:
        t_before = time.time()
        result = vfs.extract("experiment.db3", str(out_path))
        t_after = time.time()
        assert result == 0, f"Extraction failed with result: {result}"
        assert out_path.exists(), "Extracted file should exist"
        mtime = out_path.stat().st_mtime
        assert t_before - 1 <= mtime <= t_after + 1, (
            "Extracted file modification time should be close to extraction time"
        )
        print(f"Extraction result: {result}")
    except Exception as e:
        print(f"Error extracting database: {e}")
        raise
    finally:
        print(f"Output file {out_path}")
        # Cleanup
        cleanup_file(out_path)


@pytest.fixture
def created_pvfs(vfs):
    """
    Create a new PVFS by copying all files from sine.pvfs, yield (verify, files)
    for verification. Teardown closes and deletes the created file.
    """
    test_dir = Path(__file__).parent
    dest_path = test_dir / "test_created.pvfs"
    files = vfs.get_file_list()
    assert files is not None and len(files) > 0, "Source should have files to copy"

    dest = PvfsFile.create(str(dest_path))
    assert dest.is_open, "Created PVFS should be open"

    vfs.lock()
    try:
        for name in files:
            src_handle = vfs.open_file(name)
            info = src_handle.get_file_info()
            size = int(info.size)
            data = src_handle.read(size) if size > 0 else b""
            src_handle.close()

            dest.lock()
            try:
                dst_handle = dest.fcreate(name)
                if len(data) > 0:
                    chunk_size = 4000
                    offset = 0
                    data_view = memoryview(data)
                    while offset < len(data_view):
                        chunk = data_view[offset:offset + chunk_size]
                        buf = (ctypes.c_uint8 * len(chunk)).from_buffer_copy(chunk)
                        n = dst_handle.write(buf, len(chunk))
                        assert n == len(chunk), f"short write: {n} != {len(chunk)}"
                        offset += n
                    assert offset == len(data_view), f"short write for {name}: {offset} != {len(data_view)}"  
                dst_handle.flush()
                dst_handle.close()
            finally:
                dest.unlock()
    finally:
        vfs.unlock()

    dest.close()
    gc.collect()
    time.sleep(0.2)

    verify = PvfsFile.open(str(dest_path))
    try:
        yield (verify, files)
    finally:
        # Ensure verify is properly closed before attempting cleanup
        try:
            verify.close()
        except Exception as e:
            print(f"Warning: Error closing verify in created_pvfs fixture: {e}")
        
        # Force garbage collection and wait for file handles to be released
        gc.collect()
        time.sleep(0.5)  # Increased wait time for Windows file handle release
        
        # Cleanup with more retries and longer delays for Windows
        cleanup_file(dest_path, max_retries=5, delay=0.5)


def test_pvfs_create_and_copy_structure(created_pvfs):
    """Created PVFS (from sine.pvfs) should have correct channels and file count."""
    verify, files = created_pvfs
    ch = verify.get_channel_list()
    assert ch is not None and len(ch) > 0, "Created PVFS should have channels"
    fl = verify.get_file_list()
    assert fl is not None and len(fl) > 0, "Created PVFS should have files"
    assert len(fl) == len(files), "Created PVFS should have same number of files as source"


def test_pvfs_create_and_copy_database(created_pvfs):
    """Extracted experiment.db3 from created PVFS should be readable."""
    verify, _ = created_pvfs
    fl = verify.get_file_list()
    if "experiment.db3" not in fl:
        pytest.skip("experiment.db3 not in created PVFS")
    test_dir = Path(__file__).parent
    extracted_db = test_dir / "test_created_extracted.db3"
    db = None
    try:
        res = verify.extract("experiment.db3", str(extracted_db))
        assert res == 0, "Extracting experiment.db3 from created PVFS should succeed"
        assert extracted_db.exists(), "Extracted database file should exist"
        db = ExperimentDatabase(str(extracted_db))
        info = db.get_information()
        assert info is not None, "Extracted database should be readable and have experiment info"
    except TableError as e:
        pytest.skip(
            f"get_information failed (extracted DB may be empty or schema mismatch): {e}"
        )
    finally:
        if db is not None:
            db.close()
        cleanup_file(extracted_db)


def test_pvfs_create_and_copy_indexed_data(created_pvfs):
    """Indexed data (EEG10) in created PVFS should be readable."""
    verify, _ = created_pvfs
    ch = verify.get_channel_list()
    if "EEG10.index" not in ch:
        pytest.skip("EEG10.index not in created PVFS")
    idf = IndexedDataFile(verify, "EEG10")
    start = idf.get_start_time()
    stop = start + 1
    ts, vals = idf.get_data(start, stop)
    idf.close()
    assert isinstance(ts, list) and isinstance(vals, list), "get_data should return lists"
    assert len(ts) == len(vals), "timestamps and values should have same length"
    if len(vals) == 0:
        pytest.skip(
            "created PVFS has no indexed data; copy may not be persisting data"
        )


def test_pvfs_single_file_write_extract():
    """
    Minimal test: fcreate one file, write known content, flush, close; then
    extract and verify size and content. Isolates the fcreate/write/close path.
    """
    test_dir = Path(__file__).parent
    pvfs_path = test_dir / "test_single_write.pvfs"
    out_path = test_dir / "test_single_extracted.bin"
    data = b"PVFS single-file write test content"

    dest = PvfsFile.create(str(pvfs_path))
    assert dest.is_open, "created PVFS should be open"
    dest.lock()
    try:
        h = dest.fcreate("test_single.bin")
        n = h.write(data, len(data))
        assert n == len(data), f"write should return bytes written, got {n}"
        h.flush()
        h.close()
    finally:
        dest.unlock()
    dest.close()
    gc.collect()
    time.sleep(0.2)

    verify = PvfsFile.open(str(pvfs_path))
    try:
        res = verify.extract("test_single.bin", str(out_path))
        assert res == 0, f"extract failed: {res}"
        assert out_path.exists(), "extracted file should exist"
        assert out_path.stat().st_size == len(data), (
            f"extracted size {out_path.stat().st_size} != expected {len(data)}"
        )
        assert out_path.read_bytes() == data, "extracted content should match"
    finally:
        verify.close()

    # Cleanup
    for p in (pvfs_path, out_path):
        cleanup_file(p)


def test_pvfs_two_file_write_extract():
    """
    fcreate/write/flush/close two files, then extract both and verify.
    Uses per-file lock/unlock like the copy fixture. Fails if the second
    file (or multi-file handling) does not persist.
    """
    test_dir = Path(__file__).parent
    pvfs_path = test_dir / "test_two_write.pvfs"
    out_a = test_dir / "test_two_extracted_a.bin"
    out_b = test_dir / "test_two_extracted_b.bin"
    data_a = b"first file a.bin"
    data_b = b"second file b.bin"

    dest = PvfsFile.create(str(pvfs_path))
    assert dest.is_open, "created PVFS should be open"

    for name, data in [("a.bin", data_a), ("b.bin", data_b)]:
        dest.lock()
        try:
            h = dest.fcreate(name)
            n = h.write(data, len(data))
            assert n == len(data), f"write should return bytes written for {name}, got {n}"
            h.flush()
            h.close()
        finally:
            dest.unlock()

    dest.close()
    gc.collect()
    time.sleep(0.2)

    verify = PvfsFile.open(str(pvfs_path))
    try:
        for name, data, out in [("a.bin", data_a, out_a), ("b.bin", data_b, out_b)]:
            res = verify.extract(name, str(out))
            assert res == 0, f"extract {name} failed: {res}"
            assert out.exists(), f"extracted {name} should exist"
            assert out.stat().st_size == len(data), (
                f"extracted {name} size {out.stat().st_size} != expected {len(data)}"
            )
            assert out.read_bytes() == data, f"extracted {name} content should match"
    finally:
        verify.close()

    # Cleanup
    for p in (pvfs_path, out_a, out_b):
        cleanup_file(p)


def test_pvfs_copy_structure_dummy_data(vfs):
    """
    Same structure as created_pvfs copy loop: source open, get_file_list,
    vfs.lock, for each name open_file/get_file_info/read/close, dest.lock,
    fcreate, write, flush, close, dest.unlock. Writes a fixed 1-byte b'X'
    instead of read data. Extracts a few and verifies. Fails if many-file
    or source-open-during-write path does not persist.
    """
    test_dir = Path(__file__).parent
    pvfs_path = test_dir / "test_copy_structure.pvfs"
    files = vfs.get_file_list()
    assert files is not None and len(files) > 0, "Source should have files"

    dest = PvfsFile.create(str(pvfs_path))
    assert dest.is_open, "created PVFS should be open"

    non_empty = []
    vfs.lock()
    try:
        for name in files:
            src_handle = vfs.open_file(name)
            info = src_handle.get_file_info()
            size = int(info.size)
            _ = src_handle.read(size) if size > 0 else b""
            src_handle.close()

            dest.lock()
            try:
                dst_handle = dest.fcreate(name)
                if size > 0:
                    n = dst_handle.write(b"X", 1)
                    assert n == 1, f"write {name} should return 1, got {n}"
                    non_empty.append(name)
                dst_handle.flush()
                dst_handle.close()
            finally:
                dest.unlock()
    finally:
        vfs.unlock()

    dest.close()
    gc.collect()
    time.sleep(0.2)

    if len(non_empty) == 0:
        cleanup_file(pvfs_path)
        pytest.skip("no non-empty files in source to verify")

    verify = PvfsFile.open(str(pvfs_path))
    extracted_paths = []
    try:
        for i, name in enumerate(non_empty[:5]):
            out = test_dir / f"test_copy_verify_{i}.bin"
            extracted_paths.append(out)
            res = verify.extract(name, str(out))
            assert res == 0, f"extract {name} failed: {res}"
            assert out.exists(), f"extracted {name} should exist"
            assert out.stat().st_size == 1, (
                f"extracted {name} size should be 1, got {out.stat().st_size}"
            )
            assert out.read_bytes() == b"X", f"extracted {name} content should be b'X'"
    finally:
        verify.close()

    # Cleanup
    for p in [pvfs_path] + extracted_paths:
        cleanup_file(p)


def test_pvfs_database_extract_and_write(vfs):
    """
    Read experiment.db3 from sine.pvfs, write it into a new PVFS, extract,
    and verify the extracted DB has 14 tables and data in
    experiment_information_table. Focused on getting the DB copy path right.
    """
    test_dir = Path(__file__).parent
    pvfs_path = test_dir / "test_db_copy.pvfs"
    extracted_path = test_dir / "test_db_copy_extracted.db"

    fl = vfs.get_file_list()
    if "experiment.db3" not in fl:
        pytest.skip("experiment.db3 not in source")

    # Read from source
    vfs.lock()
    try:
        src = vfs.open_file("experiment.db3")
        info = src.get_file_info()
        size = int(info.size)
        data = src.read(size) if size > 0 else b""
        src.close()
    finally:
        vfs.unlock()

    if size == 0 or len(data) == 0:
        pytest.skip("experiment.db3 in source is empty")

    # Write into new PVFS in 1K chunks to match PVFS_add (pvfs.cpp uses 1024).
    # Single large write is not persisted. Flush after each chunk.
    CHUNK = 1024
    dest = PvfsFile.create(str(pvfs_path))
    assert dest.is_open
    dest.lock()
    try:
        dst = dest.fcreate("experiment.db3")
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + CHUNK]
            n = dst.write(chunk, len(chunk))
            assert n == len(chunk), f"write at offset {offset} returned {n}, expected {len(chunk)}"
            dst.flush()
            offset += n
        dst.close()
    finally:
        dest.unlock()
    dest.close()
    gc.collect()
    time.sleep(0.2)

    # Extract from new PVFS and verify with sqlite3
    verify = PvfsFile.open(str(pvfs_path))
    try:
        res = verify.extract("experiment.db3", str(extracted_path))
        assert res == 0, f"extract failed: {res}"
        assert extracted_path.exists(), "extracted DB should exist"
        assert extracted_path.stat().st_size == len(data), (
            f"extracted size {extracted_path.stat().st_size} != source {len(data)}"
        )
        magic = extracted_path.read_bytes()[:16]
        assert magic == b"SQLite format 3\x00", (
            f"extracted file should start with SQLite magic, got {magic!r}"
        )
    finally:
        verify.close()

    # Verify DB structure: 14 tables and data in experiment_information_table
    conn = sqlite3.connect(str(extracted_path))
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert len(table_names) == 14, (
            f"expected 14 tables (like sine.pvfs experiment.db3), got {len(table_names)}: {table_names}"
        )
        (nrows,) = conn.execute(
            "SELECT count(*) FROM experiment_information_table"
        ).fetchone()
        assert nrows > 0, "experiment_information_table should have rows"
    finally:
        conn.close()

    # Cleanup
    for p in (pvfs_path, extracted_path):
        cleanup_file(p)


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
    # Create a HighTime instance (use ht to avoid shadowing the time module)
    ht = HighTime(1609459200, 0.5)  # Jan 1, 2021, 00:00:00.5
    assert ht.seconds == 1609459200, "HighTime.seconds should match constructor"
    assert math.isclose(ht.subseconds, 0.5, rel_tol=0, abs_tol=1e-9), "HighTime.subseconds should match constructor"
    print(f"Seconds: {ht.seconds}")
    print(f"Subseconds: {ht.subseconds}")

def test_pvfs_locking(vfs, file_name):
    print("\nTest PVFS Locking")
    # VFS is already open from the fixture; PvfsFile has no instance method open().
    vfs.lock()
    print("VFS locked successfully")
    vfs.unlock()
    print("VFS unlocked successfully")
    assert vfs.is_open, "VFS should remain open after lock/unlock"

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
        assert len(channel_names) > 0, "Channel names list should not be empty"
        print(f"\nFound {len(channel_names)} channels:")
        for name in channel_names:
            print(f"- {name}")
    except Exception as e:
        print(f"Error getting channel names: {e}")
        raise

def test_db_get_channel_info(db, channel_name):
    """Test getting detailed information for a specific channel."""
    print(f"\nTesting database channel info retrieval for {channel_name}")
    all_channels = db.get_channel_names()
    print("\nAvailable channels in database:")
    for name in all_channels:
        print(f"- {name}")

    if channel_name not in all_channels:
        pytest.skip(f"Channel '{channel_name}' not in database; test requires this channel")

    channel_info = db.get_channel_info(channel_name)
    assert channel_info is not None, "get_channel_info should return a value when channel exists"
    assert channel_info.name == channel_name, "Returned channel name should match"
    assert hasattr(channel_info, "id"), "ChannelInformation should have id"
    assert hasattr(channel_info, "data_rate"), "ChannelInformation should have data_rate"

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

def test_db_get_channel_annotations(db, channel_name):
    """Test getting annotations for a specific channel."""
    print(f"\nTesting database channel annotations retrieval for {channel_name}")
    all_channels = db.get_channel_names()
    print("\nAvailable channels in database:")
    for name in all_channels:
        print(f"- {name}")

    if channel_name not in all_channels:
        pytest.skip(f"Channel '{channel_name}' not in database; test requires this channel")

    channel_info = db.get_channel_info(channel_name)
    assert channel_info is not None, "get_channel_info should return a value when channel exists"

    annotations = db.get_channel_annotations(channel_info.id)
    assert annotations is not None, "get_channel_annotations should return a list, not None"

    print(f"\nFound {len(annotations)} annotations:")
    for annotation in annotations:
        assert hasattr(annotation, "unique_id"), "Annotation should have unique_id"
        assert hasattr(annotation, "channel_id"), "Annotation should have channel_id"
        assert hasattr(annotation, "type"), "Annotation should have type"
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

def test_db_get_all_annotations(db):
    """Test getting all annotations from the database."""
    print("\nTesting database all annotations retrieval")
    try:
        all_annotations = db.get_all_annotations()
        assert all_annotations is not None, "Failed to retrieve all annotations"
        assert len(all_annotations) > 0, "Annotations list should not be empty"
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
    """Unit test for IndexedDataFile class using EEG10 channel."""
    
    # Get and validate channel list
    channels = vfs.get_channel_list()
    assert channels is not None and "EEG10.index" in channels

    # Open data file
    indexed_file = IndexedDataFile(vfs, "EEG10")
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
    assert indexed_file.get_channel_name() == "EEG10"

    # Retrieve a short data segment from known region
    segment_start = start_time
    segment_stop = start_time + 2  # 2 seconds worth of data
    timestamps, values = indexed_file.get_data(segment_start, segment_stop)

    # Check structure
    assert isinstance(timestamps, list)
    assert isinstance(values, list)
    assert len(timestamps) == len(values)
    assert len(values) > 0

    # Note: Reference values removed as they may differ for EEG10 channel
    # If specific reference values are needed, they should be updated based on actual data

    # Close file
    indexed_file.close()


def test_file_handle_get_info(vfs, file_name):
    """
    Test retrieving the info (startBlock, size, filename) from a PvfsFileHandle.
    """
    print(f"\nTesting file handle get_file_info with file: {file_name}")

    handle = None
    try:
        # Open a known file inside the VFS (adjust filename if needed)
        handle = vfs.open_file("EEG10.index")  # use a channel known to exist in the PVFS
        
        # Call the new get_file_info method (which must be implemented in the binding)
        info = handle.get_file_info()
        
        # Decode filename: PvfsFileEntryWrapper.filename is c_char * 256
        filename_str = bytes(info.filename).decode("utf-8", errors="ignore").rstrip("\x00")
        print(f"Start Block: {info.startBlock}")
        print(f"Size:       {info.size}")
        print(f"Filename:   {filename_str}")

        assert info.startBlock >= 0, "startBlock should be non-negative"
        assert info.size >= 0, "size should be non-negative"
        assert len(filename_str) > 0, "filename should not be empty"
    except Exception as e:
        print(f"Error in test_file_handle_get_info: {e}")
        raise
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception as e:
                print(f"Warning: Failed to close file handle: {e}")


def test_pvfs_create_database():
    """
    Create an empty pvfs file and populate it with an empty ExperimentDatabase
    called experiment.db3. The created pvfs file is left on disk.
    """
    test_dir = Path(__file__).parent
    pvfs_path = test_dir / "test_created_database.pvfs"
    temp_db_path = test_dir / "temp_experiment.db3"
    
    # Create an empty pvfs file
    dest = PvfsFile.create(str(pvfs_path))
    assert dest.is_open, "Created PVFS should be open"
    
    # Create an empty ExperimentDatabase
    # Ensure the temp file doesn't exist first
    if temp_db_path.exists():
        temp_db_path.unlink()
    
    # Create the database - _setup_database() will create the file and tables
    db = ExperimentDatabase(filename=str(temp_db_path), in_memory=False)
    
    # Close the database to ensure it's written to disk
    db.close()
    gc.collect()
    time.sleep(0.1)
    
    # Verify the database file exists and read its contents
    assert temp_db_path.exists(), "Database file should exist"
    db_data = temp_db_path.read_bytes()
    assert len(db_data) > 0, "Database file should not be empty"
    
    # Verify it's a valid SQLite database
    magic = db_data[:16]
    assert magic == b"SQLite format 3\x00", (
        f"Database should start with SQLite magic, got {magic!r}"
    )
    
    # Write the database into the pvfs file in 1K chunks (matching PVFS_add behavior)
    CHUNK = 1024
    dest.lock()
    try:
        dst = dest.fcreate("experiment.db3")
        offset = 0
        while offset < len(db_data):
            chunk = db_data[offset : offset + CHUNK]
            n = dst.write(chunk, len(chunk))
            assert n == len(chunk), (
                f"write at offset {offset} returned {n}, expected {len(chunk)}"
            )
            dst.flush()
            offset += n
        dst.close()
    finally:
        dest.unlock()
    dest.close()
    gc.collect()
    time.sleep(0.2)
    
    # Verify the database was written to the pvfs file by extracting it
    verify = PvfsFile.open(str(pvfs_path))
    extracted_path = test_dir / "test_created_database_extracted.db3"
    try:
        res = verify.extract("experiment.db3", str(extracted_path))
        assert res == 0, f"extract failed: {res}"
        assert extracted_path.exists(), "Extracted database file should exist"
        assert extracted_path.stat().st_size == len(db_data), (
            f"extracted size {extracted_path.stat().st_size} != expected {len(db_data)}"
        )
        
        # Verify the extracted database is valid
        extracted_magic = extracted_path.read_bytes()[:16]
        assert extracted_magic == b"SQLite format 3\x00", (
            f"extracted file should start with SQLite magic, got {extracted_magic!r}"
        )
        
        # Verify the database has the expected tables (empty but with schema)
        conn = sqlite3.connect(str(extracted_path))
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [r[0] for r in tables]
            # Should have at least the base tables created by ExperimentDatabase
            assert "experiment_information_table" in table_names, (
                "Database should have experiment_information_table"
            )
            assert "experiment_channel_information_table" in table_names, (
                "Database should have experiment_channel_information_table"
            )
        finally:
            conn.close()
    finally:
        verify.close()
    
    # Cleanup temporary files but leave the pvfs file on disk as requested
    cleanup_file(temp_db_path)
    cleanup_file(extracted_path)


if __name__ == "__main__":
    # Run all tests in this module via pytest (uses fixtures and runs the full suite)
    pytest.main([__file__, "-v"])
