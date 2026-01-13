-- Verification Queries for Phase 2 Migrations
-- Run these in Supabase SQL Editor AFTER applying each migration

-- ==============================================================================
-- VERIFY Migration 002: contract_pii_mapping table
-- ==============================================================================

-- Check if table exists
SELECT
    'contract_pii_mapping table' AS check_name,
    CASE WHEN EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = 'contract_pii_mapping'
    ) THEN '✓ PASS' ELSE '✗ FAIL' END AS status;

-- List all columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'contract_pii_mapping'
ORDER BY ordinal_position;

-- Check helper functions
SELECT routine_name
FROM information_schema.routines
WHERE routine_schema = 'public'
AND routine_name IN ('log_pii_access', 'get_contract_pii_count');

-- ==============================================================================
-- VERIFY Migration 003: contract table new columns
-- ==============================================================================

-- Check new columns exist
SELECT
    'contract parsing columns' AS check_name,
    COUNT(*) AS columns_added,
    CASE WHEN COUNT(*) = 7 THEN '✓ PASS' ELSE '✗ FAIL' END AS status
FROM information_schema.columns
WHERE table_name = 'contract'
AND column_name IN (
    'parsing_status',
    'parsing_started_at',
    'parsing_completed_at',
    'parsing_error',
    'pii_detected_count',
    'clauses_extracted_count',
    'processing_time_seconds'
);

-- List new columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'contract'
AND column_name IN (
    'parsing_status',
    'parsing_started_at',
    'parsing_completed_at',
    'parsing_error',
    'pii_detected_count',
    'clauses_extracted_count',
    'processing_time_seconds'
);

-- Check helper functions
SELECT routine_name
FROM information_schema.routines
WHERE routine_schema = 'public'
AND routine_name IN ('update_contract_parsing_status', 'get_parsing_statistics');

-- ==============================================================================
-- VERIFY Migration 004: clause table new columns
-- ==============================================================================

-- Check new columns exist
SELECT
    'clause AI columns' AS check_name,
    COUNT(*) AS columns_added,
    CASE WHEN COUNT(*) = 3 THEN '✓ PASS' ELSE '✗ FAIL' END AS status
FROM information_schema.columns
WHERE table_name = 'clause'
AND column_name IN ('summary', 'beneficiary_party', 'confidence_score');

-- List new columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'clause'
AND column_name IN ('summary', 'beneficiary_party', 'confidence_score');

-- Check helper functions
SELECT routine_name
FROM information_schema.routines
WHERE routine_schema = 'public'
AND routine_name IN ('get_clauses_needing_review', 'get_contract_clause_stats');

-- ==============================================================================
-- SUMMARY: All Migrations
-- ==============================================================================

SELECT
    'All migrations verification' AS check_name,
    '✓ If all above checks PASS, migrations successful!' AS status;
