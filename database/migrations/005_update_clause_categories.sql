-- =====================================================
-- MIGRATION 005: Update Clause Categories
-- =====================================================
-- Migrates from two-level hierarchy (clause_type + clause_category)
-- to flat 13-category structure per recommendations document.
--
-- Changes:
-- 1. Add key_terms column for search optimization
-- 2. Add 4 new categories: CONDITIONS_PRECEDENT, DEFAULT, MAINTENANCE, SECURITY_PACKAGE
-- 3. Rename codes for consistency (PERF_GUARANTEE → PERFORMANCE_GUARANTEE, etc.)
-- 4. Migrate SLA data to MAINTENANCE and remove SLA
-- 5. Deprecate clause_type table (keep for historical data)
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Add key_terms column to clause_category
-- =====================================================
ALTER TABLE clause_category ADD COLUMN IF NOT EXISTS key_terms TEXT[];

-- =====================================================
-- Step 2: Add 4 new categories
-- =====================================================
INSERT INTO clause_category (code, name, description, key_terms, created_at) VALUES
(
    'CONDITIONS_PRECEDENT',
    'Conditions Precedent',
    'Requirements that must be satisfied before contract becomes effective',
    ARRAY['conditions precedent', 'CP', 'condition to', 'effectiveness', 'closing conditions', 'prerequisite'],
    NOW()
),
(
    'DEFAULT',
    'Default',
    'Events of default, cure periods, remedies, and reimbursement provisions',
    ARRAY['default', 'breach', 'event of default', 'cure', 'remedy', 'reimbursement', 'failure to perform'],
    NOW()
),
(
    'MAINTENANCE',
    'Maintenance',
    'O&M obligations, service level agreements, scheduled outages, and party responsibilities',
    ARRAY['maintenance', 'O&M', 'service level', 'SLA', 'scheduled outage', 'repair', 'preventive maintenance'],
    NOW()
),
(
    'SECURITY_PACKAGE',
    'Security Package',
    'Financial security instruments including letters of credit, bonds, and guarantees',
    ARRAY['letter of credit', 'LC', 'bond', 'guarantee', 'security', 'collateral', 'parent guarantee'],
    NOW()
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    key_terms = EXCLUDED.key_terms;

-- =====================================================
-- Step 3: Rename existing codes for consistency
-- =====================================================
UPDATE clause_category SET
    code = 'PERFORMANCE_GUARANTEE',
    name = 'Performance Guarantee',
    description = 'Output guarantees, capacity factor, performance ratio, and degradation allowances',
    key_terms = ARRAY['performance ratio', 'capacity factor', 'degradation', 'output guarantee', 'energy production', 'PR guarantee']
WHERE code = 'PERF_GUARANTEE';

UPDATE clause_category SET
    code = 'LIQUIDATED_DAMAGES',
    name = 'Liquidated Damages',
    description = 'Penalties for contract breaches including availability shortfall, delays, and performance failures',
    key_terms = ARRAY['liquidated damages', 'LD', 'penalty', 'damages', 'shortfall payment', 'delay damages']
WHERE code = 'LIQ_DAMAGES';

UPDATE clause_category SET
    code = 'PAYMENT_TERMS',
    name = 'Payment Terms',
    description = 'Billing cycles, payment timing, take-or-pay obligations, and invoice procedures',
    key_terms = ARRAY['payment', 'invoice', 'billing', 'take or pay', 'minimum purchase', 'due date', 'net days']
WHERE code = 'PAYMENT';

-- Update existing categories with key_terms
UPDATE clause_category SET
    key_terms = ARRAY['availability', 'uptime', 'meter accuracy', 'curtailment', 'unavailability', 'outage hours']
WHERE code = 'AVAILABILITY' AND key_terms IS NULL;

UPDATE clause_category SET
    key_terms = ARRAY['price', 'rate', '$/kWh', '$/MWh', 'escalation', 'price adjustment', 'tariff']
WHERE code = 'PRICING' AND key_terms IS NULL;

UPDATE clause_category SET
    key_terms = ARRAY['force majeure', 'act of god', 'unforeseeable', 'beyond control', 'excused event']
WHERE code = 'FORCE_MAJEURE' AND key_terms IS NULL;

UPDATE clause_category SET
    key_terms = ARRAY['termination', 'expiration', 'early termination', 'purchase option', 'fair market value', 'buyout', 'FMV']
WHERE code = 'TERMINATION' AND key_terms IS NULL;

UPDATE clause_category SET
    key_terms = ARRAY['compliance', 'regulatory', 'permit', 'environmental', 'law', 'regulation', 'license']
WHERE code = 'COMPLIANCE' AND key_terms IS NULL;

UPDATE clause_category SET
    key_terms = ARRAY['governing law', 'dispute', 'notice', 'assignment', 'amendment', 'waiver', 'confidential', 'severability']
WHERE code = 'GENERAL' AND key_terms IS NULL;

-- =====================================================
-- Step 4: Migrate SLA data to MAINTENANCE and remove SLA
-- =====================================================
-- First, migrate any clauses from SLA to MAINTENANCE
UPDATE clause SET
    clause_category_id = (SELECT id FROM clause_category WHERE code = 'MAINTENANCE')
WHERE clause_category_id = (SELECT id FROM clause_category WHERE code = 'SLA');

-- Now delete the SLA category
DELETE FROM clause_category WHERE code = 'SLA';

-- =====================================================
-- Step 5: Deprecate clause_type table
-- =====================================================
-- Add deprecation comment (keep table for historical data)
-- COMMENT ON TABLE clause_type IS 'DEPRECATED as of migration 005: Use clause_category only for new extractions. Table kept for historical data compatibility.';

-- =====================================================
-- Verification
-- =====================================================
DO $$
DECLARE
    category_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO category_count FROM clause_category;
    IF category_count != 13 THEN
        RAISE WARNING 'Expected 13 categories, found %', category_count;
    ELSE
        RAISE NOTICE 'Migration successful: 13 categories created';
    END IF;
END $$;

COMMIT;

-- Display final state
SELECT 'Final clause_category state:' AS info;
SELECT id, code, name, key_terms IS NOT NULL AS has_key_terms
FROM clause_category
ORDER BY id;
