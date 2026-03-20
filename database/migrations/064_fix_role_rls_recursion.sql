-- =====================================================
-- Migration 064: Fix RLS infinite recursion on role table
-- =====================================================
-- The admin-read and admin-write policies on role queried
-- the role table itself, triggering infinite RLS recursion.
-- Fix: use a SECURITY DEFINER function that bypasses RLS.
-- =====================================================

BEGIN;

-- Drop the recursive policies
DROP POLICY IF EXISTS role_admin_read ON role;
DROP POLICY IF EXISTS role_admin_write ON role;

-- Create a SECURITY DEFINER function that checks admin status
-- without triggering RLS (runs as the function owner, not the caller)
CREATE OR REPLACE FUNCTION is_org_admin(p_org_id BIGINT)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
  SELECT EXISTS (
    SELECT 1 FROM role
    WHERE user_id = auth.uid()
      AND organization_id = p_org_id
      AND role_type = 'admin'
      AND is_active = true
  );
$$;

-- Recreate policies using the function (no recursion)
CREATE POLICY role_admin_read ON role FOR SELECT
  USING (is_org_admin(organization_id));

CREATE POLICY role_admin_write ON role FOR ALL
  USING (is_org_admin(organization_id));

COMMIT;
