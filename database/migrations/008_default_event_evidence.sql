-- =====================================================
-- MIGRATION 008: Add Evidence JSONB to Default Event
-- =====================================================
-- Preserves breach evidence after raw meter data is deleted (90-day retention)
-- per DATA_INGESTION_ARCHITECTURE.md section 9.3
--
-- Evidence structure:
-- {
--   "breach_period": { "start": "...", "end": "..." },
--   "meters_involved": [...],
--   "aggregate_values": { "expected": ..., "actual": ..., "shortfall": ..., "availability": ... },
--   "sample_readings": [...],  -- Minimal slice of raw data
--   "data_hash": "sha256...",  -- Hash of original data for integrity
--   "snapshot_s3_path": "s3://..."  -- Optional archived evidence file
-- }
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Add evidence column
-- =====================================================

ALTER TABLE default_event
    ADD COLUMN IF NOT EXISTS evidence JSONB;

-- =====================================================
-- Step 2: Add S3 path for archived evidence files
-- =====================================================

ALTER TABLE default_event
    ADD COLUMN IF NOT EXISTS evidence_archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS evidence_s3_path VARCHAR(1024);

-- =====================================================
-- Step 3: Add comments
-- =====================================================

COMMENT ON COLUMN default_event.evidence IS 'Preserved evidence for audit trail. Contains breach_period, meters_involved, aggregate_values, sample_readings, data_hash, snapshot_s3_path';
COMMENT ON COLUMN default_event.evidence_archived_at IS 'When evidence was archived to long-term storage (S3 Glacier)';
COMMENT ON COLUMN default_event.evidence_s3_path IS 'S3 path to archived evidence file (optional, for large evidence sets)';

-- =====================================================
-- Step 4: Create index for querying events with evidence
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_default_event_has_evidence
    ON default_event ((evidence IS NOT NULL));

-- =====================================================
-- Step 5: Create helper function to validate evidence structure
-- =====================================================

CREATE OR REPLACE FUNCTION validate_default_event_evidence(
    p_evidence JSONB
) RETURNS BOOLEAN AS $$
BEGIN
    -- Check for required top-level keys
    IF p_evidence IS NULL THEN
        RETURN TRUE;  -- NULL is valid (no evidence yet)
    END IF;

    -- Must have breach_period
    IF NOT (p_evidence ? 'breach_period') THEN
        RETURN FALSE;
    END IF;

    -- Must have aggregate_values
    IF NOT (p_evidence ? 'aggregate_values') THEN
        RETURN FALSE;
    END IF;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Add check constraint using the validation function
ALTER TABLE default_event
    ADD CONSTRAINT chk_default_event_evidence
    CHECK (validate_default_event_evidence(evidence));

COMMENT ON FUNCTION validate_default_event_evidence IS 'Validates that evidence JSONB has required structure (breach_period, aggregate_values)';

-- =====================================================
-- Step 6: Create function to preserve evidence when raw data is about to be deleted
-- =====================================================

CREATE OR REPLACE FUNCTION preserve_default_event_evidence(
    p_event_id BIGINT,
    p_breach_start TIMESTAMPTZ,
    p_breach_end TIMESTAMPTZ,
    p_meters BIGINT[],
    p_expected_value DECIMAL,
    p_actual_value DECIMAL,
    p_shortfall DECIMAL,
    p_availability DECIMAL,
    p_sample_readings JSONB DEFAULT NULL,
    p_data_hash VARCHAR DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE default_event
    SET evidence = jsonb_build_object(
        'breach_period', jsonb_build_object(
            'start', p_breach_start,
            'end', p_breach_end
        ),
        'meters_involved', to_jsonb(p_meters),
        'aggregate_values', jsonb_build_object(
            'expected', p_expected_value,
            'actual', p_actual_value,
            'shortfall', p_shortfall,
            'availability', p_availability
        ),
        'sample_readings', COALESCE(p_sample_readings, '[]'::jsonb),
        'data_hash', p_data_hash,
        'preserved_at', NOW()
    )
    WHERE id = p_event_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION preserve_default_event_evidence IS 'Preserves evidence for a default event before raw meter data is deleted';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
    col_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'default_event'
          AND column_name = 'evidence'
    ) INTO col_exists;

    IF col_exists THEN
        RAISE NOTICE 'Migration successful: evidence column added to default_event';
    ELSE
        RAISE WARNING 'Migration failed: evidence column not found';
    END IF;
END $$;

COMMIT;

-- Display updated table structure
SELECT 'default_event evidence columns:' AS info;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'default_event'
  AND column_name IN ('evidence', 'evidence_archived_at', 'evidence_s3_path')
ORDER BY ordinal_position;
