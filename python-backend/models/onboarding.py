"""
Pydantic models for the project onboarding system.

Covers Excel parsing, PPA extraction, discrepancy reporting,
and the preview/commit API workflow.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# OVERRIDES (required fields that may be missing from source files)
# =============================================================================

class OnboardingOverrides(BaseModel):
    """Required identifiers that may be absent from source files."""
    external_project_id: str = Field(..., description="e.g. GH-MOH01")
    external_contract_id: str = Field(..., description="e.g. GH-MOH01-PPA-001")


# =============================================================================
# EXCEL PARSED DATA
# =============================================================================

class ContactData(BaseModel):
    role: Optional[str] = None
    include_in_invoice: bool = False
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class MeterData(BaseModel):
    serial_number: str
    location_description: Optional[str] = None
    metering_type: Optional[str] = None
    is_billing_meter: bool = True


class AssetData(BaseModel):
    asset_type_code: str
    asset_name: Optional[str] = None
    model: Optional[str] = None
    serial_code: Optional[str] = None
    capacity: Optional[float] = None
    capacity_unit: Optional[str] = None
    quantity: int = 1


class ForecastMonthData(BaseModel):
    forecast_month: date
    operating_year: Optional[int] = None
    forecast_energy_kwh: float
    forecast_ghi: Optional[float] = None
    forecast_poa: Optional[float] = None
    forecast_pr: Optional[float] = None
    degradation_factor: Optional[float] = None
    forecast_source: str = "p50"
    source_metadata: Dict[str, Any] = Field(default_factory=dict)


class ExcelOnboardingData(BaseModel):
    """All data parsed from the Excel onboarding template."""
    # Project info
    project_name: Optional[str] = None
    country: Optional[str] = None
    sage_id: Optional[str] = None
    cod_date: Optional[date] = None
    installed_dc_capacity_kwp: Optional[float] = None
    installed_ac_capacity_kw: Optional[float] = None
    installation_location_url: Optional[str] = None

    # Customer info
    customer_name: Optional[str] = None
    registered_name: Optional[str] = None
    registration_number: Optional[str] = None
    tax_pin: Optional[str] = None
    registered_address: Optional[str] = None
    customer_email: Optional[str] = None
    customer_country: Optional[str] = None

    # Contract info
    contract_name: Optional[str] = None
    contract_type_code: str = "PPA"
    contract_term_years: Optional[int] = None
    effective_date: Optional[date] = None
    end_date: Optional[date] = None
    interconnection_voltage_kv: Optional[float] = None
    payment_security_required: Optional[bool] = None
    payment_security_details: Optional[str] = None
    agreed_fx_rate_source: Optional[str] = None

    # Tariff info
    tariff_structure: Optional[str] = None
    energy_sale_type: Optional[str] = None
    escalation_type: Optional[str] = None
    billing_currency: Optional[str] = None
    market_ref_currency: Optional[str] = None
    base_rate: Optional[float] = None
    unit: Optional[str] = None
    discount_pct: Optional[float] = None
    floor_rate: Optional[float] = None
    ceiling_rate: Optional[float] = None
    escalation_value: Optional[float] = None
    grp_method: Optional[str] = None
    payment_terms: Optional[str] = None

    # Nested collections
    contacts: List[ContactData] = Field(default_factory=list)
    meters: List[MeterData] = Field(default_factory=list)
    assets: List[AssetData] = Field(default_factory=list)
    forecasts: List[ForecastMonthData] = Field(default_factory=list)


# =============================================================================
# PPA EXTRACTED DATA
# =============================================================================

class GuaranteeYearRow(BaseModel):
    operating_year: int
    preliminary_yield_kwh: Optional[float] = None
    required_output_kwh: float
    confidence: float = 1.0


class EscalationRule(BaseModel):
    component: str  # "min_solar_price" | "max_solar_price" | "base_tariff"
    escalation_type: str  # "FIXED" | "NONE"
    escalation_value: Optional[float] = None
    start_year: int = 1


class TariffExtraction(BaseModel):
    solar_discount_pct: Optional[float] = None
    floor_rate: Optional[float] = None
    ceiling_rate: Optional[float] = None
    escalation_rules: List[EscalationRule] = Field(default_factory=list)
    confidence: float = 0.0


class ShortfallExtraction(BaseModel):
    formula_type: Optional[str] = None
    annual_cap_amount: Optional[float] = None
    annual_cap_currency: Optional[str] = None
    fx_rule: Optional[str] = None
    excused_events: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class PPAContractData(BaseModel):
    """All data extracted from the PPA PDF."""
    # Core terms
    contract_term_years: Optional[int] = None
    extension_provisions: Optional[str] = None
    initial_term_years: Optional[int] = None
    effective_date: Optional[date] = None

    # Tariff
    tariff: Optional[TariffExtraction] = None

    # Production guarantee table
    guarantee_table: List[GuaranteeYearRow] = Field(default_factory=list)

    # Shortfall
    shortfall: Optional[ShortfallExtraction] = None

    # Payment
    payment_terms: Optional[str] = None
    default_interest_rate: Optional[float] = None
    payment_security_type: Optional[str] = None
    payment_security_amount: Optional[float] = None

    # Available energy / metering
    available_energy_method: Optional[str] = None
    irradiance_threshold: Optional[float] = None
    interval_minutes: Optional[int] = None

    # FX
    agreed_exchange_rate_definition: Optional[str] = None

    # Early termination
    early_termination_schedule: Optional[str] = None

    # Per-field confidence (LLM-extracted values)
    confidence_scores: Dict[str, float] = Field(default_factory=dict)

    # Raw source metadata
    source_metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# DISCREPANCY REPORT
# =============================================================================

class Discrepancy(BaseModel):
    field: str
    excel_value: Any = None
    pdf_value: Any = None
    severity: Literal["error", "warning", "info"] = "info"
    explanation: str = ""
    recommended_value: Any = None
    recommended_source: Literal["excel", "pdf", "computed", "override"] = "excel"
    requires_manual_review: bool = False


class DiscrepancyReport(BaseModel):
    discrepancies: List[Discrepancy] = Field(default_factory=list)
    low_confidence_extractions: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""


# =============================================================================
# MERGED DATA (for staging table population)
# =============================================================================

class MergedOnboardingData(BaseModel):
    """Merged and validated data ready for staging table insertion."""
    # Identifiers
    organization_id: int
    external_project_id: str
    external_contract_id: str

    # Project
    project_name: str
    country: Optional[str] = None
    sage_id: Optional[str] = None
    cod_date: Optional[date] = None
    installed_dc_capacity_kwp: Optional[float] = None
    installed_ac_capacity_kw: Optional[float] = None
    installation_location_url: Optional[str] = None

    # Counterparty
    customer_name: Optional[str] = None
    registered_name: Optional[str] = None
    registration_number: Optional[str] = None
    tax_pin: Optional[str] = None
    registered_address: Optional[str] = None
    customer_email: Optional[str] = None
    customer_country: Optional[str] = None

    # Contract
    contract_name: Optional[str] = None
    contract_type_code: str = "PPA"
    contract_term_years: Optional[int] = None
    effective_date: Optional[date] = None
    end_date: Optional[date] = None
    interconnection_voltage_kv: Optional[float] = None
    payment_security_required: bool = False
    payment_security_details: Optional[str] = None
    agreed_fx_rate_source: Optional[str] = None

    # Tariff lines
    tariff_lines: List[Dict[str, Any]] = Field(default_factory=list)

    # Collections
    contacts: List[ContactData] = Field(default_factory=list)
    meters: List[MeterData] = Field(default_factory=list)
    assets: List[AssetData] = Field(default_factory=list)
    forecasts: List[ForecastMonthData] = Field(default_factory=list)
    guarantees: List[GuaranteeYearRow] = Field(default_factory=list)

    # Source metadata
    source_file_hash: str = ""


# =============================================================================
# API REQUEST / RESPONSE MODELS
# =============================================================================

class OnboardingPreviewResponse(BaseModel):
    preview_id: UUID
    parsed_data: Dict[str, Any]
    discrepancy_report: DiscrepancyReport
    counts: Dict[str, int]


class OnboardingCommitRequest(BaseModel):
    preview_id: UUID
    overrides: Dict[str, Any] = Field(default_factory=dict)


class OnboardingCommitResponse(BaseModel):
    success: bool
    project_id: Optional[int] = None
    contract_id: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)
