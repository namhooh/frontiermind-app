-- Migration 033: Project Onboarding Schema (Revised)
-- Date: 2026-02-17
-- Phase: 9.0 - COD Data Capture, Amendment Versioning & Tariff Term Support
--
-- Changes:
--   A. ALTER existing tables: project, contract, counterparty, asset, meter,
--      production_forecast, production_guarantee
--   B. Add unique constraints for upsert support: clause_tariff (versioned), customer_contact
--   C. CREATE new tables: reference_price, contract_amendment, onboarding_preview
--   D. Seed asset_type with equipment codes; seed invoice_line_item_type
--   E. RLS policies and indexes for new/altered tables
--   F. CHECK constraints for data quality
--   G. Unique indexes for meter and counterparty upserts
--   H. Amendment tracking: enum, columns on clause/clause_tariff, triggers, views
--   I. Contract: rename updated_by → created_by

-- =============================================================================
-- A1. ALTER project — Physical site identifiers and capacity fields
-- =============================================================================

ALTER TABLE project
  ADD COLUMN IF NOT EXISTS external_project_id  VARCHAR(50),
  ADD COLUMN IF NOT EXISTS sage_id              VARCHAR(50),
  ADD COLUMN IF NOT EXISTS country              VARCHAR(100),
  ADD COLUMN IF NOT EXISTS cod_date             DATE,
  ADD COLUMN IF NOT EXISTS installed_dc_capacity_kwp DECIMAL,
  ADD COLUMN IF NOT EXISTS installed_ac_capacity_kw  DECIMAL,
  ADD COLUMN IF NOT EXISTS installation_location_url TEXT;

COMMENT ON COLUMN project.external_project_id IS 'Client-defined project identifier (e.g., country code + number).';
COMMENT ON COLUMN project.sage_id IS 'Finance/ERP system reference (e.g., Sage ID).';
COMMENT ON COLUMN project.country IS 'Country where the project site is physically located.';
COMMENT ON COLUMN project.cod_date IS 'Commercial Operations Date — when the site was commissioned.';
COMMENT ON COLUMN project.installed_dc_capacity_kwp IS 'Total installed DC capacity in kWp. Used in billing pro-rating.';
COMMENT ON COLUMN project.installed_ac_capacity_kw IS 'Total installed AC capacity in kW. Used in billing pro-rating.';
COMMENT ON COLUMN project.installation_location_url IS 'Google Maps URL or other geo-reference for the physical site.';

-- Unique constraint for idempotent upsert
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_org_external
  ON project(organization_id, external_project_id)
  WHERE external_project_id IS NOT NULL;

-- =============================================================================
-- A2. ALTER contract — PPA-specific terms and onboarding flags
-- =============================================================================

ALTER TABLE contract
  ADD COLUMN IF NOT EXISTS external_contract_id      VARCHAR(50),
  ADD COLUMN IF NOT EXISTS contract_term_years        INTEGER,
  ADD COLUMN IF NOT EXISTS interconnection_voltage_kv DECIMAL,
  ADD COLUMN IF NOT EXISTS has_amendments             BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS payment_security_required  BOOLEAN,
  ADD COLUMN IF NOT EXISTS payment_security_details   TEXT,
  ADD COLUMN IF NOT EXISTS ppa_confirmed_uploaded     BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS agreed_fx_rate_source      VARCHAR(255);

COMMENT ON COLUMN contract.external_contract_id IS 'Client-defined contract identifier (e.g., 4-digit numerical ID).';
COMMENT ON COLUMN contract.contract_term_years IS 'PPA duration in years.';
COMMENT ON COLUMN contract.interconnection_voltage_kv IS 'Grid interconnection voltage specified in PPA (kV).';
COMMENT ON COLUMN contract.has_amendments IS 'Whether this contract has any post-signing amendments.';
COMMENT ON COLUMN contract.payment_security_required IS 'Whether payment security (LC, guarantee) is required.';
COMMENT ON COLUMN contract.payment_security_details IS 'Details of payment security arrangements.';
COMMENT ON COLUMN contract.ppa_confirmed_uploaded IS 'Whether the confirmed PPA document has been uploaded.';
COMMENT ON COLUMN contract.agreed_fx_rate_source IS 'Contractual FX rate reference (e.g., "Bank of Ghana closing rate").';

