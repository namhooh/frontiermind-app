"""
Pydantic models for the email notification engine.

This module defines data structures for email templates, notification schedules,
email logs, submission tokens, and the request/response models for the notifications API.

Database Reference: migration 032_email_notification_engine.sql
"""

from enum import Enum
from datetime import datetime, time
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# ENUMS (matching database enums from migration 032)
# =============================================================================

class EmailScheduleType(str, Enum):
    INVOICE_REMINDER = "invoice_reminder"
    INVOICE_INITIAL = "invoice_initial"
    INVOICE_ESCALATION = "invoice_escalation"
    COMPLIANCE_ALERT = "compliance_alert"
    METER_DATA_MISSING = "meter_data_missing"
    REPORT_READY = "report_ready"
    CUSTOM = "custom"


class EmailStatus(str, Enum):
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class SubmissionTokenStatus(str, Enum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


# =============================================================================
# REQUEST MODELS
# =============================================================================

class SendEmailRequest(BaseModel):
    """Request to send an email immediately."""
    template_id: int = Field(..., description="Email template to use")
    invoice_header_id: Optional[int] = Field(None, description="Invoice to include in context")
    recipient_emails: List[str] = Field(..., min_length=1, description="Recipient email addresses")
    include_submission_link: bool = Field(False, description="Include a submission link in the email")
    submission_fields: Optional[List[str]] = Field(
        None, description="Fields to collect via submission link"
    )
    extra_context: Optional[Dict[str, Any]] = Field(
        None, description="Additional template context variables"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": 1,
                "invoice_header_id": 42,
                "recipient_emails": ["finance@counterparty.com"],
                "include_submission_link": True,
                "submission_fields": ["po_number", "payment_date"],
            }
        }
    )


class CreateEmailTemplateRequest(BaseModel):
    """Request to create a new email template."""
    name: str = Field(..., min_length=1, max_length=255)
    email_schedule_type: EmailScheduleType
    subject_template: str = Field(..., min_length=1, max_length=500)
    body_html: str = Field(..., min_length=1)
    body_text: Optional[str] = None
    description: Optional[str] = None
    available_variables: List[str] = Field(default_factory=list)


class UpdateEmailTemplateRequest(BaseModel):
    """Request to update an email template."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    subject_template: Optional[str] = Field(None, min_length=1, max_length=500)
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    description: Optional[str] = None
    available_variables: Optional[List[str]] = None
    is_active: Optional[bool] = None


class CreateScheduleRequest(BaseModel):
    """Request to create a notification schedule."""
    name: str = Field(..., min_length=1, max_length=255)
    email_template_id: int
    email_schedule_type: EmailScheduleType
    report_frequency: str = Field(..., description="Reuses report_frequency enum: monthly, quarterly, annual, on_demand")
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    time_of_day: time = Field(default=time(9, 0))
    timezone: str = Field("UTC")
    conditions: Dict[str, Any] = Field(default_factory=dict)
    max_reminders: Optional[int] = Field(3, ge=1)
    escalation_after: Optional[int] = Field(1, ge=1)
    include_submission_link: bool = False
    submission_fields: Optional[List[str]] = None
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    counterparty_id: Optional[int] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Monthly Invoice Reminder",
                "email_template_id": 2,
                "email_schedule_type": "invoice_reminder",
                "report_frequency": "monthly",
                "day_of_month": 15,
                "time_of_day": "09:00:00",
                "timezone": "America/New_York",
                "conditions": {
                    "invoice_status": ["sent", "verified"],
                    "days_overdue_min": 7,
                },
                "max_reminders": 3,
                "escalation_after": 2,
                "include_submission_link": True,
                "submission_fields": ["po_number", "payment_date"],
            }
        }
    )


class UpdateScheduleRequest(BaseModel):
    """Request to update a notification schedule."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email_template_id: Optional[int] = None
    report_frequency: Optional[str] = None
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    time_of_day: Optional[time] = None
    timezone: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None
    max_reminders: Optional[int] = Field(None, ge=1)
    escalation_after: Optional[int] = Field(None, ge=1)
    include_submission_link: Optional[bool] = None
    submission_fields: Optional[List[str]] = None
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    is_active: Optional[bool] = None


