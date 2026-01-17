"""
Data Ingestion API Endpoints

This module provides REST API endpoints for meter data ingestion:
- Presigned URL generation for S3 uploads
- Ingestion status tracking
- Integration credential management
- Integration site management
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from db.database import init_connection_pool
from db.integration_repository import IntegrationRepository
from models.ingestion import (
    IngestionHistoryItem,
    IngestionHistoryResponse,
    IngestionStats,
    IngestionStatsResponse,
    IngestionStatusResponse,
    IntegrationCredentialCreate,
    IntegrationCredentialResponse,
    IntegrationCredentialUpdate,
    IntegrationSiteCreate,
    IntegrationSiteResponse,
    IntegrationSiteUpdate,
    PresignedUrlRequest,
    PresignedUrlResponse,
    SourceType,
    IngestionStatus,
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(
    prefix="/api/ingest",
    tags=["ingestion"],
    responses={
        404: {"description": "Not found"},
        500: {"description": "Internal server error"},
    },
)

# Initialize database connection and repository
try:
    init_connection_pool()
    repository = IntegrationRepository()
    logger.info("Integration repository initialized for ingest API")
except Exception as e:
    logger.warning(f"Database not available for ingest API: {e}")
    repository = None

# S3 configuration
S3_BUCKET = os.getenv("METER_DATA_BUCKET", "frontiermind-meter-data")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def get_s3_client():
    """Get S3 client with configured credentials."""
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


# ============================================================================
# Request/Response Models
# ============================================================================


class PresignedUrlRequestBody(BaseModel):
    """Request body for presigned URL generation."""

    filename: str = Field(..., description="Original filename")
    content_type: str = Field(
        default="application/json", description="MIME type of the file"
    )
    source_type: SourceType = Field(
        default=SourceType.MANUAL, description="Data source type"
    )


class FileIdResponse(BaseModel):
    """Response with file ID for tracking."""

    file_id: str
    message: str


# ============================================================================
# Presigned URL Endpoints
# ============================================================================


@router.post(
    "/presigned-url",
    response_model=PresignedUrlResponse,
    summary="Generate S3 presigned URL for upload",
    description="Generate a presigned URL for direct upload to S3. The file will be processed by the Validator Lambda.",
)
async def generate_presigned_url(
    request: PresignedUrlRequestBody,
    organization_id: int = Query(..., description="Organization ID"),
) -> PresignedUrlResponse:
    """
    Generate a presigned URL for uploading meter data to S3.

    The uploaded file will land in s3://bucket/raw/{source}/{org_id}/{date}/{file_id}_{filename}
    and trigger the Validator Lambda for processing.
    """
    try:
        s3_client = get_s3_client()

        # Generate unique file ID
        file_id = str(uuid.uuid4())
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Build S3 key
        s3_key = f"raw/{request.source_type.value}/{organization_id}/{date_str}/{file_id}_{request.filename}"

        # Generate presigned URL for PUT
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3_key,
                "ContentType": request.content_type,
                "Metadata": {
                    "organization-id": str(organization_id),
                    "source-type": request.source_type.value,
                    "original-filename": request.filename,
                },
            },
            ExpiresIn=3600,  # 1 hour
        )

        logger.info(
            f"Generated presigned URL for org {organization_id}, file_id {file_id}"
        )

        return PresignedUrlResponse(
            upload_url=presigned_url,
            file_id=file_id,
            s3_key=s3_key,
            expires_in=3600,
        )

    except ClientError as e:
        logger.error(f"S3 error generating presigned URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate upload URL",
        )
    except Exception as e:
        logger.error(f"Error generating presigned URL: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# Ingestion Status Endpoints
# ============================================================================


@router.get(
    "/status/{file_id}",
    response_model=IngestionStatusResponse,
    summary="Check ingestion status",
    description="Check the processing status of an uploaded file by its file ID.",
)
async def get_ingestion_status(
    file_id: str,
    organization_id: int = Query(..., description="Organization ID"),
) -> IngestionStatusResponse:
    """
    Get the ingestion status for a specific file.

    The file_id is returned when generating a presigned URL.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    # Search for log entry by file path pattern
    logs, _ = repository.list_ingestion_logs(
        organization_id=organization_id,
        limit=100,
    )

    # Find log matching this file_id
    matching_log = None
    for log in logs:
        if file_id in log.get("file_path", ""):
            matching_log = log
            break

    if not matching_log:
        # File may not have been processed yet
        return IngestionStatusResponse(
            file_id=file_id,
            status=IngestionStatus.PROCESSING,
            rows_loaded=None,
            error_message=None,
            validation_errors=None,
            processing_time_ms=None,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )

    return IngestionStatusResponse(
        file_id=file_id,
        status=IngestionStatus(matching_log["status"]),
        rows_loaded=matching_log.get("rows_loaded"),
        error_message=matching_log.get("error_message"),
        validation_errors=matching_log.get("validation_errors"),
        processing_time_ms=matching_log.get("processing_time_ms"),
        created_at=matching_log["created_at"],
        completed_at=matching_log.get("processing_completed_at"),
    )


