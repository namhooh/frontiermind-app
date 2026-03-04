-- Migration: 051_org_email_address.sql
-- Description: Maps organizations to dedicated email addresses on mail.frontiermind.co
-- Version: v8.2
-- Date: 2026-03-04
-- Depends on: 032_email_notification_engine.sql

-- =============================================================================
-- SECTION 1: ORG EMAIL ADDRESS TABLE
-- =============================================================================

CREATE TABLE org_email_address (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- The local part before @mail.frontiermind.co (e.g., 'cbe' → cbe@mail.frontiermind.co)
    email_prefix VARCHAR(63) NOT NULL,
    domain VARCHAR(255) NOT NULL DEFAULT 'mail.frontiermind.co',

    -- Display name shown as the sender (e.g., 'CrossBoundary Energy' → "CrossBoundary Energy <cbe@mail.frontiermind.co>")
    display_name VARCHAR(200),

    -- Purpose / routing label
    label VARCHAR(100) DEFAULT 'default',

    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each prefix+domain combination must be globally unique
CREATE UNIQUE INDEX ux_org_email_prefix_domain
    ON org_email_address (email_prefix, domain);

-- Each org can only have one address per label
CREATE UNIQUE INDEX ux_org_email_org_label
    ON org_email_address (organization_id, label);

CREATE INDEX idx_org_email_org
    ON org_email_address (organization_id);

-- Lookup by full address for inbound routing
CREATE INDEX idx_org_email_prefix_active
    ON org_email_address (email_prefix, domain)
    WHERE is_active = true;

-- =============================================================================
-- SECTION 2: COMMENTS
-- =============================================================================

COMMENT ON TABLE org_email_address IS
    'Maps organizations to dedicated email addresses on mail.frontiermind.co for bidirectional email (outbound notifications + inbound invoice ingestion).';

COMMENT ON COLUMN org_email_address.email_prefix IS
    'Local part of the email address. E.g., ''cbe'' for cbe@mail.frontiermind.co.';

COMMENT ON COLUMN org_email_address.domain IS
    'Email domain. Defaults to mail.frontiermind.co.';

COMMENT ON COLUMN org_email_address.display_name IS
    'Sender display name shown in email From header. E.g., ''CrossBoundary Energy'' → "CrossBoundary Energy <cbe@mail.frontiermind.co>".';

COMMENT ON COLUMN org_email_address.label IS
    'Purpose label for multi-address orgs (e.g., default, billing, support).';

-- =============================================================================
-- SECTION 3: ROW LEVEL SECURITY
-- =============================================================================

ALTER TABLE org_email_address ENABLE ROW LEVEL SECURITY;

-- Org members can read their org's email addresses
DROP POLICY IF EXISTS org_email_address_select_policy ON org_email_address;
CREATE POLICY org_email_address_select_policy ON org_email_address
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

-- Org admins can manage email addresses
DROP POLICY IF EXISTS org_email_address_admin_policy ON org_email_address;
CREATE POLICY org_email_address_admin_policy ON org_email_address
    FOR ALL TO authenticated
    USING (is_org_admin(organization_id))
    WITH CHECK (is_org_admin(organization_id));

-- Service role has full access
DROP POLICY IF EXISTS org_email_address_service_policy ON org_email_address;
CREATE POLICY org_email_address_service_policy ON org_email_address
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- SECTION 4: UPDATED_AT TRIGGER
-- =============================================================================

CREATE OR REPLACE FUNCTION update_org_email_address_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS org_email_address_updated_at ON org_email_address;
CREATE TRIGGER org_email_address_updated_at
    BEFORE INSERT OR UPDATE ON org_email_address
    FOR EACH ROW
    EXECUTE FUNCTION update_org_email_address_timestamp();

REVOKE EXECUTE ON FUNCTION update_org_email_address_timestamp FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_org_email_address_timestamp TO service_role;

-- =============================================================================
-- SECTION 5: SEED CBE EMAIL ADDRESS
-- =============================================================================

INSERT INTO org_email_address (organization_id, email_prefix, domain, display_name, label)
SELECT
    o.id,
    'cbe',
    'mail.frontiermind.co',
    'CrossBoundary Energy',
    'default'
FROM organization o
WHERE o.id = 1
  AND NOT EXISTS (
    SELECT 1 FROM org_email_address ea
    WHERE ea.organization_id = o.id
      AND ea.email_prefix = 'cbe'
  );

-- =============================================================================
-- SECTION 6: VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check table exists
    SELECT COUNT(*) INTO v_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'org_email_address';

    IF v_count < 1 THEN
        RAISE EXCEPTION 'org_email_address table was not created';
    END IF;

    -- Check CBE seed row
    SELECT COUNT(*) INTO v_count
    FROM org_email_address
    WHERE email_prefix = 'cbe' AND domain = 'mail.frontiermind.co';

    IF v_count < 1 THEN
        RAISE WARNING 'CBE email address seed row not found — organization id=1 may not exist yet';
    END IF;

    RAISE NOTICE 'Migration 051_org_email_address (v8.2) completed successfully';
END $$;
