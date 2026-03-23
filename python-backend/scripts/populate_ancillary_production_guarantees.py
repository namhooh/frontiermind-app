#!/usr/bin/env python3
"""
Phase 5: Populate production_guarantee rows from ancillary schedule/annexure documents.

Three projects need production guarantee data from companion docs:

  UGL01 — SSA Schedules, Schedule 5 (p17): 15 years of kWh/kWp × installed capacity
  UTK01 — SSA Schedules, Schedule 5 (p17): 15 years of absolute MWh
  LOI01 — Revised Annexures, Annexure D (p5): 10 years combined (Tented Camp + HQ)
           Updates existing rows whose values came from original SSA / PPW

Usage:
    cd python-backend
    python scripts/populate_ancillary_production_guarantees.py --dry-run
    python scripts/populate_ancillary_production_guarantees.py
    python scripts/populate_ancillary_production_guarantees.py --project UGL01
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


# ---------------------------------------------------------------------------
# Source data extracted from PDFs
# ---------------------------------------------------------------------------

# UGL01 — SSA Schedules, Schedule 5 (p17)
# Values in kWh/kWp; installed_dc_capacity_kwp = 970.2 kWp
# Required Solar Output = 80% of Expected Solar Output (Schedule 2 p12)
UGL01_KWH_PER_KWP = [
    1427, 1417, 1408, 1398, 1388,
    1378, 1369, 1359, 1349, 1340,
    1331, 1321, 1312, 1303, 1294,
]
UGL01_GUARANTEE_PCT = 0.80

# UTK01 — SSA Schedules, Schedule 5 (p17)
# Values in MWh (absolute); installed DC = 609.28 kWp per Schedule 3
# Required Solar Output = 80% of Expected Solar Output (Schedule 2 p12)
UTK01_MWH = [
    1259, 1250, 1242, 1233, 1224,
    1216, 1207, 1199, 1190, 1182,
    1174, 1165, 1157, 1149, 1141,
]
UTK01_GUARANTEE_PCT = 0.80

# LOI01 — Revised Annexures signed 2018-10-16, Annexure D (p5)
# Combined (Loisaba Tented Camp + Loisaba Head Quarters) in MWh
# Tented Camp: 47.2, 46.8, 46.5, 46.2, 45.8, 45.5, 45.2, 44.9, 44.5, 44.2
# Head Quarters: 32.0, 31.7, 31.5, 31.3, 31.1, 30.9, 30.6, 30.4, 30.2, 30.0
LOI01_COMBINED_MWH = [
    79.2, 78.5, 78.0, 77.5, 76.9,
    76.4, 75.8, 75.3, 74.7, 74.2,
]
# LOI01 existing DB rows have guaranteed_kwh = p50_annual_kwh (no separate guarantee_pct).
# The Revised Annexures supersede the original values; guarantee_pct comes from SSA clause.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_year_dates(cod: date, oy: int):
    """Return (year_start, year_end) for a given operating year."""
    # Handle COD on leap day
    month, day = cod.month, cod.day
    if month == 2 and day == 29:
        day = 28
    start = date(cod.year + (oy - 1), month, day)
    end = date(cod.year + oy, month, day)
    return start, end


def get_project(cur, sage_id: str):
    """Look up project by sage_id."""
    cur.execute("""
        SELECT id, organization_id, sage_id, installed_dc_capacity_kwp, cod_date
        FROM project WHERE sage_id = %(sid)s
    """, {"sid": sage_id})
    return cur.fetchone()


def get_existing_guarantees(cur, project_id: int):
    """Return dict of operating_year -> row id for existing guarantees."""
    cur.execute("""
        SELECT id, operating_year, guaranteed_kwh, p50_annual_kwh, guarantee_pct_of_p50
        FROM production_guarantee
        WHERE project_id = %(pid)s
        ORDER BY operating_year
    """, {"pid": project_id})
    return {row["operating_year"]: row for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Per-project handlers
# ---------------------------------------------------------------------------

def populate_ugl01(cur, dry_run: bool) -> int:
    """Insert 15 production_guarantee rows for UGL01 from Schedule 5."""
    proj = get_project(cur, "UGL01")
    if not proj:
        log.warning("UGL01 project not found — skipping")
        return 0

    capacity_kwp = float(proj["installed_dc_capacity_kwp"])
    cod = proj["cod_date"]
    if hasattr(cod, "date"):
        cod = cod.date()

    existing = get_existing_guarantees(cur, proj["id"])
    source = {
        "source": "CBE - UGL01_Unilever Ghana SSA Schedules_20180829.pdf",
        "schedule": "Schedule 5 (p17) — Estimated Monthly and Annual Production",
        "pricing_ref": "Schedule 2 (p12) — Required Solar Output = 80% of Expected Solar Output",
        "populated_by": "populate_ancillary_production_guarantees.py",
    }

    inserted = 0
    for oy, kwh_per_kwp in enumerate(UGL01_KWH_PER_KWP, start=1):
        p50_kwh = round(kwh_per_kwp * capacity_kwp)
        guaranteed_kwh = round(p50_kwh * UGL01_GUARANTEE_PCT)
        year_start, year_end = derive_year_dates(cod, oy)

        if oy in existing:
            log.info("  UGL01 OY%d: already exists (guaranteed=%s) — skipping",
                     oy, existing[oy]["guaranteed_kwh"])
            continue

        log.info("  UGL01 OY%d: %d kWh/kWp × %.1f kWp = P50 %d kWh → guaranteed %d kWh (80%%)",
                 oy, kwh_per_kwp, capacity_kwp, p50_kwh, guaranteed_kwh)

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
                "pid": proj["id"], "oid": proj["organization_id"], "oy": oy,
                "start": year_start, "end": year_end,
                "p50": p50_kwh, "pct": UGL01_GUARANTEE_PCT, "gkwh": guaranteed_kwh,
                "meta": json.dumps(source),
            })
        inserted += 1

    return inserted


def populate_utk01(cur, dry_run: bool) -> int:
    """Insert 15 production_guarantee rows for UTK01 from Schedule 5."""
    proj = get_project(cur, "UTK01")
    if not proj:
        log.warning("UTK01 project not found — skipping")
        return 0

    cod = proj["cod_date"]
    if hasattr(cod, "date"):
        cod = cod.date()

    existing = get_existing_guarantees(cur, proj["id"])
    source = {
        "source": "CBE - UTK01_Unilever Tea Kenya SSA Schedules Signed_20180205.pdf",
        "schedule": "Schedule 5 (p17) — Estimated Monthly and Annual Production",
        "pricing_ref": "Schedule 2 (p12) — Required Solar Output = 80% of Expected Solar Output",
        "populated_by": "populate_ancillary_production_guarantees.py",
    }

    inserted = 0
    for oy, mwh in enumerate(UTK01_MWH, start=1):
        p50_kwh = round(mwh * 1000)  # MWh → kWh
        guaranteed_kwh = round(p50_kwh * UTK01_GUARANTEE_PCT)
        year_start, year_end = derive_year_dates(cod, oy)

        if oy in existing:
            log.info("  UTK01 OY%d: already exists (guaranteed=%s) — skipping",
                     oy, existing[oy]["guaranteed_kwh"])
            continue

        log.info("  UTK01 OY%d: %d MWh = P50 %d kWh → guaranteed %d kWh (80%%)",
                 oy, mwh, p50_kwh, guaranteed_kwh)

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
                "pid": proj["id"], "oid": proj["organization_id"], "oy": oy,
                "start": year_start, "end": year_end,
                "p50": p50_kwh, "pct": UTK01_GUARANTEE_PCT, "gkwh": guaranteed_kwh,
                "meta": json.dumps(source),
            })
        inserted += 1

    return inserted


def update_loi01(cur, dry_run: bool) -> int:
    """Update 10 existing production_guarantee rows for LOI01 with Revised Annexure D values."""
    proj = get_project(cur, "LOI01")
    if not proj:
        log.warning("LOI01 project not found — skipping")
        return 0

    cod = proj["cod_date"]
    if hasattr(cod, "date"):
        cod = cod.date()

    existing = get_existing_guarantees(cur, proj["id"])
    source = {
        "source": "CBE - LOI01_Loisaba SSA Revised Annexures Signed_20181016.pdf",
        "schedule": "Annexure D (p5) — Expected Energy Output",
        "note": "Combined: Loisaba Tented Camp + Loisaba Head Quarters",
        "supersedes": "Original SSA / PPW values",
        "populated_by": "populate_ancillary_production_guarantees.py",
    }

    updated = 0
    for oy, mwh in enumerate(LOI01_COMBINED_MWH, start=1):
        p50_kwh = round(mwh * 1000)  # MWh → kWh
        year_start, year_end = derive_year_dates(cod, oy)

        if oy in existing:
            old_val = existing[oy]["guaranteed_kwh"]
            old_p50 = existing[oy]["p50_annual_kwh"]
            log.info("  LOI01 OY%d: UPDATE p50 %s → %d kWh, guaranteed %s → %d kWh",
                     oy, old_p50, p50_kwh, old_val, p50_kwh)

            if not dry_run:
                cur.execute("""
                    UPDATE production_guarantee
                    SET p50_annual_kwh = %(p50)s,
                        guaranteed_kwh = %(gkwh)s,
                        year_start_date = %(start)s,
                        year_end_date = %(end)s,
                        source_metadata = %(meta)s,
                        updated_at = NOW()
                    WHERE id = %(id)s
                """, {
                    "id": existing[oy]["id"],
                    "p50": p50_kwh, "gkwh": p50_kwh,
                    "start": year_start, "end": year_end,
                    "meta": json.dumps(source),
                })
        else:
            log.info("  LOI01 OY%d: INSERT p50 %d kWh (no existing row)",
                     oy, p50_kwh)

            if not dry_run:
                cur.execute("""
                    INSERT INTO production_guarantee (
                        project_id, organization_id, operating_year,
                        year_start_date, year_end_date,
                        p50_annual_kwh, guaranteed_kwh,
                        source_metadata
                    ) VALUES (
                        %(pid)s, %(oid)s, %(oy)s,
                        %(start)s, %(end)s,
                        %(p50)s, %(gkwh)s,
                        %(meta)s
                    )
                    ON CONFLICT (project_id, operating_year) DO NOTHING
                """, {
                    "pid": proj["id"], "oid": proj["organization_id"], "oy": oy,
                    "start": year_start, "end": year_end,
                    "p50": p50_kwh, "gkwh": p50_kwh,
                    "meta": json.dumps(source),
                })
        updated += 1

    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

HANDLERS = {
    "UGL01": populate_ugl01,
    "UTK01": populate_utk01,
    "LOI01": update_loi01,
}


def main():
    parser = argparse.ArgumentParser(
        description="Populate production_guarantee from ancillary schedule/annexure docs"
    )
    parser.add_argument("--project", help="Run for a specific project only (UGL01, UTK01, LOI01)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.project and args.project not in HANDLERS:
        log.error("Unknown project %s. Choose from: %s", args.project, ", ".join(HANDLERS))
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '300s'")

            targets = [args.project] if args.project else list(HANDLERS.keys())
            total = 0

            for sage_id in targets:
                log.info("=== %s ===", sage_id)
                count = HANDLERS[sage_id](cur, args.dry_run)
                total += count
                log.info("  %s: %d rows %s", sage_id, count,
                         "would be written" if args.dry_run else "written")

            if args.dry_run:
                log.info("DRY RUN — %d total rows would be written", total)
                conn.rollback()
            else:
                conn.commit()
                log.info("COMMITTED — %d total rows written", total)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
