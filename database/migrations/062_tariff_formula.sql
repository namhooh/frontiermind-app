-- =============================================================================
-- Migration 062: Tariff Formula Table
-- =============================================================================
-- Stores decomposed mathematical formulas from PPA/SSA pricing sections
-- as structured computation graphs, linked to the clause_tariff they parameterize.
-- Populated by Step 11P (Pricing & Tariff Extraction).
--
-- formula_type is VARCHAR (not ENUM) — new types can be added without a
-- migration. Validation is enforced at the Pydantic model layer.
--
-- Formula type taxonomy (14 types across 5 categories):
--   pricing:     MRP_BOUNDED, MRP_CALCULATION
--   escalation:  PERCENTAGE_ESCALATION, FIXED_ESCALATION, CPI_ESCALATION, FLOOR_CEILING_ESCALATION
--   energy:      ENERGY_OUTPUT, DEEMED_ENERGY, ENERGY_DEGRADATION, ENERGY_GUARANTEE, ENERGY_MULTIPHASE
--   performance: SHORTFALL_PAYMENT, TAKE_OR_PAY
--   billing:     FX_CONVERSION
-- =============================================================================

BEGIN;

-- =============================================================================
-- Phase 1: Create tariff_formula table
-- =============================================================================

CREATE TABLE IF NOT EXISTS tariff_formula (
    id                    BIGSERIAL PRIMARY KEY,
    clause_tariff_id      BIGINT NOT NULL REFERENCES clause_tariff(id) ON DELETE CASCADE,
    organization_id       BIGINT NOT NULL REFERENCES organization(id),

    -- Formula identity
    formula_name          VARCHAR(255) NOT NULL,       -- Human-readable name
    formula_text          TEXT NOT NULL,                -- Mathematical expression as text
    formula_type          VARCHAR(50) NOT NULL,        -- e.g. 'MRP_BOUNDED', 'CPI_ESCALATION', 'ENERGY_OUTPUT'

    -- Structured decomposition
    variables             JSONB NOT NULL DEFAULT '[]', -- Array of {symbol, role, variable_type, description, unit, maps_to}
    operations            JSONB NOT NULL DEFAULT '[]', -- Array of operations: MIN, MAX, MULTIPLY, IF, SUM, etc.
    conditions            JSONB DEFAULT '[]',          -- Array of {type, description, threshold_value, threshold_unit, if_above, then, else}

    -- Provenance
    section_ref           VARCHAR(255),                -- e.g. 'Annexure C, Clause 3.2'
    extraction_confidence NUMERIC(3,2),                -- 0.00 to 1.00
    extraction_metadata   JSONB DEFAULT '{}',          -- Raw extraction context

    -- Versioning
    version               INTEGER NOT NULL DEFAULT 1,
    is_current            BOOLEAN NOT NULL DEFAULT true,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Lookup by clause_tariff
CREATE INDEX IF NOT EXISTS idx_tariff_formula_clause_tariff
    ON tariff_formula (clause_tariff_id);

-- Lookup by organization
CREATE INDEX IF NOT EXISTS idx_tariff_formula_org
    ON tariff_formula (organization_id);

-- Lookup by formula_type
CREATE INDEX IF NOT EXISTS idx_tariff_formula_type
    ON tariff_formula (formula_type);

COMMIT;
