-- Migration 016: Create audit_log table for comprehensive security logging
-- Based on Security Assessment Section 7.3
--
-- This table logs all security-relevant actions including:
-- - PII access
-- - Authentication events
-- - Data exports
-- - Administrative actions
-- - Data modifications

-- Create enum for audit action types
DO $$ BEGIN
    CREATE TYPE audit_action_type AS ENUM (
        -- Authentication events
        'LOGIN',
        'LOGOUT',
        'LOGIN_FAILED',
        'MFA_ENROLLED',
        'MFA_VERIFIED',
        'MFA_FAILED',
        'SESSION_EXPIRED',
        'PASSWORD_CHANGED',
        'PASSWORD_RESET_REQUESTED',

        -- Authorization events
        'ACCESS_DENIED',
        'ROLE_CHANGED',
        'PERMISSION_GRANTED',
        'PERMISSION_REVOKED',

        -- Data events
        'CREATE',
        'READ',
        'UPDATE',
        'DELETE',
        'EXPORT',
        'IMPORT',
        'BULK_EXPORT',
        'BULK_DELETE',

        -- PII-specific events
        'PII_ACCESS',
        'PII_EXPORT',
        'PII_DECRYPT',

        -- Contract events
        'CONTRACT_UPLOAD',
        'CONTRACT_PARSE',
        'CONTRACT_EXPORT',

        -- Integration events
        'API_KEY_CREATED',
        'API_KEY_REVOKED',
        'OAUTH_CONNECTED',
        'OAUTH_DISCONNECTED',

        -- Administrative events
        'USER_CREATED',
        'USER_DEACTIVATED',
        'ORGANIZATION_CREATED',
        'SETTINGS_CHANGED',

        -- Security events
        'RATE_LIMIT_EXCEEDED',
        'SUSPICIOUS_ACTIVITY',
        'IP_BLOCKED'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create audit severity level enum
DO $$ BEGIN
    CREATE TYPE audit_severity AS ENUM (
        'DEBUG',
        'INFO',
        'WARNING',
        'ERROR',
        'CRITICAL'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create data classification level enum
-- Classification Hierarchy (from least to most sensitive):
--   public:       Information safe for anyone (API health, version info)
--   internal:     Business info, not sensitive (general events, login success)
--   confidential: Sensitive business data requiring protection (pricing, terms, exports)
--   restricted:   Highest sensitivity - PII, credentials, security events
--                 May trigger legal notification requirements (GDPR, CCPA)
DO $$ BEGIN
    CREATE TYPE data_classification_level AS ENUM (
        'public',       -- Safe for public access
        'internal',     -- Internal use only, minimal harm if exposed
        'confidential', -- Sensitive business data, requires protection
        'restricted'    -- PII, credentials, security - strictest controls
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create the main audit_log table
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,

    -- Timestamp with timezone for accurate global logging
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Actor information
    user_id UUID REFERENCES auth.users(id),
    organization_id BIGINT REFERENCES organization(id),
    session_id TEXT,

    -- Action details
    action audit_action_type NOT NULL,
    severity audit_severity NOT NULL DEFAULT 'INFO',

    -- Resource information
    resource_type TEXT NOT NULL,  -- e.g., 'contract', 'clause', 'user'
    resource_id TEXT,             -- ID of the affected resource
    resource_name TEXT,           -- Human-readable name for context

    -- Request information
    ip_address INET,
    user_agent TEXT,
    request_id TEXT,
    request_method TEXT,
    request_path TEXT,

    -- Event details (JSON for flexibility)
    details JSONB DEFAULT '{}',

    -- Success/failure tracking
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,

    -- Additional context
    duration_ms INTEGER,  -- How long the action took
    records_affected INTEGER DEFAULT 0,

    -- Metadata for compliance
    compliance_relevant BOOLEAN DEFAULT FALSE,
    data_classification data_classification_level DEFAULT 'internal',

    -- Indexes for common queries
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_organization_id ON audit_log(organization_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_severity ON audit_log(severity) WHERE severity IN ('WARNING', 'ERROR', 'CRITICAL');
CREATE INDEX IF NOT EXISTS idx_audit_log_compliance ON audit_log(timestamp DESC) WHERE compliance_relevant = TRUE;
CREATE INDEX IF NOT EXISTS idx_audit_log_ip ON audit_log(ip_address);

-- Composite index for user activity queries
CREATE INDEX IF NOT EXISTS idx_audit_log_user_activity
    ON audit_log(user_id, timestamp DESC)
    WHERE user_id IS NOT NULL;

-- Immutability trigger: Audit logs must be append-only
-- Prevents modification or deletion of audit records for forensic integrity
--
-- OPERATIONAL NOTE: Immutability Trigger Bypass Procedure
-- =========================================================
-- In rare cases where bulk data correction is legally required (e.g., GDPR right
-- to erasure, court order, data migration), use the following procedure:
--
-- 1. Document the reason and obtain formal approval through change management
-- 2. Connect as superuser or role with ALTER TABLE privileges
-- 3. Disable trigger:
--    ALTER TABLE audit_log DISABLE TRIGGER audit_log_immutability;
-- 4. Perform corrections (keep detailed records of what was modified/deleted)
-- 5. Re-enable trigger:
--    ALTER TABLE audit_log ENABLE TRIGGER audit_log_immutability;
-- 6. Log the bypass event manually:
--    INSERT INTO audit_log (action, resource_type, details, severity, compliance_relevant)
--    VALUES ('SETTINGS_CHANGED', 'audit_log', '{"event": "immutability_bypass", "reason": "..."}'::jsonb,
--            'CRITICAL', TRUE);
--
-- WARNING: Only perform this under formal change management with documented approval.
-- Audit log integrity is critical for compliance and forensic investigations.
--
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are immutable and cannot be modified or deleted. '
                    'This ensures forensic integrity and compliance with data protection regulations.';
END;
$$;

CREATE TRIGGER audit_log_immutability
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_log_modification();

COMMENT ON FUNCTION prevent_audit_log_modification IS 'Enforces audit log immutability - logs cannot be modified or deleted';

-- Enable RLS on audit_log
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Service role can access all logs
CREATE POLICY audit_log_service_policy ON audit_log
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- RLS Policy: Admins can read logs for their organization
CREATE POLICY audit_log_admin_read_policy ON audit_log
    FOR SELECT
    TO authenticated
    USING (
        -- User must be admin of the organization
        EXISTS (
            SELECT 1 FROM role r
            WHERE r.user_id = auth.uid()
            AND r.organization_id = audit_log.organization_id
            AND r.role_type = 'admin'
            AND r.is_active = TRUE
        )
        OR
        -- Or the log is about the current user
        user_id = auth.uid()
    );

-- RLS Policy: Only service role can insert logs
CREATE POLICY audit_log_insert_policy ON audit_log
    FOR INSERT
    TO service_role
    WITH CHECK (TRUE);

-- Function to log audit events (called from application code)
-- SECURITY: Only callable by service_role; validates organization and user exist
CREATE OR REPLACE FUNCTION log_audit_event(
    p_user_id UUID,
    p_organization_id BIGINT,
    p_action audit_action_type,
    p_resource_type TEXT,
    p_resource_id TEXT DEFAULT NULL,
    p_resource_name TEXT DEFAULT NULL,
    p_details JSONB DEFAULT '{}',
    p_success BOOLEAN DEFAULT TRUE,
    p_error_message TEXT DEFAULT NULL,
    p_ip_address INET DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL,
    p_severity audit_severity DEFAULT 'INFO',
    p_compliance_relevant BOOLEAN DEFAULT FALSE,
    p_data_classification data_classification_level DEFAULT 'internal',
    p_duration_ms INTEGER DEFAULT NULL,
    p_records_affected INTEGER DEFAULT 0
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_log_id BIGINT;
BEGIN
    -- Input validation: Verify organization exists if provided
    IF p_organization_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM organization WHERE id = p_organization_id
    ) THEN
        RAISE EXCEPTION 'Invalid organization_id: % does not exist', p_organization_id;
    END IF;

    -- Input validation: Verify user exists if provided
    IF p_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM auth.users WHERE id = p_user_id
    ) THEN
        RAISE EXCEPTION 'Invalid user_id: % does not exist', p_user_id;
    END IF;

    INSERT INTO audit_log (
        user_id,
        organization_id,
        action,
        resource_type,
        resource_id,
        resource_name,
        details,
        success,
        error_message,
        ip_address,
        user_agent,
        severity,
        compliance_relevant,
        data_classification,
        duration_ms,
        records_affected
    ) VALUES (
        p_user_id,
        p_organization_id,
        p_action,
        p_resource_type,
        p_resource_id,
        p_resource_name,
        p_details,
        p_success,
        p_error_message,
        p_ip_address,
        p_user_agent,
        p_severity,
        p_compliance_relevant,
        p_data_classification,
        p_duration_ms,
        p_records_affected
    )
    RETURNING id INTO v_log_id;

    RETURN v_log_id;
END;
$$;

-- Function to log PII access (convenience wrapper)
-- SECURITY: Validates contract exists; logs with 'restricted' classification
-- Always use this for PII operations to ensure compliance tracking
CREATE OR REPLACE FUNCTION log_pii_access_event(
    p_user_id UUID,
    p_organization_id BIGINT,
    p_contract_id BIGINT,  -- Matches contract.id (BIGSERIAL)
    p_access_type TEXT,  -- 'VIEW', 'EXPORT', 'DECRYPT'
    p_ip_address INET DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_action audit_action_type;
BEGIN
    -- Input validation: Verify contract exists
    IF p_contract_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM contract WHERE id = p_contract_id
    ) THEN
        RAISE EXCEPTION 'Invalid contract_id: % does not exist', p_contract_id;
    END IF;

    -- Map access type to audit action
    v_action := CASE p_access_type
        WHEN 'VIEW' THEN 'PII_ACCESS'::audit_action_type
        WHEN 'EXPORT' THEN 'PII_EXPORT'::audit_action_type
        WHEN 'DECRYPT' THEN 'PII_DECRYPT'::audit_action_type
        ELSE 'PII_ACCESS'::audit_action_type
    END;

    RETURN log_audit_event(
        p_user_id := p_user_id,
        p_organization_id := p_organization_id,
        p_action := v_action,
        p_resource_type := 'contract_pii_mapping',
        p_resource_id := p_contract_id::TEXT,
        p_details := jsonb_build_object('access_type', p_access_type),
        p_ip_address := p_ip_address,
        p_severity := 'WARNING'::audit_severity,
        p_compliance_relevant := TRUE,
        p_data_classification := 'restricted'::data_classification_level
    );
END;
$$;

-- Function to get audit summary for an organization
-- SECURITY: Requires caller to be an admin of the specified organization
-- Prevents cross-organization data leakage
CREATE OR REPLACE FUNCTION get_audit_summary(
    p_organization_id BIGINT,
    p_start_date TIMESTAMPTZ DEFAULT NOW() - INTERVAL '30 days',
    p_end_date TIMESTAMPTZ DEFAULT NOW()
)
RETURNS TABLE (
    action_type audit_action_type,
    severity audit_severity,
    total_count BIGINT,
    success_count BIGINT,
    failure_count BIGINT,
    unique_users BIGINT
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_is_admin BOOLEAN;
    v_current_role TEXT;
BEGIN
    -- Get current database role
    SELECT current_setting('role', true) INTO v_current_role;

    -- Service role bypass: Trusted backend has full access
    -- auth.uid() returns NULL for service_role, so we check role directly
    IF v_current_role = 'service_role' THEN
        -- Service role is trusted, skip admin check
        NULL;
    ELSE
        -- Authorization check: Verify caller is admin of the organization
        SELECT EXISTS (
            SELECT 1 FROM role r
            WHERE r.user_id = auth.uid()
            AND r.organization_id = p_organization_id
            AND r.role_type = 'admin'
            AND r.is_active = TRUE
        ) INTO v_is_admin;

        IF NOT v_is_admin THEN
            RAISE EXCEPTION 'Access denied: Admin role required for organization %', p_organization_id;
        END IF;
    END IF;

    RETURN QUERY
    SELECT
        al.action,
        al.severity,
        COUNT(*)::BIGINT,
        COUNT(*) FILTER (WHERE al.success)::BIGINT,
        COUNT(*) FILTER (WHERE NOT al.success)::BIGINT,
        COUNT(DISTINCT al.user_id)::BIGINT
    FROM audit_log al
    WHERE al.organization_id = p_organization_id
        AND al.timestamp BETWEEN p_start_date AND p_end_date
    GROUP BY al.action, al.severity
    ORDER BY COUNT(*) DESC;
END;
$$;

-- View for recent security events (WARNING and above)
CREATE OR REPLACE VIEW v_security_events AS
SELECT
    al.id,
    al.timestamp,
    al.user_id,
    u.email AS user_email,
    al.organization_id,
    o.name AS organization_name,
    al.action,
    al.severity,
    al.resource_type,
    al.resource_id,
    al.ip_address,
    al.success,
    al.error_message,
    al.details
FROM audit_log al
LEFT JOIN auth.users u ON al.user_id = u.id
LEFT JOIN organization o ON al.organization_id = o.id
WHERE al.severity IN ('WARNING', 'ERROR', 'CRITICAL')
ORDER BY al.timestamp DESC;

-- Security: Revoke default PUBLIC permissions on sensitive functions
-- These functions should only be callable by explicitly granted roles
REVOKE ALL ON FUNCTION log_audit_event FROM PUBLIC;
REVOKE ALL ON FUNCTION log_pii_access_event FROM PUBLIC;
REVOKE ALL ON FUNCTION get_audit_summary FROM PUBLIC;
REVOKE ALL ON FUNCTION prevent_audit_log_modification FROM PUBLIC;

-- Grant permissions to appropriate roles
GRANT SELECT ON v_security_events TO authenticated;
GRANT EXECUTE ON FUNCTION log_audit_event TO service_role;
GRANT EXECUTE ON FUNCTION log_pii_access_event TO service_role;
GRANT EXECUTE ON FUNCTION get_audit_summary TO authenticated;
GRANT EXECUTE ON FUNCTION get_audit_summary TO service_role;  -- Also allow service_role

COMMENT ON TABLE audit_log IS 'Comprehensive audit log for security events, compliance tracking, and forensic analysis';
COMMENT ON FUNCTION log_audit_event IS 'Log a security audit event - use from application code for all security-relevant actions';
COMMENT ON FUNCTION log_pii_access_event IS 'Convenience wrapper for logging PII access events - always use for PII operations';
