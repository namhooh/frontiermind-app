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
    """Identifiers that may be absent from source files. Override > Excel auto-extract."""
    external_project_id: Optional[str] = Field(None, description="e.g. GH 22015")
    external_contract_id: Optional[str] = Field(None, description="CBE contract management ID, e.g. CONGHA00-2025-00005")


# =============================================================================
# EXCEL PARSED DATA
# =============================================================================

class ContactData(BaseModel):
    role: Optional[str] = None
    include_in_invoice: bool = False
    escalation_only: bool = False
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
    external_project_id: Optional[str] = None
    external_contract_id: Optional[str] = None
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
    contract_service_type: Optional[str] = None  # "Contract Service/Product Type" → tariff_type
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

    # Billing product
    product_to_be_billed: Optional[str] = None
    product_to_be_billed_list: List[str] = Field(default_factory=list)

    # Multi-value service types (rows 27-28: Contract Service/Product Type 1/2)
    contract_service_types: List[str] = Field(default_factory=list)

    # Additional rate fields for non-energy service types
    equipment_rental_rate: Optional[float] = None
    bess_fee: Optional[float] = None
    loan_repayment_value: Optional[float] = None

    # Escalation detail fields
    billing_frequency: Optional[str] = None
    escalation_frequency: Optional[str] = None
    escalation_start_date: Optional[date] = None
    tariff_components_to_adjust: Optional[str] = None

    # Contract flags (wired to existing DB columns)
    ppa_confirmed_uploaded: Optional[bool] = None
    has_amendments: Optional[bool] = None

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
    pricing_formula_text: Optional[str] = None
    confidence: float = 0.0


class ShortfallExtraction(BaseModel):
    formula_type: Optional[str] = None
    annual_cap_amount: Optional[float] = None
    annual_cap_currency: Optional[str] = None
    fx_rule: Optional[str] = None
    excused_events: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class GRPExtraction(BaseModel):
    exclude_vat: Optional[bool] = None
    exclude_demand_charges: Optional[bool] = None
    exclude_savings_charges: Optional[bool] = None
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    calculation_due_days: Optional[int] = None
    verification_deadline_days: Optional[int] = None
    confidence: float = 0.0


class DefaultRateExtraction(BaseModel):
    benchmark: Optional[str] = None  # SOFR, LIBOR, PRIME, CBR
    spread_pct: Optional[float] = None  # e.g. 2.0 for 2%
    accrual_method: Optional[str] = None  # PRO_RATA_DAILY, SIMPLE_ANNUAL
    fx_indemnity: Optional[bool] = None


class AvailableEnergyVariable(BaseModel):
    symbol: str
    definition: str
    unit: Optional[str] = None


class AvailableEnergyExtraction(BaseModel):
    method: Optional[str] = None
    formula: Optional[str] = None
    irradiance_threshold_wm2: Optional[float] = None
    interval_minutes: Optional[int] = None
    variables: List[AvailableEnergyVariable] = Field(default_factory=list)


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

    # GRP
    grp: Optional[GRPExtraction] = None

    # Payment
    payment_terms: Optional[str] = None
    default_interest_rate: Optional[float] = None
    default_rate: Optional[DefaultRateExtraction] = None
    payment_security_type: Optional[str] = None
    payment_security_amount: Optional[float] = None

    # Available energy / metering (structured)
    available_energy: Optional[AvailableEnergyExtraction] = None
    # Legacy flat fields (backward compat)
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
    payment_terms: Optional[str] = None
    ppa_confirmed_uploaded: Optional[bool] = None
    has_amendments: Optional[bool] = None

    # Tariff lines
    tariff_lines: List[Dict[str, Any]] = Field(default_factory=list)

    # Shortfall (from PPA)
    shortfall_formula_type: Optional[str] = None
    shortfall_cap_usd: Optional[float] = None
    shortfall_cap_currency: Optional[str] = None
    shortfall_cap_fx_rule: Optional[str] = None
    shortfall_excused_events: List[str] = Field(default_factory=list)

    # Contract extraction metadata (from PPA)
    extraction_metadata: Dict[str, Any] = Field(default_factory=dict)

    # Billing products (Sage product codes)
    billing_products: List[str] = Field(default_factory=list)

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


# =============================================================================
# STRUCTURED SOURCE DATA (Excel-first cross-examination pipeline)
# =============================================================================

