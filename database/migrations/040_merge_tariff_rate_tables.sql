-- =============================================================================
-- Migration 040: Merge tariff_annual_rate + tariff_monthly_rate → tariff_rate
-- =============================================================================
-- Date: 2026-02-23
--
-- Creates a unified tariff_rate table with:
--   - Four-currency effective rate columns (contract, hard, local, billing)
--   - JSONB calc_detail for formula-specific intermediary variables
--   - Full FX audit trail with separate rate FKs per currency pair
--   - Calculation lineage (reference_price_id, discount_pct_applied, formula_version)
--   - Explicit row typing (annual vs monthly) and calculation status
--
-- Data migration:
--   - tariff_annual_rate rows → rate_granularity = 'annual'
--   - tariff_monthly_rate rows → rate_granularity = 'monthly'
--   - Old tables are dropped at the end of this migration
--
-- Current data: Only MOH01 has rows (1 annual, 5 monthly). Clean migration.
-- =============================================================================

BEGIN;

-- =============================================================================
-- A. Create enums
-- =============================================================================

DO $$ BEGIN
  CREATE TYPE rate_granularity AS ENUM ('annual', 'monthly');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE calc_status AS ENUM ('pending', 'computed', 'approved', 'superseded');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE contract_ccy_role AS ENUM ('hard', 'local', 'billing');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;


-- =============================================================================
-- B. Create tariff_rate table
-- =============================================================================

CREATE TABLE IF NOT EXISTS tariff_rate (
    id                          BIGSERIAL PRIMARY KEY,
    clause_tariff_id            BIGINT NOT NULL REFERENCES clause_tariff(id) ON DELETE CASCADE,
    contract_year               INTEGER NOT NULL,
    rate_granularity            rate_granularity NOT NULL,
    billing_month               DATE,               -- NULL for annual; first-of-month for monthly
    period_start                DATE NOT NULL,
    period_end                  DATE,

    -- ═══ CURRENCY FKs ═══
    hard_currency_id            BIGINT NOT NULL REFERENCES currency(id),
    local_currency_id           BIGINT NOT NULL REFERENCES currency(id),
    billing_currency_id         BIGINT NOT NULL REFERENCES currency(id),

    -- ═══ FX AUDIT TRAIL ═══
    fx_rate_hard_id             BIGINT REFERENCES exchange_rate(id),  -- NULL if hard=USD
    fx_rate_local_id            BIGINT REFERENCES exchange_rate(id),  -- NULL if local=USD

    -- ═══ EFFECTIVE RATE (universal output, four currencies) ═══
    effective_rate_contract_ccy NUMERIC(18,8),
    effective_rate_hard_ccy     NUMERIC(18,8),
    effective_rate_local_ccy    NUMERIC(18,8),
    effective_rate_billing_ccy  NUMERIC(18,8),
    effective_rate_contract_role contract_ccy_role,  -- nullable, no default; engine sets explicitly

    -- ═══ FORMULA-SPECIFIC INTERMEDIARIES ═══
    calc_detail                 JSONB,              -- escalation-type-specific variables in 4-ccy format

    -- ═══ RATE DETERMINATION ═══
    rate_binding                VARCHAR(20) NOT NULL DEFAULT 'fixed',

    -- ═══ CALCULATION LINEAGE ═══
    reference_price_id          BIGINT REFERENCES reference_price(id),
    discount_pct_applied        NUMERIC(5,4),       -- e.g., 0.2200 for 22%
    formula_version             VARCHAR(30),         -- e.g., 'rebased_v1'

    -- ═══ STATUS & METADATA ═══
    calc_status                 calc_status NOT NULL DEFAULT 'pending',
    calculation_basis           TEXT,
    is_current                  BOOLEAN NOT NULL DEFAULT false,
    approved_by                 UUID,
    approved_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ,

    -- ═══ ROW INTEGRITY CHECKS ═══
    CONSTRAINT chk_granularity_annual CHECK (
        rate_granularity != 'annual' OR billing_month IS NULL
    ),
    CONSTRAINT chk_granularity_monthly CHECK (
        rate_granularity != 'monthly' OR (
            billing_month IS NOT NULL
            AND billing_month = date_trunc('month', billing_month)::date
            AND period_start = billing_month
        )
    ),
    CONSTRAINT chk_billing_ccy_is_hard_or_local CHECK (
        billing_currency_id = hard_currency_id
        OR billing_currency_id = local_currency_id
    ),
    CONSTRAINT chk_rates_non_negative CHECK (
        (effective_rate_hard_ccy IS NULL OR effective_rate_hard_ccy >= 0)
        AND (effective_rate_local_ccy IS NULL OR effective_rate_local_ccy >= 0)
        AND (effective_rate_billing_ccy IS NULL OR effective_rate_billing_ccy >= 0)
    ),
    CONSTRAINT chk_effective_rate_contract_role CHECK (
        effective_rate_contract_ccy IS NULL
        OR effective_rate_contract_role IS NULL
        OR CASE effective_rate_contract_role
            WHEN 'hard' THEN effective_rate_contract_ccy = effective_rate_hard_ccy
            WHEN 'local' THEN effective_rate_contract_ccy = effective_rate_local_ccy
            WHEN 'billing' THEN effective_rate_contract_ccy = effective_rate_billing_ccy
        END
    ),
    CONSTRAINT chk_computed_has_rate CHECK (
        calc_status NOT IN ('computed', 'approved')
        OR effective_rate_billing_ccy IS NOT NULL
    ),
    CONSTRAINT chk_period_dates CHECK (
        period_end IS NULL OR period_end >= period_start
    ),
    CONSTRAINT chk_rate_binding_values CHECK (
        rate_binding IN ('floor', 'ceiling', 'discounted', 'fixed')
    )
);


