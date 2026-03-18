"""
Phase 4 — Pricing Validator for Step 11P.

Consistency checks on decomposed formulas and extraction results
before DB write.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models.pricing import (
    FormulaType,
    PricingExtractionResult,
    TariffFormulaCreate,
)

log = logging.getLogger("step11p.pricing_validator")


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    message: str
    severity: str = "warning"  # warning, error


@dataclass
class ValidationReport:
    checks: List[ValidationCheck] = field(default_factory=list)
    passed: bool = True

    def add(self, name: str, passed: bool, message: str, severity: str = "warning"):
        self.checks.append(ValidationCheck(name=name, passed=passed, message=message, severity=severity))
        if not passed and severity == "error":
            self.passed = False

    @property
    def errors(self) -> List[ValidationCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "error"]

    @property
    def warnings(self) -> List[ValidationCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "warning"]

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        errors = len(self.errors)
        warnings = len(self.warnings)
        return f"{passed}/{total} checks passed, {errors} errors, {warnings} warnings"


def validate(
    result: PricingExtractionResult,
    decomposed: Dict[str, Any],
) -> ValidationReport:
    """
    Run all validation checks on extraction result and decomposed output.

    Args:
        result: PricingExtractionResult from Phase 2.
        decomposed: Output from formula_decomposer.decompose().

    Returns:
        ValidationReport with pass/fail per check.
    """
    report = ValidationReport()
    formulas = decomposed.get("tariff_formulas", [])
    lp_patch = decomposed.get("logic_parameters_patch", {})

    _check_floor_ceiling(result, report)
    _check_escalation_direction(result, report)
    _check_rate_continuity(result, report)
    _check_variable_completeness(formulas, report)
    _check_currency_consistency(result, report)
    _check_energy_output_monotonic(result, report)
    _check_cross_formula_coherence(formulas, result, report)
    _check_shortfall_coherence(result, report)
    _check_cpi_params_complete(result, report)
    _check_formula_text_symbols(formulas, report)
    _check_output_role_mapping(formulas, report)
    _check_section_ref_present(formulas, report)

    log.info(f"  Validation: {report.summary()}")
    for check in report.errors:
        log.error(f"    [ERROR] {check.name}: {check.message}")
    for check in report.warnings:
        log.warning(f"    [WARN] {check.name}: {check.message}")

    return report


def _check_floor_ceiling(result: PricingExtractionResult, report: ValidationReport):
    """Floor must be less than ceiling (same currency)."""
    ts = result.tariff_schedule
    if not ts or not ts.floor or not ts.ceiling:
        report.add("floor_ceiling", True, "No floor/ceiling to check")
        return

    # Contract currency
    f_val = ts.floor.contract_ccy.value if ts.floor.contract_ccy else None
    c_val = ts.ceiling.contract_ccy.value if ts.ceiling.contract_ccy else None

    if f_val is not None and c_val is not None:
        if f_val >= c_val:
            report.add("floor_ceiling", False,
                        f"Floor ({f_val}) >= Ceiling ({c_val}) in contract currency",
                        severity="error")
        else:
            report.add("floor_ceiling", True,
                        f"Floor ({f_val}) < Ceiling ({c_val})")
    else:
        report.add("floor_ceiling", True, "Floor/ceiling not both present in contract_ccy")


def _check_escalation_direction(result: PricingExtractionResult, report: ValidationReport):
    """FIXED_INCREASE should have positive annual_amount."""
    for rule in result.escalation_rules:
        if rule.method.value == "FIXED_INCREASE":
            if rule.annual_amount is not None and rule.annual_amount <= 0:
                report.add("escalation_direction", False,
                            f"FIXED_INCREASE for {rule.component} has non-positive amount: {rule.annual_amount}")
            else:
                report.add("escalation_direction", True,
                            f"FIXED_INCREASE for {rule.component} direction OK")


def _check_rate_continuity(result: PricingExtractionResult, report: ValidationReport):
    """Year-by-year schedule should be continuous (no gaps)."""
    ts = result.tariff_schedule
    if not ts or len(ts.year_by_year_rates) < 2:
        report.add("rate_continuity", True, "Insufficient rate entries to check continuity")
        return

    years = sorted(r.year for r in ts.year_by_year_rates)
    gaps = []
    for i in range(1, len(years)):
        if years[i] - years[i - 1] > 1:
            gaps.append(f"gap between year {years[i-1]} and {years[i]}")

    if gaps:
        report.add("rate_continuity", False,
                    f"Rate schedule gaps: {', '.join(gaps)}", severity="warning")
    else:
        report.add("rate_continuity", True, f"Rate schedule continuous (years {years[0]}-{years[-1]})")


def _check_variable_completeness(formulas: List[TariffFormulaCreate], report: ValidationReport):
    """All formula input variables should have a maps_to reference."""
    for f in formulas:
        missing = []
        for v in f.variables:
            if v.get("role") == "input" and not v.get("maps_to"):
                missing.append(v.get("symbol", "?"))
        if missing:
            report.add("variable_completeness", False,
                        f"Formula '{f.formula_type}' has unmapped inputs: {missing}",
                        severity="warning")
        else:
            report.add("variable_completeness", True,
                        f"Formula '{f.formula_type}' variables complete")


def _check_currency_consistency(result: PricingExtractionResult, report: ValidationReport):
    """Floor/ceiling currency should match billing currency."""
    ts = result.tariff_schedule
    pm = result.payment_mechanics
    if not ts or not pm or not pm.currency:
        report.add("currency_consistency", True, "No currency data to cross-check")
        return

    billing_ccy = pm.currency.billing
    issues = []

    if ts.floor and ts.floor.contract_ccy:
        if ts.floor.contract_ccy.currency != billing_ccy:
            issues.append(f"floor ({ts.floor.contract_ccy.currency}) != billing ({billing_ccy})")

    if ts.ceiling and ts.ceiling.contract_ccy:
        if ts.ceiling.contract_ccy.currency != billing_ccy:
            issues.append(f"ceiling ({ts.ceiling.contract_ccy.currency}) != billing ({billing_ccy})")

    if issues:
        report.add("currency_consistency", False,
                    f"Currency mismatch: {'; '.join(issues)}", severity="warning")
    else:
        report.add("currency_consistency", True, "Currency consistent")


def _check_energy_output_monotonic(result: PricingExtractionResult, report: ValidationReport):
    """Expected energy should be decreasing or stable (degradation)."""
    eos = result.energy_output_schedule
    if not eos or len(eos.entries) < 2:
        report.add("energy_monotonic", True, "Insufficient energy entries to check")
        return

    sorted_entries = sorted(eos.entries, key=lambda e: e.year)
    increases = []
    for i in range(1, len(sorted_entries)):
        if sorted_entries[i].kwh > sorted_entries[i - 1].kwh * 1.001:  # 0.1% tolerance
            increases.append(f"year {sorted_entries[i].year} ({sorted_entries[i].kwh:,.0f}) > "
                             f"year {sorted_entries[i-1].year} ({sorted_entries[i-1].kwh:,.0f})")

    if increases:
        report.add("energy_monotonic", False,
                    f"Energy output increases (expected degradation): {increases[0]}",
                    severity="warning")
    else:
        report.add("energy_monotonic", True, "Energy output monotonically decreasing")


def _check_cross_formula_coherence(
    formulas: List[TariffFormulaCreate],
    result: PricingExtractionResult,
    report: ValidationReport,
):
    """If ENERGY_OUTPUT references E_Available, DEEMED_ENERGY should exist."""
    formula_types = {f.formula_type for f in formulas}

    if "ENERGY_OUTPUT" in formula_types and "DEEMED_ENERGY" not in formula_types:
        # Check if ENERGY_OUTPUT actually references deemed energy
        eo_formulas = [f for f in formulas if f.formula_type == "ENERGY_OUTPUT"]
        has_deemed_ref = any(
            v.get("maps_to") == "tariff_formula.DEEMED_ENERGY"
            for f in eo_formulas
            for v in f.variables
        )
        if has_deemed_ref:
            report.add("cross_formula_coherence", False,
                        "ENERGY_OUTPUT references DEEMED_ENERGY but no DEEMED_ENERGY formula found",
                        severity="warning")
            return

    report.add("cross_formula_coherence", True, "Cross-formula references consistent")


def _check_shortfall_coherence(result: PricingExtractionResult, report: ValidationReport):
    """If shortfall formula exists, guarantee and tariff should exist."""
    if not result.shortfall_mechanics or not result.shortfall_mechanics.formula_text:
        report.add("shortfall_coherence", True, "No shortfall formula to check")
        return

    issues = []
    if not result.energy_output_schedule:
        issues.append("no energy_output_schedule")
    if not result.tariff_schedule:
        issues.append("no tariff_schedule")

    if issues:
        report.add("shortfall_coherence", False,
                    f"Shortfall formula exists but missing: {', '.join(issues)}",
                    severity="warning")
    else:
        report.add("shortfall_coherence", True, "Shortfall formula dependencies present")


def _check_cpi_params_complete(result: PricingExtractionResult, report: ValidationReport):
    """If escalation = US_CPI, cpi_params must have index_name + reference_year."""
    for rule in result.escalation_rules:
        if rule.method.value in ("US_CPI", "WPI", "CUSTOM_INDEX"):
            if not rule.cpi_params:
                report.add("cpi_params_complete", False,
                            f"{rule.method.value} escalation for {rule.component} missing cpi_params",
                            severity="error")
            elif not rule.cpi_params.index_name or rule.cpi_params.reference_year is None:
                report.add("cpi_params_complete", False,
                            f"{rule.method.value} escalation for {rule.component}: "
                            f"cpi_params missing index_name or reference_year",
                            severity="error")
            else:
                report.add("cpi_params_complete", True,
                            f"CPI params complete for {rule.component}")


def _check_formula_text_symbols(formulas: List[TariffFormulaCreate], report: ValidationReport):
    """Every symbol in variables should appear in formula_text."""
    import re
    for f in formulas:
        text = f.formula_text
        missing = []
        for v in f.variables:
            symbol = v.get("symbol", "")
            if not symbol:
                continue
            # Escape for regex, check presence in formula_text
            if symbol not in text and re.sub(r'[_\s]', '', symbol) not in re.sub(r'[_\s]', '', text):
                missing.append(symbol)
        if missing:
            report.add("formula_text_symbols", False,
                        f"Formula '{f.formula_name}': variables {missing} not found in formula_text",
                        severity="warning")
        else:
            report.add("formula_text_symbols", True,
                        f"Formula '{f.formula_name}': all variable symbols present in formula_text")


def _check_output_role_mapping(formulas: List[TariffFormulaCreate], report: ValidationReport):
    """Output variables for payment formulas should map to invoice_line_item.amount, not rates."""
    payment_types = {"SHORTFALL_PAYMENT", "TAKE_OR_PAY", "MRP_CALCULATION", "FX_CONVERSION"}
    for f in formulas:
        for v in f.variables:
            if v.get("role") != "output":
                continue
            maps_to = v.get("maps_to") or ""
            # Payment outputs should not map to rate columns
            if f.formula_type in payment_types and maps_to == "tariff_rate.effective_rate_contract_ccy":
                report.add("output_role_mapping", False,
                            f"Formula '{f.formula_name}': payment output '{v.get('symbol')}' "
                            f"maps to tariff_rate (a per-kWh rate) — should be invoice_line_item.amount",
                            severity="warning")
            else:
                report.add("output_role_mapping", True,
                            f"Formula '{f.formula_name}': output mapping OK")


def _check_section_ref_present(formulas: List[TariffFormulaCreate], report: ValidationReport):
    """Every formula should have a section_ref pointing to the source clause/annexure."""
    for f in formulas:
        if not f.section_ref:
            report.add("section_ref_present", False,
                        f"Formula '{f.formula_name}' ({f.formula_type}) has no section_ref — "
                        f"may be hallucinated from prose rather than extracted from an explicit equation",
                        severity="warning")
        else:
            report.add("section_ref_present", True,
                        f"Formula '{f.formula_name}': section_ref present ({f.section_ref})")
