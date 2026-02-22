-- Migration 039: Pipeline Integrity Fixes
--
-- Addresses verified gaps from pipeline gap analysis:
-- A. Partial unique index on annual reference_price rows (prevents duplicate
--    annual rows when period_start varies for the same operating year)
-- B. Seed missing asset_type codes (tracker, meter, mounting_structure,
--    combiner_box) so onboarding FK lookups resolve
-- C. Expand metering_type CHECK constraint to include 'gross' and
--    'bidirectional' (real metering types produced by the normalizer)
-- D. Remove hardcoded UPDATE from migration 037 (make idempotent via
--    stable tariff_group_key lookup)

-- =============================================================================
-- A. Partial unique index on annual reference_price rows
-- =============================================================================
-- The existing unique constraint is (project_id, observation_type, period_start).
-- Annual period_start is derived from the first monthly row's period_start,
-- which can vary depending on which monthly rows exist. This index ensures
-- only one annual row per (project_id, operating_year).
--
-- Pre-dedupe: if duplicate annual rows exist for the same (project_id,
-- operating_year), keep only the most recently updated one before creating
-- the unique index.

DELETE FROM reference_price
WHERE observation_type = 'annual'
  AND id NOT IN (
      SELECT DISTINCT ON (project_id, operating_year) id
      FROM reference_price
      WHERE observation_type = 'annual'
      ORDER BY project_id, operating_year, COALESCE(updated_at, created_at) DESC
  );

CREATE UNIQUE INDEX IF NOT EXISTS uq_reference_price_annual_project_year
  ON reference_price (project_id, operating_year)
  WHERE observation_type = 'annual';

-- =============================================================================
-- B. Seed missing asset_type codes
-- =============================================================================
-- The excel_parser produces these codes but they weren't in the seed data.

INSERT INTO asset_type (name, code, description) VALUES
  ('Tracker', 'tracker', 'Single-axis or dual-axis solar tracker'),
  ('Meter', 'meter', 'Revenue or check meter'),
  ('Mounting Structure', 'mounting_structure', 'Fixed-tilt racking or mounting system'),
  ('Combiner Box', 'combiner_box', 'DC string combiner box')
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- C. Expand metering_type CHECK constraint
-- =============================================================================
-- The normalizer can return 'gross' and 'bidirectional' which are valid
-- metering configurations. The old constraint only allowed 'net'/'export_only'.

ALTER TABLE meter DROP CONSTRAINT IF EXISTS chk_meter_metering_type;
ALTER TABLE meter ADD CONSTRAINT chk_meter_metering_type
  CHECK (metering_type IS NULL OR metering_type IN ('net', 'export_only', 'gross', 'bidirectional'));

COMMENT ON COLUMN meter.metering_type IS 'Metering configuration: net, export_only, gross, or bidirectional.';

-- =============================================================================
-- D. Idempotent GRP seed for GH-MOH01 via stable tariff_group_key
-- =============================================================================
-- Migration 037 used `WHERE id = 2` which is environment-specific.
-- This replaces it with a stable lookup by tariff_group_key.

UPDATE clause_tariff
SET logic_parameters = COALESCE(logic_parameters, '{}'::jsonb) || '{
    "grp_method": "utility_variable_charges_tou",
    "grp_clause_text": "The Grid Reference Price (\"GRP\") for each month shall be calculated as the sum of all variable energy charges (excluding VAT, demand charges, and fixed charges) from the applicable ECG Utility Reference Invoice, divided by the total kWh invoiced during the billing period. Only charges incurred during the 06:00–18:00 operating window shall be included. The Utility Company shall deliver each Reference Invoice within 15 days of the end of the billing month. The Parties shall jointly verify the GRP within 30 days of receipt."
}'::jsonb
WHERE tariff_group_key = 'GH-MOH01-PPA-001-MAIN'
  AND (logic_parameters IS NULL OR NOT logic_parameters ? 'grp_method');
