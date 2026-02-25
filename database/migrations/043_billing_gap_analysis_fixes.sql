-- Migration 043: Billing Engine Gap Analysis Fixes
--
-- Tighten billing_tax_rule RLS (F15)
--   Replace overly permissive USING(true) with org-scoped policy.
--   Service-role (backend) bypasses RLS entirely.

BEGIN;

-- ============================================================================
-- billing_tax_rule RLS — org-scoped
-- ============================================================================

DROP POLICY IF EXISTS billing_tax_rule_org_read ON billing_tax_rule;

CREATE POLICY billing_tax_rule_org_read ON billing_tax_rule
  FOR SELECT
  USING (
    -- Global/shared rules visible to all
    organization_id IS NULL
    OR
    -- Org-scoped rules visible only to members of that org
    organization_id IN (
      SELECT r.organization_id
      FROM role r
      WHERE r.user_id = auth.uid()
        AND r.is_active = true
    )
  );

COMMIT;
