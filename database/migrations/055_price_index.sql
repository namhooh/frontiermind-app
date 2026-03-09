-- Migration 055: Create price_index table for CPI and other economic indices
-- Used for tariff escalation calculations (US CPI-linked projects: LOI01, GC001, etc.)

CREATE TABLE IF NOT EXISTS price_index (
    id              BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id),
    index_code      VARCHAR(50),                    -- e.g., 'CUUR0000SA0' (BLS series ID)
    index_name      VARCHAR(200) NOT NULL,          -- e.g., 'US CPI-U All Items'
    reference_date  DATE NOT NULL,                  -- First day of the month the value applies to
    index_value     NUMERIC(12, 4) NOT NULL,        -- The index level (e.g., 261.582)
    source          VARCHAR(100) NOT NULL DEFAULT 'manual', -- e.g., 'bls.gov', 'revenue_masterfile'
    source_metadata JSONB,                          -- Additional context (base period, seasonal adjustment, etc.)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_price_index UNIQUE (organization_id, index_code, reference_date)
);

COMMENT ON TABLE price_index IS 'Economic price indices (CPI, PPI, etc.) used for tariff escalation calculations';
COMMENT ON COLUMN price_index.index_code IS 'BLS series ID or other standard identifier';
COMMENT ON COLUMN price_index.reference_date IS 'First day of month the index value applies to';
COMMENT ON COLUMN price_index.index_value IS 'The index level (not percentage change)';

-- Enable RLS
ALTER TABLE price_index ENABLE ROW LEVEL SECURITY;

CREATE POLICY "price_index_org_access" ON price_index
    USING (is_org_member(organization_id));
