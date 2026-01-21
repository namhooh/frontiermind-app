-- Migration 017: Add Row Level Security to Core Tables
-- Based on Security Assessment Section 4.6
--
-- This migration adds RLS policies to the following critical tables:
-- - organization (tenant isolation)
-- - project (organization-scoped)
-- - contract (organization-scoped)
-- - clause (organization-scoped via contract)
-- - event (organization-scoped via contract)
-- - counterparty (organization-scoped)

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================
-- These functions centralize authorization logic for cleaner policies,
-- better performance (single place to optimize), and easier maintenance.

-- Check if current user is a member of the specified organization
-- Explicitly checks for NULL auth.uid() to fail safely in unauthenticated contexts
CREATE OR REPLACE FUNCTION is_org_member(p_org_id BIGINT)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT (SELECT auth.uid()) IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM public.role r
        WHERE r.user_id = (SELECT auth.uid())
        AND r.organization_id = p_org_id
        AND r.is_active = TRUE
    );
$$;

-- Check if current user is an admin of the specified organization
-- Explicitly checks for NULL auth.uid() to fail safely in unauthenticated contexts
CREATE OR REPLACE FUNCTION is_org_admin(p_org_id BIGINT)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT (SELECT auth.uid()) IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM public.role r
        WHERE r.user_id = (SELECT auth.uid())
        AND r.organization_id = p_org_id
        AND r.role_type = 'admin'
        AND r.is_active = TRUE
    );
$$;

-- Get organization_id for a project (for nested lookups)
CREATE OR REPLACE FUNCTION get_project_org_id(p_project_id BIGINT)
RETURNS BIGINT
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT organization_id FROM public.project WHERE id = p_project_id;
$$;

-- Get organization_id for a contract (via project)
CREATE OR REPLACE FUNCTION get_contract_org_id(p_contract_id BIGINT)
RETURNS BIGINT
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT p.organization_id
    FROM public.contract c
    JOIN public.project p ON p.id = c.project_id
    WHERE c.id = p_contract_id;
$$;

-- Get organization_id for an asset (via project)
CREATE OR REPLACE FUNCTION get_asset_org_id(p_asset_id BIGINT)
RETURNS BIGINT
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT p.organization_id
    FROM public.asset a
    JOIN public.project p ON p.id = a.project_id
    WHERE a.id = p_asset_id;
$$;

-- Get organization_id for a meter (via asset -> project)
CREATE OR REPLACE FUNCTION get_meter_org_id(p_meter_id BIGINT)
RETURNS BIGINT
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT p.organization_id
    FROM public.meter m
    JOIN public.asset a ON a.id = m.asset_id
    JOIN public.project p ON p.id = a.project_id
    WHERE m.id = p_meter_id;
$$;

-- Security: Revoke default PUBLIC access, grant only to required roles
REVOKE EXECUTE ON FUNCTION is_org_member FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION is_org_admin FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_project_org_id FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_contract_org_id FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_asset_org_id FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_meter_org_id FROM PUBLIC;

GRANT EXECUTE ON FUNCTION is_org_member TO authenticated;
GRANT EXECUTE ON FUNCTION is_org_admin TO authenticated;
-- Note: get_* functions are granted to authenticated because RLS policies
-- use them in USING clauses (e.g., is_org_member(get_project_org_id(...))).
-- The caller (authenticated user) must have EXECUTE privilege on all functions
-- invoked within the policy expression. These functions are read-only and
-- only return organization IDs that the user would already see via RLS.
GRANT EXECUTE ON FUNCTION get_project_org_id TO authenticated;
GRANT EXECUTE ON FUNCTION get_contract_org_id TO authenticated;
GRANT EXECUTE ON FUNCTION get_asset_org_id TO authenticated;
GRANT EXECUTE ON FUNCTION get_meter_org_id TO authenticated;

GRANT EXECUTE ON FUNCTION is_org_member TO service_role;
GRANT EXECUTE ON FUNCTION is_org_admin TO service_role;
GRANT EXECUTE ON FUNCTION get_project_org_id TO service_role;
GRANT EXECUTE ON FUNCTION get_contract_org_id TO service_role;
GRANT EXECUTE ON FUNCTION get_asset_org_id TO service_role;
GRANT EXECUTE ON FUNCTION get_meter_org_id TO service_role;

