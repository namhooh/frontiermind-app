"""
Notifications API Endpoints

REST API for email notification management: templates, schedules, email logs.
Dashboard endpoints use Supabase JWT auth (require_supabase_auth).
"""

import logging
import os
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel

from middleware.supabase_auth import require_supabase_auth
from models.notifications import (
    SendEmailRequest,
    CreateEmailTemplateRequest,
    UpdateEmailTemplateRequest,
    CreateScheduleRequest,
    UpdateScheduleRequest,
    EmailTemplateResponse,
    EmailTemplateListResponse,
    OutboundMessageResponse,
    OutboundMessageListResponse,
    NotificationScheduleResponse,
    NotificationScheduleListResponse,
    SubmissionResponseListResponse,
    SubmissionResponseModel,
    SendEmailResponse,
    MRPCollectionRequest,
    PreviewTemplateRequest,
    PreviewTemplateResponse,
    ContactItem,
    ContactListResponse,
    TemplateGenerateRequest,
    TemplateGenerateResponse,
)
from db.notification_repository import NotificationRepository
from db.database import init_connection_pool, get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
    responses={
        401: {"description": "Missing or invalid token"},
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


def require_repo():
    if not notification_repo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"success": False, "error": "DatabaseNotAvailable",
                    "message": "Database connection not available"},
        )


def _validate_entity_ownership(table: str, entity_id: int, org_id: int) -> None:
    """Verify an entity belongs to the given organization. Raises 404 if not."""
    allowed_tables = {"project", "contract", "counterparty"}
    if table not in allowed_tables:
        raise ValueError(f"Invalid table: {table}")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id FROM {table} WHERE id = %s AND organization_id = %s",
                (entity_id, org_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"success": False, "message": f"{table.title()} not found"},
                )


# ============================================================================
# Test Email
# ============================================================================

class TestEmailRequest(BaseModel):
    to: str
    subject: str = "Test email from FrontierMind"
    body: str = "This is a test email. If you received this, SES is working correctly."


class TestEmailResponse(BaseModel):
    success: bool
    message: str
    sender: str


