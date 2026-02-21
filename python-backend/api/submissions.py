"""
Public Submission API Endpoints

Unauthenticated endpoints for counterparties to submit data via token-based links.
Rate limited: 10 requests/minute per IP.
"""

import hashlib
import logging
import os
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, status, Request, UploadFile, File, Form
from pydantic import BaseModel

from models.notifications import SubmitResponseRequest, SubmissionFormConfig
from db.notification_repository import NotificationRepository
from db.database import init_connection_pool
from services.email.token_service import TokenService
from middleware.rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/submit",
    tags=["submissions"],
)

# Initialize repository
notification_repo = None
token_service = None
try:
    init_connection_pool()
    notification_repo = NotificationRepository()
    token_service = TokenService(notification_repo)
    logger.info("Submissions API: Database initialized")
except Exception as e:
    logger.warning(f"Submissions API: Database initialization failed: {e}")

# File upload constraints
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
}
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class SubmissionSuccessResponse(BaseModel):
    success: bool = True
    message: str
    submission_id: int


class FileUploadSuccessResponse(BaseModel):
    success: bool = True
    message: str
    observation_id: int
    grp_per_kwh: float
    total_variable_charges: float
    total_kwh_invoiced: float
    line_items_count: int
    extraction_confidence: str


def require_services():
    if not notification_repo or not token_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "message": "Service not available"},
        )


@router.get(
    "/{token}",
    response_model=SubmissionFormConfig,
    summary="Validate token and get form configuration",
)
@limiter.limit("10/minute")
async def get_submission_form(request: Request, token: str) -> SubmissionFormConfig:
    """
    Public endpoint: validate a submission token and return the form config.
    No authentication required.
    """
    require_services()

    record = token_service.validate_token(token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Invalid or expired link"},
        )

    submission_type = record.get("submission_type", "form_response")

    # Build fields based on submission type
    if submission_type == "grp_upload":
        fields = [
            {"name": "billing_month", "label": "Billing Month", "type": "month", "required": True},
            {"name": "utility_invoice", "label": "Utility Invoice", "type": "file", "required": True},
        ]
    else:
        fields = record.get("submission_fields", [])

    # Build invoice summary for display
    invoice_summary = None
    if record.get("invoice_number"):
        invoice_summary = {
            "invoice_number": record.get("invoice_number"),
            "total_amount": str(record["total_amount"]) if record.get("total_amount") else None,
            "due_date": record["due_date"].isoformat() if record.get("due_date") else None,
        }

    return SubmissionFormConfig(
        fields=fields,
        invoice_summary=invoice_summary,
        counterparty_name=record.get("counterparty_name"),
        organization_name=record.get("organization_name"),
        project_name=record.get("project_name"),
        submission_type=submission_type,
        expires_at=record["expires_at"],
    )


@router.post(
    "/{token}",
    response_model=SubmissionSuccessResponse,
    summary="Submit data via token",
)
@limiter.limit("10/minute")
async def submit_response(
    request: Request,
    token: str,
    body: SubmitResponseRequest,
) -> SubmissionSuccessResponse:
    """
    Public endpoint: submit data against a valid token.
    No authentication required. Rate limited.
    """
    require_services()

    record = token_service.validate_token(token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Invalid or expired link"},
        )

    # Get client IP
    ip_address = request.client.host if request.client else None

    try:
        response_id = token_service.use_token(
            token_record=record,
            response_data=body.response_data,
            submitted_by_email=body.submitted_by_email,
            ip_address=ip_address,
        )

        return SubmissionSuccessResponse(
            success=True,
            message="Submission received successfully",
            submission_id=response_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"success": False, "message": str(e)},
        )
    except Exception as e:
        logger.error(f"Submission failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "message": "Failed to process submission"},
        )


