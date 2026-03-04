#!/usr/bin/env python3
"""
Populate monthly MRP (Market Reference Price) observations from the Market Ref Pricing workbook.

Parses per-project sheets from 'Sage Contract Extracts market Ref pricing data.xlsx'
and upserts into the reference_price table.

Usage:
    cd python-backend

    # Single project
    python scripts/populate_mrp_from_excel.py --project KAS01
    python scripts/populate_mrp_from_excel.py --project KAS01 --dry-run

    # All projects in workbook
    python scripts/populate_mrp_from_excel.py --all --dry-run
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import get_db_connection, init_connection_pool, close_connection_pool
from services.onboarding.parsers.market_ref_pricing_parser import MarketRefPricingParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("populate_mrp")

# Default Excel file path (relative to project root)
DEFAULT_EXCEL_PATH = os.path.join(
    str(project_root.parent),
    "CBE_data_extracts",
    "Sage Contract Extracts market Ref pricing data.xlsx",
)

# sage_id → local currency code fallback (used when clause_tariff.market_ref_currency_id is NULL)
SAGE_ID_CURRENCY_FALLBACK = {
    # Ghana (GHS)
    "KAS01": "GHS", "MOH01": "GHS", "UGL01": "GHS", "GBL01": "GHS",
    # Nigeria (NGN)
    "NBL01": "NGN", "NBL02": "NGN", "JAB01": "NGN",
    # Kenya (KES)
    "UTK01": "KES", "TBM01": "KES",
}


def resolve_project(sage_id: str) -> dict | None:
    """Look up project, contract, clause_tariff, and currency by sage_id."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id as project_id, p.sage_id, p.name as project_name,
                       p.cod_date, p.organization_id,
                       ct.id as clause_tariff_id,
                       ct.market_ref_currency_id,
                       ct.logic_parameters
                FROM project p
                LEFT JOIN contract c ON c.project_id = p.id
                LEFT JOIN clause_tariff ct ON ct.contract_id = c.id
                WHERE p.sage_id = %s
                LIMIT 1
            """, (sage_id,))
            row = cur.fetchone()
            if not row:
                return None

            # Resolve currency_id
            currency_id = row["market_ref_currency_id"]
            if not currency_id:
                fallback_code = SAGE_ID_CURRENCY_FALLBACK.get(sage_id)
                if fallback_code:
                    cur.execute("SELECT id FROM currency WHERE code = %s", (fallback_code,))
                    cur_row = cur.fetchone()
                    if cur_row:
                        currency_id = cur_row["id"]

            return {
                "project_id": row["project_id"],
                "sage_id": row["sage_id"],
                "project_name": row["project_name"],
                "cod_date": row["cod_date"].date() if hasattr(row["cod_date"], "date") else row["cod_date"],
                "organization_id": row["organization_id"],
                "clause_tariff_id": row["clause_tariff_id"],
                "currency_id": currency_id,
                "logic_parameters": row["logic_parameters"],
            }


def compute_operating_year(cod_date: date, billing_month: str) -> int:
    """
    Compute operating year from COD date and billing month.

    Operating years are 1-based, counted from COD anniversary.
    Months before COD get operating_year = 0 (pre-COD).
    """
    year, month = int(billing_month[:4]), int(billing_month[5:7])
    period_start = date(year, month, 1)

    if period_start < cod_date:
        return 0

    # Operating year = floor((months since COD) / 12) + 1
    months_since_cod = (period_start.year - cod_date.year) * 12 + (period_start.month - cod_date.month)
    return (months_since_cod // 12) + 1


def last_day_of_month(year: int, month: int) -> date:
    """Return the last day of the given month."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def populate_project(
    sage_id: str,
    parser: MarketRefPricingParser,
    dry_run: bool = False,
) -> dict:
    """
    Parse and upsert MRP observations for a single project.

    Returns summary dict with counts.
    """
    # 1. Resolve project in DB
    project = resolve_project(sage_id)
    if not project:
        logger.warning(f"[{sage_id}] No project found in DB — skipping")
        return {"sage_id": sage_id, "status": "skipped", "reason": "no_project"}

    if not project["cod_date"]:
        logger.warning(f"[{sage_id}] No COD date — skipping")
        return {"sage_id": sage_id, "status": "skipped", "reason": "no_cod_date"}

    logger.info(
        f"[{sage_id}] Project: {project['project_name']} (id={project['project_id']}, "
        f"COD={project['cod_date']}, clause_tariff={project['clause_tariff_id']})"
    )

    # 2. Parse Excel
    try:
        observations = parser.parse_mrp_monthly(sage_id)
    except ValueError as e:
        logger.warning(f"[{sage_id}] {e} — skipping")
        return {"sage_id": sage_id, "status": "skipped", "reason": str(e)}

    if not observations:
        logger.warning(f"[{sage_id}] No MRP observations parsed — skipping")
        return {"sage_id": sage_id, "status": "skipped", "reason": "no_observations"}

    logger.info(f"[{sage_id}] Parsed {len(observations)} monthly MRP observations")

    # 3. Compute operating years and prepare rows
    rows_by_year: dict[int, list] = {}
    for obs in observations:
        oy = compute_operating_year(project["cod_date"], obs["billing_month"])
        obs["operating_year"] = oy
        rows_by_year.setdefault(oy, []).append(obs)

    # Print summary
    for oy in sorted(rows_by_year.keys()):
        months = [o["billing_month"] for o in rows_by_year[oy]]
        mrps = [o["mrp_per_kwh"] for o in rows_by_year[oy]]
        logger.info(
            f"  OY {oy}: {len(months)} months "
            f"({months[0]}..{months[-1]}), "
            f"MRP range {min(mrps):.4f}..{max(mrps):.4f}"
        )

    if dry_run:
        logger.info(f"[{sage_id}] DRY RUN — no DB writes")
        return {
            "sage_id": sage_id,
            "status": "dry_run",
            "parsed": len(observations),
            "operating_years": sorted(rows_by_year.keys()),
        }

    # 4. Upsert monthly observations
    source_file = os.path.basename(parser.file_path)
    inserted = 0
    updated = 0

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for obs in observations:
                year, month = int(obs["billing_month"][:4]), int(obs["billing_month"][5:7])
                period_start = date(year, month, 1)
                period_end = last_day_of_month(year, month)

                source_metadata = {
                    "entry_method": "excel_import",
                    "source_file": source_file,
                    "tariff_components": obs["tariff_components"],
                }

                cur.execute("""
                    INSERT INTO reference_price (
                        project_id, organization_id, operating_year,
                        period_start, period_end,
                        calculated_mrp_per_kwh, currency_id,
                        observation_type, source_metadata, verification_status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        'monthly', %s, 'estimated'
                    )
                    ON CONFLICT (project_id, observation_type, period_start)
                    DO UPDATE SET
                        calculated_mrp_per_kwh = EXCLUDED.calculated_mrp_per_kwh,
                        currency_id = EXCLUDED.currency_id,
                        operating_year = EXCLUDED.operating_year,
                        period_end = EXCLUDED.period_end,
                        source_metadata = EXCLUDED.source_metadata,
                        verification_status = 'estimated',
                        updated_at = NOW()
                    RETURNING id, (xmax = 0) AS is_insert
                """, (
                    project["project_id"],
                    project["organization_id"],
                    obs["operating_year"],
                    period_start,
                    period_end,
                    obs["mrp_per_kwh"],
                    project["currency_id"],
                    json.dumps(source_metadata),
                ))
                result = cur.fetchone()
                if result["is_insert"]:
                    inserted += 1
                else:
                    updated += 1

            # 5. Delete stale annual rows so they can be recalculated
            # First detach any tariff_rate FK references to these annual rows
            cur.execute("""
                UPDATE tariff_rate SET reference_price_id = NULL
                WHERE reference_price_id IN (
                    SELECT id FROM reference_price
                    WHERE project_id = %s AND observation_type = 'annual'
                )
            """, (project["project_id"],))
            detached = cur.rowcount
            if detached:
                logger.info(f"[{sage_id}] Detached {detached} tariff_rate FK references")

            cur.execute("""
                DELETE FROM reference_price
                WHERE project_id = %s AND observation_type = 'annual'
                RETURNING id
            """, (project["project_id"],))
            deleted_annual = cur.rowcount

        conn.commit()

    logger.info(
        f"[{sage_id}] Done: {inserted} inserted, {updated} updated, "
        f"{deleted_annual} stale annual rows deleted"
    )

    return {
        "sage_id": sage_id,
        "status": "ok",
        "inserted": inserted,
        "updated": updated,
        "deleted_annual": deleted_annual,
        "total_monthly": len(observations),
    }


