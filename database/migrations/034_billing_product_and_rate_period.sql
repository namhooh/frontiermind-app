-- Migration 034: Billing Product Capture & Tariff Rate Versioning
-- Date: 2026-02-19
-- Phase: 9.1 - Billing Product Reference Tables, Contract Billing Products, Tariff Rate Periods
--
-- Changes:
--   A. CREATE billing_product — Org-scoped billing product reference table (Sage product codes)
--   B. CREATE contract_billing_product — Junction: which billing products apply to a contract
--   C. CREATE tariff_rate_period — Effective rate history per clause_tariff (annual escalation tracking)
--   D. Seed billing_product with CBE product codes from dim_finance_product_code
--   E. RLS policies and indexes for all new tables

-- =============================================================================
-- A. CREATE billing_product — Org-scoped billing product reference
-- =============================================================================
-- Stores Sage product codes (e.g., GHREVS001 = "Metered Energy") for each organization.
-- These describe WHAT is billed. The contract_billing_product junction controls
-- which products are relevant per contract.

CREATE TABLE IF NOT EXISTS billing_product (
  id              BIGSERIAL PRIMARY KEY,
  code            VARCHAR(50) NOT NULL,
  name            VARCHAR(255),
  organization_id BIGINT REFERENCES organization(id),
  is_active       BOOLEAN DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE billing_product IS 'Org-scoped billing product reference table. Stores Sage/ERP product codes (e.g., GHREVS001 = "Metered Energy"). NULL organization_id = platform-level canonical.';
COMMENT ON COLUMN billing_product.code IS 'Product code from finance/ERP system (e.g., GHREVS001, ENER004).';
COMMENT ON COLUMN billing_product.name IS 'Human-readable product name (e.g., "Metered Energy (EMetered)").';
COMMENT ON COLUMN billing_product.organization_id IS 'Owning organization. NULL = platform-level canonical product.';

-- Partial unique indexes: prevent duplicate canonical rows (NULL ≠ NULL in standard UNIQUE)
-- and enforce uniqueness within each organization separately.
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_product_canonical
  ON billing_product(code) WHERE organization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_product_org
  ON billing_product(code, organization_id) WHERE organization_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_billing_product_org_lookup
  ON billing_product(organization_id);

-- RLS for billing_product
ALTER TABLE billing_product ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS billing_product_org_policy ON billing_product;
CREATE POLICY billing_product_org_policy ON billing_product
  FOR SELECT
  USING (organization_id IS NULL OR is_org_member(organization_id));

DROP POLICY IF EXISTS billing_product_admin_modify_policy ON billing_product;
CREATE POLICY billing_product_admin_modify_policy ON billing_product
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS billing_product_service_policy ON billing_product;
CREATE POLICY billing_product_service_policy ON billing_product
  FOR ALL
  USING (auth.role() = 'service_role');

-- =============================================================================
-- B. CREATE contract_billing_product — Junction table
-- =============================================================================
-- Links contracts to their applicable billing products. One contract can generate
-- multiple invoice line types (e.g., metered energy + available energy).
-- Product codes describe WHAT is billed; tariff terms (clause_tariff) describe HOW.

CREATE TABLE IF NOT EXISTS contract_billing_product (
  id                 BIGSERIAL PRIMARY KEY,
  contract_id        BIGINT NOT NULL REFERENCES contract(id),
  billing_product_id BIGINT NOT NULL REFERENCES billing_product(id),
  is_primary         BOOLEAN DEFAULT false,
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(contract_id, billing_product_id)
);

COMMENT ON TABLE contract_billing_product IS 'Junction: which billing products apply to a contract. One contract can generate multiple invoice line types with different product codes.';
COMMENT ON COLUMN contract_billing_product.is_primary IS 'Marks the main revenue line (e.g., metered energy vs available energy).';
COMMENT ON COLUMN contract_billing_product.notes IS 'Optional description (e.g., "Metered solar energy").';

CREATE INDEX IF NOT EXISTS idx_contract_billing_product_contract
  ON contract_billing_product(contract_id);

CREATE INDEX IF NOT EXISTS idx_contract_billing_product_product
  ON contract_billing_product(billing_product_id);

-- Only one primary billing product per contract
CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_billing_product_primary
  ON contract_billing_product(contract_id) WHERE is_primary = true;

-- Cross-tenant validation: billing_product must be canonical (NULL org)
-- or belong to the same organization as the contract.
CREATE OR REPLACE FUNCTION trg_validate_billing_product_org()
RETURNS TRIGGER AS $$
DECLARE
  v_bp_org_id BIGINT;
  v_contract_org_id BIGINT;
BEGIN
  SELECT organization_id INTO v_bp_org_id
    FROM billing_product WHERE id = NEW.billing_product_id;

  -- Canonical (platform-level) products are always allowed
  IF v_bp_org_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT organization_id INTO v_contract_org_id
    FROM contract WHERE id = NEW.contract_id;

  IF v_bp_org_id IS DISTINCT FROM v_contract_org_id THEN
    RAISE EXCEPTION 'billing_product (org_id=%) does not belong to contract organization (org_id=%)',
      v_bp_org_id, v_contract_org_id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_contract_billing_product_org_check
  BEFORE INSERT OR UPDATE ON contract_billing_product
  FOR EACH ROW EXECUTE FUNCTION trg_validate_billing_product_org();

-- RLS for contract_billing_product
ALTER TABLE contract_billing_product ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS contract_billing_product_org_policy ON contract_billing_product;
CREATE POLICY contract_billing_product_org_policy ON contract_billing_product
  FOR SELECT
  USING (is_org_member(get_contract_org_id(contract_id)));

DROP POLICY IF EXISTS contract_billing_product_admin_modify_policy ON contract_billing_product;
CREATE POLICY contract_billing_product_admin_modify_policy ON contract_billing_product
  FOR ALL
  USING (is_org_admin(get_contract_org_id(contract_id)));

DROP POLICY IF EXISTS contract_billing_product_service_policy ON contract_billing_product;
CREATE POLICY contract_billing_product_service_policy ON contract_billing_product
  FOR ALL
  USING (auth.role() = 'service_role');

-- =============================================================================
-- C. CREATE tariff_rate_period — Effective rate history per clause_tariff
-- =============================================================================
-- Tracks the effective rate after annual escalation. clause_tariff.base_rate stays
-- as the original contractual rate (never modified after onboarding). The
-- version/is_current/supersedes_tariff_id columns on clause_tariff (migration 033)
-- track contract AMENDMENTS, not rate escalation.
--
-- Lifecycle:
--   Onboarding → clause_tariff created (base_rate = original contractual rate)
--              → tariff_rate_period Year 1 created (effective_rate = base_rate, is_current = true)
--   Annual escalation → New tariff_rate_period row inserted
--                     → Previous period: is_current = false, period_end set
--                     → New period: is_current = true, effective_rate = calculated value
--   Invoicing → JOIN tariff_rate_period WHERE is_current = true

CREATE TABLE IF NOT EXISTS tariff_rate_period (
  id                BIGSERIAL PRIMARY KEY,
  clause_tariff_id  BIGINT NOT NULL REFERENCES clause_tariff(id),
  contract_year     INTEGER NOT NULL,
  period_start      DATE NOT NULL,
  period_end        DATE,
  effective_rate    DECIMAL NOT NULL,
  currency_id       BIGINT REFERENCES currency(id),
  calculation_basis TEXT,
  is_current        BOOLEAN NOT NULL DEFAULT false,
  approved_by       UUID REFERENCES auth.users(id),
  approved_at       TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(clause_tariff_id, contract_year),
  CHECK (contract_year >= 1),
  CHECK (effective_rate >= 0),
  CHECK (period_end IS NULL OR period_end >= period_start)
);

COMMENT ON TABLE tariff_rate_period IS 'Effective rate history per clause_tariff. Tracks rate after annual escalation (FIXED_INCREASE, PERCENTAGE, US_CPI, REBASED_MARKET_PRICE). clause_tariff.base_rate = original contractual rate; tariff_rate_period.effective_rate = rate after escalation.';
COMMENT ON COLUMN tariff_rate_period.contract_year IS 'Contract operating year (1-based). Year 1 = COD year.';
COMMENT ON COLUMN tariff_rate_period.effective_rate IS 'The rate after escalation, used for invoicing.';
COMMENT ON COLUMN tariff_rate_period.calculation_basis IS 'Human-readable explanation: "Base 0.1087 + 2.5% CPI (2026)" or "GRP rebased: 0.1365 * 0.79".';
COMMENT ON COLUMN tariff_rate_period.is_current IS 'true = active rate for current billing; false = historical.';
COMMENT ON COLUMN tariff_rate_period.approved_by IS 'Who approved this rate (for audit trail).';

CREATE UNIQUE INDEX IF NOT EXISTS idx_tariff_rate_period_current
  ON tariff_rate_period(clause_tariff_id) WHERE is_current = true;

CREATE INDEX IF NOT EXISTS idx_tariff_rate_period_date_range
  ON tariff_rate_period(clause_tariff_id, period_start);

-- RLS for tariff_rate_period
ALTER TABLE tariff_rate_period ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tariff_rate_period_org_policy ON tariff_rate_period;
CREATE POLICY tariff_rate_period_org_policy ON tariff_rate_period
  FOR SELECT
  USING (is_org_member(
    (SELECT organization_id FROM clause_tariff WHERE id = clause_tariff_id)
  ));

DROP POLICY IF EXISTS tariff_rate_period_admin_modify_policy ON tariff_rate_period;
CREATE POLICY tariff_rate_period_admin_modify_policy ON tariff_rate_period
  FOR ALL
  USING (is_org_admin(
    (SELECT organization_id FROM clause_tariff WHERE id = clause_tariff_id)
  ));

DROP POLICY IF EXISTS tariff_rate_period_service_policy ON tariff_rate_period;
CREATE POLICY tariff_rate_period_service_policy ON tariff_rate_period
  FOR ALL
  USING (auth.role() = 'service_role');

-- =============================================================================
-- D. Seed billing_product with CBE product codes
-- =============================================================================
-- Source: CBE_data_extracts/dim_finance_product_code.csv (~110 rows)
-- All seeded with organization_id = NULL (platform-level) initially.
-- The onboarding pipeline will associate them with specific organizations.
-- Using ON CONFLICT to be idempotent.

INSERT INTO billing_product (code, name) VALUES
  ('PCM00_PROSER', 'Professional Service'),
  ('PDW0_PROSER', 'Professional fees'),
  ('PE000_CUSTOMFEE', 'Custom Clearance Fees'),
  ('ENER004', 'Minimum Offtake'),
  ('GHREVS001', 'Metered Energy (EMetered)'),
  ('PD0V_CONENG', 'Construction and Engineering'),
  ('PCH00_CORPORATEFEES', 'CORPORATE Services'),
  ('PG000_REGAUT', 'Regulatory Authority'),
  ('PD0V_CUSTOM', 'Custom Duties & Assessment fee'),
  ('MOREVS001', 'Rent'),
  ('RWREVS001', NULL),
  ('NIREVS008', 'Grid (EMetered)'),
  ('PGWV7_ACCSER', 'Accounting Services'),
  ('PA0V_OTHER', 'Other expenses'),
  ('PA0V_TRAVEL', 'Travel'),
  ('NIREVS012', 'Sourced E-Metered Energy'),
  ('NIREVS011', 'Generator (EAvailable)'),
  ('PCM00_CONSUL', 'Consultancy'),
  ('PCM00_LEGSER', 'Legal Services'),
  ('NIREVS002', 'Available Energy (EAvailable)'),
  ('PD00_INSUR', 'Insurance'),
  ('PA0V_ACCT', 'Accounting and taxation Services'),
  ('PG000_ROBOT', 'Robot Cleaners'),
  ('PCM00_INSURA', 'Insurance'),
  ('RENT001', NULL),
  ('PD00_CONENG', 'Construction and Engineering'),
  ('PCH00_FSCFEES', 'FSC Fees'),
  ('PCH00_CONENG', 'Construction & Engineering Services'),
  ('PCM0V_RENT', 'RENT'),
  ('GHREV002', 'Grid (E Metered)'),
  ('EGREVS001', 'Metered Energy (EMetered)'),
  ('LEGAL', 'Legal Fees'),
  ('PD0V_OPEMAI', 'Operations & Maintenance'),
  ('PD0V_ACCSER', 'Accounting Services'),
  ('PCH00_CRSFEES', 'CRS Fees'),
  ('KEREVS003', 'Loisaba HQ (EMetered)'),
  ('PD0V_TRAVEL', 'Travel'),
  ('PCH00-AUDIT', 'Audit'),
  ('KEREVS006', 'Substation 1 (EMetered)'),
  ('PGW02_CONENG', 'Construction & Engineering Services'),
  ('PD0V_LEGSER', 'Legal Services'),
  ('PCM00_CONENG', 'Construction & Engineering Services'),
  ('PG000_INSURA', 'Insurance'),
  ('PCH00_ROCFEES', 'ROC Fees'),
  ('PCH00_INSURA', 'Insurance'),
  ('PE000_REGAUT', 'Regulatory Authority'),
  ('PA0V_RENT', 'RENT'),
  ('CUSTOM-DUTY', 'Custom duty'),
  ('PE000_INSURA', 'Insurance'),
  ('PE00V_ACCFEE', 'Accounting Fees'),
  ('PEW01_CONENG', 'Construction & Engineering Services'),
  ('MAREVS004', 'Early Operating Energy'),
  ('PCM_OPEMAI', 'Operations and Maintenance'),
  ('PEW05_LEGFEE', 'Legal Fees'),
  ('MAREVS001', 'Metered Energy (EMetered)'),
  ('PCM00_SOFTWA', 'Software'),
  ('PD00_CONSULT', 'Consultancy'),
  ('MARES006', 'Lease'),
  ('RENT002', NULL),
  ('NIREVS009', 'Generator (EMetered)'),
  ('PGW07_OPEMAI', 'Operation and Maintenance'),
  ('PGW07_CONENG', 'Construction & Engineering Services'),
  ('KEREVS008', 'Rent'),
  ('MDREV', 'Camp Power'),
  ('SAREVRS001', NULL),
  ('NIREVS014', 'Security Fee'),
  ('NIREVS001', 'Metered Energy (EMetered)'),
  ('PCM00_ENVSOC', 'Environmental & Social Diligence'),
  ('NIREVS010', 'Grid (EAvailable)'),
  ('REVLLC', NULL),
  ('PGWV7_AUDIT', 'Audit'),
  ('NIREVS013', 'Service Fee'),
  ('PGWV5_CONENG', 'Construction & Engineering Services'),
  ('MAREVS003', 'BESS Capacity Charge'),
  ('PCH00_FACTA', 'FACTA'),
  ('KEREVS007', 'Substation 3 (EMetered)'),
  ('PGWV7_CONSUL', 'Consultancy'),
  ('NIREVS015', 'Additional Expenses'),
  ('KEREVS002', 'Available Energy (EAvailable)'),
  ('PCM5V_RENT', 'RENT'),
  ('PA0V_LEGSER', 'Legal'),
  ('REVS005', NULL),
  ('MARES005', 'Metered Energy (EMetered)'),
  ('PCM00_GEN', 'G&A and Other Direct Costs'),
  ('PCH00_INSTALER', 'Solar Installer'),
  ('PD0V_LICENC', 'Licenses and Permit Fees'),
  ('PA0V_RECRUIT', 'Recruitment Fees'),
  ('MAREVS002', 'Deemed Energy (Eavailable)'),
  ('PCHWV_ACCTAXSER', 'Accounting and taxation Services'),
  ('GHREVS002', 'Available Energy (EAvailable)'),
  ('PD0V_DUEDIL', 'Due Diligence'),
  ('KEREVS004', 'Loisaba Camp (EMetered)'),
  ('PD0V_AUDIT', 'Audit Services'),
  ('ENER002', 'Metered Energy (EMetered)'),
  ('PGWV7_COUPOS', 'Courier & Postage'),
  ('MOREVS002', 'Operations & Maintenance (O&M)'),
  ('ENER001', 'Early Operating or Test Energy'),
  ('PEW03_OPEMAI', 'Operations and Maintenance'),
  ('KEREVS009', 'Rental Income'),
  ('GHREV001', 'Grid (E Available)'),
  ('KEREVS010', 'Total Energy'),
  ('REVD', NULL),
  ('EGREVS002', 'Available Energy (Eavailable)'),
  ('KEREVS001', 'Metered Energy (EMetered)'),
  ('PD0V_CONSULT', 'Consultancy'),
  ('ENER003', 'Available Energy (EAvailable)'),
  ('SERV001', NULL),
  ('PCM00_MODDEV', 'Modelling and Development')
ON CONFLICT (code) WHERE organization_id IS NULL DO NOTHING;
