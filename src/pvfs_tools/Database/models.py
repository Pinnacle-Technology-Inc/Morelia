"""Data models for the experiment database system."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from ..Core.pvfs_binding import HighTime

class ExperimentInformation(BaseModel):
    """Information about an experiment."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    id: str = Field(..., description="Unique identifier for the experiment")
    name: str = Field(..., description="Name of the experiment")
    description: Optional[str] = Field(None, description="Description of the experiment")
    start_time: Optional[HighTime] = Field(None, description="Start time of the experiment")
    end_time: Optional[HighTime] = Field(None, description="End time of the experiment")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")

class ExperimentChannelInformation(BaseModel):
    """Information about a channel in an experiment."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    id: int = Field(..., description="Unique identifier for the channel")
    experiment_id: int = Field(..., description="ID of the parent experiment")
    name: str = Field(..., description="Name of the channel")
    description: Optional[str] = Field(None, description="Description of the channel")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")

class ChannelInformation(BaseModel):
    """Information about a channel in an experiment."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    name: str = Field(..., description="Name of the channel")
    id: int = Field(..., description="Unique identifier for the channel")
    type: int = Field(..., description="Type of the channel")
    filename: Optional[str] = Field(None, description="Filename associated with the channel")
    comments: Optional[str] = Field(None, description="Comments about the channel")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    data_rate: Optional[int] = Field(None, description="Data rate in samples per second")
    data_rate_float: Optional[str] = Field(None, description="Data rate as a float string")
    start_time: Optional[HighTime] = Field(None, description="Start time of the channel data")
    end_time: Optional[HighTime] = Field(None, description="End time of the channel data")
    device_name: Optional[str] = Field(None, description="Name of the device")
    pvfs_filename: Optional[str] = Field(None, description="PVFS filename")
    low_range: Optional[str] = Field(None, description="Low range of the channel")
    high_range: Optional[str] = Field(None, description="High range of the channel")

class Annotation(BaseModel):
    """Information about an annotation in an experiment."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    unique_id: int = Field(..., description="Unique identifier for the annotation")
    channel_id: int = Field(..., description="ID of the channel this annotation belongs to")
    start_time: Optional[HighTime] = Field(None, description="Start time of the annotation")
    end_time: Optional[HighTime] = Field(None, description="End time of the annotation")
    comment: Optional[str] = Field(None, description="Comment text for the annotation")
    type: Optional[str] = Field(None, description="Type of annotation")
    creator: Optional[str] = Field(None, description="Creator of the annotation")
    last_edited: Optional[str] = Field(None, description="Last edit timestamp")
    uuid: Optional[str] = Field(None, description="UUID of the annotation") 