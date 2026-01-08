-- =====================================================
-- MIGRATION: Repurpose role table for authentication
-- =====================================================
-- This migration transforms the role table from storing
-- organizational positions to storing user authentication
-- and permission information.
-- =====================================================

BEGIN;

-- Drop existing role data (organizational positions no longer needed)
TRUNCATE TABLE role CASCADE;

-- Add new columns for authentication
ALTER TABLE role
  ADD COLUMN user_id UUID UNIQUE,
  ADD COLUMN role_type VARCHAR CHECK (role_type IN ('admin', 'staff')),
  ADD COLUMN is_active BOOLEAN DEFAULT true,
  ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now();

-- Make new columns NOT NULL (after adding them nullable first)
ALTER TABLE role
  ALTER COLUMN user_id SET NOT NULL,
  ALTER COLUMN role_type SET NOT NULL;

-- Update indexes
CREATE INDEX idx_role_user_id ON role(user_id);
-- idx_role_org_id may already exist, if not:
CREATE INDEX IF NOT EXISTS idx_role_org_id ON role(organization_id);

COMMIT;

-- Note: Cannot use REFERENCES auth.users(id) directly across schemas
-- (public schema cannot reference auth schema)
-- Validate user_id existence in application code instead
