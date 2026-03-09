-- Migration 056: Add project_id to billing_tax_rule for project-specific overrides
--
-- Resolves Section 9.3 open decision (Option A):
--   NULL project_id = country default
--   non-NULL project_id = project-specific override
--
-- The existing GiST exclusion constraint is updated to include project_id
-- so that project-specific rules don't conflict with country defaults.

-- 1. Add project_id column
ALTER TABLE billing_tax_rule
ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES project(id);

COMMENT ON COLUMN billing_tax_rule.project_id IS
  'NULL = country-level default rule. Non-NULL = project-specific override (e.g., different WHT rate).';

-- 2. Drop and recreate the GiST exclusion constraint to include project_id
-- The old constraint only scoped by (organization_id, country_code, daterange).
-- We need (organization_id, country_code, COALESCE(project_id, 0), daterange)
-- so that a country default (project_id=NULL→0) and a project override can coexist.

ALTER TABLE billing_tax_rule
DROP CONSTRAINT IF EXISTS billing_tax_rule_no_overlap;

ALTER TABLE billing_tax_rule
ADD CONSTRAINT billing_tax_rule_no_overlap
EXCLUDE USING gist (
  organization_id WITH =,
  country_code WITH =,
  COALESCE(project_id, 0) WITH =,
  daterange(effective_start_date, effective_end_date, '[]') WITH &&
) WHERE (is_active = true);

-- 3. Update lookup index to include project_id for efficient queries
DROP INDEX IF EXISTS idx_billing_tax_rule_lookup;
CREATE INDEX idx_billing_tax_rule_lookup
ON billing_tax_rule (organization_id, country_code, project_id, is_active)
WHERE is_active = true;

-- 4. Update the billing API lookup order:
--    First check project-specific rule, then fall back to country default.
--    This is handled in application code, not SQL.
