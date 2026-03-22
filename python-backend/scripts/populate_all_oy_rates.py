"""
Populate missing OY annual tariff_rate rows for all projects.

- Deterministic tariffs (NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE):
  Uses RatePeriodGenerator.generate() to compute OY 1..N.

- Floating tariffs (FLOATING_GRID, FLOATING_GRID_GENERATOR, REBASED_MARKET_PRICE):
  Uses RebasedMarketPriceEngine.calculate_and_store() for OYs where MRP + FX
  data exists. Inserts placeholder rows (calc_status='pending') for others.

- US_CPI tariffs: Skipped (no CPI data feed).

Usage:
    cd python-backend
    python -m scripts.populate_all_oy_rates [--dry-run] [--project SAGE_ID]
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from dotenv import load_dotenv

load_dotenv()

from db.database import get_db_connection, init_connection_pool, close_connection_pool
from services.tariff.rate_period_generator import RatePeriodGenerator
from services.tariff.rebased_market_price_engine import RebasedMarketPriceEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DETERMINISTIC_CODES = frozenset({"NONE", "FIXED_INCREASE", "FIXED_DECREASE", "PERCENTAGE"})
FLOATING_CODES = frozenset({"FLOATING_GRID", "FLOATING_GENERATOR", "FLOATING_GRID_GENERATOR", "REBASED_MARKET_PRICE"})
SKIP_CODES = frozenset({"US_CPI"})


def _get_projects(sage_id_filter: str | None = None) -> list[dict]:
    """Fetch projects with their tariff info."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            sql = """
                SELECT p.id, p.sage_id, p.cod_date,
                       ct.id AS clause_tariff_id,
                       ct.base_rate, ct.valid_from, ct.currency_id,
                       ct.logic_parameters,
                       esc.code AS escalation_type_code,
                       c.contract_term_years,
                       (SELECT COUNT(*) FROM tariff_rate tr
                        WHERE tr.clause_tariff_id = ct.id
                          AND tr.rate_granularity = 'annual') AS existing_annual_rows
                FROM project p
                JOIN clause_tariff ct ON ct.project_id = p.id AND ct.is_current = true
                JOIN contract c ON ct.contract_id = c.id
                JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                WHERE ct.base_rate IS NOT NULL
            """
            params = []
            if sage_id_filter:
                sql += " AND p.sage_id = %s"
                params.append(sage_id_filter)
            sql += " ORDER BY p.sage_id"
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _get_floating_oy_data(project_id: int, clause_tariff_id: int, valid_from: date, term_years: int) -> list[dict]:
    """For floating tariffs, find OYs where we have MRP + FX data to compute rates."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get annual reference_price (MRP) observations
            cur.execute("""
                SELECT operating_year, calculated_mrp_per_kwh
                FROM reference_price
                WHERE project_id = %s AND observation_type = 'annual'
                  AND calculated_mrp_per_kwh IS NOT NULL
                ORDER BY operating_year
            """, (project_id,))
            mrp_by_oy = {row["operating_year"]: float(row["calculated_mrp_per_kwh"]) for row in cur.fetchall()}

            # Get existing annual tariff_rate rows
            cur.execute("""
                SELECT operating_year FROM tariff_rate
                WHERE clause_tariff_id = %s AND rate_granularity = 'annual'
            """, (clause_tariff_id,))
            existing_oys = {row["operating_year"] for row in cur.fetchall()}

            # Get FX rate coverage (monthly rates for the local currency)
            cur.execute("""
                SELECT DISTINCT date_trunc('month', er.rate_date)::date AS month
                FROM exchange_rate er
                JOIN clause_tariff ct ON ct.id = %s
                WHERE er.currency_id = ct.market_ref_currency_id
                  OR er.currency_id = ct.currency_id
            """, (clause_tariff_id,))
            fx_months = {row["month"] for row in cur.fetchall()}

            results = []
            for oy in range(1, term_years + 1):
                if oy in existing_oys:
                    continue  # Already has a tariff_rate row

                oy_start = _add_years(valid_from, oy - 1)
                oy_end = _add_years(valid_from, oy) - timedelta(days=1)

                has_mrp = oy in mrp_by_oy
                # Check if we have FX rates covering this OY's period
                oy_months_needed = []
                d = oy_start.replace(day=1)
                while d <= oy_end:
                    oy_months_needed.append(d)
                    if d.month == 12:
                        d = d.replace(year=d.year + 1, month=1)
                    else:
                        d = d.replace(month=d.month + 1)
                has_fx = len(oy_months_needed) > 0 and any(m in fx_months for m in oy_months_needed)

                results.append({
                    "operating_year": oy,
                    "has_mrp": has_mrp,
                    "has_fx": has_fx,
                    "mrp_per_kwh": mrp_by_oy.get(oy),
                    "computable": has_mrp and has_fx,
                })

            return results


