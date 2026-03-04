"""
Inbound Email Ingestion API Endpoints.

Prefix: /api/inbound-email

- SNS webhook (unauthenticated — SNS signature verified)
- Admin endpoints for message review (API key + org header)
"""

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.database import init_connection_pool
from db.ingest_repository import IngestRepository
from middleware.api_key_auth import require_api_key
from models.email_ingest import (
    InboundAttachmentResponse,
    InboundMessageListResponse,
    InboundMessageResponse,
    ReviewAction,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/inbound-email",
    tags=["inbound-email"],
)

# Initialize repository
ingest_repo = None
try:
    init_connection_pool()
    ingest_repo = IngestRepository()
    logger.info("Inbound email API: Database initialized")
except Exception as e:
    logger.warning(f"Inbound email API: Database initialization failed: {e}")


class SuccessResponse(BaseModel):
    success: bool = True
    message: str


class PresignedUrlResponse(BaseModel):
    success: bool = True
    url: str
    filename: Optional[str] = None


def get_org_id(request: Request) -> int:
    org_id = request.headers.get("X-Organization-ID")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "message": "X-Organization-ID header required"},
        )
    try:
        return int(org_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "message": "X-Organization-ID must be an integer"},
        )


def validate_org_access(request: Request, auth: dict) -> int:
    """Ensure API key org matches X-Organization-ID header."""
    org_id = get_org_id(request)
    key_org_id = auth.get("organization_id")
    if key_org_id and key_org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "message": "API key organization mismatch"},
        )
    return org_id


def require_repo():
    if not ingest_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "message": "Database not available"},
        )


# =============================================================================
# SNS WEBHOOK (unauthenticated — signature verified internally)
# =============================================================================

@router.post(
    "/webhook",
    summary="SNS webhook for inbound email notifications",
)
async def sns_webhook(request: Request):
    """
    Receive SNS notifications for inbound emails.
    Unauthenticated — SNS signature is verified by the service.
    Returns 200 only after successful processing (SNS retries on non-2xx).
    """
    require_repo()

    try:
        # SNS sends JSON with text/plain content type
        body = await request.body()
        sns_body = json.loads(body)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Invalid SNS payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        from services.ingest.email_ingest_service import EmailIngestService

        service = EmailIngestService(ingest_repo)
        result = service.process_sns_notification(sns_body)

        return JSONResponse(content={"success": True, **result})

    except Exception as e:
        logger.error(f"SNS webhook processing failed: {e}", exc_info=True)
        # Return 500 so SNS retries
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"success": False, "message": str(e)},
        )


# =============================================================================
# ADMIN: LIST / GET MESSAGES
# =============================================================================

@router.get(
    "/messages",
    response_model=InboundMessageListResponse,
    summary="List inbound messages",
)
async def list_messages(
    request: Request,
    channel: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="inbound_message_status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_api_key),
) -> InboundMessageListResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    messages, total = ingest_repo.list_inbound_messages(
        org_id=org_id,
        channel=channel,
        inbound_message_status=status_filter,
        limit=limit,
        offset=offset,
    )

    return InboundMessageListResponse(
        messages=[InboundMessageResponse(**m) for m in messages],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/messages/{message_id}",
    response_model=InboundMessageResponse,
    summary="Get inbound message details with attachments",
)
async def get_message(
    request: Request,
    message_id: int,
    auth: dict = Depends(require_api_key),
) -> InboundMessageResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    msg = ingest_repo.get_inbound_message(message_id, org_id)
    if not msg:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Message not found"})

    attachments = [
        InboundAttachmentResponse(**a)
        for a in msg.get("attachments", [])
    ]
    return InboundMessageResponse(**{**msg, "attachments": attachments})


# =============================================================================
# ADMIN: APPROVE / REJECT / REPROCESS
# =============================================================================

