#!/usr/bin/env python3
"""
Populate oy_start_date in clause_tariff.logic_parameters from project.cod_date.

For every clause_tariff where oy_start_date is NULL and the project has a cod_date,
sets oy_start_date = project.cod_date.  Skips projects that already have oy_start_date
(e.g. LOI01 = Transfer Date) and projects with NULL cod_date.

Usage:
    cd python-backend
    python scripts/populate_oy_start_date.py --dry-run
    python scripts/populate_oy_start_date.py
"""

import argparse
import json
import logging
import os
import sys
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


def populate(dry_run: bool):
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Find clause_tariff records where oy_start_date is missing but cod_date exists
        cur.execute("""
            SELECT ct.id AS clause_tariff_id, p.sage_id, p.name,
                   p.cod_date, ct.logic_parameters
            FROM project p
            JOIN contract c ON c.project_id = p.id
            JOIN clause_tariff ct ON ct.contract_id = c.id
            WHERE p.cod_date IS NOT NULL
            ORDER BY p.sage_id, ct.id
        """)

        rows = cur.fetchall()
        updated = 0
        skipped = 0

        for row in rows:
            sage_id = row["sage_id"]
            ct_id = row["clause_tariff_id"]
            params = row["logic_parameters"] or {}
            cod_date = row["cod_date"]

            # Skip if oy_start_date already set (e.g. LOI01)
            if params.get("oy_start_date"):
                log.info(f"  SKIP  ct={ct_id}  {sage_id} ({row['name']}) — already has oy_start_date={params['oy_start_date']}")
                skipped += 1
                continue

            # Set oy_start_date = cod_date (ISO format string)
            cod_str = cod_date.isoformat() if hasattr(cod_date, "isoformat") else str(cod_date)
            params["oy_start_date"] = cod_str

            if dry_run:
                log.info(f"  DRY   ct={ct_id}  {sage_id} ({row['name']}) → oy_start_date={cod_str}")
            else:
                cur.execute("""
                    UPDATE clause_tariff
                    SET logic_parameters = %s
                    WHERE id = %s
                """, (json.dumps(params), ct_id))
                log.info(f"  SET   ct={ct_id}  {sage_id} ({row['name']}) → oy_start_date={cod_str}")

            updated += 1

        if dry_run:
            log.info(f"\nDRY RUN: would update {updated} clause_tariff rows, skipped {skipped}")
            conn.rollback()
        else:
            conn.commit()
            log.info(f"\nDONE: updated {updated} clause_tariff rows, skipped {skipped}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate oy_start_date from project.cod_date")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    populate(args.dry_run)
