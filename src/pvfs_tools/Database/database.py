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
        except SQLAlchemyError as e:
            raise DatabaseConnectionError(f"Failed to connect to database: {e}")

    def _create_tables(self):
        """Create database tables if they don't exist."""
        with self._engine.connect() as conn:
            # Create experiment information table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS experiment_information_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    start_time_seconds INTEGER,
                    start_time_subseconds INTEGER,
                    end_time_seconds INTEGER,
                    end_time_subseconds INTEGER,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """))
            
            # Create channel information table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS experiment_channel_information (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (experiment_id) REFERENCES experiment_information_table(id)
                )
            """))
            conn.commit()

    def set_information(self, information: ExperimentInformation) -> bool:
        """Set experiment information.
        
        Args:
            information: ExperimentInformation object containing the data.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            with self.session() as session:
                # Convert HighTime objects to database format
                start_time_seconds = information.start_time.seconds if information.start_time else None
                start_time_subseconds = information.start_time.subseconds if information.start_time else None
                end_time_seconds = information.end_time.seconds if information.end_time else None
                end_time_subseconds = information.end_time.subseconds if information.end_time else None

                session.execute(text("""
                    INSERT INTO experiment_information_table 
                    (name, description, start_time_seconds, start_time_subseconds,
                     end_time_seconds, end_time_subseconds, created_at, updated_at)
                    VALUES (:name, :description, :start_time_seconds, :start_time_subseconds,
                            :end_time_seconds, :end_time_subseconds, :created_at, :updated_at)
                """), {
                    "name": information.name,
                    "description": information.description,
                    "start_time_seconds": start_time_seconds,
                    "start_time_subseconds": start_time_subseconds,
                    "end_time_seconds": end_time_seconds,
                    "end_time_subseconds": end_time_subseconds,
                    "created_at": information.created_at,
                    "updated_at": information.updated_at
                })
            return True
        except Exception as e:
            raise TableError(f"Failed to set experiment information: {e}")

    def get_information(self) -> Optional[ExperimentInformation]:
        """Get experiment information.
        
        Returns:
            Optional[ExperimentInformation]: The experiment information if found, None otherwise.
        """
        try:
            with self.session() as session:
                result = session.execute(text("""
                    SELECT * FROM experiment_information_table ORDER BY experiment_id DESC LIMIT 1
                """)).fetchone()
                
                if not result:
                    return None

                def convert_subseconds(subsec_str: str) -> float:
                    """Convert decimal subsecond string to float subseconds."""
                    if not subsec_str:
                        return 0.0
                    try:
                        return float(subsec_str)
                    except (ValueError, TypeError):
                        return 0.0

                # Convert database format to HighTime objects
                start_time = HighTime(
                    result.start_time_seconds,
                    convert_subseconds(result.start_time_sub_seconds)
                ) if result.start_time_seconds is not None else None

                end_time = HighTime(
                    result.end_time_seconds,
                    convert_subseconds(result.end_time_sub_seconds)
                ) if result.end_time_seconds is not None else None

                return ExperimentInformation(
                    id=result.experiment_id,  # This is a VARCHAR in the database
                    name=result.animal_id,    # Using animal_id as the name
                    description=result.comments,
                    start_time=start_time,
                    end_time=end_time,
                    created_at=datetime.now(),  # These fields don't exist in the old schema
                    updated_at=datetime.now()
                )
        except Exception as e:
            raise TableError(f"Failed to get experiment information: {e}")

    def update_experiment_start_time(self, start_time: HighTime) -> bool:
        """Update the experiment start time.
        
        Args:
            start_time: New start time.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            with self.session() as session:
                session.execute(text("""
                    UPDATE experiment_information_table 
                    SET start_time_seconds = :seconds,
                        start_time_subseconds = :subseconds,
                        updated_at = :updated_at
                    WHERE id = (SELECT MAX(id) FROM experiment_information_table)
                """), {
                    "seconds": start_time.seconds,
                    "subseconds": start_time.subseconds,
                    "updated_at": datetime.now()
                })
            return True
        except Exception as e:
            raise TableError(f"Failed to update experiment start time: {e}")

    def update_experiment_end_time(self, end_time: HighTime) -> bool:
        """Update the experiment end time.
        
        Args:
            end_time: New end time.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            with self.session() as session:
                session.execute(text("""
                    UPDATE experiment_information_table 
                    SET end_time_seconds = :seconds,
                        end_time_subseconds = :subseconds,
                        updated_at = :updated_at
                    WHERE id = (SELECT MAX(id) FROM experiment_information_table)
                """), {
                    "seconds": end_time.seconds,
                    "subseconds": end_time.subseconds,
                    "updated_at": datetime.now()
                })
            return True
        except Exception as e:
            raise TableError(f"Failed to update experiment end time: {e}")

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
        if os.path.exists(target_file):
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
                        # Get column names
                        columns = [desc[0] for desc in source_conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
                        
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
        try:
            # Create a temporary connection to the destination database
            dest_engine = create_engine(f"sqlite:///{filename}")
            
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
                        # Get column names
                        columns = [desc[0] for desc in source_conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
                        
                        # Insert data into the destination database
                        with dest_engine.connect() as dest_conn:
                            for row in data:
                                dest_conn.execute(
                                    text(f"INSERT INTO {table_name} ({','.join(columns)}) VALUES ({','.join([':' + col for col in columns])})"),
                                    dict(zip(columns, row))
                                )
                            dest_conn.commit()
            
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to save database to file: {e}")

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

                return ChannelInformation(
                    name=result.name,
                    id=result.id,
                    type=result.type,
                    filename=result.filename,
                    comments=result.comments,
                    unit=result.unit,
                    data_rate=result.data_rate,
                    data_rate_float=result.data_rate_float,
                    start_time=start_time,
                    end_time=end_time,
                    device_name=result.device_name,
                    pvfs_filename=result.pvfs_filename,
                    low_range=result.low_range,
                    high_range=result.high_range
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