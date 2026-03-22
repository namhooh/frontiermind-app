-- =====================================================
-- Migration 066: Loan Repayment & Rental/Ancillary Charge Tables
-- =====================================================
-- Creates two period-level tables that parallel tariff_rate:
--   loan_repayment          — amortization rows for loan clause_tariffs
--   rental_ancillary_charge — monthly charges for non-energy clause_tariffs
--
-- Loan terms live as clause_tariff rows (energy_sale_type = LOAN).
-- Recurring charge terms live on existing non-energy clause_tariff rows.
-- These tables record the periodic schedule data (amounts per month).
--
-- Reconciliation with invoices is via existing
-- expected_invoice_line_item.clause_tariff_id /
-- invoice_line_item.contract_line_id joins (invoice → schedule direction).
--
-- Also renames tariff_rate.contract_year → operating_year for consistency
-- with the operating_year convention used across the codebase.
-- =====================================================

BEGIN;

SET statement_timeout = '300s';

-- ============================================================================
-- 0. Rename tariff_rate.contract_year → operating_year
-- ============================================================================
-- "contract_year" is confusing; codebase uses "operating year" everywhere
-- (oy_definition, oy_start_date, operating_year on new tables).
-- PostgreSQL RENAME COLUMN auto-updates indexes and constraints.
ALTER TABLE tariff_rate RENAME COLUMN contract_year TO operating_year;

-- ============================================================================
-- 1. loan_repayment — amortization schedule rows per loan clause_tariff
-- ============================================================================
-- Parallels tariff_rate: records period-level data for a clause_tariff.
-- Loan terms (opening_balance, interest_rate, loan_variant) are stored
-- in clause_tariff.logic_parameters JSONB.
--
-- Source field mapping (Revenue Masterfile "Loans" tab → unified columns):
--
--   ZL02 (amortization):
--     Excel "Payment"         → scheduled_amount
--     Excel "Principle"       → principal_amount
--     Excel "Interest"        → interest_amount
--     Excel "Closing Balance" → closing_balance
--     JSONB keys: payment, principal, interest, closing_balance
--
--   GC001 (interest_income):
--     Excel "Invoiced"           → scheduled_amount
--     Excel "Capital Repayment"  → principal_amount
--     Excel "Interest Income"    → interest_amount
--     (no closing balance in source)
--     JSONB keys: invoiced, capital_repayment, interest_income
--
--   iSAT01 (fixed_repayment):
--     No schedule rows yet. Fixed payment amount ($61,632/mo) stored in
--     clause_tariff.base_rate and logic_parameters.fixed_payment.
--
-- Loan clause_tariff rows (energy_sale_type = LOAN, tariff_type = FINANCE_LEASE):
--   ct#66 → ZL02  (contract#96, currency#1 USD)
--   ct#67 → GC001 (contract#16, currency#1 USD)
--   ct#68 → iSAT01 (no contract, currency#1 USD, needs_review=true)

CREATE TABLE IF NOT EXISTS loan_repayment (
    id                    BIGSERIAL PRIMARY KEY,
    clause_tariff_id      BIGINT NOT NULL REFERENCES clause_tariff(id),
    organization_id       BIGINT NOT NULL REFERENCES organization(id),

    contract_line_id      BIGINT REFERENCES contract_line(id),

    -- Period identification
    billing_month         DATE,
    billing_period_id     BIGINT REFERENCES billing_period(id),
    operating_year        INTEGER,

    -- Repayment decomposition
    scheduled_amount      NUMERIC(16, 2),    -- total repayment for the period
    principal_amount      NUMERIC(16, 2),    -- principal component
    interest_amount       NUMERIC(16, 2),    -- interest component
    closing_balance       NUMERIC(16, 2),    -- outstanding balance after payment
    billing_currency_id   BIGINT REFERENCES currency(id),

    -- Data quality
    data_quality          VARCHAR(20) NOT NULL DEFAULT 'ok',

    -- Provenance
    source                VARCHAR(100) NOT NULL DEFAULT 'manual',
    source_row_ref        VARCHAR(255),
    source_metadata       JSONB NOT NULL DEFAULT '{}',
    notes                 TEXT,

    -- Audit
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ
);

-- Unique: follows tariff_rate pattern (clause_tariff_id, billing_month)
CREATE UNIQUE INDEX IF NOT EXISTS uq_loan_repayment_month
    ON loan_repayment (clause_tariff_id, billing_month);

CREATE INDEX IF NOT EXISTS idx_loan_repayment_clause_tariff
    ON loan_repayment (clause_tariff_id);

CREATE INDEX IF NOT EXISTS idx_loan_repayment_billing_month
    ON loan_repayment (billing_month);

