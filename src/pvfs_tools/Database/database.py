"""
Python implementation of the Experiment Database system.
This package provides a Python interface to the experiment database system,
replacing the original C++/Qt implementation.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
import json
from typing import List, Optional, Dict, Any
from .models import ExperimentInformation, ExperimentChannelInformation, ChannelInformation, Annotation
from ..Core.pvfs_binding import HighTime
from .exceptions import DatabaseError, DatabaseConnectionError, TableError
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

class ExperimentDatabase:
    """Main database class for managing experiment data."""
    
    DEFAULT_FILENAME = "experiment.db"
    ALL_CHANNELS = -1

    def __init__(self, filename: Optional[str] = None, in_memory: bool = False):
        """Initialize the database connection.
        
        Args:
            filename: Path to the database file. If None, uses DEFAULT_FILENAME.
            in_memory: If True, creates an in-memory database. If False, uses file-based storage.
        """
        self.filename = filename or self.DEFAULT_FILENAME
        self.in_memory = in_memory
        self._engine = None
        self._Session = None
        self._setup_database()

    def _setup_database(self):
        """Set up the database connection and create tables if they don't exist."""
        try:
            if self.in_memory:
                # Use SQLite in-memory database
                self._engine = create_engine('sqlite:///:memory:')
                self._Session = sessionmaker(bind=self._engine)
                self._create_tables()
            else:
                # Use file-based database
                self._engine = create_engine(f"sqlite:///{self.filename}")
                self._Session = sessionmaker(bind=self._engine)
                # Only create tables if the database is new (empty)
                if not os.path.exists(self.filename) or os.path.getsize(self.filename) == 0:
                    self._create_tables()
                # Force DELETE journal mode so all committed data resides in the
                # main database file.  Some Linux distributions default to WAL,
                # which stores recent writes in a separate -wal file that
                # shutil.copy2 (used by PvfsDataFile._save_database) would miss.
                with self._engine.connect() as conn:
                    conn.execute(text("PRAGMA journal_mode=DELETE"))
                    conn.commit()
        except SQLAlchemyError as e:
            raise DatabaseConnectionError(f"Failed to connect to database: {e}")

    def _schema_ddl(self):
        """Return the CREATE TABLE IF NOT EXISTS statements for the standard schema.
        Matches the 14-table layout of standard PVFS (e.g. sine.pvfs) so generated DBs
        are structurally compatible.
        """
        # Column names and order match C++ base (working/experiment_source/*.cpp).
        # No separate id column; first column is experiment_id (varChar in C++).
        return [
            """
            CREATE TABLE IF NOT EXISTS experiment_information_table (
                experiment_id TEXT,
                animal_id TEXT,
                researcher TEXT,
                start_time_seconds INTEGER,
                start_time_sub_seconds REAL,
                end_time_seconds INTEGER,
                end_time_sub_seconds REAL,
                timezone INTEGER,
                is_dst INTEGER,
                comments TEXT,
                num_channels INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS experiment_channel_information_table (
                name TEXT NOT NULL,
                id INTEGER,
                type INTEGER,
                filename TEXT,
                comments TEXT,
                unit TEXT,
                data_rate INTEGER,
                data_rate_float REAL,
                start_time_seconds INTEGER,
                start_time_sub_seconds REAL,
                end_time_seconds INTEGER,
                end_time_sub_seconds REAL,
                device_name TEXT,
                pvfs_filename TEXT,
                low_range REAL,
                high_range REAL
            )
            """,
            "CREATE TABLE IF NOT EXISTS annotation_parameters_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS annotation_types (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS device_preferences_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS experiment_annotation_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS experiment_artifacts (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS experiment_channel_parameters_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS experiment_extra_parameters_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS experiment_file_time_segment_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS group_housing_zones_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS object_events_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS object_properties_table (id INTEGER PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS view_table (id INTEGER PRIMARY KEY)",
        ]

    def _create_tables(self):
        """Create database tables if they don't exist. Schemas match the base (sine.pvfs) format."""
        with self._engine.connect() as conn:
            for ddl in self._schema_ddl():
                conn.execute(text(ddl))
            conn.commit()

    def _create_tables_on_engine(self, engine):
        """Create schema on an arbitrary engine (e.g. destination in save_to_file)."""
        with engine.connect() as conn:
            for ddl in self._schema_ddl():
                conn.execute(text(ddl))
            conn.commit()

    def set_information(self, information: ExperimentInformation) -> bool:
        """Set experiment information. Uses base (sine.pvfs) column names."""
        try:
            with self.session() as session:
                start_time_seconds = information.start_time.seconds if information.start_time else None
                start_time_sub_seconds = information.start_time.subseconds if information.start_time else None
                end_time_seconds = information.end_time.seconds if information.end_time else None
                end_time_sub_seconds = information.end_time.subseconds if information.end_time else None

                session.execute(text("""
                    INSERT INTO experiment_information_table 
                    (experiment_id, animal_id, researcher, start_time_seconds, start_time_sub_seconds,
                     end_time_seconds, end_time_sub_seconds, timezone, is_dst, comments, num_channels)
                    VALUES (:experiment_id, :animal_id, :researcher, :start_time_seconds, :start_time_sub_seconds,
                            :end_time_seconds, :end_time_sub_seconds, :timezone, :is_dst, :comments, :num_channels)
                """), {
                    "experiment_id": "Experiment",
                    "animal_id": information.name if information.name else "Animal",
                    "researcher": "Test",
                    "start_time_seconds": start_time_seconds,
                    "start_time_sub_seconds": start_time_sub_seconds,
                    "end_time_seconds": end_time_seconds,
                    "end_time_sub_seconds": end_time_sub_seconds,
                    "timezone": -6,
                    "is_dst": 1,
                    "comments": information.description,
                    "num_channels": 0,
                })
            return True
        except Exception as e:
            raise TableError(f"Failed to set experiment information: {e}")

    def get_information(self) -> Optional[ExperimentInformation]:
        """Get experiment information. Uses base (sine.pvfs) schema column names."""
        try:
            with self.session() as session:
                result = session.execute(text("""
                    SELECT *, rowid FROM experiment_information_table ORDER BY experiment_id DESC, rowid DESC LIMIT 1
                """)).fetchone()

                if not result:
                    return None

                def _sub(val) -> float:
                    if val is None:
                        return 0.0
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return 0.0

                eid = result.experiment_id if result.experiment_id is not None else result.rowid
                start_time = HighTime(
                    result.start_time_seconds, _sub(result.start_time_sub_seconds)
                ) if result.start_time_seconds is not None else None
                end_time = HighTime(
                    result.end_time_seconds, _sub(result.end_time_sub_seconds)
                ) if result.end_time_seconds is not None else None

                return ExperimentInformation(
                    id=str(eid) if eid is not None else "0",
                    name=result.animal_id or "",
                    description=result.comments,
                    start_time=start_time,
                    end_time=end_time,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
        except Exception as e:
            raise TableError(f"Failed to get experiment information: {e}")

    def update_experiment_start_time(self, start_time: HighTime) -> bool:
        """Update the experiment start time. Uses base schema (start_time_sub_seconds)."""
        try:
            with self.session() as session:
                session.execute(text("""
                    UPDATE experiment_information_table 
                    SET start_time_seconds = :seconds, start_time_sub_seconds = :sub_seconds
                    WHERE rowid = (SELECT MAX(rowid) FROM experiment_information_table)
                """), {"seconds": start_time.seconds, "sub_seconds": start_time.subseconds})
            return True
        except Exception as e:
            raise TableError(f"Failed to update experiment start time: {e}")

    def update_experiment_end_time(self, end_time: HighTime) -> bool:
        """Update the experiment end time. Uses base schema (end_time_sub_seconds)."""
        try:
            with self.session() as session:
                session.execute(text("""
                    UPDATE experiment_information_table 
                    SET end_time_seconds = :seconds, end_time_sub_seconds = :sub_seconds
                    WHERE rowid = (SELECT MAX(rowid) FROM experiment_information_table)
                """), {"seconds": end_time.seconds, "sub_seconds": end_time.subseconds})
            return True
        except Exception as e:
            raise TableError(f"Failed to update experiment end time: {e}")

    def update_channel_start_time(self, channel_name: str, start_time: HighTime) -> bool:
        """Update a channel's start time by name."""
        try:
            with self.session() as session:
                session.execute(text("""
                    UPDATE experiment_channel_information_table 
                    SET start_time_seconds = :seconds, start_time_sub_seconds = :sub_seconds
                    WHERE name = :name
                """), {"name": channel_name, "seconds": start_time.seconds, "sub_seconds": start_time.subseconds})
            return True
        except Exception as e:
            raise TableError(f"Failed to update channel start time: {e}")

    def update_channel_end_time(self, channel_name: str, end_time: HighTime) -> bool:
        """Update a channel's end time by name."""
        try:
            with self.session() as session:
                session.execute(text("""
                    UPDATE experiment_channel_information_table 
                    SET end_time_seconds = :seconds, end_time_sub_seconds = :sub_seconds
                    WHERE name = :name
                """), {"name": channel_name, "seconds": end_time.seconds, "sub_seconds": end_time.subseconds})
            return True
        except Exception as e:
            raise TableError(f"Failed to update channel end time: {e}")

    def add_channel_info(self, channel_info: ChannelInformation) -> bool:
        """Insert a channel row into experiment_channel_information_table.
        Ensures an experiment row exists (inserts one if empty). Matches C++ schema (no experiment_id in channel table).
        """
        try:
            with self.session() as session:
                row = session.execute(text("""
                    SELECT rowid FROM experiment_information_table ORDER BY rowid DESC LIMIT 1
                """)).fetchone()
                if row is None:
                    session.execute(text("""
                        INSERT INTO experiment_information_table
                        (experiment_id, animal_id, researcher, start_time_seconds, start_time_sub_seconds,
                         end_time_seconds, end_time_sub_seconds, timezone, is_dst, comments, num_channels)
                        VALUES ('Experiment', 'Animal', 'Test', 0, 0.0, 0, 0.0, -6, 1, '', 0)
                    """))

                start_sec = channel_info.start_time.seconds if channel_info.start_time else None
                start_sub = channel_info.start_time.subseconds if channel_info.start_time else None
                end_sec = channel_info.end_time.seconds if channel_info.end_time else None
                end_sub = channel_info.end_time.subseconds if channel_info.end_time else None

                # Column order matches C++ FIELD_NAMES (16 columns): name, id, type, filename, comments, unit,
                # data_rate, data_rate_float, start_time_*, end_time_*, device_name, pvfs_filename, low_range, high_range
                channel_id = channel_info.id if channel_info.id is not None else 0
                low_r = float(channel_info.low_range) if channel_info.low_range is not None else None
                high_r = float(channel_info.high_range) if channel_info.high_range is not None else None
                session.execute(text("""
                    INSERT INTO experiment_channel_information_table (
                        name, id, type, filename, comments, unit, data_rate, data_rate_float,
                        start_time_seconds, start_time_sub_seconds, end_time_seconds, end_time_sub_seconds,
                        device_name, pvfs_filename, low_range, high_range
                    ) VALUES (
                        :name, :id, :type, :filename, :comments, :unit, :data_rate, :data_rate_float,
                        :start_time_seconds, :start_time_sub_seconds, :end_time_seconds, :end_time_sub_seconds,
                        :device_name, :pvfs_filename, :low_range, :high_range
                    )
                """), {
                    "name": channel_info.name,
                    "id": channel_id,
                    "type": channel_info.type,
                    "filename": channel_info.filename or "",
                    "comments": channel_info.comments or "",
                    "unit": channel_info.unit or "",
                    "data_rate": channel_info.data_rate,
                    "data_rate_float": float(channel_info.data_rate_float) if channel_info.data_rate_float not in (None, "") else None,
                    "start_time_seconds": start_sec,
                    "start_time_sub_seconds": start_sub,
                    "end_time_seconds": end_sec,
                    "end_time_sub_seconds": end_sub,
                    "device_name": channel_info.device_name or "",
                    "pvfs_filename": channel_info.pvfs_filename or "",
                    "low_range": low_r,
                    "high_range": high_r,
                })
                # Keep experiment num_channels in sync (total channel count; one experiment per DB in C++ schema)
                session.execute(text("""
                    UPDATE experiment_information_table SET num_channels = (
                        SELECT COUNT(*) FROM experiment_channel_information_table
                    )
                    WHERE rowid = (SELECT MAX(rowid) FROM experiment_information_table)
                """))
            return True
        except Exception as e:
            raise TableError(f"Failed to add channel info: {e}")

    @contextmanager
    def session(self) -> Session:
        """Get a database session.
        
        Yields:
            SQLAlchemy session object.
        """
        session = self._Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create(self, filename: Optional[str] = None) -> bool:
        """Create a new database file.
        
        Args:
            filename: Path to the new database file. If None, uses self.filename.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        target_file = filename or self.filename
        target_abs = os.path.abspath(target_file)
        if os.path.exists(target_file):
            # If it's our current database (already open), we already have tables; don't remove
            if self._engine and os.path.abspath(self.filename) == target_abs:
                return True
            try:
                os.remove(target_file)
            except OSError:
                return False

        self.filename = target_file
        self._setup_database()
        return True

    def open(self, filename: str) -> bool:
        """Open an existing database file.
        
        Args:
            filename: Path to the database file.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        if not os.path.exists(filename):
            return False
        
        self.filename = filename
        self._setup_database()
        return True

    def close(self) -> bool:
        """Close the database connection.
        
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            if self._engine:
                self._engine.dispose()
            return True
        except Exception:
            return False

    def sync_to_disk(self) -> None:
        """Force all committed data to be written and checkpointed to the database file.
        Call before copying or reading the file (e.g. on WSL/Linux where durability matters).
        """
        if not self._engine:
            return
        try:
            with self._engine.connect() as conn:
                # Ensure DELETE journal mode (no WAL to miss on copy)
                conn.execute(text("PRAGMA journal_mode=DELETE"))
                conn.execute(text("PRAGMA wal_checkpoint(FULL)"))
                conn.commit()
        except Exception:
            pass

    def load_from_file(self, filename: str) -> bool:
        """Load database contents from a file into the current database.
        
        Args:
            filename: Path to the source database file.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            # Create a temporary connection to the source database
            source_engine = create_engine(f"sqlite:///{filename}")
            
            # Get all tables from the source database
            with source_engine.connect() as source_conn:
                tables = source_conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """)).fetchall()
                
                # Copy data from each table
                for (table_name,) in tables:
                    # Get all data from the source table
                    data = source_conn.execute(text(f"SELECT * FROM {table_name}")).fetchall()
                    if data:
                        # Get column names (PRAGMA table_info returns cid, name, type, ...; name is index 1)
                        columns = [desc[1] for desc in source_conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
                        
                        # Insert data into the current database
                        with self._engine.connect() as dest_conn:
                            for row in data:
                                dest_conn.execute(
                                    text(f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({','.join([':' + col for col in columns])})"),
                                    dict(zip(columns, row))
                                )
                            dest_conn.commit()
            
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to load database from file: {e}")

    def save_to_file(self, filename: str) -> bool:
        """Save the current database contents to a file.
        
        Args:
            filename: Path to the destination database file.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        dest_engine = create_engine(f"sqlite:///{filename}")
        try:
            # Ensure source has all data visible (e.g. WAL checkpointed) before copy
            with self._engine.connect() as source_sync:
                source_sync.execute(text("PRAGMA wal_checkpoint(FULL)"))
                source_sync.commit()
            # Create destination engine and ensure it has the same schema (empty file has no tables)
            self._create_tables_on_engine(dest_engine)

            # Get all tables from the current database
            with self._engine.connect() as source_conn:
                tables = source_conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """)).fetchall()
                
                # Copy data from each table
                for (table_name,) in tables:
                    # Get all data from the source table
                    data = source_conn.execute(text(f"SELECT * FROM {table_name}")).fetchall()
                    if data:
                        # Get column names (PRAGMA table_info returns cid, name, type, ...; name is index 1)
                        columns = [desc[1] for desc in source_conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
                        
                        # Insert data into the destination database
                        with dest_engine.connect() as dest_conn:
                            for row in data:
                                dest_conn.execute(
                                    text(f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({','.join([':' + col for col in columns])})"),
                                    dict(zip(columns, row))
                                )
                            dest_conn.commit()
            
            # Force destination file to be fully synced to disk (important on WSL/Linux
            # where otherwise the file may not be durable before we read it back).
            with dest_engine.connect() as sync_conn:
                sync_conn.execute(text("PRAGMA synchronous=FULL"))
                sync_conn.execute(text("PRAGMA wal_checkpoint(FULL)"))
                sync_conn.commit()
            
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to save database to file: {e}")
        finally:
            # Release all connections to the destination file so it can be deleted on Windows
            dest_engine.dispose()

    def get_channel_names(self) -> List[str]:
        """Get a list of all channel names from the experiment_channel_information_table.
        
        Returns:
            List[str]: List of channel names.
        """
        try:
            with self.session() as session:
                results = session.execute(text("""
                    SELECT name FROM experiment_channel_information_table ORDER BY name
                """)).fetchall()
                return [row[0] for row in results]
        except Exception as e:
            raise TableError(f"Failed to get channel names: {e}")

    def get_channel_info(self, name: str) -> Optional[ChannelInformation]:
        """Get all information for a specific channel by name.
        
        Args:
            name: Name of the channel to look up.
            
        Returns:
            Optional[ChannelInformation]: Channel information if found, None otherwise.
        """
        try:
            with self.session() as session:
                result = session.execute(text("""
                    SELECT * FROM experiment_channel_information_table 
                    WHERE name = :name
                """), {"name": name}).fetchone()
                
                if not result:
                    return None

                # Convert database format to HighTime objects
                start_time = HighTime(
                    result.start_time_seconds,
                    float(result.start_time_sub_seconds)
                ) if result.start_time_seconds is not None else None

                end_time = HighTime(
                    result.end_time_seconds,
                    float(result.end_time_sub_seconds)
                ) if result.end_time_seconds is not None else None

                # data_rate_float, low_range, high_range stored as REAL in DB; model uses str
                def _num_to_str(v):
                    if v is None:
                        return None
                    return str(v) if not isinstance(v, str) else v

                return ChannelInformation(
                    name=result.name,
                    id=result.id,
                    type=result.type,
                    filename=result.filename,
                    comments=result.comments,
                    unit=result.unit,
                    data_rate=result.data_rate,
                    data_rate_float=_num_to_str(result.data_rate_float),
                    start_time=start_time,
                    end_time=end_time,
                    device_name=result.device_name,
                    pvfs_filename=result.pvfs_filename,
                    low_range=_num_to_str(result.low_range),
                    high_range=_num_to_str(result.high_range)
                )
        except Exception as e:
            raise TableError(f"Failed to get channel information: {e}")

    def get_channel_annotations(self, channel_id: int) -> List[Annotation]:
        """Get all annotations for a specific channel.
        
        Args:
            channel_id: ID of the channel to get annotations for.
            
        Returns:
            List[Annotation]: List of annotations for the channel.
        """
        try:
            with self.session() as session:
                results = session.execute(text("""
                    SELECT * FROM experiment_annotation_table 
                    WHERE channel_id = :channel_id
                    ORDER BY start_time_seconds
                """), {"channel_id": channel_id}).fetchall()
                

                annotations = []
                for result in results:
                    # Convert database format to HighTime objects
                    start_time = HighTime(
                        result.start_time_seconds,
                        float(result.start_time_sub_seconds)
                    ) if result.start_time_seconds is not None else None

                    end_time = HighTime(
                        result.end_time_seconds,
                        float(result.end_time_sub_seconds)
                    ) if result.end_time_seconds is not None else None

                    annotations.append(Annotation(
                        unique_id=result.unique_id,
                        channel_id=result.channel_id,
                        start_time=start_time,
                        end_time=end_time,
                        comment=result.comment,
                        type=result.type,
                        creator=result.creator,
                        last_edited=result.last_edited,
                        uuid=result.uuid
                    ))
                return annotations
        except Exception as e:
            raise TableError(f"Failed to get channel annotations: {e}")

    def get_all_annotations(self) -> List[Annotation]:
        """Get all annotations from the experiment_annotation_table.
        
        Returns:
            List[Annotation]: List of all annotations.
        """
        try:
            with self.session() as session:
                results = session.execute(text("""
                    SELECT * FROM experiment_annotation_table 
                    ORDER BY start_time_seconds
                """)).fetchall()
                

                annotations = []
                for result in results:
                    # Convert database format to HighTime objects
                    start_time = HighTime(
                        result.start_time_seconds,
                        float(result.start_time_sub_seconds)
                    ) if result.start_time_seconds is not None else None

                    end_time = HighTime(
                        result.end_time_seconds,
                        float(result.end_time_sub_seconds)
                    ) if result.end_time_seconds is not None else None

                    annotations.append(Annotation(
                        unique_id=result.unique_id,
                        channel_id=result.channel_id,
                        start_time=start_time,
                        end_time=end_time,
                        comment=result.comment,
                        type=result.type,
                        creator=result.creator,
                        last_edited=result.last_edited,
                        uuid=result.uuid
                    ))
                return annotations
        except Exception as e:
            raise TableError(f"Failed to get all annotations: {e}") 