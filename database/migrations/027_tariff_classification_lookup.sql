-- Migration 027: Tariff Classification Lookup Tables
-- Date: 2026-02-14
-- Phase: 7.0 - CBE Schema Design Review
--
-- Changes:
--   1. New table: tariff_structure_type (FIXED, GRID, GENERATOR) — org-scoped
--   2. New table: energy_sale_type (TAKE_OR_PAY, MIN_OFFTAKE, etc.) — org-scoped
--   3. New table: escalation_type (FIXED, CPI, CUSTOM, etc.) — org-scoped
--   4. Extend clause_tariff: tariff_structure_id, energy_sale_type_id, escalation_type_id, market_ref_currency_id
--   5. Seed platform-level canonical types (organization_id = NULL)

-- =============================================================================
-- 1. Tariff Structure Type (FIXED / GRID / GENERATOR)
-- =============================================================================
-- Describes the pricing structure basis for a tariff line.
-- organization_id = NULL → platform-level canonical type
-- organization_id = <org> → client-specific subtype or override

CREATE TABLE IF NOT EXISTS tariff_structure_type (
  id              BIGSERIAL PRIMARY KEY,
  code            VARCHAR(50) NOT NULL,
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  organization_id BIGINT REFERENCES organization(id),
  is_active       BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(code, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_tariff_structure_type_org
  ON tariff_structure_type(organization_id);

COMMENT ON TABLE tariff_structure_type IS 'Pricing structure basis for tariff lines (FIXED, GRID, GENERATOR). NULL organization_id = platform canonical type.';
COMMENT ON COLUMN tariff_structure_type.organization_id IS 'NULL = platform-level canonical type. Non-NULL = client-specific subtype.';

-- =============================================================================
-- 2. Energy Sale Type (TAKE_OR_PAY / MIN_OFFTAKE / FULL_OFFTAKE / etc.)
-- =============================================================================
-- Describes the energy sale/offtake arrangement for a tariff line.

CREATE TABLE IF NOT EXISTS energy_sale_type (
  id              BIGSERIAL PRIMARY KEY,
  code            VARCHAR(50) NOT NULL,
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  organization_id BIGINT REFERENCES organization(id),
  is_active       BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(code, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_energy_sale_type_org
  ON energy_sale_type(organization_id);

COMMENT ON TABLE energy_sale_type IS 'Energy sale/offtake arrangement types. NULL organization_id = platform canonical type.';

-- =============================================================================
-- 3. Escalation Type (FIXED / CPI / CUSTOM / NONE)
-- =============================================================================
-- Describes how the tariff rate escalates over time.

CREATE TABLE IF NOT EXISTS escalation_type (
  id              BIGSERIAL PRIMARY KEY,
  code            VARCHAR(50) NOT NULL,
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  organization_id BIGINT REFERENCES organization(id),
  is_active       BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(code, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_escalation_type_org
  ON escalation_type(organization_id);

COMMENT ON TABLE escalation_type IS 'Tariff rate escalation methods. NULL organization_id = platform canonical type.';

-- =============================================================================
-- 4. Seed Platform-Level Canonical Types (organization_id = NULL)
-- =============================================================================

-- Tariff Structure Types
INSERT INTO tariff_structure_type (code, name, description, organization_id) VALUES
  ('FIXED', 'Fixed Rate', 'Fixed contractual rate, not linked to external reference price', NULL),
  ('GRID', 'Grid-Referenced', 'Rate derived from utility grid tariff (discount-to-grid model)', NULL),
  ('GENERATOR', 'Generator-Referenced', 'Rate derived from diesel/gas generator cost baseline', NULL)
ON CONFLICT (code, organization_id) DO NOTHING;

-- Energy Sale Types
-- Four canonical types aligned with CBE portfolio contracts.
-- FULL_OFFTAKE, AS_PRODUCED, DEEMED were removed — they had no contract mappings
-- and overlapped with TAKE_OR_PAY or belonged at the invoice line item level.
INSERT INTO energy_sale_type (code, name, description, organization_id) VALUES
  ('TAKE_OR_PAY', 'Take-or-Pay', 'Customer pays for minimum contracted volume regardless of actual consumption', NULL),
  ('MIN_OFFTAKE', 'Minimum Offtake', 'Customer must consume minimum percentage of production; shortfall deferred or billed', NULL),
  ('TAKE_AND_PAY', 'Take-and-Pay', 'Customer pays only for energy actually consumed (metered only, no availability component)', NULL),
  ('LEASE', 'Lease', 'Fixed equipment rental — billing is not energy-based', NULL)
ON CONFLICT (code, organization_id) DO NOTHING;

-- Escalation Types
INSERT INTO escalation_type (code, name, description, organization_id) VALUES
  ('FIXED', 'Fixed Escalation', 'Rate escalates by a fixed percentage annually', NULL),
  ('CPI', 'CPI-Linked', 'Rate escalates linked to Consumer Price Index', NULL),
  ('CUSTOM', 'Custom Formula', 'Rate escalation follows a client-specific formula', NULL),
  ('NONE', 'No Escalation', 'Rate remains constant throughout contract term', NULL),
  ('GRID_PASSTHROUGH', 'Grid Passthrough', 'Rate follows grid tariff changes with fixed discount maintained', NULL)
ON CONFLICT (code, organization_id) DO NOTHING;

-- =============================================================================
-- 5. Extend clause_tariff with Classification FKs
-- =============================================================================

ALTER TABLE clause_tariff
  ADD COLUMN IF NOT EXISTS tariff_structure_id  BIGINT REFERENCES tariff_structure_type(id),
  ADD COLUMN IF NOT EXISTS energy_sale_type_id  BIGINT REFERENCES energy_sale_type(id),
  ADD COLUMN IF NOT EXISTS escalation_type_id   BIGINT REFERENCES escalation_type(id),
  ADD COLUMN IF NOT EXISTS market_ref_currency_id BIGINT REFERENCES currency(id);

CREATE INDEX IF NOT EXISTS idx_clause_tariff_structure
  ON clause_tariff(tariff_structure_id);

CREATE INDEX IF NOT EXISTS idx_clause_tariff_energy_sale
  ON clause_tariff(energy_sale_type_id);

CREATE INDEX IF NOT EXISTS idx_clause_tariff_escalation
  ON clause_tariff(escalation_type_id);

COMMENT ON COLUMN clause_tariff.tariff_structure_id IS 'Pricing structure basis: FIXED, GRID-referenced, or GENERATOR-referenced.';
COMMENT ON COLUMN clause_tariff.energy_sale_type_id IS 'Energy sale arrangement: TAKE_OR_PAY, MIN_OFFTAKE, FULL_OFFTAKE, etc.';
COMMENT ON COLUMN clause_tariff.escalation_type_id IS 'How the tariff rate escalates over time: FIXED %, CPI-linked, CUSTOM formula, etc.';
COMMENT ON COLUMN clause_tariff.market_ref_currency_id IS 'Currency of the Market Reference Price (MRP). May differ from billing currency (clause_tariff.currency_id).';

-- =============================================================================
-- 6. RLS Policies for Lookup Tables
-- =============================================================================
-- Platform-level rows (organization_id IS NULL) are visible to all authenticated users.
-- Org-scoped rows are visible to org members.

ALTER TABLE tariff_structure_type ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tariff_structure_type_select_policy ON tariff_structure_type;
CREATE POLICY tariff_structure_type_select_policy ON tariff_structure_type
  FOR SELECT
  USING (organization_id IS NULL OR is_org_member(organization_id));

DROP POLICY IF EXISTS tariff_structure_type_admin_modify_policy ON tariff_structure_type;
CREATE POLICY tariff_structure_type_admin_modify_policy ON tariff_structure_type
  FOR ALL
  USING (organization_id IS NOT NULL AND is_org_admin(organization_id));

DROP POLICY IF EXISTS tariff_structure_type_service_policy ON tariff_structure_type;
CREATE POLICY tariff_structure_type_service_policy ON tariff_structure_type
  FOR ALL
  USING (auth.role() = 'service_role');

ALTER TABLE energy_sale_type ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS energy_sale_type_select_policy ON energy_sale_type;
CREATE POLICY energy_sale_type_select_policy ON energy_sale_type
  FOR SELECT
  USING (organization_id IS NULL OR is_org_member(organization_id));

DROP POLICY IF EXISTS energy_sale_type_admin_modify_policy ON energy_sale_type;
CREATE POLICY energy_sale_type_admin_modify_policy ON energy_sale_type
  FOR ALL
  USING (organization_id IS NOT NULL AND is_org_admin(organization_id));

DROP POLICY IF EXISTS energy_sale_type_service_policy ON energy_sale_type;
CREATE POLICY energy_sale_type_service_policy ON energy_sale_type
  FOR ALL
  USING (auth.role() = 'service_role');

ALTER TABLE escalation_type ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS escalation_type_select_policy ON escalation_type;
CREATE POLICY escalation_type_select_policy ON escalation_type
  FOR SELECT
  USING (organization_id IS NULL OR is_org_member(organization_id));

DROP POLICY IF EXISTS escalation_type_admin_modify_policy ON escalation_type;
CREATE POLICY escalation_type_admin_modify_policy ON escalation_type
  FOR ALL
  USING (organization_id IS NOT NULL AND is_org_admin(organization_id));

DROP POLICY IF EXISTS escalation_type_service_policy ON escalation_type;
CREATE POLICY escalation_type_service_policy ON escalation_type
  FOR ALL
  USING (auth.role() = 'service_role');
