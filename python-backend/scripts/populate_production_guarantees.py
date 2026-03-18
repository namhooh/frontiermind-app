#!/usr/bin/env python3
"""
Populate production_guarantee rows from extracted PERFORMANCE_GUARANTEE clauses
and production_forecast P50 data.

For each project that has a PERFORMANCE_GUARANTEE clause with a threshold,
computes guaranteed_kwh = P50_annual × (threshold/100) per operating year.

Usage:
    cd python-backend
    python scripts/populate_production_guarantees.py --dry-run
    python scripts/populate_production_guarantees.py --project MB01
"""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir.parent))

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]


def get_projects_with_guarantees(cur, project_filter: str | None):
    """Find projects that have a PERFORMANCE_GUARANTEE clause with a threshold."""
    sql = """
        SELECT DISTINCT ON (p.id)
            p.id as project_id,
            p.organization_id,
            p.name as project_name,
            p.sage_id,
            p.cod_date,
            con.contract_term_years,
            c.normalized_payload
        FROM clause c
        JOIN clause_category cc ON cc.id = c.clause_category_id
        JOIN project p ON p.id = c.project_id
        JOIN contract con ON con.id = c.contract_id
        WHERE cc.code = 'PERFORMANCE_GUARANTEE'
          AND c.normalized_payload->>'threshold' IS NOT NULL
          AND c.is_current = true
    """
    params = {}
    if project_filter:
        sql += " AND (p.sage_id = %(filter)s OR p.external_project_id = %(filter)s)"
        params["filter"] = project_filter
    cur.execute(sql, params)
    return cur.fetchall()


def get_forecast_by_oy(cur, project_id: int):
    """Get P50 annual forecast totals by operating year."""
    cur.execute("""
        SELECT operating_year,
               SUM(forecast_energy_kwh) as p50_kwh,
               COUNT(*) as months
        FROM production_forecast
        WHERE project_id = %(pid)s
          AND operating_year IS NOT NULL
        GROUP BY operating_year
        ORDER BY operating_year
    """, {"pid": project_id})
    return cur.fetchall()


def get_existing_guarantees(cur, project_id: int):
    """Get existing guarantee operating years for this project."""
    cur.execute("""
        SELECT operating_year FROM production_guarantee
        WHERE project_id = %(pid)s
    """, {"pid": project_id})
    return {row["operating_year"] for row in cur.fetchall()}


def populate_guarantees(cur, project, dry_run: bool) -> int:
    """Populate production_guarantee rows for a single project."""
    project_id = project["project_id"]
    org_id = project["organization_id"]
    project_name = project["project_name"]
    cod_date = project["cod_date"]
    payload = project["normalized_payload"]
    contract_term = project["contract_term_years"] or 20

    if not cod_date:
        log.warning("  %s: No COD date — skipping", project_name)
        return 0

    # Ensure cod_date is a date object
    if hasattr(cod_date, "date"):
        cod_date = cod_date.date()

    threshold_pct = float(payload.get("threshold", 0))
    if threshold_pct <= 0:
        log.warning("  %s: threshold=%s — skipping", project_name, threshold_pct)
        return 0

    # Normalize: if > 1 treat as percentage, else treat as fraction
    guarantee_fraction = threshold_pct / 100.0 if threshold_pct > 1 else threshold_pct

    log.info("  %s (id=%d): COD=%s, term=%d yrs, guarantee=%.0f%% of P50",
             project_name, project_id, cod_date, contract_term, guarantee_fraction * 100)

    forecasts = get_forecast_by_oy(cur, project_id)
    if not forecasts:
        log.warning("  %s: No forecast data — skipping", project_name)
        return 0

    existing = get_existing_guarantees(cur, project_id)

    inserted = 0
    for row in forecasts:
        oy = row["operating_year"]
        if oy < 1 or oy > contract_term:
            continue
        if oy in existing:
            log.info("    OY%d: already exists — skipping", oy)
            continue

        p50_kwh = float(row["p50_kwh"])
        guaranteed_kwh = round(p50_kwh * guarantee_fraction)

        # Derive year boundaries from COD
        year_start = date(cod_date.year + (oy - 1), cod_date.month, cod_date.day)
        year_end = date(cod_date.year + oy, cod_date.month, cod_date.day)

        source_meta = {
            "source": "clause_performance_guarantee",
            "threshold_pct": threshold_pct,
            "reference": payload.get("reference_annex", ""),
            "populated_by": "populate_production_guarantees.py",
        }

        log.info("    OY%d: P50=%.0f kWh -> guaranteed=%.0f kWh (%s to %s)",
                 oy, p50_kwh, guaranteed_kwh, year_start, year_end)

        if not dry_run:
            cur.execute("""
                INSERT INTO production_guarantee (
                    project_id, organization_id, operating_year,
                    year_start_date, year_end_date,
                    p50_annual_kwh, guarantee_pct_of_p50, guaranteed_kwh,
                    source_metadata
                ) VALUES (
                    %(pid)s, %(oid)s, %(oy)s,
                    %(start)s, %(end)s,
                    %(p50)s, %(pct)s, %(gkwh)s,
                    %(meta)s
                )
                ON CONFLICT (project_id, operating_year) DO NOTHING
            """, {
                "pid": project_id, "oid": org_id, "oy": oy,
                "start": year_start, "end": year_end,
                "p50": round(p50_kwh), "pct": round(guarantee_fraction, 4),
                "gkwh": guaranteed_kwh,
                "meta": json.dumps(source_meta),
            })

        inserted += 1

    return inserted


def main():
    parser = argparse.ArgumentParser(description="Populate production_guarantee from clauses + forecasts")
    parser.add_argument("--project", help="Filter to a specific project (sage_id)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '300s'")

            projects = get_projects_with_guarantees(cur, args.project)
            log.info("Found %d projects with PERFORMANCE_GUARANTEE clauses", len(projects))

            total = 0
            for proj in projects:
                count = populate_guarantees(cur, proj, args.dry_run)
                total += count

            if args.dry_run:
                log.info("DRY RUN — %d guarantee rows would be inserted", total)
                conn.rollback()
            else:
                conn.commit()
                log.info("COMMITTED — %d guarantee rows inserted", total)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
