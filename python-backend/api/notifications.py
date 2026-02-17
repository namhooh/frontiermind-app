"""
Notifications API Endpoints

REST API for email notification management: templates, schedules, email logs.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Query, Request
from pydantic import BaseModel

from models.notifications import (
    SendEmailRequest,
    CreateEmailTemplateRequest,
    UpdateEmailTemplateRequest,
    CreateScheduleRequest,
    UpdateScheduleRequest,
    EmailTemplateResponse,
    EmailTemplateListResponse,
    EmailLogResponse,
    EmailLogListResponse,
    NotificationScheduleResponse,
    NotificationScheduleListResponse,
    SubmissionResponseListResponse,
    SubmissionResponseModel,
    SendEmailResponse,
)
from db.notification_repository import NotificationRepository
from db.database import init_connection_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    responses={
        404: {"description": "Resource not found"},
        500: {"description": "Internal server error"},
    },
)

# Initialize repository
notification_repo = None
try:
    init_connection_pool()
    notification_repo = NotificationRepository()
    logger.info("Notifications API: Database initialized")
except Exception as e:
    logger.warning(f"Notifications API: Database initialization failed: {e}")


class SuccessResponse(BaseModel):
    success: bool = True
    message: str


def get_org_id(request: Request) -> int:
    org_id = request.headers.get("X-Organization-ID")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "MissingOrganization",
                    "message": "X-Organization-ID header required"},
        )
    try:
        return int(org_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": "InvalidOrganization",
                    "message": "X-Organization-ID must be an integer"},
        )


def require_repo():
    if not notification_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable",
                    "message": "Database connection not available"},
        )


# ============================================================================
# Send Email
# ============================================================================

@router.post(
    "/send",
    response_model=SendEmailResponse,
    summary="Send email immediately",
)
async def send_email(request: Request, body: SendEmailRequest) -> SendEmailResponse:
    require_repo()
    org_id = get_org_id(request)

    try:
        from services.email.notification_service import NotificationService
        service = NotificationService(notification_repo)

        result = service.send_immediate(
            org_id=org_id,
            template_id=body.template_id,
            recipient_emails=body.recipient_emails,
            invoice_header_id=body.invoice_header_id,
            include_submission_link=body.include_submission_link,
            submission_fields=body.submission_fields,
            extra_context=body.extra_context,
        )

        return SendEmailResponse(
            success=True,
            emails_sent=result["emails_sent"],
            email_log_ids=result["email_log_ids"],
            submission_token_id=result.get("submission_token_id"),
            message=f"Sent {result['emails_sent']} email(s)",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.error(f"Error sending email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


# ============================================================================
# Template Endpoints
# ============================================================================

@router.get("/templates", response_model=EmailTemplateListResponse)
async def list_templates(
    request: Request,
    email_schedule_type: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
) -> EmailTemplateListResponse:
    require_repo()
    org_id = get_org_id(request)
    try:
        templates = notification_repo.list_templates(
            org_id, email_schedule_type=email_schedule_type, include_inactive=include_inactive
        )
        return EmailTemplateListResponse(
            templates=[EmailTemplateResponse(**t) for t in templates],
            total=len(templates),
        )
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


@router.get("/templates/{template_id}", response_model=EmailTemplateResponse)
async def get_template(request: Request, template_id: int) -> EmailTemplateResponse:
    require_repo()
    org_id = get_org_id(request)
    template = notification_repo.get_template(template_id, org_id)
    if not template:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found"})
    return EmailTemplateResponse(**template)


@router.post(
    "/templates",
    response_model=EmailTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    request: Request, body: CreateEmailTemplateRequest
) -> EmailTemplateResponse:
    require_repo()
    org_id = get_org_id(request)
    try:
        template_id = notification_repo.create_template(
            org_id, body.model_dump(exclude_none=True)
        )
        template = notification_repo.get_template(template_id, org_id)
        return EmailTemplateResponse(**template)
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


@router.put("/templates/{template_id}", response_model=EmailTemplateResponse)
async def update_template(
    request: Request, template_id: int, body: UpdateEmailTemplateRequest
) -> EmailTemplateResponse:
    require_repo()
    org_id = get_org_id(request)
    existing = notification_repo.get_template(template_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found"})
    updates = body.model_dump(exclude_none=True)
    if updates:
        notification_repo.update_template(template_id, org_id, updates)
    template = notification_repo.get_template(template_id, org_id)
    return EmailTemplateResponse(**template)


@router.delete("/templates/{template_id}", response_model=SuccessResponse)
async def delete_template(request: Request, template_id: int) -> SuccessResponse:
    require_repo()
    org_id = get_org_id(request)
    success = notification_repo.deactivate_template(template_id, org_id)
    if not success:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found or is system template"})
    return SuccessResponse(message="Template deactivated")


# ============================================================================
# Schedule Endpoints
# ============================================================================

@router.get("/schedules", response_model=NotificationScheduleListResponse)
async def list_schedules(
    request: Request,
    include_inactive: bool = Query(False),
) -> NotificationScheduleListResponse:
    require_repo()
    org_id = get_org_id(request)
    schedules = notification_repo.list_schedules(org_id, include_inactive=include_inactive)
    return NotificationScheduleListResponse(
        schedules=[NotificationScheduleResponse(**s) for s in schedules],
        total=len(schedules),
    )


@router.get("/schedules/{schedule_id}", response_model=NotificationScheduleResponse)
async def get_schedule(request: Request, schedule_id: int) -> NotificationScheduleResponse:
    require_repo()
    org_id = get_org_id(request)
    schedule = notification_repo.get_schedule(schedule_id, org_id)
    if not schedule:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})
    return NotificationScheduleResponse(**schedule)


@router.post(
    "/schedules",
    response_model=NotificationScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    request: Request, body: CreateScheduleRequest
) -> NotificationScheduleResponse:
    require_repo()
    org_id = get_org_id(request)
    try:
        # Verify template exists
        template = notification_repo.get_template(body.email_template_id, org_id)
        if not template:
            raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found"})

        schedule_id = notification_repo.create_schedule(
            org_id, body.model_dump(exclude_none=True)
        )
        schedule = notification_repo.get_schedule(schedule_id, org_id)
        return NotificationScheduleResponse(**schedule)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating schedule: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


@router.put("/schedules/{schedule_id}", response_model=NotificationScheduleResponse)
async def update_schedule(
    request: Request, schedule_id: int, body: UpdateScheduleRequest
) -> NotificationScheduleResponse:
    require_repo()
    org_id = get_org_id(request)
    existing = notification_repo.get_schedule(schedule_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})
    updates = body.model_dump(exclude_none=True)
    if updates:
        notification_repo.update_schedule(schedule_id, org_id, updates)
    schedule = notification_repo.get_schedule(schedule_id, org_id)
    return NotificationScheduleResponse(**schedule)


@router.delete("/schedules/{schedule_id}", response_model=SuccessResponse)
async def delete_schedule(request: Request, schedule_id: int) -> SuccessResponse:
    require_repo()
    org_id = get_org_id(request)
    existing = notification_repo.get_schedule(schedule_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})
    notification_repo.update_schedule(schedule_id, org_id, {"is_active": False})
    return SuccessResponse(message="Schedule deactivated")


@router.post("/schedules/{schedule_id}/trigger", response_model=SendEmailResponse)
async def trigger_schedule(request: Request, schedule_id: int) -> SendEmailResponse:
    """Manually trigger a schedule immediately."""
    require_repo()
    org_id = get_org_id(request)
    schedule = notification_repo.get_schedule(schedule_id, org_id)
    if not schedule:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})

    try:
        from services.email.notification_service import NotificationService
        service = NotificationService(notification_repo)

        # Get template for this schedule
        template = notification_repo.get_template(schedule["email_template_id"], org_id)
        schedule_with_template = {**schedule, **{
            "subject_template": template["subject_template"],
            "body_html": template["body_html"],
            "body_text": template.get("body_text"),
        }}

        sent = service._process_single_schedule(schedule_with_template)
        notification_repo.update_schedule_after_run(schedule_id, "completed")

        return SendEmailResponse(
            success=True,
            emails_sent=sent,
            email_log_ids=[],
            message=f"Triggered: sent {sent} email(s)",
        )
    except Exception as e:
        logger.error(f"Error triggering schedule {schedule_id}: {e}", exc_info=True)
        notification_repo.update_schedule_after_run(schedule_id, "failed", str(e))
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


# ============================================================================
# Email Log Endpoints
# ============================================================================

@router.get("/email-log", response_model=EmailLogListResponse)
async def list_email_logs(
    request: Request,
    invoice_header_id: Optional[int] = Query(None),
    schedule_id: Optional[int] = Query(None),
    email_status: Optional[str] = Query(None, alias="email_status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> EmailLogListResponse:
    require_repo()
    org_id = get_org_id(request)
    logs, total = notification_repo.list_email_logs(
        org_id,
        invoice_header_id=invoice_header_id,
        schedule_id=schedule_id,
        status=email_status,
        limit=limit,
        offset=offset,
    )
    return EmailLogListResponse(
        logs=[EmailLogResponse(**log) for log in logs],
        total=total,
    )


# ============================================================================
# Submission Response Endpoints
# ============================================================================

@router.get("/submissions", response_model=SubmissionResponseListResponse)
async def list_submissions(
    request: Request,
    invoice_header_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SubmissionResponseListResponse:
    require_repo()
    org_id = get_org_id(request)
    submissions, total = notification_repo.list_submission_responses(
        org_id, invoice_header_id=invoice_header_id, limit=limit, offset=offset
    )
    return SubmissionResponseListResponse(
        submissions=[SubmissionResponseModel(**s) for s in submissions],
        total=total,
    )
