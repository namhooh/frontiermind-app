-- Migration: 003_add_contract_parsing_fields.sql
-- Description: Add contract parsing status tracking fields
-- Author: Phase 2 - Database Integration
-- Date: 2026-01-11

-- ==============================================================================
-- UP Migration
-- ==============================================================================

-- Add parsing status and metadata fields to contract table
ALTER TABLE contract ADD COLUMN IF NOT EXISTS parsing_status VARCHAR(50);
ALTER TABLE contract ADD COLUMN IF NOT EXISTS parsing_started_at TIMESTAMPTZ;
ALTER TABLE contract ADD COLUMN IF NOT EXISTS parsing_completed_at TIMESTAMPTZ;
ALTER TABLE contract ADD COLUMN IF NOT EXISTS parsing_error TEXT;
ALTER TABLE contract ADD COLUMN IF NOT EXISTS pii_detected_count INTEGER DEFAULT 0;
ALTER TABLE contract ADD COLUMN IF NOT EXISTS clauses_extracted_count INTEGER DEFAULT 0;
ALTER TABLE contract ADD COLUMN IF NOT EXISTS processing_time_seconds NUMERIC(10,2);

-- Add check constraint for parsing_status values
ALTER TABLE contract ADD CONSTRAINT contract_parsing_status_check
  CHECK (parsing_status IN ('pending', 'processing', 'completed', 'failed', NULL));

-- Add check constraints for counts
ALTER TABLE contract ADD CONSTRAINT contract_pii_detected_count_check
  CHECK (pii_detected_count >= 0);

ALTER TABLE contract ADD CONSTRAINT contract_clauses_extracted_count_check
  CHECK (clauses_extracted_count >= 0);

ALTER TABLE contract ADD CONSTRAINT contract_processing_time_check
  CHECK (processing_time_seconds >= 0);

-- Add indexes for querying by parsing status
CREATE INDEX idx_contract_parsing_status ON contract(parsing_status) WHERE parsing_status IS NOT NULL;
CREATE INDEX idx_contract_parsing_completed_at ON contract(parsing_completed_at) WHERE parsing_completed_at IS NOT NULL;

-- Add comments
COMMENT ON COLUMN contract.parsing_status IS
'Status of contract parsing pipeline: pending, processing, completed, failed.
NULL for contracts uploaded before parsing feature was implemented.';

COMMENT ON COLUMN contract.parsing_started_at IS
'Timestamp when contract parsing pipeline started (LlamaParse OCR initiated).';

COMMENT ON COLUMN contract.parsing_completed_at IS
'Timestamp when contract parsing pipeline completed successfully.';

COMMENT ON COLUMN contract.parsing_error IS
'Error message if parsing failed. Contains technical details for debugging.';

COMMENT ON COLUMN contract.pii_detected_count IS
'Number of PII entities detected by Presidio during parsing.
Matches pii_entities_count in contract_pii_mapping table.';

COMMENT ON COLUMN contract.clauses_extracted_count IS
'Number of clauses successfully extracted by Claude AI from the contract.
Matches the count of records in clause table for this contract.';

COMMENT ON COLUMN contract.processing_time_seconds IS
'Total time taken to parse the contract (in seconds), from document upload
through OCR, PII detection, anonymization, and clause extraction.';

-- Helper function: Update parsing status
CREATE OR REPLACE FUNCTION update_contract_parsing_status(
  p_contract_id BIGINT,
  p_status VARCHAR(50),
  p_error TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
  IF p_status = 'processing' THEN
    -- Mark as processing
    UPDATE contract
    SET
      parsing_status = p_status,
      parsing_started_at = NOW(),
      parsing_completed_at = NULL,
      parsing_error = NULL
    WHERE id = p_contract_id;

  ELSIF p_status = 'completed' THEN
    -- Mark as completed
    UPDATE contract
    SET
      parsing_status = p_status,
      parsing_completed_at = NOW(),
      parsing_error = NULL
    WHERE id = p_contract_id;

  ELSIF p_status = 'failed' THEN
    -- Mark as failed with error
    UPDATE contract
    SET
      parsing_status = p_status,
      parsing_completed_at = NOW(),
      parsing_error = p_error
    WHERE id = p_contract_id;

  ELSE
    RAISE EXCEPTION 'Invalid parsing status: %', p_status;
  END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION update_contract_parsing_status IS
'Helper function to update contract parsing status and timestamps.
Handles setting appropriate timestamps based on status transition.';

-- Helper function: Get parsing statistics
CREATE OR REPLACE FUNCTION get_parsing_statistics(
  p_days_back INTEGER DEFAULT 30
) RETURNS TABLE (
  total_contracts BIGINT,
  completed_contracts BIGINT,
  failed_contracts BIGINT,
  processing_contracts BIGINT,
  pending_contracts BIGINT,
  avg_processing_time NUMERIC,
  avg_pii_detected NUMERIC,
  avg_clauses_extracted NUMERIC
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    COUNT(*)::BIGINT AS total_contracts,
    COUNT(*) FILTER (WHERE parsing_status = 'completed')::BIGINT AS completed_contracts,
    COUNT(*) FILTER (WHERE parsing_status = 'failed')::BIGINT AS failed_contracts,
    COUNT(*) FILTER (WHERE parsing_status = 'processing')::BIGINT AS processing_contracts,
    COUNT(*) FILTER (WHERE parsing_status = 'pending')::BIGINT AS pending_contracts,
    AVG(processing_time_seconds) FILTER (WHERE parsing_status = 'completed') AS avg_processing_time,
    AVG(pii_detected_count) FILTER (WHERE parsing_status = 'completed') AS avg_pii_detected,
    AVG(clauses_extracted_count) FILTER (WHERE parsing_status = 'completed') AS avg_clauses_extracted
  FROM contract
  WHERE parsing_started_at >= NOW() - (p_days_back || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_parsing_statistics IS
'Returns aggregate statistics about contract parsing for the last N days.
Useful for monitoring parsing pipeline health and performance.';

-- ==============================================================================
-- DOWN Migration
-- ==============================================================================

-- Drop helper functions
DROP FUNCTION IF EXISTS get_parsing_statistics(INTEGER);
DROP FUNCTION IF EXISTS update_contract_parsing_status(BIGINT, VARCHAR, TEXT);

-- Drop indexes
DROP INDEX IF EXISTS idx_contract_parsing_completed_at;
DROP INDEX IF EXISTS idx_contract_parsing_status;

-- Drop constraints
ALTER TABLE contract DROP CONSTRAINT IF EXISTS contract_processing_time_check;
ALTER TABLE contract DROP CONSTRAINT IF EXISTS contract_clauses_extracted_count_check;
ALTER TABLE contract DROP CONSTRAINT IF EXISTS contract_pii_detected_count_check;
ALTER TABLE contract DROP CONSTRAINT IF EXISTS contract_parsing_status_check;

-- Drop columns
ALTER TABLE contract DROP COLUMN IF EXISTS processing_time_seconds;
ALTER TABLE contract DROP COLUMN IF EXISTS clauses_extracted_count;
ALTER TABLE contract DROP COLUMN IF EXISTS pii_detected_count;
ALTER TABLE contract DROP COLUMN IF EXISTS parsing_error;
ALTER TABLE contract DROP COLUMN IF EXISTS parsing_completed_at;
ALTER TABLE contract DROP COLUMN IF EXISTS parsing_started_at;
ALTER TABLE contract DROP COLUMN IF EXISTS parsing_status;
