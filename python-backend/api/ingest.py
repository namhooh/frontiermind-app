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
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form, status
from pydantic import BaseModel, Field

from middleware.rate_limiter import limiter, limit_default
from middleware.api_key_auth import require_api_key

from db.database import init_connection_pool
from db.integration_repository import IntegrationRepository
from models.ingestion import (
    BillingReadsBatchRequest,
    GenerateAPIKeyRequest,
    GenerateAPIKeyResponse,
    IngestionHistoryItem,
    IngestionHistoryResponse,
    IngestionResultResponse,
    IngestionStats,
    IngestionStatsResponse,
    IngestionStatusResponse,
    IntegrationCredentialCreate,
    IntegrationCredentialResponse,
    IntegrationCredentialUpdate,
    IntegrationSiteCreate,
    IntegrationSiteResponse,
    IntegrationSiteUpdate,
    MeterDataBatchRequest,
    PresignedUrlRequest,
    PresignedUrlResponse,
    SOURCE_TYPE_TO_DS_ID,
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

# Lazy repository singleton
_repository = None


def get_repository() -> IntegrationRepository:
    """Get or create the IntegrationRepository singleton."""
    global _repository
    if _repository is None:
        init_connection_pool()
        _repository = IntegrationRepository()
        logger.info("Integration repository initialized for ingest API")
    return _repository


# Lazy-loaded IngestService (import only when data-ingestion modules are available)
_ingest_service = None


def get_ingest_service():
    """Get or create the IngestService singleton."""
    global _ingest_service
    if _ingest_service is None:
        from data_ingestion.processing.ingest_service import IngestService
        _ingest_service = IngestService(repository=get_repository())
    return _ingest_service


def _authorize_source_for_token(auth: dict, requested_source_type: SourceType) -> None:
    """Ensure API key is only used for its configured data source."""
    token_ds_id = auth.get("data_source_id")
    if token_ds_id is None:
        return

    requested_ds_id = SOURCE_TYPE_TO_DS_ID.get(requested_source_type)
    if requested_ds_id is None or requested_ds_id != token_ds_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"API key is scoped to data_source_id={token_ds_id}, "
                f"but request used source_type='{requested_source_type.value}'"
            ),
        )


# Max upload file size (50 MB)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(50 * 1024 * 1024)))

# S3 configuration
S3_BUCKET = os.getenv("METER_DATA_BUCKET", "frontiermind-meter-data")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Security: Presigned URL expiration times (in seconds)
# Per Security Assessment Section 3.2: Use short expiration times
PRESIGNED_URL_EXPIRY_UPLOAD = int(os.getenv("PRESIGNED_URL_EXPIRY_UPLOAD", "900"))  # 15 minutes
PRESIGNED_URL_EXPIRY_DOWNLOAD = int(os.getenv("PRESIGNED_URL_EXPIRY_DOWNLOAD", "300"))  # 5 minutes


