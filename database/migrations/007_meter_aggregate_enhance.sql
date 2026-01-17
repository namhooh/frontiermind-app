-- =====================================================
-- MIGRATION 007: Enhance Meter Aggregate Table
-- =====================================================
-- Adds new columns for lake-house architecture per DATA_INGESTION_ARCHITECTURE.md
--
-- Changes:
-- 1. Add period_type enum ('hourly', 'daily', 'monthly')
-- 2. Add period_start, period_end timestamps
-- 3. Add energy_wh, energy_kwh for standardized energy values
-- 4. Add availability metrics (hours_available, hours_expected, availability_percent)
-- 5. Add data quality metrics (reading_count, data_completeness_percent)
-- 6. Add organization_id for multi-tenant support
-- 7. Add source tracking fields
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Add organization_id column
-- =====================================================

ALTER TABLE meter_aggregate
    ADD COLUMN IF NOT EXISTS organization_id BIGINT REFERENCES organization(id);

-- =====================================================
-- Step 2: Add period_type and time range columns
-- =====================================================

ALTER TABLE meter_aggregate
    ADD COLUMN IF NOT EXISTS period_type VARCHAR(20) DEFAULT 'monthly',
    ADD COLUMN IF NOT EXISTS period_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS period_end TIMESTAMPTZ;

-- Add constraint for period_type
ALTER TABLE meter_aggregate
    ADD CONSTRAINT chk_meter_aggregate_period_type
    CHECK (period_type IN ('hourly', 'daily', 'monthly'));

-- =====================================================
-- Step 3: Add standardized energy columns
-- =====================================================

ALTER TABLE meter_aggregate
    ADD COLUMN IF NOT EXISTS energy_wh DECIMAL,
    ADD COLUMN IF NOT EXISTS energy_kwh DECIMAL;

-- =====================================================
-- Step 4: Add availability metrics
-- =====================================================

ALTER TABLE meter_aggregate
    ADD COLUMN IF NOT EXISTS hours_available DECIMAL,
    ADD COLUMN IF NOT EXISTS hours_expected DECIMAL,
    ADD COLUMN IF NOT EXISTS availability_percent DECIMAL(5,2);

-- =====================================================
-- Step 5: Add data quality metrics
-- =====================================================

ALTER TABLE meter_aggregate
    ADD COLUMN IF NOT EXISTS reading_count INTEGER,
    ADD COLUMN IF NOT EXISTS data_completeness_percent DECIMAL(5,2);

-- =====================================================
-- Step 6: Add source tracking
-- =====================================================

ALTER TABLE meter_aggregate
    ADD COLUMN IF NOT EXISTS source_system VARCHAR(50),
    ADD COLUMN IF NOT EXISTS aggregated_at TIMESTAMPTZ DEFAULT NOW();

-- =====================================================
-- Step 7: Backfill period_start/period_end from billing_period
-- =====================================================

UPDATE meter_aggregate ma
SET
    period_start = bp.start_date::timestamptz,
    period_end = (bp.end_date + INTERVAL '1 day')::timestamptz,
    energy_wh = COALESCE(total_production * 1000, 0),
    energy_kwh = total_production,
    period_type = 'monthly'
FROM billing_period bp
WHERE ma.billing_period_id = bp.id
    AND ma.period_start IS NULL;

-- =====================================================
-- Step 8: Add indexes for new columns
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_meter_aggregate_org ON meter_aggregate(organization_id);
CREATE INDEX IF NOT EXISTS idx_meter_aggregate_period ON meter_aggregate(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_meter_aggregate_type ON meter_aggregate(period_type);

-- =====================================================
-- Step 9: Add comments
-- =====================================================

COMMENT ON COLUMN meter_aggregate.organization_id IS 'Organization that owns this aggregate data';
COMMENT ON COLUMN meter_aggregate.period_type IS 'Aggregation period: hourly, daily, or monthly';
COMMENT ON COLUMN meter_aggregate.period_start IS 'Start of aggregation period (inclusive)';
COMMENT ON COLUMN meter_aggregate.period_end IS 'End of aggregation period (exclusive)';
COMMENT ON COLUMN meter_aggregate.energy_wh IS 'Total energy in Watt-hours';
COMMENT ON COLUMN meter_aggregate.energy_kwh IS 'Total energy in kilowatt-hours';
COMMENT ON COLUMN meter_aggregate.hours_available IS 'Hours the system was available/producing';
COMMENT ON COLUMN meter_aggregate.hours_expected IS 'Hours the system was expected to be available';
COMMENT ON COLUMN meter_aggregate.availability_percent IS 'Calculated availability: (hours_available / hours_expected) * 100';
COMMENT ON COLUMN meter_aggregate.reading_count IS 'Number of raw readings that contributed to this aggregate';
COMMENT ON COLUMN meter_aggregate.data_completeness_percent IS 'Percentage of expected readings that were actual (vs estimated/missing)';
COMMENT ON COLUMN meter_aggregate.source_system IS 'Primary source of aggregated data';
COMMENT ON COLUMN meter_aggregate.aggregated_at IS 'When this aggregate was calculated';

-- =====================================================
-- Step 10: Create helper function for calculating availability
-- =====================================================

CREATE OR REPLACE FUNCTION calculate_availability_percent(
    p_hours_available DECIMAL,
    p_hours_expected DECIMAL
) RETURNS DECIMAL(5,2) AS $$
BEGIN
    IF p_hours_expected IS NULL OR p_hours_expected = 0 THEN
        RETURN NULL;
    END IF;
    RETURN ROUND((p_hours_available / p_hours_expected) * 100, 2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_availability_percent IS 'Calculates availability percentage from hours available and expected';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
    col_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'meter_aggregate'
      AND column_name IN ('period_type', 'period_start', 'period_end', 'availability_percent', 'data_completeness_percent');

    IF col_count >= 5 THEN
        RAISE NOTICE 'Migration successful: meter_aggregate enhanced with % new columns', col_count;
    ELSE
        RAISE WARNING 'Expected 5 new columns, found %', col_count;
    END IF;
END $$;

COMMIT;

-- Display updated table structure
SELECT 'meter_aggregate new columns:' AS info;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'meter_aggregate'
  AND column_name IN ('organization_id', 'period_type', 'period_start', 'period_end',
                      'energy_wh', 'energy_kwh', 'hours_available', 'hours_expected',
                      'availability_percent', 'reading_count', 'data_completeness_percent',
                      'source_system', 'aggregated_at')
ORDER BY ordinal_position;
