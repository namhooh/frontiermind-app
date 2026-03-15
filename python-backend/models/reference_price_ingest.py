"""
Pydantic models for reference price external ingestion.

Canonical request model for POST /api/ingest/reference-prices.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReferencePriceEntry(BaseModel):
    """Single reference price entry in an API push request."""
    project_sage_id: str = Field(..., description="SAGE project identifier (e.g. 'MB01')")
    period_start: date = Field(..., description="First day of the billing period")
    observation_type: str = Field("monthly", description="'monthly' or 'annual'")
    operating_year: Optional[int] = Field(None, description="Contract operating year (auto-derived from COD if omitted)")
    total_variable_charges: Decimal = Field(..., description="Total variable energy charges from utility invoice")
    total_kwh_invoiced: Decimal = Field(..., description="Total kWh invoiced by utility")
    currency_code: str = Field(..., description="ISO 4217 currency code for variable charges (e.g. 'GHS')")
    source_document_path: Optional[str] = Field(None, description="S3 path or reference to source document")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class ReferencePriceBatchRequest(BaseModel):
    """Request body for POST /api/ingest/reference-prices."""
    entries: List[ReferencePriceEntry] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Array of reference price entries (max 500 per batch)",
    )
    source: str = Field("api", description="Source label for audit trail")


class ReferencePriceBatchResponse(BaseModel):
    """Response for reference price batch ingestion."""
    success: bool = True
    inserted: int = 0
    updated: int = 0
    rejected: int = 0
    errors: Optional[List[Dict[str, Any]]] = None
