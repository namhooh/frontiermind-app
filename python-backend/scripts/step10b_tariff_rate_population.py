#!/usr/bin/env python3
"""
Step 10b: Populate tariff_rate rows for all tariffs with base_rate.

Generates:
- Annual tariff_rate rows showing the standing/escalated rate per contract year
- Monthly tariff_rate rows for local-currency tariffs with FX conversion tracking

Follows the KAS01/MOH01 pattern where:
- Annual rows define the standing rate per operating year
- Monthly rows track FX-converted amounts for each billing month

Usage:
    cd python-backend
    python scripts/step10b_tariff_rate_population.py --dry-run
    python scripts/step10b_tariff_rate_population.py
    python scripts/step10b_tariff_rate_population.py --project UGL01
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv

load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

USD_CURRENCY_ID = 1


def main():
    parser = argparse.ArgumentParser(description="Populate tariff_rate rows")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--project", type=str, help="Single sage_id to process")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)

    try:
        tariffs = _fetch_unpopulated_tariffs(conn, args.project)
        print(f"Found {len(tariffs)} tariffs with base_rate to populate")

        if not tariffs:
            return

        if args.dry_run:
            for t in tariffs:
                local_ccy = t["currency_code"] != "USD"
                cur_year = _get_operating_year(t["resolved_valid_from"], date.today())
                esc_label = t["esc_code"] or "flat"
                print(
                    f"  {t['sage_id']:8s} tariff_id={t['tariff_id']:3d} "
                    f"{str(t['base_rate']):>12s} {t['currency_code']:3s} "
                    f"esc={esc_label:12s} yr={cur_year:2d} "
                    f"valid_from={t['resolved_valid_from'] or 'TBD':>12} "
                    f"{'+ FX monthly' if local_ccy else 'USD-only'}"
                )
            return

        stats = {"annual_inserted": 0, "monthly_inserted": 0, "valid_from_updated": 0}

        # Commit any implicit transaction from fetch queries before starting writes
        conn.commit()
        conn.autocommit = False
        with conn.cursor() as cur:
            # 1. Update clause_tariff.valid_from where missing
            for t in tariffs:
                if t["ct_valid_from"] is None and t["resolved_valid_from"] is not None:
                    cur.execute(
                        "UPDATE clause_tariff SET valid_from = %s WHERE id = %s",
                        (t["resolved_valid_from"], t["tariff_id"]),
                    )
                    stats["valid_from_updated"] += cur.rowcount

            # 2. Insert annual tariff_rate rows
            for t in tariffs:
                n = _insert_annual_rows(cur, t)
                stats["annual_inserted"] += n

            # 3. Insert monthly rows for local-currency tariffs
            for t in tariffs:
                if t["currency_code"] != "USD":
                    n = _insert_monthly_rows(cur, t, conn)
                    stats["monthly_inserted"] += n

        conn.commit()

        print(f"\nResults:")
        print(f"  valid_from updated:    {stats['valid_from_updated']}")
        print(f"  Annual rows inserted:  {stats['annual_inserted']}")
        print(f"  Monthly rows inserted: {stats['monthly_inserted']}")

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch_unpopulated_tariffs(conn, sage_id_filter=None):
    """Fetch clause_tariff rows with base_rate that have no tariff_rate entries."""
    with conn.cursor() as cur:
        where_extra = ""
        params = {}
        if sage_id_filter:
            where_extra = "AND p.sage_id = %(sage_id)s"
            params["sage_id"] = sage_id_filter

        cur.execute(
            f"""
            SELECT ct.id AS tariff_id, ct.base_rate, ct.currency_id,
                   ct.valid_from AS ct_valid_from,
                   ct.logic_parameters,
                   ct.project_id,
                   c2.code AS currency_code,
                   et.code AS esc_code,
                   p.sage_id, p.cod_date,
                   c.effective_date, c.end_date, c.contract_term_years
            FROM clause_tariff ct
            JOIN project p ON ct.project_id = p.id
            JOIN contract c ON ct.contract_id = c.id
            JOIN currency c2 ON ct.currency_id = c2.id
            LEFT JOIN escalation_type et ON ct.escalation_type_id = et.id
            WHERE ct.is_active = true
              AND ct.base_rate IS NOT NULL
              AND ct.is_current = true
              AND NOT EXISTS (SELECT 1 FROM tariff_rate tr WHERE tr.clause_tariff_id = ct.id)
              AND COALESCE(et.code, '') != 'REBASED_MARKET_PRICE'
              {where_extra}
            ORDER BY p.sage_id
            """,
            params,
        )

        rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            r["resolved_valid_from"] = _resolve_valid_from(r)
            lp = r["logic_parameters"] or {}
            r["esc_rate"] = Decimal(
                str(lp.get("escalation_rate") or lp.get("escalation_value") or 0)
            )

        return rows


def _resolve_valid_from(t):
    """Derive valid_from from available date fields."""
    for field in ("ct_valid_from", "cod_date", "effective_date"):
        v = t.get(field)
        if v:
            return v.date() if hasattr(v, "date") else v
    # Fallback: derive from end_date - contract_term_years
    end = t.get("end_date")
    term = t.get("contract_term_years")
    if end and term:
        ed = end.date() if hasattr(end, "date") else end
        try:
            return ed.replace(year=ed.year - int(term))
        except ValueError:
            return ed.replace(year=ed.year - int(term), day=28)
    return None


# ---------------------------------------------------------------------------
# Year / rate helpers
# ---------------------------------------------------------------------------


def _get_operating_year(valid_from, target_date):
    """Return operating year number (1-based) for a target date."""
    if not valid_from:
        return 1
    vf = valid_from.date() if hasattr(valid_from, "date") else valid_from
    td = target_date.date() if hasattr(target_date, "date") else target_date
    years = td.year - vf.year
    if (td.month, td.day) < (vf.month, vf.day):
        years -= 1
    return max(1, years + 1)


def _compute_rate(base_rate, esc_code, esc_rate, year):
    """Compute the effective rate for a given operating year."""
    base = Decimal(str(base_rate))
    if year <= 1 or not esc_code:
        return base
    if esc_code == "PERCENTAGE" and esc_rate:
        multiplier = (1 + esc_rate) ** (year - 1)
        return (base * multiplier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    # NONE, US_CPI (no CPI data), or unknown → flat
    return base


def _add_years(d, years):
    """Add N years to a date, handling Feb 29 → Feb 28."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