-- Unique constraint for idempotent upsert
CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_project_external
  ON contract(project_id, external_contract_id)
  WHERE external_contract_id IS NOT NULL;

-- =============================================================================
-- A3. ALTER counterparty — Legal registration fields
-- =============================================================================

ALTER TABLE counterparty
  ADD COLUMN IF NOT EXISTS registered_name       VARCHAR(255),
  ADD COLUMN IF NOT EXISTS registration_number   VARCHAR(100),
  ADD COLUMN IF NOT EXISTS tax_pin               VARCHAR(100),
  ADD COLUMN IF NOT EXISTS registered_address    TEXT;

COMMENT ON COLUMN counterparty.registered_name IS 'Official registered company name (may differ from trading name).';
COMMENT ON COLUMN counterparty.registration_number IS 'Company registration number.';
COMMENT ON COLUMN counterparty.tax_pin IS 'Tax identification number (TIN/PIN).';
COMMENT ON COLUMN counterparty.registered_address IS 'Registered address from contract Notices clause.';

-- =============================================================================
-- A4. ALTER asset — Equipment capacity and quantity
-- =============================================================================

ALTER TABLE asset
  ADD COLUMN IF NOT EXISTS capacity       DECIMAL,
  ADD COLUMN IF NOT EXISTS capacity_unit  VARCHAR(20),
  ADD COLUMN IF NOT EXISTS quantity       INTEGER DEFAULT 1;

COMMENT ON COLUMN asset.capacity IS 'Rated capacity of the asset (e.g., 450 for a 450Wp module).';
COMMENT ON COLUMN asset.capacity_unit IS 'Unit of capacity: kWp, kW, kWh, kVA.';
COMMENT ON COLUMN asset.quantity IS 'Count of units (e.g., 500 PV modules, 10 inverters). Default 1.';

-- =============================================================================
-- A5. ALTER meter — Serial number and metering configuration
-- =============================================================================

ALTER TABLE meter
  ADD COLUMN IF NOT EXISTS serial_number         VARCHAR(100),
  ADD COLUMN IF NOT EXISTS location_description  TEXT,
  ADD COLUMN IF NOT EXISTS metering_type         VARCHAR(20);

COMMENT ON COLUMN meter.serial_number IS 'Billing meter serial number for identification.';
COMMENT ON COLUMN meter.location_description IS 'Physical location description of the meter installation.';
COMMENT ON COLUMN meter.metering_type IS 'Metering configuration: net or export_only.';

-- =============================================================================
-- A6. ALTER production_forecast — Add POA irradiance for PVSyst completeness
-- =============================================================================

ALTER TABLE production_forecast
  ADD COLUMN IF NOT EXISTS forecast_poa_irradiance DECIMAL;

COMMENT ON COLUMN production_forecast.forecast_poa_irradiance IS 'Forecasted Plane of Array (POA) irradiance (kWh/m2). From PVSyst report — used for variance analysis against measured values, NOT for Available Energy formula (which uses measured irradiance from meter_reading).';

-- =============================================================================
-- A7. ALTER production_guarantee — Shortfall cap fields
-- =============================================================================

ALTER TABLE production_guarantee
  ADD COLUMN IF NOT EXISTS shortfall_cap_usd      DECIMAL,
  ADD COLUMN IF NOT EXISTS shortfall_cap_fx_rule   VARCHAR(255);

COMMENT ON COLUMN production_guarantee.shortfall_cap_usd IS 'Annual shortfall payment cap in USD (queryable for billing calculations).';
COMMENT ON COLUMN production_guarantee.shortfall_cap_fx_rule IS 'FX conversion rule for the shortfall cap (e.g., "Agreed Exchange Rate as defined in Section X").';

-- =============================================================================
-- B1. UNIQUE constraint on clause_tariff for versioned upsert support
-- =============================================================================
-- Scoped to current rows only (amendment versioning adds is_current column below)
-- This index will be created after the is_current column is added in section H.

-- =============================================================================
-- B2. UNIQUE constraint on customer_contact for deduplication
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_contact_email_role
  ON customer_contact(counterparty_id, LOWER(email), role)
  WHERE is_active = true AND email IS NOT NULL;

