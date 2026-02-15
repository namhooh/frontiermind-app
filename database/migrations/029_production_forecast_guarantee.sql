-- Migration 029: Production Forecast & Production Guarantee Tables
-- Date: 2026-02-14
-- Phase: 7.0 - CBE Schema Design Review
--
-- Changes:
--   1. New table: production_forecast (monthly time-series per project)
--   2. New table: production_guarantee (annual per project)
--   3. These are project-level operational data, separate from clause/tariff
--
-- Design rationale:
--   - Forecasts are time-series data (one row per project per billing period)
--   - Guarantees are annual data (one row per project per operating year)
--   - Neither is a property of a clause/tariff — they are project-level concepts
--   - Mixing into clause logic_parameters JSONB would couple unrelated concerns

-- =============================================================================
-- 1. Production Forecast Table (Monthly)
-- =============================================================================
-- One row per project per billing period.
-- Contains forecast energy, irradiance, performance ratio, degradation.
-- Used for: variance analysis (actual vs forecast), performance monitoring.

CREATE TABLE IF NOT EXISTS production_forecast (
  id                      BIGSERIAL PRIMARY KEY,
  project_id              BIGINT NOT NULL REFERENCES project(id),
  organization_id         BIGINT NOT NULL REFERENCES organization(id),
  billing_period_id       BIGINT REFERENCES billing_period(id),
  forecast_month          DATE NOT NULL,
  operating_year          INTEGER,
  forecast_energy_kwh     DECIMAL NOT NULL,
  forecast_ghi_irradiance DECIMAL,
  forecast_pr             DECIMAL(5,4),
  degradation_factor      DECIMAL(6,5),
  forecast_source         VARCHAR(100) DEFAULT 'p50',
  source_metadata         JSONB DEFAULT '{}',
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(project_id, forecast_month)
);

CREATE INDEX IF NOT EXISTS idx_production_forecast_project
  ON production_forecast(project_id, forecast_month);

CREATE INDEX IF NOT EXISTS idx_production_forecast_org
  ON production_forecast(organization_id);

CREATE INDEX IF NOT EXISTS idx_production_forecast_period
  ON production_forecast(billing_period_id);

COMMENT ON TABLE production_forecast IS 'Monthly energy production forecasts per project. Time-series data for variance analysis and performance monitoring.';
COMMENT ON COLUMN production_forecast.forecast_month IS 'First day of the forecast month (e.g., 2026-01-01 for January 2026).';
COMMENT ON COLUMN production_forecast.operating_year IS 'Contract operating year (1-based). Year 1 = COD year.';
COMMENT ON COLUMN production_forecast.forecast_energy_kwh IS 'Forecasted energy production in kWh for this month.';
COMMENT ON COLUMN production_forecast.forecast_ghi_irradiance IS 'Forecasted Global Horizontal Irradiance (kWh/m2) for this month.';
COMMENT ON COLUMN production_forecast.forecast_pr IS 'Forecasted Performance Ratio (0.0000-1.0000).';
COMMENT ON COLUMN production_forecast.degradation_factor IS 'Annual degradation factor applied (e.g., 0.99500 = 0.5% degradation).';
COMMENT ON COLUMN production_forecast.forecast_source IS 'Source of forecast: p50, p75, p90, vendor, manual.';

-- =============================================================================
-- 2. Production Guarantee Table (Annual)
-- =============================================================================
-- One row per project per operating year.
-- Contains guaranteed output, guarantee percentage of P50.
-- Used for: defining annual production guarantee terms per operating year.
-- Year-end evaluation (actual vs guaranteed) is modeled via default_event + rule_output pipeline.

CREATE TABLE IF NOT EXISTS production_guarantee (
  id                      BIGSERIAL PRIMARY KEY,
  project_id              BIGINT NOT NULL REFERENCES project(id),
  organization_id         BIGINT NOT NULL REFERENCES organization(id),
  operating_year          INTEGER NOT NULL,
  year_start_date         DATE NOT NULL,
  year_end_date           DATE NOT NULL,
  guaranteed_kwh          DECIMAL NOT NULL,
  guarantee_pct_of_p50    DECIMAL(5,4),
  p50_annual_kwh          DECIMAL,
  source_metadata         JSONB DEFAULT '{}',
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(project_id, operating_year)
);

CREATE INDEX IF NOT EXISTS idx_production_guarantee_project
  ON production_guarantee(project_id, operating_year);

CREATE INDEX IF NOT EXISTS idx_production_guarantee_org
  ON production_guarantee(organization_id);

COMMENT ON TABLE production_guarantee IS 'Annual production guarantee definitions per project. Evaluation results (actual vs guaranteed) go through the default_event + rule_output pipeline.';
COMMENT ON COLUMN production_guarantee.operating_year IS 'Contract operating year (1-based). Year 1 = COD year.';
COMMENT ON COLUMN production_guarantee.guaranteed_kwh IS 'Guaranteed annual energy production in kWh.';
COMMENT ON COLUMN production_guarantee.guarantee_pct_of_p50 IS 'Guarantee as percentage of P50 forecast (e.g., 0.9000 = 90% of P50).';
COMMENT ON COLUMN production_guarantee.p50_annual_kwh IS 'P50 annual forecast used as baseline for guarantee calculation.';

-- =============================================================================
-- 3. RLS Policies
-- =============================================================================

ALTER TABLE production_forecast ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS production_forecast_org_policy ON production_forecast;
CREATE POLICY production_forecast_org_policy ON production_forecast
  FOR SELECT
  USING (is_org_member(organization_id));

DROP POLICY IF EXISTS production_forecast_admin_modify_policy ON production_forecast;
CREATE POLICY production_forecast_admin_modify_policy ON production_forecast
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS production_forecast_service_policy ON production_forecast;
CREATE POLICY production_forecast_service_policy ON production_forecast
  FOR ALL
  USING (auth.role() = 'service_role');

ALTER TABLE production_guarantee ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS production_guarantee_org_policy ON production_guarantee;
CREATE POLICY production_guarantee_org_policy ON production_guarantee
  FOR SELECT
  USING (is_org_member(organization_id));

DROP POLICY IF EXISTS production_guarantee_admin_modify_policy ON production_guarantee;
CREATE POLICY production_guarantee_admin_modify_policy ON production_guarantee
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS production_guarantee_service_policy ON production_guarantee;
CREATE POLICY production_guarantee_service_policy ON production_guarantee
  FOR ALL
  USING (auth.role() = 'service_role');
