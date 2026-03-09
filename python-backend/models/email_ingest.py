"""
Pydantic models for the inbound email ingestion system.

Covers: inbound_message, inbound_attachment, SNS webhook payloads.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# =============================================================================
# ENUMS
# =============================================================================

class InboundChannel(str, Enum):
    email = "email"
    token_form = "token_form"
    token_upload = "token_upload"


class InboundMessageStatus(str, Enum):
    received = "received"
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    noise = "noise"
    auto_processed = "auto_processed"
    failed = "failed"


class AttachmentProcessingStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    extracted = "extracted"
    failed = "failed"
    skipped = "skipped"


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class InboundAttachmentResponse(BaseModel):
    id: int
    filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    attachment_processing_status: str
    extraction_result: Optional[dict] = None
    reference_price_id: Optional[int] = None
    failed_reason: Optional[str] = None
    created_at: datetime


class InboundMessageResponse(BaseModel):
    id: int
    organization_id: int
    channel: InboundChannel
    subject: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    inbound_message_status: InboundMessageStatus
    classification_reason: Optional[str] = None
    failed_reason: Optional[str] = None
    attachment_count: int = 0
    invoice_header_id: Optional[int] = None
    project_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    outbound_message_id: Optional[int] = None
    created_at: datetime
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    attachments: List[InboundAttachmentResponse] = []


class InboundMessageListResponse(BaseModel):
    success: bool = True
    messages: List[InboundMessageResponse]
    total: int
    limit: int
    offset: int


# =============================================================================
# REQUEST MODELS
# =============================================================================

class ReviewAction(BaseModel):
    reason: Optional[str] = None
    project_id: Optional[int] = None
    billing_month: Optional[str] = None


class ProcessAttachmentRequest(BaseModel):
    project_id: Optional[int] = None
    billing_month: Optional[str] = None


class AttachmentProcessingResponse(BaseModel):
    success: bool
    message: str
    status: str
    observation_id: Optional[int] = None
    mrp_per_kwh: Optional[float] = None
    confidence: Optional[str] = None
    billing_month: Optional[str] = None
    failed_reason: Optional[str] = None


class ApproveMessageResponse(BaseModel):
    success: bool = True
    message: str
    extraction_results: List[AttachmentProcessingResponse] = []


# =============================================================================
# SNS MODELS
# =============================================================================

class SNSMessage(BaseModel):
    Type: str
    MessageId: str
    TopicArn: str
    Subject: Optional[str] = None
    Message: str
    SubscribeURL: Optional[str] = None
    Timestamp: str
    SignatureVersion: str
    Signature: str
    SigningCertURL: str
