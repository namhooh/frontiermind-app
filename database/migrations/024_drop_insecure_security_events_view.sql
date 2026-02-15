-- Migration 024: Drop insecure v_security_events view
--
-- Security fix: v_security_events had two Supabase security linter issues:
--   1. "Exposed Auth Users Entity" - LEFT JOIN on auth.users exposed email to authenticated role
--   2. "SECURITY DEFINER property" - Ran with creator (superuser) permissions, bypassing RLS
--
-- Combined impact: ANY authenticated user could read ALL security events across ALL organizations.
-- The view is unused (zero references in app/, lib/, python-backend/).
-- get_audit_summary() already provides secure, org-scoped audit access.

BEGIN;

-- Revoke permissions before dropping
REVOKE SELECT ON v_security_events FROM authenticated;

-- Drop the insecure view
DROP VIEW IF EXISTS v_security_events;

-- Verify
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'v_security_events'
    ) THEN
        RAISE NOTICE 'Migration 024 successful: v_security_events dropped';
    ELSE
        RAISE WARNING 'Migration 024 failed: v_security_events still exists';
    END IF;
END $$;

COMMIT;