@router.post(
    "/{token}/upload",
    response_model=FileUploadSuccessResponse,
    summary="Submit file via token (GRP upload)",
)
@limiter.limit("5/minute")
async def submit_file(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    billing_month: str = Form(...),
    submitted_by_email: Optional[str] = Form(None),
) -> FileUploadSuccessResponse:
    """
    Public endpoint: upload a utility invoice file for GRP extraction.
    No authentication required. Rate limited to 5/minute.
    """
    require_services()

    # 1. Validate token
    record = token_service.validate_token(token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Invalid or expired link"},
        )

    # 2. Validate submission type
    if record.get("submission_type") != "grp_upload":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "This token does not accept file uploads"},
        )

    project_id = record.get("project_id")
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Token missing project context"},
        )

    # 3. Validate billing_month format
    try:
        from datetime import date
        # Accept YYYY-MM or YYYY-MM-DD
        if len(billing_month) == 7:
            billing_month_date = date.fromisoformat(billing_month + "-01")
        else:
            billing_month_date = date.fromisoformat(billing_month)
            billing_month_date = billing_month_date.replace(day=1)
        billing_month_str = billing_month_date.isoformat()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "Invalid billing_month format. Use YYYY-MM or YYYY-MM-DD."},
        )

    # 4. Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "No file provided"},
        )

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": f"File type not allowed. Accepted: PDF, PNG, JPG."},
        )

    # Validate content type
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": f"Content type '{file.content_type}' not allowed. Accepted: PDF, PNG, JPG."},
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "File too large. Maximum size is 20 MB."},
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "File is empty"},
        )

    # 5. Hash file for dedup
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # 6. Check for duplicate document (same hash already stored for this project)
    try:
        _check_duplicate_document(project_id, file_hash)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"success": False, "message": str(e)},
        )

    # 7. Upload to S3 — use hash-based filename to prevent user-supplied path injection
    org_id = record["organization_id"]
    year = billing_month_date.year
    month = billing_month_date.month
    safe_filename = f"{file_hash[:16]}{ext}"
    s3_key = f"grp-uploads/{org_id}/{project_id}/{year}/{month:02d}/{safe_filename}"

    _upload_to_s3(file_bytes, s3_key, file.content_type)

    # 8. Determine operating year from token fields or calculate from COD
    token_fields = record.get("submission_fields") or []
    operating_year = None
    for field in token_fields:
        if isinstance(field, dict) and "operating_year" in field:
            operating_year = field["operating_year"]
            break

    if operating_year is None:
        operating_year, cod_date = _determine_operating_year(project_id, billing_month_date)
    else:
        cod_date = _get_cod_date(project_id)

    # 9. Validate billing_month >= COD date
    if cod_date and billing_month_date < cod_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "message": "Billing month cannot precede project COD date",
            },
        )

    # 10. Extract and store GRP (synchronous — client waits ~10-30s)
    try:
        from services.grp.extraction_service import GRPExtractionService

        extraction_service = GRPExtractionService()

        result = extraction_service.extract_and_store(
            file_bytes=file_bytes,
            filename=file.filename,
            project_id=project_id,
            org_id=org_id,
            billing_month=billing_month_str,
            operating_year=operating_year,
            s3_path=s3_key,
            file_hash=file_hash,
            submission_response_id=None,  # Linked after token consumption via UPDATE
        )

    except Exception as e:
        logger.error(f"GRP extraction failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "message": f"Extraction failed: {str(e)}",
            },
        )

    # 11. Consume token AFTER successful extraction — if extraction fails, client can retry
    ip_address = request.client.host if request.client else None

    try:
        response_id = token_service.use_token(
            token_record=record,
            response_data={
                "billing_month": billing_month_str,
                "original_filename": file.filename,
                "file_hash": file_hash,
                "s3_path": s3_key,
                "observation_id": result["observation_id"],
                "grp_per_kwh": result["grp_per_kwh"],
            },
            submitted_by_email=submitted_by_email,
            ip_address=ip_address,
        )
    except ValueError as e:
        # Token exhausted between validation and consumption — extraction succeeded
        # but we can't record the submission. Log and return success anyway.
        logger.warning(f"Token use failed after successful extraction: {e}")
        response_id = None

    # 12. Link submission_response to the reference_price observation
    if response_id and result.get("observation_id"):
        _link_submission_to_observation(result["observation_id"], response_id)

    return FileUploadSuccessResponse(
        success=True,
        message="Invoice processed successfully",
        observation_id=result["observation_id"],
        grp_per_kwh=result["grp_per_kwh"],
        total_variable_charges=result["total_variable_charges"],
        total_kwh_invoiced=result["total_kwh_invoiced"],
        line_items_count=result["line_items_count"],
        extraction_confidence=result["extraction_confidence"],
    )


def _upload_to_s3(file_bytes: bytes, s3_key: str, content_type: Optional[str] = None) -> None:
    """Upload file bytes to S3. Raises if boto3 is unavailable."""
    try:
        import boto3
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "message": "S3 storage is not available"},
        )

    bucket = os.getenv("GRP_S3_BUCKET", "frontiermind-grp-uploads")
    region = os.getenv("AWS_REGION", "us-east-1")

    s3_client = boto3.client("s3", region_name=region)
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=file_bytes,
        **extra_args,
    )
    logger.info(f"Uploaded to S3: s3://{bucket}/{s3_key}")


def _check_duplicate_document(project_id: int, file_hash: str) -> None:
    """Check if a document with the same hash already exists for this project."""
    from db.database import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, period_start FROM reference_price
                WHERE project_id = %s AND source_document_hash = %s
                """,
                (project_id, file_hash),
            )
            row = cur.fetchone()
            if row:
                raise ValueError(
                    f"This invoice has already been uploaded (observation {row['id']}, "
                    f"period {row['period_start']}). Please upload a different invoice."
                )


def _determine_operating_year(project_id: int, billing_month: "date") -> tuple:
    """Determine the contract operating year from the project's COD date.

    Returns:
        Tuple of (operating_year, cod_date). cod_date may be None.
    """
    from db.database import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cod_date FROM project WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if not row or not row["cod_date"]:
                return 1, None  # Default to year 1 if COD not set

            cod_date = row["cod_date"]
            # Operating year = how many full years since COD + 1
            year_diff = billing_month.year - cod_date.year
            if billing_month.month < cod_date.month:
                year_diff -= 1
            return max(1, year_diff + 1), cod_date


def _get_cod_date(project_id: int):
    """Get the COD date for a project."""
    from db.database import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cod_date FROM project WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            return row["cod_date"] if row else None


def _link_submission_to_observation(observation_id: int, response_id: int) -> None:
    """Link the submission_response back to the reference_price observation."""
    from db.database import get_db_connection

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reference_price SET submission_response_id = %s WHERE id = %s",
                    (response_id, observation_id),
                )
                conn.commit()
    except Exception as e:
        # Non-fatal: observation was stored successfully, just missing the FK link
        logger.warning(f"Failed to link submission {response_id} to observation {observation_id}: {e}")
