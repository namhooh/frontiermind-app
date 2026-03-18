-- Migration 059: Tariff Classification Taxonomy Restructure
--
-- Separates three orthogonal classification dimensions on clause_tariff:
--   tariff_type      → repurposed: Offtake/Billing Model (how the buyer pays)
--   energy_sale_type → repurposed: Revenue/Product Type (what is being sold)
--   escalation_type  → expanded:   Pricing Mechanism + Escalation (how rate changes)
--
-- All three lookup tables are only referenced by clause_tariff (~60 rows).
-- FLOATING_* codes stored as flat rows in escalation_type (no parent_id hierarchy).

BEGIN;

SET statement_timeout = '300s';

-- ============================================================================
-- PHASE 1: Expand escalation_type with new flat codes (no parent_id)
-- ============================================================================

-- 1a. Insert FLOATING_* as flat codes + NOT_ENERGY_SALES
INSERT INTO escalation_type (code, name, description, organization_id)
VALUES
  ('FLOATING_GRID', 'Floating Grid Tariff',
   'Rate derived from grid utility tariff with discount', 1),
  ('FLOATING_GENERATOR', 'Floating Generator Tariff',
   'Rate derived from diesel/gas generator cost with discount', 1),
  ('FLOATING_GRID_GENERATOR', 'Floating Grid + Generator Tariff',
   'Rate derived from combined grid and generator baseline', 1),
  ('NOT_ENERGY_SALES', 'N/A - not Energy Sales',
   'Contract is not an energy sales arrangement (e.g. lease, O&M)', 1)
ON CONFLICT DO NOTHING;


-- ============================================================================
-- PHASE 2: Migrate clause_tariff.escalation_type_id for FLOATING + non-energy rows
-- ============================================================================

-- 2a. FLOATING_GRID rows → FLOATING_GRID escalation_type
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'FLOATING_GRID' AND organization_id = 1)
FROM energy_sale_type est
WHERE ct.energy_sale_type_id = est.id AND est.code = 'FLOATING_GRID';

-- 2b. FLOATING_GENERATOR rows → FLOATING_GENERATOR escalation_type
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'FLOATING_GENERATOR' AND organization_id = 1)
FROM energy_sale_type est
WHERE ct.energy_sale_type_id = est.id AND est.code = 'FLOATING_GENERATOR';

-- 2c. FLOATING_GRID_GENERATOR rows → FLOATING_GRID_GENERATOR escalation_type
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'FLOATING_GRID_GENERATOR' AND organization_id = 1)
FROM energy_sale_type est
WHERE ct.energy_sale_type_id = est.id AND est.code = 'FLOATING_GRID_GENERATOR';

-- 2d. NOT_ENERGY_SALES rows → NOT_ENERGY_SALES escalation_type
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'NOT_ENERGY_SALES' AND organization_id = 1)
FROM energy_sale_type est
WHERE ct.energy_sale_type_id = est.id AND est.code = 'NOT_ENERGY_SALES';


-- ============================================================================
-- PHASE 3: Repurpose energy_sale_type → Revenue/Product Type
-- ============================================================================

-- 3a. Clear all clause_tariff.energy_sale_type_id (will re-populate from tariff_type codes)
UPDATE clause_tariff SET energy_sale_type_id = NULL;

-- 3b. Delete old rows (FIXED_SOLAR, FLOATING_*, NOT_ENERGY_SALES, ENERGY, CAPACITY)
DELETE FROM energy_sale_type;

-- 3c. Insert new revenue/product type values (copied from current tariff_type codes)
INSERT INTO energy_sale_type (code, name, description, organization_id) VALUES
  ('ENERGY_SALES',           'Energy Sales',                'Energy sales contract — solar, grid, or generator tariff', 1),
  ('EQUIPMENT_RENTAL_LEASE', 'Equipment Rental/Lease/Boot', 'Equipment rental, lease, or boot arrangement', 1),
  ('LOAN',                   'Loan',                        'Loan financing arrangement', 1),
  ('BESS_LEASE',             'Battery Lease (BESS)',         'Battery energy storage system lease', 1),
  ('ENERGY_AS_SERVICE',      'Energy as a Service',          'Bundled energy-as-a-service contract', 1),
  ('OTHER_SERVICE',          'Other',                        'Other contract service/product type', 1),
  ('NOT_APPLICABLE',         'N/A',                          'Not applicable — no specific contract service type', 1);

