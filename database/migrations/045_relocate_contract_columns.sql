-- =============================================================================
-- Migration 045: Relocate misplaced contract columns
-- =============================================================================
-- Moves columns that were added during onboarding (migration 033) but don't
-- belong on the contract table:
--
--   A. interconnection_voltage_kv  → project.technical_specs  (JSONB)
--   B. agreed_fx_rate_source       → clause_tariff            (VARCHAR)
--   C. payment_security_*          → clause                   (SECURITY_PACKAGE)
--   D. Drop deprecated columns from contract
-- =============================================================================

BEGIN;

-- ============================================================================
-- A. interconnection_voltage_kv → project.technical_specs JSONB
-- ============================================================================

ALTER TABLE project ADD COLUMN IF NOT EXISTS technical_specs JSONB DEFAULT '{}';

COMMENT ON COLUMN project.technical_specs IS
  'Technical specifications JSONB bag. Keys: interconnection_voltage_kv, etc.';

-- Migrate existing data from contract → project
UPDATE project p
SET technical_specs = COALESCE(p.technical_specs, '{}'::jsonb)
  || jsonb_build_object('interconnection_voltage_kv', c.interconnection_voltage_kv)
FROM contract c
WHERE c.project_id = p.id
  AND c.interconnection_voltage_kv IS NOT NULL;

-- ============================================================================
-- B. agreed_fx_rate_source → clause_tariff
-- ============================================================================

ALTER TABLE clause_tariff ADD COLUMN IF NOT EXISTS agreed_fx_rate_source VARCHAR(255);

COMMENT ON COLUMN clause_tariff.agreed_fx_rate_source IS
  'Agreed source/method for FX rate determination (e.g. "Central Bank of Ghana mid-rate")';

-- Migrate: copy from contract to all is_current=true tariffs for that contract
UPDATE clause_tariff ct
SET agreed_fx_rate_source = c.agreed_fx_rate_source
FROM contract c
WHERE ct.contract_id = c.id
  AND ct.is_current = true
  AND c.agreed_fx_rate_source IS NOT NULL;

-- ============================================================================
-- C. Payment security → clause records (category: SECURITY_PACKAGE)
-- ============================================================================

-- Insert a clause for each contract that has payment_security_required = true
-- or has payment_security_details populated.
INSERT INTO clause (
  contract_id,
  clause_category_id,
  section_ref,
  name,
  normalized_payload,
  is_current
)
SELECT
  c.id,
  cc.id,
  'SEC-001',
  'Payment Security',
  jsonb_build_object(
    'required', COALESCE(c.payment_security_required, false),
    'details', c.payment_security_details
  ),
  true
FROM contract c
CROSS JOIN clause_category cc
WHERE cc.code = 'SECURITY_PACKAGE'
  AND (c.payment_security_required = true OR c.payment_security_details IS NOT NULL)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- D. Drop deprecated columns from contract
-- ============================================================================
-- Data verified migrated; no code reads these from contract anymore.
-- Remaining references are in staging tables (transport layer) and onboarding
-- models, which feed into the new targets via onboard_project.sql.

ALTER TABLE contract DROP COLUMN IF EXISTS interconnection_voltage_kv;
ALTER TABLE contract DROP COLUMN IF EXISTS payment_security_required;
ALTER TABLE contract DROP COLUMN IF EXISTS payment_security_details;
ALTER TABLE contract DROP COLUMN IF EXISTS agreed_fx_rate_source;

COMMIT;
