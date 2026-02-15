-- Migration 026: Billing Aggregate Dedup Index
-- Version: 6.3
-- Date: 2026-02-11
-- Description: Business-key unique index on meter_aggregate for billing dedup.
--
-- The billing aggregate pipeline inserts monthly rows via ON CONFLICT DO NOTHING.
-- Without a unique index, duplicates are never detected (PK is auto-increment id).
--
-- This partial index covers monthly billing aggregates only.
-- COALESCE handles NULL FKs (from the "Load with NULLs + warn" strategy
-- where unresolved tariffs/periods are set to NULL).

CREATE UNIQUE INDEX IF NOT EXISTS idx_meter_aggregate_billing_dedup
ON meter_aggregate (
    organization_id,
    COALESCE(billing_period_id, -1),
    COALESCE(clause_tariff_id, -1)
)
WHERE period_type = 'monthly';

COMMENT ON INDEX idx_meter_aggregate_billing_dedup IS
    'Dedup index for monthly billing aggregates. Prevents duplicate rows per org + billing period + tariff line.';