-- =============================================================================
-- C. Indexes
-- =============================================================================

-- Annual: one row per tariff per year
CREATE UNIQUE INDEX IF NOT EXISTS uq_tariff_rate_annual
    ON tariff_rate (clause_tariff_id, contract_year)
    WHERE rate_granularity = 'annual';

-- Monthly: one row per tariff per billing month
CREATE UNIQUE INDEX IF NOT EXISTS uq_tariff_rate_monthly
    ON tariff_rate (clause_tariff_id, billing_month)
    WHERE rate_granularity = 'monthly';

-- One current annual row per tariff
CREATE UNIQUE INDEX IF NOT EXISTS uq_tariff_rate_current_annual
    ON tariff_rate (clause_tariff_id)
    WHERE is_current = true AND rate_granularity = 'annual';

-- One current monthly row per tariff
CREATE UNIQUE INDEX IF NOT EXISTS uq_tariff_rate_current_monthly
    ON tariff_rate (clause_tariff_id)
    WHERE is_current = true AND rate_granularity = 'monthly';

CREATE INDEX IF NOT EXISTS idx_tariff_rate_clause ON tariff_rate (clause_tariff_id);
CREATE INDEX IF NOT EXISTS idx_tariff_rate_billing_month ON tariff_rate (billing_month)
    WHERE rate_granularity = 'monthly';

-- GIN index for JSONB queries on calc_detail
CREATE INDEX IF NOT EXISTS idx_tariff_rate_calc_detail ON tariff_rate USING gin (calc_detail);


-- =============================================================================
-- D. RLS (idempotent — safe to re-run)
-- =============================================================================

ALTER TABLE tariff_rate ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tariff_rate_org_policy ON tariff_rate;
CREATE POLICY tariff_rate_org_policy ON tariff_rate
    FOR SELECT USING (is_org_member(
        (SELECT organization_id FROM clause_tariff WHERE id = clause_tariff_id)
    ));

DROP POLICY IF EXISTS tariff_rate_admin_modify_policy ON tariff_rate;
CREATE POLICY tariff_rate_admin_modify_policy ON tariff_rate
    FOR ALL USING (is_org_admin(
        (SELECT organization_id FROM clause_tariff WHERE id = clause_tariff_id)
    ));

DROP POLICY IF EXISTS tariff_rate_service_policy ON tariff_rate;
CREATE POLICY tariff_rate_service_policy ON tariff_rate
    FOR ALL USING (auth.role() = 'service_role');


-- =============================================================================
-- E. Migrate tariff_annual_rate → annual rows
-- =============================================================================
-- billing_currency_id = clause_tariff.currency_id (billing currency, per onboarding)
-- local_currency_id   = clause_tariff.currency_id (billing = local for current projects)
-- hard_currency_id    = USD (default for current projects)

