#!/usr/bin/env python3
"""
One-off cleanup: NULL out internal pipeline notes from contract_billing_product.

These "Step N ..." strings are engineering metadata that leak through to the
dashboard Pricing & Tariffs tab.  User-entered notes are preserved.

Usage:
    cd python-backend
    python scripts/cleanup_internal_notes.py --dry-run   # Preview
    python scripts/cleanup_internal_notes.py              # Execute
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg2

def main():
    parser = argparse.ArgumentParser(description="Clean internal pipeline notes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changing data")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()

        # Preview affected rows
        cur.execute(
            "SELECT id, notes FROM contract_billing_product WHERE notes LIKE 'Step %%'"
        )
        rows = cur.fetchall()
        print(f"Found {len(rows)} rows with internal pipeline notes")

        if not rows:
            print("Nothing to clean up.")
            return

        if args.dry_run:
            for row_id, notes in rows[:5]:
                print(f"  id={row_id}  notes={notes!r}")
            if len(rows) > 5:
                print(f"  ... and {len(rows) - 5} more")
            print("\nRe-run without --dry-run to apply.")
            return

        cur.execute(
            "UPDATE contract_billing_product SET notes = NULL WHERE notes LIKE 'Step %%'"
        )
        updated = cur.rowcount
        conn.commit()
        print(f"Cleared notes on {updated} rows.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