-- =============================================================================
-- C1. CREATE contract_amendment — Lightweight amendment metadata
-- =============================================================================

CREATE TABLE IF NOT EXISTS contract_amendment (
  id                BIGSERIAL PRIMARY KEY,
  contract_id       BIGINT NOT NULL REFERENCES contract(id),
  organization_id   BIGINT NOT NULL REFERENCES organization(id),
  amendment_number  INTEGER NOT NULL,
  amendment_date    DATE NOT NULL,
  effective_date    DATE,
  description       TEXT,
  file_path         TEXT,
  source_metadata   JSONB DEFAULT '{}',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW(),
  created_by        UUID,
  UNIQUE(contract_id, amendment_number)
);

CREATE INDEX IF NOT EXISTS idx_contract_amendment_contract
  ON contract_amendment(contract_id);

CREATE INDEX IF NOT EXISTS idx_contract_amendment_org
  ON contract_amendment(organization_id);

COMMENT ON TABLE contract_amendment IS 'Lightweight metadata for post-signing contract amendments. Clauses/tariffs link here via contract_amendment_id.';
COMMENT ON COLUMN contract_amendment.amendment_number IS 'Incrementing amendment number per contract (1, 2, 3...).';
COMMENT ON COLUMN contract_amendment.amendment_date IS 'Date the amendment was signed.';
COMMENT ON COLUMN contract_amendment.effective_date IS 'Date the amendment takes effect (may differ from signing date).';

-- RLS for contract_amendment
ALTER TABLE contract_amendment ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS contract_amendment_org_policy ON contract_amendment;
CREATE POLICY contract_amendment_org_policy ON contract_amendment
  FOR SELECT
  USING (is_org_member(organization_id));

DROP POLICY IF EXISTS contract_amendment_admin_modify_policy ON contract_amendment;
CREATE POLICY contract_amendment_admin_modify_policy ON contract_amendment
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS contract_amendment_service_policy ON contract_amendment;
CREATE POLICY contract_amendment_service_policy ON contract_amendment
  FOR ALL
  USING (auth.role() = 'service_role');

-- =============================================================================
-- C2. CREATE reference_price — Annual calculated reference price per project
-- =============================================================================

-- Enum for verification status
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'verification_status') THEN
    CREATE TYPE verification_status AS ENUM ('pending', 'jointly_verified', 'disputed', 'estimated');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS reference_price (
  id                      BIGSERIAL PRIMARY KEY,
  project_id              BIGINT NOT NULL REFERENCES project(id),
  organization_id         BIGINT NOT NULL REFERENCES organization(id),
  operating_year          INTEGER NOT NULL,
  period_start            DATE NOT NULL,
  period_end              DATE NOT NULL,
  calculated_grp_per_kwh  DECIMAL,
  currency_id             BIGINT REFERENCES currency(id),
  total_variable_charges  DECIMAL,
  total_kwh_invoiced      DECIMAL,
  verification_status     verification_status NOT NULL DEFAULT 'pending',
  verified_at             TIMESTAMPTZ,
  source_metadata         JSONB DEFAULT '{}',
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(project_id, operating_year)
);

CREATE INDEX IF NOT EXISTS idx_ref_price_project
  ON reference_price(project_id, operating_year);

CREATE INDEX IF NOT EXISTS idx_ref_price_org
  ON reference_price(organization_id);

COMMENT ON TABLE reference_price IS 'Annual Grid Reference Price calculated from Utility Reference Invoices. Used as P_Alternate in GRID tariff pricing and shortfall payment calculations.';
COMMENT ON COLUMN reference_price.operating_year IS 'Contract operating year (1-based). Year 1 = COD year.';
COMMENT ON COLUMN reference_price.calculated_grp_per_kwh IS 'Calculated GRP in local currency per kWh: total_variable_charges / total_kwh_invoiced.';
COMMENT ON COLUMN reference_price.total_variable_charges IS 'Sum of variable charges from Utility Reference Invoices (excl. VAT, demand charges, demand charge savings). Only charges between 6am-6pm.';
COMMENT ON COLUMN reference_price.total_kwh_invoiced IS 'Total kWh invoiced in Utility Reference Invoices for the operating year.';
COMMENT ON COLUMN reference_price.verification_status IS 'Status: pending, jointly_verified, disputed, estimated.';

