-- =====================================================
-- Migration 063: Role Table Expansion
-- =====================================================
-- Expands role_type values, adds profile/invite fields,
-- enables RLS, and adds audit action types for team management.
-- =====================================================

-- Note: ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
-- Run these first, outside the main BEGIN/COMMIT.
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'MEMBER_INVITED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'MEMBER_ROLE_CHANGED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'MEMBER_DEACTIVATED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'MEMBER_REACTIVATED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'INVITE_ACCEPTED';

BEGIN;

-- 1. Expand role_type values: admin, staff → admin, approver, editor, viewer
ALTER TABLE role DROP CONSTRAINT IF EXISTS role_role_type_check;
ALTER TABLE role ADD CONSTRAINT role_role_type_check
  CHECK (role_type IN ('admin', 'approver', 'editor', 'viewer'));

-- Migrate existing 'staff' → 'editor'
UPDATE role SET role_type = 'editor' WHERE role_type = 'staff';

-- 2. Add profile/team fields
ALTER TABLE role ADD COLUMN IF NOT EXISTS department VARCHAR;
ALTER TABLE role ADD COLUMN IF NOT EXISTS job_title VARCHAR;

-- 3. Create member_status enum and add invite lifecycle fields
DO $$ BEGIN
  CREATE TYPE member_status AS ENUM ('invited', 'active', 'suspended', 'deactivated');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE role ADD COLUMN IF NOT EXISTS member_status member_status DEFAULT 'active';
ALTER TABLE role ADD COLUMN IF NOT EXISTS invited_by UUID;
ALTER TABLE role ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ;
ALTER TABLE role ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ;
ALTER TABLE role ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;

-- Backfill existing rows
UPDATE role SET member_status = 'active' WHERE member_status IS NULL;
ALTER TABLE role ALTER COLUMN member_status SET NOT NULL;

-- 4. Enable RLS
ALTER TABLE role ENABLE ROW LEVEL SECURITY;

-- Users can read their own membership
CREATE POLICY role_self_read ON role FOR SELECT
  USING (user_id = auth.uid());

-- Update is_org_admin function to include role_type check
-- (SECURITY DEFINER bypasses RLS, avoiding infinite recursion)
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

-- Org admins can read all memberships in their org
CREATE POLICY role_admin_read ON role FOR SELECT
  USING (is_org_admin(organization_id));

-- Org admins can insert/update/delete memberships in their org
CREATE POLICY role_admin_write ON role FOR ALL
  USING (is_org_admin(organization_id));

COMMIT;
