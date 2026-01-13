-- =====================================================
-- ONE-TIME DATABASE RESET FOR PRODUCTION FIX
-- =====================================================
-- This script fixes the PostgreSQL sequence conflict issue
-- Run this ONCE in Supabase SQL Editor
-- After this, the system will work indefinitely without manual cleanup
-- =====================================================

BEGIN;

-- Step 1: Clear all existing data (including old seed data with explicit IDs)
DELETE FROM clause;
DELETE FROM contract_pii_mapping;
DELETE FROM contract;

-- Step 2: Reset sequences to start fresh
-- This ensures next inserts get IDs starting from 1
SELECT SETVAL('clause_id_seq', 1, false);
SELECT SETVAL('contract_id_seq', 1, false);
SELECT SETVAL('contract_pii_mapping_id_seq', 1, false);

-- Step 3: Verify sequences are reset
SELECT 'clause_id_seq' as sequence_name, last_value, is_called FROM clause_id_seq
UNION ALL
SELECT 'contract_id_seq', last_value, is_called FROM contract_id_seq
UNION ALL
SELECT 'contract_pii_mapping_id_seq', last_value, is_called FROM contract_pii_mapping_id_seq;

COMMIT;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================
-- After running the above, check that tables are empty:
SELECT COUNT(*) as clause_count FROM clause;
SELECT COUNT(*) as contract_count FROM contract;
SELECT COUNT(*) as pii_mapping_count FROM contract_pii_mapping;

-- All should return 0

-- =====================================================
-- NEXT STEP: Reload seed data
-- =====================================================
-- After running this script:
-- 1. Copy the contents of: database/seed/fixtures/02_test_project.sql
-- 2. Paste and run it in Supabase SQL Editor
-- 3. Verify with: SELECT MAX(id) FROM clause;
-- 4. Then run your end-to-end test - it will work forever!
-- =====================================================