@router.post(
    "/test-email",
    response_model=TestEmailResponse,
    summary="Send a quick test email using org sender config",
)
async def test_email(request: Request, body: TestEmailRequest, auth: dict = Depends(require_supabase_auth)) -> TestEmailResponse:
    require_repo()
    org_id = auth["organization_id"]

    try:
        from services.email.ses_client import SESClient
        from services.email.notification_service import NotificationService

        service = NotificationService(notification_repo)
        org_sender = service._get_org_sender(org_id)

        ses = SESClient()
        html_body = f"<p>{body.body}</p>"
        ses_message_id = ses.send_email(
            to=[body.to],
            subject=body.subject,
            html_body=html_body,
            text_body=body.body,
            sender_name=org_sender["sender_name"],
            sender_email=org_sender["sender_email"],
        )

        sender_display = ses.format_sender(org_sender["sender_name"], org_sender["sender_email"])
        return TestEmailResponse(
            success=True,
            message=f"Test email sent (SES ID: {ses_message_id})",
            sender=sender_display,
        )
    except Exception as e:
        logger.error(f"Test email failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


# ============================================================================
# Send Email
# ============================================================================

@router.post(
    "/send",
    response_model=SendEmailResponse,
    summary="Send email immediately",
)
async def send_email(request: Request, body: SendEmailRequest, auth: dict = Depends(require_supabase_auth)) -> SendEmailResponse:
    require_repo()
    org_id = auth["organization_id"]

    try:
        from services.email.notification_service import NotificationService
        frontend_url = request.headers.get("X-Frontend-URL") or None
        service = NotificationService(notification_repo, frontend_url=frontend_url)

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
            outbound_message_ids=result["outbound_message_ids"],
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
    email_schedule_type: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    auth: dict = Depends(require_supabase_auth),
) -> EmailTemplateListResponse:
    require_repo()
    org_id = auth["organization_id"]
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
async def get_template(template_id: int, auth: dict = Depends(require_supabase_auth)) -> EmailTemplateResponse:
    require_repo()
    org_id = auth["organization_id"]
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
    body: CreateEmailTemplateRequest, auth: dict = Depends(require_supabase_auth),
) -> EmailTemplateResponse:
    require_repo()
    org_id = auth["organization_id"]
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
    template_id: int, body: UpdateEmailTemplateRequest, auth: dict = Depends(require_supabase_auth),
) -> EmailTemplateResponse:
    require_repo()
    org_id = auth["organization_id"]
    existing = notification_repo.get_template(template_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found"})
    updates = body.model_dump(exclude_none=True)
    if updates:
        notification_repo.update_template(template_id, org_id, updates)
    template = notification_repo.get_template(template_id, org_id)
    return EmailTemplateResponse(**template)


@router.delete("/templates/{template_id}", response_model=SuccessResponse)
async def delete_template(template_id: int, auth: dict = Depends(require_supabase_auth)) -> SuccessResponse:
    require_repo()
    org_id = auth["organization_id"]
    success = notification_repo.deactivate_template(template_id, org_id)
    if not success:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found or is system template"})
    return SuccessResponse(message="Template deactivated")


# ============================================================================
# AI Template Generation
# ============================================================================

@router.post(
    "/templates/generate",
    response_model=TemplateGenerateResponse,
    summary="Generate email template using AI",
)
async def generate_template(
    body: TemplateGenerateRequest, auth: dict = Depends(require_supabase_auth),
) -> TemplateGenerateResponse:
    """Use Claude to generate an HTML email template from a natural language prompt."""
    import json as _json
    from anthropic import Anthropic

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise HTTPException(status_code=500, detail={"success": False, "message": "ANTHROPIC_API_KEY not configured"})

    variables_list = ", ".join(f"{{{{ {v} }}}}" for v in body.variables) if body.variables else "none provided"

    system_prompt = (
        "You are an expert email template designer for a renewable energy contract management platform called FrontierMind. "
        "Generate a professional, responsive HTML email template based on the user's description.\n\n"
        "Rules:\n"
        "- Use Jinja2 {{ variable_name }} syntax for dynamic content\n"
        "- Include ALL provided variables naturally in the template\n"
        "- Generate clean, inline-styled HTML that renders well in email clients\n"
        "- Use a professional color scheme (blues/grays) with good typography\n"
        "- Include a header, body content, and footer section\n"
        "- Make the template responsive with max-width container\n"
        "- Do NOT use external CSS or JavaScript\n"
        "- Generate a matching plain text version\n\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        '{ "subject_template": "...", "body_html": "...", "body_text": "..." }\n\n'
        "No markdown code fences. No explanation. Just the JSON object."
    )

    user_message = (
        f"Template type: {body.email_schedule_type}\n"
        f"Description: {body.prompt}\n"
        f"Available variables: {variables_list}"
    )

    try:
        client = Anthropic(api_key=anthropic_api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            temperature=0.7,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

        result = _json.loads(raw_text)

        return TemplateGenerateResponse(
            success=True,
            subject_template=result["subject_template"],
            body_html=result["body_html"],
            body_text=result["body_text"],
        )
    except _json.JSONDecodeError as e:
        logger.error(f"AI template generation returned invalid JSON: {e}")
        raise HTTPException(status_code=502, detail={"success": False, "message": "AI returned invalid response. Please try again."})
    except Exception as e:
        logger.error(f"AI template generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": f"Template generation failed: {e}"})


# ============================================================================
# Template Preview
# ============================================================================

# Sample context for previewing templates without real invoice data
SAMPLE_CONTEXT = {
    "company_name": "Acme Solar LLC",
    "project_name": "Solar Farm Alpha",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-03-01",
    "due_date": "2026-03-31",
    "total_amount": "12,500.00",
    "currency": "USD",
    "billing_period": "February 2026",
    "counterparty_name": "Green Energy Corp",
    "contract_name": "PPA — Solar Farm Alpha",
    "submission_url": "#",
    "recipient_name": "Jane Doe",
    "sender_name": "FrontierMind",
}


@router.post(
    "/templates/preview",
    response_model=PreviewTemplateResponse,
    summary="Preview a rendered template",
)
async def preview_template(
    body: PreviewTemplateRequest, auth: dict = Depends(require_supabase_auth),
) -> PreviewTemplateResponse:
    """Render a template with sample or real data, returns HTML without sending."""
    require_repo()
    org_id = auth["organization_id"]

    subject_tpl = body.subject_template
    body_html_tpl = body.body_html

    # Load from DB if template_id given (and inline not provided)
    if body.template_id and (not subject_tpl or not body_html_tpl):
        template = notification_repo.get_template(body.template_id, org_id)
        if not template:
            raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found"})
        if not subject_tpl:
            subject_tpl = template["subject_template"]
        if not body_html_tpl:
            body_html_tpl = template["body_html"]

    if not subject_tpl or not body_html_tpl:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "message": "Provide template_id or inline subject_template + body_html"},
        )

    # Build context: start with sample defaults, then overlay real org data
    context = dict(SAMPLE_CONTEXT)

    # Fetch real organization data to replace hardcoded placeholders
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM organization WHERE id = %s",
                    (org_id,),
                )
                org_row = cur.fetchone()
                if org_row:
                    context["company_name"] = org_row["name"]
                    context["sender_name"] = org_row["name"]

                # Use a real project name if available
                cur.execute(
                    "SELECT name FROM project WHERE organization_id = %s ORDER BY id LIMIT 1",
                    (org_id,),
                )
                proj_row = cur.fetchone()
                if proj_row:
                    context["project_name"] = proj_row["name"]
    except Exception as e:
        logger.warning(f"Failed to load org context for preview: {e}")

    # If invoice_header_id provided, overlay real invoice data
    if body.invoice_header_id:
        try:
            from services.email.notification_service import NotificationService
            service = NotificationService(notification_repo)
            invoice_context = service._build_invoice_context(body.invoice_header_id, org_id)
            if invoice_context:
                context.update(invoice_context)
        except Exception as e:
            logger.warning(f"Failed to load invoice context for preview: {e}")

    # Override with extra_context
    if body.extra_context:
        context.update(body.extra_context)

    try:
        from services.email.template_renderer import EmailTemplateRenderer
        renderer = EmailTemplateRenderer()
        rendered = renderer.render_email(
            subject_template=subject_tpl,
            body_html_template=body_html_tpl,
            body_text_template=None,
            context=context,
        )
        return PreviewTemplateResponse(
            success=True,
            subject=rendered["subject"],
            html=rendered["html"],
        )
    except Exception as e:
        logger.error(f"Template preview render error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail={"success": False, "message": f"Render error: {e}"})


# ============================================================================
# Contacts Endpoint
# ============================================================================

@router.get(
    "/contacts",
    response_model=ContactListResponse,
    summary="List email-eligible contacts",
)
async def list_contacts(
    counterparty_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    include_all: bool = Query(False),
    auth: dict = Depends(require_supabase_auth),
) -> ContactListResponse:
    """List contacts eligible for email notifications, optionally filtered."""
    require_repo()
    org_id = auth["organization_id"]
    try:
        contacts = notification_repo.list_contacts(
            org_id,
            counterparty_id=counterparty_id,
            project_id=project_id,
            include_all=include_all,
        )
        return ContactListResponse(
            contacts=[ContactItem(**c) for c in contacts],
            total=len(contacts),
        )
    except Exception as e:
        logger.error(f"Error listing contacts: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


# ============================================================================
# Schedule Endpoints
# ============================================================================

@router.get("/schedules", response_model=NotificationScheduleListResponse)
async def list_schedules(
    include_inactive: bool = Query(False),
    project_id: Optional[int] = Query(None),
    auth: dict = Depends(require_supabase_auth),
) -> NotificationScheduleListResponse:
    require_repo()
    org_id = auth["organization_id"]
    schedules = notification_repo.list_schedules(org_id, include_inactive=include_inactive, project_id=project_id)
    return NotificationScheduleListResponse(
        schedules=[NotificationScheduleResponse(**s) for s in schedules],
        total=len(schedules),
    )


@router.get("/schedules/{schedule_id}", response_model=NotificationScheduleResponse)
async def get_schedule(schedule_id: int, auth: dict = Depends(require_supabase_auth)) -> NotificationScheduleResponse:
    require_repo()
    org_id = auth["organization_id"]
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
    body: CreateScheduleRequest, auth: dict = Depends(require_supabase_auth),
) -> NotificationScheduleResponse:
    require_repo()
    org_id = auth["organization_id"]
    try:
        # Verify template exists
        template = notification_repo.get_template(body.email_template_id, org_id)
        if not template:
            raise HTTPException(status_code=404, detail={"success": False, "message": "Template not found"})

        # Validate entity ownership for scope fields
        if body.project_id:
            _validate_entity_ownership("project", body.project_id, org_id)
        if body.contract_id:
            _validate_entity_ownership("contract", body.contract_id, org_id)
        if body.counterparty_id:
            _validate_entity_ownership("counterparty", body.counterparty_id, org_id)

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
    schedule_id: int, body: UpdateScheduleRequest, auth: dict = Depends(require_supabase_auth),
) -> NotificationScheduleResponse:
    require_repo()
    org_id = auth["organization_id"]
    existing = notification_repo.get_schedule(schedule_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})

    # Validate entity ownership for scope fields if being updated
    if body.project_id:
        _validate_entity_ownership("project", body.project_id, org_id)
    if body.contract_id:
        _validate_entity_ownership("contract", body.contract_id, org_id)
    if body.counterparty_id:
        _validate_entity_ownership("counterparty", body.counterparty_id, org_id)

    updates = body.model_dump(exclude_none=True)
    if updates:
        notification_repo.update_schedule(schedule_id, org_id, updates)
    schedule = notification_repo.get_schedule(schedule_id, org_id)
    return NotificationScheduleResponse(**schedule)


