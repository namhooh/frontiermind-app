"""
Tariff Rate Service.

Dispatches tariff rate generation for a project/billing_month:
- Deterministic (NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE) → RatePeriodGenerator
- Floating (REBASED_MARKET_PRICE) → RebasedMarketPriceEngine (after verifying FX + MRP exist)
- US_CPI → skipped (requires external CPI feed)
"""

import logging
from datetime import date
from typing import Any, Dict, Optional

from db.database import get_db_connection
from services.tariff.rate_period_generator import RatePeriodGenerator
from services.tariff.rebased_market_price_engine import RebasedMarketPriceEngine

logger = logging.getLogger(__name__)

DETERMINISTIC_CODES = frozenset({"NONE", "FIXED_INCREASE", "FIXED_DECREASE", "PERCENTAGE"})
FLOATING_CODES = frozenset({"REBASED_MARKET_PRICE", "FLOATING_GRID", "FLOATING_GENERATOR", "FLOATING_GRID_GENERATOR"})


class TariffRateService:
    """Generate tariff rates for a project billing month."""

    def __init__(self):
        self._rate_generator = RatePeriodGenerator()
        self._rebased_engine = RebasedMarketPriceEngine()

    def generate(
        self,
        project_id: int,
        billing_month: str,
        operating_year: Optional[int] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Generate tariff rates for a project.

        Returns dict with status and details per tariff type.
        """
        bm_date = _parse_billing_month(billing_month)

        # Fetch clause_tariff(s) for this project
        tariffs = self._fetch_all_tariffs(project_id)
        if not tariffs:
            return {
                "success": False,
                "error": f"No current clause_tariff found for project {project_id}",
            }

        results = []
        has_error = False

        # Group tariffs by family to avoid redundant work
        has_deterministic = any(t["escalation_type_code"] in DETERMINISTIC_CODES for t in tariffs)
        deterministic_done = False

        for tariff in tariffs:
            esc_code = tariff["escalation_type_code"]

            if esc_code in DETERMINISTIC_CODES:
                # RatePeriodGenerator.generate() handles all deterministic tariffs
                # for a project in one call — only run it once
                if not deterministic_done:
                    result = self._generate_deterministic(project_id, tariff, force_refresh)
                    results.append(result)
                    deterministic_done = True

            elif esc_code in FLOATING_CODES:
                result = self._generate_floating(
                    project_id, tariff, bm_date, operating_year, force_refresh
                )
                results.append(result)
                if not result.get("success", False):
                    has_error = True

            elif esc_code == "US_CPI":
                results.append({
                    "tariff_type": "US_CPI",
                    "clause_tariff_id": tariff["id"],
                    "status": "skipped",
                    "reason": "US_CPI requires external CPI feed — not yet supported",
                })

            else:
                results.append({
                    "tariff_type": esc_code,
                    "clause_tariff_id": tariff["id"],
                    "status": "skipped",
                    "reason": f"Unknown escalation type: {esc_code}",
                })

        return {
            "success": not has_error,
            "project_id": project_id,
            "billing_month": billing_month,
            "tariff_results": results,
        }

    def _generate_deterministic(
        self, project_id: int, tariff: dict, force_refresh: bool
    ) -> Dict[str, Any]:
        """Generate deterministic tariff rates via RatePeriodGenerator."""
        try:
            result = self._rate_generator.generate(project_id)
            return {
                "tariff_type": tariff["escalation_type_code"],
                "clause_tariff_id": tariff["id"],
                "status": "computed",
                "success": True,
                **result,
            }
        except Exception as e:
            logger.error(f"Deterministic rate generation failed for project {project_id}: {e}", exc_info=True)
            return {
                "tariff_type": tariff["escalation_type_code"],
                "clause_tariff_id": tariff["id"],
                "status": "error",
                "success": False,
                "error": str(e),
            }

    def _generate_floating(
        self,
        project_id: int,
        tariff: dict,
        bm_date: date,
        operating_year: Optional[int],
        force_refresh: bool,
    ) -> Dict[str, Any]:
        """Generate floating tariff rates via RebasedMarketPriceEngine.

        Verifies FX rates and MRP data exist before computing.
        """
        ct_id = tariff["id"]
        org_id = tariff.get("organization_id")

        # Resolve operating year from COD if not provided
        if operating_year is None:
            operating_year = self._derive_operating_year(project_id, bm_date)
            if operating_year is None:
                return {
                    "tariff_type": tariff["escalation_type_code"],
                    "clause_tariff_id": ct_id,
                    "status": "error",
                    "success": False,
                    "error": "Cannot derive operating_year — project has no cod_date",
                }

        # Check if rates already exist (skip if not force_refresh)
        if not force_refresh:
            existing = self._check_existing_rates(ct_id, bm_date)
            if existing:
                return {
                    "tariff_type": tariff["escalation_type_code"],
                    "clause_tariff_id": ct_id,
                    "status": "verified",
                    "success": True,
                    "detail": "Tariff rates already exist for this period",
                }

        # Check FX rates
        fx_rates = self._fetch_fx_rates(project_id, tariff, bm_date, operating_year)
        if not fx_rates:
            return {
                "tariff_type": tariff["escalation_type_code"],
                "clause_tariff_id": ct_id,
                "status": "missing",
                "success": False,
                "error": "Missing FX rates for billing period",
                "blocked_by": "exchange_rate",
            }

        # Check MRP
        mrp_per_kwh = self._fetch_mrp(project_id, bm_date, operating_year)
        if mrp_per_kwh is None:
            return {
                "tariff_type": tariff["escalation_type_code"],
                "clause_tariff_id": ct_id,
                "status": "missing",
                "success": False,
                "error": "Missing MRP data for billing period",
                "blocked_by": "reference_price",
            }

        # Compute
        try:
            result = self._rebased_engine.calculate_and_store(
                project_id=project_id,
                operating_year=operating_year,
                mrp_per_kwh=float(mrp_per_kwh),
                monthly_fx_rates=fx_rates,
            )
            return {
                "tariff_type": tariff["escalation_type_code"],
                "clause_tariff_id": ct_id,
                "status": "computed",
                **result,
            }
        except Exception as e:
            logger.error(f"Floating rate generation failed for project {project_id}: {e}", exc_info=True)
            return {
                "tariff_type": tariff["escalation_type_code"],
                "clause_tariff_id": ct_id,
                "status": "error",
                "success": False,
                "error": str(e),
            }

    def _fetch_all_tariffs(self, project_id: int) -> list:
        """Fetch all current clause_tariff rows for a project."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ct.id, ct.base_rate, ct.valid_from, ct.currency_id,
                           ct.market_ref_currency_id, ct.logic_parameters,
                           ct.organization_id, ct.project_id,
                           esc.code AS escalation_type_code,
                           c.contract_term_years
                    FROM clause_tariff ct
                    JOIN contract c ON ct.contract_id = c.id
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    WHERE ct.project_id = %s AND ct.is_current = true
                """, (project_id,))
                return [dict(row) for row in cur.fetchall()]

    def _derive_operating_year(self, project_id: int, bm_date: date) -> Optional[int]:
        """Derive operating year from COD date."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT cod_date FROM project WHERE id = %s", (project_id,))
                row = cur.fetchone()
                if not row or not row["cod_date"]:
                    return None
                cod = row["cod_date"]
                months_since = (bm_date.year - cod.year) * 12 + (bm_date.month - cod.month)
                if months_since < 0:
                    return 0
                return (months_since // 12) + 1

    def _check_existing_rates(self, clause_tariff_id: int, bm_date: date) -> bool:
        """Check if tariff rates already exist for this period."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 1 FROM tariff_rate
                    WHERE clause_tariff_id = %s
                      AND (billing_month = %s OR (period_start <= %s AND (period_end IS NULL OR period_end >= %s)))
                      AND calc_status IN ('computed', 'approved')
                    LIMIT 1
                """, (clause_tariff_id, bm_date, bm_date, bm_date))
                return cur.fetchone() is not None

    def _fetch_fx_rates(
        self, project_id: int, tariff: dict, bm_date: date, operating_year: int
    ) -> Optional[list]:
        """Fetch monthly FX rates for the contract year containing bm_date."""
        valid_from = tariff.get("valid_from")
        if hasattr(valid_from, "date"):
            valid_from = valid_from.date()
        if not valid_from:
            return None

        market_ref_ccy = tariff.get("market_ref_currency_id") or tariff.get("currency_id")
        org_id = tariff.get("organization_id")

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get FX rates for months in this operating year
                year_start = _add_years(valid_from, operating_year - 1)
                year_end = _add_years(valid_from, operating_year)

                cur.execute("""
                    SELECT er.rate_date, er.rate
                    FROM exchange_rate er
                    WHERE er.organization_id = %s
                      AND er.currency_id = %s
                      AND er.rate_date >= %s
                      AND er.rate_date < %s
                    ORDER BY er.rate_date
                """, (org_id, market_ref_ccy, year_start, year_end))
                rows = cur.fetchall()

                if not rows:
                    return None

                # Build monthly_fx_rates list
                monthly = []
                for row in rows:
                    rd = row["rate_date"]
                    if hasattr(rd, "date"):
                        rd = rd.date()
                    monthly.append({
                        "billing_month": date(rd.year, rd.month, 1),
                        "fx_rate": float(row["rate"]),
                        "rate_date": rd,
                    })
                return monthly

    def _fetch_mrp(self, project_id: int, bm_date: date, operating_year: int) -> Optional[float]:
        """Fetch calculated MRP per kWh for the billing period."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Try monthly first
                cur.execute("""
                    SELECT calculated_mrp_per_kwh FROM reference_price
                    WHERE project_id = %s
                      AND observation_type = 'monthly'
                      AND period_start = %s
                    LIMIT 1
                """, (project_id, bm_date))
                row = cur.fetchone()
                if row and row["calculated_mrp_per_kwh"] is not None:
                    return float(row["calculated_mrp_per_kwh"])

                # Fallback to annual
                cur.execute("""
                    SELECT calculated_mrp_per_kwh FROM reference_price
                    WHERE project_id = %s
                      AND observation_type = 'annual'
                      AND operating_year = %s
                    LIMIT 1
                """, (project_id, operating_year))
                row = cur.fetchone()
                if row and row["calculated_mrp_per_kwh"] is not None:
                    return float(row["calculated_mrp_per_kwh"])

                return None


def _parse_billing_month(billing_month: str) -> date:
    """Parse 'YYYY-MM' to date(YYYY, MM, 1)."""
    parts = billing_month.split("-")
    return date(int(parts[0]), int(parts[1]), 1)


def _add_years(d: date, years: int) -> date:
    """Add N years to a date, handling Feb 29 → Feb 28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