def main():
    ap = argparse.ArgumentParser(description="Populate monthly MRP from Market Ref Pricing workbook")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", type=str, help="Single sage_id to populate (e.g. KAS01)")
    group.add_argument("--all", action="store_true", help="Populate all projects in workbook")
    ap.add_argument("--dry-run", action="store_true", help="Parse and print but don't write to DB")
    ap.add_argument("--file", type=str, default=DEFAULT_EXCEL_PATH, help="Path to Excel file")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        logger.error(f"Excel file not found: {args.file}")
        sys.exit(1)

    parser = MarketRefPricingParser(args.file)
    init_connection_pool(min_connections=1, max_connections=3)

    try:
        if args.project:
            sage_ids = [args.project.upper()]
        else:
            sage_ids = parser.get_available_sheets()
            logger.info(f"Discovered {len(sage_ids)} project sheets: {sage_ids}")

        results = []
        for sage_id in sage_ids:
            result = populate_project(sage_id, parser, dry_run=args.dry_run)
            results.append(result)
            print()

        # Print summary table
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"{'Sage ID':<8} {'Status':<10} {'Parsed':<8} {'Inserted':<10} {'Updated':<9} {'Annual Del':<10}")
        print("-" * 70)
        for r in results:
            parsed = r.get("parsed") or r.get("total_monthly", "-")
            ins = r.get("inserted", "-")
            upd = r.get("updated", "-")
            adel = r.get("deleted_annual", "-")
            print(f"{r['sage_id']:<8} {r['status']:<10} {str(parsed):<8} {str(ins):<10} {str(upd):<9} {str(adel):<10}")

    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
