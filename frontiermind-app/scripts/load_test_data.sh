#!/bin/bash
# Load test data scenario

source .env.local

echo "Loading test data..."

# Load in order
psql $SUPABASE_DB_URL -f database/seed/00_reference_data.sql
psql $SUPABASE_DB_URL -f database/seed/01_test_organizations.sql
psql $SUPABASE_DB_URL -f database/seed/02_test_project.sql
psql $SUPABASE_DB_URL -f database/seed/03_default_event_scenario.sql

echo "✅ Test data loaded"
