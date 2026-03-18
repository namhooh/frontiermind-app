"""
Phase 2 — Pricing Extractor (Claude API Wrapper) for Step 11P.

Takes a PricingSectionBundle from Phase 1, calls Claude for structured
extraction, and returns a validated PricingExtractionResult.

Includes post-extraction normalization to fix common Claude/OCR issues:
- formula_type aliases (category names → enum values)
- Hardcoded numeric values in formula_text → variable symbols
- OCR garbled variable names (Enist → E_hist, Irrhist → Irr_hist)
- Missing variables (symbols in formula_text not in variables array)
- Wrong roles (parameter → input for DB-sourced values)
"""

import json
import logging
import re
from typing import Optional

import anthropic

from models.pricing import PricingExtractionResult
from services.pricing.section_isolator import PricingSectionBundle
from services.prompts.pricing_extraction_prompt import build_pricing_extraction_prompt

log = logging.getLogger("step11p.pricing_extractor")

# Claude model for extraction — Sonnet for speed/cost, Opus for complex contracts
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8192

# Map common Claude mismatches to valid FormulaType values.
_FORMULA_TYPE_ALIASES: dict[str, str] = {
    "pricing": "MRP_BOUNDED",
    "escalation": "PERCENTAGE_ESCALATION",
    "energy": "ENERGY_OUTPUT",
    "performance": "SHORTFALL_PAYMENT",
    "billing": "FX_CONVERSION",
    "bounded_discount": "MRP_BOUNDED",
    "mrp_bounded_discount": "MRP_BOUNDED",
    "mrp": "MRP_CALCULATION",
    "shortfall": "SHORTFALL_PAYMENT",
    "deemed_energy": "DEEMED_ENERGY",
    "degradation": "ENERGY_DEGRADATION",
    "guarantee": "ENERGY_GUARANTEE",
    "multiphase": "ENERGY_MULTIPHASE",
    "cpi": "CPI_ESCALATION",
    "fixed": "FIXED_ESCALATION",
    "percentage": "PERCENTAGE_ESCALATION",
    "fx": "FX_CONVERSION",
    "take_or_pay": "TAKE_OR_PAY",
    "floor_ceiling": "FLOOR_CEILING_ESCALATION",
}

_VALID_TYPES = {
    "MRP_BOUNDED", "MRP_CALCULATION",
    "PERCENTAGE_ESCALATION", "FIXED_ESCALATION", "CPI_ESCALATION", "FLOOR_CEILING_ESCALATION",
    "ENERGY_OUTPUT", "DEEMED_ENERGY", "ENERGY_DEGRADATION", "ENERGY_GUARANTEE", "ENERGY_MULTIPHASE",
    "SHORTFALL_PAYMENT", "TAKE_OR_PAY",
    "FX_CONVERSION",
}

# Common OCR garbled variable names → corrected
_OCR_FIXES: dict[str, str] = {
    "Enist": "E_hist",
    "Ehist": "E_hist",
    "E hist": "E_hist",
    "Irrhist": "Irr_hist",
    "Irr hist": "Irr_hist",
    "lrr": "Irr",
    "lrrhist": "Irr_hist",
    "Emetered": "E_metered",
    "EAvailable": "E_Available",
    "Eavailable": "E_Available",
}

# DB table prefixes that indicate a variable is an input (not parameter)
_DB_INPUT_PREFIXES = (
    "meter_aggregate.", "reference_price.", "tariff_rate.", "production_guarantee.",
    "production_forecast.", "exchange_rate.", "price_index.", "project.",
    "clause_tariff.", "invoice_line_item.",
)


# =============================================================================
# Fix 1: Normalize formula_type values
# =============================================================================

def _normalize_formula_types(data: dict) -> None:
    """Normalize formula_type values in-place before Pydantic validation."""
    for formula in data.get("pricing_formulas") or []:
        ft = formula.get("formula_type", "")
        if ft not in _VALID_TYPES:
            normalized = _FORMULA_TYPE_ALIASES.get(ft.lower().strip())
            if normalized:
                log.info(f"  Normalized formula_type: '{ft}' → '{normalized}'")
                formula["formula_type"] = normalized
            else:
                upper = ft.upper().replace(" ", "_")
                if upper in _VALID_TYPES:
                    formula["formula_type"] = upper
                else:
                    log.warning(f"  Unknown formula_type '{ft}' — defaulting to MRP_BOUNDED")
                    formula["formula_type"] = "MRP_BOUNDED"