-- ============================================================================
-- ORGANIZATION TABLE
-- ============================================================================

-- Enable RLS on organization table
ALTER TABLE organization ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own organization
DROP POLICY IF EXISTS organization_select_policy ON organization;
CREATE POLICY organization_select_policy ON organization
    FOR SELECT
    TO authenticated
    USING (is_org_member(organization.id));

-- Policy: Service role can access all organizations
DROP POLICY IF EXISTS organization_service_policy ON organization;
CREATE POLICY organization_service_policy ON organization
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- PROJECT TABLE
-- ============================================================================

-- Enable RLS on project table
ALTER TABLE project ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see projects from their organization
DROP POLICY IF EXISTS project_org_policy ON project;
CREATE POLICY project_org_policy ON project
    FOR SELECT
    TO authenticated
    USING (is_org_member(project.organization_id));

-- Policy: Admins can insert/update projects in their organization
DROP POLICY IF EXISTS project_admin_modify_policy ON project;
CREATE POLICY project_admin_modify_policy ON project
    FOR ALL
    TO authenticated
    USING (is_org_admin(project.organization_id))
    WITH CHECK (is_org_admin(project.organization_id));

-- Policy: Service role can access all projects
DROP POLICY IF EXISTS project_service_policy ON project;
CREATE POLICY project_service_policy ON project
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- CONTRACT TABLE
-- ============================================================================

-- Enable RLS on contract table
ALTER TABLE contract ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see contracts from their organization (via project)
DROP POLICY IF EXISTS contract_org_policy ON contract;
CREATE POLICY contract_org_policy ON contract
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_project_org_id(contract.project_id)));

-- Policy: Admins can modify contracts in their organization
DROP POLICY IF EXISTS contract_admin_modify_policy ON contract;
CREATE POLICY contract_admin_modify_policy ON contract
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_project_org_id(contract.project_id)))
    WITH CHECK (is_org_admin(get_project_org_id(contract.project_id)));

-- Policy: Service role can access all contracts
DROP POLICY IF EXISTS contract_service_policy ON contract;
CREATE POLICY contract_service_policy ON contract
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- CLAUSE TABLE
-- ============================================================================

-- Enable RLS on clause table
ALTER TABLE clause ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see clauses from contracts in their organization
DROP POLICY IF EXISTS clause_org_policy ON clause;
CREATE POLICY clause_org_policy ON clause
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_contract_org_id(clause.contract_id)));

-- Policy: Admins can modify clauses in their organization
DROP POLICY IF EXISTS clause_admin_modify_policy ON clause;
CREATE POLICY clause_admin_modify_policy ON clause
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_contract_org_id(clause.contract_id)))
    WITH CHECK (is_org_admin(get_contract_org_id(clause.contract_id)));

-- Policy: Service role can access all clauses
DROP POLICY IF EXISTS clause_service_policy ON clause;
CREATE POLICY clause_service_policy ON clause
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- EVENT TABLE
-- ============================================================================

-- Enable RLS on event table
ALTER TABLE event ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see events in their organization
DROP POLICY IF EXISTS event_org_policy ON event;
CREATE POLICY event_org_policy ON event
    FOR SELECT
    TO authenticated
    USING (is_org_member(event.organization_id));

-- Policy: Admins can modify events in their organization
DROP POLICY IF EXISTS event_admin_modify_policy ON event;
CREATE POLICY event_admin_modify_policy ON event
    FOR ALL
    TO authenticated
    USING (is_org_admin(event.organization_id))
    WITH CHECK (is_org_admin(event.organization_id));

-- Policy: Service role can access all events
DROP POLICY IF EXISTS event_service_policy ON event;
CREATE POLICY event_service_policy ON event
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- DEFAULT_EVENT TABLE
-- ============================================================================

