-- Migration 044: Legal Entity, Counterparty Industry, and MOH01 Data Fixes
-- Date: 2026-02-26
-- Phase: 10.7 — Customer Summary Cross-Check
--
-- Changes:
--   1. New table: legal_entity (CBE entities with Sage company codes)
--   2. FK: project.legal_entity_id → legal_entity
--   3. New column: counterparty.industry
--   4. COMMENT correction: project.sage_id
--   5. Seed CBE legal entities (CBCH, EGY0, GHA0)
--   6. MOH01 data fixes: external_project_id, name, sage_id, legal_entity_id,
--      energy_sale_type (FIXED_SOLAR → FLOATING_GRID), counterparty.industry

BEGIN;

-- ============================================================================
-- 1. legal_entity table
-- ============================================================================

CREATE TABLE IF NOT EXISTS legal_entity (
  id              BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organization(id),
  name            VARCHAR(255) NOT NULL,
  external_legal_entity_id VARCHAR(50),  -- Sage company code (GHA0, CBCH, EGY0)
  country         VARCHAR(100),
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, external_legal_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_legal_entity_org ON legal_entity(organization_id);

COMMENT ON TABLE legal_entity IS 'CBE legal entities (SPVs) with Sage company codes. Each project maps to one legal entity.';
COMMENT ON COLUMN legal_entity.external_legal_entity_id IS 'Sage company code (e.g., GHA0, CBCH, EGY0).';

-- ============================================================================
-- 2. RLS policies (follow migration 027 pattern)
-- ============================================================================

ALTER TABLE legal_entity ENABLE ROW LEVEL SECURITY;

CREATE POLICY legal_entity_select_policy ON legal_entity
  FOR SELECT USING (is_org_member(organization_id));

CREATE POLICY legal_entity_admin_modify_policy ON legal_entity
  FOR ALL USING (is_org_admin(organization_id));

CREATE POLICY legal_entity_service_policy ON legal_entity
  FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- 3. FK on project → legal_entity
-- ============================================================================

ALTER TABLE project ADD COLUMN IF NOT EXISTS legal_entity_id BIGINT REFERENCES legal_entity(id);

-- ============================================================================
-- 4. counterparty.industry
-- ============================================================================

ALTER TABLE counterparty ADD COLUMN IF NOT EXISTS industry VARCHAR(100);

-- ============================================================================
-- 5. COMMENT correction on project.sage_id
-- ============================================================================

COMMENT ON COLUMN project.sage_id IS 'Sage Customer ID (e.g., MOH01, GBL01). Maps to Sage customer identifier.';

-- ============================================================================
-- 6. Seed CBE legal entities
-- ============================================================================

INSERT INTO legal_entity (organization_id, name, external_legal_entity_id, country) VALUES
  (1, 'CrossBoundary Energy Credit Holding', 'CBCH', 'Mauritius'),
  (1, 'CrossBoundary Energy Egypt For Solar Energy', 'EGY0', 'Egypt'),
  (1, 'CrossBoundary Energy Ghana Limited Company', 'GHA0', 'Ghana')
ON CONFLICT (organization_id, external_legal_entity_id) DO NOTHING;

-- ============================================================================
-- 7. MOH01 data fixes (natural key lookups, no hardcoded IDs)
-- ============================================================================

-- 7a. Project field updates
UPDATE project
SET sage_id = 'MOH01',
    external_project_id = 'GH 22015',
    name = 'Mohinani Group',
    legal_entity_id = (
      SELECT id FROM legal_entity
      WHERE external_legal_entity_id = 'GHA0' AND organization_id = 1
    )
WHERE organization_id = 1 AND external_project_id = 'MOH01';

-- 7b. Counterparty industry
UPDATE counterparty SET industry = 'Consumer Products'
WHERE name = 'Polytanks Ghana Limited';

-- 7c. Energy sale type: FIXED_SOLAR → FLOATING_GRID (code lookup)
UPDATE clause_tariff SET energy_sale_type_id = (
  SELECT id FROM energy_sale_type WHERE code = 'FLOATING_GRID'
)
WHERE project_id = (
  SELECT id FROM project WHERE organization_id = 1 AND external_project_id = 'GH 22015'
);

COMMIT;