-- RLS for reference_price
ALTER TABLE reference_price ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS reference_price_org_policy ON reference_price;
CREATE POLICY reference_price_org_policy ON reference_price
  FOR SELECT
  USING (is_org_member(organization_id));

DROP POLICY IF EXISTS reference_price_admin_modify_policy ON reference_price;
CREATE POLICY reference_price_admin_modify_policy ON reference_price
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS reference_price_service_policy ON reference_price;
CREATE POLICY reference_price_service_policy ON reference_price
  FOR ALL
  USING (auth.role() = 'service_role');

-- =============================================================================
-- D. Seed asset_type with equipment codes
-- =============================================================================
-- Uses ON CONFLICT to be idempotent. Assumes asset_type has UNIQUE on code.
-- If no UNIQUE exists, add one first.

DO $$
BEGIN
  -- Ensure code uniqueness for idempotent seeding
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE tablename = 'asset_type' AND indexdef LIKE '%code%' AND indexdef LIKE '%UNIQUE%'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
    WHERE tc.table_name = 'asset_type' AND ccu.column_name = 'code' AND tc.constraint_type = 'UNIQUE'
  ) THEN
    -- Add unique constraint if not already present
    CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_type_code ON asset_type(code);
  END IF;
END $$;

INSERT INTO asset_type (name, code, description) VALUES
  ('PV Module', 'pv_module', 'Photovoltaic solar panel/module'),
  ('Inverter', 'inverter', 'DC to AC power inverter'),
  ('Battery Energy Storage', 'bess', 'Battery energy storage system'),
  ('Power Conversion System', 'pcs', 'Power conversion system for BESS'),
  ('Generator', 'generator', 'Diesel generator (DG) or wind turbine generator (WTG)'),
  ('Transformer', 'transformer', 'Step-up/step-down transformer'),
  ('Power Plant Controller', 'ppc', 'Power plant controller / SCADA system'),
  ('Data Logger', 'data_logger', 'Data acquisition/logging device')
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- D2. Seed invoice_line_item_type for GRP charge classification
-- =============================================================================

-- Ensure code uniqueness for ON CONFLICT
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_line_item_type_code
  ON invoice_line_item_type(code);

INSERT INTO invoice_line_item_type (name, code, description) VALUES
  ('Variable Energy Charge', 'VARIABLE_ENERGY', 'Variable utility charge for energy consumed'),
  ('Demand Charge', 'DEMAND', 'Demand-based utility charge'),
  ('Fixed Charge', 'FIXED', 'Fixed utility service charge'),
  ('Tax / VAT', 'TAX', 'Tax or VAT line item')
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- F. CHECK Constraints — Data quality guards
-- =============================================================================

-- Production guarantee: guaranteed_kwh must be positive
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.check_constraints
    WHERE constraint_name = 'chk_production_guarantee_kwh_positive'
  ) THEN
    ALTER TABLE production_guarantee
      ADD CONSTRAINT chk_production_guarantee_kwh_positive
      CHECK (guaranteed_kwh > 0);
  END IF;
END $$;

-- Meter: metering_type valid values
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.check_constraints
    WHERE constraint_name = 'chk_meter_metering_type'
  ) THEN
    ALTER TABLE meter
      ADD CONSTRAINT chk_meter_metering_type
      CHECK (metering_type IS NULL OR metering_type IN ('net', 'export_only'));
  END IF;
END $$;

-- Asset: quantity must be positive
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.check_constraints
    WHERE constraint_name = 'chk_asset_quantity_positive'
  ) THEN
    ALTER TABLE asset
      ADD CONSTRAINT chk_asset_quantity_positive
      CHECK (quantity IS NULL OR quantity > 0);
  END IF;
END $$;

-- =============================================================================
-- G1. Unique index on meter(project_id, serial_number) for upsert support
-- =============================================================================
-- Required by onboard_project.sql Step 4.10: ON CONFLICT (project_id, serial_number)
-- Partial index excludes NULL serial_number (existing meters may lack serial numbers)