@router.delete("/schedules/{schedule_id}", response_model=SuccessResponse)
async def delete_schedule(schedule_id: int, auth: dict = Depends(require_supabase_auth)) -> SuccessResponse:
    require_repo()
    org_id = auth["organization_id"]
    existing = notification_repo.get_schedule(schedule_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})
    notification_repo.update_schedule(schedule_id, org_id, {"is_active": False})
    return SuccessResponse(message="Schedule deactivated")


@router.post("/schedules/{schedule_id}/trigger", response_model=SendEmailResponse)
async def trigger_schedule(request: Request, schedule_id: int, auth: dict = Depends(require_supabase_auth)) -> SendEmailResponse:
    """Manually trigger a schedule immediately."""
    require_repo()
    org_id = auth["organization_id"]
    schedule = notification_repo.get_schedule(schedule_id, org_id)
    if not schedule:
        raise HTTPException(status_code=404, detail={"success": False, "message": "Schedule not found"})

    try:
        from services.email.notification_service import NotificationService
        frontend_url = request.headers.get("X-Frontend-URL") or None
        service = NotificationService(notification_repo, frontend_url=frontend_url)

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
            outbound_message_ids=[],
            message=f"Triggered: sent {sent} email(s)",
        )
    except Exception as e:
        logger.error(f"Error triggering schedule {schedule_id}: {e}", exc_info=True)
        notification_repo.update_schedule_after_run(schedule_id, "failed", str(e))
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


