-- =============================================================================
-- Migration 041: Multi-Meter Billing & Plant Performance
-- =============================================================================
-- Date: 2026-02-23
--
-- Adds:
--   1. meter.name column for human-readable meter names
--   2. contract_line table — links contracts to specific meters and billing products
--   3. meter_aggregate enhancements — available_energy_kwh, contract_line_id, irradiance
--   4. plant_performance table — monthly project-level performance analysis
--   5. Billing dedup index fix — adds meter_id + contract_line_id to dedup key
--   6. contract_line.external_line_id unique index for bulk FK lookup
--   7. Backfill external_line_id on MOH01 contract_line seed rows
--   8. Clarify irradiance unit comments (Wh/m² stored, kWh/m² in forecast)
--
-- Seeds:
--   - MOH01 contract_line rows (contract_id=7, 8 lines)
--   - MOH01 meter names (PPL1, PPL2, Bottles, BBM1, BBM2)
--   - MOH01 external_line_ids (CONZIM00-2025-00002-{line_number})
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1A. Add `name` column to `meter` table
-- =============================================================================

ALTER TABLE meter ADD COLUMN IF NOT EXISTS name VARCHAR(100);

COMMENT ON COLUMN meter.name IS 'Human-readable meter name (e.g. PPL1, BBM2)';

-- =============================================================================
-- 1B. New `contract_line` table
-- =============================================================================

DO $$ BEGIN
  CREATE TYPE energy_category AS ENUM ('metered', 'available', 'test');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS contract_line (
    id                    BIGSERIAL PRIMARY KEY,
    contract_id           BIGINT NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    billing_product_id    BIGINT REFERENCES billing_product(id),
    meter_id              BIGINT REFERENCES meter(id),
    contract_line_number  INTEGER NOT NULL,
    product_desc          VARCHAR(255),
    energy_category       energy_category NOT NULL DEFAULT 'metered',
    effective_start_date  DATE,
    effective_end_date    DATE,
    is_active             BOOLEAN DEFAULT true,
    organization_id       BIGINT NOT NULL REFERENCES organization(id),
    external_line_id      VARCHAR(100),
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(contract_id, contract_line_number)
);

COMMENT ON TABLE contract_line IS 'Links a contract to specific meters and energy product categories. Bridge between CBE Snowflake data and billing engine.';
COMMENT ON COLUMN contract_line.contract_line_number IS 'CBE line code: 1000, 4000, etc.';
COMMENT ON COLUMN contract_line.energy_category IS 'metered = generation, available = curtailed/available energy, test = test energy';
COMMENT ON COLUMN contract_line.external_line_id IS 'CBE CONTRACT_LINE_UNIQUE_ID';

-- =============================================================================
-- 1C. Enhance `meter_aggregate` table
-- =============================================================================

ALTER TABLE meter_aggregate
  ADD COLUMN IF NOT EXISTS available_energy_kwh DECIMAL,
  ADD COLUMN IF NOT EXISTS contract_line_id BIGINT REFERENCES contract_line(id),
  ADD COLUMN IF NOT EXISTS ghi_irradiance_wm2 DECIMAL,
  ADD COLUMN IF NOT EXISTS poa_irradiance_wm2 DECIMAL;

COMMENT ON COLUMN meter_aggregate.available_energy_kwh IS 'Available Energy per meter per month (kWh). Total Available = SUM across all meters.';
COMMENT ON COLUMN meter_aggregate.contract_line_id IS 'Links this aggregate to a specific billable contract line';
-- Irradiance unit comments: meter_aggregate stores Wh/m² (monthly cumulative).
-- production_forecast stores kWh/m² (standard PVSyst output).
-- The Performance API must convert Wh/m² → kWh/m² (÷1000) before comparison.
COMMENT ON COLUMN meter_aggregate.ghi_irradiance_wm2 IS
    'Monthly GHI irradiance in Wh/m² (cumulative). Divide by 1000 to get kWh/m² for forecast comparison.';
COMMENT ON COLUMN meter_aggregate.poa_irradiance_wm2 IS
    'Monthly POA irradiance in Wh/m² (cumulative). Divide by 1000 to get kWh/m² for forecast comparison.';

