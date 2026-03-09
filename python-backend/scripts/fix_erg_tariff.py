#!/usr/bin/env python3
"""
One-shot data fix for ERG tariff (clause_tariff id=27).

Fixes:
1. currency_id: MGA(15) → USD(1), unit → 'USD/kWh'
2. escalation_type_id: NULL → 8 (PERCENTAGE)
3. logic_parameters: add escalation_rate=0.025
4. Deletes stale tariff_rate rows so step10b can regenerate them

Run:
    cd python-backend
    python scripts/fix_erg_tariff.py --dry-run
    python scripts/fix_erg_tariff.py
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import psycopg2
from psycopg2.extras import RealDictCursor

TARIFF_ID = 27

def main():
    dry_run = '--dry-run' in sys.argv
    mode = 'DRY RUN' if dry_run else 'LIVE'
    print(f"=== ERG Tariff Fix ({mode}) ===")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # Read current state
    cur.execute("""
        SELECT ct.id, ct.base_rate, ct.currency_id, c.code as currency_code,
               ct.unit, ct.escalation_type_id, ct.logic_parameters
        FROM clause_tariff ct
        LEFT JOIN currency c ON ct.currency_id = c.id
        WHERE ct.id = %s
    """, (TARIFF_ID,))
    tariff = cur.fetchone()
    if not tariff:
        print(f"ERROR: clause_tariff {TARIFF_ID} not found")
        sys.exit(1)

    print(f"Before:")
    print(f"  base_rate:          {tariff['base_rate']}")
    print(f"  currency:           {tariff['currency_code']} (id={tariff['currency_id']})")
    print(f"  unit:               {tariff['unit']}")
    print(f"  escalation_type_id: {tariff['escalation_type_id']}")
    print(f"  logic_parameters:   {json.dumps(tariff['logic_parameters'], indent=2)}")

    # Count existing tariff_rate rows
    cur.execute("SELECT count(*) as cnt FROM tariff_rate WHERE clause_tariff_id = %s", (TARIFF_ID,))
    rate_count = cur.fetchone()['cnt']
    print(f"  tariff_rate rows:   {rate_count}")

    # Build updated logic_parameters
    lp = tariff['logic_parameters'] or {}
    lp['escalation_rate'] = 0.025
    new_lp = json.dumps(lp)

    print(f"\nAfter:")
    print(f"  currency:           USD (id=1)")
    print(f"  unit:               USD/kWh")
    print(f"  escalation_type_id: 8 (PERCENTAGE)")
    print(f"  logic_parameters:   {json.dumps(lp, indent=2)}")
    print(f"  tariff_rate rows:   0 (deleted, re-run step10b)")

    if dry_run:
        print("\nDRY RUN — no changes applied")
        conn.close()
        return

    # Apply fix
    cur.execute("""
        UPDATE clause_tariff
        SET currency_id = 1,
            unit = 'USD/kWh',
            escalation_type_id = 8,
            logic_parameters = %s
        WHERE id = %s
    """, (new_lp, TARIFF_ID))
    print(f"\n  Updated clause_tariff {TARIFF_ID}")

    # Delete stale tariff_rate rows
    cur.execute("DELETE FROM tariff_rate WHERE clause_tariff_id = %s", (TARIFF_ID,))
    print(f"  Deleted {cur.rowcount} tariff_rate rows")

    conn.commit()
    conn.close()
    print("\nDone. Now run: python scripts/step10b_tariff_rate_population.py --project ERG")


if __name__ == '__main__':
    main()
