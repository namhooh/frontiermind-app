-- Migration 050: Rename GRP (Grid Reference Price) → MRP (Market Reference Price)
-- This is a terminology change only — no logic changes.
-- "Grid Reference Price" is now "Market Reference Price" across the application.
--
-- Note: tariff_monthly_rate was merged into tariff_rate by migration 040.
-- The old discounted_grp_local column no longer exists (it became a JSONB
-- value inside tariff_rate.rate_components → discounted_base).

BEGIN;

-- ============================================================
-- A. Rename columns
-- ============================================================

-- A1. reference_price.calculated_grp_per_kwh → calculated_mrp_per_kwh
ALTER TABLE reference_price
  RENAME COLUMN calculated_grp_per_kwh TO calculated_mrp_per_kwh;

-- ============================================================
-- B. Update ALL grp_* JSONB keys in clause_tariff.logic_parameters
-- ============================================================

UPDATE clause_tariff
SET logic_parameters = (
  logic_parameters
    - 'grp_method'
    - 'grp_included_components'
    - 'grp_excluded_components'
    - 'grp_time_window_start'
    - 'grp_time_window_end'
    - 'grp_per_kwh'
    - 'grp_clause_text'
    - 'grp_calculation_due_days'
    - 'grp_exclude_demand_charges'
    - 'grp_exclude_vat'
    - 'grp_verification_deadline_days'
  ) || jsonb_strip_nulls(jsonb_build_object(
    'mrp_method',                    logic_parameters->'grp_method',
    'mrp_included_components',       logic_parameters->'grp_included_components',
    'mrp_excluded_components',       logic_parameters->'grp_excluded_components',
    'mrp_time_window_start',         logic_parameters->'grp_time_window_start',
    'mrp_time_window_end',           logic_parameters->'grp_time_window_end',
    'mrp_per_kwh',                   logic_parameters->'grp_per_kwh',
    'mrp_clause_text',               logic_parameters->'grp_clause_text',
    'mrp_calculation_due_days',      logic_parameters->'grp_calculation_due_days',
    'mrp_exclude_demand_charges',    logic_parameters->'grp_exclude_demand_charges',
    'mrp_exclude_vat',               logic_parameters->'grp_exclude_vat',
    'mrp_verification_deadline_days',logic_parameters->'grp_verification_deadline_days'
  ))
WHERE logic_parameters IS NOT NULL
  AND (
    logic_parameters ? 'grp_method'
    OR logic_parameters ? 'grp_included_components'
    OR logic_parameters ? 'grp_excluded_components'
    OR logic_parameters ? 'grp_time_window_start'
    OR logic_parameters ? 'grp_time_window_end'
    OR logic_parameters ? 'grp_per_kwh'
    OR logic_parameters ? 'grp_clause_text'
    OR logic_parameters ? 'grp_calculation_due_days'
    OR logic_parameters ? 'grp_exclude_demand_charges'
    OR logic_parameters ? 'grp_exclude_vat'
    OR logic_parameters ? 'grp_verification_deadline_days'
  );

-- ============================================================
-- C. Update submission_type enum value
-- ============================================================

-- C1. Drop old CHECK constraints first (must precede data update)
ALTER TABLE submission_token
  DROP CONSTRAINT IF EXISTS chk_submission_type;

ALTER TABLE submission_token
  DROP CONSTRAINT IF EXISTS chk_grp_requires_project;

-- C2. Update existing rows
UPDATE submission_token
SET submission_type = 'mrp_upload'
WHERE submission_type = 'grp_upload';

-- C3. Re-add CHECK constraints with updated values
ALTER TABLE submission_token
  ADD CONSTRAINT chk_submission_type
  CHECK (submission_type IN ('form_response', 'mrp_upload'));

ALTER TABLE submission_token
  ADD CONSTRAINT chk_mrp_requires_project
  CHECK (submission_type <> 'mrp_upload' OR project_id IS NOT NULL);

-- ============================================================
-- D. Update table/column comments
-- ============================================================

COMMENT ON TABLE reference_price IS
  'Annual Market Reference Price calculated from Utility Reference Invoices. Used as P_Alternate in GRID tariff pricing and shortfall payment calculations.';

COMMENT ON COLUMN reference_price.calculated_mrp_per_kwh IS
  'Calculated MRP in local currency per kWh: total_variable_charges / total_kwh_invoiced.';

COMMENT ON COLUMN submission_token.project_id IS
  'Project context for MRP and other project-scoped submissions.';

COMMENT ON COLUMN submission_token.submission_type IS
  'Type of submission: form_response (default), mrp_upload.';

COMMENT ON COLUMN tariff_rate.reference_price_id IS
  'FK to reference_price (MRP observation). NULL for deterministic tariffs.';

COMMIT;
