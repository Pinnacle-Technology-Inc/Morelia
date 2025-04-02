"""
Core module for PVFS file system access.
This module provides low-level access to the PVFS file system through a C++ wrapper.
"""

from .pvfs_binding import PvfsFile

__version__ = "0.1.0"
__all__ = ["PvfsFile"] 