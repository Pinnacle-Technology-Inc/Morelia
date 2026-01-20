"""
Python implementation of PVFSDataFile for PVFS file creation, opening, and closing.

This module provides a Python interface for creating, opening, and managing PVFS files,
similar to the C++ PVFSDataFile class but adapted for Python use.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from .pvfs_binding import PvfsFile, HighTime
from .indexed_data_file import IndexedDataFile
from .video_data_file import VideoDataFile
from ..Database.database import ExperimentDatabase
from ..Database.models import ExperimentInformation, ChannelInformation

class PvfsDataFile:
    """Python implementation of PVFSDataFile for managing PVFS files.
    
    This class provides functionality for creating, opening, and managing PVFS files,
    including database management and channel access.
    """
    
    # Constants
    EXPERIMENT_DB_FILENAME = "experiment.db3"
    EXPERIMENT_DB_BACKUP_FILENAME = "experiment_backup.db3"
    LOCK_FILE_STRING = ".LOCK"
    
    def __init__(self, filename: str = "", read_only: bool = False):
        """Initialize the PVFS data file.
        
        Args:
            filename: Path to the PVFS file
            read_only: Whether to open in read-only mode
        """
        self._filename = filename
        self._filepath = ""
        self._read_only = read_only
        self._pvfs = None
        self._database = None
        self._indexed_data_files: Dict[str, IndexedDataFile] = {}
        self._video_files: Dict[str, VideoDataFile] = {}
        self._search_paths: List[Path] = []
        self._unique_id = str(uuid.uuid4())
        self._temp_db_path: Optional[str] = None
        self._owns_temp_db: bool = False
        
        # Try to open the file if filename is provided
        if filename:
            if not self.open(filename):
                if not read_only and not os.path.exists(filename):
                    self.create(filename)
    
    def create(self, filename: str, block_size: int = 0x4000) -> bool:
        """Create a new PVFS file.
        
        Args:
            filename: Path to the PVFS file to create
            block_size: Block size for the PVFS file
            
        Returns:
            bool: True if successful, False otherwise
        """
        if self._read_only:
            raise RuntimeError("Cannot create file in read-only mode")
        
        # Close any existing file
        self.close()
        
        if not filename:
            return False
        
        try:
            print(f"  - Creating PVFS file: {filename}")
            
            # Create the PVFS file
            self._pvfs = PvfsFile.create(filename)
            if not self._pvfs:
                print("  - Failed to create PVFS file object")
                return False
            
            print("  - PVFS file object created successfully")
            
            # Create in-memory database (like the C++ implementation)
            print(f"  - Creating in-memory database")
            pvfs_dir = Path(filename).parent
            temp_db_path = str((pvfs_dir / f"temp_{self._unique_id}.db3").absolute())

            self._database = ExperimentDatabase(filename=temp_db_path, in_memory=False)
            db_create_result = self._database.create(temp_db_path)
            self._temp_db_path = temp_db_path
            self._owns_temp_db = True
            print("  - ExperimentDatabase instance created")
            
            db_create_result = self._database.create()
            print(f"  - Database create result: {db_create_result}")
            
            if not db_create_result:
                print("  - Failed to create database")
                return False
            
            print("  - Database created successfully")
            
            # Set file information
            file_path = Path(filename)
            self._filename = file_path.name
            self._filepath = str(file_path.absolute())
            
            print(f"  - File info set: {self._filename} -> {self._filepath}")
            
            # Add the directory to search paths
            self.add_search_path(file_path.parent)
            
            return True
            
        except Exception as e:
            print(f"Error creating PVFS file: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def open(self, filename: str) -> bool:
        """Open an existing PVFS file.
        
        Args:
            filename: Path to the PVFS file to open
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not filename:
            return False
        
        # Close any existing file
        self.close()
        
        try:
            # Try to open the PVFS file
            self._pvfs = PvfsFile.open(filename)
            if not self._pvfs:
                return False
            
            # Set file information
            file_path = Path(filename)
            self._filename = file_path.name
            self._filepath = str(file_path.absolute())
            
            # Add the directory to search paths
            self.add_search_path(file_path.parent)
            
            # Load database
            if not self._load_database():
                return False
            
            # Open channels
            return self._open_channels(filename)
            
        except Exception as e:
            print(f"Error opening PVFS file: {e}")
            return False
    
    def close(self):
        """Close the PVFS file and save all data."""
        try:
            print("  - Closing PVFS file and saving database...")
            
            if self._database and self._pvfs:
                self.flush()

            if self._owns_temp_db and self._temp_db_path and os.path.exists(self._temp_db_path):
                try:
                    os.remove(self._temp_db_path)
                except OSError:
                    pass
            self._temp_db_path = None
            self._owns_temp_db = False

            # Close the PVFS file
            if self._pvfs:
                self._pvfs.close()
                self._pvfs = None
            
            # Close the database
            if self._database:
                self._database.close()
                self._database = None
            
            print("  - PVFS file closed successfully")
            return True
            
        except Exception as e:
            print(f"Error closing PVFS file: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def flush(self, synchronous: bool = True) -> None:
        """Flush all data to disk.
        
        Args:
            synchronous: Whether to flush synchronously
        """
        # Flush indexed data files
        for indexed_file in self._indexed_data_files.values():
            if indexed_file:
                indexed_file.flush(synchronous)
        
        self._save_database()

    
    def create_channel(self, channel_name: str, data_rate: float = 1.0, 
                      data_type: int = 1, unit: str = "uV") -> Optional[IndexedDataFile]:
        """Create a new data channel in the PVFS file.
        
        Args:
            channel_name: Name of the channel
            data_rate: Data rate in samples per second
            data_type: Type of data (1 for regular data)
            unit: Unit of measurement
            
        Returns:
            IndexedDataFile: The created indexed data file, or None if failed
        """
        if not self._pvfs or self._read_only:
            return None
        
        try:
            # Create indexed data file
            indexed_file = IndexedDataFile(self._pvfs, channel_name, create=True)
            # The constructor now handles creation, so no need to call create() again
            if not indexed_file._index_file or not indexed_file._data_file:
                return None
            
            # Set data rate
            indexed_file.set_data_rate(data_rate)
            
            # Add to our list
            self._indexed_data_files[channel_name] = indexed_file
            
            # Add channel information to database
            if self._database:
                channel_info = ChannelInformation(
                    name=channel_name,
                    id=len(self._indexed_data_files),
                    type=data_type,
                    filename=channel_name,
                    comments=f"Channel {channel_name}",
                    unit=unit,
                    data_rate=int(data_rate),
                    data_rate_float=str(data_rate),
                    device_name="PVFS Data File",
                    pvfs_filename=channel_name
                )
                self._database.add_channel_info(channel_info)
            
            return indexed_file
            
        except Exception as e:
            print(f"Error creating channel {channel_name}: {e}")
            return None
    
    def open_channel(self, channel_name: str) -> Optional[IndexedDataFile]:
        """Open an existing data channel.
        
        Args:
            channel_name: Name of the channel to open
            
        Returns:
            IndexedDataFile: The opened indexed data file, or None if failed
        """
        if not self._pvfs:
            return None
        
        # Check if already open
        if channel_name in self._indexed_data_files:
            return self._indexed_data_files[channel_name]
        
        try:
            # Try to open the indexed data file
            indexed_file = IndexedDataFile(self._pvfs, channel_name)
            if indexed_file.open(self._pvfs, channel_name):
                self._indexed_data_files[channel_name] = indexed_file
                return indexed_file
            
        except Exception as e:
            print(f"Error opening channel {channel_name}: {e}")
        
        return None
    
    def get_channel_names(self) -> List[str]:
        """Get list of available channel names.
        
        Returns:
            List[str]: List of channel names
        """
        if not self._database:
            return []
        
        try:
            return self._database.get_channel_names()
        except Exception as e:
            print(f"Error getting channel names: {e}")
            return []
    
    def get_channel_info(self, channel_name: str) -> Optional[ChannelInformation]:
        """Get information about a specific channel.
        
        Args:
            channel_name: Name of the channel
            
        Returns:
            ChannelInformation: Channel information, or None if not found
        """
        if not self._database:
            return None
        
        try:
            return self._database.get_channel_info(channel_name)
        except Exception as e:
            print(f"Error getting channel info for {channel_name}: {e}")
            return None
    
    def set_experiment_info(self, name: str, description: str = "", 
                           start_time: Optional[HighTime] = None,
                           end_time: Optional[HighTime] = None) -> bool:
        """Set experiment information.
        
        Args:
            name: Name of the experiment
            description: Description of the experiment
            start_time: Start time of the experiment
            end_time: End time of the experiment
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._database:
            return False
        
        try:
            experiment_info = ExperimentInformation(
                id=self._unique_id,
                name=name,
                description=description,
                start_time=start_time or HighTime(datetime.now().timestamp()),
                end_time=end_time
            )
            
            return self._database.set_information(experiment_info)
            
        except Exception as e:
            print(f"Error setting experiment info: {e}")
            return False
    
    def get_experiment_info(self) -> Optional[ExperimentInformation]:
        """Get experiment information.
        
        Returns:
            ExperimentInformation: Experiment information, or None if not available
        """
        if not self._database:
            return None
        
        try:
            return self._database.get_information()
        except Exception as e:
            print(f"Error getting experiment info: {e}")
            return None
    
    def add_search_path(self, path: Path) -> None:
        """Add a search path for external files.
        
        Args:
            path: Path to add to search list
        """
        if path not in self._search_paths:
            self._search_paths.append(path)
    
    def _load_database(self) -> bool:
        """Load the database from the PVFS file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._pvfs:
            return False
        
        try:
            print(f"    - Loading database from PVFS...")
            # Create database
            self._database = ExperimentDatabase()
            
            # Try to extract database from PVFS
            temp_db_path = os.path.abspath(f"temp_{self._unique_id}.db3")
            print(f"    - Temporary database path: {temp_db_path}")
            
            # Try different possible database filenames
            db_filenames = [
                self.EXPERIMENT_DB_FILENAME,
                f"{self._filename}.db3",
                self.EXPERIMENT_DB_BACKUP_FILENAME
            ]
            
            print(f"    - Trying database filenames: {db_filenames}")
            
            for db_filename in db_filenames:
                try:
                    print(f"    - Attempting to extract: {db_filename}")
                    result = self._pvfs.extract(db_filename, temp_db_path)
                    print(f"    - Extract result for {db_filename}: {result}")
                    if result == 0 and os.path.exists(temp_db_path):
                        print(f"    - Successfully extracted {db_filename} to {temp_db_path}")
                        # Load the database
                        if self._database = ExperimentDatabase(filename=temp_db_path, in_memory=False)
                            # ensure connection to that file
                            if not self._database.open(temp_db_path):
                                return False

                            self._temp_db_path = temp_db_path
                            self._owns_temp_db = True  # we'll clean it up on close
                            return True
                        else:
                            print(f"    - Failed to load database from {temp_db_path}")
                    else:
                        print(f"    - Extract failed for {db_filename}: result={result}, file_exists={os.path.exists(temp_db_path)}")
                except Exception as e:
                    print(f"    - Exception during extract of {db_filename}: {e}")
                    continue
            
            print(f"    - No database found, creating in-memory database")
            # If no database found, create a new one
            temp_db_path = os.path.abspath(f"temp_{self._unique_id}.db3")
            self._database = ExperimentDatabase(filename=temp_db_path, in_memory=False)
            if not self._database.create(temp_db_path):
                return False
            self._temp_db_path = temp_db_path
            self._owns_temp_db = True
            return True
            
        except Exception as e:
            print(f"Error loading database: {e}")
            return False
    
    def _save_database(self, targets: Optional[list[str]] = None) -> bool:
        targets = targets or [self.EXPERIMENT_DB_FILENAME, self.EXPERIMENT_DB_BACKUP_FILENAME]
        # 1) make a clean snapshot file from the *current* DB
        snapshot_path = os.path.abspath(f"temp_snapshot_{self._unique_id}.db3")
        if not self._database.save_to_file(snapshot_path):
            return False  # snapshot failed

        # 2) read bytes once
        with open(snapshot_path, "rb") as f:
            db_data = f.read()

        # 3) write the same bytes to each target inside PVFS
        ok = True
        for name in targets:
            handle = self._pvfs.create_file(name)
            if not handle:
                ok = False
                break
            handle.write(db_data, len(db_data))
            handle.flush(commit=True)
            handle.close()

        # 4) cleanup
        try: os.remove(snapshot_path)
        except OSError: pass

        return ok

    
    def _open_channels(self, filename: str) -> bool:
        """Open all channels in the PVFS file.
        
        Args:
            filename: Path to the PVFS file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get channel names from database
            channel_names = self.get_channel_names()
            
            # Try to open each channel
            for channel_name in channel_names:
                self.open_channel(channel_name)
            
            return True
            
        except Exception as e:
            print(f"Error opening channels: {e}")
            return False
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    @property
    def filename(self) -> str:
        """Get the filename."""
        return self._filename
    
    @property
    def filepath(self) -> str:
        """Get the full filepath."""
        return self._filepath
    
    @property
    def is_read_only(self) -> bool:
        """Check if file is opened in read-only mode."""
        return self._read_only
    
    @property
    def is_open(self) -> bool:
        """Check if file is open."""
        return self._pvfs is not None 