# =============================================================================
# Fix 2: Post-extraction normalization (hardcoded values, OCR, roles)
# =============================================================================

def _fix_ocr_errors(data: dict) -> int:
    """Fix common OCR-garbled variable names in formula_text and variables."""
    fixes = 0
    for formula in data.get("pricing_formulas") or []:
        text = formula.get("formula_text", "")
        for wrong, right in _OCR_FIXES.items():
            if wrong in text:
                text = text.replace(wrong, right)
                fixes += 1
        formula["formula_text"] = text

        for v in formula.get("variables") or []:
            sym = v.get("symbol", "")
            for wrong, right in _OCR_FIXES.items():
                if wrong in sym:
                    v["symbol"] = sym.replace(wrong, right)
                    fixes += 1
                    break

    # Also fix in shortfall_mechanics and deemed_energy_params
    for obj_key in ("shortfall_mechanics", "deemed_energy_params", "energy_output_definition"):
        obj = data.get(obj_key)
        if not obj:
            continue
        text = obj.get("formula_text", "")
        for wrong, right in _OCR_FIXES.items():
            if wrong in text:
                text = text.replace(wrong, right)
                fixes += 1
        obj["formula_text"] = text
        for v in obj.get("formula_variables") or []:
            sym = v.get("symbol", "")
            for wrong, right in _OCR_FIXES.items():
                if wrong in sym:
                    v["symbol"] = sym.replace(wrong, right)
                    fixes += 1
                    break

    return fixes


def _fix_hardcoded_values(data: dict) -> int:
    """Replace hardcoded numeric values in formula_text with variable symbols."""
    fixes = 0
    # Pattern: number followed by % or preceded by × (
    # e.g., "× (1 + 0.025)^" or "0.1199 USD/kWh ×"
    pct_pattern = re.compile(r'\b(\d+\.?\d*)\s*%')
    decimal_in_formula = re.compile(r'(?<=[×\(+\-])\s*(\d+\.\d{2,})\b')

    for formula in data.get("pricing_formulas") or []:
        text = formula.get("formula_text", "")
        variables = formula.get("variables") or []

        # Check for hardcoded percentages like "0.025" or "2.5%"
        # Only flag if there's no variable with that value as its symbol
        existing_symbols = {v.get("symbol", "") for v in variables}

        for match in pct_pattern.finditer(text):
            val = match.group(1)
            if val not in existing_symbols and val not in ("0", "1", "100"):
                log.warning(f"  Hardcoded percentage '{val}%' in formula_text: {formula.get('formula_name')}")

        for match in decimal_in_formula.finditer(text):
            val = match.group(1)
            if val not in existing_symbols and float(val) not in (0.0, 1.0):
                log.warning(f"  Hardcoded decimal '{val}' in formula_text: {formula.get('formula_name')}")

    return fixes


def _fix_variable_roles(data: dict) -> int:
    """Force role=input for variables with maps_to pointing to DB tables."""
    fixes = 0
    for formula in data.get("pricing_formulas") or []:
        for v in formula.get("variables") or []:
            maps_to = v.get("maps_to") or ""
            if v.get("role") == "parameter" and any(maps_to.startswith(p) for p in _DB_INPUT_PREFIXES):
                v["role"] = "input"
                fixes += 1

    # Also fix in shortfall_mechanics and deemed_energy_params
    for obj_key in ("shortfall_mechanics", "deemed_energy_params", "energy_output_definition"):
        obj = data.get(obj_key)
        if not obj:
            continue
        for v in obj.get("formula_variables") or []:
            maps_to = v.get("maps_to") or ""
            if v.get("role") == "parameter" and any(maps_to.startswith(p) for p in _DB_INPUT_PREFIXES):
                v["role"] = "input"
                fixes += 1

    return fixes


