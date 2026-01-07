#!/bin/bash
# Reset database to clean state

# Load environment
source .env.local

echo "⚠️  WARNING: This will DELETE ALL DATA!"
echo "Database: $SUPABASE_DB_URL"
read -p "Type 'YES' to continue: " confirm

if [ "$confirm" != "YES" ]; then
    echo "Aborted."
    exit 1
fi

echo "Dropping all tables..."
psql $SUPABASE_DB_URL << 'EOF'
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO public;
EOF

echo "✅ Database reset complete"
echo "Next steps:"
echo "  1. Run: ./scripts/apply_schema.sh"
echo "  2. Run: ./scripts/load_reference_data.sh"
echo "  3. Run: ./scripts/load_test_data.sh (optional)"
