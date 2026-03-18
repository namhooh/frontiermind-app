"""
Fix Devki Group counterparty mapping:
- Counterparty 50 "Devki Group" has MB01-specific data but is shared across 6 contracts
- Clean 50 to be generic parent, create subsidiary counterparties, reassign contracts
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from db.database import init_connection_pool, get_db_connection

# Devki subsidiary mapping: sage_id -> buyer name
DEVKI_SUBSIDIARIES = {
    "MB01": "Maisha Mabati Mills Limited",
    "MF01": "Maisha Minerals and Fertilizers Limited",
    "MP01": "Maisha Packaging Limited (Nakuru)",
    "MP02": "Maisha Packaging Limited (Lukenya)",
    "NC02": "National Cement Company Limited (Athi River)",
    "NC03": "National Cement Company Limited (Nakuru)",
}


def main():
    init_connection_pool(min_connections=1, max_connections=3)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # 1. Clean counterparty 50 to be generic Devki Group parent
            cur.execute("""
                UPDATE counterparty
                SET registered_name = NULL,
                    sage_bp_code = NULL
                WHERE id = 50
                RETURNING id, name
            """)
            r = cur.fetchone()
            print(f"Cleaned counterparty {r['id']} ({r['name']}): removed MB01-specific fields")

            # 2. MB01 already has counterparty 97 — just reassign the contract
            cur.execute("""
                UPDATE contract SET counterparty_id = 97
                WHERE id = 23
                RETURNING id
            """)
            print(f"Updated contract 23 (MB01): counterparty_id -> 97 (Maisha Mabati Mills Limited)")

            # 3. Create subsidiary counterparties for MF01, MP01, MP02, NC02, NC03
            for sage_id, buyer_name in DEVKI_SUBSIDIARIES.items():
                if sage_id == "MB01":
                    continue  # Already handled (counterparty 97)

                # Check if already exists
                cur.execute(
                    "SELECT id FROM counterparty WHERE name = %s LIMIT 1",
                    (buyer_name,)
                )
                existing = cur.fetchone()
                if existing:
                    cp_id = existing['id']
                    print(f"  {sage_id}: counterparty '{buyer_name}' already exists (id={cp_id})")
                else:
                    cur.execute("""
                        INSERT INTO counterparty (name, country, industry, counterparty_type_id)
                        VALUES (%s, 'Kenya', 'Manufacturing', 1)
                        RETURNING id
                    """, (buyer_name,))
                    cp_id = cur.fetchone()['id']
                    print(f"  {sage_id}: created counterparty '{buyer_name}' (id={cp_id})")

                # Reassign contract
                cur.execute("""
                    UPDATE contract SET counterparty_id = %s
                    WHERE id = (
                        SELECT c.id FROM contract c
                        JOIN project p ON p.id = c.project_id
                        WHERE p.sage_id = %s AND c.organization_id = 1
                        LIMIT 1
                    )
                    RETURNING id
                """, (cp_id, sage_id))
                updated = cur.fetchone()
                if updated:
                    print(f"  {sage_id}: contract {updated['id']} -> counterparty_id={cp_id}")
                else:
                    print(f"  {sage_id}: WARNING — no contract found")

            conn.commit()
            print("\nDone. All Devki subsidiary contracts reassigned.")


if __name__ == "__main__":
    main()