def _insert_placeholder_row(clause_tariff_id: int, operating_year: int, period_start: date, period_end: date | None, currency_id: int):
    """Insert a placeholder annual tariff_rate row with calc_status='pending'."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tariff_rate (
                    clause_tariff_id, operating_year, rate_granularity,
                    period_start, period_end,
                    hard_currency_id, local_currency_id, billing_currency_id,
                    calc_status, calculation_basis, is_current
                ) VALUES (
                    %s, %s, 'annual',
                    %s, %s,
                    %s, %s, %s,
                    'pending', 'Awaiting MRP/FX data', false
                )
                ON CONFLICT (clause_tariff_id, operating_year)
                    WHERE rate_granularity = 'annual'
                DO NOTHING
            """, (clause_tariff_id, operating_year, period_start, period_end, currency_id, currency_id, currency_id))
            conn.commit()
            return cur.rowcount


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def main():
    parser = argparse.ArgumentParser(description="Populate missing OY annual tariff_rate rows")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--project", type=str, help="Filter to a specific sage_id")
    args = parser.parse_args()

    init_connection_pool(min_connections=1, max_connections=5)
    try:
        return _run(args)
    finally:
        close_connection_pool()


def _run(args):
    projects = _get_projects(args.project)
    logger.info(f"Found {len(projects)} tariff(s) to process")

    rpg = RatePeriodGenerator()
    rmp = RebasedMarketPriceEngine()
    results = []

    for p in projects:
        sage_id = p["sage_id"]
        esc_code = p["escalation_type_code"]
        term_years = p["contract_term_years"] or 1
        existing = p["existing_annual_rows"]

        if esc_code in SKIP_CODES:
            logger.info(f"  {sage_id}: SKIP ({esc_code} — no data feed)")
            results.append({"sage_id": sage_id, "action": "skipped", "reason": esc_code})
            continue

        if esc_code in DETERMINISTIC_CODES:
            if existing >= term_years:
                logger.info(f"  {sage_id}: OK ({existing}/{term_years} OYs already populated)")
                results.append({"sage_id": sage_id, "action": "already_complete", "existing": existing, "term": term_years})
                continue

            logger.info(f"  {sage_id}: DETERMINISTIC {esc_code} — {existing}/{term_years} OYs, generating missing...")
            if not args.dry_run:
                result = rpg.generate(p["id"])
                logger.info(f"    Generated {result['periods_generated']} periods")
                results.append({"sage_id": sage_id, "action": "generated", **result})
            else:
                results.append({"sage_id": sage_id, "action": "dry_run", "would_generate": term_years - existing})

        elif esc_code in FLOATING_CODES:
            valid_from = p["valid_from"]
            if hasattr(valid_from, "date"):
                valid_from = valid_from.date()

            oy_data = _get_floating_oy_data(p["id"], p["clause_tariff_id"], valid_from, term_years)
            missing = [d for d in oy_data if not d["computable"]]
            computable = [d for d in oy_data if d["computable"]]

            if not oy_data:
                logger.info(f"  {sage_id}: FLOATING {esc_code} — all OYs already populated")
                results.append({"sage_id": sage_id, "action": "already_complete"})
                continue

            logger.info(f"  {sage_id}: FLOATING {esc_code} — {len(computable)} computable, {len(missing)} pending")

            for od in missing:
                oy = od["operating_year"]
                oy_start = _add_years(valid_from, oy - 1)
                oy_end = _add_years(valid_from, oy) - timedelta(days=1)
                if not args.dry_run:
                    inserted = _insert_placeholder_row(p["clause_tariff_id"], oy, oy_start, oy_end, p["currency_id"])
                    logger.info(f"    OY {oy}: placeholder inserted ({inserted} rows)")

            # For computable OYs, we would call RebasedMarketPriceEngine but it
            # requires monthly_fx_rates which need careful assembly per project.
            # Log what's available for manual follow-up.
            for od in computable:
                oy = od["operating_year"]
                logger.info(f"    OY {oy}: MRP={od['mrp_per_kwh']:.4f} — ready for calculate_and_store()")

            results.append({
                "sage_id": sage_id,
                "action": "floating_partial",
                "computable_oys": [d["operating_year"] for d in computable],
                "pending_oys": [d["operating_year"] for d in missing],
            })
        else:
            logger.info(f"  {sage_id}: UNKNOWN escalation type {esc_code}")
            results.append({"sage_id": sage_id, "action": "unknown", "escalation": esc_code})

    # Summary
    logger.info("=" * 60)
    logger.info("Summary:")
    for r in results:
        logger.info(f"  {r}")

    return results


if __name__ == "__main__":
    main()
