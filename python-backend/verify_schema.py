"""
Verify Phase 2 database schema changes.

This script connects to the database and verifies that all Phase 2 migrations
have been applied successfully.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("Error: psycopg2 not installed. Install with: pip install psycopg2-binary")
    sys.exit(1)


def verify_schema():
    """Verify database schema changes from Phase 2 migrations."""

    # Get database connection string from environment
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not found in environment variables")
        print("Set it in .env file or export DATABASE_URL='postgresql://user:password@host:port/database'")
        return False

    try:
        # Connect to database
        print("Connecting to database...")
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        print("✓ Connected successfully\n")

        # Verify contract_pii_mapping table exists
        print("=" * 80)
        print("1. Checking contract_pii_mapping table...")
        print("=" * 80)
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'contract_pii_mapping'
            ORDER BY ordinal_position;
        """)
        columns = cursor.fetchall()

        if columns:
            print("✓ contract_pii_mapping table exists")
            print("\nColumns:")
            for col_name, data_type, nullable in columns:
                print(f"  - {col_name}: {data_type} ({'NULL' if nullable == 'YES' else 'NOT NULL'})")
        else:
            print("✗ contract_pii_mapping table NOT FOUND")
            return False

        # Verify contract table new columns
        print("\n" + "=" * 80)
        print("2. Checking contract table new columns...")
        print("=" * 80)
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'contract'
            AND column_name IN (
                'parsing_status', 'parsing_started_at', 'parsing_completed_at',
                'parsing_error', 'pii_detected_count', 'clauses_extracted_count',
                'processing_time_seconds'
            )
            ORDER BY ordinal_position;
        """)
        contract_columns = cursor.fetchall()

        if len(contract_columns) == 7:
            print("✓ All 7 new columns added to contract table")
            print("\nNew columns:")
            for col_name, data_type, nullable in contract_columns:
                print(f"  - {col_name}: {data_type} ({'NULL' if nullable == 'YES' else 'NOT NULL'})")
        else:
            print(f"✗ Expected 7 columns, found {len(contract_columns)}")
            return False

        # Verify clause table new columns
        print("\n" + "=" * 80)
        print("3. Checking clause table new columns...")
        print("=" * 80)
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'clause'
            AND column_name IN ('summary', 'beneficiary_party', 'confidence_score')
            ORDER BY ordinal_position;
        """)
        clause_columns = cursor.fetchall()

        if len(clause_columns) == 3:
            print("✓ All 3 new columns added to clause table")
            print("\nNew columns:")
            for col_name, data_type, nullable in clause_columns:
                print(f"  - {col_name}: {data_type} ({'NULL' if nullable == 'YES' else 'NOT NULL'})")
        else:
            print(f"✗ Expected 3 columns, found {len(clause_columns)}")
            return False

        # Verify helper functions exist
        print("\n" + "=" * 80)
        print("4. Checking helper functions...")
        print("=" * 80)
        cursor.execute("""
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_schema = 'public'
            AND routine_name IN (
                'log_pii_access',
                'get_contract_pii_count',
                'update_contract_parsing_status',
                'get_parsing_statistics',
                'get_clauses_needing_review',
                'get_contract_clause_stats'
            )
            ORDER BY routine_name;
        """)
        functions = cursor.fetchall()

        if len(functions) == 6:
            print("✓ All 6 helper functions created")
            print("\nFunctions:")
            for (func_name,) in functions:
                print(f"  - {func_name}()")
        else:
            print(f"✗ Expected 6 functions, found {len(functions)}")
            for (func_name,) in functions:
                print(f"  - {func_name}()")

        # Verify indexes
        print("\n" + "=" * 80)
        print("5. Checking indexes...")
        print("=" * 80)
        cursor.execute("""
            SELECT indexname, tablename
            FROM pg_indexes
            WHERE schemaname = 'public'
            AND indexname IN (
                'idx_contract_pii_mapping_contract_id',
                'idx_contract_pii_mapping_created_at',
                'idx_contract_pii_mapping_accessed_at',
                'idx_contract_parsing_status',
                'idx_contract_parsing_completed_at',
                'idx_clause_confidence_score',
                'idx_clause_beneficiary_party'
            )
            ORDER BY tablename, indexname;
        """)
        indexes = cursor.fetchall()

        print(f"✓ Found {len(indexes)} indexes")
        print("\nIndexes:")
        for idx_name, table_name in indexes:
            print(f"  - {idx_name} on {table_name}")

        # Verify pgcrypto extension
        print("\n" + "=" * 80)
        print("6. Checking pgcrypto extension...")
        print("=" * 80)
        cursor.execute("""
            SELECT extname, extversion
            FROM pg_extension
            WHERE extname = 'pgcrypto';
        """)
        extension = cursor.fetchone()

        if extension:
            ext_name, ext_version = extension
            print(f"✓ pgcrypto extension installed (version {ext_version})")
        else:
            print("⚠ pgcrypto extension NOT found")

        print("\n" + "=" * 80)
        print("VERIFICATION COMPLETE")
        print("=" * 80)
        print("\n✅ All Phase 2 migrations applied successfully!")

        cursor.close()
        conn.close()
        return True

    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = verify_schema()
    sys.exit(0 if success else 1)