-- =============================================================================
-- 1D. New `plant_performance` table
-- =============================================================================

CREATE TABLE IF NOT EXISTS plant_performance (
    id                        BIGSERIAL PRIMARY KEY,
    project_id                BIGINT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    organization_id           BIGINT NOT NULL REFERENCES organization(id),
    production_forecast_id    BIGINT REFERENCES production_forecast(id),
    billing_period_id         BIGINT REFERENCES billing_period(id),
    billing_month             DATE NOT NULL,
    operating_year            INTEGER,
    -- Performance metrics (computed from meter_aggregate + production_forecast)
    actual_pr                 DECIMAL(5,4),
    actual_availability_pct   DECIMAL(5,2),
    -- Comparison ratios (actual / forecast)
    energy_comparison         DECIMAL(6,4),
    irr_comparison            DECIMAL(6,4),
    pr_comparison             DECIMAL(6,4),
    -- Metadata
    comments                  TEXT,
    created_at                TIMESTAMPTZ DEFAULT NOW(),
    updated_at                TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, billing_month)
);

COMMENT ON TABLE plant_performance IS 'Monthly project-level performance analysis. Raw data lives in meter_aggregate and production_forecast; this stores only derived metrics.';
COMMENT ON COLUMN plant_performance.actual_pr IS 'Performance Ratio = total_energy * 1000 / (actual_ghi * capacity)';
COMMENT ON COLUMN plant_performance.actual_availability_pct IS 'System availability percentage';
COMMENT ON COLUMN plant_performance.energy_comparison IS 'Ratio: total actual energy / forecast energy';
COMMENT ON COLUMN plant_performance.irr_comparison IS 'Ratio: actual GHI / forecast GHI';
COMMENT ON COLUMN plant_performance.pr_comparison IS 'Ratio: actual PR / forecast PR';

-- =============================================================================
-- 1E. Indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_contract_line_contract_id ON contract_line(contract_id);
CREATE INDEX IF NOT EXISTS idx_contract_line_meter_id ON contract_line(meter_id);
CREATE INDEX IF NOT EXISTS idx_meter_aggregate_contract_line_id ON meter_aggregate(contract_line_id);
CREATE INDEX IF NOT EXISTS idx_plant_performance_project_month ON plant_performance(project_id, billing_month);
CREATE INDEX IF NOT EXISTS idx_plant_performance_billing_period ON plant_performance(billing_period_id);
CREATE INDEX IF NOT EXISTS idx_plant_performance_forecast ON plant_performance(production_forecast_id);

-- =============================================================================
-- 1F. Replace billing dedup index
-- =============================================================================
-- Old index (migration 026) only keyed on (org_id, billing_period_id, clause_tariff_id).
-- With multi-meter billing, different meters sharing the same tariff+period would
-- collide. The new key adds meter_id and contract_line_id.

DROP INDEX IF EXISTS idx_meter_aggregate_billing_dedup;

CREATE UNIQUE INDEX idx_meter_aggregate_billing_dedup
ON meter_aggregate (
    organization_id,
    COALESCE(meter_id, -1),
    COALESCE(billing_period_id, -1),
    COALESCE(clause_tariff_id, -1),
    COALESCE(contract_line_id, -1)
)
WHERE period_type = 'monthly';

COMMENT ON INDEX idx_meter_aggregate_billing_dedup IS
    'Dedup index for monthly billing aggregates. Prevents duplicate rows per org + meter + billing period + tariff + contract line.';

-- =============================================================================
-- 1G. Unique index on contract_line.external_line_id (per org)
-- =============================================================================
-- Enables bulk lookup by CBE CONTRACT_LINE_UNIQUE_ID during ingestion.
-- Partial index: only non-NULL external_line_ids are enforced unique per org.

CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_line_external_line_id
ON contract_line (organization_id, external_line_id)
WHERE external_line_id IS NOT NULL;

COMMENT ON INDEX uq_contract_line_external_line_id IS
    'Unique external_line_id per org. Maps CBE CONTRACT_LINE_UNIQUE_ID for bulk FK resolution.';

-- =============================================================================
-- 1H. Row-Level Security
-- =============================================================================

