"""
Billing Cycle Orchestrator.

Models the monthly billing workflow as a dependency graph (NOT a linear chain):

Layer 1: Verify inputs exist (FX, MRP conditional, meter data)
Layer 2: Compute (parallel branches)
  - Branch A: tariff_rate (needs FX; needs MRP only if floating)
  - Branch B: plant_performance (needs meters; independent of tariff)
Layer 3: Output (needs tariff + meters, NOT performance)
  - expected_invoice generation

Recompute rules:
- FX or reference_price change → supersede tariff_rate → re-generate expected_invoice
- meter_aggregate change → recompute plant_performance AND re-generate expected_invoice
- billing_tax_rule change → re-generate expected_invoice
- tariff_rate change → re-generate expected_invoice
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from db.database import get_db_connection
from models.billing_cycle import BillingCycleResult, BillingCycleStepResult
from services.billing.tariff_rate_service import TariffRateService
from services.billing.performance_service import PerformanceService
from services.billing.invoice_service import InvoiceService

logger = logging.getLogger(__name__)

FLOATING_CODES = frozenset({"REBASED_MARKET_PRICE", "FLOATING_GRID", "FLOATING_GENERATOR", "FLOATING_GRID_GENERATOR"})


class BillingCycleOrchestrator:
    """Run the full monthly billing cycle as a dependency graph."""

    def __init__(self):
        self._tariff_service = TariffRateService()
        self._performance_service = PerformanceService()
        self._invoice_service = InvoiceService()

    def run_cycle(
        self,
        project_id: int,
        billing_month: str,
        force_refresh: bool = False,
        invoice_direction: str = "payable",
    ) -> BillingCycleResult:
        """Run the full billing cycle for a project/month.

        Returns step-by-step status; blocks at first missing prerequisite per branch.
        """
        bm_date = _parse_billing_month(billing_month)
        steps: List[BillingCycleStepResult] = []
        blocked_at = None

        # =====================================================
        # Layer 1: Verify inputs exist
        # =====================================================

        # Determine tariff families present on this project
        has_floating_tariffs = self._has_mrp_tariffs(project_id)
        has_deterministic_tariffs = self._has_deterministic_tariffs(project_id)

        # Check FX rates (only required for floating tariffs)
        fx_ok = True
        if has_floating_tariffs:
            fx_ok, fx_detail = self._check_fx_rates(project_id, bm_date)
            steps.append(BillingCycleStepResult(
                step="check_fx_rates",
                status="verified" if fx_ok else "missing",
                detail=fx_detail,
            ))
        else:
            steps.append(BillingCycleStepResult(
                step="check_fx_rates",
                status="skipped",
                detail={"reason": "No floating tariffs — FX rates not required"},
            ))

        # Check MRP (only required for floating tariffs)
        mrp_ok = True
        if has_floating_tariffs:
            mrp_ok, mrp_detail = self._check_mrp(project_id, bm_date)
            steps.append(BillingCycleStepResult(
                step="check_mrp",
                status="verified" if mrp_ok else "missing",
                detail=mrp_detail,
            ))
        else:
            steps.append(BillingCycleStepResult(
                step="check_mrp",
                status="skipped",
                detail={"reason": "No floating tariffs — MRP not required"},
            ))

        # Check meter data
        meter_ok, meter_detail = self._check_meter_data(project_id, bm_date)
        steps.append(BillingCycleStepResult(
            step="check_meter_data",
            status="verified" if meter_ok else "missing",
            detail=meter_detail,
        ))

        # =====================================================
        # Layer 2: Compute (parallel branches)
        # =====================================================

        # Branch A: tariff_rate
        # Deterministic tariffs: always proceed (no FX/MRP needed)
        # Floating tariffs: need FX + MRP
        # Mixed: proceed — TariffRateService handles per-tariff dispatching
        tariff_ok = False
        can_generate_tariffs = True
        tariff_block_reason = None

        if has_floating_tariffs and not fx_ok:
            can_generate_tariffs = False
            tariff_block_reason = "Missing FX rates for floating tariffs"
        if has_floating_tariffs and not mrp_ok:
            can_generate_tariffs = False
            tariff_block_reason = "Missing MRP data for floating tariffs"

        # If we only have deterministic tariffs, always proceed
        if has_deterministic_tariffs and not has_floating_tariffs:
            can_generate_tariffs = True

        if can_generate_tariffs:
            tariff_result = self._tariff_service.generate(
                project_id=project_id,
                billing_month=billing_month,
                force_refresh=force_refresh,
            )
            tariff_ok = tariff_result.get("success", False)
            steps.append(BillingCycleStepResult(
                step="generate_tariff_rates",
                status="computed" if tariff_ok else "error",
                detail=tariff_result,
            ))
        else:
            steps.append(BillingCycleStepResult(
                step="generate_tariff_rates",
                status="missing",
                detail={"reason": f"Blocked: {tariff_block_reason}"},
            ))
            if not blocked_at:
                blocked_at = "generate_tariff_rates"

        # Branch B: plant_performance (needs meters; independent of tariff)
        perf_ok = False
        if meter_ok:
            perf_result = self._performance_service.compute(
                project_id=project_id,
                billing_month=billing_month,
            )
            perf_ok = perf_result.get("success", False)
            steps.append(BillingCycleStepResult(
                step="compute_plant_performance",
                status="computed" if perf_ok else "error",
                detail=perf_result,
            ))
        else:
            steps.append(BillingCycleStepResult(
                step="compute_plant_performance",
                status="missing",
                detail={"reason": "Blocked: No meter data"},
            ))

        # =====================================================
        # Layer 3: Output (needs tariff + meters, NOT performance)
        # =====================================================
        invoice_ok = False
        if tariff_ok and meter_ok:
            invoice_result = self._invoice_service.generate(
                project_id=project_id,
                billing_month=billing_month,
                invoice_direction=invoice_direction,
            )
            invoice_ok = invoice_result.get("success", False)
            steps.append(BillingCycleStepResult(
                step="generate_expected_invoice",
                status="generated" if invoice_ok else "error",
                detail=invoice_result,
            ))
        else:
            reasons = []
            if not tariff_ok:
                reasons.append("tariff rates not available")
            if not meter_ok:
                reasons.append("meter data not available")
            steps.append(BillingCycleStepResult(
                step="generate_expected_invoice",
                status="missing",
                detail={"reason": f"Blocked: {', '.join(reasons)}"},
            ))
            if not blocked_at:
                blocked_at = "generate_expected_invoice"

        overall_success = tariff_ok and invoice_ok  # perf is independent
        return BillingCycleResult(
            success=overall_success,
            project_id=project_id,
            billing_month=billing_month,
            steps=steps,
            blocked_at=blocked_at,
        )

    def _check_fx_rates(self, project_id: int, bm_date: date) -> tuple[bool, dict]:
        """Check if FX rates exist for this project's billing month."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get project org + tariff currency
                cur.execute("""
                    SELECT ct.organization_id, ct.market_ref_currency_id, ct.currency_id
                    FROM clause_tariff ct
                    WHERE ct.project_id = %s AND ct.is_current = true
                    LIMIT 1
                """, (project_id,))
                row = cur.fetchone()
                if not row:
                    return False, {"error": "No clause_tariff found"}

                ccy_id = row["market_ref_currency_id"] or row["currency_id"]
                org_id = row["organization_id"]

                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM exchange_rate
                    WHERE organization_id = %s AND currency_id = %s
                      AND rate_date >= %s AND rate_date < (%s + INTERVAL '1 month')
                """, (org_id, ccy_id, bm_date, bm_date))
                cnt = cur.fetchone()["cnt"]
                return cnt > 0, {"fx_rate_count": cnt}

    def _has_deterministic_tariffs(self, project_id: int) -> bool:
        """Check if project has any deterministic tariffs."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM clause_tariff ct
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    WHERE ct.project_id = %s AND ct.is_current = true
                      AND esc.code IN ('NONE', 'FIXED_INCREASE', 'FIXED_DECREASE', 'PERCENTAGE')
                    LIMIT 1
                """, (project_id,))
                return cur.fetchone() is not None

    def _has_mrp_tariffs(self, project_id: int) -> bool:
        """Check if project has any floating/rebased tariffs."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM clause_tariff ct
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    WHERE ct.project_id = %s AND ct.is_current = true
                      AND esc.code IN ('REBASED_MARKET_PRICE', 'FLOATING_GRID',
                                       'FLOATING_GENERATOR', 'FLOATING_GRID_GENERATOR')
                    LIMIT 1
                """, (project_id,))
                return cur.fetchone() is not None

    def _check_mrp(self, project_id: int, bm_date: date) -> tuple[bool, dict]:
        """Check if MRP data exists for this project's billing month."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, calculated_mrp_per_kwh FROM reference_price
                    WHERE project_id = %s
                      AND (
                          (observation_type = 'monthly' AND period_start = %s)
                          OR (observation_type = 'annual' AND period_start <= %s
                              AND (period_end IS NULL OR period_end >= %s))
                      )
                    LIMIT 1
                """, (project_id, bm_date, bm_date, bm_date))
                row = cur.fetchone()
                if row:
                    return True, {"reference_price_id": row["id"], "mrp_per_kwh": float(row["calculated_mrp_per_kwh"] or 0)}
                return False, {"error": "No reference_price data found"}

    def _check_meter_data(self, project_id: int, bm_date: date) -> tuple[bool, dict]:
        """Check if meter_aggregate data exists for this project's billing month."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) AS cnt,
                           SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS total_kwh
                    FROM meter_aggregate ma
                    JOIN meter m ON m.id = ma.meter_id
                    WHERE m.project_id = %s
                      AND date_trunc('month', ma.period_start) = %s
                """, (project_id, bm_date))
                row = cur.fetchone()
                cnt = row["cnt"] or 0
                total = float(row["total_kwh"] or 0)
                return cnt > 0, {"meter_aggregate_rows": cnt, "total_kwh": total}


def _parse_billing_month(billing_month: str) -> date:
    parts = billing_month.split("-")
    return date(int(parts[0]), int(parts[1]), 1)