-- Enable RLS on default_event table
ALTER TABLE default_event ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see default_events from contracts in their organization
DROP POLICY IF EXISTS default_event_org_policy ON default_event;
CREATE POLICY default_event_org_policy ON default_event
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_contract_org_id(default_event.contract_id)));

-- Policy: Admins can modify default_events in their organization
DROP POLICY IF EXISTS default_event_admin_modify_policy ON default_event;
CREATE POLICY default_event_admin_modify_policy ON default_event
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_contract_org_id(default_event.contract_id)))
    WITH CHECK (is_org_admin(get_contract_org_id(default_event.contract_id)));

-- Policy: Service role can access all default_events
DROP POLICY IF EXISTS default_event_service_policy ON default_event;
CREATE POLICY default_event_service_policy ON default_event
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- COUNTERPARTY TABLE
-- ============================================================================

-- Enable RLS on counterparty table
ALTER TABLE counterparty ENABLE ROW LEVEL SECURITY;

-- Policy: Users can see counterparties linked to contracts in their organization
DROP POLICY IF EXISTS counterparty_org_policy ON counterparty;
CREATE POLICY counterparty_org_policy ON counterparty
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM contract c
            WHERE c.counterparty_id = counterparty.id
            AND is_org_member(c.organization_id)
        )
    );

-- Policy: Admins can modify counterparties linked to contracts in their organization
DROP POLICY IF EXISTS counterparty_admin_modify_policy ON counterparty;
CREATE POLICY counterparty_admin_modify_policy ON counterparty
    FOR ALL
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM contract c
            WHERE c.counterparty_id = counterparty.id
            AND is_org_admin(c.organization_id)
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM contract c
            WHERE c.counterparty_id = counterparty.id
            AND is_org_admin(c.organization_id)
        )
    );

-- Policy: Service role can access all counterparties
DROP POLICY IF EXISTS counterparty_service_policy ON counterparty;
CREATE POLICY counterparty_service_policy ON counterparty
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- INVOICE TABLES (Financial Data - High Sensitivity)
-- ============================================================================

-- Enable RLS on invoice_header
ALTER TABLE invoice_header ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS invoice_header_org_policy ON invoice_header;
CREATE POLICY invoice_header_org_policy ON invoice_header
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_contract_org_id(invoice_header.contract_id)));

DROP POLICY IF EXISTS invoice_header_admin_modify_policy ON invoice_header;
CREATE POLICY invoice_header_admin_modify_policy ON invoice_header
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_contract_org_id(invoice_header.contract_id)))
    WITH CHECK (is_org_admin(get_contract_org_id(invoice_header.contract_id)));

DROP POLICY IF EXISTS invoice_header_service_policy ON invoice_header;
CREATE POLICY invoice_header_service_policy ON invoice_header
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- Enable RLS on received_invoice_header
ALTER TABLE received_invoice_header ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS received_invoice_header_org_policy ON received_invoice_header;
CREATE POLICY received_invoice_header_org_policy ON received_invoice_header
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_contract_org_id(received_invoice_header.contract_id)));

DROP POLICY IF EXISTS received_invoice_header_admin_modify_policy ON received_invoice_header;
CREATE POLICY received_invoice_header_admin_modify_policy ON received_invoice_header
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_contract_org_id(received_invoice_header.contract_id)))
    WITH CHECK (is_org_admin(get_contract_org_id(received_invoice_header.contract_id)));

DROP POLICY IF EXISTS received_invoice_header_service_policy ON received_invoice_header;
CREATE POLICY received_invoice_header_service_policy ON received_invoice_header
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- ASSET AND METER TABLES (Operational Data)
-- ============================================================================

-- Enable RLS on asset
ALTER TABLE asset ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS asset_org_policy ON asset;
CREATE POLICY asset_org_policy ON asset
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_project_org_id(asset.project_id)));

DROP POLICY IF EXISTS asset_admin_modify_policy ON asset;
CREATE POLICY asset_admin_modify_policy ON asset
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_project_org_id(asset.project_id)))
    WITH CHECK (is_org_admin(get_project_org_id(asset.project_id)));

