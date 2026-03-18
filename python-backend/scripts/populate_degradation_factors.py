#!/usr/bin/env python3
"""
Populate degradation_pct in clause_tariff.logic_parameters from CBE Revenue Masterfile.

Source: CBE Asset Management Operating Revenue Masterfile - Energy Sales tab, Row 3.

Usage:
    cd python-backend
    python scripts/populate_degradation_factors.py --dry-run
    python scripts/populate_degradation_factors.py
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

# Degradation factors from CBE Revenue Masterfile - Energy Sales tab, Row 3
# Mapped: Excel project name → sage_id → annual degradation rate (decimal)
DEGRADATION_BY_SAGE_ID = {
    "GC001": 0.004,    # Garden City Mall
    "UGL01": 0.005,    # Unilever Ghana
    "UTK01": 0.007,    # eKaterra Tea Kenya (Unilever Tea Kenya)
    "KAS01": 0.004,    # Kasapreko Phase I+II
    "NBL01": 0.007,    # Nigerian Breweries - Ibadan
    "NBL02": 0.004,    # Nigerian Breweries - Ama
    "JAB01": 0.005,    # Jabi Lake Mall
    "GBL01": 0.005,    # Guinness Ghana Breweries
    "XFAB":  0.005,    # XFlora AB
    "XFBV":  0.005,    # XFlora BV (Bloom Valley)
    "XFSS":  0.005,    # XFlora SS (Sojanmi Spring)
    "XFL01": 0.005,    # XFlora XF (Xpressions Flora)
    "LOI01": 0.007,    # Loisaba
    "TBM01": 0.007,    # TeePee Brushes
    "QMM01": 0.005,    # Rio Tinto QMM (Solar + Wind)
    "MIR01": 0.005,    # Miro Forestry
    "IVL01": 0.004,    # Indorama Ventures
    "ERG":   0.005,    # Molo Graphite
    "MF01":  0.0055,   # Maisha Minerals & Fertilizer Athi
    "NC02":  0.0055,   # National Cement Athi River
    "MB01":  0.0055,   # Maisha Mabati Mills Lukenya
    "MP02":  0.0055,   # Maisha Packaging Lukenya
    "MP01":  0.0055,   # Maisha Packaging Nakuru
    "NC03":  0.0055,   # National Cement Nakuru
    "UNSOS": 0.005,    # UNSOS Baidoa
    "CAL01": 0.005,    # Caledonia
    "MOH01": 0.007,    # Mohinani
    "AMP01": 0.005,    # Ampersand
}


def populate(dry_run: bool):
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Find clause_tariff records for each project
        cur.execute("""
            SELECT ct.id AS clause_tariff_id, p.sage_id, p.name,
                   ct.logic_parameters
            FROM project p
            JOIN contract c ON c.project_id = p.id
            JOIN clause_tariff ct ON ct.contract_id = c.id
            WHERE p.sage_id = ANY(%s)
            ORDER BY p.sage_id, ct.id
        """, (list(DEGRADATION_BY_SAGE_ID.keys()),))

        rows = cur.fetchall()
        updated = 0
        skipped = 0

        for row in rows:
            sage_id = row["sage_id"]
            ct_id = row["clause_tariff_id"]
            params = row["logic_parameters"] or {}
            target_deg = DEGRADATION_BY_SAGE_ID[sage_id]

            current_deg = params.get("degradation_pct")
            if current_deg is not None and float(current_deg) == target_deg:
                log.info(f"  SKIP  ct={ct_id}  {sage_id} ({row['name']}) — already {current_deg}")
                skipped += 1
                continue

            params["degradation_pct"] = target_deg

            if dry_run:
                log.info(f"  DRY   ct={ct_id}  {sage_id} ({row['name']}) → {target_deg}")
            else:
                cur.execute("""
                    UPDATE clause_tariff
                    SET logic_parameters = %s
                    WHERE id = %s
                """, (json.dumps(params), ct_id))
                log.info(f"  SET   ct={ct_id}  {sage_id} ({row['name']}) → {target_deg}")

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
    parser = argparse.ArgumentParser(description="Populate degradation factors")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    populate(args.dry_run)
