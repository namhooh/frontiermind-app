-- Migration 060: tariff_rate schema cleanup
-- 1. Add billing_period_id FK (aligns with 6 other tables)
-- 2. Drop always-NULL fx_rate_hard_id column
-- 3. Rename fx_rate_local_id → exchange_rate_id

BEGIN;

-- ── Part A: Add billing_period_id FK ──────────────────────────────

ALTER TABLE tariff_rate
  ADD COLUMN IF NOT EXISTS billing_period_id BIGINT REFERENCES billing_period(id);

-- Backfill monthly rows from existing billing_month
UPDATE tariff_rate tr
SET billing_period_id = bp.id
FROM billing_period bp
WHERE tr.rate_granularity = 'monthly'
  AND tr.billing_month IS NOT NULL
  AND tr.billing_period_id IS NULL
  AND bp.start_date = tr.billing_month;

CREATE INDEX IF NOT EXISTS idx_tariff_rate_billing_period
  ON tariff_rate(billing_period_id) WHERE billing_period_id IS NOT NULL;

COMMENT ON COLUMN tariff_rate.billing_period_id IS
  'FK to billing_period for monthly rows. NULL for annual rows.';

-- ── Part B: Merge fx_rate columns ─────────────────────────────────

-- Drop the always-NULL column
ALTER TABLE tariff_rate DROP COLUMN IF EXISTS fx_rate_hard_id;

-- Rename surviving column
ALTER TABLE tariff_rate RENAME COLUMN fx_rate_local_id TO exchange_rate_id;

COMMENT ON COLUMN tariff_rate.exchange_rate_id IS
  'FK to exchange_rate for local→USD conversion. NULL for USD-denominated or annual rows.';

COMMIT;
