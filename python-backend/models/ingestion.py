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


# =====================================================
# Integration Credential Models
# =====================================================

class IntegrationCredentialBase(BaseModel):
    """Base model for integration credentials."""
    source_type: SourceType
    auth_type: AuthType
    label: Optional[str] = None


class IntegrationCredentialCreate(IntegrationCredentialBase):
    """Model for creating an integration credential."""
    # For API key auth
    api_key: Optional[str] = Field(None, description="API key for API key authentication")

    # For OAuth2 auth
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None


class IntegrationCredentialUpdate(BaseModel):
    """Model for updating an integration credential."""
    label: Optional[str] = None
    is_active: Optional[bool] = None

    # For API key update
    api_key: Optional[str] = None

    # For OAuth2 token update
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None


class IntegrationCredentialResponse(IntegrationCredentialBase):
    """Response model for integration credential (without sensitive data)."""
    id: int
    organization_id: int
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
    credential_id: int
    project_id: Optional[int] = None
    meter_id: Optional[int] = None
    source_type: SourceType
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
    credential_id: int
    project_id: Optional[int] = None
    meter_id: Optional[int] = None
    source_type: SourceType
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
    reading_interval_seconds: int = 900
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
    source_type: SourceType
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
