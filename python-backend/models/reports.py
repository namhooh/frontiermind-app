"""
Pydantic models for the report generation system.

This module defines data structures for report templates, scheduled reports,
generated reports, and the request/response models for the reports API.

Database Reference: migration 018_export_and_reports_schema.sql
"""

from enum import Enum
from datetime import datetime, time
from decimal import Decimal
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# ENUMS (matching database enums from migration 018)
# =============================================================================

class InvoiceReportType(str, Enum):
    """Report types for invoice-related reports."""
    INVOICE_TO_CLIENT = "invoice_to_client"
    INVOICE_EXPECTED = "invoice_expected"
    INVOICE_RECEIVED = "invoice_received"
    INVOICE_COMPARISON = "invoice_comparison"


class FileFormat(str, Enum):
    """Supported output file formats."""
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"
    PDF = "pdf"


class ReportFrequency(str, Enum):
    """Frequency options for scheduled reports."""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ON_DEMAND = "on_demand"


class ReportStatus(str, Enum):
    """Report generation lifecycle status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationSource(str, Enum):
    """Identifies how a report was triggered."""
    ON_DEMAND = "on_demand"
    SCHEDULED = "scheduled"


class DeliveryMethod(str, Enum):
    """Delivery options for scheduled reports."""
    EMAIL = "email"
    S3 = "s3"
    BOTH = "both"


# =============================================================================
# REQUEST MODELS
# =============================================================================

class GenerateReportRequest(BaseModel):
    """Request to generate a report on-demand."""

    template_id: Optional[int] = Field(None, description="Report template to use (optional for ad-hoc)")
    billing_period_id: int = Field(..., description="Billing period to generate report for")
    contract_id: Optional[int] = Field(None, description="Optional: filter to single contract")
    project_id: Optional[int] = Field(None, description="Optional: filter to single project")
    file_format: Optional[FileFormat] = Field(
        None,
        description="Override template's default file format"
    )
    report_type: Optional[InvoiceReportType] = Field(
        None,
        description="Report type (required if no template_id)"
    )
    name: Optional[str] = Field(
        None,
        max_length=255,
        description="Custom report name"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": 1,
                "billing_period_id": 12,
                "contract_id": 5,
                "file_format": "pdf"
            }
        }
    )


class CreateTemplateRequest(BaseModel):
    """Request to create a new report template."""

    name: str = Field(..., min_length=1, max_length=255, description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    report_type: InvoiceReportType = Field(..., description="Type of invoice report")
    file_format: FileFormat = Field(FileFormat.PDF, description="Default output format")
    template_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Template-specific configuration"
    )
    include_charts: bool = Field(True, description="Include charts in output")
    include_summary: bool = Field(True, description="Include summary section")
    include_line_items: bool = Field(True, description="Include line item details")
    project_id: Optional[int] = Field(
        None,
        description="Project ID for project-specific template (NULL = org-wide)"
    )
    default_contract_id: Optional[int] = Field(None, description="Default contract filter")
    logo_path: Optional[str] = Field(None, description="Path to logo for branding")
    header_text: Optional[str] = Field(None, description="Custom header text")
    footer_text: Optional[str] = Field(None, description="Custom footer text")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Monthly Client Invoice",
                "description": "Standard monthly invoice report for clients",
                "report_type": "invoice_to_client",
                "file_format": "pdf",
                "template_config": {
                    "include_meter_summary": True,
                    "include_adjustments": True
                },
                "include_charts": True,
                "include_summary": True,
                "include_line_items": True
            }
        }
    )


class UpdateTemplateRequest(BaseModel):
    """Request to update an existing report template."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    file_format: Optional[FileFormat] = None
    template_config: Optional[Dict[str, Any]] = None
    include_charts: Optional[bool] = None
    include_summary: Optional[bool] = None
    include_line_items: Optional[bool] = None
    default_contract_id: Optional[int] = None
    logo_path: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    is_active: Optional[bool] = None