@router.post(
    "/messages/{message_id}/approve",
    response_model=SuccessResponse,
    summary="Approve an inbound message",
)
async def approve_message(
    request: Request,
    message_id: int,
    body: ReviewAction = ReviewAction(),
    auth: dict = Depends(require_api_key),
) -> SuccessResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    updated = ingest_repo.update_inbound_message_status(
        message_id=message_id,
        org_id=org_id,
        inbound_message_status="approved",
        reason=body.reason or "admin approved",
    )
    if not updated:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Message not found"})

    return SuccessResponse(message="Message approved")


@router.post(
    "/messages/{message_id}/reject",
    response_model=SuccessResponse,
    summary="Reject an inbound message",
)
async def reject_message(
    request: Request,
    message_id: int,
    body: ReviewAction = ReviewAction(),
    auth: dict = Depends(require_api_key),
) -> SuccessResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    updated = ingest_repo.update_inbound_message_status(
        message_id=message_id,
        org_id=org_id,
        inbound_message_status="rejected",
        reason=body.reason or "admin rejected",
    )
    if not updated:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Message not found"})

    return SuccessResponse(message="Message rejected")


@router.post(
    "/messages/{message_id}/reprocess",
    response_model=SuccessResponse,
    summary="Re-trigger processing for a failed message",
)
async def reprocess_message(
    request: Request,
    message_id: int,
    auth: dict = Depends(require_api_key),
) -> SuccessResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    msg = ingest_repo.get_inbound_message(message_id, org_id)
    if not msg:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Message not found"})

    if msg["channel"] != "email":
        raise HTTPException(status_code=400, detail={"success": False, "message": "Reprocessing only supported for email channel"})

    if not msg.get("s3_raw_path"):
        raise HTTPException(status_code=400, detail={"success": False, "message": "No raw email path available"})

    # Reset status to received and delete old record so it can be reprocessed
    ingest_repo.update_inbound_message_status(
        message_id=message_id,
        org_id=org_id,
        inbound_message_status="received",
        reason="reprocessing triggered",
    )

    return SuccessResponse(message="Reprocessing initiated")


# =============================================================================
# ADMIN: ATTACHMENTS
# =============================================================================

@router.get(
    "/attachments/{attachment_id}",
    response_model=PresignedUrlResponse,
    summary="Get presigned download URL for an attachment",
)
async def get_attachment_download(
    request: Request,
    attachment_id: int,
    auth: dict = Depends(require_api_key),
) -> PresignedUrlResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    att = ingest_repo.get_attachment(attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Attachment not found"})

    # Verify the attachment belongs to a message in this org
    msg = ingest_repo.get_inbound_message(att["inbound_message_id"], org_id)
    if not msg:
        raise HTTPException(status_code=403, detail={"success": False, "message": "Access denied"})

    # Generate presigned URL
    s3_path = att["s3_path"]
    if s3_path.startswith("s3://"):
        parts = s3_path[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
    else:
        bucket = os.getenv("EMAIL_INGEST_S3_BUCKET", "frontiermind-email-ingest")
        key = s3_path

    try:
        import boto3
        s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": "Failed to generate download URL"})

    return PresignedUrlResponse(url=url, filename=att.get("filename"))


@router.post(
    "/attachments/{attachment_id}/process",
    response_model=SuccessResponse,
    summary="Trigger extraction for a specific attachment",
)
async def process_attachment(
    request: Request,
    attachment_id: int,
    auth: dict = Depends(require_api_key),
) -> SuccessResponse:
    require_repo()
    org_id = validate_org_access(request, auth)

    att = ingest_repo.get_attachment(attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Attachment not found"})

    msg = ingest_repo.get_inbound_message(att["inbound_message_id"], org_id)
    if not msg:
        raise HTTPException(status_code=403, detail={"success": False, "message": "Access denied"})

    # Mark as processing
    ingest_repo.update_attachment_status(attachment_id, "processing")

    return SuccessResponse(message=f"Processing triggered for attachment {attachment_id}")