-- 3d. Re-populate clause_tariff.energy_sale_type_id from old tariff_type values
-- Direct code-to-code mapping (same codes, just moving table)
UPDATE clause_tariff ct
SET energy_sale_type_id = est.id
FROM tariff_type tt, energy_sale_type est
WHERE ct.tariff_type_id = tt.id
  AND est.code = tt.code
  AND est.organization_id = 1;

-- 3e. Remaining NULLs — Main Tariff rows default to ENERGY_SALES
UPDATE clause_tariff
SET energy_sale_type_id = (SELECT id FROM energy_sale_type WHERE code = 'ENERGY_SALES' AND organization_id = 1)
WHERE energy_sale_type_id IS NULL AND name LIKE '%Main Tariff%';

-- 3f. BESS rows
UPDATE clause_tariff
SET energy_sale_type_id = (SELECT id FROM energy_sale_type WHERE code = 'BESS_LEASE' AND organization_id = 1)
WHERE energy_sale_type_id IS NULL AND name LIKE '%BESS%';


-- ============================================================================
-- PHASE 4: Repurpose tariff_type → Offtake/Billing Model
-- ============================================================================

-- 4a. Clear all clause_tariff.tariff_type_id
UPDATE clause_tariff SET tariff_type_id = NULL;

-- 4b. Delete old rows (ENERGY_SALES, EQUIPMENT_RENTAL_LEASE, LOAN, etc.)
DELETE FROM tariff_type;

-- 4c. Insert new offtake-model values (tariff_type has no organization_id column)
INSERT INTO tariff_type (code, name, description) VALUES
  ('TAKE_OR_PAY',     'Take or Pay',     'Buyer pays for contracted volume regardless of consumption'),
  ('TAKE_AND_PAY',    'Take and Pay',    'Buyer pays only for energy actually consumed'),
  ('MINIMUM_OFFTAKE', 'Minimum Offtake', 'Buyer commits to minimum consumption threshold'),
  ('FINANCE_LEASE',   'Finance Lease',   'Equipment financing structure'),
  ('OPERATING_LEASE', 'Operating Lease', 'Operating lease arrangement'),
  ('NOT_APPLICABLE',  'N/A',             'Non-energy or no specific offtake model');

-- 4d. Populate tariff_type_id from PO Summary col E mapping
-- TAKE_OR_PAY projects
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'TAKE_OR_PAY')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id IN ('KAS01', 'UTK01', 'LOI01', 'JAB01', 'UGL01',
                     'XFAB', 'XFBV', 'XFL01', 'XFSS',
                     'NBL01', 'NBL02', 'GBL01', 'TBM01', 'QMM01',
                     'MIR01', 'CAL01', 'AMP01', 'MOH01')
  AND ct.tariff_type_id IS NULL;

-- IVL01 main tariff only (not O&M)
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'TAKE_OR_PAY')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id = 'IVL01'
  AND ct.name NOT LIKE '%O&M%'
  AND ct.tariff_type_id IS NULL;

-- TAKE_AND_PAY
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'TAKE_AND_PAY')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id = 'UNSOS'
  AND ct.tariff_type_id IS NULL;

-- MINIMUM_OFFTAKE
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'MINIMUM_OFFTAKE')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id IN ('MB01', 'MF01', 'MP01', 'MP02', 'NC02', 'NC03', 'ERG')
  AND ct.tariff_type_id IS NULL;