-- contract_line RLS
ALTER TABLE contract_line ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS contract_line_select_policy ON contract_line;
CREATE POLICY contract_line_select_policy ON contract_line
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS contract_line_insert_policy ON contract_line;
CREATE POLICY contract_line_insert_policy ON contract_line
    FOR INSERT WITH CHECK (is_org_admin(organization_id));

DROP POLICY IF EXISTS contract_line_update_policy ON contract_line;
CREATE POLICY contract_line_update_policy ON contract_line
    FOR UPDATE USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS contract_line_delete_policy ON contract_line;
CREATE POLICY contract_line_delete_policy ON contract_line
    FOR DELETE USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS contract_line_service_role_policy ON contract_line;
CREATE POLICY contract_line_service_role_policy ON contract_line
    FOR ALL USING (auth.role() = 'service_role');

-- plant_performance RLS
ALTER TABLE plant_performance ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS plant_performance_select_policy ON plant_performance;
CREATE POLICY plant_performance_select_policy ON plant_performance
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS plant_performance_insert_policy ON plant_performance;
CREATE POLICY plant_performance_insert_policy ON plant_performance
    FOR INSERT WITH CHECK (is_org_admin(organization_id));

DROP POLICY IF EXISTS plant_performance_update_policy ON plant_performance;
CREATE POLICY plant_performance_update_policy ON plant_performance
    FOR UPDATE USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS plant_performance_delete_policy ON plant_performance;
CREATE POLICY plant_performance_delete_policy ON plant_performance
    FOR DELETE USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS plant_performance_service_role_policy ON plant_performance;
CREATE POLICY plant_performance_service_role_policy ON plant_performance
    FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- 1I. Seed data — MOH01 meter names
-- =============================================================================

-- Backfill meter names (meter ids 2-6 for project_id=8, MOH01)
UPDATE meter SET name = 'PPL1' WHERE id = 2 AND name IS NULL;
UPDATE meter SET name = 'PPL2' WHERE id = 3 AND name IS NULL;
UPDATE meter SET name = 'Bottles' WHERE id = 4 AND name IS NULL;
UPDATE meter SET name = 'BBM1' WHERE id = 5 AND name IS NULL;
UPDATE meter SET name = 'BBM2' WHERE id = 6 AND name IS NULL;

-- =============================================================================
-- 1J. Seed data — MOH01 contract_line rows (contract_id=7)
-- =============================================================================
-- From dim_finance_contract_line.csv: 8 lines mapping meters to billing products.
-- contract_line_number values from CBE CONTRACT_LINE column.

INSERT INTO contract_line (contract_id, billing_product_id, meter_id, contract_line_number, product_desc, energy_category, organization_id, is_active)
VALUES
  (7, NULL, 2, 4000, 'Metered Energy (EMetered) - PPL1', 'metered', 1, true),
  (7, NULL, 3, 5000, 'Metered Energy (EMetered) - PPL2', 'metered', 1, true),
  (7, NULL, 4, 6000, 'Metered Energy (EMetered) - Bottles', 'metered', 1, true),
  (7, NULL, 5, 7000, 'Metered Energy (EMetered) - BBM1', 'metered', 1, true),
  (7, NULL, 6, 8000, 'Metered Energy (EMetered) - BBM2', 'metered', 1, true),
  (7, NULL, 2, 4001, 'Available Energy (EAvailable) - PPL1', 'available', 1, true),
  (7, NULL, 3, 5001, 'Available Energy (EAvailable) - PPL2', 'available', 1, true),
  (7, NULL, 5, 7001, 'Available Energy (EAvailable) - BBM1', 'available', 1, true)
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;

-- =============================================================================
-- 1K. Backfill external_line_id on MOH01 contract_line seed rows
-- =============================================================================
-- Values derived from CBE dim_finance_contract_line.csv:
--   CONTRACT_LINE_UNIQUE_ID = "CONZIM00-2025-00002-{contract_line_number}"
-- The tariff_group_key on clause_tariff uses the same value.

UPDATE contract_line
SET external_line_id = 'CONZIM00-2025-00002-' || contract_line_number::text
WHERE contract_id = 7
  AND external_line_id IS NULL;

COMMIT;
