-- Migration 028: Customer Contact Table
-- Date: 2026-02-14
-- Phase: 7.0 - CBE Schema Design Review
--
-- Changes:
--   1. New table: customer_contact (1:many from counterparty)
--   2. Supports multiple contacts per counterparty with role, email, invoice/escalation flags
--   3. Organization-scoped for multi-tenant isolation

-- =============================================================================
-- 1. Customer Contact Table
-- =============================================================================
-- Each counterparty can have multiple contacts (accounting, CFO, operations, etc.)
-- Contact count varies per counterparty — separate table avoids anti-pattern of
-- flattened contact_1_name, contact_2_name columns.

CREATE TABLE IF NOT EXISTS customer_contact (
  id                       BIGSERIAL PRIMARY KEY,
  counterparty_id          BIGINT NOT NULL REFERENCES counterparty(id) ON DELETE CASCADE,
  organization_id          BIGINT NOT NULL REFERENCES organization(id),
  role                     VARCHAR(100),
  full_name                VARCHAR(255),
  email                    VARCHAR(255),
  phone                    VARCHAR(50),
  include_in_invoice_email BOOLEAN DEFAULT false,
  escalation_only          BOOLEAN DEFAULT false,
  is_active                BOOLEAN DEFAULT true,
  source_metadata          JSONB DEFAULT '{}',
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customer_contact_counterparty
  ON customer_contact(counterparty_id);

CREATE INDEX IF NOT EXISTS idx_customer_contact_org
  ON customer_contact(organization_id);

CREATE INDEX IF NOT EXISTS idx_customer_contact_invoice_email
  ON customer_contact(counterparty_id)
  WHERE include_in_invoice_email = true AND is_active = true;

COMMENT ON TABLE customer_contact IS 'Contacts associated with a counterparty. Multiple contacts per counterparty with role-based flags.';
COMMENT ON COLUMN customer_contact.role IS 'Contact role: accounting, cfo, financial_manager, general_manager, operations_manager, etc.';
COMMENT ON COLUMN customer_contact.include_in_invoice_email IS 'Whether this contact should receive invoice emails.';
COMMENT ON COLUMN customer_contact.escalation_only IS 'Whether this contact should only be contacted for escalations.';
COMMENT ON COLUMN customer_contact.source_metadata IS 'Client-specific contact metadata (e.g., CBE contact_type code, Sage contact_id).';

-- =============================================================================
-- 2. RLS Policies
-- =============================================================================

ALTER TABLE customer_contact ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_contact_org_policy ON customer_contact;
CREATE POLICY customer_contact_org_policy ON customer_contact
  FOR SELECT
  USING (is_org_member(organization_id));

DROP POLICY IF EXISTS customer_contact_admin_modify_policy ON customer_contact;
CREATE POLICY customer_contact_admin_modify_policy ON customer_contact
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS customer_contact_service_policy ON customer_contact;
CREATE POLICY customer_contact_service_policy ON customer_contact
  FOR ALL
  USING (auth.role() = 'service_role');
