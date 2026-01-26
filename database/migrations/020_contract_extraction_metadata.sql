-- Migration: 020_contract_extraction_metadata.sql
-- Description: Add extraction_metadata column and seed contract_type lookup table
-- Date: 2026-01-26
--
-- Purpose:
-- Support AI-extracted contract metadata for enhanced contract processing:
-- 1. Store extraction metadata (party names, match confidence) in JSONB column
-- 2. Seed contract_type lookup table with standard energy contract types
--
-- Related: Contract Metadata Extraction feature
-- See: IMPLEMENTATION_GUIDE.md

-- =============================================================================
-- Part 1: Add extraction_metadata column to contract table
-- =============================================================================

-- Add JSONB column for storing AI extraction metadata
ALTER TABLE contract
    ADD COLUMN IF NOT EXISTS extraction_metadata JSONB;

-- Add comment for documentation
COMMENT ON COLUMN contract.extraction_metadata IS 'AI-extracted metadata: party names, match confidence, extraction timestamps, etc.';

-- Create GIN index for JSONB querying (e.g., finding contracts with unmatched counterparties)
CREATE INDEX IF NOT EXISTS idx_contract_extraction_metadata
    ON contract USING GIN (extraction_metadata);

-- =============================================================================
-- Part 2: Seed contract_type lookup table
-- =============================================================================

-- First, add unique constraint on code if it doesn't exist
-- This enables ON CONFLICT handling for idempotent inserts
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'contract_type_code_key'
    ) THEN
        ALTER TABLE contract_type ADD CONSTRAINT contract_type_code_key UNIQUE (code);
    END IF;
END $$;

-- Insert standard energy contract types
-- Using ON CONFLICT DO NOTHING to make migration idempotent
INSERT INTO contract_type (name, code, description) VALUES
    ('Power Purchase Agreement', 'PPA', 'Agreement for purchase of electricity from a generation facility'),
    ('Operations & Maintenance', 'O_M', 'Agreement for facility operations and maintenance services'),
    ('Engineering Procurement Construction', 'EPC', 'Agreement for facility design, procurement, and construction'),
    ('Lease Agreement', 'LEASE', 'Land or equipment lease agreement'),
    ('Interconnection Agreement', 'IA', 'Grid interconnection agreement with utility'),
    ('Energy Storage Agreement', 'ESA', 'Agreement for battery or other energy storage services'),
    ('Virtual Power Purchase Agreement', 'VPPA', 'Financial PPA where electricity is not physically delivered'),
    ('Tolling Agreement', 'TOLLING', 'Agreement where offtaker provides fuel and receives generated power'),
    ('Other', 'OTHER', 'Other contract type not classified above')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;

-- =============================================================================
-- Part 3: Helper function for extraction metadata queries
-- =============================================================================

-- Function to get contracts needing counterparty review
-- (where counterparty was extracted but not matched to existing record)
CREATE OR REPLACE FUNCTION get_contracts_needing_counterparty_review(
    p_limit INTEGER DEFAULT 100
)
RETURNS TABLE (
    contract_id INTEGER,
    contract_name VARCHAR,
    extracted_seller_name TEXT,
    extracted_buyer_name TEXT,
    match_confidence NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id AS contract_id,
        c.name AS contract_name,
        c.extraction_metadata->>'seller_name' AS extracted_seller_name,
        c.extraction_metadata->>'buyer_name' AS extracted_buyer_name,
        (c.extraction_metadata->>'counterparty_match_confidence')::NUMERIC AS match_confidence,
        c.created_at
    FROM contract c
    WHERE c.extraction_metadata IS NOT NULL
      AND (c.extraction_metadata->>'counterparty_matched')::BOOLEAN = FALSE
    ORDER BY c.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_contracts_needing_counterparty_review(INTEGER) IS
'Returns contracts where AI extracted counterparty names but could not match to existing records';

-- =============================================================================
-- Verification Queries (run manually to verify migration)
-- =============================================================================

-- Verify extraction_metadata column exists
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'contract' AND column_name = 'extraction_metadata';

-- Verify contract_type seeding
-- SELECT id, code, name, description FROM contract_type ORDER BY id;

-- Verify GIN index exists
-- SELECT indexname, indexdef FROM pg_indexes WHERE indexname = 'idx_contract_extraction_metadata';