def get_s3_client():
    """
    Get S3 client with configured credentials.

    On AWS ECS Fargate with a task role, uses IAM role credentials automatically.
    For local development or environments without IAM roles, uses explicit credentials.
    """
    # Check if running on ECS (task role provides credentials via container metadata)
    if os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        # Running on ECS Fargate - use IAM task role (boto3 handles this automatically)
        logger.info("Using IAM task role for S3 credentials")
        return boto3.client("s3", region_name=AWS_REGION)

    # Check if running with AWS credentials in environment (EC2, Lambda, etc.)
    # boto3 will automatically use AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY if set
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        logger.info("Using explicit AWS credentials for S3")
        return boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

    # Fallback: let boto3 use its default credential chain
    # (instance metadata, config files, etc.)
    logger.info("Using boto3 default credential chain for S3")
    return boto3.client("s3", region_name=AWS_REGION)


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
@limiter.limit("30/minute")  # Rate limit presigned URL generation
async def generate_presigned_url(
    http_request: Request,  # Required for rate limiting
    request: PresignedUrlRequestBody,
    organization_id: int = Query(..., description="Organization ID"),
) -> PresignedUrlResponse:
    """
    Generate a presigned URL for uploading meter data to S3.

    Security:
    - Presigned URLs expire after 15 minutes (configurable via PRESIGNED_URL_EXPIRY_UPLOAD)
    - Rate limited to 30 requests/minute per client
    - Organization ID required for audit trail

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

        # Generate presigned URL for PUT with short expiration
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
            ExpiresIn=PRESIGNED_URL_EXPIRY_UPLOAD,  # 15 minutes (security best practice)
        )

        logger.info(
            f"Generated presigned URL for org {organization_id}, file_id {file_id}, "
            f"expires_in={PRESIGNED_URL_EXPIRY_UPLOAD}s"
        )

        return PresignedUrlResponse(
            upload_url=presigned_url,
            file_id=file_id,
            s3_key=s3_key,
            expires_in=PRESIGNED_URL_EXPIRY_UPLOAD,
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
# API-First Ingestion Endpoints (meter-data & file upload)
# ============================================================================


@router.post(
    "/meter-data",
    response_model=IngestionResultResponse,
    summary="Push meter data via API",
    description="Ingest meter readings as a JSON batch. Used by Snowflake pipelines, partner APIs, and any HTTP client.",
)
@limiter.limit("30/minute")
async def ingest_meter_data(
    http_request: Request,
    request: MeterDataBatchRequest,
    auth: dict = Depends(require_api_key),
) -> IngestionResultResponse:
    """
    Ingest a batch of meter readings synchronously.

    Returns validation results immediately — no need to poll a status endpoint.
    Max 5,000 readings per batch.
    """
    repository = get_repository()
    organization_id = auth["organization_id"]
    _authorize_source_for_token(auth, request.source_type)

    try:
        svc = get_ingest_service()
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion pipeline not available",
        )

    # Convert Pydantic models to dicts for the pipeline
    records = [r.model_dump(exclude_none=True) for r in request.readings]

    result = svc.ingest_records(
        records=records,
        source_type=request.source_type.value,
        organization_id=organization_id,
        metadata=request.metadata,
        credential_id=auth.get("credential_id"),
    )

    return IngestionResultResponse(
        ingestion_id=result.ingestion_id,
        status=IngestionStatus(result.status),
        rows_accepted=result.rows_accepted,
        rows_rejected=result.rows_rejected,
        errors=result.errors if result.errors else None,
        processing_time_ms=result.processing_time_ms,
        data_start=result.data_start,
        data_end=result.data_end,
        message=result.message,
    )


@router.post(
    "/upload",
    response_model=IngestionResultResponse,
    summary="Upload meter data file",
    description="Upload a CSV, JSON, or Parquet file containing meter readings.",
)
@limiter.limit("10/minute")
async def upload_meter_data(
    request: Request,
    file: UploadFile = File(..., description="CSV, JSON, or Parquet file"),
    source_type: str = Query("manual", description="Data source type"),
    auth: dict = Depends(require_api_key),
) -> IngestionResultResponse:
    """
    Upload and ingest a meter data file synchronously.

    Supports CSV, JSON, and Parquet formats. Max file size: 50 MB.
    """
    organization_id = auth["organization_id"]

    try:
        svc = get_ingest_service()
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion pipeline not available",
        )

    # Read file content with size check
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: {len(content)} bytes (max {MAX_UPLOAD_SIZE})",
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    # Validate source_type
    try:
        src = SourceType(source_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_type: {source_type}. Must be one of: {[s.value for s in SourceType]}",
        )
    _authorize_source_for_token(auth, src)

    result = svc.ingest_file(
        content=content,
        filename=file.filename or "upload",
        source_type=src.value,
        organization_id=organization_id,
        credential_id=auth.get("credential_id"),
    )

    return IngestionResultResponse(
        ingestion_id=result.ingestion_id,
        status=IngestionStatus(result.status),
        rows_accepted=result.rows_accepted,
        rows_rejected=result.rows_rejected,
        errors=result.errors if result.errors else None,
        processing_time_ms=result.processing_time_ms,
        data_start=result.data_start,
        data_end=result.data_end,
        message=result.message,
    )


# ============================================================================
# Billing Aggregate Ingestion Endpoint
# ============================================================================


@router.post(
    "/billing-reads",
    response_model=IngestionResultResponse,
    summary="Push billing aggregate data via API",
    description="Ingest monthly billing aggregates (opening/closing/utilized readings). "
                "Client-specific field names are mapped by an adapter.",
)
@limiter.limit("30/minute")
async def ingest_billing_reads(
    http_request: Request,
    request: BillingReadsBatchRequest,
    auth: dict = Depends(require_api_key),
) -> IngestionResultResponse:
    """
    Ingest a batch of billing aggregate readings synchronously.

    Accepts client-native field names (e.g. CBE's SCREAMING_SNAKE_CASE).
    A client-specific adapter maps fields, validates, and transforms
    to canonical meter_aggregate columns.

    Target table: meter_aggregate (permanent, not partitioned).
    Max 5,000 readings per batch.
    """
    organization_id = auth["organization_id"]
    _authorize_source_for_token(auth, request.source_type)

    try:
        svc = get_ingest_service()
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion pipeline not available",
        )

    result = svc.ingest_billing_records(
        records=request.readings,
        source_type=request.source_type.value,
        organization_id=organization_id,
        metadata=request.metadata,
        credential_id=auth.get("credential_id"),
    )

    return IngestionResultResponse(
        ingestion_id=result.ingestion_id,
        status=IngestionStatus(result.status),
        rows_accepted=result.rows_accepted,
        rows_rejected=result.rows_rejected,
        errors=result.errors if result.errors else None,
        processing_time_ms=result.processing_time_ms,
        data_start=result.data_start,
        data_end=result.data_end,
        message=result.message,
    )


# ============================================================================
# Inverter Sync Endpoint
# ============================================================================


class SyncResponse(BaseModel):
    """Response from inverter sync trigger."""
    site_id: int
    status: str
    records_fetched: Optional[int] = None
    ingestion_id: Optional[int] = None
    error: Optional[str] = None


# Reverse lookup: data_source_id -> source_type string for fetcher dispatch
_DS_ID_TO_SOURCE_NAME = {v: k.value for k, v in SOURCE_TYPE_TO_DS_ID.items()}


@router.post(
    "/sync/{site_id}",
    response_model=SyncResponse,
    summary="Trigger inverter data sync",
    description="Fetch latest data from an inverter API and ingest it.",
)
@limiter.limit("10/minute")
async def sync_site(
    request: Request,
    site_id: int,
    lookback_hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    auth: dict = Depends(require_api_key),
) -> SyncResponse:
    """
    Trigger a data fetch from the inverter API for a specific site.

    Looks up the site's credential and source type, fetches data from
    the manufacturer API, and ingests it through the pipeline.
    """
    repository = get_repository()
    organization_id = auth["organization_id"]

    # Look up site
    site = repository.get_site(site_id=site_id, organization_id=organization_id)
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )

    # Look up credential
    credential = repository.get_credential(
        credential_id=site["integration_credential_id"],
        organization_id=organization_id,
        include_secrets=True,
    )
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found for this site",
        )

    source_type = _DS_ID_TO_SOURCE_NAME.get(site["data_source_id"])
    if not source_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown data_source_id: {site['data_source_id']}",
        )
    token_ds_id = auth.get("data_source_id")
    if token_ds_id is not None and token_ds_id != site["data_source_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"API key is scoped to data_source_id={token_ds_id}, "
                f"but site uses data_source_id={site['data_source_id']}"
            ),
        )

    # Import the appropriate fetcher
    try:
        fetcher_class = _get_fetcher_class(source_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    try:
        from datetime import timedelta
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=lookback_hours)

        # Get API key from credential
        api_key = credential.get("api_key") or credential.get("access_token")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No API key or access token found in credential",
            )

        # Instantiate fetcher and fetch data
        fetcher = fetcher_class(dry_run=False)
        data = fetcher.fetch_site_data(
            api_key=api_key,
            site_id=site["external_site_id"],
            start_time=start_time,
            end_time=end_time,
        )

        # Ingest through pipeline
        svc = get_ingest_service()
        readings = data.get("readings", [])
        result = svc.ingest_records(
            records=readings,
            source_type=source_type,
            organization_id=organization_id,
            site_id=site_id,
        )

        # Update sync status
        repository.update_site_sync_status(
            site_id=site_id,
            organization_id=organization_id,
            status="success" if result.status == "success" else "error",
            records_count=result.rows_accepted,
            error=result.message if result.status != "success" else None,
        )

        return SyncResponse(
            site_id=site_id,
            status=result.status,
            records_fetched=result.rows_accepted,
            ingestion_id=result.ingestion_id,
        )

    except Exception as e:
        logger.error(f"Sync failed for site {site_id}: {e}", exc_info=True)
        repository.update_site_sync_status(
            site_id=site_id,
            organization_id=organization_id,
            status="error",
            error=str(e),
        )
        return SyncResponse(
            site_id=site_id,
            status="error",
            error=str(e),
        )


def _get_fetcher_class(source_type: str):
    """Import and return the fetcher class for a source type."""
    fetcher_map = {
        "solaredge": "data_ingestion.fetchers.solaredge.fetcher.SolarEdgeFetcher",
        "enphase": "data_ingestion.fetchers.enphase.fetcher.EnphaseFetcher",
        "sma": "data_ingestion.fetchers.sma.fetcher.SMAFetcher",
        "goodwe": "data_ingestion.fetchers.goodwe.fetcher.GoodWeFetcher",
    }

    if source_type not in fetcher_map:
        raise ValueError(
            f"No fetcher available for source type '{source_type}'. "
            f"Supported: {list(fetcher_map.keys())}"
        )

    module_path, class_name = fetcher_map[source_type].rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


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
    auth: dict = Depends(require_api_key),
) -> IngestionStatusResponse:
    """
    Get the ingestion status for a specific file.

    The file_id is returned when generating a presigned URL.
    """
    repository = get_repository()
    organization_id = auth["organization_id"]

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
        status=IngestionStatus(matching_log["ingestion_status"]),
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
    auth: dict = Depends(require_api_key),
) -> IngestionStatusResponse:
    """
    Get the ingestion status for a file by its SHA256 hash.

    This endpoint is designed for Snowflake COPY INTO clients who push files
    directly to S3 without using the presigned URL flow. Since they don't
    receive a file_id, they can query status using the file's SHA256 hash.

    The file_hash should be the SHA256 hash of the uploaded file contents.
    """
    repository = get_repository()
    organization_id = auth["organization_id"]

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
        status=IngestionStatus(matching_log["ingestion_status"]),
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
    auth: dict = Depends(require_api_key),
    data_source_id: Optional[int] = Query(None, description="Filter by data source ID"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> IngestionHistoryResponse:
    """
    Get paginated ingestion history for an organization.
    """
    repository = get_repository()
    organization_id = auth["organization_id"]

    offset = (page - 1) * page_size

    logs, total = repository.list_ingestion_logs(
        organization_id=organization_id,
        data_source_id=data_source_id,
        status=status_filter,
        limit=page_size,
        offset=offset,
    )

    items = [
        IngestionHistoryItem(
            id=log["id"],
            file_path=log["file_path"],
            file_name=log.get("file_name"),
            data_source_id=log["data_source_id"],
            status=IngestionStatus(log["ingestion_status"]),
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
    auth: dict = Depends(require_api_key),
    days: int = Query(30, ge=1, le=90, description="Number of days to look back"),
) -> IngestionStatsResponse:
    """
    Get daily ingestion statistics for an organization.
    """
    repository = get_repository()
    organization_id = auth["organization_id"]

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

    Pass credentials as a JSON dict:
    - For API key auth: {"api_key": "..."}
    - For OAuth2: {"access_token": "...", "refresh_token": "...", "scope": "..."}
    """
    repository = get_repository()

    try:
        result = repository.create_credential(
            organization_id=organization_id,
            data_source_id=credential.data_source_id,
            auth_type=credential.auth_type.value,
            credentials=credential.credentials,
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


@router.post(
    "/credentials/generate-key",
    response_model=GenerateAPIKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an API key",
    description="Generate a new API key for client data ingestion. The plaintext key is returned only once.",
)
async def generate_api_key(
    body: GenerateAPIKeyRequest,
    organization_id: int = Query(..., description="Organization ID"),
) -> GenerateAPIKeyResponse:
    """
    Generate a new API key for a client.

    Creates a credential with a server-generated key prefixed with `fm_`.
    The plaintext key is returned in the response and cannot be retrieved again.
    """
    repository = get_repository()

    plaintext_key = f"fm_{secrets.token_urlsafe(32)}"

    try:
        result = repository.create_credential(
            organization_id=organization_id,
            data_source_id=body.data_source_id,
            auth_type="api_key",
            credentials={"api_key": plaintext_key},
            label=body.label,
        )

        return GenerateAPIKeyResponse(
            credential_id=result["id"],
            organization_id=result["organization_id"],
            data_source_id=result["data_source_id"],
            api_key=plaintext_key,
            label=result.get("label"),
            created_at=result["created_at"],
        )

    except Exception as e:
        logger.error(f"Error generating API key: {e}")
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
    data_source_id: Optional[int] = Query(None, description="Filter by data source ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> List[IntegrationCredentialResponse]:
    """
    List integration credentials for an organization.
    """
    repository = get_repository()

    credentials = repository.list_credentials(
        organization_id=organization_id,
        data_source_id=data_source_id,
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
    repository = get_repository()

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
    repository = get_repository()

    result = repository.update_credential(
        credential_id=credential_id,
        organization_id=organization_id,
        label=update.label,
        is_active=update.is_active,
        credentials=update.credentials,
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
    repository = get_repository()

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
    repository = get_repository()

    try:
        result = repository.create_site(
            organization_id=organization_id,
            integration_credential_id=site.integration_credential_id,
            data_source_id=site.data_source_id,
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
    integration_credential_id: Optional[int] = Query(None, description="Filter by credential"),
    data_source_id: Optional[int] = Query(None, description="Filter by data source"),
    project_id: Optional[int] = Query(None, description="Filter by project"),
    sync_enabled: Optional[bool] = Query(None, description="Filter by sync enabled"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> List[IntegrationSiteResponse]:
    """
    List integration sites for an organization.
    """
    repository = get_repository()

    sites = repository.list_sites(
        organization_id=organization_id,
        integration_credential_id=integration_credential_id,
        data_source_id=data_source_id,
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
    repository = get_repository()

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
    repository = get_repository()

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
    repository = get_repository()

    deleted = repository.delete_site(
        site_id=site_id,
        organization_id=organization_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found",
        )