INSERT INTO tariff_rate (
    clause_tariff_id, contract_year, rate_granularity,
    billing_month, period_start, period_end,
    hard_currency_id, local_currency_id, billing_currency_id,
    fx_rate_hard_id, fx_rate_local_id,
    effective_rate_contract_ccy, effective_rate_hard_ccy,
    effective_rate_local_ccy, effective_rate_billing_ccy,
    effective_rate_contract_role,
    calc_detail,
    rate_binding,
    calc_status, calculation_basis, is_current,
    approved_at, created_at
)
SELECT
    tar.clause_tariff_id,
    tar.contract_year,
    'annual'::rate_granularity,
    NULL,                                       -- billing_month
    tar.period_start,
    tar.period_end,
    -- hard_currency_id = USD
    (SELECT id FROM currency WHERE code = 'USD'),
    -- local_currency_id: for REBASED = market_ref (e.g. GHS); else = clause_tariff.currency_id
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' AND ct.market_ref_currency_id IS NOT NULL
         THEN ct.market_ref_currency_id
         ELSE ct.currency_id END,
    -- billing_currency_id: for REBASED = market_ref (GHS, billing in local); else = clause_tariff.currency_id
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' AND ct.market_ref_currency_id IS NOT NULL
         THEN ct.market_ref_currency_id
         ELSE ct.currency_id END,
    NULL,                                       -- fx_rate_hard_id (hard=USD → NULL)
    NULL,                                       -- fx_rate_local_id (populated by engine re-run)
    -- effective_rate: existing value is in the tariff's currency
    -- For REBASED_MARKET_PRICE: effective_tariff is the representative rate in local ccy
    -- For deterministic same-ccy: effective_tariff is the same across all columns
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' THEN tar.effective_tariff
         ELSE tar.effective_tariff END,         -- contract_ccy
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' THEN NULL  -- engine must re-compute USD
         ELSE tar.effective_tariff END,         -- hard_ccy (same-ccy for deterministic)
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' THEN tar.effective_tariff
         ELSE tar.effective_tariff END,         -- local_ccy
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' THEN tar.effective_tariff
         ELSE tar.effective_tariff END,         -- billing_ccy
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' THEN 'local'::contract_ccy_role
         ELSE 'hard'::contract_ccy_role END,    -- contract_role
    NULL,                                       -- calc_detail (populated by engine re-run)
    'fixed',                                    -- rate_binding (annual rows use fixed)
    CASE WHEN tar.effective_tariff IS NOT NULL THEN 'computed'::calc_status
         ELSE 'pending'::calc_status END,
    tar.calculation_basis,
    tar.is_current,
    tar.approved_at,
    tar.created_at
FROM tariff_annual_rate tar
JOIN clause_tariff ct ON ct.id = tar.clause_tariff_id
JOIN escalation_type esc ON esc.id = ct.escalation_type_id;


-- =============================================================================
-- F. Migrate tariff_monthly_rate → monthly rows
-- =============================================================================
-- For monthly rows we need to reconstruct values from the old schema:
-- effective_rate_local_ccy = effective_tariff_local
-- effective_rate_hard_ccy = effective_tariff_local / exchange_rate.rate
-- effective_rate_billing_ccy = effective_rate_local_ccy (billing=local for MOH01)
-- effective_rate_contract_ccy = effective_rate_local_ccy (contract_role='local')

