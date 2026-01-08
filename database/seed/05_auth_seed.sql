-- =====================================================
-- AUTH SEED DATA
-- =====================================================
-- Link Supabase auth users to role table
-- This creates the first admin user in the system
-- =====================================================

BEGIN;

-- Link first Supabase auth user to admin role
-- User UID from Supabase: 0738a58c-594a-4aae-9397-e08cdcc1eed4
INSERT INTO role (user_id, organization_id, role_type, name, email, is_active)
VALUES ('0738a58c-594a-4aae-9397-e08cdcc1eed4', 1, 'admin', 'System Administrator', 'admin@yourcompany.com', true);

COMMIT;
