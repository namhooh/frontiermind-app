"""
Pydantic models for operational events.

Defines data structures for event detection, storage, and retrieval.
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List


class DetectedEvent(BaseModel):
    """
    Represents an operational event detected from meter data.

    This model is used by EventDetector to return detected anomalies
    before they are stored in the database.
    """
    event_type: str  # 'equipment_failure', 'performance_degradation', 'grid_outage'
    event_type_id: int  # Foreign key to event_type table
    severity: int  # 1-5 scale (1=minor, 5=critical) - stored in raw_data JSONB
    time_start: datetime
    time_end: Optional[datetime] = None
    description: str
    raw_data: Dict[str, Any]  # JSONB metadata with event-specific details (includes severity)
    metric_outcome: Optional[Dict[str, Any]] = {}  # JSONB with calculated metrics
    affected_meters: Optional[List[int]] = []  # List of meter IDs affected


class EventType(BaseModel):
    """
    Event type reference data from event_type table.

    Represents the types of operational events that can be detected.
    """
    id: int
    code: str  # 'equipment_failure', 'performance_degradation', etc.
    name: str  # Human-readable name


class EventCreate(BaseModel):
    """
    Request model for creating an event via API.

    Used by API endpoints to create events manually or from external systems.
    """
    project_id: int
    event_type_id: int
    time_start: datetime
    time_end: Optional[datetime] = None
    severity: int  # Stored in raw_data JSONB
    raw_data: Dict[str, Any]  # Must include severity
    metric_outcome: Optional[Dict[str, Any]] = {}
    description: str
    status: Optional[str] = 'open'  # ENUM: 'open', 'closed'


class Event(BaseModel):
    """
    Complete event model matching database schema.

    Represents a stored operational event with all database fields.
    """
    id: int
    project_id: int
    event_type_id: int
    event_type_code: Optional[str] = None  # Joined from event_type table
    event_type_name: Optional[str] = None  # Joined from event_type table
    time_start: datetime
    time_end: Optional[datetime] = None
    time_acknowledged: Optional[datetime] = None
    time_fixed: Optional[datetime] = None
    raw_data: Dict[str, Any]  # Includes severity
    metric_outcome: Optional[Dict[str, Any]] = {}
    description: str
    status: str  # ENUM: 'open', 'closed'
    created_at: datetime
    updated_at: Optional[datetime] = None


class DetectEventsRequest(BaseModel):
    """
    API request model for event detection endpoint.

    Used to trigger event detection for a specific project and time period.
    """
    project_id: int
    period_start: datetime
    period_end: datetime


class DetectEventsResponse(BaseModel):
    """
    API response model for event detection endpoint.

    Returns detected events with summary statistics.
    """
    events_detected: int
    events: List[Event]
    processing_notes: Optional[List[str]] = []