INSERT INTO tariff_rate (
    clause_tariff_id, contract_year, rate_granularity,
    billing_month, period_start, period_end,
    hard_currency_id, local_currency_id, billing_currency_id,
    fx_rate_hard_id, fx_rate_local_id,
    effective_rate_contract_ccy, effective_rate_hard_ccy,
    effective_rate_local_ccy, effective_rate_billing_ccy,
    effective_rate_contract_role,
    calc_detail,
    rate_binding,
    reference_price_id,
    calc_status, calculation_basis, is_current,
    created_at
)
SELECT
    tar.clause_tariff_id,
    tar.contract_year,
    'monthly'::rate_granularity,
    tmr.billing_month,
    tmr.billing_month,                          -- period_start = billing_month for monthly
    (tmr.billing_month + interval '1 month' - interval '1 day')::date,  -- period_end = last day of month
    -- hard_currency_id = USD
    (SELECT id FROM currency WHERE code = 'USD'),
    -- local_currency_id: for REBASED = market_ref (e.g. GHS); else = clause_tariff.currency_id
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' AND ct.market_ref_currency_id IS NOT NULL
         THEN ct.market_ref_currency_id
         ELSE ct.currency_id END,
    -- billing_currency_id: for REBASED = market_ref (GHS, billing in local); else = clause_tariff.currency_id
    CASE WHEN esc.code = 'REBASED_MARKET_PRICE' AND ct.market_ref_currency_id IS NOT NULL
         THEN ct.market_ref_currency_id
         ELSE ct.currency_id END,
    NULL,                                       -- fx_rate_hard_id (hard=USD → NULL)
    tmr.exchange_rate_id,                       -- fx_rate_local_id
    -- effective_rate_contract_ccy = local (contract_role='local')
    tmr.effective_tariff_local,
    -- effective_rate_hard_ccy = local / fx_rate
    CASE WHEN er.rate IS NOT NULL AND er.rate > 0
         THEN ROUND(tmr.effective_tariff_local / er.rate, 8)
         ELSE NULL END,
    -- effective_rate_local_ccy
    tmr.effective_tariff_local,
    -- effective_rate_billing_ccy = local (billing=local for MOH01)
    tmr.effective_tariff_local,
    'local'::contract_ccy_role,
    -- calc_detail: reconstruct floor/ceiling/discounted_base from monthly_rate + FX
    CASE WHEN tmr.floor_local IS NOT NULL THEN
        jsonb_build_object(
            'floor', jsonb_build_object(
                'contract_ccy', CASE WHEN er.rate IS NOT NULL AND er.rate > 0
                    THEN ROUND(tmr.floor_local / er.rate, 8) ELSE NULL END,
                'hard_ccy', CASE WHEN er.rate IS NOT NULL AND er.rate > 0
                    THEN ROUND(tmr.floor_local / er.rate, 8) ELSE NULL END,
                'local_ccy', tmr.floor_local,
                'billing_ccy', tmr.floor_local,
                'contract_role', 'hard'
            ),
            'ceiling', jsonb_build_object(
                'contract_ccy', CASE WHEN er.rate IS NOT NULL AND er.rate > 0
                    THEN ROUND(tmr.ceiling_local / er.rate, 8) ELSE NULL END,
                'hard_ccy', CASE WHEN er.rate IS NOT NULL AND er.rate > 0
                    THEN ROUND(tmr.ceiling_local / er.rate, 8) ELSE NULL END,
                'local_ccy', tmr.ceiling_local,
                'billing_ccy', tmr.ceiling_local,
                'contract_role', 'hard'
            ),
            'discounted_base', jsonb_build_object(
                'contract_ccy', tmr.discounted_grp_local,
                'hard_ccy', CASE WHEN er.rate IS NOT NULL AND er.rate > 0
                    THEN ROUND(tmr.discounted_grp_local / er.rate, 8) ELSE NULL END,
                'local_ccy', tmr.discounted_grp_local,
                'billing_ccy', tmr.discounted_grp_local,
                'contract_role', 'local'
            )
        )
    ELSE NULL END,
    tmr.rate_binding,
    -- reference_price_id: match by billing_month to reference_price.period_start where observation_type='monthly'
    (SELECT rp.id FROM reference_price rp
     WHERE rp.project_id = ct.project_id
       AND rp.observation_type = 'monthly'
       AND rp.period_start = tmr.billing_month
     LIMIT 1),
    'computed'::calc_status,                    -- monthly rows have effective_tariff so they're computed
    tmr.calculation_basis,
    tmr.is_current,
    tmr.created_at
FROM tariff_monthly_rate tmr
JOIN tariff_annual_rate tar ON tar.id = tmr.tariff_annual_rate_id
JOIN clause_tariff ct ON ct.id = tar.clause_tariff_id
JOIN escalation_type esc ON esc.id = ct.escalation_type_id
LEFT JOIN exchange_rate er ON er.id = tmr.exchange_rate_id;


-- =============================================================================
-- G-pre. Data fix: correct local_currency_id for REBASED_MARKET_PRICE rows
-- =============================================================================
-- Existing tariff_rate rows may have local_currency_id = clause_tariff.currency_id (USD)
-- when it should be market_ref_currency_id (GHS) for REBASED_MARKET_PRICE tariffs.

UPDATE tariff_rate tr
SET local_currency_id = ct.market_ref_currency_id,
    billing_currency_id = ct.market_ref_currency_id,
    updated_at = NOW()
