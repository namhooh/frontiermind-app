-- =============================================================================
-- Migration 037: GRP Ingestion — Monthly Observations & File Upload
-- =============================================================================
-- Extends reference_price for monthly granularity, extends submission_token
-- with project_id and submission_type for GRP upload workflow.
-- =============================================================================

BEGIN;

-- =========================================================================
-- A. Extend submission_token with project_id and submission_type
-- =========================================================================

ALTER TABLE submission_token
    ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES project(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS submission_type VARCHAR(30) NOT NULL DEFAULT 'form_response';

COMMENT ON COLUMN submission_token.project_id IS 'Project context for GRP and other project-scoped submissions.';
COMMENT ON COLUMN submission_token.submission_type IS 'Type of submission: form_response (default), grp_upload.';

-- CHECK constraints on submission_type
ALTER TABLE submission_token DROP CONSTRAINT IF EXISTS chk_submission_type;
ALTER TABLE submission_token ADD CONSTRAINT chk_submission_type
    CHECK (submission_type IN ('form_response', 'grp_upload'));

-- GRP uploads require a project context
ALTER TABLE submission_token DROP CONSTRAINT IF EXISTS chk_grp_requires_project;
ALTER TABLE submission_token ADD CONSTRAINT chk_grp_requires_project
    CHECK (submission_type != 'grp_upload' OR project_id IS NOT NULL);

-- =========================================================================
-- B. Extend reference_price for monthly granularity
-- =========================================================================

-- Add observation type and document tracking columns FIRST (before constraints that reference them)
ALTER TABLE reference_price
    ADD COLUMN IF NOT EXISTS observation_type VARCHAR(10) NOT NULL DEFAULT 'annual',
    ADD COLUMN IF NOT EXISTS source_document_path TEXT,
    ADD COLUMN IF NOT EXISTS source_document_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS submission_response_id BIGINT REFERENCES submission_response(id);

-- Change unique constraint: include observation_type so annual and monthly rows
-- don't collide when period_start coincides (e.g. annual year-start = monthly first-of-month)
ALTER TABLE reference_price DROP CONSTRAINT IF EXISTS reference_price_project_id_operating_year_key;
ALTER TABLE reference_price DROP CONSTRAINT IF EXISTS reference_price_project_period_key;
ALTER TABLE reference_price ADD CONSTRAINT reference_price_project_obs_period_key
    UNIQUE(project_id, observation_type, period_start);

-- CHECK constraint on observation_type
ALTER TABLE reference_price DROP CONSTRAINT IF EXISTS chk_observation_type;
ALTER TABLE reference_price ADD CONSTRAINT chk_observation_type
    CHECK (observation_type IN ('monthly', 'annual'));

COMMENT ON COLUMN reference_price.observation_type IS 'monthly or annual. Monthly rows are individual utility invoice observations; annual is the aggregate.';
COMMENT ON COLUMN reference_price.source_document_path IS 'S3 path to uploaded utility invoice document.';
COMMENT ON COLUMN reference_price.source_document_hash IS 'SHA-256 hash of source document for deduplication.';
COMMENT ON COLUMN reference_price.submission_response_id IS 'Link to the submission_response that created this observation.';

-- Update indexes to match new unique key
DROP INDEX IF EXISTS idx_ref_price_project;
CREATE INDEX IF NOT EXISTS idx_ref_price_project ON reference_price(project_id, observation_type, period_start);
CREATE INDEX IF NOT EXISTS idx_ref_price_project_year ON reference_price(project_id, operating_year);

-- Document hash dedup: prevent duplicate uploads for the same project
CREATE UNIQUE INDEX IF NOT EXISTS idx_ref_price_document_hash
    ON reference_price(project_id, source_document_hash)
    WHERE source_document_hash IS NOT NULL;

-- =========================================================================
-- C. Seed GRP definition for GH-MOH01
-- =========================================================================
-- Populates grp_method and grp_clause_text in clause_tariff.logic_parameters
-- for contract 7 (GH-MOH01).

UPDATE clause_tariff
SET logic_parameters = logic_parameters || '{
    "grp_method": "utility_variable_charges_tou",
    "grp_clause_text": "The Grid Reference Price (\"GRP\") for each month shall be calculated as the sum of all variable energy charges (excluding VAT, demand charges, and fixed charges) from the applicable ECG Utility Reference Invoice, divided by the total kWh invoiced during the billing period. Only charges incurred during the 06:00–18:00 operating window shall be included. The Utility Company shall deliver each Reference Invoice within 15 days of the end of the billing month. The Parties shall jointly verify the GRP within 30 days of receipt."
}'::jsonb
WHERE id = 2;

COMMIT;