class SAGEContractLine(BaseModel):
    """A single contract line from SAGE ERP."""
    contract_line_unique_id: str
    contract_number: str
    contract_line: int
    product_desc: str
    product_code: Optional[str] = None
    metered_available: Optional[str] = None
    quantity_unit: Optional[str] = None
    active_status: int = 1
    effective_start_date: Optional[date] = None
    effective_end_date: Optional[date] = None
    price_adjust_date: Optional[date] = None
    ind_use_cpi_inflation: int = 0
    energy_category: Optional[str] = None  # metered_energy | available_energy | non_energy


class SAGEMeterReading(BaseModel):
    """A single meter reading row from SAGE ERP."""
    meter_reading_unique_id: str
    customer_number: str
    facility: str
    bill_date: date
    contract_number: str
    contract_line: int
    product_desc: str
    metered_available: Optional[str] = None
    utilized_reading: float = 0.0
    discount_reading: float = 0.0
    sourced_energy: float = 0.0
    opening_reading: Optional[float] = None
    closing_reading: Optional[float] = None
    contract_currency: Optional[str] = None


class SAGEProjectData(BaseModel):
    """All SAGE ERP data for a single project, keyed by sage_id."""
    sage_id: str
    customer_number: str
    customer_name: Optional[str] = None
    country: Optional[str] = None

    # Contract-level from dim_finance_contract
    contracts: List[Dict[str, Any]] = Field(default_factory=list)
    primary_contract_number: Optional[str] = None
    contract_currency: Optional[str] = None
    payment_terms: Optional[str] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    contract_category: Optional[str] = None  # KWH, RENTAL, OM

    # Contract lines
    contract_lines: List[SAGEContractLine] = Field(default_factory=list)

    # Meter readings
    meter_readings: List[SAGEMeterReading] = Field(default_factory=list)

    # Product codes (unique set)
    product_codes: List[str] = Field(default_factory=list)

    # Flags
    has_cpi_inflation: bool = False


class RevenueMasterfileProject(BaseModel):
    """Tariff parameters for a single project from the Revenue Masterfile."""
    project_name: Optional[str] = None
    sage_id: Optional[str] = None
    currency: Optional[str] = None
    cod_date: Optional[date] = None
    term_years: Optional[int] = None
    base_rate: Optional[float] = None
    current_rate: Optional[float] = None
    rate_series: Dict[int, float] = Field(
        default_factory=dict,
        description="Year offset (1-based) → rate value from Inp_Proj year series"
    )
    discount_pct: Optional[float] = None
    floor_rate: Optional[float] = None
    ceiling_rate: Optional[float] = None
    escalation_type: Optional[str] = None
    escalation_value: Optional[float] = None
    formula_type: Optional[str] = None  # FIXED, FLOATING_GRID, FLOATING_GENERATOR


class RevenueMasterfileData(BaseModel):
    """All data extracted from the Revenue Masterfile (.xlsb)."""
    projects: Dict[str, RevenueMasterfileProject] = Field(
        default_factory=dict, description="Keyed by sage_id"
    )
    us_cpi_rates: Dict[int, float] = Field(
        default_factory=dict, description="Year -> CPI rate"
    )
    grid_gen_costs: Dict[str, Dict[int, float]] = Field(
        default_factory=dict, description="sage_id -> {year: reference_price}"
    )
    fx_rates: Dict[str, Dict[int, float]] = Field(
        default_factory=dict, description="currency_pair -> {year: rate}"
    )


class PlantPerformanceMonthly(BaseModel):
    """Monthly performance data from the Plant Performance Workbook."""
    month: date
    metered_energy_kwh: Optional[float] = None
    available_energy_kwh: Optional[float] = None
    ghi_kwh_m2: Optional[float] = None
    poa_kwh_m2: Optional[float] = None
    performance_ratio_pct: Optional[float] = None
    availability_pct: Optional[float] = None


class TechnicalModelRow(BaseModel):
    """One month from the Technical Model section of the Plant Performance Workbook."""
    month: date
    operating_year: int
    # Forecast
    forecast_energy_phase1_kwh: Optional[float] = None
    forecast_energy_phase2_kwh: Optional[float] = None
    forecast_energy_combined_kwh: Optional[float] = None
    forecast_ghi_wm2: Optional[float] = None
    forecast_poa_wm2: Optional[float] = None
    forecast_pr: Optional[float] = None
    # Actuals — per phase
    phase1_meter_opening: Optional[float] = None
    phase1_meter_closing: Optional[float] = None
    phase1_invoiced_kwh: Optional[float] = None
    phase2_meter_opening: Optional[float] = None
    phase2_meter_closing: Optional[float] = None
    phase2_invoiced_kwh: Optional[float] = None
    # Actuals — aggregated
    total_metered_kwh: Optional[float] = None
    available_energy_kwh: Optional[float] = None
    total_energy_kwh: Optional[float] = None
    actual_ghi_wm2: Optional[float] = None
    actual_poa_wm2: Optional[float] = None
    actual_pr: Optional[float] = None
    actual_availability_pct: Optional[float] = None
    # Derived
    energy_comparison: Optional[float] = None
    irr_comparison: Optional[float] = None
    pr_comparison: Optional[float] = None
    comments: Optional[str] = None


