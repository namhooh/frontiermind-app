"""
Pydantic models for Step 11P — Pricing & Tariff Extraction.

Nine structured extraction objects matching the Claude prompt schema,
plus DB storage models for tariff_formula and logic_parameters enrichment.

Formula type taxonomy (14 types across 5 categories):
  pricing:     MRP_BOUNDED, MRP_CALCULATION
  escalation:  PERCENTAGE_ESCALATION, FIXED_ESCALATION, CPI_ESCALATION, FLOOR_CEILING_ESCALATION
  energy:      ENERGY_OUTPUT, DEEMED_ENERGY, ENERGY_DEGRADATION, ENERGY_GUARANTEE, ENERGY_MULTIPHASE
  performance: SHORTFALL_PAYMENT, TAKE_OR_PAY
  billing:     FX_CONVERSION
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums (Python-side validation; VARCHAR in DB)
# =============================================================================

class FormulaType(str, Enum):
    # pricing
    MRP_BOUNDED = "MRP_BOUNDED"
    MRP_CALCULATION = "MRP_CALCULATION"
    # escalation
    PERCENTAGE_ESCALATION = "PERCENTAGE_ESCALATION"
    FIXED_ESCALATION = "FIXED_ESCALATION"
    CPI_ESCALATION = "CPI_ESCALATION"
    FLOOR_CEILING_ESCALATION = "FLOOR_CEILING_ESCALATION"
    # energy
    ENERGY_OUTPUT = "ENERGY_OUTPUT"
    DEEMED_ENERGY = "DEEMED_ENERGY"
    ENERGY_DEGRADATION = "ENERGY_DEGRADATION"
    ENERGY_GUARANTEE = "ENERGY_GUARANTEE"
    ENERGY_MULTIPHASE = "ENERGY_MULTIPHASE"
    # performance
    SHORTFALL_PAYMENT = "SHORTFALL_PAYMENT"
    TAKE_OR_PAY = "TAKE_OR_PAY"
    # billing
    FX_CONVERSION = "FX_CONVERSION"


class VariableType(str, Enum):
    RATE = "RATE"
    PRICE = "PRICE"
    ENERGY = "ENERGY"
    IRRADIANCE = "IRRADIANCE"
    PERCENTAGE = "PERCENTAGE"
    INDEX = "INDEX"
    CURRENCY = "CURRENCY"
    TIME = "TIME"
    CAPACITY = "CAPACITY"


class EscalationMethod(str, Enum):
    FIXED_INCREASE = "FIXED_INCREASE"
    PERCENTAGE = "PERCENTAGE"
    US_CPI = "US_CPI"
    WPI = "WPI"
    CUSTOM_INDEX = "CUSTOM_INDEX"
    NONE = "NONE"


class VariableRole(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    PARAMETER = "parameter"
    INTERMEDIATE = "intermediate"


class ScheduleType(str, Enum):
    EXPECTED_ANNUAL_ENERGY = "expected_annual_energy"
    GUARANTEED_ANNUAL_ENERGY = "guaranteed_annual_energy"
    MONTHLY_ENERGY = "monthly_energy"


# =============================================================================
# Shared Sub-Models
# =============================================================================

class RateValue(BaseModel):
    """A monetary rate with currency and unit."""
    value: float
    currency: str = "USD"
    unit: str = "per_kwh"


class FloorCeiling(BaseModel):
    """Floor or ceiling rate, optionally dual-currency with escalation."""
    contract_ccy: Optional[RateValue] = None
    local_ccy: Optional[RateValue] = None
    escalation: Optional[Dict[str, Any]] = None


class FormulaVariable(BaseModel):
    """A variable in a mathematical formula."""
    symbol: str
    role: VariableRole
    variable_type: Optional[VariableType] = None
    description: Optional[str] = ""
    unit: Optional[str] = None
    maps_to: Optional[str] = None  # DB column: table.column or tariff_formula.FORMULA_TYPE
    lookup_key: Optional[str] = None  # Temporal dimension: "billing_month", "operating_year", or null


class FormulaCondition(BaseModel):
    """A condition/threshold on a formula."""
    type: str  # e.g. 'threshold', 'time_window', 'excused_event'
    description: Optional[str] = ""
    threshold_value: Optional[float] = None
    threshold_unit: Optional[str] = None
    if_above: Optional[str] = None  # e.g. "Annual Minimum Offtake Guarantee"
    then: Optional[str] = None      # e.g. "metered_only"
    else_: Optional[str] = Field(default=None, alias="else")

    model_config = ConfigDict(populate_by_name=True)


# =============================================================================
# Object 1: Tariff Schedule
# =============================================================================

class YearRate(BaseModel):
    """A single year's rate in a year-by-year schedule."""
    year: int
    rate: float
    source: str = "explicit_table"  # explicit_table, calculated, interpolated