class SubmitResponseRequest(BaseModel):
    """Public submission from counterparty."""
    response_data: Dict[str, Any] = Field(..., description="Submitted form data")
    submitted_by_email: Optional[str] = Field(None, max_length=255)


class GRPCollectionRequest(BaseModel):
    """Request to generate a GRP collection token."""
    project_id: int = Field(..., description="Project for GRP collection")
    counterparty_id: Optional[int] = Field(None, description="Utility counterparty")
    operating_year: int = Field(..., ge=1, description="Contract operating year")
    max_uses: int = Field(12, ge=1, le=24, description="Max uploads (default 12 = one per month)")
    expiry_hours: int = Field(8760, description="Token expiry in hours (default 1 year)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_id": 1,
                "counterparty_id": 3,
                "operating_year": 2,
                "max_uses": 12,
            }
        }
    )


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class EmailTemplateResponse(BaseModel):
    """Response model for email template."""
    id: int
    organization_id: int
    email_schedule_type: EmailScheduleType
    name: str
    description: Optional[str]
    subject_template: str
    body_html: str
    body_text: Optional[str]
    available_variables: List[Any]
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmailLogResponse(BaseModel):
    """Response model for email log entry."""
    id: int
    organization_id: int
    email_notification_schedule_id: Optional[int]
    email_template_id: Optional[int]
    recipient_email: str
    recipient_name: Optional[str]
    subject: str
    email_status: EmailStatus
    ses_message_id: Optional[str]
    reminder_count: int
    invoice_header_id: Optional[int]
    submission_token_id: Optional[int]
    error_message: Optional[str]
    sent_at: Optional[datetime]
    delivered_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationScheduleResponse(BaseModel):
    """Response model for notification schedule."""
    id: int
    organization_id: int
    email_template_id: int
    name: str
    email_schedule_type: EmailScheduleType
    report_frequency: str
    day_of_month: Optional[int]
    time_of_day: time
    timezone: str
    conditions: Dict[str, Any]
    max_reminders: Optional[int]
    escalation_after: Optional[int]
    include_submission_link: bool
    submission_fields: Optional[List[Any]]
    is_active: bool
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    last_run_error: Optional[str]
    next_run_at: Optional[datetime]
    project_id: Optional[int]
    contract_id: Optional[int]
    counterparty_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionTokenResponse(BaseModel):
    """Response model for submission token (internal use)."""
    id: int
    organization_id: int
    submission_token_status: SubmissionTokenStatus
    submission_fields: List[Any]
    max_uses: int
    use_count: int
    expires_at: datetime
    invoice_header_id: Optional[int]
    counterparty_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionFormConfig(BaseModel):
    """Public response for submission form configuration."""
    fields: List[Any]
    invoice_summary: Optional[Dict[str, Any]] = None
    counterparty_name: Optional[str] = None
    organization_name: Optional[str] = None
    project_name: Optional[str] = None
    submission_type: str = "form_response"
    expires_at: datetime


class SubmissionResponseModel(BaseModel):
    """Response model for a submission response."""
    id: int
    organization_id: int
    submission_token_id: int
    response_data: Dict[str, Any]
    submitted_by_email: Optional[str]
    invoice_header_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SendEmailResponse(BaseModel):
    """Response for immediate email send."""
    success: bool = True
    emails_sent: int
    email_log_ids: List[int]
    submission_token_id: Optional[int] = None
    message: str


# =============================================================================
# LIST RESPONSE MODELS
# =============================================================================

class EmailTemplateListResponse(BaseModel):
    success: bool = True
    templates: List[EmailTemplateResponse]
    total: int


class EmailLogListResponse(BaseModel):
    success: bool = True
    logs: List[EmailLogResponse]
    total: int


class NotificationScheduleListResponse(BaseModel):
    success: bool = True
    schedules: List[NotificationScheduleResponse]
    total: int


class SubmissionResponseListResponse(BaseModel):
    success: bool = True
    submissions: List[SubmissionResponseModel]
    total: int
