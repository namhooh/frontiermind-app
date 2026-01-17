-- =====================================================
-- MIGRATION 006: Meter Reading V2 - Partitioned Lake-House Schema
-- =====================================================
-- Implements the canonical meter data model from DATA_INGESTION_ARCHITECTURE.md
--
-- BREAKING CHANGE: Drops old meter_reading table (no existing data)
--
-- Changes:
-- 1. New partitioned table with monthly RANGE partitioning
-- 2. Split single 'value' column into energy_wh, power_w, irradiance_wm2, temperature_c
-- 3. Add source_system, reading_interval_seconds, quality, other_metrics
-- 4. Add organization_id for multi-tenant support
-- 5. Create partitions for current + 3 future months
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Drop old meter_reading table
-- =====================================================
-- NOTE: Only safe because there is no existing data
-- If data exists, use a migration strategy instead

DROP TABLE IF EXISTS meter_reading CASCADE;

-- =====================================================
-- Step 2: Create partitioned meter_reading table
-- =====================================================
-- Canonical data model per DATA_INGESTION_ARCHITECTURE.md

CREATE TABLE meter_reading (
    id BIGSERIAL,
    organization_id BIGINT NOT NULL REFERENCES organization(id),
    project_id BIGINT REFERENCES project(id),
    meter_id BIGINT REFERENCES meter(id),

    -- Source tracking
    source_system VARCHAR(50) NOT NULL,  -- 'solaredge', 'enphase', 'sma', 'goodwe', 'snowflake', 'manual'
    external_site_id VARCHAR(255),       -- Site ID in source system
    external_device_id VARCHAR(255),     -- Device/meter ID in source system

    -- Timestamp and interval
    reading_timestamp TIMESTAMPTZ NOT NULL,
    reading_interval updated_frequency NOT NULL DEFAULT '15min',  -- Uses updated_frequency enum

    -- Metrics (nullable - not all sources provide all metrics)
    energy_wh DECIMAL,                   -- Energy in Watt-hours
    power_w DECIMAL,                     -- Power in Watts
    irradiance_wm2 DECIMAL,              -- Solar irradiance in W/m2
    temperature_c DECIMAL,               -- Temperature in Celsius
    other_metrics JSONB,                 -- Additional metrics as needed

    -- Data quality
    quality VARCHAR(20) NOT NULL DEFAULT 'measured',  -- 'measured', 'estimated', 'missing'

    -- Audit
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Composite primary key required for partitioning
    PRIMARY KEY (id, reading_timestamp)
) PARTITION BY RANGE (reading_timestamp);

-- =====================================================
-- Step 3: Create partitions
-- =====================================================
-- Create partitions for current month + 3 future months
-- Naming convention: meter_reading_YYYY_MM

CREATE TABLE meter_reading_2026_01 PARTITION OF meter_reading
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE meter_reading_2026_02 PARTITION OF meter_reading
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

CREATE TABLE meter_reading_2026_03 PARTITION OF meter_reading
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE TABLE meter_reading_2026_04 PARTITION OF meter_reading
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- =====================================================
-- Step 4: Create indexes
-- =====================================================
-- Indexes are created on parent table and inherited by partitions

CREATE INDEX idx_meter_reading_org ON meter_reading(organization_id);
CREATE INDEX idx_meter_reading_project ON meter_reading(project_id);
CREATE INDEX idx_meter_reading_meter ON meter_reading(meter_id);
CREATE INDEX idx_meter_reading_source ON meter_reading(source_system);
CREATE INDEX idx_meter_reading_timestamp ON meter_reading(reading_timestamp);
CREATE INDEX idx_meter_reading_external_site ON meter_reading(external_site_id);

-- Composite index for common query patterns
CREATE INDEX idx_meter_reading_org_project_ts ON meter_reading(organization_id, project_id, reading_timestamp);

-- =====================================================
-- Step 5: Add constraints
-- =====================================================

-- Quality must be one of the allowed values
ALTER TABLE meter_reading ADD CONSTRAINT chk_meter_reading_quality
    CHECK (quality IN ('measured', 'estimated', 'missing'));

-- Source system must be one of the allowed values
ALTER TABLE meter_reading ADD CONSTRAINT chk_meter_reading_source
    CHECK (source_system IN ('solaredge', 'enphase', 'sma', 'goodwe', 'snowflake', 'manual'));

-- Note: reading_interval uses updated_frequency enum for validation (no CHECK needed)

-- =====================================================
-- Step 6: Add comments
-- =====================================================

