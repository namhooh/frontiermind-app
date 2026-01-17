-- =====================================================
-- MIGRATION 009: Create Integration Credential Table
-- =====================================================
-- Stores encrypted API keys and OAuth tokens for inverter integrations
-- per DATA_INGESTION_ARCHITECTURE.md section 5.1
--
-- Supported sources: Reference data_source table for integration types
-- Auth types: api_key (SolarEdge, GoodWe), oauth2 (Enphase, SMA)
--
-- Security:
-- - Credentials encrypted using Fernet (AES-128-CBC)
-- - Encryption key stored in AWS Secrets Manager
-- - Row Level Security enabled for multi-tenant isolation
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Create integration_credential table
-- =====================================================

CREATE TABLE IF NOT EXISTS integration_credential (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- Integration identification
    data_source_id BIGINT NOT NULL REFERENCES data_source(id),
    auth_type VARCHAR(20) NOT NULL,       -- 'api_key', 'oauth2'
    label VARCHAR(255),                   -- User-friendly label (e.g., "Main SolarEdge Account")

    -- Encrypted credentials (Fernet-encrypted JSON)
    -- For API key: {"api_key": "..."}
    -- For OAuth: {"access_token": "...", "refresh_token": "...", "scope": "..."}
    encrypted_credentials BYTEA NOT NULL,
    encryption_method VARCHAR(50) NOT NULL DEFAULT 'fernet',

    -- OAuth token management
    token_expires_at TIMESTAMPTZ,         -- When access token expires
    token_refreshed_at TIMESTAMPTZ,       -- When token was last refreshed

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    last_error TEXT,
    error_count INTEGER DEFAULT 0,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id),

    -- Constraints
    CONSTRAINT chk_integration_credential_auth
        CHECK (auth_type IN ('api_key', 'oauth2'))
);

-- =====================================================
-- Step 2: Create indexes
-- =====================================================

CREATE INDEX idx_integration_credential_org ON integration_credential(organization_id);
CREATE INDEX idx_integration_credential_source ON integration_credential(data_source_id);
CREATE INDEX idx_integration_credential_active ON integration_credential(is_active) WHERE is_active = TRUE;

-- =====================================================
-- Step 3: Enable Row Level Security
-- =====================================================

ALTER TABLE integration_credential ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see credentials for their organization
CREATE POLICY integration_credential_org_policy ON integration_credential
    FOR ALL
    USING (
        organization_id IN (
            SELECT organization_id FROM role
            WHERE user_id = auth.uid()
        )
    );

-- Service role can access all (for fetcher workers)
CREATE POLICY integration_credential_service_policy ON integration_credential
    FOR ALL
    USING (auth.role() = 'service_role');

-- =====================================================
-- Step 4: Create trigger for updated_at
-- =====================================================

CREATE OR REPLACE FUNCTION update_integration_credential_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_integration_credential_updated_at
    BEFORE UPDATE ON integration_credential
    FOR EACH ROW
    EXECUTE FUNCTION update_integration_credential_timestamp();

-- =====================================================
-- Step 5: Add comments
-- =====================================================

COMMENT ON TABLE integration_credential IS 'Encrypted API keys and OAuth tokens for external data source integrations';
COMMENT ON COLUMN integration_credential.data_source_id IS 'FK to data_source table for external integration type';
COMMENT ON COLUMN integration_credential.auth_type IS 'Authentication method: api_key (static), oauth2 (token refresh)';
COMMENT ON COLUMN integration_credential.encrypted_credentials IS 'Fernet-encrypted JSON containing API key or OAuth tokens';
COMMENT ON COLUMN integration_credential.token_expires_at IS 'For OAuth: when the access token expires and needs refresh';
COMMENT ON COLUMN integration_credential.last_error IS 'Last error message from using this credential';
COMMENT ON COLUMN integration_credential.error_count IS 'Consecutive error count (reset on success)';

-- =====================================================
-- Step 6: Create helper functions
-- =====================================================

-- Function to check if token needs refresh (for OAuth)
CREATE OR REPLACE FUNCTION integration_credential_needs_refresh(
    p_credential_id BIGINT
) RETURNS BOOLEAN AS $$
DECLARE
    v_auth_type VARCHAR(20);
    v_expires_at TIMESTAMPTZ;
BEGIN
    SELECT auth_type, token_expires_at
    INTO v_auth_type, v_expires_at
    FROM integration_credential
    WHERE id = p_credential_id;

    -- API keys don't need refresh
    IF v_auth_type = 'api_key' THEN
        RETURN FALSE;
    END IF;

    -- OAuth tokens need refresh 5 minutes before expiry
    IF v_expires_at IS NULL THEN
        RETURN TRUE;  -- Unknown expiry, refresh to be safe
    END IF;

    RETURN v_expires_at <= (NOW() + INTERVAL '5 minutes');
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Function to record successful credential use
CREATE OR REPLACE FUNCTION integration_credential_record_success(
    p_credential_id BIGINT
) RETURNS VOID AS $$
BEGIN
    UPDATE integration_credential
    SET
        last_used_at = NOW(),
        last_error = NULL,
        error_count = 0
    WHERE id = p_credential_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to record credential error
CREATE OR REPLACE FUNCTION integration_credential_record_error(
    p_credential_id BIGINT,
    p_error_message TEXT
) RETURNS VOID AS $$
BEGIN
    UPDATE integration_credential
    SET
        last_used_at = NOW(),
        last_error = p_error_message,
        error_count = error_count + 1
    WHERE id = p_credential_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION integration_credential_needs_refresh IS 'Checks if an OAuth credential needs token refresh';
COMMENT ON FUNCTION integration_credential_record_success IS 'Records successful use of credential, resets error count';
COMMENT ON FUNCTION integration_credential_record_error IS 'Records error when using credential';

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
        WHERE table_name = 'integration_credential'
    ) INTO table_exists;

    IF table_exists THEN
        RAISE NOTICE 'Migration successful: integration_credential table created';
    ELSE
        RAISE WARNING 'Migration failed: integration_credential table not found';
    END IF;
END $$;

COMMIT;

-- Display table structure
SELECT 'integration_credential table structure:' AS info;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'integration_credential'
ORDER BY ordinal_position;