CREATE UNIQUE INDEX IF NOT EXISTS uq_meter_project_serial
  ON meter(project_id, serial_number)
  WHERE serial_number IS NOT NULL;

-- =============================================================================
-- G2. Unique index on counterparty for idempotent upsert
-- =============================================================================
-- Required by onboard_project.sql Step 4.1: ON CONFLICT (counterparty_type_id, LOWER(name))

CREATE UNIQUE INDEX IF NOT EXISTS uq_counterparty_type_name
  ON counterparty(counterparty_type_id, LOWER(name));

-- =============================================================================
-- H1. Amendment tracking — change_action enum
-- =============================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'change_action') THEN
    CREATE TYPE change_action AS ENUM ('ADDED', 'MODIFIED', 'REMOVED');
  END IF;
END $$;

-- =============================================================================
-- H2. ALTER clause — amendment linkage + current semantics
-- =============================================================================

ALTER TABLE clause
  ADD COLUMN IF NOT EXISTS contract_amendment_id  BIGINT REFERENCES contract_amendment(id),
  ADD COLUMN IF NOT EXISTS supersedes_clause_id   BIGINT REFERENCES clause(id),
  ADD COLUMN IF NOT EXISTS is_current             BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS change_action          change_action;

COMMENT ON COLUMN clause.contract_amendment_id IS 'NULL = original clause; non-NULL = introduced/modified by that amendment.';
COMMENT ON COLUMN clause.supersedes_clause_id IS 'Points to the clause row this one replaces (forms a version chain).';
COMMENT ON COLUMN clause.is_current IS 'true = active version; false = superseded by a newer clause.';
COMMENT ON COLUMN clause.change_action IS 'ADDED, MODIFIED, REMOVED (NULL for original clauses).';

CREATE INDEX IF NOT EXISTS idx_clause_contract_amendment
  ON clause(contract_amendment_id);

CREATE INDEX IF NOT EXISTS idx_clause_supersedes
  ON clause(supersedes_clause_id);

-- Partial unique index: enforce only one current version per logical identity
CREATE UNIQUE INDEX IF NOT EXISTS uq_clause_current_per_type_section
  ON clause(contract_id, clause_type_id, section_ref)
  WHERE is_current = true AND section_ref IS NOT NULL;

-- =============================================================================
-- H3. ALTER clause_tariff — amendment linkage + current semantics
-- =============================================================================

ALTER TABLE clause_tariff
  ADD COLUMN IF NOT EXISTS contract_amendment_id  BIGINT REFERENCES contract_amendment(id),
  ADD COLUMN IF NOT EXISTS supersedes_tariff_id   BIGINT REFERENCES clause_tariff(id),
  ADD COLUMN IF NOT EXISTS version                INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS is_current             BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS change_action          change_action;

COMMENT ON COLUMN clause_tariff.contract_amendment_id IS 'NULL = original tariff; non-NULL = introduced/modified by that amendment.';
COMMENT ON COLUMN clause_tariff.supersedes_tariff_id IS 'Points to the tariff row this one replaces (forms a version chain).';
COMMENT ON COLUMN clause_tariff.version IS 'Version number (1 = original, incremented on amendment).';
COMMENT ON COLUMN clause_tariff.is_current IS 'true = active version; false = superseded.';
COMMENT ON COLUMN clause_tariff.change_action IS 'ADDED, MODIFIED, REMOVED (NULL for original tariff rows).';

CREATE INDEX IF NOT EXISTS idx_clause_tariff_contract_amendment
  ON clause_tariff(contract_amendment_id);

CREATE INDEX IF NOT EXISTS idx_clause_tariff_supersedes
  ON clause_tariff(supersedes_tariff_id);

-- Versioned uniqueness: only one current row per (contract, tariff_group_key, validity window)
CREATE UNIQUE INDEX IF NOT EXISTS uq_clause_tariff_current_group_validity
  ON clause_tariff(contract_id, tariff_group_key, valid_from, COALESCE(valid_to, '9999-12-31'::date))
  WHERE tariff_group_key IS NOT NULL AND is_current = true;

-- =============================================================================
-- H4. Integrity triggers — auto-flip superseded rows
-- =============================================================================