# ---------------------------------------------------------------------------
# Annual rows
# ---------------------------------------------------------------------------


def _insert_annual_rows(cur, t):
    """Insert annual tariff_rate rows for a tariff."""
    tariff_id = t["tariff_id"]
    base_rate = Decimal(str(t["base_rate"]))
    currency_id = t["currency_id"]
    esc_code = t["esc_code"]
    esc_rate = t["esc_rate"]
    valid_from = t["resolved_valid_from"]
    term_years = t["contract_term_years"] or 1

    today = date.today()
    current_year = _get_operating_year(valid_from, today) if valid_from else 1

    # For PERCENTAGE with valid_from: create all years up to current + 1
    # For others: just create one annual row for current year
    if esc_code == "PERCENTAGE" and valid_from and esc_rate:
        max_year = min(current_year + 1, term_years)
        years_to_create = range(1, max_year + 1)
    else:
        years_to_create = [current_year]

    inserted = 0
    for year in years_to_create:
        rate = _compute_rate(base_rate, esc_code, esc_rate, year)
        is_current = year == current_year

        # Period dates
        if valid_from:
            period_start = _add_years(valid_from, year - 1)
            period_end = (
                _add_years(valid_from, year) - timedelta(days=1)
                if year < term_years
                else None
            )
        else:
            period_start = None
            period_end = None

        # Calculation basis
        if year == 1:
            basis = "Year 1: original contractual base rate"
        elif esc_code == "PERCENTAGE" and esc_rate:
            pct = float(esc_rate * 100)
            basis = f"Year {year}: {base_rate} × (1 + {pct}%)^{year - 1}"
        else:
            basis = f"Year {year}: flat rate (no escalation)"

        # Currency mapping
        is_usd = currency_id == USD_CURRENCY_ID
        hard_id = USD_CURRENCY_ID
        local_id = USD_CURRENCY_ID if is_usd else currency_id
        billing_id = local_id

        if is_usd:
            contract_rate = hard_rate = local_rate = billing_rate = rate
            contract_role = "hard"
        else:
            contract_rate = local_rate = billing_rate = rate
            hard_rate = rate  # placeholder; monthly rows have the real FX-converted rate
            contract_role = "local"

        calc_detail = json.dumps(
            {
                "source": "population_v1",
                "year": year,
                "base_rate": float(base_rate),
                "escalation_code": esc_code,
                "escalation_rate": float(esc_rate) if esc_rate else None,
            }
        )

        cur.execute(
            """
            INSERT INTO tariff_rate (
                clause_tariff_id, contract_year, rate_granularity,
                period_start, period_end,
                hard_currency_id, local_currency_id, billing_currency_id,
                effective_rate_contract_ccy, effective_rate_hard_ccy,
                effective_rate_local_ccy, effective_rate_billing_ccy,
                effective_rate_contract_role,
                calc_detail,
                rate_binding, formula_version, calc_status,
                calculation_basis, is_current
            ) VALUES (
                %s, %s, 'annual',
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s,
                %s::jsonb,
                'fixed', 'population_v1', 'computed',
                %s, %s
            )
            ON CONFLICT (clause_tariff_id, contract_year)
                WHERE rate_granularity = 'annual'
            DO NOTHING
            """,
            (
                tariff_id,
                year,
                period_start,
                period_end,
                hard_id,
                local_id,
                billing_id,
                contract_rate,
                hard_rate,
                local_rate,
                billing_rate,
                contract_role,
                calc_detail,
                basis,
                is_current,
            ),
        )
        inserted += cur.rowcount

    if inserted:
        logger.info(f"  {t['sage_id']}: {inserted} annual rows (current yr {current_year})")

    return inserted