# ============================================================================
# Outbound Message Endpoints
# ============================================================================

@router.get("/outbound-messages", response_model=OutboundMessageListResponse)
async def list_outbound_messages(
    invoice_header_id: Optional[int] = Query(None),
    schedule_id: Optional[int] = Query(None),
    email_status: Optional[str] = Query(None, alias="email_status"),
    project_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_supabase_auth),
) -> OutboundMessageListResponse:
    require_repo()
    org_id = auth["organization_id"]
    logs, total = notification_repo.list_outbound_messages(
        org_id,
        invoice_header_id=invoice_header_id,
        schedule_id=schedule_id,
        status=email_status,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return OutboundMessageListResponse(
        messages=[OutboundMessageResponse(**log) for log in logs],
        total=total,
    )


# ============================================================================
# Submission Response Endpoints
# ============================================================================

@router.get("/submissions", response_model=SubmissionResponseListResponse)
async def list_submissions(
    invoice_header_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_supabase_auth),
) -> SubmissionResponseListResponse:
    require_repo()
    org_id = auth["organization_id"]
    submissions, total = notification_repo.list_inbound_messages(
        org_id, invoice_header_id=invoice_header_id, limit=limit, offset=offset
    )
    return SubmissionResponseListResponse(
        submissions=[SubmissionResponseModel(**s) for s in submissions],
        total=total,
    )


