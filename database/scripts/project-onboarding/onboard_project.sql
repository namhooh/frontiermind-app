-- =============================================================================
-- onboard_project.sql — Staged ETL for COD Project Onboarding
-- =============================================================================
-- Architecture: Deterministic ETL with Batch Validation
--   staging tables (with batch_id)
--     → validation checks (fail fast on missing required FKs)
--     → upserts in FK dependency order
--     → post-load assertions
--     → COMMIT (or ROLLBACK on any assertion failure)
--
-- Usage:
--   Option A: psql \copy to populate staging tables, then run upsert sections
--   Option B: Backend API populates staging tables via INSERT, then runs upsert
--   Option C: Adapt staging table INSERTs for specific project data
--
-- Prerequisites:
--   - Migrations 033 and 034 (billing product, rate periods, tariff_type service codes) applied
--   - Organization must exist in organization table
--   - Lookup types (tariff_type, escalation_type, currency, asset_type) must be seeded
--   - billing_product seed data must be loaded (migration 034)
--
-- IMPORTANT: Use \copy or INSERT, NOT COPY FROM (requires superuser on Supabase)
-- =============================================================================

BEGIN;

-- =============================================================================
-- Step 1: Create Staging Tables
-- =============================================================================

CREATE TEMP TABLE stg_batch (
  batch_id          UUID DEFAULT gen_random_uuid(),
  source_file       VARCHAR(255),
  source_file_hash  VARCHAR(64),
  loaded_at         TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO stg_batch (source_file) VALUES ('onboard_project.sql');

CREATE TEMP TABLE stg_project_core (
  batch_id                    UUID,
  -- Organization
  organization_id             BIGINT NOT NULL,
  -- Project
  external_project_id         VARCHAR(50) NOT NULL,
  sage_id                     VARCHAR(50),
  project_name                VARCHAR(255) NOT NULL,
  country                     VARCHAR(100),
  cod_date                    DATE,
  installed_dc_capacity_kwp   DECIMAL,
  installed_ac_capacity_kw    DECIMAL,
  installation_location_url   TEXT,
  -- Counterparty
  customer_name               VARCHAR(255),
  registered_name             VARCHAR(255),
  registration_number         VARCHAR(100),
  tax_pin                     VARCHAR(100),
  registered_address          TEXT,
  customer_email              VARCHAR(255),
  customer_country            VARCHAR(100),
  -- Contract
  external_contract_id        VARCHAR(50),
  contract_name               VARCHAR(255),
  contract_type_code          VARCHAR(50) DEFAULT 'PPA',
  contract_term_years         INTEGER,
  effective_date              DATE,
  end_date                    DATE,
  interconnection_voltage_kv  DECIMAL,
  payment_security_required   BOOLEAN DEFAULT false,
  payment_security_details    TEXT,
  agreed_fx_rate_source       TEXT,
  extraction_metadata         JSONB DEFAULT '{}'
);

CREATE TEMP TABLE stg_tariff_lines (
  batch_id                UUID,
  external_project_id     VARCHAR(50) NOT NULL,
  tariff_group_key        VARCHAR(255) NOT NULL,
  tariff_name             VARCHAR(255),
  tariff_type_code        VARCHAR(50),
  energy_sale_type_code   VARCHAR(50),
  escalation_type_code    VARCHAR(50),
  billing_currency_code   VARCHAR(10) NOT NULL,
  market_ref_currency_code VARCHAR(10),
  base_rate               DECIMAL,
  unit                    VARCHAR(50),
  valid_from              DATE NOT NULL,
  valid_to                DATE,
  discount_pct            DECIMAL,
  floor_rate              DECIMAL,
  ceiling_rate            DECIMAL,
  escalation_value        DECIMAL,
  grp_method              VARCHAR(100),
  logic_parameters_extra  JSONB DEFAULT '{}'
);

CREATE TEMP TABLE stg_contacts (
  batch_id              UUID,
  external_project_id   VARCHAR(50) NOT NULL,
  role                  VARCHAR(100),
  full_name             VARCHAR(255),
  email                 VARCHAR(255),
  phone                 VARCHAR(50),
  include_in_invoice    BOOLEAN DEFAULT false,
  escalation_only       BOOLEAN DEFAULT false
);

CREATE TEMP TABLE stg_forecast_monthly (
  batch_id              UUID,
  external_project_id   VARCHAR(50) NOT NULL,
  forecast_month        DATE NOT NULL,
  operating_year        INTEGER,
  forecast_energy_kwh   DECIMAL NOT NULL,
  forecast_ghi          DECIMAL,
  forecast_poa          DECIMAL,
  forecast_pr           DECIMAL(5,4),
  degradation_factor    DECIMAL(6,5),
  forecast_source       VARCHAR(100) DEFAULT 'p50',
  source_metadata       JSONB DEFAULT '{}'
);

CREATE TEMP TABLE stg_guarantee_yearly (
  batch_id              UUID,
  external_project_id   VARCHAR(50) NOT NULL,
  operating_year        INTEGER NOT NULL,
  year_start_date       DATE,
  year_end_date         DATE,
  guaranteed_kwh        DECIMAL NOT NULL,
  guarantee_pct_of_p50  DECIMAL,
  p50_annual_kwh        DECIMAL,
  shortfall_cap_usd     DECIMAL,
  shortfall_cap_fx_rule VARCHAR(255),
  source_metadata       JSONB DEFAULT '{}'
);

CREATE TEMP TABLE stg_installation (
  batch_id              UUID,
  external_project_id   VARCHAR(50) NOT NULL,
  asset_type_code       VARCHAR(50) NOT NULL,
  asset_name            VARCHAR(255),
  model                 VARCHAR(255),
  serial_code           VARCHAR(255),
  capacity              DECIMAL,
  capacity_unit         VARCHAR(20),
  quantity              INTEGER DEFAULT 1
);

CREATE TEMP TABLE stg_meters (
  batch_id              UUID,
  external_project_id   VARCHAR(50) NOT NULL,
  serial_number         VARCHAR(100) NOT NULL,
  location_description  TEXT,
  metering_type         VARCHAR(20),  -- 'net' or 'export_only'
  is_billing_meter      BOOLEAN DEFAULT TRUE
);

CREATE TEMP TABLE stg_billing_products (
  batch_id              UUID,
  external_project_id   VARCHAR(50) NOT NULL,
  product_code          VARCHAR(50) NOT NULL,
  is_primary            BOOLEAN DEFAULT false
);

-- =============================================================================
-- Step 2: Load Data
-- =============================================================================
-- Populate staging tables using one of:
--   \copy stg_project_core FROM 'project_core.csv' WITH (FORMAT csv, HEADER true);
--   INSERT INTO stg_project_core VALUES (...);
--   Backend API INSERT statements

-- Set batch_id on all staging rows
-- (Run after data is loaded into staging tables)
-- UPDATE stg_project_core SET batch_id = (SELECT batch_id FROM stg_batch LIMIT 1);
-- UPDATE stg_tariff_lines SET batch_id = (SELECT batch_id FROM stg_batch LIMIT 1);
-- ... etc for all staging tables

-- =============================================================================
-- Step 3: Pre-Flight Validation (fail fast)
-- =============================================================================

DO $$
BEGIN
  -- Verify organization exists
  IF EXISTS (
    SELECT 1 FROM stg_project_core s
    LEFT JOIN organization o ON o.id = s.organization_id
    WHERE o.id IS NULL
  ) THEN
    RAISE EXCEPTION 'Unresolved organization_id in staging data';
  END IF;

  -- Verify tariff type codes exist
  IF EXISTS (
    SELECT 1 FROM stg_tariff_lines s
    LEFT JOIN tariff_type t ON t.code = s.tariff_type_code
    WHERE s.tariff_type_code IS NOT NULL AND t.id IS NULL
  ) THEN
    RAISE EXCEPTION 'Unresolved tariff_type codes: %',
      (SELECT string_agg(DISTINCT s.tariff_type_code, ', ')
       FROM stg_tariff_lines s
       LEFT JOIN tariff_type t ON t.code = s.tariff_type_code
       WHERE s.tariff_type_code IS NOT NULL AND t.id IS NULL);
  END IF;

  -- Verify energy_sale_type codes exist
  IF EXISTS (
    SELECT 1 FROM stg_tariff_lines s
    LEFT JOIN energy_sale_type e ON e.code = s.energy_sale_type_code
    WHERE s.energy_sale_type_code IS NOT NULL AND e.id IS NULL
  ) THEN
    RAISE EXCEPTION 'Unresolved energy_sale_type codes: %',
      (SELECT string_agg(DISTINCT s.energy_sale_type_code, ', ')
       FROM stg_tariff_lines s
       LEFT JOIN energy_sale_type e ON e.code = s.energy_sale_type_code
       WHERE s.energy_sale_type_code IS NOT NULL AND e.id IS NULL);
  END IF;

  -- Verify currency codes exist
  IF EXISTS (
    SELECT 1 FROM stg_tariff_lines s
    LEFT JOIN currency c ON c.code = s.billing_currency_code
    WHERE c.id IS NULL
  ) THEN
    RAISE EXCEPTION 'Unresolved currency codes: %',
      (SELECT string_agg(DISTINCT s.billing_currency_code, ', ')
       FROM stg_tariff_lines s
       LEFT JOIN currency c ON c.code = s.billing_currency_code
       WHERE c.id IS NULL);
  END IF;

  -- Verify asset_type codes exist
  IF EXISTS (
    SELECT 1 FROM stg_installation s
    LEFT JOIN asset_type at ON at.code = s.asset_type_code
    WHERE at.id IS NULL
  ) THEN
    RAISE EXCEPTION 'Unresolved asset_type codes: %',
      (SELECT string_agg(DISTINCT s.asset_type_code, ', ')
       FROM stg_installation s
       LEFT JOIN asset_type at ON at.code = s.asset_type_code
       WHERE at.id IS NULL);
  END IF;

  -- Verify billing product codes exist
  IF EXISTS (
    SELECT 1 FROM stg_billing_products s
    LEFT JOIN stg_project_core spc ON s.external_project_id = spc.external_project_id
    WHERE NOT EXISTS (
      SELECT 1 FROM billing_product bp
      WHERE bp.code = s.product_code
        AND (bp.organization_id = spc.organization_id OR bp.organization_id IS NULL)
    )
  ) THEN
    RAISE EXCEPTION 'Unresolved billing product codes: %',
      (SELECT string_agg(DISTINCT s.product_code, ', ')
       FROM stg_billing_products s
       LEFT JOIN stg_project_core spc ON s.external_project_id = spc.external_project_id
       WHERE NOT EXISTS (
         SELECT 1 FROM billing_product bp
         WHERE bp.code = s.product_code
           AND (bp.organization_id = spc.organization_id OR bp.organization_id IS NULL)
       ));
  END IF;

  -- Verify COD date is present
  IF EXISTS (SELECT 1 FROM stg_project_core WHERE cod_date IS NULL) THEN
    RAISE EXCEPTION 'COD date is required for all projects';
  END IF;

  -- Verify guaranteed_kwh is positive
  IF EXISTS (SELECT 1 FROM stg_guarantee_yearly WHERE guaranteed_kwh <= 0) THEN
    RAISE EXCEPTION 'guaranteed_kwh must be positive for all guarantee years';
  END IF;
END $$;

-- =============================================================================
-- Step 4: Upsert Master Entities (FK dependency order)
-- =============================================================================

-- 4.1 Counterparty
INSERT INTO counterparty (
  counterparty_type_id, name, email, address, country,
  registered_name, registration_number, tax_pin, registered_address
)
SELECT
  (SELECT id FROM counterparty_type WHERE code = 'OFFTAKER' LIMIT 1),
  COALESCE(s.customer_name, s.external_project_id || ' Offtaker'),
  s.customer_email,
  s.registered_address,
  s.customer_country,
  s.registered_name,
  s.registration_number,
  s.tax_pin,
  s.registered_address
FROM stg_project_core s
ON CONFLICT (counterparty_type_id, LOWER(name)) DO UPDATE SET
  registered_name = EXCLUDED.registered_name,
  registration_number = EXCLUDED.registration_number,
  tax_pin = EXCLUDED.tax_pin,
  registered_address = EXCLUDED.registered_address;

-- 4.2 Project
INSERT INTO project (
  organization_id, name, external_project_id, sage_id, country,
  cod_date, installed_dc_capacity_kwp, installed_ac_capacity_kw,
  installation_location_url
)
SELECT
  s.organization_id,
  s.project_name,
  s.external_project_id,
  s.sage_id,
  s.country,
  s.cod_date,
  s.installed_dc_capacity_kwp,
  s.installed_ac_capacity_kw,
  s.installation_location_url
FROM stg_project_core s
ON CONFLICT (organization_id, external_project_id)
  WHERE external_project_id IS NOT NULL
DO UPDATE SET
  cod_date = EXCLUDED.cod_date,
  installed_dc_capacity_kwp = EXCLUDED.installed_dc_capacity_kwp,
  installed_ac_capacity_kw = EXCLUDED.installed_ac_capacity_kw,
  sage_id = EXCLUDED.sage_id,
  country = EXCLUDED.country,
  installation_location_url = EXCLUDED.installation_location_url;

-- 4.3 Contract
INSERT INTO contract (
  project_id, organization_id, counterparty_id,
  contract_type_id, contract_status_id,
  name, effective_date, end_date,
  external_contract_id, contract_term_years,
  interconnection_voltage_kv,
  payment_security_required, payment_security_details,
  agreed_fx_rate_source, extraction_metadata
)
SELECT
  p.id,
  s.organization_id,
  cp.id,
  ct.id,
  (SELECT id FROM contract_status WHERE code = 'ACTIVE' LIMIT 1),
  COALESCE(s.contract_name, s.project_name || ' PPA'),
  s.effective_date,
  s.end_date,
  s.external_contract_id,
  s.contract_term_years,
  s.interconnection_voltage_kv,
  s.payment_security_required,
  s.payment_security_details,
  s.agreed_fx_rate_source,
  s.extraction_metadata
FROM stg_project_core s
JOIN project p ON p.organization_id = s.organization_id AND p.external_project_id = s.external_project_id
LEFT JOIN counterparty cp ON LOWER(cp.name) = LOWER(s.customer_name)
LEFT JOIN contract_type ct ON ct.code = s.contract_type_code
ON CONFLICT (project_id, external_contract_id)
  WHERE external_contract_id IS NOT NULL
DO UPDATE SET
  counterparty_id = COALESCE(EXCLUDED.counterparty_id, contract.counterparty_id),
  name = EXCLUDED.name,
  effective_date = COALESCE(EXCLUDED.effective_date, contract.effective_date),
  end_date = COALESCE(EXCLUDED.end_date, contract.end_date),
  contract_term_years = EXCLUDED.contract_term_years,
  interconnection_voltage_kv = EXCLUDED.interconnection_voltage_kv,
  payment_security_required = EXCLUDED.payment_security_required,
  payment_security_details = EXCLUDED.payment_security_details,
  agreed_fx_rate_source = EXCLUDED.agreed_fx_rate_source,
  extraction_metadata = COALESCE(EXCLUDED.extraction_metadata, contract.extraction_metadata),
  updated_at = NOW();

-- 4.4 Asset (equipment)
INSERT INTO asset (
  project_id, asset_type_id, name, model, serial_code,
  capacity, capacity_unit, quantity
)
SELECT
  p.id,
  at.id,
  COALESCE(si.asset_name, at.name),
  si.model,
  si.serial_code,
  si.capacity,
  si.capacity_unit,
  si.quantity
FROM stg_installation si
JOIN stg_project_core spc ON si.external_project_id = spc.external_project_id
JOIN project p ON p.organization_id = spc.organization_id AND p.external_project_id = si.external_project_id
JOIN asset_type at ON at.code = si.asset_type_code
ON CONFLICT DO NOTHING;

-- 4.5 Clause Tariff
INSERT INTO clause_tariff (
  project_id, contract_id, organization_id,
  tariff_group_key, name,
  tariff_type_id, energy_sale_type_id, escalation_type_id,
  currency_id, market_ref_currency_id,
  base_rate, unit, valid_from, valid_to,
  logic_parameters, is_active
)
SELECT
  p.id,
  c.id,
  spc.organization_id,
  stl.tariff_group_key,
  COALESCE(stl.tariff_name, stl.tariff_group_key),
  tt.id,
  est.id,
  esc.id,
  cur.id,
  mrc.id,
  stl.base_rate,
  stl.unit,
  stl.valid_from,
  stl.valid_to,
  jsonb_build_object(
    'discount_pct', stl.discount_pct,
    'floor_rate', stl.floor_rate,
    'ceiling_rate', stl.ceiling_rate,
    'escalation_value', stl.escalation_value,
    'grp_method', stl.grp_method
  ) || stl.logic_parameters_extra,
  true
FROM stg_tariff_lines stl
JOIN stg_project_core spc ON stl.external_project_id = spc.external_project_id
JOIN project p ON p.organization_id = spc.organization_id AND p.external_project_id = stl.external_project_id
JOIN contract c ON c.project_id = p.id AND c.external_contract_id = spc.external_contract_id
LEFT JOIN tariff_type tt ON tt.code = stl.tariff_type_code
LEFT JOIN energy_sale_type est ON est.code = stl.energy_sale_type_code
  AND (est.organization_id IS NULL OR est.organization_id = spc.organization_id)
LEFT JOIN escalation_type esc ON esc.code = stl.escalation_type_code AND esc.organization_id IS NULL
JOIN currency cur ON cur.code = stl.billing_currency_code
LEFT JOIN currency mrc ON mrc.code = stl.market_ref_currency_code
ON CONFLICT (contract_id, tariff_group_key, valid_from, COALESCE(valid_to, '9999-12-31'::date))
  WHERE tariff_group_key IS NOT NULL AND is_current = true
DO UPDATE SET
  base_rate = EXCLUDED.base_rate,
  logic_parameters = EXCLUDED.logic_parameters,
  tariff_type_id = EXCLUDED.tariff_type_id,
  energy_sale_type_id = EXCLUDED.energy_sale_type_id,
  escalation_type_id = EXCLUDED.escalation_type_id,
  updated_at = NOW();

-- 4.6 Customer Contact
INSERT INTO customer_contact (
  counterparty_id, organization_id, role, full_name, email, phone,
  include_in_invoice_email, escalation_only
)
SELECT
  cp.id,
  spc.organization_id,
  sc.role,
  sc.full_name,
  sc.email,
  sc.phone,
  sc.include_in_invoice,
  sc.escalation_only
FROM stg_contacts sc
JOIN stg_project_core spc ON sc.external_project_id = spc.external_project_id
JOIN counterparty cp ON LOWER(cp.name) = LOWER(spc.customer_name)
ON CONFLICT (counterparty_id, LOWER(email), role)
  WHERE is_active = true AND email IS NOT NULL
DO UPDATE SET
  full_name = EXCLUDED.full_name,
  phone = EXCLUDED.phone,
  updated_at = NOW();

-- 4.7 Production Forecast (12 months)
INSERT INTO production_forecast (
  project_id, organization_id, forecast_month, operating_year,
  forecast_energy_kwh, forecast_ghi_irradiance, forecast_poa_irradiance,
  forecast_pr, degradation_factor, forecast_source, source_metadata
)
SELECT
  p.id,
  spc.organization_id,
  sf.forecast_month,
  sf.operating_year,
  sf.forecast_energy_kwh,
  sf.forecast_ghi,
  sf.forecast_poa,
  sf.forecast_pr,
  sf.degradation_factor,
  sf.forecast_source,
  sf.source_metadata
FROM stg_forecast_monthly sf
JOIN stg_project_core spc ON sf.external_project_id = spc.external_project_id
JOIN project p ON p.organization_id = spc.organization_id AND p.external_project_id = sf.external_project_id
ON CONFLICT (project_id, forecast_month) DO UPDATE SET
  forecast_energy_kwh = EXCLUDED.forecast_energy_kwh,
  forecast_ghi_irradiance = EXCLUDED.forecast_ghi_irradiance,
  forecast_poa_irradiance = EXCLUDED.forecast_poa_irradiance,
  forecast_pr = EXCLUDED.forecast_pr,
  degradation_factor = EXCLUDED.degradation_factor,
  updated_at = NOW();

-- 4.8 Production Guarantee (20 years)
INSERT INTO production_guarantee (
  project_id, organization_id, operating_year,
  year_start_date, year_end_date,
  guaranteed_kwh, guarantee_pct_of_p50, p50_annual_kwh,
  shortfall_cap_usd, shortfall_cap_fx_rule, source_metadata
)
SELECT
  p.id,
  spc.organization_id,
  sg.operating_year,
  sg.year_start_date,
  sg.year_end_date,
  sg.guaranteed_kwh,
  sg.guarantee_pct_of_p50,
  sg.p50_annual_kwh,
  sg.shortfall_cap_usd,
  sg.shortfall_cap_fx_rule,
  sg.source_metadata
FROM stg_guarantee_yearly sg
JOIN stg_project_core spc ON sg.external_project_id = spc.external_project_id
JOIN project p ON p.organization_id = spc.organization_id AND p.external_project_id = sg.external_project_id
ON CONFLICT (project_id, operating_year) DO UPDATE SET
  year_start_date = EXCLUDED.year_start_date,
  year_end_date = EXCLUDED.year_end_date,
  guaranteed_kwh = EXCLUDED.guaranteed_kwh,
  guarantee_pct_of_p50 = EXCLUDED.guarantee_pct_of_p50,
  p50_annual_kwh = EXCLUDED.p50_annual_kwh,
  shortfall_cap_usd = EXCLUDED.shortfall_cap_usd,
  shortfall_cap_fx_rule = EXCLUDED.shortfall_cap_fx_rule,
  updated_at = NOW();

-- 4.9 Meters
INSERT INTO meter (project_id, serial_number, location_description, metering_type)
SELECT
  p.id,
  sm.serial_number,
  sm.location_description,
  sm.metering_type
FROM stg_meters sm
JOIN stg_project_core spc ON sm.external_project_id = spc.external_project_id
JOIN project p ON p.organization_id = spc.organization_id AND p.external_project_id = sm.external_project_id
ON CONFLICT (project_id, serial_number)
  WHERE serial_number IS NOT NULL
DO UPDATE SET
  location_description = EXCLUDED.location_description,
  metering_type = EXCLUDED.metering_type;

-- 4.10 Contract Billing Products
-- Resolve billing_product.id by code, preferring org-scoped over canonical (NULL org).
-- LATERAL subquery ensures exactly one match per product code, with org-scoped winning
-- over platform-level canonical when both exist.
INSERT INTO contract_billing_product (contract_id, billing_product_id, is_primary)
SELECT
  c.id,
  bp.id,
  sbp.is_primary
FROM stg_billing_products sbp
JOIN stg_project_core spc ON sbp.external_project_id = spc.external_project_id
JOIN project p ON p.organization_id = spc.organization_id AND p.external_project_id = sbp.external_project_id
JOIN contract c ON c.project_id = p.id AND c.external_contract_id = spc.external_contract_id
JOIN LATERAL (
  SELECT id FROM billing_product
  WHERE code = sbp.product_code
    AND (organization_id = spc.organization_id OR organization_id IS NULL)
  ORDER BY organization_id NULLS LAST
  LIMIT 1
) bp ON true
ON CONFLICT (contract_id, billing_product_id) DO UPDATE SET
  is_primary = EXCLUDED.is_primary;

-- 4.11 Tariff Rate Period (Year 1 = base_rate)
-- Creates the initial tariff_rate_period row for each clause_tariff.
-- effective_rate = base_rate for Year 1. Future escalation inserts new rows.
INSERT INTO tariff_rate_period (
  clause_tariff_id, contract_year, period_start, period_end,
  effective_rate, currency_id, calculation_basis, is_current
)
SELECT
  ct.id,
  1,
  ct.valid_from,
  ct.valid_to,
  ct.base_rate,
  ct.currency_id,
  'Year 1: original contractual base rate',
  true
FROM clause_tariff ct
JOIN contract c ON ct.contract_id = c.id
JOIN stg_project_core spc ON c.project_id = (
  SELECT p.id FROM project p
  WHERE p.organization_id = spc.organization_id AND p.external_project_id = spc.external_project_id
)
WHERE ct.is_current = true
  AND ct.base_rate IS NOT NULL
ON CONFLICT (clause_tariff_id, contract_year) DO NOTHING;

-- =============================================================================
-- Step 5: Post-Load Assertions (fail → ROLLBACK)
-- =============================================================================

DO $$
DECLARE
  v_project_id BIGINT;
  v_ext_id VARCHAR;
  v_org_id BIGINT;
  v_forecast_count INTEGER;
  v_guarantee_count INTEGER;
  v_stg_forecast_count INTEGER;
  v_stg_guarantee_count INTEGER;
BEGIN
  -- Get project from staging
  SELECT external_project_id, organization_id
    INTO v_ext_id, v_org_id
    FROM stg_project_core LIMIT 1;

  IF v_ext_id IS NULL THEN
    RAISE NOTICE 'No staging data found — skipping assertions';
    RETURN;
  END IF;

  SELECT id INTO v_project_id
    FROM project
    WHERE organization_id = v_org_id AND external_project_id = v_ext_id;

  IF v_project_id IS NULL THEN
    RAISE EXCEPTION 'Project not found after upsert: external_project_id=%', v_ext_id;
  END IF;

  -- Count staging rows for comparison
  SELECT COUNT(*) INTO v_stg_forecast_count FROM stg_forecast_monthly WHERE external_project_id = v_ext_id;
  SELECT COUNT(*) INTO v_stg_guarantee_count FROM stg_guarantee_yearly WHERE external_project_id = v_ext_id;

  -- Verify forecast rows match staging count
  SELECT COUNT(*) INTO v_forecast_count FROM production_forecast WHERE project_id = v_project_id;
  IF v_stg_forecast_count > 0 AND v_forecast_count < v_stg_forecast_count THEN
    RAISE EXCEPTION 'Expected at least % production_forecast rows, found %', v_stg_forecast_count, v_forecast_count;
  END IF;

  -- Verify guarantee rows match staging count
  SELECT COUNT(*) INTO v_guarantee_count FROM production_guarantee WHERE project_id = v_project_id;
  IF v_stg_guarantee_count > 0 AND v_guarantee_count < v_stg_guarantee_count THEN
    RAISE EXCEPTION 'Expected at least % production_guarantee rows, found %', v_stg_guarantee_count, v_guarantee_count;
  END IF;

  -- Verify meter rows match staging count
  DECLARE v_stg_meter_count INTEGER; v_meter_count INTEGER;
  BEGIN
    SELECT COUNT(*) INTO v_stg_meter_count FROM stg_meters WHERE external_project_id = v_ext_id;
    IF v_stg_meter_count > 0 THEN
      SELECT COUNT(*) INTO v_meter_count FROM meter WHERE project_id = v_project_id;
      IF v_meter_count < v_stg_meter_count THEN
        RAISE EXCEPTION 'Expected at least % meter rows, found %', v_stg_meter_count, v_meter_count;
      END IF;
    END IF;
  END;

  -- Verify contract exists
  IF NOT EXISTS (SELECT 1 FROM contract WHERE project_id = v_project_id) THEN
    RAISE EXCEPTION 'No contract found for project_id=%', v_project_id;
  END IF;

  -- Verify billing products match staging count
  DECLARE v_stg_bp_count INTEGER; v_bp_count INTEGER; v_primary_count INTEGER;
  BEGIN
    SELECT COUNT(*) INTO v_stg_bp_count FROM stg_billing_products WHERE external_project_id = v_ext_id;
    IF v_stg_bp_count > 0 THEN
      SELECT COUNT(*), COUNT(*) FILTER (WHERE is_primary = true)
        INTO v_bp_count, v_primary_count
        FROM contract_billing_product
        WHERE contract_id IN (SELECT id FROM contract WHERE project_id = v_project_id);
      IF v_bp_count < v_stg_bp_count THEN
        RAISE EXCEPTION 'Expected at least % contract_billing_product rows, found %', v_stg_bp_count, v_bp_count;
      END IF;
      IF v_primary_count != 1 THEN
        RAISE EXCEPTION 'Expected exactly 1 primary billing product per contract, found %', v_primary_count;
      END IF;
    END IF;
  END;

  -- Verify tariff rate period Year 1 was created for each tariff with base_rate
  DECLARE v_tariff_count INTEGER; v_trp_count INTEGER;
  BEGIN
    SELECT COUNT(*) INTO v_tariff_count
      FROM clause_tariff ct
      JOIN contract c ON ct.contract_id = c.id
      WHERE c.project_id = v_project_id AND ct.is_current = true AND ct.base_rate IS NOT NULL;
    IF v_tariff_count > 0 THEN
      SELECT COUNT(*) INTO v_trp_count
        FROM tariff_rate_period trp
        JOIN clause_tariff ct ON ct.id = trp.clause_tariff_id
        JOIN contract c ON ct.contract_id = c.id
        WHERE c.project_id = v_project_id AND trp.is_current = true;
      IF v_trp_count < v_tariff_count THEN
        RAISE EXCEPTION 'Expected at least % current tariff_rate_period rows (one per tariff), found %', v_tariff_count, v_trp_count;
      END IF;
    END IF;
  END;

  -- Data quality: guaranteed_kwh must be positive
  IF EXISTS (
    SELECT 1 FROM production_guarantee
    WHERE project_id = v_project_id AND guaranteed_kwh <= 0
  ) THEN
    RAISE EXCEPTION 'guaranteed_kwh must be positive for all guarantee years';
  END IF;

  -- Data quality: guarantee should be monotonically declining (if > 1 year)
  IF v_guarantee_count > 1 AND EXISTS (
    SELECT 1 FROM (
      SELECT operating_year, guaranteed_kwh,
        LAG(guaranteed_kwh) OVER (ORDER BY operating_year) AS prev
      FROM production_guarantee WHERE project_id = v_project_id
    ) t WHERE prev IS NOT NULL AND guaranteed_kwh > prev
  ) THEN
    RAISE WARNING 'Guaranteed kWh is not monotonically declining — review degradation schedule';
    -- Warning only, not exception — some contracts have non-declining guarantees
  END IF;

  -- Data quality: tariff discount_pct between 0 and 1
  IF EXISTS (
    SELECT 1 FROM clause_tariff ct
    JOIN contract c ON ct.contract_id = c.id
    WHERE c.project_id = v_project_id
      AND ct.logic_parameters ? 'discount_pct'
      AND (ct.logic_parameters->>'discount_pct')::decimal NOT BETWEEN 0 AND 1
  ) THEN
    RAISE EXCEPTION 'discount_pct must be between 0 and 1';
  END IF;

  -- Data quality: floor <= ceiling
  IF EXISTS (
    SELECT 1 FROM clause_tariff ct
    JOIN contract c ON ct.contract_id = c.id
    WHERE c.project_id = v_project_id
      AND ct.logic_parameters ? 'floor_rate'
      AND ct.logic_parameters ? 'ceiling_rate'
      AND (ct.logic_parameters->>'floor_rate')::decimal > (ct.logic_parameters->>'ceiling_rate')::decimal
  ) THEN
    RAISE EXCEPTION 'floor_rate must be <= ceiling_rate';
  END IF;

  RAISE NOTICE 'Post-load assertions passed for project % (id=%)', v_ext_id, v_project_id;
  RAISE NOTICE '  Forecasts: %, Guarantees: %, Billing products: checked, Rate periods: checked', v_forecast_count, v_guarantee_count;
END $$;

COMMIT;
