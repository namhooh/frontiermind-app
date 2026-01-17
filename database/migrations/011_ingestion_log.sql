-- =====================================================
-- MIGRATION 011: Create Ingestion Log Table
-- =====================================================
-- Tracks all data ingestion attempts for audit trail and debugging
-- per DATA_INGESTION_ARCHITECTURE.md section 7.2
--
-- Records every file processed by the Validator Lambda:
-- - Source file information (path, size, format)
-- - Processing results (rows processed, loaded, errors)
-- - Timing information (processing duration)
-- - Validation errors (for quarantined files)
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Create enum types
-- =====================================================

CREATE TYPE ingestion_status AS ENUM ('processing', 'success', 'quarantined', 'skipped', 'error');
CREATE TYPE ingestion_stage AS ENUM ('validating', 'transforming', 'loading', 'moving', 'complete');

-- =====================================================
-- Step 2: Create ingestion_log table
-- =====================================================

CREATE TABLE IF NOT EXISTS ingestion_log (
id BIGSERIAL PRIMARY KEY,
organization_id BIGINT REFERENCES organization(id),
integration_site_id BIGINT REFERENCES integration_site(id),

-- Source file information
data_source_id BIGINT NOT NULL REFERENCES data_source(id),
file_path VARCHAR(1024) NOT NULL,       -- S3 path: raw/solaredge/1/2026-01-16/site_abc_140000.json
file_name VARCHAR(255),                 -- Just the filename
file_size_bytes BIGINT,
file_format VARCHAR(50),                -- 'json', 'csv', 'parquet'
file_hash VARCHAR(64),                  -- SHA256 hash of file for deduplication

-- Processing status
ingestion_status ingestion_status NOT NULL DEFAULT 'processing',
ingestion_stage ingestion_stage,

-- Processing results
rows_in_file INTEGER,                   -- Total rows found in file
rows_valid INTEGER,                     -- Rows that passed validation
rows_loaded INTEGER,                    -- Rows successfully inserted
rows_skipped INTEGER,                   -- Rows skipped (duplicates, etc.)
rows_failed INTEGER,                    -- Rows that failed to load

-- Data range (for meter readings)
data_start_timestamp TIMESTAMPTZ,       -- Earliest reading timestamp
data_end_timestamp TIMESTAMPTZ,         -- Latest reading timestamp

-- Validation errors (for quarantined files)
validation_errors JSONB,                -- Array of {field, error, sample_value}
error_message TEXT,                     -- Top-level error message

-- Performance metrics
processing_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
processing_completed_at TIMESTAMPTZ,
processing_time_ms INTEGER,             -- Total processing time

-- File movement
destination_path VARCHAR(1024),         -- validated/ or quarantine/ path

-- Audit
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

-- Constraints
CONSTRAINT chk_ingestion_log_format
    CHECK (file_format IS NULL OR file_format IN ('json', 'csv', 'parquet', 'xlsx'))
);

-- =====================================================
-- Step 3: Create indexes
-- =====================================================

CREATE INDEX idx_ingestion_log_org ON ingestion_log(organization_id);
CREATE INDEX idx_ingestion_log_site ON ingestion_log(integration_site_id);
CREATE INDEX idx_ingestion_log_source ON ingestion_log(data_source_id);
CREATE INDEX idx_ingestion_log_status ON ingestion_log(ingestion_status);
CREATE INDEX idx_ingestion_log_created ON ingestion_log(created_at);
CREATE INDEX idx_ingestion_log_file_hash ON ingestion_log(file_hash);

-- Composite index for common query patterns
CREATE INDEX idx_ingestion_log_org_date ON ingestion_log(organization_id, created_at DESC);

-- =====================================================
-- Step 4: Enable Row Level Security
-- =====================================================

ALTER TABLE ingestion_log ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see logs for their organization
CREATE POLICY ingestion_log_org_policy ON ingestion_log
FOR SELECT
USING (
    organization_id IS NULL  -- System-level logs visible to all
    OR organization_id IN (
        SELECT organization_id FROM role
        WHERE user_id = auth.uid()
    )
);

-- Service role can access all (for Validator Lambda)
CREATE POLICY ingestion_log_service_policy ON ingestion_log
FOR ALL
USING (auth.role() = 'service_role');

-- =====================================================
-- Step 5: Add comments
-- =====================================================

COMMENT ON TABLE ingestion_log IS 'Audit trail for all data ingestion attempts from S3 Validator Lambda';
COMMENT ON COLUMN ingestion_log.data_source_id IS 'FK to data_source table for integration type';
COMMENT ON COLUMN ingestion_log.file_path IS 'Full S3 path of source file';
COMMENT ON COLUMN ingestion_log.file_hash IS 'SHA256 hash for deduplication and integrity';
COMMENT ON COLUMN ingestion_log.ingestion_status IS 'Processing result: success (loaded), quarantined (validation failed), skipped (duplicate)';
COMMENT ON COLUMN ingestion_log.ingestion_stage IS 'Processing stage where status was set';
COMMENT ON COLUMN ingestion_log.rows_loaded IS 'Number of rows successfully inserted into meter_reading';
COMMENT ON COLUMN ingestion_log.validation_errors IS 'Array of validation errors: [{field, error, sample_value}]';
COMMENT ON COLUMN ingestion_log.destination_path IS 'Where file was moved: validated/ or quarantine/';

-- =====================================================
-- Step 6: Create helper functions
-- =====================================================

-- Function to start ingestion log
CREATE OR REPLACE FUNCTION start_ingestion_log(
p_organization_id BIGINT,
p_data_source_id BIGINT,
p_file_path VARCHAR(1024),
p_file_size BIGINT DEFAULT NULL,
p_file_format VARCHAR(50) DEFAULT NULL,
p_file_hash VARCHAR(64) DEFAULT NULL,
p_site_id BIGINT DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE
v_log_id BIGINT;
BEGIN
INSERT INTO ingestion_log (
    organization_id,
    integration_site_id,
    data_source_id,
    file_path,
    file_name,
    file_size_bytes,
    file_format,
    file_hash,
    ingestion_status,
    ingestion_stage
) VALUES (
    p_organization_id,
    p_site_id,
    p_data_source_id,
    p_file_path,
    REGEXP_REPLACE(p_file_path, '.*/([^/]+)$', '\1'),  -- Extract filename
    p_file_size,
    p_file_format,
    p_file_hash,
    'processing',
    'validating'
)
RETURNING id INTO v_log_id;

RETURN v_log_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to complete ingestion log with success
CREATE OR REPLACE FUNCTION complete_ingestion_log_success(
p_log_id BIGINT,
p_rows_loaded INTEGER,
p_rows_skipped INTEGER DEFAULT 0,
p_data_start TIMESTAMPTZ DEFAULT NULL,
p_data_end TIMESTAMPTZ DEFAULT NULL,
p_destination_path VARCHAR(1024) DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
UPDATE ingestion_log
SET
    ingestion_status = 'success',
    ingestion_stage = 'complete',
    rows_loaded = p_rows_loaded,
    rows_skipped = p_rows_skipped,
    rows_valid = p_rows_loaded + p_rows_skipped,
    data_start_timestamp = p_data_start,
    data_end_timestamp = p_data_end,
    destination_path = p_destination_path,
    processing_completed_at = NOW(),
    processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
WHERE id = p_log_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to complete ingestion log with quarantine
CREATE OR REPLACE FUNCTION complete_ingestion_log_quarantine(
p_log_id BIGINT,
p_validation_errors JSONB,
p_error_message TEXT DEFAULT NULL,
p_destination_path VARCHAR(1024) DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
UPDATE ingestion_log
SET
    ingestion_status = 'quarantined',
    ingestion_stage = 'validating',
    validation_errors = p_validation_errors,
    error_message = p_error_message,
    destination_path = p_destination_path,
    processing_completed_at = NOW(),
    processing_time_ms = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER * 1000
WHERE id = p_log_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get ingestion statistics
CREATE OR REPLACE FUNCTION get_ingestion_stats(
p_organization_id BIGINT,
p_days INTEGER DEFAULT 7
) RETURNS TABLE (
date DATE,
files_processed BIGINT,
files_success BIGINT,
files_quarantined BIGINT,
rows_loaded BIGINT,
avg_processing_ms NUMERIC
) AS $$
BEGIN
RETURN QUERY
SELECT
    DATE(created_at) AS date,
    COUNT(*) AS files_processed,
    COUNT(*) FILTER (WHERE ingestion_status = 'success') AS files_success,
    COUNT(*) FILTER (WHERE ingestion_status = 'quarantined') AS files_quarantined,
    COALESCE(SUM(ingestion_log.rows_loaded), 0) AS rows_loaded,
    ROUND(AVG(processing_time_ms), 0) AS avg_processing_ms
FROM ingestion_log
WHERE (p_organization_id IS NULL OR organization_id = p_organization_id)
    AND created_at >= NOW() - (p_days || ' days')::INTERVAL
GROUP BY DATE(created_at)
ORDER BY date DESC;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

COMMENT ON FUNCTION start_ingestion_log IS 'Creates a new ingestion log entry when file processing begins';
COMMENT ON FUNCTION complete_ingestion_log_success IS 'Marks ingestion as successful with row counts';
COMMENT ON FUNCTION complete_ingestion_log_quarantine IS 'Marks ingestion as quarantined with validation errors';
COMMENT ON FUNCTION get_ingestion_stats IS 'Returns daily ingestion statistics for monitoring';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
table_exists BOOLEAN;
BEGIN
SELECT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_name = 'ingestion_log'
) INTO table_exists;

IF table_exists THEN
    RAISE NOTICE 'Migration successful: ingestion_log table created';
ELSE
    RAISE WARNING 'Migration failed: ingestion_log table not found';
END IF;
END $$;

COMMIT;

-- Display table structure
SELECT 'ingestion_log table structure:' AS info;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'ingestion_log'
ORDER BY ordinal_position;