class PlantPerformanceData(BaseModel):
    """All data extracted from the Plant Performance Workbook."""
    projects: Dict[str, List[PlantPerformanceMonthly]] = Field(
        default_factory=dict, description="sage_id -> monthly time-series"
    )
    technical_model: Dict[str, List[TechnicalModelRow]] = Field(
        default_factory=dict, description="sage_id -> technical model time-series"
    )
    site_parameters: Dict[str, dict] = Field(
        default_factory=dict, description="sage_id -> {capacity_kwp, degradation_pct, ...}"
    )
    tab_to_sage_id: Dict[str, str] = Field(
        default_factory=dict, description="Tab name -> sage_id mapping used"
    )


class MarketRefPricingProject(BaseModel):
    """Market reference pricing summary for a project."""
    sage_id: Optional[str] = None
    project_name: Optional[str] = None
    tariff_summary: Dict[str, Any] = Field(default_factory=dict)
    reference_prices: Dict[str, float] = Field(
        default_factory=dict, description="period -> price"
    )


class MarketRefPricingData(BaseModel):
    """All data from the Market Ref Pricing workbook."""
    projects: Dict[str, MarketRefPricingProject] = Field(
        default_factory=dict, description="Keyed by sage_id"
    )
    po_summary: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# CROSS-VERIFICATION MODELS
# =============================================================================

class FieldVerification(BaseModel):
    """Verification result for a single field."""
    field_name: str
    primary_source: str
    primary_value: Any = None
    verification_sources: Dict[str, Any] = Field(
        default_factory=dict, description="source_name -> value"
    )
    confidence: float = 0.75
    status: Literal["confirmed", "warning", "conflict", "single_source"] = "single_source"
    variance_pct: Optional[float] = None
    notes: str = ""
    requires_manual_approval: bool = False


class TariffTypeResult(BaseModel):
    """Result of tariff type detection."""
    energy_sale_type_id: Optional[str] = None  # FIXED_SOLAR, FLOATING_GRID, etc.
    escalation_type_id: Optional[str] = None   # NONE, PERCENTAGE, US_CPI, etc.
    formula_type: Optional[str] = None         # For logic_parameters
    grp_method: Optional[str] = None           # GRP calculation method for tariff engine
    signals: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.75


class MotherChildPattern(BaseModel):
    """Detection result for mother-child line decomposition."""
    pattern: Literal["single_meter", "mother_children", "multi_phase"]
    mother_line_number: Optional[int] = None
    child_line_numbers: List[int] = Field(default_factory=list)
    notes: str = ""


class CrossVerificationResult(BaseModel):
    """Full cross-verification result for a project — extends DiscrepancyReport."""
    sage_id: str
    project_name: Optional[str] = None

    # Field-level verification
    field_verifications: List[FieldVerification] = Field(default_factory=list)

    # Tariff detection
    tariff_type: Optional[TariffTypeResult] = None

    # Mother-child decomposition
    line_decomposition: Optional[MotherChildPattern] = None

    # Overall confidence (average of field confidences)
    overall_confidence: float = 0.0

    # Merged best-values for DB population
    merged_values: Dict[str, Any] = Field(default_factory=dict)

    # Discrepancies (extends DiscrepancyReport format)
    discrepancies: List[Discrepancy] = Field(default_factory=list)
    critical_conflicts: List[str] = Field(default_factory=list)
    blocked: bool = False  # True if critical-field conflict blocks auto-population

    # Source data references
    sage_data: Optional[SAGEProjectData] = None
    masterfile_data: Optional[RevenueMasterfileProject] = None

    # Provenance
    source_metadata: Dict[str, Any] = Field(default_factory=dict)


class PDFValidationField(BaseModel):
    """Single field comparison between DB (Excel) and PPA (PDF)."""
    field_name: str
    db_value: Any = None
    pdf_value: Any = None
    tolerance: Optional[float] = None
    within_tolerance: bool = True
    notes: str = ""


class PDFValidationResult(BaseModel):
    """Result of comparing DB-populated values against PPA extraction."""
    sage_id: str
    contract_id: Optional[int] = None
    status: Literal["confirmed", "discrepancy_found", "pdf_failed"] = "pdf_failed"
    comparisons: List[PDFValidationField] = Field(default_factory=list)
    enrichments: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
