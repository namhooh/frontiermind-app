-- =====================================================
-- CLEAN PRODUCTION RESET
-- =====================================================
-- This script deletes all test/dummy data and resets sequences
-- while preserving essential lookup/reference tables.
--
-- Run this ONCE in Supabase SQL Editor to prepare for production.
-- After this, the parser will create real contracts from PDFs.
-- =====================================================

BEGIN;

-- =====================================================
-- STEP 1: Delete all test/dummy transactional data
-- =====================================================

DELETE FROM clause;
DELETE FROM clause_tariff;
DELETE FROM contract_pii_mapping;
DELETE FROM contract;
DELETE FROM project;
DELETE FROM asset;
DELETE FROM meter;
DELETE FROM data_source;

-- Delete test entities (if they exist from dummy data)
DELETE FROM organization WHERE id IN (1, 2);
DELETE FROM counterparty WHERE id IN (1, 2);
DELETE FROM clause_responsibleparty WHERE id IN (1, 2);
DELETE FROM vendor WHERE id IN (1, 2, 3);
DELETE FROM role WHERE id IN (1, 2, 3);
DELETE FROM grid_operator WHERE id = 1;

-- =====================================================
-- STEP 2: Reset ALL sequences to start from 1
-- =====================================================

SELECT SETVAL('project_id_seq', 1, false);
SELECT SETVAL('contract_id_seq', 1, false);
SELECT SETVAL('clause_id_seq', 1, false);
SELECT SETVAL('clause_tariff_id_seq', 1, false);
SELECT SETVAL('contract_pii_mapping_id_seq', 1, false);
SELECT SETVAL('asset_id_seq', 1, false);
SELECT SETVAL('meter_id_seq', 1, false);
SELECT SETVAL('data_source_id_seq', 1, false);
SELECT SETVAL('organization_id_seq', 1, false);
SELECT SETVAL('counterparty_id_seq', 1, false);
SELECT SETVAL('clause_responsibleparty_id_seq', 1, false);
SELECT SETVAL('vendor_id_seq', 1, false);
SELECT SETVAL('role_id_seq', 1, false);
SELECT SETVAL('grid_operator_id_seq', 1, false);

-- =====================================================
-- STEP 3: Verify reference data exists
-- =====================================================
-- These lookup tables should have data and remain untouched

SELECT 'Reference Data Summary' as info;
SELECT COUNT(*) as contract_types FROM contract_type;
SELECT COUNT(*) as contract_statuses FROM contract_status;
SELECT COUNT(*) as clause_types FROM clause_type;
SELECT COUNT(*) as clause_categories FROM clause_category;
SELECT COUNT(*) as counterparty_types FROM counterparty_type;

COMMIT;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================
-- Run these to confirm database is clean:

SELECT COUNT(*) as clause_count FROM clause;           -- Should be 0
SELECT COUNT(*) as contract_count FROM contract;       -- Should be 0
SELECT COUNT(*) as project_count FROM project;         -- Should be 0

-- Check sequences are reset (all should be 1)
SELECT last_value FROM contract_id_seq;
SELECT last_value FROM clause_id_seq;
SELECT last_value FROM project_id_seq;

-- =====================================================
-- NEXT STEP
-- =====================================================
-- Run end-to-end test:
--   python test_end_to_end.py "test_data/City Fort Collins_Power_Purchase_AgreementPPA).pdf"
--
-- The parser will create:
--   - First contract (ID = 1) from the PDF
--   - Clauses (IDs = 1, 2, 3, ...) extracted from the PDF
--   - PII mappings for anonymization
--
-- This will work indefinitely without any manual cleanup!
-- =====================================================