# ============================================================================
# MRP Collection
# ============================================================================

class MRPCollectionResponse(BaseModel):
    success: bool = True
    token_id: int
    submission_url: str
    message: str


@router.post(
    "/mrp-collection",
    response_model=MRPCollectionResponse,
    summary="Generate MRP collection token",
)
async def create_mrp_collection(
    request: Request, body: MRPCollectionRequest, auth: dict = Depends(require_supabase_auth),
) -> MRPCollectionResponse:
    """Generate a reusable MRP upload token for a project."""
    require_repo()
    org_id = auth["organization_id"]

    _validate_entity_ownership("project", body.project_id, org_id)
    if body.counterparty_id:
        _validate_entity_ownership("counterparty", body.counterparty_id, org_id)

    try:
        from services.email.token_service import TokenService

        token_svc = TokenService(notification_repo)
        result = token_svc.generate_token(
            org_id=org_id,
            counterparty_id=body.counterparty_id,
            fields=[{"operating_year": body.operating_year}],
            expiry_hours=body.expiry_hours,
            max_uses=body.max_uses,
            project_id=body.project_id,
            submission_type="mrp_upload",
        )

        frontend_url = request.headers.get(
            "X-Frontend-URL",
            os.getenv("APP_BASE_URL", "https://frontiermind-app.vercel.app"),
        )
        submission_url = f"{frontend_url}/submit/{result['token']}"
        token_svc.store_submission_url(result["token_id"], submission_url)

        return MRPCollectionResponse(
            success=True,
            token_id=result["token_id"],
            submission_url=submission_url,
            message=f"MRP collection token created (max {body.max_uses} uploads)",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating MRP collection token: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": str(e)},
        )


# ============================================================================
# Submission Token Listing
# ============================================================================

class SubmissionTokenItem(BaseModel):
    id: int
    organization_id: int
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    submission_type: Optional[str] = None
    submission_token_status: str
    max_uses: int
    use_count: int
    expires_at: Optional[str] = None
    submission_url: Optional[str] = None
    created_at: Optional[str] = None


class SubmissionTokenListResponse(BaseModel):
    success: bool = True
    tokens: List[SubmissionTokenItem]
    total: int


@router.get(
    "/tokens",
    response_model=SubmissionTokenListResponse,
    summary="List submission tokens",
)
async def list_tokens(
    project_id: Optional[int] = Query(None),
    submission_type: Optional[str] = Query(None),
    include_expired: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_supabase_auth),
) -> SubmissionTokenListResponse:
    """List submission tokens for the organization."""
    require_repo()
    org_id = auth["organization_id"]

    try:
        tokens, total = notification_repo.list_submission_tokens(
            org_id=org_id,
            project_id=project_id,
            submission_type=submission_type,
            include_expired=include_expired,
            limit=limit,
            offset=offset,
        )
        return SubmissionTokenListResponse(
            tokens=[
                SubmissionTokenItem(
                    **{
                        k: (str(v) if k in ("expires_at", "created_at") and v is not None else v)
                        for k, v in t.items()
                    }
                )
                for t in tokens
            ],
            total=total,
        )
    except Exception as e:
        logger.error(f"Error listing tokens: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})


@router.post(
    "/tokens/{token_id}/revoke",
    response_model=SuccessResponse,
    summary="Revoke a submission token",
)
async def revoke_token(token_id: int, auth: dict = Depends(require_supabase_auth)) -> SuccessResponse:
    """Revoke an active submission token so its link stops working."""
    require_repo()
    org_id = auth["organization_id"]

    try:
        notification_repo.revoke_submission_token(token_id, org_id)
        return SuccessResponse(message="Token revoked")
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail={"success": False, "message": msg})
        raise HTTPException(status_code=400, detail={"success": False, "message": msg})
