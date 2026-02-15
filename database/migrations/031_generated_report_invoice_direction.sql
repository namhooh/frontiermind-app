-- Migration: 031_generated_report_invoice_direction
-- Description: Add invoice_direction column to generated_report for report pipeline filtering
-- Date: 2026-02-15
--
-- Context: The invoice_direction enum (migration 022) and the repository methods
-- already support filtering by direction, but the report generation pipeline
-- never persisted this parameter. The background task reconstructs config from
-- the generated_report row, so the direction must be stored there.
-- NULL means "all directions" (backward compatible with existing reports).

ALTER TABLE generated_report
  ADD COLUMN IF NOT EXISTS invoice_direction invoice_direction;

COMMENT ON COLUMN generated_report.invoice_direction IS
  'Optional invoice direction filter (receivable/payable). NULL = all directions.';
