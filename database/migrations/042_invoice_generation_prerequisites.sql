-- Migration 042: Invoice Generation Prerequisites
-- Phase 10.5: Billing integrity, invoice schema extensions, and tax rules
--
-- 1a. Clean dedup index (drop COALESCE hack, exclude unresolved rows)
-- 1b. contract_line → clause_tariff FK
-- 1c. New invoice_line_item_type entries
-- 1d. expected_invoice_header versioning + idempotency
-- 1e. expected_invoice_line_item audit + sign enforcement
-- 1f. billing_tax_rule with GiST overlap prevention
-- 1g. invoice_header — add invoice_direction
-- 1h. invoice_line_item — tax/component columns + sign constraint

BEGIN;

-- ============================================================================
-- 1a. Clean dedup index — exclude rows with NULL FKs
-- ============================================================================

-- Replace COALESCE-based dedup index with clean resolved-only index
-- Old index used COALESCE(-1) which allowed NULL FKs into the main table
DROP INDEX IF EXISTS idx_meter_aggregate_billing_dedup;

CREATE UNIQUE INDEX idx_meter_aggregate_billing_dedup
ON meter_aggregate (organization_id, meter_id, billing_period_id, contract_line_id)
WHERE period_type = 'monthly'
  AND meter_id IS NOT NULL
  AND billing_period_id IS NOT NULL
  AND contract_line_id IS NOT NULL;

-- ============================================================================
-- 1b. contract_line → clause_tariff explicit FK
-- ============================================================================

ALTER TABLE contract_line
  ADD COLUMN IF NOT EXISTS clause_tariff_id BIGINT REFERENCES clause_tariff(id);

-- ============================================================================
-- 1c. New invoice_line_item_type entries
-- ============================================================================

INSERT INTO invoice_line_item_type (name, code, description)
VALUES
  ('Available Energy', 'AVAILABLE_ENERGY', 'Available energy charge'),
  ('Levy', 'LEVY', 'Government levy'),
  ('Withholding', 'WITHHOLDING', 'Withholding tax or VAT deduction')
ON CONFLICT (code) DO NOTHING;

-- ============================================================================
-- 1d. expected_invoice_header — versioning + idempotency
-- ============================================================================

ALTER TABLE expected_invoice_header
  ADD COLUMN IF NOT EXISTS version_no INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100),
  ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}';

-- One current invoice per (project, period, direction)
CREATE UNIQUE INDEX IF NOT EXISTS idx_expected_invoice_current
ON expected_invoice_header (project_id, billing_period_id, invoice_direction)
WHERE is_current = true;

-- Version history uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS idx_expected_invoice_version
ON expected_invoice_header (project_id, billing_period_id, invoice_direction, version_no);

-- Idempotency key uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS idx_expected_invoice_idempotency
ON expected_invoice_header (idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- ============================================================================
-- 1e. expected_invoice_line_item — tax audit + sign enforcement
-- ============================================================================

ALTER TABLE expected_invoice_line_item
  ADD COLUMN IF NOT EXISTS component_code VARCHAR(30),
  ADD COLUMN IF NOT EXISTS basis_amount DECIMAL,
  ADD COLUMN IF NOT EXISTS rate_pct DECIMAL,
  ADD COLUMN IF NOT EXISTS amount_sign SMALLINT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS contract_line_id BIGINT REFERENCES contract_line(id);

-- Sign enforcement: positive charges have sign=1, deductions have sign=-1
ALTER TABLE expected_invoice_line_item
  DROP CONSTRAINT IF EXISTS chk_line_amount_sign;

ALTER TABLE expected_invoice_line_item
  ADD CONSTRAINT chk_line_amount_sign CHECK (
    (amount_sign = 1 AND (line_total_amount IS NULL OR line_total_amount >= 0))
    OR (amount_sign = -1 AND (line_total_amount IS NULL OR line_total_amount <= 0))
  );

-- ============================================================================
-- 1f. billing_tax_rule with GiST exclusion constraint
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS billing_tax_rule (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT REFERENCES organization(id),
  country_code CHAR(2) NOT NULL,
  name VARCHAR(100) NOT NULL,
  effective_start_date DATE NOT NULL,
  effective_end_date DATE,
  rules JSONB NOT NULL,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Prevent overlapping active date ranges per org/country
-- Note: EXCLUDE constraint requires the table to not already have the constraint
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'billing_tax_rule_no_overlap'
  ) THEN
    ALTER TABLE billing_tax_rule
    ADD CONSTRAINT billing_tax_rule_no_overlap
    EXCLUDE USING gist (
      organization_id WITH =,
      country_code WITH =,
      daterange(effective_start_date, effective_end_date, '[]') WITH &&
    ) WHERE (is_active = true);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_billing_tax_rule_lookup
ON billing_tax_rule (organization_id, country_code, is_active)
WHERE is_active = true;

-- ============================================================================
-- RLS Policies for billing_tax_rule
-- ============================================================================

ALTER TABLE billing_tax_rule ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'billing_tax_rule' AND policyname = 'billing_tax_rule_org_read'
  ) THEN
    CREATE POLICY billing_tax_rule_org_read ON billing_tax_rule
      FOR SELECT
      USING (true);
  END IF;
END $$;

-- ============================================================================
-- 1g. invoice_header — add invoice_direction
-- ============================================================================

ALTER TABLE invoice_header
  ADD COLUMN IF NOT EXISTS invoice_direction invoice_direction;

-- ============================================================================
-- 1h. invoice_line_item — tax/component columns + sign constraint
-- ============================================================================

ALTER TABLE invoice_line_item
  ADD COLUMN IF NOT EXISTS component_code VARCHAR(30),
  ADD COLUMN IF NOT EXISTS basis_amount DECIMAL,
  ADD COLUMN IF NOT EXISTS rate_pct DECIMAL,
  ADD COLUMN IF NOT EXISTS amount_sign SMALLINT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS contract_line_id BIGINT REFERENCES contract_line(id);

ALTER TABLE invoice_line_item
  DROP CONSTRAINT IF EXISTS chk_invoice_line_amount_sign;

ALTER TABLE invoice_line_item
  ADD CONSTRAINT chk_invoice_line_amount_sign CHECK (
    (amount_sign = 1 AND (line_total_amount IS NULL OR line_total_amount >= 0))
    OR (amount_sign = -1 AND (line_total_amount IS NULL OR line_total_amount <= 0))
  );

-- ============================================================================
-- Fix fabricated tariff_group_key to match real CBE contract ID
-- ============================================================================
-- GH-MOH01-PPA-001 was hardcoded in reonboard script, not from CBE data.
-- Real contract ID: CONGHA00-2025-00005 (from CBE contract management).

UPDATE clause_tariff
SET tariff_group_key = REPLACE(tariff_group_key, 'GH-MOH01-PPA-001', 'CONGHA00-2025-00005')
WHERE tariff_group_key LIKE 'GH-MOH01-PPA-001%';

COMMIT;