-- FINANCE_LEASE
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'FINANCE_LEASE')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id = 'GC001'
  AND ct.tariff_type_id IS NULL;

-- OPERATING_LEASE
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'OPERATING_LEASE')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id = 'AR01'
  AND ct.tariff_type_id IS NULL;

-- NOT_APPLICABLE — non-energy tariff rows + specific projects
UPDATE clause_tariff ct
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'NOT_APPLICABLE')
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id IN ('ZL01', 'ZL02', 'TWG01')
  AND ct.tariff_type_id IS NULL;

-- NOT_APPLICABLE — O&M, BESS, Lease, Diesel, Penalty rows for any project
UPDATE clause_tariff
SET tariff_type_id = (SELECT id FROM tariff_type WHERE code = 'NOT_APPLICABLE')
WHERE tariff_type_id IS NULL
  AND (name LIKE '%O&M%' OR name LIKE '%BESS%' OR name LIKE '%Lease%'
       OR name LIKE '%Diesel%' OR name LIKE '%Penalt%');


-- ============================================================================
-- PHASE 5: Fix remaining NULL escalation_type_id values
-- ============================================================================

-- PERCENTAGE escalation for known projects
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'PERCENTAGE' AND organization_id = 1)
FROM project p
WHERE ct.project_id = p.id
  AND ct.escalation_type_id IS NULL
  AND p.sage_id IN ('AMP01', 'CAL01', 'MIR01', 'TBM01', 'UTK01', 'IVL01');

-- NONE (fixed price) for known projects
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'NONE' AND organization_id = 1)
FROM project p
WHERE ct.project_id = p.id
  AND ct.escalation_type_id IS NULL
  AND p.sage_id IN ('QMM01', 'UNSOS');

-- US_CPI for known projects
UPDATE clause_tariff ct
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'US_CPI' AND organization_id = 1)
FROM project p
WHERE ct.project_id = p.id
  AND ct.escalation_type_id IS NULL
  AND p.sage_id IN ('GC001');

-- NOT_ENERGY_SALES for remaining non-energy rows
UPDATE clause_tariff
SET escalation_type_id = (SELECT id FROM escalation_type WHERE code = 'NOT_ENERGY_SALES' AND organization_id = 1)
WHERE escalation_type_id IS NULL
  AND (name LIKE '%O&M%' OR name LIKE '%BESS%' OR name LIKE '%Lease%'
       OR name LIKE '%Diesel%' OR name LIKE '%Penalt%');


-- ============================================================================
-- PHASE 6: Drop parent_id column if it exists (cleanup from earlier draft)
-- ============================================================================

ALTER TABLE escalation_type DROP COLUMN IF EXISTS parent_id;


-- ============================================================================
-- PHASE 7: Verification assertions
-- ============================================================================

DO $$ BEGIN
  -- All 3 lookup tables populated
  ASSERT (SELECT COUNT(*) FROM tariff_type) = 6,
    'tariff_type should have 6 rows';
  ASSERT (SELECT COUNT(*) FROM energy_sale_type) = 7,
    'energy_sale_type should have 7 rows';
  ASSERT (SELECT COUNT(*) FROM escalation_type) >= 10,
    'escalation_type should have at least 10 rows (6 original + 3 FLOATING + NOT_ENERGY_SALES)';

  -- No parent_id column (flat hierarchy)
  ASSERT NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'escalation_type' AND column_name = 'parent_id'
  ), 'escalation_type should not have parent_id column';

  -- No NULLs except ABI01, BNT01 (not in PO Summary) + NBL01 (escalation TBD)
  ASSERT (SELECT COUNT(*) FROM clause_tariff WHERE escalation_type_id IS NULL) <= 3,
    'at most 3 clause_tariff rows should have NULL escalation_type_id';
  ASSERT (SELECT COUNT(*) FROM clause_tariff WHERE energy_sale_type_id IS NULL) <= 3,
    'at most 3 clause_tariff rows should have NULL energy_sale_type_id';
END $$;

COMMIT;
