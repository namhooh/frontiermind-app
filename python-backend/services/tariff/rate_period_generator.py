"""
Tariff Rate Period Generator.

Computes effective rates for Years 2..N for deterministic escalation types
(NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE) and batch-inserts them
into tariff_annual_rate.

Non-deterministic types (US_CPI, REBASED_MARKET_PRICE) are skipped — they
require external data feeds.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List

from db.database import get_db_connection

logger = logging.getLogger(__name__)

DETERMINISTIC_CODES = frozenset({"NONE", "FIXED_INCREASE", "FIXED_DECREASE", "PERCENTAGE"})


class RatePeriodGenerator:
    """Generate tariff_annual_rate rows for deterministic escalation types."""

    def generate(self, project_id: int) -> Dict[str, int]:
        """
        Main entry point.  For each current clause_tariff with a deterministic
        escalation type, compute Years 2..N and batch INSERT.

        Returns {"tariffs_processed": M, "periods_generated": N}.
        """
        tariffs = self._fetch_tariffs(project_id)
        if not tariffs:
            logger.info(f"No deterministic tariffs found for project {project_id}")
            return {"tariffs_processed": 0, "periods_generated": 0}

        total_periods = 0

        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    for t in tariffs:
                        n = self._process_tariff(cur, t)
                        total_periods += n
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        logger.info(
            f"Rate period generation complete: {len(tariffs)} tariffs, "
            f"{total_periods} periods generated for project {project_id}"
        )
        return {"tariffs_processed": len(tariffs), "periods_generated": total_periods}

    def _fetch_tariffs(self, project_id: int) -> List[Dict[str, Any]]:
        """Fetch clause_tariff rows with deterministic escalation types."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ct.id, ct.base_rate, ct.valid_from, ct.currency_id,
                           ct.logic_parameters, esc.code AS escalation_type_code,
                           c.contract_term_years
                    FROM clause_tariff ct
                    JOIN contract c ON ct.contract_id = c.id
                    JOIN escalation_type esc ON esc.id = ct.escalation_type_id
                    WHERE ct.project_id = %s
                      AND ct.is_current = true
                      AND ct.base_rate IS NOT NULL
                      AND esc.code IN ('NONE', 'FIXED_INCREASE', 'FIXED_DECREASE', 'PERCENTAGE')
                    """,
                    (project_id,),
                )
                return [dict(row) for row in cur.fetchall()]

    def _process_tariff(self, cur, tariff: Dict[str, Any]) -> int:
        """Compute and insert rate periods for a single tariff. Returns count of new rows."""
        ct_id = tariff["id"]
        base_rate = Decimal(str(tariff["base_rate"]))
        valid_from = tariff["valid_from"]
        currency_id = tariff["currency_id"]
        esc_code = tariff["escalation_type_code"]
        term_years = tariff["contract_term_years"] or 1
        lp = tariff["logic_parameters"] or {}

        escalation_value = Decimal(str(lp.get("escalation_value") or 0))
        escalation_start_date_str = lp.get("escalation_start_date")

        # If valid_from is a datetime, extract the date
        if hasattr(valid_from, "date"):
            valid_from = valid_from.date()

        today = date.today()

        # Build list of (year, period_start, period_end, effective_tariff, basis)
        periods: List[tuple] = []

        for year in range(1, term_years + 1):
            # --- period_start ---
            if year == 1:
                p_start = valid_from
            elif year == 2 and escalation_start_date_str:
                p_start = date.fromisoformat(str(escalation_start_date_str))
            else:
                # Derive from escalation_start_date for year 2+ if available
                if escalation_start_date_str:
                    esc_start = date.fromisoformat(str(escalation_start_date_str))
                    p_start = _add_years(esc_start, year - 2)
                else:
                    p_start = _add_years(valid_from, year - 1)

            # --- effective_tariff ---
            rate, basis = _compute_rate(esc_code, base_rate, escalation_value, year)

            periods.append((year, p_start, rate, basis))

        # --- period_end: each year ends the day before the next starts; last year is NULL ---
        period_rows = []
        for i, (year, p_start, rate, basis) in enumerate(periods):
            if i + 1 < len(periods):
                p_end = periods[i + 1][1] - timedelta(days=1)
            else:
                p_end = None
            period_rows.append((year, p_start, p_end, rate, basis))

        # --- is_current: only the period containing today ---
        current_year = None
        for year, p_start, p_end, rate, basis in period_rows:
            if p_start <= today and (p_end is None or today <= p_end):
                current_year = year
                break

        # --- Update Year 1 row (already exists): set period_end and is_current ---
        year1_end = period_rows[0][2] if period_rows else None
        year1_is_current = (current_year == 1)

        # Clear is_current on all existing rows for this tariff first
        # (required by the unique partial index on is_current)
        cur.execute(
            "UPDATE tariff_annual_rate SET is_current = false WHERE clause_tariff_id = %s AND is_current = true",
            (ct_id,),
        )

        # Update Year 1's period_end and final_effective_tariff
        cur.execute(
            """
            UPDATE tariff_annual_rate
            SET period_end = %s, is_current = %s,
                final_effective_tariff = effective_tariff,
                final_effective_tariff_source = 'annual'
            WHERE clause_tariff_id = %s AND contract_year = 1
            """,
            (year1_end, year1_is_current, ct_id),
        )

        # --- Insert Years 2..N ---
        inserted = 0
        for year, p_start, p_end, rate, basis in period_rows:
            if year == 1:
                continue  # Already exists
            is_current = (year == current_year)
            cur.execute(
                """
                INSERT INTO tariff_annual_rate
                    (clause_tariff_id, contract_year, period_start, period_end,
                     effective_tariff, currency_id, calculation_basis, is_current,
                     final_effective_tariff, final_effective_tariff_source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'annual')
                ON CONFLICT (clause_tariff_id, contract_year) DO NOTHING
                """,
                (ct_id, year, p_start, p_end, rate, currency_id, basis, is_current, rate),
            )
            inserted += cur.rowcount

        # Set the correct is_current row (in case ON CONFLICT skipped inserts
        # but the current year changed)
        if current_year and current_year > 1:
            cur.execute(
                """
                UPDATE tariff_annual_rate
                SET is_current = true
                WHERE clause_tariff_id = %s AND contract_year = %s
                """,
                (ct_id, current_year),
            )

        return inserted


def _compute_rate(
    esc_code: str,
    base_rate: Decimal,
    escalation_value: Decimal,
    year: int,
) -> tuple[Decimal, str]:
    """Return (effective_tariff, calculation_basis) for a given year."""
    if year == 1:
        return base_rate, "Year 1: original contractual base rate"

    y_minus_1 = year - 1

    if esc_code == "NONE":
        return base_rate, f"Year {year}: flat rate (no escalation)"

    if esc_code == "FIXED_INCREASE":
        rate = base_rate + escalation_value * y_minus_1
        return rate, f"Year {year}: {base_rate} + {escalation_value} x {y_minus_1}"

    if esc_code == "FIXED_DECREASE":
        rate = max(Decimal(0), base_rate - escalation_value * y_minus_1)
        return rate, f"Year {year}: max(0, {base_rate} - {escalation_value} x {y_minus_1})"

    if esc_code == "PERCENTAGE":
        multiplier = (1 + escalation_value) ** y_minus_1
        rate = (base_rate * multiplier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        return rate, f"Year {year}: {base_rate} x (1 + {escalation_value})^{y_minus_1}"

    # Should not reach here for deterministic types
    return base_rate, f"Year {year}: unknown escalation type {esc_code}"


def _add_years(d: date, years: int) -> date:
    """Add N years to a date, handling Feb 29 → Feb 28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 in a leap year → Feb 28 in non-leap year
        return d.replace(year=d.year + years, day=28)