-- RLS
ALTER TABLE loan_repayment ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS loan_repayment_org_policy ON loan_repayment;
CREATE POLICY loan_repayment_org_policy ON loan_repayment
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS loan_repayment_admin_modify_policy ON loan_repayment;
CREATE POLICY loan_repayment_admin_modify_policy ON loan_repayment
    FOR ALL USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS loan_repayment_service_policy ON loan_repayment;
CREATE POLICY loan_repayment_service_policy ON loan_repayment
    FOR ALL USING (auth.role() = 'service_role');

-- ============================================================================
-- 2. rental_ancillary_charge — monthly charge rows per non-energy clause_tariff
-- ============================================================================
-- Parallels tariff_rate: records period-level scheduled amounts for
-- BESS capacity, equipment rental, O&M, lease, diesel, penalty charges.
--
-- Charge type is determined by the parent clause_tariff's energy_sale_type_id
-- (BESS_LEASE, EQUIPMENT_RENTAL_LEASE, OTHER_SERVICE, etc.)
--
-- Primary parent: clause_tariff_id (the non-energy tariff row)
-- Reconciliation parent: contract_line_id (the billing grain)
--
-- Source: Revenue Masterfile "Rental and Ancillary" tab
-- scheduled_amount = JSONB "amount" field per project per month
--
-- Project resolution (clause_tariff → contract_line → energy_sale_type):
--   LOI01:  ct#14  → cl#209 (BESS_LEASE,              base_rate=$2,000/mo)
--   AR01:   ct#46  → cl#184 (EQUIPMENT_RENTAL_LEASE,   base_rate=$9,050/mo)
--   QMM01:  ct#33  → cl#262 (BESS_LEASE,              base_rate=MGA 57,878/mo)
--   TWG01:  ct#45  → cl#267 (EQUIPMENT_RENTAL_LEASE,   base_rate=$306,250/mo)
--   TWG01:  ct#31  → cl#266 (OTHER_SERVICE / O&M,      base_rate=$39,583/mo)
--   AMP01:  ct#65  → cl#181 (EQUIPMENT_RENTAL_LEASE,   SKIPPED — placeholder data)
--
-- clause_tariff backfills (base_rate set from technical_specs where NULL):
--   ct#14  (LOI01 BESS): base_rate=2000, lp+={billing_frequency, charge_indexation: "US CPI"}
--   ct#31  (TWG01 O&M):  base_rate=39583, lp+={billing_frequency}
--   ct#65  (AMP01):       base_rate=4605, lp+={billing_frequency, charge_indexation: "0.02"}

CREATE TABLE IF NOT EXISTS rental_ancillary_charge (
    id                    BIGSERIAL PRIMARY KEY,
    clause_tariff_id      BIGINT NOT NULL REFERENCES clause_tariff(id),
    organization_id       BIGINT NOT NULL REFERENCES organization(id),
    contract_line_id      BIGINT REFERENCES contract_line(id),

    -- Period identification
    billing_month         DATE NOT NULL,
    billing_period_id     BIGINT REFERENCES billing_period(id),
    operating_year        INTEGER,

    -- Amount
    scheduled_amount      NUMERIC(16, 2),
    billing_currency_id   BIGINT REFERENCES currency(id),

    -- Data quality
    data_quality          VARCHAR(20) NOT NULL DEFAULT 'ok',

    -- Provenance
    source                VARCHAR(100) NOT NULL DEFAULT 'manual',
    source_row_ref        VARCHAR(255),
    source_metadata       JSONB NOT NULL DEFAULT '{}',
    notes                 TEXT,

    -- Audit
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ
);

-- Unique at contract_line grain per clause_tariff per month
-- Handles QMM01 two BESS lines, ZL02 multiple O&M lines
CREATE UNIQUE INDEX IF NOT EXISTS uq_rental_charge_line_month
    ON rental_ancillary_charge (clause_tariff_id, contract_line_id, billing_month);

CREATE INDEX IF NOT EXISTS idx_rental_charge_clause_tariff
    ON rental_ancillary_charge (clause_tariff_id);

CREATE INDEX IF NOT EXISTS idx_rental_charge_contract_line
    ON rental_ancillary_charge (contract_line_id);

CREATE INDEX IF NOT EXISTS idx_rental_charge_billing_month
    ON rental_ancillary_charge (billing_month);

-- RLS
ALTER TABLE rental_ancillary_charge ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rental_charge_org_policy ON rental_ancillary_charge;
CREATE POLICY rental_charge_org_policy ON rental_ancillary_charge
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS rental_charge_admin_modify_policy ON rental_ancillary_charge;
CREATE POLICY rental_charge_admin_modify_policy ON rental_ancillary_charge
    FOR ALL USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS rental_charge_service_policy ON rental_ancillary_charge;
CREATE POLICY rental_charge_service_policy ON rental_ancillary_charge
    FOR ALL USING (auth.role() = 'service_role');

COMMIT;