class RecipientInfo(BaseModel):
    """Email recipient information for scheduled reports."""

    email: str = Field(..., description="Email address")
    name: Optional[str] = Field(None, description="Recipient name")


class CreateScheduleRequest(BaseModel):
    """Request to create a scheduled report."""

    name: str = Field(..., min_length=1, max_length=255, description="Schedule name")
    template_id: int = Field(..., description="Report template to use")
    report_frequency: ReportFrequency = Field(..., description="How often to run")
    day_of_month: Optional[int] = Field(
        None,
        ge=1,
        le=28,
        description="Day of month to run (1-28, required for monthly/quarterly/annual)"
    )
    time_of_day: time = Field(
        default=time(6, 0),
        description="Time of day to run (default: 06:00)"
    )
    timezone: str = Field("UTC", description="Timezone for scheduling")
    project_id: Optional[int] = Field(None, description="Project scope override")
    contract_id: Optional[int] = Field(None, description="Contract scope override")
    billing_period_id: Optional[int] = Field(
        None,
        description="Specific billing period (NULL = auto-select latest completed)"
    )
    recipients: List[RecipientInfo] = Field(
        default_factory=list,
        description="Email recipients for report delivery"
    )
    delivery_method: DeliveryMethod = Field(
        DeliveryMethod.EMAIL,
        description="How to deliver the report"
    )
    s3_destination: Optional[str] = Field(None, description="S3 path for delivery")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Monthly Invoice Report",
                "template_id": 1,
                "report_frequency": "monthly",
                "day_of_month": 1,
                "time_of_day": "06:00:00",
                "timezone": "America/New_York",
                "recipients": [
                    {"email": "finance@example.com", "name": "Finance Team"}
                ],
                "delivery_method": "email"
            }
        }
    )