def _fix_invented_maps_to(data: dict) -> int:
    """Fix maps_to references pointing to tariff_formula.* (invented cross-references).

    Claude sometimes invents cross-formula references like tariff_formula.DEEMED_ENERGY.
    These aren't real DB columns. Replace with the actual DB column where the value lives.
    """
    fixes = 0
    # Map invented references to real DB columns
    invented_to_real = {
        "tariff_formula.DEEMED_ENERGY": "meter_aggregate.available_energy_kwh",
        "tariff_formula.ENERGY_OUTPUT": "meter_aggregate.total_production",
        "tariff_formula.SHORTFALL_PAYMENT": "invoice_line_item.amount",
        "tariff_formula.MRP_BOUNDED": "tariff_rate.effective_rate_contract_ccy",
        "tariff_formula.MRP_CALCULATION": "tariff_rate.effective_rate_contract_ccy",
    }

    for obj_key in ("pricing_formulas",):
        for formula in data.get(obj_key) or []:
            for v in formula.get("variables") or []:
                maps_to = v.get("maps_to") or ""
                if maps_to.startswith("tariff_formula."):
                    real = invented_to_real.get(maps_to)
                    if real:
                        v["maps_to"] = real
                        fixes += 1
                    else:
                        # Unknown tariff_formula reference — clear it
                        log.warning(f"  Unknown invented maps_to '{maps_to}' — clearing")
                        v["maps_to"] = None
                        fixes += 1

    # Also fix in sub-objects
    for obj_key in ("shortfall_mechanics", "deemed_energy_params", "energy_output_definition"):
        obj = data.get(obj_key)
        if not obj:
            continue
        for v in obj.get("formula_variables") or []:
            maps_to = v.get("maps_to") or ""
            if maps_to.startswith("tariff_formula."):
                real = invented_to_real.get(maps_to)
                v["maps_to"] = real
                fixes += 1

    return fixes


def _fix_missing_variables(data: dict) -> int:
    """Ensure every symbol in formula_text has a matching variable entry."""
    fixes = 0
    # Symbol patterns: E_xxx(i), Irr(x), PR_month, Cap — single tokens with
    # underscores or parenthesized args, NOT multi-word names
    symbol_pattern = re.compile(r'\b([A-Z][a-z]*_[A-Za-z_]+(?:\([^)]*\))?)\b')
    func_pattern = re.compile(r'\b([A-Z][a-z]+\([^)]*\))\b')

    for formula in data.get("pricing_formulas") or []:
        text = formula.get("formula_text", "")
        variables = formula.get("variables") or []
        existing_symbols = {v.get("symbol", "") for v in variables}
        # Also normalize: strip underscores/spaces for fuzzy match
        normalized_existing = {s.replace("_", "").replace(" ", "").lower() for s in existing_symbols}

        skip = {"MAX", "MIN", "IF", "THEN", "ELSE", "SUM"}

        for pattern in (symbol_pattern, func_pattern):
            for match in pattern.finditer(text):
                sym = match.group(1)
                if sym in skip or sym in existing_symbols:
                    continue
                norm = sym.replace("_", "").replace(" ", "").lower()
                if norm in normalized_existing:
                    continue
                log.warning(f"  Symbol '{sym}' in formula_text but not in variables: {formula.get('formula_name')}")

    return fixes


def _filter_hallucinated_formulas(data: dict) -> int:
    """Remove likely hallucinated formulas that were synthesized from prose."""
    removed = 0
    formulas = data.get("pricing_formulas") or []
    filtered = []

    # Patterns that indicate a hallucinated formula (prose, not an equation)
    hallucination_signals = [
        # No mathematical operators at all
        lambda f: not any(op in f.get("formula_text", "") for op in ("=", "+", "-", "×", "*", "/", "^", "MAX", "MIN", "∑")),
        # FX conversion without explicit equation in contract (common hallucination)
        lambda f: f.get("formula_type") == "FX_CONVERSION" and not f.get("section_ref"),
        # No section_ref AND formula_text reads like prose
        lambda f: not f.get("section_ref") and any(
            phrase in f.get("formula_text", "").lower()
            for phrase in ("shall be", "converted at", "prevailing rate", "as invoiced", "previous month")
        ),
    ]

    for f in formulas:
        is_hallucinated = any(check(f) for check in hallucination_signals)
        if is_hallucinated:
            log.warning(f"  Filtered hallucinated formula: '{f.get('formula_name')}' — {f.get('formula_text', '')[:80]}")
            removed += 1
        else:
            filtered.append(f)

    data["pricing_formulas"] = filtered
    return removed