class TariffSchedule(BaseModel):
    """Core rate structure — base rate, year-by-year schedule, floor/ceiling."""
    base_rate: Optional[RateValue] = None
    escalation_type: Optional[EscalationMethod] = None
    escalation_params: Optional[Dict[str, Any]] = None
    year_by_year_rates: List[YearRate] = Field(default_factory=list)
    floor: Optional[FloorCeiling] = None
    ceiling: Optional[FloorCeiling] = None
    discount_pct: Optional[float] = None
    raw_text_refs: List[str] = Field(default_factory=list)


# =============================================================================
# Object 2: Pricing Formulas
# =============================================================================

class BillingEngineParams(BaseModel):
    """Billing engine configuration extracted from formula context."""
    available_energy_method: Optional[str] = None
    interval_minutes: Optional[int] = None
    irradiance_threshold_wm2: Optional[float] = None
    reference_period: Optional[str] = None


class MRPDefinition(BaseModel):
    """Market Reference Price scope definition."""
    included_components: List[str] = Field(default_factory=list)
    excluded_components: List[str] = Field(default_factory=list)
    time_window: Optional[Dict[str, str]] = None  # {start, end}
    verification_deadline_days: Optional[int] = None


class PricingFormula(BaseModel):
    """A decomposed mathematical formula from the contract."""
    formula_id: str
    formula_name: str
    formula_text: str
    formula_type: FormulaType
    variables: List[FormulaVariable] = Field(default_factory=list)
    operations: List[str] = Field(default_factory=list)
    conditions: List[FormulaCondition] = Field(default_factory=list)
    billing_engine_params: Optional[BillingEngineParams] = None
    mrp_definition: Optional[MRPDefinition] = None
    section_ref: Optional[str] = None


# =============================================================================
# Object 3: Energy Output Schedule
# =============================================================================

class EnergyOutputEntry(BaseModel):
    """A single year's expected/guaranteed energy output."""
    year: int
    kwh: float
    source: str = "annexure_table"


class WeatherAdjustment(BaseModel):
    """Weather adjustment method for energy guarantees."""
    method: str  # e.g. 'irradiance_corrected', 'none'
    description: Optional[str] = ""


class CureMechanism(BaseModel):
    """Shortfall cure mechanism."""
    allowed: bool = False
    window_years: Optional[int] = None
    description: Optional[str] = ""


class EnergyOutputSchedule(BaseModel):
    """Expected/guaranteed energy output by year with degradation."""
    schedule_type: ScheduleType = ScheduleType.EXPECTED_ANNUAL_ENERGY
    degradation_rate_pct_per_year: Optional[float] = None
    entries: List[EnergyOutputEntry] = Field(default_factory=list)
    guaranteed_percentage: Optional[float] = None
    guaranteed_basis: Optional[str] = None
    weather_adjustment: Optional[WeatherAdjustment] = None
    measurement_period: str = "annual"
    cure_mechanism: Optional[CureMechanism] = None
    section_ref: Optional[str] = None


# =============================================================================
# Object 4: Payment Mechanics
# =============================================================================

class CurrencyConfig(BaseModel):
    """Invoice currency and FX conversion parameters."""
    billing: str = "USD"
    local: Optional[str] = None
    fx_source: Optional[str] = None
    fx_determination_date: Optional[str] = None


class TakeOrPay(BaseModel):
    """Take-or-pay / minimum offtake parameters."""
    applies: bool = False
    minimum_offtake_pct: Optional[float] = None
    shortfall_rate_pct_of_tariff: Optional[float] = None


class OperatingYear(BaseModel):
    """Operating year definition."""
    definition: str = "cod_anniversary"  # cod_anniversary, calendar_year, fiscal_year
    start_date: Optional[str] = None
    start_month: Optional[int] = None
    note: Optional[str] = ""


class PaymentMechanics(BaseModel):
    """Invoice timing, FX conversion, take-or-pay, operating year definition."""
    billing_frequency: str = "monthly"
    invoice_timing_days_after_month_end: Optional[int] = None
    payment_due_days: Optional[int] = None
    currency: Optional[CurrencyConfig] = None
    take_or_pay: Optional[TakeOrPay] = None
    late_payment_interest_pct: Optional[float] = None
    operating_year: Optional[OperatingYear] = None
    section_refs: List[str] = Field(default_factory=list)


# =============================================================================
# Object 5: Escalation Rules
# =============================================================================

class CPIParams(BaseModel):
    """CPI/index-linked escalation parameters."""
    index_name: str = "CPI-U"
    reference_year: Optional[int] = None
    base_index_value: Optional[float] = None
    cap_pct: Optional[float] = None
    floor_pct: Optional[float] = None
    lag_months: Optional[int] = None
    adjustment_frequency: str = "annual"


