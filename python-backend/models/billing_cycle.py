"""
Pydantic models for the billing cycle orchestrator and compute services.

Includes models for:
- Tariff rate generation requests
- Plant performance computation requests
- Billing cycle orchestration requests and results
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GenerateTariffRatesRequest(BaseModel):
    """Request body for POST /api/projects/{id}/billing/generate-tariff-rates."""
    billing_month: str = Field(..., description="YYYY-MM format")
    operating_year: Optional[int] = Field(None, description="Override operating year (auto-derived from COD if omitted)")
    force_refresh: bool = Field(False, description="Recompute even if tariff rates already exist")


class ComputePerformanceRequest(BaseModel):
    """Request body for POST /api/projects/{id}/plant-performance/compute."""
    billing_month: str = Field(..., description="YYYY-MM format")


class RunCycleRequest(BaseModel):
    """Request body for POST /api/projects/{id}/billing/run-cycle."""
    billing_month: str = Field(..., description="YYYY-MM format")
    force_refresh: bool = Field(False, description="Recompute all steps even if data exists")
    invoice_direction: str = Field("payable", description="'payable' or 'receivable'")


class BillingCycleStepResult(BaseModel):
    """Result of a single step in the billing cycle."""
    step: str
    status: str  # "verified", "computed", "generated", "missing", "skipped", "error"
    detail: Optional[Dict[str, Any]] = None


class BillingCycleResult(BaseModel):
    """Result of a full billing cycle run."""
    success: bool
    project_id: int
    billing_month: str
    steps: List[BillingCycleStepResult] = []
    blocked_at: Optional[str] = None
