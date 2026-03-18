"""
Field-level cross-verification engine for structured data sources.

Uses the field-level authority matrix to determine which source is primary
for each data point, then cross-verifies against other sources.

Confidence scoring:
  - 3+ agreeing sources → 0.95
  - 2 agreeing → 0.85
  - 1 source (authority) → 0.75
  - Disagreement → 0.40 + flag

Critical-field conflict rule: If two primary sources disagree on
tariff base rate, discount %, floor, ceiling, or escalation type →
block auto-population, require manual approval.
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from models.onboarding import (
    CrossVerificationResult,
    Discrepancy,
    FieldVerification,
    MarketRefPricingProject,
    MotherChildPattern,
    RevenueMasterfileProject,
    SAGEContractLine,
    SAGEProjectData,
    TariffTypeResult,
)
from services.onboarding.tariff_type_detector import detect_tariff_type

logger = logging.getLogger(__name__)

# ─── Critical Fields (block auto-population if disagreement) ────────────────
CRITICAL_FIELDS = {
    "base_rate", "discount_pct", "floor_rate", "ceiling_rate", "escalation_type",
}

# ─── Tolerance Thresholds ──────────────────────────────────────────────────
TARIFF_VARIANCE_THRESHOLD = 0.05   # 5% for tariff values
PRODUCTION_VARIANCE_THRESHOLD = 0.10  # 10% for production values
COD_DATE_TOLERANCE_DAYS = 30
TERM_TOLERANCE_YEARS = 1


def _values_agree(
    v1: Any, v2: Any, tolerance_pct: Optional[float] = None
) -> bool:
    """Check if two values agree, optionally within a percentage tolerance."""
    if v1 is None or v2 is None:
        return True  # Can't disagree if one is missing

    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        if v1 == 0 and v2 == 0:
            return True
        if v1 == 0 or v2 == 0:
            return False
        if tolerance_pct is not None:
            variance = abs(v1 - v2) / max(abs(v1), abs(v2))
            return variance <= tolerance_pct
        return v1 == v2

    return str(v1).strip().upper() == str(v2).strip().upper()


def _compute_variance_pct(v1: Any, v2: Any) -> Optional[float]:
    """Compute percentage variance between two numeric values."""
    if v1 is None or v2 is None:
        return None
    try:
        f1, f2 = float(v1), float(v2)
        if f1 == 0 and f2 == 0:
            return 0.0
        if max(abs(f1), abs(f2)) == 0:
            return None
        return abs(f1 - f2) / max(abs(f1), abs(f2))
    except (ValueError, TypeError):
        return None


class CrossVerifier:
    """
    Cross-verifies data across structured sources using field-level authority.

    Usage:
        verifier = CrossVerifier()
        result = verifier.verify(
            sage_data=sage_project,
            masterfile_data=masterfile_project,
            market_ref_data=market_ref_project,
        )
    """

    def verify(
        self,
        sage_data: Optional[SAGEProjectData] = None,
        masterfile_data: Optional[RevenueMasterfileProject] = None,
        market_ref_data: Optional[MarketRefPricingProject] = None,
        onboarding_data: Optional[Dict[str, Any]] = None,
    ) -> CrossVerificationResult:
        """
        Run field-level cross-verification for a single project.

        Args:
            sage_data: Parsed SAGE CSV data
            masterfile_data: Parsed Revenue Masterfile data
            market_ref_data: Parsed Market Ref Pricing data
            onboarding_data: AM Onboarding Template data (if available)

        Returns:
            CrossVerificationResult with field verifications, merged values,
            and conflict flags.
        """
        sage_id = None
        project_name = None
        if sage_data:
            sage_id = sage_data.sage_id
            project_name = sage_data.customer_name
        elif masterfile_data:
            sage_id = masterfile_data.sage_id
            project_name = masterfile_data.project_name

        if not sage_id:
            return CrossVerificationResult(
                sage_id="UNKNOWN",
                blocked=True,
                critical_conflicts=["No sage_id available from any source"],
            )

        verifications: List[FieldVerification] = []
        merged: Dict[str, Any] = {"sage_id": sage_id}
        discrepancies: List[Discrepancy] = []
        critical_conflicts: List[str] = []

        # ─── Contract Identity / Currency / Payment Terms ──────────────
        # Primary: SAGE | Verification: Masterfile, Onboarding
        verifications.append(self._verify_field(
            "contract_currency",
            primary_source="sage",
            primary_value=sage_data.contract_currency if sage_data else None,
            verification_sources={
                "masterfile": masterfile_data.currency if masterfile_data else None,
                "onboarding": onboarding_data.get("billing_currency") if onboarding_data else None,
            },
        ))

        verifications.append(self._verify_field(
            "payment_terms",
            primary_source="sage",
            primary_value=sage_data.payment_terms if sage_data else None,
            verification_sources={},
        ))

        # ─── Tariff Base Rate ──────────────────────────────────────────
        # Primary: Masterfile Inp_Proj | Verification: Market Ref PO Summary
        masterfile_base = masterfile_data.base_rate if masterfile_data else None
        market_ref_base = None
        if market_ref_data and market_ref_data.tariff_summary:
            market_ref_base = market_ref_data.tariff_summary.get("base_rate")

        v = self._verify_field(
            "base_rate",
            primary_source="masterfile",
            primary_value=masterfile_base,
            verification_sources={
                "market_ref": market_ref_base,
                "onboarding": onboarding_data.get("base_rate") if onboarding_data else None,
            },
            tolerance_pct=TARIFF_VARIANCE_THRESHOLD,
            is_critical=True,
        )
        verifications.append(v)
        if v.requires_manual_approval:
            critical_conflicts.append(f"base_rate: disagreement between sources")

        # ─── Discount % ───────────────────────────────────────────────
        # Primary: Masterfile | Verification: Market Ref
        masterfile_disc = masterfile_data.discount_pct if masterfile_data else None
        market_ref_disc = None
        if market_ref_data and market_ref_data.tariff_summary:
            market_ref_disc = market_ref_data.tariff_summary.get("discount_pct")

        v = self._verify_field(
            "discount_pct",
            primary_source="masterfile",
            primary_value=masterfile_disc,
            verification_sources={
                "market_ref": market_ref_disc,
                "onboarding": onboarding_data.get("discount_pct") if onboarding_data else None,
            },
            is_critical=True,
        )
        verifications.append(v)
        if v.requires_manual_approval:
            critical_conflicts.append(f"discount_pct: disagreement between sources")

        # ─── Floor Rate ────────────────────────────────────────────────
        masterfile_floor = masterfile_data.floor_rate if masterfile_data else None
        v = self._verify_field(
            "floor_rate",
            primary_source="masterfile",
            primary_value=masterfile_floor,
            verification_sources={
                "onboarding": onboarding_data.get("floor_rate") if onboarding_data else None,
            },
            tolerance_pct=TARIFF_VARIANCE_THRESHOLD,
            is_critical=True,
        )
        verifications.append(v)
        if v.requires_manual_approval:
            critical_conflicts.append(f"floor_rate: disagreement between sources")

        # ─── Ceiling Rate ──────────────────────────────────────────────
        masterfile_ceiling = masterfile_data.ceiling_rate if masterfile_data else None
        v = self._verify_field(
            "ceiling_rate",
            primary_source="masterfile",
            primary_value=masterfile_ceiling,
            verification_sources={
                "onboarding": onboarding_data.get("ceiling_rate") if onboarding_data else None,
            },
            tolerance_pct=TARIFF_VARIANCE_THRESHOLD,
            is_critical=True,
        )
        verifications.append(v)
        if v.requires_manual_approval:
            critical_conflicts.append(f"ceiling_rate: disagreement between sources")

        # ─── Escalation Type ──────────────────────────────────────────
        # Cross-verify SAGE CPI flag + Masterfile escalation type
        sage_esc = None
        if sage_data and sage_data.has_cpi_inflation:
            sage_esc = "US_CPI"
        masterfile_esc = masterfile_data.escalation_type if masterfile_data else None

        v = self._verify_field(
            "escalation_type",
            primary_source="sage",
            primary_value=sage_esc,
            verification_sources={
                "masterfile": masterfile_esc,
                "onboarding": onboarding_data.get("escalation_type") if onboarding_data else None,
            },
            is_critical=True,
        )
        verifications.append(v)
        if v.requires_manual_approval:
            critical_conflicts.append(f"escalation_type: mismatch between SAGE CPI flag and Masterfile")

        # ─── COD Date ──────────────────────────────────────────────────
        # Primary: Masterfile | Verification: Onboarding, SAGE
        #
        # Multi-phase rule: For projects with multiple phases (e.g.,
        # Phase I COD = 2018, Phase II COD = 2024), always use the
        # EARLIEST COD for operating year counting and tariff period
        # anchoring (clause_tariff.valid_from).  Later phase CODs are
        # recorded in source_metadata for reference but do not override
        # the initial COD.
        masterfile_cod = masterfile_data.cod_date if masterfile_data else None
        onboarding_cod = onboarding_data.get("cod_date") if onboarding_data else None
        sage_start = sage_data.contract_start_date if sage_data else None

        # Collect all COD candidates and pick the earliest (initial COD)
        cod_candidates = [d for d in [masterfile_cod, onboarding_cod, sage_start] if d is not None]
        initial_cod = min(cod_candidates) if cod_candidates else None

        # If earliest differs from masterfile by >COD_DATE_TOLERANCE_DAYS,
        # flag it so cross-exam output highlights the multi-phase situation.
        if initial_cod and masterfile_cod and initial_cod != masterfile_cod:
            days_diff = abs((masterfile_cod - initial_cod).days)
            if days_diff > COD_DATE_TOLERANCE_DAYS:
                merged["_multi_phase_cod"] = {
                    "initial_cod": str(initial_cod),
                    "masterfile_cod": str(masterfile_cod),
                    "sage_contract_start": str(sage_start) if sage_start else None,
                    "onboarding_cod": str(onboarding_cod) if onboarding_cod else None,
                    "rule": "Using earliest COD for operating year counting",
                }

        verifications.append(self._verify_field(
            "cod_date",
            primary_source="masterfile",
            primary_value=initial_cod or masterfile_cod,
            verification_sources={
                "onboarding": onboarding_cod,
                "sage_contract_start": sage_start,
            },
        ))

        # ─── Contract Term ─────────────────────────────────────────────
        sage_term = None
        if sage_data and sage_data.contract_start_date and sage_data.contract_end_date:
            delta = sage_data.contract_end_date - sage_data.contract_start_date
            sage_term = round(delta.days / 365.25)

        masterfile_term = masterfile_data.term_years if masterfile_data else None
        onboarding_term = onboarding_data.get("contract_term_years") if onboarding_data else None

        verifications.append(self._verify_field(
            "contract_term_years",
            primary_source="sage",
            primary_value=sage_term,
            verification_sources={
                "masterfile": masterfile_term,
                "onboarding": onboarding_term,
            },
        ))

        # ─── Tariff Type Detection ─────────────────────────────────────
        tariff_type = detect_tariff_type(sage_data, masterfile_data)

        # ─── Mother-Child Line Decomposition ───────────────────────────
        line_decomp = self._detect_line_decomposition(sage_data)

        # ─── Build Merged Values ───────────────────────────────────────
        for v in verifications:
            if v.primary_value is not None:
                merged[v.field_name] = v.primary_value
            elif v.verification_sources:
                # Use first non-None verification source
                for src_val in v.verification_sources.values():
                    if src_val is not None:
                        merged[v.field_name] = src_val
                        break

        # Add tariff type detection results to merged (post-059 field names)
        if tariff_type:
            merged["energy_sale_type_id"] = tariff_type.energy_sale_type_code
            merged["escalation_type_id"] = tariff_type.escalation_type_code
            merged["formula_type"] = tariff_type.formula_type
            if tariff_type.mrp_method:
                merged["mrp_method"] = tariff_type.mrp_method

        # ─── Build Single Tariff (MOH01 pattern) ─────────────────────
        # One clause_tariff row with floor/ceiling/discount in logic_parameters
        ext_contract_id = sage_data.primary_contract_number if sage_data else sage_id
        currency = merged.get("contract_currency")

        if merged.get("base_rate") is not None:
            merged["tariff"] = {
                "tariff_group_key": f"{ext_contract_id}-MAIN",
                "base_rate": merged["base_rate"],
                "currency": currency,
                "discount_pct": merged.get("discount_pct"),
                "floor_rate": merged.get("floor_rate"),
                "ceiling_rate": merged.get("ceiling_rate"),
            }

        # Include rate_series from masterfile if available
        if masterfile_data and masterfile_data.rate_series:
            merged["rate_series"] = masterfile_data.rate_series

        # ─── Build Discrepancy List ────────────────────────────────────
        for v in verifications:
            if v.status in ("conflict", "warning"):
                disc = Discrepancy(
                    field=v.field_name,
                    excel_value=v.primary_value,
                    pdf_value=str(v.verification_sources),
                    severity="error" if v.requires_manual_approval else "warning",
                    explanation=v.notes,
                    requires_manual_review=v.requires_manual_approval,
                )
                discrepancies.append(disc)

        # ─── Overall Confidence ────────────────────────────────────────
        if verifications:
            overall = sum(v.confidence for v in verifications) / len(verifications)
        else:
            overall = 0.0

        blocked = len(critical_conflicts) > 0

        return CrossVerificationResult(
            sage_id=sage_id,
            project_name=project_name,
            field_verifications=verifications,
            tariff_type=tariff_type,
            line_decomposition=line_decomp,
            overall_confidence=round(overall, 4),
            merged_values=merged,
            discrepancies=discrepancies,
            critical_conflicts=critical_conflicts,
            blocked=blocked,
            sage_data=sage_data,
            masterfile_data=masterfile_data,
            source_metadata={
                "sources_present": {
                    "sage": sage_data is not None,
                    "masterfile": masterfile_data is not None,
                    "market_ref": market_ref_data is not None,
                    "onboarding": onboarding_data is not None,
                },
            },
        )

    def _verify_field(
        self,
        field_name: str,
        primary_source: str,
        primary_value: Any,
        verification_sources: Dict[str, Any],
        tolerance_pct: Optional[float] = None,
        is_critical: bool = False,
    ) -> FieldVerification:
        """
        Verify a single field across sources using the authority matrix.

        Returns FieldVerification with confidence and status.
        """
        non_null_sources: Dict[str, Any] = {}
        if primary_value is not None:
            non_null_sources[primary_source] = primary_value
        for src, val in verification_sources.items():
            if val is not None:
                non_null_sources[src] = val

        total_sources = len(non_null_sources)

        if total_sources == 0:
            return FieldVerification(
                field_name=field_name,
                primary_source=primary_source,
                primary_value=None,
                verification_sources=verification_sources,
                confidence=0.0,
                status="single_source",
                notes="No data available from any source",
            )

        if total_sources == 1:
            return FieldVerification(
                field_name=field_name,
                primary_source=primary_source,
                primary_value=primary_value,
                verification_sources=verification_sources,
                confidence=0.75,
                status="single_source",
                notes=f"Only available from {list(non_null_sources.keys())[0]}",
            )

        # Check agreement
        values = list(non_null_sources.values())
        ref = values[0]
        all_agree = all(_values_agree(ref, v, tolerance_pct) for v in values[1:])

        if all_agree:
            confidence = 0.95 if total_sources >= 3 else 0.85
            return FieldVerification(
                field_name=field_name,
                primary_source=primary_source,
                primary_value=primary_value,
                verification_sources=verification_sources,
                confidence=confidence,
                status="confirmed",
                variance_pct=_compute_variance_pct(values[0], values[-1]) if len(values) > 1 else None,
                notes=f"{total_sources} sources agree",
            )

        # Disagreement
        variance = _compute_variance_pct(values[0], values[1]) if len(values) >= 2 else None
        requires_approval = is_critical and field_name in CRITICAL_FIELDS

        return FieldVerification(
            field_name=field_name,
            primary_source=primary_source,
            primary_value=primary_value,
            verification_sources=verification_sources,
            confidence=0.40,
            status="conflict",
            variance_pct=variance,
            notes=f"Disagreement: {non_null_sources}",
            requires_manual_approval=requires_approval,
        )

    def _detect_line_decomposition(
        self, sage_data: Optional[SAGEProjectData]
    ) -> Optional[MotherChildPattern]:
        """Detect mother-child line decomposition pattern from SAGE contract lines."""
        if not sage_data or not sage_data.contract_lines:
            return None

        active_energy_lines = [
            l for l in sage_data.contract_lines
            if l.active_status == 1 and l.energy_category in ("metered_energy", "available_energy")
        ]

        if not active_energy_lines:
            return MotherChildPattern(pattern="single_meter")

        # Check for available_energy lines (potential mother lines)
        available_lines = [l for l in active_energy_lines if l.energy_category == "available_energy"]
        metered_lines = [l for l in active_energy_lines if l.energy_category == "metered_energy"]

        if available_lines and metered_lines:
            # Mother (available) + children (metered) pattern
            mother = min(available_lines, key=lambda l: l.contract_line)
            children = sorted(metered_lines, key=lambda l: l.contract_line)
            return MotherChildPattern(
                pattern="mother_children",
                mother_line_number=mother.contract_line,
                child_line_numbers=[c.contract_line for c in children],
                notes=f"Available energy line {mother.contract_line} as mother, "
                      f"{len(children)} metered children",
            )

        # Check for multi-phase (same product across different line numbers)
        product_groups: Dict[str, List[int]] = {}
        for l in active_energy_lines:
            base_product = l.product_desc.split(" - ")[0].strip()
            product_groups.setdefault(base_product, []).append(l.contract_line)

        for product, line_nums in product_groups.items():
            if len(line_nums) > 1:
                return MotherChildPattern(
                    pattern="multi_phase",
                    child_line_numbers=sorted(line_nums),
                    notes=f"Multi-phase: {product} across lines {sorted(line_nums)}",
                )

        return MotherChildPattern(pattern="single_meter")
