"""
Public Submission API Endpoints

Unauthenticated endpoints for counterparties to submit data via token-based links.
Rate limited: 10 requests/minute per IP.
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status, Request
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


class SubmissionSuccessResponse(BaseModel):
    success: bool = True
    message: str
    submission_id: int


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

    # Build invoice summary for display
    invoice_summary = None
    if record.get("invoice_number"):
        invoice_summary = {
            "invoice_number": record.get("invoice_number"),
            "total_amount": str(record["total_amount"]) if record.get("total_amount") else None,
            "due_date": record["due_date"].isoformat() if record.get("due_date") else None,
        }

    return SubmissionFormConfig(
        fields=record.get("submission_fields", []),
        invoice_summary=invoice_summary,
        counterparty_name=record.get("counterparty_name"),
        organization_name=record.get("organization_name"),
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
