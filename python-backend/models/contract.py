"""
Pydantic models for contract processing, PII detection, and clause extraction.

These models define the data structures used throughout the contract
digitization pipeline.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Optional, Any
from datetime import datetime
from decimal import Decimal


class PIIEntity(BaseModel):
    """
    Represents a detected PII (Personally Identifiable Information) entity.

    Used by the PII detection service to identify sensitive information
    in contract text before sending to external APIs.
    """

    entity_type: str = Field(
        ...,
        description="Type of PII (EMAIL_ADDRESS, PHONE_NUMBER, PERSON, US_SSN, CREDIT_CARD, CONTRACT_ID, etc.)"
    )
    start: int = Field(..., description="Start position of PII in text", ge=0)
    end: int = Field(..., description="End position of PII in text", ge=0)
    score: float = Field(
        ..., description="Confidence score (0.0-1.0)", ge=0.0, le=1.0
    )
    text: str = Field(..., description="The actual PII text detected")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entity_type": "EMAIL_ADDRESS",
                "start": 42,
                "end": 65,
                "score": 0.95,
                "text": "john.smith@example.com",
            }
        }
    )


class AnonymizedResult(BaseModel):
    """
    Result of PII anonymization process.

    Contains the anonymized text with PII replaced by placeholders,
    along with metadata about what was detected and a mapping for
    potential re-identification.
    """

    anonymized_text: str = Field(
        ..., description="Text with PII replaced by placeholders like <EMAIL_REDACTED>"
    )
    pii_count: int = Field(..., description="Total number of PII entities detected", ge=0)
    entities_found: List[PIIEntity] = Field(
        default_factory=list, description="List of all PII entities detected"
    )
    mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of placeholders to original PII values (for authorized re-identification)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "anonymized_text": "Contact <EMAIL_REDACTED> at <PHONE_REDACTED>",
                "pii_count": 2,
                "entities_found": [
                    {
                        "entity_type": "EMAIL_ADDRESS",
                        "start": 8,
                        "end": 28,
                        "score": 0.95,
                        "text": "john@example.com",
                    }
                ],
                "mapping": {
                    "<EMAIL_ADDRESS_8_28>": "john@example.com",
                    "<PHONE_NUMBER_32_44>": "555-123-4567",
                },
            }
        }
    )


class ExtractedClause(BaseModel):
    """
    Represents a clause extracted from a contract.

    Used in contract parsing (Task 1.3) to store structured clause information.

    Updated January 2026: New fields for 13-category flat structure.
    - category/category_code replaces clause_type/clause_category
    - category_confidence and extraction_confidence added
    - suggested_category for UNIDENTIFIED clauses
    - notes field for extraction context
    """

    # New primary fields (January 2026)
    clause_id: Optional[str] = Field(None, description="Sequential ID (clause_001, clause_002)")
    clause_name: str = Field(..., description="Name/title of the clause")
    section_reference: str = Field(..., description="Section number or reference (e.g., '4.1')")

    # Category fields (new flat structure)
    category: Optional[str] = Field(
        None,
        description="Category code (AVAILABILITY, LIQUIDATED_DAMAGES, etc.) or UNIDENTIFIED"
    )
    category_code: Optional[str] = Field(
        None,
        description="Category code for database FK (null for UNIDENTIFIED)"
    )
    category_confidence: Optional[float] = Field(
        None,
        description="Confidence in category assignment (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    suggested_category: Optional[str] = Field(
        None,
        description="For UNIDENTIFIED clauses, the AI's best guess category"
    )

    # Content fields
    raw_text: str = Field(..., description="Original clause text")
    summary: Optional[str] = Field(None, description="Brief summary of the clause")
    responsible_party: str = Field(..., description="Party responsible for this clause")
    beneficiary_party: Optional[str] = Field(None, description="Beneficiary party, if applicable")
    normalized_payload: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Structured data for rules engine (thresholds, formulas, etc.)"
    )

    # Confidence and notes
    extraction_confidence: Optional[float] = Field(
        None,
        description="Confidence in extracted values (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    notes: Optional[str] = Field(None, description="Additional extraction notes")

    # DEPRECATED fields (kept for backward compatibility)
    clause_type: Optional[str] = Field(
        None,
        description="DEPRECATED: Use category instead. High-level type classification."
    )
    clause_category: Optional[str] = Field(
        None,
        description="DEPRECATED: Use category instead. Specific category."
    )
    confidence_score: Optional[float] = Field(
        None,
        description="DEPRECATED: Use extraction_confidence instead.",
        ge=0.0,
        le=1.0
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "clause_id": "clause_001",
                "clause_name": "Availability Guarantee",
                "section_reference": "4.1",
                "category": "AVAILABILITY",
                "category_code": "AVAILABILITY",
                "category_confidence": 0.95,
                "raw_text": "Seller shall ensure the Facility achieves a minimum annual Availability of 95%.",
                "summary": "Requires 95% annual availability",
                "responsible_party": "Seller",
                "beneficiary_party": "Buyer",
                "normalized_payload": {
                    "threshold_percent": 95.0,
                    "measurement_period": "annual",
                    "excused_events": ["force_majeure", "grid_curtailment"],
                },
                "extraction_confidence": 0.92,
                "notes": "Standard availability clause with annual measurement",
            }
        }
    )


class ExtractionSummary(BaseModel):
    """
    Summary of clause extraction results.

    Added January 2026: Provides metadata about the extraction process.
    """

    contract_type_detected: Optional[str] = Field(
        None, description="Detected contract type (PPA, O&M, EPC)"
    )
    total_clauses_extracted: int = Field(
        0, description="Total number of clauses extracted", ge=0
    )
    clauses_by_category: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of clauses per category"
    )
    unidentified_count: int = Field(
        0, description="Number of UNIDENTIFIED clauses", ge=0
    )
    average_confidence: Optional[float] = Field(
        None, description="Average extraction confidence (0.0-1.0)"
    )
    extraction_warnings: List[str] = Field(
        default_factory=list,
        description="Warnings about missing clauses or potential issues"
    )
    is_template: bool = Field(
        False, description="Whether contract appears to be a template (placeholder values)"
    )


class ContractParseResult(BaseModel):
    """
    Complete result of contract parsing pipeline.

    Returned by ContractParser.process_contract() (Task 1.3).

    Updated January 2026: Added extraction_summary field.
    """

    contract_id: int = Field(..., description="Database ID of stored contract")
    clauses: List[ExtractedClause] = Field(
        default_factory=list, description="List of extracted clauses"
    )
    extraction_summary: Optional[ExtractionSummary] = Field(
        None, description="Summary of extraction results (January 2026)"
    )
    pii_detected: int = Field(..., description="Number of PII entities detected", ge=0)
    pii_anonymized: int = Field(..., description="Number of PII entities anonymized", ge=0)
    processing_time: float = Field(
        ..., description="Total processing time in seconds", ge=0.0
    )
    status: str = Field(..., description="Processing status (success, failed, partial)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "contract_id": 1234,
                "clauses": [],
                "extraction_summary": {
                    "contract_type_detected": "PPA",
                    "total_clauses_extracted": 12,
                    "unidentified_count": 1,
                    "average_confidence": 0.85,
                },
                "pii_detected": 5,
                "pii_anonymized": 5,
                "processing_time": 12.34,
                "status": "success",
            }
        }
    )


class RuleResult(BaseModel):
    """
    Result of a single rule evaluation.

    Used by the rules engine (Task 3.1) to report default events and
    liquidated damages calculations.
    """

    breach: bool = Field(..., description="Whether a breach occurred")
    rule_type: str = Field(
        ..., description="Type of rule (AvailabilityRule, CapacityFactorRule, etc.)"
    )
    clause_id: int = Field(..., description="Database ID of the clause being evaluated")
    calculated_value: Optional[float] = Field(
        None, description="Calculated metric value (e.g., actual availability)"
    )
    threshold_value: Optional[float] = Field(
        None, description="Threshold from contract clause"
    )
    shortfall: Optional[float] = Field(
        None, description="Difference between threshold and actual"
    )
    ld_amount: Optional[Decimal] = Field(
        None, description="Liquidated damages amount calculated"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Additional calculation details and context"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "breach": True,
                "rule_type": "AvailabilityRule",
                "clause_id": 42,
                "calculated_value": 92.5,
                "threshold_value": 95.0,
                "shortfall": 2.5,
                "ld_amount": "125000.00",
                "details": {
                    "period": "2024-Q1",
                    "total_hours": 2160,
                    "outage_hours": 162,
                },
            }
        }
    )


class RuleEvaluationResult(BaseModel):
    """
    Complete result of rules engine evaluation for a period.

    Returned by RulesEngine.evaluate_period() (Task 3.1).
    """

    contract_id: int = Field(..., description="Database ID of contract")
    period_start: datetime = Field(..., description="Evaluation period start date")
    period_end: datetime = Field(..., description="Evaluation period end date")
    default_events: List[RuleResult] = Field(
        default_factory=list, description="List of detected default events"
    )
    ld_total: Decimal = Field(..., description="Total liquidated damages for period")
    notifications_generated: int = Field(
        ..., description="Number of notifications created", ge=0
    )
    processing_notes: List[str] = Field(
        default_factory=list,
        description="Notes about calculation process (excused events, data gaps, etc.)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "contract_id": 1234,
                "period_start": "2024-01-01T00:00:00Z",
                "period_end": "2024-03-31T23:59:59Z",
                "default_events": [],
                "ld_total": "250000.00",
                "notifications_generated": 2,
                "processing_notes": [
                    "Force majeure event on 2024-02-15 excluded from calculation"
                ],
            }
        }
    )
