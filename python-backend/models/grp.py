"""
Pydantic models for GRP (Grid Reference Price) management endpoints.

Covers: listing observations, aggregation, verification, and admin upload.
Database Reference: migrations 033 + 037 (reference_price table).
"""

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# ENUMS
# =============================================================================

class VerificationStatus(str, Enum):
    JOINTLY_VERIFIED = "jointly_verified"
    DISPUTED = "disputed"
    ESTIMATED = "estimated"


class ObservationType(str, Enum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


# =============================================================================
# REQUEST MODELS
# =============================================================================

class AggregateGRPRequest(BaseModel):
    """Request to aggregate monthly observations into an annual GRP."""
    operating_year: int = Field(..., ge=1, description="Contract operating year to aggregate")
    include_pending: bool = Field(False, description="Include pending (unverified) observations")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operating_year": 2,
                "include_pending": False,
            }
        }
    )


class VerifyObservationRequest(BaseModel):
    """Request to verify or dispute a GRP observation."""
    verification_status: VerificationStatus = Field(
        ..., description="New status: jointly_verified, disputed, or estimated"
    )
    notes: Optional[str] = Field(None, max_length=2000, description="Verification notes")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "verification_status": "jointly_verified",
                "notes": "Verified against utility statement.",
            }
        }
    )


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class GRPObservation(BaseModel):
    """Single GRP observation (monthly or annual)."""
    id: int
    project_id: int
    operating_year: int
    period_start: date
    period_end: date
    observation_type: str
    calculated_grp_per_kwh: Optional[float] = None
    total_variable_charges: Optional[float] = None
    total_kwh_invoiced: Optional[float] = None
    verification_status: str
    verified_at: Optional[datetime] = None
    source_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GRPObservationListResponse(BaseModel):
    success: bool = True
    observations: List[GRPObservation]
    total: int


class AggregateGRPResponse(BaseModel):
    success: bool = True
    observation_id: int
    annual_grp_per_kwh: float
    operating_year: int
    months_included: int
    months_excluded: int
    total_variable_charges: float
    total_kwh_invoiced: float
    message: str


class VerifyObservationResponse(BaseModel):
    success: bool = True
    observation_id: int
    verification_status: str
    verified_at: Optional[datetime] = None
    message: str


class AdminUploadResponse(BaseModel):
    success: bool = True
    observation_id: int
    grp_per_kwh: float
    total_variable_charges: float
    total_kwh_invoiced: float
    line_items_count: int
    extraction_confidence: str
    message: str