class EscalationRule(BaseModel):
    """Per-component escalation rule."""
    component: str  # base_rate, floor_rate, ceiling_rate
    method: EscalationMethod
    annual_pct: Optional[float] = None
    annual_amount: Optional[float] = None
    currency: Optional[str] = None
    start_year: Optional[int] = None
    first_indexation_date: Optional[str] = None
    compound: bool = True
    cpi_params: Optional[CPIParams] = None


# =============================================================================
# Object 6: Definitions Registry
# =============================================================================

class ContractDefinition(BaseModel):
    """A contract-defined term that formulas reference."""
    term: str
    definition: str
    section_ref: Optional[str] = None


# =============================================================================
# Object 7: Shortfall Mechanics
# =============================================================================

class ShortfallMechanics(BaseModel):
    """Penalty/shortfall payment formulas, excused events, caps."""
    shortfall_formula_type: Optional[str] = None
    formula_text: Optional[str] = None
    formula_variables: List[FormulaVariable] = Field(default_factory=list)
    excused_events: List[str] = Field(default_factory=list)
    payment_cap: Optional[Dict[str, Any]] = None
    cure_mechanism: Optional[CureMechanism] = None
    measurement_period: str = "annual"
    weather_adjustment: Optional[WeatherAdjustment] = None
    section_refs: List[str] = Field(default_factory=list)


# =============================================================================
# Object 8: Deemed Energy Params
# =============================================================================

class DeemedEnergyParams(BaseModel):
    """Available/deemed energy calculation parameters for the billing engine."""
    available_energy_method: Optional[str] = None
    formula_text: Optional[str] = None
    formula_variables: List[FormulaVariable] = Field(default_factory=list)
    interval_minutes: Optional[int] = None
    irradiance_threshold_wm2: Optional[float] = None
    reference_period: Optional[str] = None
    excused_events: List[str] = Field(default_factory=list)
    section_refs: List[str] = Field(default_factory=list)


# =============================================================================
# Object 9: Energy Output Definition
# =============================================================================

class EnergyOutputDefinition(BaseModel):
    """Contractual Energy Output definition with conditional logic.

    Captures the if/then/else branching in Energy Output clauses:
    e.g. "if metered >= offtake guarantee, use metered only;
    else MIN(metered + available, guarantee)"

    Applies monthly and/or annually per contract terms.
    """
    formula_text: Optional[str] = None
    formula_variables: List[FormulaVariable] = Field(default_factory=list)
    operations: List[str] = Field(default_factory=list)  # IF, MIN, SUM, MAX
    conditions: List[FormulaCondition] = Field(default_factory=list)
    applies_monthly: bool = True
    applies_annually: bool = True
    section_ref: Optional[str] = None


# =============================================================================
# Composite: Full Extraction Result
# =============================================================================

class PricingExtractionResult(BaseModel):
    """Complete output from Phase 2 Claude extraction."""
    tariff_schedule: Optional[TariffSchedule] = None
    pricing_formulas: List[PricingFormula] = Field(default_factory=list)
    energy_output_schedule: Optional[EnergyOutputSchedule] = None
    payment_mechanics: Optional[PaymentMechanics] = None
    escalation_rules: List[EscalationRule] = Field(default_factory=list)
    definitions_registry: List[ContractDefinition] = Field(default_factory=list)
    shortfall_mechanics: Optional[ShortfallMechanics] = None
    deemed_energy_params: Optional[DeemedEnergyParams] = None
    energy_output_definition: Optional[EnergyOutputDefinition] = None

    # Extraction metadata
    extraction_confidence: Optional[float] = None
    sections_found: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# =============================================================================
# DB Storage Models
# =============================================================================

class TariffFormulaCreate(BaseModel):
    """Request model for creating a tariff_formula row."""
    clause_tariff_id: int
    organization_id: int
    formula_name: str
    formula_text: str
    formula_type: str
    variables: List[Dict[str, Any]] = Field(default_factory=list)
    operations: List[str] = Field(default_factory=list)
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    section_ref: Optional[str] = None
    extraction_confidence: Optional[float] = None
    extraction_metadata: Dict[str, Any] = Field(default_factory=dict)


class TariffFormulaResponse(BaseModel):
    """Response model for a tariff_formula row."""
    id: int
    clause_tariff_id: int
    organization_id: int
    formula_name: str
    formula_text: str
    formula_type: str
    variables: List[Dict[str, Any]]
    operations: List[str]
    conditions: List[Dict[str, Any]]
    section_ref: Optional[str] = None
    extraction_confidence: Optional[float] = None
    version: int
    is_current: bool

    model_config = ConfigDict(from_attributes=True)
