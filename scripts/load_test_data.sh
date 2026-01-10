#!/bin/bash
# Load reference and test data

source .env.local

echo "Loading reference data..."

# Load reference data (production lookup tables)
psql $SUPABASE_DB_URL -f database/seed/reference/00_reference_data.sql

echo "✅ Reference data loaded"
echo ""
echo "Loading test fixtures..."

# Load test fixtures (development/testing only)
psql $SUPABASE_DB_URL -f database/seed/fixtures/01_test_organizations.sql
psql $SUPABASE_DB_URL -f database/seed/fixtures/02_test_project.sql
psql $SUPABASE_DB_URL -f database/seed/fixtures/03_default_event_scenario.sql
psql $SUPABASE_DB_URL -f database/seed/fixtures/05_auth_seed.sql

echo "✅ Test fixtures loaded"
