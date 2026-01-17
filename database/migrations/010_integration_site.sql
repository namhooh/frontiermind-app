-- =====================================================
-- MIGRATION 010: Create Integration Site Table
-- =====================================================
-- Maps external inverter sites to internal projects
-- per DATA_INGESTION_ARCHITECTURE.md section 5.2
--
-- Each credential can have multiple sites (e.g., one SolarEdge account manages multiple installations)
-- Each site maps to one project (or can be unmapped initially for discovery)
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Create integration_site table
-- =====================================================

CREATE TABLE IF NOT EXISTS integration_site (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    integration_credential_id BIGINT NOT NULL REFERENCES integration_credential(id) ON DELETE CASCADE,

    -- Project mapping (can be NULL if not yet mapped)
    project_id BIGINT REFERENCES project(id) ON DELETE SET NULL,
    meter_id BIGINT REFERENCES meter(id) ON DELETE SET NULL,

    -- External identifiers
    data_source_id BIGINT NOT NULL REFERENCES data_source(id),
    external_site_id VARCHAR(255) NOT NULL, -- Site ID in the external system
    external_site_name VARCHAR(255),        -- Human-readable name from external system
    external_metadata JSONB,                -- Additional site info from API (capacity, location, etc.)

    -- Sync configuration
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sync_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sync_interval_minutes INTEGER DEFAULT 60,   -- How often to fetch data

    -- Sync status
    last_sync_at TIMESTAMPTZ,
    last_sync_status VARCHAR(50),           -- 'success', 'error', 'pending', 'partial'
    last_sync_error TEXT,
    last_sync_records_count INTEGER,        -- Records fetched in last sync
    consecutive_failures INTEGER DEFAULT 0,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT uq_integration_site_credential_external
        UNIQUE (integration_credential_id, external_site_id),
    CONSTRAINT chk_integration_site_sync_status
        CHECK (last_sync_status IS NULL OR last_sync_status IN ('success', 'error', 'pending', 'partial'))
);

-- =====================================================
-- Step 2: Create indexes
-- =====================================================

CREATE INDEX idx_integration_site_org ON integration_site(organization_id);
CREATE INDEX idx_integration_site_credential ON integration_site(integration_credential_id);
CREATE INDEX idx_integration_site_project ON integration_site(project_id);
CREATE INDEX idx_integration_site_external ON integration_site(external_site_id);
CREATE INDEX idx_integration_site_active ON integration_site(is_active, sync_enabled)
    WHERE is_active = TRUE AND sync_enabled = TRUE;

-- =====================================================
-- Step 3: Enable Row Level Security
-- =====================================================

ALTER TABLE integration_site ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see sites for their organization
CREATE POLICY integration_site_org_policy ON integration_site
    FOR ALL
    USING (
        organization_id IN (
            SELECT organization_id FROM role
            WHERE user_id = auth.uid()
        )
    );

-- Service role can access all (for fetcher workers)
CREATE POLICY integration_site_service_policy ON integration_site
    FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- Step 4: Create trigger for updated_at
-- =====================================================

CREATE OR REPLACE FUNCTION update_integration_site_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_integration_site_updated_at
    BEFORE UPDATE ON integration_site
    FOR EACH ROW
    EXECUTE FUNCTION update_integration_site_timestamp();

-- =====================================================
-- Step 5: Add comments
-- =====================================================

COMMENT ON TABLE integration_site IS 'Maps external inverter sites to internal projects for data synchronization';
COMMENT ON COLUMN integration_site.integration_credential_id IS 'The API credential used to access this site';
COMMENT ON COLUMN integration_site.data_source_id IS 'FK to data_source table for integration type';
COMMENT ON COLUMN integration_site.project_id IS 'Internal project this site maps to (NULL if unmapped)';
COMMENT ON COLUMN integration_site.external_site_id IS 'Site identifier in the external system (e.g., SolarEdge site ID)';
COMMENT ON COLUMN integration_site.external_site_name IS 'Human-readable site name from external system';
COMMENT ON COLUMN integration_site.external_metadata IS 'Additional site info: capacity, location, installation date, etc.';
COMMENT ON COLUMN integration_site.sync_interval_minutes IS 'How often to fetch data for this site';
COMMENT ON COLUMN integration_site.last_sync_status IS 'Status of last sync: success, error, pending, partial';
COMMENT ON COLUMN integration_site.consecutive_failures IS 'Count of consecutive sync failures (for alerting)';

-- =====================================================
-- Step 6: Create helper functions
-- =====================================================

-- Function to get sites ready for sync
-- Drop old signature first to avoid overload conflict
DROP FUNCTION IF EXISTS get_sites_ready_for_sync(VARCHAR);

CREATE OR REPLACE FUNCTION get_sites_ready_for_sync(
    p_data_source_id BIGINT DEFAULT NULL
) RETURNS TABLE (
    site_id BIGINT,
    organization_id BIGINT,
    integration_credential_id BIGINT,
    project_id BIGINT,
    external_site_id VARCHAR(255),
    minutes_since_sync INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id AS site_id,
        s.organization_id,
        s.integration_credential_id,
        s.project_id,
        s.external_site_id,
        EXTRACT(EPOCH FROM (NOW() - COALESCE(s.last_sync_at, '1970-01-01'::timestamptz)))::INTEGER / 60 AS minutes_since_sync
    FROM integration_site s
    JOIN integration_credential c ON s.integration_credential_id = c.id
    WHERE s.is_active = TRUE
      AND s.sync_enabled = TRUE
      AND c.is_active = TRUE
      AND (p_data_source_id IS NULL OR s.data_source_id = p_data_source_id)
      AND (
          s.last_sync_at IS NULL
          OR s.last_sync_at < NOW() - (s.sync_interval_minutes || ' minutes')::INTERVAL
      )
    ORDER BY s.last_sync_at NULLS FIRST;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Function to update sync status
CREATE OR REPLACE FUNCTION update_site_sync_status(
    p_site_id BIGINT,
    p_status VARCHAR(50),
    p_error TEXT DEFAULT NULL,
    p_records_count INTEGER DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE integration_site
    SET
        last_sync_at = NOW(),
        last_sync_status = p_status,
        last_sync_error = CASE WHEN p_status = 'success' THEN NULL ELSE p_error END,
        last_sync_records_count = p_records_count,
        consecutive_failures = CASE
            WHEN p_status = 'success' THEN 0
            ELSE consecutive_failures + 1
        END
    WHERE id = p_site_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_sites_ready_for_sync IS 'Returns sites that are due for data synchronization';
COMMENT ON FUNCTION update_site_sync_status IS 'Updates the sync status after a fetch attempt';

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
        WHERE table_name = 'integration_site'
    ) INTO table_exists;

    IF table_exists THEN
        RAISE NOTICE 'Migration successful: integration_site table created';
    ELSE
        RAISE WARNING 'Migration failed: integration_site table not found';
    END IF;
END $$;

COMMIT;

-- Display table structure
SELECT 'integration_site table structure:' AS info;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'integration_site'
ORDER BY ordinal_position;