FROM clause_tariff ct
JOIN escalation_type esc ON esc.id = ct.escalation_type_id
WHERE tr.clause_tariff_id = ct.id
  AND esc.code = 'REBASED_MARKET_PRICE'
  AND ct.market_ref_currency_id IS NOT NULL
  AND (tr.local_currency_id != ct.market_ref_currency_id
       OR tr.billing_currency_id != ct.market_ref_currency_id);


-- =============================================================================
-- G. Same-currency backfill
-- =============================================================================
-- For deterministic same-currency tariffs where hard = local, the hard_ccy rate
-- should equal the local_ccy rate. The annual migration above sets hard_ccy = NULL
-- for REBASED_MARKET_PRICE rows, but deterministic same-ccy rows should match.

UPDATE tariff_rate
SET effective_rate_hard_ccy = effective_rate_local_ccy,
    updated_at = NOW()
WHERE effective_rate_hard_ccy IS NULL
  AND effective_rate_local_ccy IS NOT NULL
  AND hard_currency_id = local_currency_id;


-- =============================================================================
-- H. Table comments
-- =============================================================================

COMMENT ON TABLE tariff_rate IS 'Unified tariff rate table. Stores both annual and monthly rates with four-currency representation, FX audit trail, and calculation lineage. Replaces tariff_annual_rate + tariff_monthly_rate.';
COMMENT ON COLUMN tariff_rate.rate_granularity IS 'annual or monthly. Annual rows have billing_month=NULL; monthly rows have billing_month set.';
COMMENT ON COLUMN tariff_rate.billing_month IS 'First of month (e.g. 2026-09-01) for monthly rows. NULL for annual.';
COMMENT ON COLUMN tariff_rate.hard_currency_id IS 'International reference currency (USD, EUR).';
COMMENT ON COLUMN tariff_rate.local_currency_id IS 'Local market currency where project operates.';
COMMENT ON COLUMN tariff_rate.billing_currency_id IS 'Currency on invoices. Must equal hard or local.';
COMMENT ON COLUMN tariff_rate.fx_rate_hard_id IS 'FK to exchange_rate for hard currency. NULL if hard=USD.';
COMMENT ON COLUMN tariff_rate.fx_rate_local_id IS 'FK to exchange_rate for local currency. NULL if local=USD.';
COMMENT ON COLUMN tariff_rate.effective_rate_contract_ccy IS 'Effective rate in the contractual source-of-truth currency.';
COMMENT ON COLUMN tariff_rate.effective_rate_hard_ccy IS 'Effective rate in hard/international currency.';
COMMENT ON COLUMN tariff_rate.effective_rate_local_ccy IS 'Effective rate in local market currency.';
COMMENT ON COLUMN tariff_rate.effective_rate_billing_ccy IS 'Effective rate in billing/invoice currency.';
COMMENT ON COLUMN tariff_rate.effective_rate_contract_role IS 'Which category (hard/local/billing) is the source of truth.';
COMMENT ON COLUMN tariff_rate.calc_detail IS 'JSONB with escalation-type-specific intermediary variables in four-currency format.';
COMMENT ON COLUMN tariff_rate.rate_binding IS 'Which constraint was binding: floor, ceiling, discounted, or fixed.';
COMMENT ON COLUMN tariff_rate.reference_price_id IS 'FK to reference_price (GRP observation). NULL for deterministic tariffs.';
COMMENT ON COLUMN tariff_rate.discount_pct_applied IS 'Discount percentage applied (e.g. 0.2200 for 22%).';
COMMENT ON COLUMN tariff_rate.formula_version IS 'Engine version identifier (e.g. rebased_v1, deterministic_v1).';
COMMENT ON COLUMN tariff_rate.calc_status IS 'pending → computed → approved → superseded.';
COMMENT ON COLUMN tariff_rate.is_current IS 'true = active rate for billing. Separate is_current per granularity (enforced by unique indexes).';


-- =============================================================================
-- I. Drop legacy tables
-- =============================================================================
-- All data has been migrated to tariff_rate. All application code now reads/writes
-- exclusively from tariff_rate. Safe to drop.

DROP TABLE IF EXISTS tariff_monthly_rate;
DROP TABLE IF EXISTS tariff_annual_rate;

COMMIT;