-- Clause supersede trigger
CREATE OR REPLACE FUNCTION trg_clause_supersede() RETURNS trigger AS $$
BEGIN
  IF NEW.supersedes_clause_id IS NOT NULL THEN
    -- Validate: cannot supersede across contracts
    IF (SELECT contract_id FROM clause WHERE id = NEW.supersedes_clause_id) != NEW.contract_id THEN
      RAISE EXCEPTION 'Cannot supersede clause from different contract';
    END IF;
    -- Validate: cannot self-reference
    IF NEW.id = NEW.supersedes_clause_id THEN
      RAISE EXCEPTION 'Clause cannot supersede itself';
    END IF;
    -- Flip prior to non-current
    UPDATE clause SET is_current = false WHERE id = NEW.supersedes_clause_id;
  END IF;
  -- Auto-maintain contract.has_amendments
  IF NEW.contract_amendment_id IS NOT NULL THEN
    UPDATE contract SET has_amendments = true WHERE id = NEW.contract_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS clause_supersede_trigger ON clause;
CREATE TRIGGER clause_supersede_trigger
  AFTER INSERT ON clause
  FOR EACH ROW EXECUTE FUNCTION trg_clause_supersede();

-- Clause tariff supersede trigger
CREATE OR REPLACE FUNCTION trg_clause_tariff_supersede() RETURNS trigger AS $$
BEGIN
  IF NEW.supersedes_tariff_id IS NOT NULL THEN
    -- Validate: cannot supersede across contracts
    IF (SELECT contract_id FROM clause_tariff WHERE id = NEW.supersedes_tariff_id) != NEW.contract_id THEN
      RAISE EXCEPTION 'Cannot supersede tariff from different contract';
    END IF;
    -- Validate: cannot self-reference
    IF NEW.id = NEW.supersedes_tariff_id THEN
      RAISE EXCEPTION 'Clause tariff cannot supersede itself';
    END IF;
    -- Flip prior to non-current
    UPDATE clause_tariff SET is_current = false WHERE id = NEW.supersedes_tariff_id;
  END IF;
  -- Auto-maintain contract.has_amendments
  IF NEW.contract_amendment_id IS NOT NULL THEN
    UPDATE contract SET has_amendments = true WHERE id = NEW.contract_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS clause_tariff_supersede_trigger ON clause_tariff;
CREATE TRIGGER clause_tariff_supersede_trigger
  AFTER INSERT ON clause_tariff
  FOR EACH ROW EXECUTE FUNCTION trg_clause_tariff_supersede();

-- =============================================================================
-- H5. Views for current clauses/tariffs
-- =============================================================================

CREATE OR REPLACE VIEW clause_current_v AS
  SELECT * FROM clause WHERE is_current = true;

CREATE OR REPLACE VIEW clause_tariff_current_v AS
  SELECT * FROM clause_tariff WHERE is_current = true;

-- =============================================================================
-- I. Contract — Rename updated_by to created_by
-- =============================================================================
-- The contract table has updated_by UUID from migration 012. Rename to created_by.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'contract' AND column_name = 'updated_by'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'contract' AND column_name = 'created_by'
  ) THEN
    ALTER TABLE contract RENAME COLUMN updated_by TO created_by;
  END IF;
END $$;

COMMENT ON COLUMN contract.created_by IS 'UUID of auth.users who created this record';

-- =============================================================================
-- J. CREATE onboarding_preview — Server-side preview state storage
-- =============================================================================
-- Used by the two-phase onboarding service (preview → commit).
-- Preview data expires after 1 hour.

CREATE TABLE IF NOT EXISTS onboarding_preview (
  preview_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id   BIGINT NOT NULL REFERENCES organization(id),
  parsed_data       JSONB NOT NULL,
  file_hash         VARCHAR(64) NOT NULL,
  discrepancy_report JSONB,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  expires_at        TIMESTAMPTZ DEFAULT NOW() + INTERVAL '1 hour'
);

ALTER TABLE onboarding_preview ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS onboarding_preview_service_policy ON onboarding_preview;
CREATE POLICY onboarding_preview_service_policy ON onboarding_preview
  FOR ALL USING (auth.role() = 'service_role');

CREATE INDEX IF NOT EXISTS idx_onboarding_preview_expires
  ON onboarding_preview(expires_at);
