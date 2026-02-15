"""
Pydantic models for data ingestion.

Includes models for:
- Integration credentials and sites
- Ingestion requests and responses
- Meter reading canonical model
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =====================================================
# Enums
# =====================================================

class SourceType(str, Enum):
    """Supported data source types."""
    SOLAREDGE = "solaredge"
    ENPHASE = "enphase"
    SMA = "sma"
    GOODWE = "goodwe"
    SNOWFLAKE = "snowflake"
    MANUAL = "manual"


class AuthType(str, Enum):
    """Authentication types for integrations."""
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


class DataQuality(str, Enum):
    """Data quality flags."""
    MEASURED = "measured"
    ESTIMATED = "estimated"
    MISSING = "missing"


class IngestionStatus(str, Enum):
    """Ingestion processing status."""
    PROCESSING = "processing"
    SUCCESS = "success"
    QUARANTINED = "quarantined"
    SKIPPED = "skipped"
    ERROR = "error"


class SyncStatus(str, Enum):
    """Site synchronization status."""
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"
    PARTIAL = "partial"


# Maps data_source_id → SourceType enum for API responses
DS_ID_TO_SOURCE_TYPE = {
    5: SourceType.SNOWFLAKE,
    6: SourceType.MANUAL,
    7: SourceType.SOLAREDGE,
    8: SourceType.ENPHASE,
    9: SourceType.GOODWE,
    10: SourceType.SMA,
}

# Maps SourceType → data_source_id for API requests
SOURCE_TYPE_TO_DS_ID = {
    SourceType.SNOWFLAKE: 5,
    SourceType.MANUAL: 6,
    SourceType.SOLAREDGE: 7,
    SourceType.ENPHASE: 8,
    SourceType.GOODWE: 9,
    SourceType.SMA: 10,
}


# =====================================================
# Integration Credential Models
# =====================================================

class IntegrationCredentialCreate(BaseModel):
    """Model for creating an integration credential."""
    data_source_id: int = Field(..., description="FK to data_source table")
    auth_type: AuthType
    credentials: Dict[str, str] = Field(
        ..., description="Credential secrets: {'api_key': '...'} or {'access_token': '...', 'refresh_token': '...', 'scope': '...'}"
    )
    token_expires_at: Optional[datetime] = None
    label: Optional[str] = None


class IntegrationCredentialUpdate(BaseModel):
    """Model for updating an integration credential."""
    label: Optional[str] = None
    is_active: Optional[bool] = None
    credentials: Optional[Dict[str, str]] = Field(None, description="Replacement credential secrets")
    token_expires_at: Optional[datetime] = None


class IntegrationCredentialResponse(BaseModel):
    """Response model for integration credential (without sensitive data)."""
    id: int
    organization_id: int
    data_source_id: int
    auth_type: str
    label: Optional[str] = None
    is_active: bool
    last_used_at: Optional[datetime] = None
    last_error: Optional[str] = None
    error_count: int = 0
    token_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# Integration Site Models
# =====================================================

class IntegrationSiteBase(BaseModel):
    """Base model for integration sites."""
    external_site_id: str
    external_site_name: Optional[str] = None


class IntegrationSiteCreate(IntegrationSiteBase):
    """Model for creating an integration site."""
    integration_credential_id: int
    project_id: Optional[int] = None
    meter_id: Optional[int] = None
    data_source_id: int
    external_metadata: Optional[Dict[str, Any]] = None
    sync_interval_minutes: int = 60


class IntegrationSiteUpdate(BaseModel):
    """Model for updating an integration site."""
    project_id: Optional[int] = None
    meter_id: Optional[int] = None
    external_site_name: Optional[str] = None
    is_active: Optional[bool] = None
    sync_enabled: Optional[bool] = None
    sync_interval_minutes: Optional[int] = None


class IntegrationSiteResponse(IntegrationSiteBase):
    """Response model for integration site."""
    id: int
    organization_id: int
    integration_credential_id: int
    project_id: Optional[int] = None
    meter_id: Optional[int] = None
    data_source_id: int
    external_metadata: Optional[Dict[str, Any]] = None
    is_active: bool
    sync_enabled: bool
    sync_interval_minutes: int
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[SyncStatus] = None
    last_sync_error: Optional[str] = None
    last_sync_records_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# Meter Reading Models
# =====================================================

class MeterReadingCanonical(BaseModel):
    """Canonical meter reading model (matches database schema)."""
    organization_id: int
    project_id: Optional[int] = None
    meter_id: Optional[int] = None
    source_system: SourceType
    external_site_id: Optional[str] = None
    external_device_id: Optional[str] = None
    reading_timestamp: datetime
    reading_interval: str = "15min"
    energy_wh: Optional[Decimal] = None
    power_w: Optional[Decimal] = None
    irradiance_wm2: Optional[Decimal] = None
    temperature_c: Optional[Decimal] = None
    other_metrics: Optional[Dict[str, Any]] = None
    quality: DataQuality = DataQuality.MEASURED


class MeterReadingResponse(MeterReadingCanonical):
    """Response model for meter reading."""
    id: int
    ingested_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# Ingestion Request/Response Models
# =====================================================

class PresignedUrlRequest(BaseModel):
    """Request for S3 presigned URL."""
    filename: str
    content_type: str = "application/json"
    source_type: SourceType = SourceType.MANUAL


class PresignedUrlResponse(BaseModel):
    """Response with presigned URL for upload."""
    upload_url: str
    file_id: str
    s3_key: str
    expires_in: int = 3600


class IngestionStatusResponse(BaseModel):
    """Response for ingestion status check."""
    file_id: str
    status: IngestionStatus
    rows_loaded: Optional[int] = None
    error_message: Optional[str] = None
    validation_errors: Optional[List[Dict[str, Any]]] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class IngestionHistoryItem(BaseModel):
    """Single item in ingestion history."""
    id: int
    file_path: str
    file_name: Optional[str] = None
    data_source_id: int
    status: IngestionStatus
    rows_loaded: Optional[int] = None
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IngestionHistoryResponse(BaseModel):
    """Response for ingestion history."""
    items: List[IngestionHistoryItem]
    total: int
    page: int
    page_size: int


class IngestionStats(BaseModel):
    """Ingestion statistics."""
    date: str
    files_processed: int
    files_success: int
    files_quarantined: int
    rows_loaded: int
    avg_processing_ms: Optional[float] = None


class IngestionStatsResponse(BaseModel):
    """Response for ingestion statistics."""
    stats: List[IngestionStats]
    period_days: int


# =====================================================
# API-First Ingestion Models (meter-data & upload)
# =====================================================

class MeterDataReading(BaseModel):
    """Single meter reading in an API push request."""
    timestamp: str = Field(..., description="ISO 8601 or Unix timestamp (UTC)")
    site_id: Optional[str] = Field(None, description="External site identifier")
    device_id: Optional[str] = Field(None, description="External device identifier")
    energy_wh: Optional[float] = Field(None, description="Energy in Watt-hours")
    power_w: Optional[float] = Field(None, description="Power in Watts")
    irradiance_wm2: Optional[float] = Field(None, description="Solar irradiance W/m²")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")
    quality: Optional[str] = Field(None, description="measured, estimated, or missing")
    interval_seconds: Optional[int] = Field(None, description="Reading interval in seconds")


class MeterDataBatchRequest(BaseModel):
    """Request body for POST /api/ingest/meter-data."""
    readings: List[MeterDataReading] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Array of meter readings (max 5,000 per batch)",
    )
    source_type: SourceType = Field(
        default=SourceType.SNOWFLAKE,
        description="Data source type",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional metadata (project_id, meter_id, etc.)",
    )


class BillingReadsBatchRequest(BaseModel):
    """Request body for POST /api/ingest/billing-reads.

    Readings are untyped dicts because field names vary by client:
    - CBE sends: OPENING_READING, CLOSING_READING, CONTRACT_LINE_UNIQUE_ID, BILL_DATE, etc.
    - Future clients will send different field names.
    The client adapter maps these to canonical meter_aggregate columns.
    """
    readings: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Array of billing aggregate readings (max 5,000 per batch)",
    )
    source_type: SourceType = Field(
        default=SourceType.SNOWFLAKE,
        description="Data source type",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional metadata (project_id, etc.)",
    )


class GenerateAPIKeyRequest(BaseModel):
    """Request body for POST /api/ingest/credentials/generate-key."""
    data_source_id: int = Field(..., description="FK to data_source table")
    label: Optional[str] = Field(None, description="Human-readable label for the key")


class GenerateAPIKeyResponse(BaseModel):
    """Response for generate-key (includes plaintext key shown only once)."""
    credential_id: int
    organization_id: int
    data_source_id: int
    api_key: str = Field(..., description="Plaintext API key (shown only once)")
    label: Optional[str] = None
    created_at: datetime


class IngestionResultResponse(BaseModel):
    """Synchronous response from meter-data and upload endpoints."""
    ingestion_id: int = Field(..., description="Ingestion log entry ID")
    status: IngestionStatus = Field(..., description="Processing result")
    rows_accepted: int = Field(0, description="Rows successfully loaded")
    rows_rejected: int = Field(0, description="Rows that failed validation or transformation")
    errors: Optional[List[Dict[str, Any]]] = Field(None, description="Validation errors (first 10)")
    processing_time_ms: Optional[int] = Field(None, description="Total processing time in ms")
    data_start: Optional[datetime] = Field(None, description="Earliest reading timestamp")
    data_end: Optional[datetime] = Field(None, description="Latest reading timestamp")
    message: Optional[str] = Field(None, description="Human-readable status message")
