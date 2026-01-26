"""
Pydantic models for the contract compliance system.

This module exports all data models used for contract processing,
PII detection, clause extraction, rules engine evaluation, and report generation.
"""

from .contract import (
    PIIEntity,
    AnonymizedResult,
    ExtractedClause,
    ContractParseResult,
    RuleResult,
    RuleEvaluationResult,
)

from .reports import (
    # Enums
    InvoiceReportType,
    FileFormat,
    ReportFrequency,
    ReportStatus,
    GenerationSource,
    DeliveryMethod,
    # Request models
    GenerateReportRequest,
    CreateTemplateRequest,
    UpdateTemplateRequest,
    CreateScheduleRequest,
    UpdateScheduleRequest,
    RecipientInfo,
    # Response models
    ReportTemplateResponse,
    GeneratedReportResponse,
    ScheduledReportResponse,
    ReportTemplateListResponse,
    GeneratedReportListResponse,
    ScheduledReportListResponse,
    # Internal models
    ExtractedData,
    ReportConfig,
    BillingPeriodInfo,
    ExtractedDataMetadata,
)

__all__ = [
    # Contract models
    "PIIEntity",
    "AnonymizedResult",
    "ExtractedClause",
    "ContractParseResult",
    "RuleResult",
    "RuleEvaluationResult",
    # Report enums
    "InvoiceReportType",
    "FileFormat",
    "ReportFrequency",
    "ReportStatus",
    "GenerationSource",
    "DeliveryMethod",
    # Report request models
    "GenerateReportRequest",
    "CreateTemplateRequest",
    "UpdateTemplateRequest",
    "CreateScheduleRequest",
    "UpdateScheduleRequest",
    "RecipientInfo",
    # Report response models
    "ReportTemplateResponse",
    "GeneratedReportResponse",
    "ScheduledReportResponse",
    "ReportTemplateListResponse",
    "GeneratedReportListResponse",
    "ScheduledReportListResponse",
    # Report internal models
    "ExtractedData",
    "ReportConfig",
    "BillingPeriodInfo",
    "ExtractedDataMetadata",
]