@router.get(
    "/status/by-hash/{file_hash}",
    response_model=IngestionStatusResponse,
    summary="Check ingestion status by file hash",
    description="Check the processing status of an uploaded file by its SHA256 hash. Used by Snowflake COPY INTO clients.",
)
async def get_ingestion_status_by_hash(
    file_hash: str,
    organization_id: int = Query(..., description="Organization ID"),
) -> IngestionStatusResponse:
    """
    Get the ingestion status for a file by its SHA256 hash.

    This endpoint is designed for Snowflake COPY INTO clients who push files
    directly to S3 without using the presigned URL flow. Since they don't
    receive a file_id, they can query status using the file's SHA256 hash.

    The file_hash should be the SHA256 hash of the uploaded file contents.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    # Look up log by hash
    matching_log = repository.get_ingestion_log_by_hash(
        file_hash=file_hash,
        organization_id=organization_id,
    )

    if not matching_log:
        # File may not have been processed yet, or hash doesn't exist
        return IngestionStatusResponse(
            file_id=file_hash,
            status=IngestionStatus.PROCESSING,
            rows_loaded=None,
            error_message=None,
            validation_errors=None,
            processing_time_ms=None,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )

    return IngestionStatusResponse(
        file_id=file_hash,
        status=IngestionStatus(matching_log["status"]),
        rows_loaded=matching_log.get("rows_loaded"),
        error_message=matching_log.get("error_message"),
        validation_errors=matching_log.get("validation_errors"),
        processing_time_ms=matching_log.get("processing_time_ms"),
        created_at=matching_log["created_at"],
        completed_at=matching_log.get("processing_completed_at"),
    )


@router.get(
    "/history",
    response_model=IngestionHistoryResponse,
    summary="Get ingestion history",
    description="List recent ingestion logs for the organization.",
)
async def get_ingestion_history(
    organization_id: int = Query(..., description="Organization ID"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> IngestionHistoryResponse:
    """
    Get paginated ingestion history for an organization.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    offset = (page - 1) * page_size

    logs, total = repository.list_ingestion_logs(
        organization_id=organization_id,
        source_type=source_type,
        status=status_filter,
        limit=page_size,
        offset=offset,
    )

    items = [
        IngestionHistoryItem(
            id=log["id"],
            file_path=log["file_path"],
            file_name=log.get("file_name"),
            source_type=SourceType(log["source_type"]),
            status=IngestionStatus(log["status"]),
            rows_loaded=log.get("rows_loaded"),
            error_message=log.get("error_message"),
            processing_time_ms=log.get("processing_time_ms"),
            created_at=log["created_at"],
        )
        for log in logs
    ]

    return IngestionHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/stats",
    response_model=IngestionStatsResponse,
    summary="Get ingestion statistics",
    description="Get daily ingestion statistics for the organization.",
)
async def get_ingestion_stats(
    organization_id: int = Query(..., description="Organization ID"),
    days: int = Query(30, ge=1, le=90, description="Number of days to look back"),
) -> IngestionStatsResponse:
    """
    Get daily ingestion statistics for an organization.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    stats_data = repository.get_ingestion_stats(
        organization_id=organization_id,
        days=days,
    )

    stats = [
        IngestionStats(
            date=str(s["date"]),
            files_processed=s["files_processed"],
            files_success=s["files_success"],
            files_quarantined=s["files_quarantined"],
            rows_loaded=s["rows_loaded"],
            avg_processing_ms=float(s["avg_processing_ms"]) if s.get("avg_processing_ms") else None,
        )
        for s in stats_data
    ]

    return IngestionStatsResponse(
        stats=stats,
        period_days=days,
    )


# ============================================================================
# Integration Credential Endpoints
# ============================================================================


@router.post(
    "/credentials",
    response_model=IntegrationCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create integration credential",
    description="Store API key or OAuth tokens for an inverter integration.",
)
async def create_credential(
    credential: IntegrationCredentialCreate,
    organization_id: int = Query(..., description="Organization ID"),
) -> IntegrationCredentialResponse:
    """
    Create a new integration credential.

    For API key auth, provide api_key.
    For OAuth2 auth, provide access_token, refresh_token, and token_expires_at.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    try:
        result = repository.create_credential(
            organization_id=organization_id,
            source_type=credential.source_type.value,
            auth_type=credential.auth_type.value,
            api_key=credential.api_key,
            access_token=credential.access_token,
            refresh_token=credential.refresh_token,
            token_expires_at=credential.token_expires_at,
            label=credential.label,
        )

        return IntegrationCredentialResponse(**result)

    except Exception as e:
        logger.error(f"Error creating credential: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/credentials",
    response_model=List[IntegrationCredentialResponse],
    summary="List integration credentials",
    description="List all integration credentials for the organization.",
)
async def list_credentials(
    organization_id: int = Query(..., description="Organization ID"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> List[IntegrationCredentialResponse]:
    """
    List integration credentials for an organization.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    credentials = repository.list_credentials(
        organization_id=organization_id,
        source_type=source_type,
        is_active=is_active,
    )

    return [IntegrationCredentialResponse(**c) for c in credentials]


@router.get(
    "/credentials/{credential_id}",
    response_model=IntegrationCredentialResponse,
    summary="Get integration credential",
    description="Get a specific integration credential.",
)
async def get_credential(
    credential_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> IntegrationCredentialResponse:
    """
    Get a specific integration credential.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    credential = repository.get_credential(
        credential_id=credential_id,
        organization_id=organization_id,
        include_secrets=False,
    )

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    return IntegrationCredentialResponse(**credential)


@router.put(
    "/credentials/{credential_id}",
    response_model=IntegrationCredentialResponse,
    summary="Update integration credential",
    description="Update an integration credential.",
)
async def update_credential(
    credential_id: int,
    update: IntegrationCredentialUpdate,
    organization_id: int = Query(..., description="Organization ID"),
) -> IntegrationCredentialResponse:
    """
    Update an integration credential.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    result = repository.update_credential(
        credential_id=credential_id,
        organization_id=organization_id,
        label=update.label,
        is_active=update.is_active,
        api_key=update.api_key,
        access_token=update.access_token,
        refresh_token=update.refresh_token,
        token_expires_at=update.token_expires_at,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    return IntegrationCredentialResponse(**result)


@router.delete(
    "/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete integration credential",
    description="Delete an integration credential and all associated sites.",
)
async def delete_credential(
    credential_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> None:
    """
    Delete an integration credential.

    This will also delete all integration sites associated with this credential.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    deleted = repository.delete_credential(
        credential_id=credential_id,
        organization_id=organization_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )


# ============================================================================
# Integration Site Endpoints
# ============================================================================


@router.post(
    "/sites",
    response_model=IntegrationSiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create integration site",
    description="Map an external inverter site to an internal project.",
)
async def create_site(
    site: IntegrationSiteCreate,
    organization_id: int = Query(..., description="Organization ID"),
) -> IntegrationSiteResponse:
    """
    Create an integration site mapping.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    try:
        result = repository.create_site(
            organization_id=organization_id,
            credential_id=site.credential_id,
            source_type=site.source_type.value,
            external_site_id=site.external_site_id,
            external_site_name=site.external_site_name,
            project_id=site.project_id,
            meter_id=site.meter_id,
            external_metadata=site.external_metadata,
            sync_interval_minutes=site.sync_interval_minutes,
        )

        return IntegrationSiteResponse(**result)

    except Exception as e:
        logger.error(f"Error creating site: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/sites",
    response_model=List[IntegrationSiteResponse],
    summary="List integration sites",
    description="List all integration sites for the organization.",
)
async def list_sites(
    organization_id: int = Query(..., description="Organization ID"),
    credential_id: Optional[int] = Query(None, description="Filter by credential"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    project_id: Optional[int] = Query(None, description="Filter by project"),
    sync_enabled: Optional[bool] = Query(None, description="Filter by sync enabled"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> List[IntegrationSiteResponse]:
    """
    List integration sites for an organization.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    sites = repository.list_sites(
        organization_id=organization_id,
        credential_id=credential_id,
        source_type=source_type,
        project_id=project_id,
        sync_enabled=sync_enabled,
        is_active=is_active,
    )

    return [IntegrationSiteResponse(**s) for s in sites]


@router.get(
    "/sites/{site_id}",
    response_model=IntegrationSiteResponse,
    summary="Get integration site",
    description="Get a specific integration site.",
)
async def get_site(
    site_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> IntegrationSiteResponse:
    """
    Get a specific integration site.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    site = repository.get_site(
        site_id=site_id,
        organization_id=organization_id,
    )

    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )

    return IntegrationSiteResponse(**site)


@router.put(
    "/sites/{site_id}",
    response_model=IntegrationSiteResponse,
    summary="Update integration site",
    description="Update an integration site.",
)
async def update_site(
    site_id: int,
    update: IntegrationSiteUpdate,
    organization_id: int = Query(..., description="Organization ID"),
) -> IntegrationSiteResponse:
    """
    Update an integration site.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    result = repository.update_site(
        site_id=site_id,
        organization_id=organization_id,
        project_id=update.project_id,
        meter_id=update.meter_id,
        external_site_name=update.external_site_name,
        is_active=update.is_active,
        sync_enabled=update.sync_enabled,
        sync_interval_minutes=update.sync_interval_minutes,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )

    return IntegrationSiteResponse(**result)


@router.delete(
    "/sites/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete integration site",
    description="Delete an integration site.",
)
async def delete_site(
    site_id: int,
    organization_id: int = Query(..., description="Organization ID"),
) -> None:
    """
    Delete an integration site.
    """
    if not repository:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )

    deleted = repository.delete_site(
        site_id=site_id,
        organization_id=organization_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )
