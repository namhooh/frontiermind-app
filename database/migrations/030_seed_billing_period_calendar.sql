-- Migration: 030_seed_billing_period_calendar
-- Description: Seed billing_period with a full calendar (Jan 2024 - Dec 2027)
-- Date: 2026-02-15
--
-- Context: Only one billing period was seeded (migration 021, January 2026).
-- This caused NULL FK for any other month's data, which then collapsed
-- distinct months into one row via the COALESCE(-1) dedup index (migration 026).
-- Seeding 48 months covers historical CBE data (2024), current operations
-- (2025-2026), and near-future forecast periods (2027).

-- Step 1: Add UNIQUE constraint on (start_date, end_date) for idempotency
-- No existing duplicates since only one row exists
ALTER TABLE billing_period
  ADD CONSTRAINT uq_billing_period_dates UNIQUE (start_date, end_date);

-- Step 2: Seed 48 months (Jan 2024 - Dec 2027)
-- Uses ON CONFLICT to skip the existing Jan 2026 row (preserves ID=1)
INSERT INTO billing_period (name, start_date, end_date)
VALUES
  -- 2024
  ('January 2024',   '2024-01-01', '2024-01-31'),
  ('February 2024',  '2024-02-01', '2024-02-29'),
  ('March 2024',     '2024-03-01', '2024-03-31'),
  ('April 2024',     '2024-04-01', '2024-04-30'),
  ('May 2024',       '2024-05-01', '2024-05-31'),
  ('June 2024',      '2024-06-01', '2024-06-30'),
  ('July 2024',      '2024-07-01', '2024-07-31'),
  ('August 2024',    '2024-08-01', '2024-08-31'),
  ('September 2024', '2024-09-01', '2024-09-30'),
  ('October 2024',   '2024-10-01', '2024-10-31'),
  ('November 2024',  '2024-11-01', '2024-11-30'),
  ('December 2024',  '2024-12-01', '2024-12-31'),
  -- 2025
  ('January 2025',   '2025-01-01', '2025-01-31'),
  ('February 2025',  '2025-02-01', '2025-02-28'),
  ('March 2025',     '2025-03-01', '2025-03-31'),
  ('April 2025',     '2025-04-01', '2025-04-30'),
  ('May 2025',       '2025-05-01', '2025-05-31'),
  ('June 2025',      '2025-06-01', '2025-06-30'),
  ('July 2025',      '2025-07-01', '2025-07-31'),
  ('August 2025',    '2025-08-01', '2025-08-31'),
  ('September 2025', '2025-09-01', '2025-09-30'),
  ('October 2025',   '2025-10-01', '2025-10-31'),
  ('November 2025',  '2025-11-01', '2025-11-30'),
  ('December 2025',  '2025-12-01', '2025-12-31'),
  -- 2026
  ('January 2026',   '2026-01-01', '2026-01-31'),
  ('February 2026',  '2026-02-01', '2026-02-28'),
  ('March 2026',     '2026-03-01', '2026-03-31'),
  ('April 2026',     '2026-04-01', '2026-04-30'),
  ('May 2026',       '2026-05-01', '2026-05-31'),
  ('June 2026',      '2026-06-01', '2026-06-30'),
  ('July 2026',      '2026-07-01', '2026-07-31'),
  ('August 2026',    '2026-08-01', '2026-08-31'),
  ('September 2026', '2026-09-01', '2026-09-30'),
  ('October 2026',   '2026-10-01', '2026-10-31'),
  ('November 2026',  '2026-11-01', '2026-11-30'),
  ('December 2026',  '2026-12-01', '2026-12-31'),
  -- 2027
  ('January 2027',   '2027-01-01', '2027-01-31'),
  ('February 2027',  '2027-02-01', '2027-02-28'),
  ('March 2027',     '2027-03-01', '2027-03-31'),
  ('April 2027',     '2027-04-01', '2027-04-30'),
  ('May 2027',       '2027-05-01', '2027-05-31'),
  ('June 2027',      '2027-06-01', '2027-06-30'),
  ('July 2027',      '2027-07-01', '2027-07-31'),
  ('August 2027',    '2027-08-01', '2027-08-31'),
  ('September 2027', '2027-09-01', '2027-09-30'),
  ('October 2027',   '2027-10-01', '2027-10-31'),
  ('November 2027',  '2027-11-01', '2027-11-30'),
  ('December 2027',  '2027-12-01', '2027-12-31')
ON CONFLICT (start_date, end_date) DO NOTHING;

-- Step 3: Reset sequence to avoid ID conflicts with future inserts
DO $$
BEGIN
  PERFORM setval('billing_period_id_seq', (SELECT COALESCE(MAX(id), 0) FROM billing_period));
END $$;
