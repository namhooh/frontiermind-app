-- Migration: 021_seed_billing_period
-- Description: Seed billing_period table with default entry for invoice/report workflow
-- Date: 2026-01-26

-- Insert default billing period with ID=1 if it doesn't exist
-- This is required for the invoice generation and report workflow
-- which uses billing_period_id: 1 as a hardcoded default

INSERT INTO billing_period (id, name, start_date, end_date)
VALUES (1, 'January 2026', '2026-01-01', '2026-01-31')
ON CONFLICT (id) DO NOTHING;

-- Reset sequence to avoid conflicts with future inserts
-- Using DO block for compatibility with Supabase SQL editor
DO $$
BEGIN
  PERFORM setval('billing_period_id_seq', GREATEST(1, (SELECT COALESCE(MAX(id), 0) FROM billing_period)));
END $$;

