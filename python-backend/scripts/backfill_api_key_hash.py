"""One-time backfill: populate api_key_hash for existing API keys."""

import hashlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_connection_pool, get_db_connection
from db.integration_repository import IntegrationRepository


def backfill():
    init_connection_pool()
    repo = IntegrationRepository()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, encrypted_credentials
                FROM integration_credential
                WHERE auth_type = 'api_key' AND api_key_hash IS NULL
            """)
            rows = cur.fetchall()

    print(f"Found {len(rows)} credentials without api_key_hash")

    updated = 0
    skipped = 0
    for row in rows:
        creds = repo._unpack_credentials(row["encrypted_credentials"])
        api_key = creds.get("api_key")
        if not api_key:
            skipped += 1
            continue

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE integration_credential SET api_key_hash = %s WHERE id = %s",
                    (key_hash, row["id"]),
                )
        updated += 1

    print(f"Backfilled api_key_hash for {updated} credentials ({skipped} skipped — no api_key in blob)")


if __name__ == "__main__":
    backfill()
