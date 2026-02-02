#!/usr/bin/env python3
"""
Database Diagnostic Script

Checks database connectivity and seed data status for the entities API.
Run this from the python-backend directory:
    python scripts/diagnose_db.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_database():
    """Run diagnostic checks on the database."""

    print("=" * 60)
    print("FrontierMind Database Diagnostic")
    print("=" * 60)

    # Check 1: DATABASE_URL environment variable
    db_url = os.getenv("DATABASE_URL")
    print("\n1. DATABASE_URL Check:")
    if not db_url:
        print("   ❌ DATABASE_URL is NOT SET")
        print("   Fix: Add DATABASE_URL to python-backend/.env")
        print("   Example: DATABASE_URL=postgresql://user:pass@host:port/database")
        return False
    else:
        # Mask password in output
        masked = db_url
        if "@" in db_url and ":" in db_url:
            parts = db_url.split("@")
            user_pass = parts[0].split("://")[1] if "://" in parts[0] else parts[0]
            if ":" in user_pass:
                user = user_pass.split(":")[0]
                masked = db_url.replace(user_pass, f"{user}:****")
        print(f"   ✅ DATABASE_URL is set")
        print(f"   Value: {masked}")

    # Check 2: Database connection
    print("\n2. Database Connection Check:")
    try:
        from db.database import init_connection_pool, get_db_connection, close_connection_pool

        # Force re-initialization
        close_connection_pool()
        init_connection_pool()
        print("   ✅ Connection pool initialized successfully")

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 as test")
                result = cursor.fetchone()
                if result and result.get('test') == 1:
                    print("   ✅ Database query successful")
                else:
                    print("   ❌ Database query returned unexpected result")
                    return False

    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        print("\n   Possible causes:")
        print("   - Wrong password in DATABASE_URL")
        print("   - Database server not accessible")
        print("   - Wrong host/port")
        print("\n   Fix: Update DATABASE_URL in python-backend/.env with correct credentials")
        print("   Get the connection string from Supabase Dashboard → Project Settings → Database")
        return False

    # Check 3: Organization data
    print("\n3. Organization Data Check:")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM organization")
                result = cursor.fetchone()
                count = result.get('count', 0) if result else 0

                if count > 0:
                    print(f"   ✅ Found {count} organization(s)")

                    cursor.execute("SELECT id, name FROM organization ORDER BY id LIMIT 5")
                    orgs = cursor.fetchall()
                    for org in orgs:
                        print(f"      - ID {org['id']}: {org['name']}")
                else:
                    print("   ❌ No organizations found in database")
                    print("\n   Fix: Run the seed data script:")
                    print("   psql \"$DATABASE_URL\" -f database/seed/fixtures/dummy_data.sql")
                    return False

    except Exception as e:
        print(f"   ❌ Query failed: {e}")
        print("   The 'organization' table may not exist.")
        print("   Run database migrations first.")
        return False

    # Check 4: Project data
    print("\n4. Project Data Check:")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM project")
                result = cursor.fetchone()
                count = result.get('count', 0) if result else 0

                if count > 0:
                    print(f"   ✅ Found {count} project(s)")

                    cursor.execute("""
                        SELECT p.id, p.name, p.organization_id, o.name as org_name
                        FROM project p
                        LEFT JOIN organization o ON p.organization_id = o.id
                        ORDER BY p.id LIMIT 5
                    """)
                    projects = cursor.fetchall()
                    for proj in projects:
                        print(f"      - ID {proj['id']}: {proj['name']} (Org: {proj['org_name']})")
                else:
                    print("   ❌ No projects found in database")
                    print("\n   Fix: Run the seed data script:")
                    print("   psql \"$DATABASE_URL\" -f database/seed/fixtures/dummy_data.sql")
                    return False

    except Exception as e:
        print(f"   ❌ Query failed: {e}")
        return False

    # Cleanup
    close_connection_pool()

    print("\n" + "=" * 60)
    print("✅ All checks passed! The API should return data correctly.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = check_database()
    sys.exit(0 if success else 1)