COMMENT ON TABLE meter_reading IS 'Raw meter readings from multiple sources. Partitioned by month with 90-day retention policy.';
COMMENT ON COLUMN meter_reading.source_system IS 'Origin of data: solaredge, enphase, sma, goodwe, snowflake, manual';
COMMENT ON COLUMN meter_reading.external_site_id IS 'Site identifier in the source system (e.g., SolarEdge site ID)';
COMMENT ON COLUMN meter_reading.external_device_id IS 'Device/meter identifier in the source system';
COMMENT ON COLUMN meter_reading.reading_interval IS 'Interval between readings using updated_frequency enum: daily, hourly, 15min, min, sec, millisec';
COMMENT ON COLUMN meter_reading.energy_wh IS 'Energy production/consumption in Watt-hours';
COMMENT ON COLUMN meter_reading.power_w IS 'Instantaneous power in Watts';
COMMENT ON COLUMN meter_reading.irradiance_wm2 IS 'Solar irradiance in Watts per square meter';
COMMENT ON COLUMN meter_reading.temperature_c IS 'Temperature in Celsius (ambient or module)';
COMMENT ON COLUMN meter_reading.other_metrics IS 'Additional metrics as JSONB (e.g., voltage, current, frequency)';
COMMENT ON COLUMN meter_reading.quality IS 'Data quality flag: measured (actual reading), estimated (interpolated), missing (placeholder)';
COMMENT ON COLUMN meter_reading.ingested_at IS 'When the reading was ingested into the system';

-- =====================================================
-- Step 7: Create helper function for partition management
-- =====================================================

CREATE OR REPLACE FUNCTION create_meter_reading_partition(
    partition_date DATE
) RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    partition_name := 'meter_reading_' || TO_CHAR(partition_date, 'YYYY_MM');
    start_date := DATE_TRUNC('month', partition_date);
    end_date := start_date + INTERVAL '1 month';

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF meter_reading FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        start_date,
        end_date
    );

    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_meter_reading_partition IS 'Creates a new monthly partition for meter_reading table. Call with first day of desired month.';

-- =====================================================
-- Step 8: Automatic Partition Management via pg_cron
-- =====================================================
-- Creates new partitions automatically each month
-- Runs on 1st of every month at midnight UTC
-- Creates partition for 3 months ahead to ensure data always has a home

-- Enable pg_cron extension (Supabase has this available)
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Schedule monthly job to create future partitions
-- Job runs at midnight UTC on the 1st of each month
SELECT cron.schedule(
    'meter-reading-partition-maintenance',  -- Job name (unique identifier)
    '0 0 1 * *',                            -- Cron: midnight UTC on 1st of each month
    $$
    SELECT create_meter_reading_partition(
        (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '3 months')::DATE
    );
    $$
);

-- Grant necessary permissions for cron job execution
GRANT USAGE ON SCHEMA cron TO postgres;

COMMENT ON EXTENSION pg_cron IS 'Scheduled job for automatic meter_reading partition creation';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
    partition_count INTEGER;
    cron_job_count INTEGER;
BEGIN
    -- Count partitions
    SELECT COUNT(*) INTO partition_count
    FROM pg_inherits
    WHERE inhparent = 'meter_reading'::regclass;

    IF partition_count >= 4 THEN
        RAISE NOTICE 'Migration successful: meter_reading created with % partitions', partition_count;
    ELSE
        RAISE WARNING 'Expected at least 4 partitions, found %', partition_count;
    END IF;

    -- Check pg_cron job
    SELECT COUNT(*) INTO cron_job_count
    FROM cron.job
    WHERE jobname = 'meter-reading-partition-maintenance';

    IF cron_job_count = 1 THEN
        RAISE NOTICE 'pg_cron job scheduled successfully';
    ELSE
        RAISE WARNING 'pg_cron job not found - automatic partition creation will not work';
    END IF;
END $$;

COMMIT;

-- Display table structure
SELECT 'meter_reading table structure:' AS info;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'meter_reading'
ORDER BY ordinal_position;

-- Display partitions
SELECT 'Partitions:' AS info;
SELECT c.relname AS partition_name
FROM pg_inherits i
JOIN pg_class c ON i.inhrelid = c.oid
WHERE i.inhparent = 'meter_reading'::regclass
ORDER BY c.relname;

-- Display pg_cron job
SELECT 'Scheduled pg_cron job:' AS info;
SELECT jobid, jobname, schedule, command
FROM cron.job
WHERE jobname = 'meter-reading-partition-maintenance';