class UpdateScheduleRequest(BaseModel):
    """Request to update a scheduled report."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    report_frequency: Optional[ReportFrequency] = None
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    time_of_day: Optional[time] = None
    timezone: Optional[str] = None
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    billing_period_id: Optional[int] = None
    recipients: Optional[List[RecipientInfo]] = None
    delivery_method: Optional[DeliveryMethod] = None
    s3_destination: Optional[str] = None
    is_active: Optional[bool] = None


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class ReportTemplateResponse(BaseModel):
    """Response model for report template."""

    id: int
    organization_id: int
    project_id: Optional[int]
    name: str
    description: Optional[str]
    report_type: InvoiceReportType
    file_format: FileFormat
    template_config: Dict[str, Any]
    include_charts: bool
    include_summary: bool
    include_line_items: bool
    default_contract_id: Optional[int]
    logo_path: Optional[str]
    header_text: Optional[str]
    footer_text: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GeneratedReportResponse(BaseModel):
    """Response model for generated report."""

    id: int
    organization_id: int
    report_template_id: Optional[int] = None
    scheduled_report_id: Optional[int] = None
    generation_source: GenerationSource = GenerationSource.ON_DEMAND
    report_type: InvoiceReportType
    name: str
    report_status: ReportStatus = Field(..., alias="report_status")
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    billing_period_id: Optional[int] = None
    file_format: FileFormat
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    download_url: Optional[str] = Field(None, description="Presigned S3 download URL")
    record_count: Optional[int] = None
    summary_data: Optional[Dict[str, Any]] = None
    download_count: int = 0
    processing_time_ms: Optional[int] = None
    processing_error: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ScheduledReportResponse(BaseModel):
    """Response model for scheduled report."""

    id: int
    organization_id: int
    report_template_id: int
    name: str
    report_frequency: ReportFrequency
    day_of_month: Optional[int]
    time_of_day: time
    timezone: str
    project_id: Optional[int]
    contract_id: Optional[int]
    billing_period_id: Optional[int]
    recipients: List[Dict[str, Any]]
    delivery_method: DeliveryMethod
    s3_destination: Optional[str]
    is_active: bool
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    last_run_status: Optional[ReportStatus]
    last_run_error: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# INTERNAL MODELS
# =============================================================================

class InvoiceLineItem(BaseModel):
    """Represents a single line item from an invoice."""

    id: int
    description: Optional[str]
    quantity: Optional[Decimal]
    unit_price: Optional[Decimal]
    total_amount: Optional[Decimal]
    line_item_type: Optional[str]
    meter_aggregate_id: Optional[int]
    metered_value: Optional[Decimal]
    unit: Optional[str]


class InvoiceHeader(BaseModel):
    """Represents an invoice header."""

    id: int
    invoice_number: Optional[str]
    billing_period_id: Optional[int]
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    total_amount: Optional[Decimal]
    status: Optional[str]
    contract_id: Optional[int]
    contract_name: Optional[str]
    project_id: Optional[int]
    project_name: Optional[str]
    invoice_date: Optional[datetime]
    due_date: Optional[datetime]
    received_date: Optional[datetime]


class BillingPeriodInfo(BaseModel):
    """Billing period information for reports."""

    id: int
    start_date: datetime
    end_date: datetime


class ExtractedDataMetadata(BaseModel):
    """Metadata about extracted invoice data."""

    total_amount: Optional[Decimal] = None
    record_count: int = 0
    contract_names: List[str] = Field(default_factory=list)
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExtractedData(BaseModel):
    """
    Container for extracted invoice data.

    Used internally by extractors to pass data to formatters.
    """

    report_type: InvoiceReportType
    headers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Invoice header records"
    )
    line_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Invoice line item records with header_id reference"
    )
    billing_period: Optional[BillingPeriodInfo] = Field(
        None,
        description="Billing period information"
    )
    metadata: ExtractedDataMetadata = Field(
        default_factory=ExtractedDataMetadata,
        description="Summary statistics about the extracted data"
    )
    # For comparison reports
    comparison_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Variance/comparison data for invoice_comparison reports"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "report_type": "invoice_to_client",
                "headers": [
                    {
                        "id": 1,
                        "invoice_number": "INV-2024-001",
                        "total_amount": "15000.00",
                        "contract_name": "Solar PPA - Project Alpha"
                    }
                ],
                "line_items": [
                    {
                        "id": 1,
                        "invoice_header_id": 1,
                        "description": "Energy Generation",
                        "quantity": "1500.50",
                        "line_total_amount": "12000.00"
                    }
                ],
                "billing_period": {
                    "id": 12,
                    "start_date": "2024-01-01T00:00:00Z",
                    "end_date": "2024-01-31T23:59:59Z"
                },
                "metadata": {
                    "total_amount": "15000.00",
                    "record_count": 1,
                    "contract_names": ["Solar PPA - Project Alpha"]
                }
            }
        }
    )


class ReportConfig(BaseModel):
    """
    Merged configuration for report generation.

    Combines template defaults with request-time overrides.
    """

    template_id: int
    report_type: InvoiceReportType
    file_format: FileFormat
    billing_period_id: int
    organization_id: int
    contract_id: Optional[int] = None
    project_id: Optional[int] = None

    # Template config options
    include_charts: bool = True
    include_summary: bool = True
    include_line_items: bool = True
    template_config: Dict[str, Any] = Field(default_factory=dict)

    # Branding
    logo_path: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": 1,
                "report_type": "invoice_to_client",
                "file_format": "pdf",
                "billing_period_id": 12,
                "organization_id": 1,
                "contract_id": 5,
                "include_charts": True,
                "include_summary": True,
                "include_line_items": True,
                "template_config": {
                    "include_meter_summary": True
                }
            }
        }
    )


# =============================================================================
# LIST RESPONSE MODELS
# =============================================================================

class ReportTemplateListResponse(BaseModel):
    """Paginated list of report templates."""

    items: List[ReportTemplateResponse]
    total: int
    limit: int
    offset: int


class GeneratedReportListResponse(BaseModel):
    """Paginated list of generated reports."""

    items: List[GeneratedReportResponse]
    total: int
    limit: int
    offset: int


class ScheduledReportListResponse(BaseModel):
    """Paginated list of scheduled reports."""

    items: List[ScheduledReportResponse]
    total: int
    limit: int
    offset: int
