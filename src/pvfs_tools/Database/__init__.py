"""
Python implementation of the Experiment Database system.
This package provides a Python interface to the experiment database system,
replacing the original C++/Qt implementation.
"""

from .database import ExperimentDatabase
from .models import ExperimentInformation, ExperimentChannelInformation
from .exceptions import DatabaseError

__version__ = "0.1.0"
__all__ = ["ExperimentDatabase", "ExperimentInformation", "ExperimentChannelInformation", "DatabaseError"] 