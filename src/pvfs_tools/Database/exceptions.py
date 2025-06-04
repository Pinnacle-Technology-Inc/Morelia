"""
Custom exceptions for the database module.
"""

class DatabaseError(Exception):
    """Base exception for database-related errors."""
    pass

class DatabaseConnectionError(DatabaseError):
    """Exception raised when there are issues connecting to the database."""
    pass

class TableError(DatabaseError):
    """Exception raised when there are issues with database tables."""
    pass 