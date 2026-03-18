"""
Phase 3 — Formula Decomposer for Step 11P.

Maps PricingExtractionResult → DB rows:
  - tariff_formula rows (computation graphs)
  - clause_tariff.logic_parameters enrichment (defensive merge)
  - tariff_rate rows (year-by-year explicit rates)
  - production_guarantee rows (energy output schedule)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models.pricing import (
    EscalationRule,
    FormulaType,
    PricingExtractionResult,
    PricingFormula,
    TariffFormulaCreate,
    VariableType,
)

log = logging.getLogger("step11p.formula_decomposer")


# =============================================================================
# Canonical variable → DB mapping
# =============================================================================

CANONICAL_MAPS_TO: Dict[str, Tuple[str, str]] = {
    # maps_to value → (table.column, VariableType)
    "clause_tariff.base_rate": ("clause_tariff.base_rate", "RATE"),
    "clause_tariff.logic_parameters.floor_rate": ("clause_tariff.logic_parameters.floor_rate", "RATE"),
    "clause_tariff.logic_parameters.ceiling_rate": ("clause_tariff.logic_parameters.ceiling_rate", "RATE"),
    "clause_tariff.logic_parameters.discount_pct": ("clause_tariff.logic_parameters.discount_pct", "PERCENTAGE"),
    "reference_price.calculated_mrp_per_kwh": ("reference_price.calculated_mrp_per_kwh", "PRICE"),
    "tariff_rate.effective_rate_contract_ccy": ("tariff_rate.effective_rate_contract_ccy", "RATE"),
    "meter_aggregate.total_production": ("meter_aggregate.total_production", "ENERGY"),
    "meter_aggregate.available_energy_kwh": ("meter_aggregate.available_energy_kwh", "ENERGY"),
    "meter_aggregate.ghi_irradiance_wm2": ("meter_aggregate.ghi_irradiance_wm2", "IRRADIANCE"),
    "production_forecast.forecast_energy_kwh": ("production_forecast.forecast_energy_kwh", "ENERGY"),
    "production_forecast.degradation_factor": ("production_forecast.degradation_factor", "PERCENTAGE"),
    "production_guarantee.guaranteed_kwh": ("production_guarantee.guaranteed_kwh", "ENERGY"),
    "production_guarantee.p50_annual_kwh": ("production_guarantee.p50_annual_kwh", "ENERGY"),
    "production_guarantee.guarantee_pct_of_p50": ("production_guarantee.guarantee_pct_of_p50", "PERCENTAGE"),
    "production_guarantee.minimum_offtake_kwh": ("production_guarantee.minimum_offtake_kwh", "ENERGY"),
    "price_index.index_value": ("price_index.index_value", "INDEX"),
    "exchange_rate.rate": ("exchange_rate.rate", "CURRENCY"),
    "project.capacity_kwp": ("project.capacity_kwp", "CAPACITY"),
    "clause_tariff.logic_parameters.performance_ratio_monthly": ("clause_tariff.logic_parameters.performance_ratio_monthly", "PERCENTAGE"),
    "meter_aggregate.performance_ratio": ("meter_aggregate.performance_ratio", "PERCENTAGE"),
}


# Temporal lookup rules: maps_to prefix → lookup_key
_TEMPORAL_LOOKUP: Dict[str, str] = {
    "meter_aggregate.": "billing_month",
    "reference_price.": "billing_month",
    "tariff_rate.": "billing_month",
    "production_guarantee.": "operating_year",
    "production_forecast.": "operating_year",
    "exchange_rate.": "billing_month",
    "price_index.": "operating_year",
}

# Static tables — no temporal lookup needed
_STATIC_PREFIXES = ("clause_tariff.", "project.", "invoice_line_item.", "tariff_formula.")


def _infer_lookup_key(maps_to: Optional[str]) -> Optional[str]:
    """Infer lookup_key from maps_to table prefix."""
    if not maps_to:
        return None
    for prefix, key in _TEMPORAL_LOOKUP.items():
        if maps_to.startswith(prefix):
            return key
    return None


def _infer_variable_type(maps_to: Optional[str]) -> Optional[str]:
    """Infer variable_type from maps_to using canonical mapping."""
    if not maps_to:
        return None
    entry = CANONICAL_MAPS_TO.get(maps_to)
    if entry:
        return entry[1]
    # Heuristic fallback
    lower = maps_to.lower()
    if "rate" in lower or "tariff" in lower:
        return "RATE"
    if "kwh" in lower or "energy" in lower or "production" in lower:
        return "ENERGY"
    if "pct" in lower or "percent" in lower or "factor" in lower:
        return "PERCENTAGE"
    if "irradiance" in lower:
        return "IRRADIANCE"
    if "index" in lower or "cpi" in lower:
        return "INDEX"
    if "fx" in lower or "exchange" in lower:
        return "CURRENCY"
    return None


def _formula_to_db_row(
    formula: PricingFormula,
    clause_tariff_id: int,
    organization_id: int,
    extraction_confidence: Optional[float] = None,
) -> TariffFormulaCreate:
    """Convert a PricingFormula extraction object to a TariffFormulaCreate."""
    # Enrich variables with variable_type and lookup_key where missing
    variables = []
    for v in formula.variables:
        var_dict = v.model_dump(by_alias=True)
        if not var_dict.get("variable_type") and var_dict.get("maps_to"):
            var_dict["variable_type"] = _infer_variable_type(var_dict["maps_to"])
        if not var_dict.get("lookup_key") and var_dict.get("maps_to"):
            # Only auto-infer as fallback — Claude should provide lookup_key
            var_dict["lookup_key"] = _infer_lookup_key(var_dict["maps_to"])
        variables.append(var_dict)

    return TariffFormulaCreate(
        clause_tariff_id=clause_tariff_id,
        organization_id=organization_id,
        formula_name=formula.formula_name,
        formula_text=formula.formula_text,
        formula_type=formula.formula_type.value if isinstance(formula.formula_type, FormulaType) else formula.formula_type,
        variables=variables,
        operations=formula.operations,
        conditions=[c.model_dump(by_alias=True) for c in formula.conditions],
        section_ref=formula.section_ref,
        extraction_confidence=extraction_confidence,
    )


# =============================================================================
# Synthesize additional formulas from non-formula extraction objects
# =============================================================================

def _synthesize_escalation_formulas(
    rules: List[EscalationRule],
    clause_tariff_id: int,
    organization_id: int,
) -> List[TariffFormulaCreate]:
    """Create tariff_formula rows from escalation rules."""
    formulas = []
    for rule in rules:
        if rule.method.value == "NONE":
            continue

        # Map escalation method to formula_type
        type_map = {
            "PERCENTAGE": "PERCENTAGE_ESCALATION",
            "FIXED_INCREASE": "FIXED_ESCALATION",
            "US_CPI": "CPI_ESCALATION",
            "WPI": "CPI_ESCALATION",
            "CUSTOM_INDEX": "CPI_ESCALATION",
        }
        formula_type = type_map.get(rule.method.value, "PERCENTAGE_ESCALATION")

        # Build formula text — use variable symbols, never hardcode values
        if rule.method.value == "PERCENTAGE":
            compound = "^" if rule.compound else "×"
            formula_text = f"Rate_N = base × (1 + escalation_pct){compound}(N-1)"
        elif rule.method.value == "FIXED_INCREASE":
            formula_text = "Rate_N = base + escalation_amount × (N-1)"
        elif rule.method.value == "US_CPI":
            formula_text = "Rate_N = base × (CPI_current / CPI_base)"
        else:
            formula_text = f"Rate_N = base × escalation({rule.method.value})"

        variables = [
            {"symbol": "Rate_N", "role": "output", "variable_type": "RATE",
             "description": f"Escalated {rule.component} for year N",
             "maps_to": "tariff_rate.effective_rate_contract_ccy"},
            {"symbol": "base", "role": "input", "variable_type": "RATE",
             "description": f"Base {rule.component}",
             "maps_to": f"clause_tariff.{'base_rate' if rule.component == 'base_rate' else 'logic_parameters.' + rule.component}"},
            {"symbol": "N", "role": "parameter", "variable_type": "TIME",
             "description": "Operating year number"},
        ]

        if rule.method.value == "PERCENTAGE" and rule.annual_pct is not None:
            variables.append(
                {"symbol": "escalation_pct", "role": "input", "variable_type": "PERCENTAGE",
                 "description": f"Annual escalation percentage ({rule.annual_pct}%)",
                 "maps_to": "clause_tariff.logic_parameters.escalation_pct",
                 "lookup_key": None},
            )
        elif rule.method.value == "FIXED_INCREASE" and rule.annual_amount is not None:
            variables.append(
                {"symbol": "escalation_amount", "role": "input", "variable_type": "RATE",
                 "description": f"Annual escalation amount ({rule.annual_amount})",
                 "unit": rule.currency,
                 "maps_to": "clause_tariff.logic_parameters.escalation_amount",
                 "lookup_key": None},
            )

        if rule.method.value == "US_CPI" and rule.cpi_params:
            variables.extend([
                {"symbol": "CPI_current", "role": "input", "variable_type": "INDEX",
                 "description": f"{rule.cpi_params.index_name} current value",
                 "maps_to": "price_index.index_value"},
                {"symbol": "CPI_base", "role": "parameter", "variable_type": "INDEX",
                 "description": f"{rule.cpi_params.index_name} base value ({rule.cpi_params.base_index_value})"},
            ])

        formulas.append(TariffFormulaCreate(
            clause_tariff_id=clause_tariff_id,
            organization_id=organization_id,
            formula_name=f"{rule.component.replace('_', ' ').title()} Escalation ({rule.method.value})",
            formula_text=formula_text,
            formula_type=formula_type,
            variables=variables,
            operations=["MULTIPLY", "POWER"] if rule.compound else ["MULTIPLY", "ADD"],
            conditions=[],
            section_ref=None,
            extraction_metadata={"source": "escalation_rules", "component": rule.component},
        ))

    return formulas


def _synthesize_shortfall_formula(
    result: PricingExtractionResult,
    clause_tariff_id: int,
    organization_id: int,
) -> Optional[TariffFormulaCreate]:
    """Create tariff_formula row from shortfall mechanics."""
    sm = result.shortfall_mechanics
    if not sm or not sm.formula_text:
        return None

    # Shortfall is always annual — force operating_year on all variables
    variables = [v.model_dump(by_alias=True) for v in sm.formula_variables]
    for v in variables:
        if not v.get("variable_type") and v.get("maps_to"):
            v["variable_type"] = _infer_variable_type(v["maps_to"])
        v["lookup_key"] = "operating_year"

    formula_type = "TAKE_OR_PAY" if sm.shortfall_formula_type == "take_or_pay" else "SHORTFALL_PAYMENT"

    return TariffFormulaCreate(
        clause_tariff_id=clause_tariff_id,
        organization_id=organization_id,
        formula_name=f"Shortfall Payment ({sm.shortfall_formula_type})",
        formula_text=sm.formula_text,
        formula_type=formula_type,
        variables=variables,
        operations=["MAX", "SUBTRACT", "MULTIPLY"],
        conditions=[],
        section_ref=sm.section_refs[0] if sm.section_refs else None,
        extraction_metadata={"excused_events": sm.excused_events, "payment_cap": sm.payment_cap},
    )


def _synthesize_deemed_energy_formula(
    result: PricingExtractionResult,
    clause_tariff_id: int,
    organization_id: int,
) -> Optional[TariffFormulaCreate]:
    """Create tariff_formula row from deemed energy params."""
    de = result.deemed_energy_params
    if not de or not de.formula_text:
        return None

    variables = [v.model_dump(by_alias=True) for v in de.formula_variables]
    for v in variables:
        if not v.get("variable_type") and v.get("maps_to"):
            v["variable_type"] = _infer_variable_type(v["maps_to"])
            if not v.get("lookup_key"):
                v["lookup_key"] = _infer_lookup_key(v["maps_to"])

    return TariffFormulaCreate(
        clause_tariff_id=clause_tariff_id,
        organization_id=organization_id,
        formula_name="Deemed/Available Energy Calculation",
        formula_text=de.formula_text,
        formula_type="DEEMED_ENERGY",
        variables=variables,
        operations=["MULTIPLY", "DIVIDE"],
        conditions=[],
        section_ref=de.section_refs[0] if de.section_refs else None,
        extraction_metadata={"excused_events": de.excused_events},
    )


def _synthesize_energy_output_formula(
    result: PricingExtractionResult,
    clause_tariff_id: int,
    organization_id: int,
) -> Optional[TariffFormulaCreate]:
    """Create tariff_formula row from energy output definition (Object 9)."""
    eod = result.energy_output_definition
    if not eod or not eod.formula_text:
        return None

    variables = [v.model_dump(by_alias=True) for v in eod.formula_variables]
    for v in variables:
        if not v.get("variable_type") and v.get("maps_to"):
            v["variable_type"] = _infer_variable_type(v["maps_to"])
            if not v.get("lookup_key"):
                v["lookup_key"] = _infer_lookup_key(v["maps_to"])

    return TariffFormulaCreate(
        clause_tariff_id=clause_tariff_id,
        organization_id=organization_id,
        formula_name="Contractual Energy Output Definition",
        formula_text=eod.formula_text,
        formula_type="ENERGY_OUTPUT",
        variables=variables,
        operations=eod.operations,
        conditions=[c.model_dump(by_alias=True) for c in eod.conditions],
        section_ref=eod.section_ref,
        extraction_metadata={
            "applies_monthly": eod.applies_monthly,
            "applies_annually": eod.applies_annually,
        },
    )


# =============================================================================
# Logic Parameters Enrichment (Defensive Merge)
# =============================================================================

def build_logic_parameters_patch(
    result: PricingExtractionResult,
) -> Dict[str, Any]:
    """
    Build a dict of logic_parameters keys to merge into clause_tariff.

    Only includes keys — the caller does the defensive merge (never overwrite).
    """
    patch: Dict[str, Any] = {}

    # From tariff_schedule
    ts = result.tariff_schedule
    if ts:
        if ts.floor and ts.floor.contract_ccy:
            patch["floor_rate"] = ts.floor.contract_ccy.value
        if ts.floor and ts.floor.local_ccy:
            patch["floor_rate_local"] = ts.floor.local_ccy.value
        if ts.ceiling and ts.ceiling.contract_ccy:
            patch["ceiling_rate"] = ts.ceiling.contract_ccy.value
        if ts.ceiling and ts.ceiling.local_ccy:
            patch["ceiling_rate_local"] = ts.ceiling.local_ccy.value
        if ts.discount_pct is not None:
            patch["discount_pct"] = ts.discount_pct
        if ts.escalation_params:
            patch["escalation_params"] = ts.escalation_params

    # From payment_mechanics
    pm = result.payment_mechanics
    if pm:
        if pm.take_or_pay and pm.take_or_pay.applies:
            patch["take_or_pay"] = True
            if pm.take_or_pay.minimum_offtake_pct is not None:
                patch["minimum_offtake_pct"] = pm.take_or_pay.minimum_offtake_pct
        if pm.operating_year:
            if pm.operating_year.start_date:
                patch["oy_start_date"] = pm.operating_year.start_date
            if pm.operating_year.definition:
                patch["oy_definition"] = pm.operating_year.definition
        if pm.currency:
            if pm.currency.fx_source:
                patch["fx_source"] = pm.currency.fx_source
            if pm.currency.local:
                patch["local_currency"] = pm.currency.local

    # From deemed_energy_params
    de = result.deemed_energy_params
    if de:
        if de.available_energy_method:
            patch["available_energy_method"] = de.available_energy_method
        if de.interval_minutes:
            patch["interval_minutes"] = de.interval_minutes
        if de.irradiance_threshold_wm2:
            patch["irradiance_threshold_wm2"] = de.irradiance_threshold_wm2
        if de.reference_period:
            patch["reference_period"] = de.reference_period

    # From energy_output_schedule
    eos = result.energy_output_schedule
    if eos:
        if eos.degradation_rate_pct_per_year is not None:
            patch["degradation_pct"] = eos.degradation_rate_pct_per_year / 100.0
        if eos.guaranteed_percentage is not None:
            patch["guarantee_pct_of_p50"] = eos.guaranteed_percentage

    # From shortfall_mechanics
    sm = result.shortfall_mechanics
    if sm:
        if sm.excused_events:
            patch["shortfall_excused_events"] = sm.excused_events
        if sm.payment_cap:
            patch["shortfall_payment_cap"] = sm.payment_cap

    # From escalation_rules — merge CPI params
    for rule in result.escalation_rules:
        if rule.cpi_params:
            patch["cpi_params"] = rule.cpi_params.model_dump()
            break

    return patch


# =============================================================================
# Main Decomposer
# =============================================================================

def decompose(
    result: PricingExtractionResult,
    clause_tariff_id: int,
    organization_id: int,
) -> Dict[str, Any]:
    """
    Decompose PricingExtractionResult into DB-ready structures.

    Returns:
        {
            "tariff_formulas": List[TariffFormulaCreate],
            "logic_parameters_patch": Dict[str, Any],
            "tariff_rate_entries": List[dict],  # year-by-year rates
            "production_guarantee_entries": List[dict],  # energy schedule
        }
    """
    formulas: List[TariffFormulaCreate] = []
    confidence = result.extraction_confidence

    # 1. Convert explicit pricing_formulas from Claude
    for pf in result.pricing_formulas:
        formulas.append(_formula_to_db_row(pf, clause_tariff_id, organization_id, confidence))

    # Track which formula_types Claude already extracted (Fix 4)
    claude_types = {f.formula_type for f in formulas}

    # 2. Synthesize from escalation rules — only if Claude didn't extract them
    #    AND only for non-base_rate components when project uses MRP-bounded pricing
    #    (MRP-bounded projects derive the rate from grid tariff, not from base rate escalation)
    escalation_types = {"PERCENTAGE_ESCALATION", "FIXED_ESCALATION", "CPI_ESCALATION", "FLOOR_CEILING_ESCALATION"}
    is_mrp_bounded = "MRP_BOUNDED" in claude_types or "MRP_CALCULATION" in claude_types
    if not claude_types & escalation_types:
        rules_to_synthesize = result.escalation_rules
        if is_mrp_bounded:
            # Skip base_rate escalation for MRP-bounded — rate comes from grid tariff, not escalation
            rules_to_synthesize = [r for r in rules_to_synthesize if r.component != "base_rate"]
            if len(rules_to_synthesize) < len(result.escalation_rules):
                log.info("  Skipping base_rate escalation synthesis — MRP-bounded project derives rate from grid tariff")
        formulas.extend(_synthesize_escalation_formulas(
            rules_to_synthesize, clause_tariff_id, organization_id,
        ))
    else:
        log.info("  Skipping synthesized escalation formulas — Claude already extracted them")

    # 3. Synthesize shortfall formula — only if Claude didn't extract one
    if "SHORTFALL_PAYMENT" not in claude_types and "TAKE_OR_PAY" not in claude_types:
        sf = _synthesize_shortfall_formula(result, clause_tariff_id, organization_id)
        if sf:
            formulas.append(sf)
    else:
        log.info("  Skipping synthesized shortfall formula — Claude already extracted one")

    # 4. Synthesize deemed energy formula — only if Claude didn't extract one
    if "DEEMED_ENERGY" not in claude_types:
        df = _synthesize_deemed_energy_formula(result, clause_tariff_id, organization_id)
        if df:
            formulas.append(df)
    else:
        log.info("  Skipping synthesized deemed energy formula — Claude already extracted one")

    # 5. Synthesize energy output formula (Object 9) — only if Claude didn't extract one
    if "ENERGY_OUTPUT" not in claude_types:
        eof = _synthesize_energy_output_formula(result, clause_tariff_id, organization_id)
        if eof:
            formulas.append(eof)
    else:
        log.info("  Skipping synthesized energy output formula — Claude already extracted one")

    # 6. Build logic_parameters patch
    lp_patch = build_logic_parameters_patch(result)

    # 7. Extract year-by-year tariff_rate entries
    tariff_rate_entries = []
    if result.tariff_schedule and result.tariff_schedule.year_by_year_rates:
        for yr in result.tariff_schedule.year_by_year_rates:
            tariff_rate_entries.append({
                "operating_year": yr.year,
                "rate": yr.rate,
                "source": yr.source,
                "currency": result.tariff_schedule.base_rate.currency if result.tariff_schedule.base_rate else "USD",
            })

    # 8. Extract production_guarantee entries
    production_guarantee_entries = []
    if result.energy_output_schedule and result.energy_output_schedule.entries:
        eos = result.energy_output_schedule
        for entry in eos.entries:
            production_guarantee_entries.append({
                "operating_year": entry.year,
                "expected_kwh": entry.kwh,
                "guaranteed_kwh": round(entry.kwh * (eos.guaranteed_percentage / 100.0)) if eos.guaranteed_percentage else None,
                "guarantee_pct": eos.guaranteed_percentage,
                "source": entry.source,
            })

    # Deduplicate by (formula_type, normalized formula_text) — keep the one
    # with richer extraction_metadata (synthesized formulas carry excused_events etc.)
    seen: Dict[tuple, TariffFormulaCreate] = {}
    for f in formulas:
        # Normalize whitespace in formula_text for comparison
        norm_text = " ".join(f.formula_text.split())
        key = (f.formula_type, norm_text)
        existing = seen.get(key)
        if existing is None:
            seen[key] = f
        else:
            # Keep whichever has richer extraction_metadata
            if len(f.extraction_metadata) > len(existing.extraction_metadata):
                seen[key] = f
    formulas = list(seen.values())

    log.info(
        f"  Decomposed: {len(formulas)} formula rows, "
        f"{len(lp_patch)} LP keys, "
        f"{len(tariff_rate_entries)} rate entries, "
        f"{len(production_guarantee_entries)} guarantee entries"
    )

    return {
        "tariff_formulas": formulas,
        "logic_parameters_patch": lp_patch,
        "tariff_rate_entries": tariff_rate_entries,
        "production_guarantee_entries": production_guarantee_entries,
    }
