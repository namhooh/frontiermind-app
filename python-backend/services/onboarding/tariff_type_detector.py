"""
Tariff type detection from structured data sources.

Outputs:
  - energy_sale_type_id (FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, etc.)
  - escalation_type_id (NONE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, etc.)
  - formula_type (inside logic_parameters)

Does NOT output tariff_structure_id (dropped in migration 034).

Signals are combined from:
  - SAGE IND_USE_CPI_INFLATION flag
  - Revenue Masterfile floor/ceiling presence
  - Contract line product descriptions (Grid vs Generator keywords)
  - Ground truth validation against known project types
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from models.onboarding import (
    RevenueMasterfileProject,
    SAGEContractLine,
    SAGEProjectData,
    TariffTypeResult,
)

logger = logging.getLogger(__name__)

# ─── Ground Truth (known project tariff types) ─────────────────────────────
# Loaded from config/tariff_type_overrides.yaml so new projects can be added
# without editing code.
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tariff_type_overrides.yaml"
try:
    with open(_CONFIG_PATH) as _f:
        _overrides = yaml.safe_load(_f) or {}
except FileNotFoundError:
    logger.warning(f"Tariff type overrides config not found at {_CONFIG_PATH}, using empty defaults")
    _overrides = {}
KNOWN_FIXED: set = set(_overrides.get("fixed", []))
KNOWN_GRID: set = set(_overrides.get("grid", []))
KNOWN_GENERATOR: set = set(_overrides.get("generator", []))


def detect_tariff_type(
    sage_data: Optional[SAGEProjectData],
    masterfile_data: Optional[RevenueMasterfileProject],
) -> TariffTypeResult:
    """
    Detect tariff type from multiple signal sources.

    Returns TariffTypeResult with energy_sale_type_id, escalation_type_id,
    formula_type, and confidence.
    """
    signals: Dict[str, Any] = {}
    sage_id = None

    if sage_data:
        sage_id = sage_data.sage_id
    elif masterfile_data and masterfile_data.sage_id:
        sage_id = masterfile_data.sage_id

    if not sage_id:
        return TariffTypeResult(confidence=0.0, signals={"error": "no sage_id available"})

    # ─── Signal 1: SAGE CPI flag ───────────────────────────────────────────
    has_cpi = False
    if sage_data:
        has_cpi = sage_data.has_cpi_inflation
        for line in sage_data.contract_lines:
            if line.ind_use_cpi_inflation == 1:
                has_cpi = True
                break
    signals["sage_cpi_flag"] = has_cpi

    # ─── Signal 2: Masterfile floor/ceiling ─────────────────────────────────
    has_floor_ceiling = False
    masterfile_esc_type = None
    masterfile_formula = None
    if masterfile_data:
        has_floor_ceiling = (
            masterfile_data.floor_rate is not None or masterfile_data.ceiling_rate is not None
        )
        masterfile_esc_type = (masterfile_data.escalation_type or "").strip().upper()
        masterfile_formula = (masterfile_data.formula_type or "").strip().upper()
    signals["masterfile_floor_ceiling"] = has_floor_ceiling
    signals["masterfile_escalation_type"] = masterfile_esc_type
    signals["masterfile_formula_type"] = masterfile_formula

    # ─── Signal 3: Product description keywords ─────────────────────────────
    has_grid_product = False
    has_generator_product = False
    if sage_data:
        for line in sage_data.contract_lines:
            desc = (line.product_desc or "").lower()
            if "grid" in desc:
                has_grid_product = True
            if "generator" in desc:
                has_generator_product = True
    signals["grid_product_found"] = has_grid_product
    signals["generator_product_found"] = has_generator_product

    # ─── Signal 4: Ground truth lookup ──────────────────────────────────────
    ground_truth_type = None
    if sage_id in KNOWN_FIXED:
        ground_truth_type = "FIXED"
    elif sage_id in KNOWN_GRID:
        ground_truth_type = "GRID"
    elif sage_id in KNOWN_GENERATOR:
        ground_truth_type = "GENERATOR"
    signals["ground_truth"] = ground_truth_type

    # ─── Inference Logic ────────────────────────────────────────────────────

    # Start with ground truth if available
    energy_sale_type = None
    escalation_type = None
    formula_type = None
    confidence = 0.75

    if ground_truth_type == "FIXED":
        energy_sale_type = "FIXED_SOLAR"
        formula_type = "FIXED"
        confidence = 0.95
    elif ground_truth_type == "GRID":
        energy_sale_type = "FLOATING_GRID"
        formula_type = "FLOATING_GRID"
        confidence = 0.95
    elif ground_truth_type == "GENERATOR":
        energy_sale_type = "FLOATING_GENERATOR"
        formula_type = "FLOATING_GENERATOR"
        confidence = 0.95
    else:
        # Infer from signals
        if has_floor_ceiling:
            # Floor/ceiling implies floating tariff
            if has_generator_product and not has_grid_product:
                energy_sale_type = "FLOATING_GENERATOR"
                formula_type = "FLOATING_GENERATOR"
            else:
                energy_sale_type = "FLOATING_GRID"
                formula_type = "FLOATING_GRID"
            confidence = 0.85
        elif has_grid_product:
            energy_sale_type = "FLOATING_GRID"
            formula_type = "FLOATING_GRID"
            confidence = 0.80
        elif has_generator_product:
            energy_sale_type = "FLOATING_GENERATOR"
            formula_type = "FLOATING_GENERATOR"
            confidence = 0.80
        else:
            energy_sale_type = "FIXED_SOLAR"
            formula_type = "FIXED"
            confidence = 0.70

    # Determine escalation type
    if has_cpi:
        escalation_type = "US_CPI"
        if formula_type == "FIXED":
            # CPI on a fixed tariff implies indexed escalation
            pass
    elif masterfile_esc_type:
        esc_upper = masterfile_esc_type
        if "CPI" in esc_upper:
            escalation_type = "US_CPI"
        elif "FIXED" in esc_upper and "INCREASE" in esc_upper:
            escalation_type = "FIXED_INCREASE"
        elif "PERCENT" in esc_upper:
            escalation_type = "PERCENTAGE"
        elif "REBASED" in esc_upper or "MARKET" in esc_upper:
            escalation_type = "REBASED_MARKET_PRICE"
        elif esc_upper in ("NONE", "FLAT", "NO", "NO ADJUSTMENT"):
            escalation_type = "NONE"
        else:
            escalation_type = "NONE"
    else:
        escalation_type = "NONE"

    signals["inferred_energy_sale_type"] = energy_sale_type
    signals["inferred_escalation_type"] = escalation_type

    # Derive grp_method from formula_type:
    # - GRID-based formulas → GRP = sum of utility variable charges (ToU)
    # - GENERATOR-based formulas → GRP = utility total charges
    # - FIXED → no GRP needed
    grp_method: Optional[str] = None
    if formula_type in ("FLOATING_GRID", "GRID_DISCOUNT_BOUNDED"):
        grp_method = "utility_variable_charges_tou"
    elif formula_type == "FLOATING_GENERATOR":
        grp_method = "utility_total_charges"

    return TariffTypeResult(
        energy_sale_type_id=energy_sale_type,
        escalation_type_id=escalation_type,
        formula_type=formula_type,
        grp_method=grp_method,
        signals=signals,
        confidence=confidence,
    )
