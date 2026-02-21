-- Migration 027: Tariff Classification Lookup Tables
-- Date: 2026-02-14
-- Phase: 7.0 - CBE Schema Design Review
--
-- Changes:
--   1. New table: tariff_structure_type (FIXED, GRID, GENERATOR) — org-scoped
--   2. New table: energy_sale_type (FIXED_SOLAR, FLOATING_GRID, etc.) — org-scoped
--   3. New table: escalation_type (FIXED_INCREASE, PERCENTAGE, US_CPI, etc.) — org-scoped
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
-- 2. Energy Sale Type (FIXED_SOLAR / FLOATING_GRID / FLOATING_GENERATOR / etc.)
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
-- 3. Escalation Type (FIXED_INCREASE / PERCENTAGE / US_CPI / REBASED_MARKET_PRICE / NONE)
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
-- Aligned with Excel onboarding template dropdown menu.
INSERT INTO energy_sale_type (code, name, description, organization_id) VALUES
  ('FIXED_SOLAR', 'Fixed Solar Tariff', 'Fixed contractual solar energy rate', NULL),
  ('FLOATING_GRID', 'Floating Grid Tariff (discounted)', 'Rate derived from utility grid tariff with discount', NULL),
  ('FLOATING_GENERATOR', 'Floating Generator Tariff (discounted)', 'Rate derived from diesel/gas generator cost with discount', NULL),
  ('FLOATING_GRID_GENERATOR', 'Floating Grid + Generator Tariff (discounted)', 'Rate derived from combined grid and generator baseline with discount', NULL),
  ('NOT_ENERGY_SALES', 'N/A - not Energy Sales Contract', 'Contract is not an energy sales arrangement (e.g. lease, O&M)', NULL)
ON CONFLICT (code, organization_id) DO NOTHING;

-- Escalation Types
-- Aligned with Excel onboarding template dropdown menu.
INSERT INTO escalation_type (code, name, description, organization_id) VALUES
  ('FIXED_INCREASE', 'Fixed Amount Increase', 'Rate increases by a fixed amount annually', NULL),
  ('FIXED_DECREASE', 'Fixed Amount Decrease', 'Rate decreases by a fixed amount annually', NULL),
  ('PERCENTAGE', 'Percentage', 'Rate escalates by a percentage annually', NULL),
  ('US_CPI', 'US CPI', 'Rate escalates linked to US Consumer Price Index', NULL),
  ('REBASED_MARKET_PRICE', 'Rebased Market Price', 'Rate rebased periodically to market reference price', NULL),
  ('NONE', 'No adjustment - Fixed Price', 'Rate remains constant throughout contract term', NULL)
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
COMMENT ON COLUMN clause_tariff.energy_sale_type_id IS 'Energy sale arrangement: FIXED_SOLAR, FLOATING_GRID, FLOATING_GENERATOR, etc.';
COMMENT ON COLUMN clause_tariff.escalation_type_id IS 'How the tariff rate escalates over time: FIXED_INCREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE, NONE.';
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