# ---------------------------------------------------------------------------
# Monthly rows (local-currency FX tracking)
# ---------------------------------------------------------------------------


def _insert_monthly_rows(cur, t, conn):
    """Insert monthly tariff_rate rows for local-currency tariffs with FX tracking."""
    tariff_id = t["tariff_id"]
    base_rate = Decimal(str(t["base_rate"]))
    currency_id = t["currency_id"]
    currency_code = t["currency_code"]
    esc_code = t["esc_code"]
    esc_rate = t["esc_rate"]
    valid_from = t["resolved_valid_from"]

    # Fetch exchange rates for this currency
    with conn.cursor() as cur2:
        cur2.execute(
            """
            SELECT id, rate_date, rate
            FROM exchange_rate
            WHERE currency_id = %s
            ORDER BY rate_date DESC
            """,
            (currency_id,),
        )
        fx_rates = [dict(r) for r in cur2.fetchall()]

    if not fx_rates:
        logger.info(f"  {t['sage_id']}: no FX data for {currency_code}, skipping monthly")
        return 0

    today = date.today()
    current_year = _get_operating_year(valid_from, today) if valid_from else 1
    latest_month_raw = fx_rates[0]["rate_date"]
    latest_month = (
        latest_month_raw.date() if hasattr(latest_month_raw, "date") else latest_month_raw
    )

    inserted = 0
    for fx in fx_rates:
        billing_month_raw = fx["rate_date"]
        billing_month = (
            billing_month_raw.date()
            if hasattr(billing_month_raw, "date")
            else billing_month_raw
        )
        fx_rate_value = Decimal(str(fx["rate"]))
        fx_id = fx["id"]

        # For PERCENTAGE tariffs: compute escalated rate for the correct year
        # For flat tariffs: all months use the same base_rate → assign to current year
        if esc_code == "PERCENTAGE" and esc_rate and valid_from:
            year = _get_operating_year(valid_from, billing_month)
            local_rate = _compute_rate(base_rate, esc_code, esc_rate, year)
        else:
            year = current_year
            local_rate = base_rate

        # USD equivalent via FX
        hard_rate = (local_rate / fx_rate_value).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )

        is_current_month = billing_month == latest_month

        # period_start/end for monthly rows: the billing month boundaries
        month_end = (billing_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

        cur.execute(
            """
            INSERT INTO tariff_rate (
                clause_tariff_id, contract_year, rate_granularity, billing_month,
                period_start, period_end,
                hard_currency_id, local_currency_id, billing_currency_id,
                effective_rate_contract_ccy, effective_rate_hard_ccy,
                effective_rate_local_ccy, effective_rate_billing_ccy,
                effective_rate_contract_role,
                fx_rate_local_id,
                rate_binding, formula_version, calc_status,
                calculation_basis, is_current
            ) VALUES (
                %s, %s, 'monthly', %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                'local',
                %s,
                'fixed', 'population_v1', 'computed',
                %s, %s
            )
            ON CONFLICT (clause_tariff_id, billing_month)
                WHERE rate_granularity = 'monthly'
            DO NOTHING
            """,
            (
                tariff_id,
                year,
                billing_month,
                billing_month,
                month_end,
                USD_CURRENCY_ID,
                currency_id,
                currency_id,
                local_rate,
                hard_rate,
                local_rate,
                local_rate,
                fx_id,
                f"{base_rate} {currency_code} / {fx_rate_value} = {hard_rate} USD",
                is_current_month,
            ),
        )
        inserted += cur.rowcount

    if inserted:
        logger.info(f"  {t['sage_id']}: {inserted} monthly FX rows ({currency_code})")

    return inserted


if __name__ == "__main__":
    main()