def _normalize_extraction(data: dict) -> None:
    """Run all post-extraction normalization passes."""
    _normalize_formula_types(data)

    ocr_fixes = _fix_ocr_errors(data)
    if ocr_fixes:
        log.info(f"  Post-extraction: {ocr_fixes} OCR fixes applied")

    role_fixes = _fix_variable_roles(data)
    if role_fixes:
        log.info(f"  Post-extraction: {role_fixes} variable roles corrected (parameter → input)")

    ref_fixes = _fix_invented_maps_to(data)
    if ref_fixes:
        log.info(f"  Post-extraction: {ref_fixes} invented maps_to references fixed")

    hallucination_removals = _filter_hallucinated_formulas(data)
    if hallucination_removals:
        log.info(f"  Post-extraction: {hallucination_removals} hallucinated formulas filtered")

    _fix_hardcoded_values(data)  # warnings only — doesn't auto-fix
    _fix_missing_variables(data)  # warnings only — doesn't auto-fix


# =============================================================================
# Main extraction function
# =============================================================================

def extract_pricing(
    bundle: PricingSectionBundle,
    project_hint: Optional[str] = None,
    model: Optional[str] = None,
) -> PricingExtractionResult:
    """
    Call Claude to extract pricing objects from contract text.

    Args:
        bundle: PricingSectionBundle from Phase 1 (or full text with --no-isolate).
        project_hint: Optional project identifier for context.
        model: Override Claude model (default: sonnet).

    Returns:
        Validated PricingExtractionResult.

    Raises:
        ValueError: If extraction fails or response cannot be parsed.
    """
    if not bundle.combined_text.strip():
        raise ValueError("Empty pricing sections — nothing to extract")

    prompt = build_pricing_extraction_prompt(
        pricing_sections=bundle.combined_text,
        project_hint=project_hint,
    )

    client = anthropic.Anthropic()
    use_model = model or DEFAULT_MODEL

    log.info(
        f"  Calling Claude ({use_model}) — "
        f"{len(bundle.combined_text):,} chars input, "
        f"{len(bundle.sections)} sections"
    )

    response = client.messages.create(
        model=use_model,
        max_tokens=MAX_TOKENS,
        system=prompt["system"],
        messages=[{"role": "user", "content": prompt["user"]}],
    )

    # Extract text content
    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    if not raw_text.strip():
        raise ValueError("Claude returned empty response")

    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Parse JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"  Failed to parse Claude response as JSON: {e}")
        log.error(f"  First 500 chars: {text[:500]}")
        raise ValueError(f"Invalid JSON from Claude: {e}") from e

    # Post-extraction normalization (Fix 1 + Fix 2)
    _normalize_extraction(data)

    # Validate through Pydantic
    try:
        result = PricingExtractionResult.model_validate(data)
    except Exception as e:
        log.error(f"  Pydantic validation failed: {e}")
        raise ValueError(f"Response failed validation: {e}") from e

    # Log extraction summary
    formula_count = len(result.pricing_formulas)
    escalation_count = len(result.escalation_rules)
    definition_count = len(result.definitions_registry)
    energy_entries = len(result.energy_output_schedule.entries) if result.energy_output_schedule else 0

    log.info(
        f"  Extraction complete: {formula_count} formulas, "
        f"{escalation_count} escalation rules, {definition_count} definitions, "
        f"{energy_entries} energy schedule entries, "
        f"confidence={result.extraction_confidence}"
    )

    if result.warnings:
        for w in result.warnings:
            log.warning(f"  Extraction warning: {w}")

    return result