DROP POLICY IF EXISTS asset_service_policy ON asset;
CREATE POLICY asset_service_policy ON asset
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- Enable RLS on meter
ALTER TABLE meter ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meter_org_policy ON meter;
CREATE POLICY meter_org_policy ON meter
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_asset_org_id(meter.asset_id)));

DROP POLICY IF EXISTS meter_admin_modify_policy ON meter;
CREATE POLICY meter_admin_modify_policy ON meter
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_asset_org_id(meter.asset_id)))
    WITH CHECK (is_org_admin(get_asset_org_id(meter.asset_id)));

DROP POLICY IF EXISTS meter_service_policy ON meter;
CREATE POLICY meter_service_policy ON meter
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- Enable RLS on meter_reading
ALTER TABLE meter_reading ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meter_reading_org_policy ON meter_reading;
CREATE POLICY meter_reading_org_policy ON meter_reading
    FOR SELECT
    TO authenticated
    USING (is_org_member(get_meter_org_id(meter_reading.meter_id)));

DROP POLICY IF EXISTS meter_reading_admin_modify_policy ON meter_reading;
CREATE POLICY meter_reading_admin_modify_policy ON meter_reading
    FOR ALL
    TO authenticated
    USING (is_org_admin(get_meter_org_id(meter_reading.meter_id)))
    WITH CHECK (is_org_admin(get_meter_org_id(meter_reading.meter_id)));

DROP POLICY IF EXISTS meter_reading_service_policy ON meter_reading;
CREATE POLICY meter_reading_service_policy ON meter_reading
    FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ============================================================================
-- SUPPORTING INDEXES FOR RLS PERFORMANCE
-- ============================================================================
-- These indexes optimize the helper function lookups and policy checks

-- Role table indexes (most frequently queried in RLS checks)
CREATE INDEX IF NOT EXISTS idx_role_user_org_active
    ON public.role (user_id, organization_id, is_active);
CREATE INDEX IF NOT EXISTS idx_role_admin_check
    ON public.role (user_id, organization_id, role_type, is_active)
    WHERE role_type = 'admin' AND is_active = TRUE;

-- Note: idx_project_id_org removed - redundant because 'id' is the PRIMARY KEY
-- The PK index handles lookups by id, and get_project_org_id only needs id lookup
DROP INDEX IF EXISTS idx_project_id_org;

-- Contract lookup index (for get_contract_org_id)
CREATE INDEX IF NOT EXISTS idx_contract_project
    ON public.contract (project_id);

-- Asset lookup index (for get_asset_org_id)
CREATE INDEX IF NOT EXISTS idx_asset_project
    ON public.asset (project_id);

-- Meter lookup index (for get_meter_org_id)
CREATE INDEX IF NOT EXISTS idx_meter_asset
    ON public.meter (asset_id);

-- ============================================================================
-- COMMENTS
-- ============================================================================

-- Helper function comments
COMMENT ON FUNCTION is_org_member IS 'Check if current user is a member of the specified organization';
COMMENT ON FUNCTION is_org_admin IS 'Check if current user is an admin of the specified organization';
COMMENT ON FUNCTION get_project_org_id IS 'Get organization_id for a project';
COMMENT ON FUNCTION get_contract_org_id IS 'Get organization_id for a contract (via project)';
COMMENT ON FUNCTION get_asset_org_id IS 'Get organization_id for an asset (via project)';
COMMENT ON FUNCTION get_meter_org_id IS 'Get organization_id for a meter (via asset -> project)';

-- Policy comments
COMMENT ON POLICY organization_select_policy ON organization IS 'Users can only see their own organization';
COMMENT ON POLICY project_org_policy ON project IS 'Users can only see projects from their organization';
COMMENT ON POLICY contract_org_policy ON contract IS 'Users can only see contracts from their organization via project';
COMMENT ON POLICY clause_org_policy ON clause IS 'Users can only see clauses from contracts in their organization';
COMMENT ON POLICY event_org_policy ON event IS 'Users can only see events from contracts in their organization';
COMMENT ON POLICY counterparty_org_policy ON counterparty IS 'Users can only see counterparties from their organization';
