-- =============================================================================
-- Migration 036: Monthly Tariff Rate & FX Support
-- =============================================================================
-- Date: 2026-02-20
--
-- Changes:
--   A. Rename tariff_rate_period → tariff_annual_rate (indexes, policies, comments)
--   B. Add final_effective_tariff + final_effective_tariff_source to tariff_annual_rate
--   C. Create tariff_monthly_rate table (child of tariff_annual_rate) with RLS
--
-- Context:
--   REBASED_MARKET_PRICE tariffs are rebased annually to the Grid Reference Price
--   (GRP) but floor/ceiling USD→GHS conversion uses each billing month's FX rate,
--   producing up to 12 effective rates per contract year.
--
--   tariff_annual_rate stores the annual anchor; tariff_monthly_rate stores the
--   monthly FX-adjusted effective rates. The final_effective_tariff field on
--   tariff_annual_rate is the authoritative billing rate.
-- =============================================================================

BEGIN;

-- =============================================================================
-- A. Rename tariff_rate_period → tariff_annual_rate
-- =============================================================================
-- PostgreSQL ALTER TABLE RENAME automatically updates FK references, sequences,
-- and constraints.

ALTER TABLE tariff_rate_period RENAME TO tariff_annual_rate;

-- Rename effective_rate → effective_tariff for naming consistency with final_effective_tariff
ALTER TABLE tariff_annual_rate RENAME COLUMN effective_rate TO effective_tariff;

-- Rename indexes
ALTER INDEX idx_tariff_rate_period_current RENAME TO idx_tariff_annual_rate_current;
ALTER INDEX idx_tariff_rate_period_date_range RENAME TO idx_tariff_annual_rate_date_range;
ALTER INDEX tariff_rate_period_clause_tariff_id_contract_year_key
    RENAME TO tariff_annual_rate_clause_tariff_id_contract_year_key;

-- Rename RLS policies
ALTER POLICY tariff_rate_period_org_policy ON tariff_annual_rate
    RENAME TO tariff_annual_rate_org_policy;
ALTER POLICY tariff_rate_period_admin_modify_policy ON tariff_annual_rate
    RENAME TO tariff_annual_rate_admin_modify_policy;
ALTER POLICY tariff_rate_period_service_policy ON tariff_annual_rate
    RENAME TO tariff_annual_rate_service_policy;

-- Update table comment
COMMENT ON TABLE tariff_annual_rate IS 'Annual effective rate per clause_tariff after escalation. For REBASED_MARKET_PRICE tariffs, this is the representative annual rate; monthly detail lives in tariff_monthly_rate.';


-- =============================================================================
-- B. Add final_effective_tariff fields to tariff_annual_rate
-- =============================================================================
-- final_effective_tariff is the authoritative billing rate. For deterministic
-- escalation types it equals effective_tariff; for REBASED_MARKET_PRICE it's
-- set to the latest monthly FX-adjusted rate.

ALTER TABLE tariff_annual_rate
    ADD COLUMN IF NOT EXISTS final_effective_tariff DECIMAL,
    ADD COLUMN IF NOT EXISTS final_effective_tariff_source VARCHAR(20);

COMMENT ON COLUMN tariff_annual_rate.final_effective_tariff IS 'Final effective tariff for invoicing. For deterministic escalation: equals effective_tariff. For REBASED_MARKET_PRICE: set to latest monthly rate (monthly overrides annual when they diverge).';
COMMENT ON COLUMN tariff_annual_rate.final_effective_tariff_source IS 'Source of final_effective_tariff: annual (deterministic escalation unchanged), monthly (FX-adjusted monthly rate overrides), or manual (manually set).';


-- =============================================================================
-- C. Create tariff_monthly_rate table
-- =============================================================================
-- Child of tariff_annual_rate. Stores monthly-resolved effective rates for
-- REBASED_MARKET_PRICE escalation types. Uses the existing exchange_rate table
-- (migration 022) for FX system of record.

CREATE TABLE IF NOT EXISTS tariff_monthly_rate (
    id                      BIGSERIAL PRIMARY KEY,
    tariff_annual_rate_id   BIGINT NOT NULL REFERENCES tariff_annual_rate(id) ON DELETE CASCADE,
    exchange_rate_id        BIGINT REFERENCES exchange_rate(id),
    billing_month           DATE NOT NULL,
    floor_local             DECIMAL,
    ceiling_local           DECIMAL,
    discounted_grp_local    DECIMAL,
    effective_tariff_local  DECIMAL NOT NULL,
    rate_binding            VARCHAR(20) NOT NULL,
    calculation_basis       TEXT,
    is_current              BOOLEAN NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tariff_annual_rate_id, billing_month)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tariff_monthly_rate_current
    ON tariff_monthly_rate(tariff_annual_rate_id) WHERE is_current = true;

CREATE INDEX IF NOT EXISTS idx_tariff_monthly_rate_lookup
    ON tariff_monthly_rate(tariff_annual_rate_id, billing_month);

COMMENT ON TABLE tariff_monthly_rate IS 'Monthly effective rates for REBASED_MARKET_PRICE tariffs. Child of tariff_annual_rate. Up to 12 rows per contract year, each with FX-adjusted floor/ceiling.';
COMMENT ON COLUMN tariff_monthly_rate.exchange_rate_id IS 'FK to exchange_rate row used for this month FX conversion. Provides audit trail.';
COMMENT ON COLUMN tariff_monthly_rate.billing_month IS 'First of month (e.g. 2026-09-01).';
COMMENT ON COLUMN tariff_monthly_rate.floor_local IS 'Floor rate in local currency (GHS) after FX conversion.';
COMMENT ON COLUMN tariff_monthly_rate.ceiling_local IS 'Ceiling rate in local currency (GHS) after FX conversion.';
COMMENT ON COLUMN tariff_monthly_rate.discounted_grp_local IS 'GRP × (1 - discount_pct) in local currency.';
COMMENT ON COLUMN tariff_monthly_rate.effective_tariff_local IS 'Final tariff in local currency after applying floor/ceiling bounds.';
COMMENT ON COLUMN tariff_monthly_rate.rate_binding IS 'Which bound is active: floor, ceiling, or discounted.';
COMMENT ON COLUMN tariff_monthly_rate.is_current IS 'true = the latest/active month for billing; false = historical months.';

-- Currency for the local-currency rate (e.g. GHS). Distinct from the USD rate on tariff_annual_rate.
ALTER TABLE tariff_monthly_rate
    ADD COLUMN IF NOT EXISTS currency_id BIGINT REFERENCES currency(id);
COMMENT ON COLUMN tariff_monthly_rate.currency_id IS 'Local currency for effective_tariff_local (e.g. GHS).';


-- =============================================================================
-- C2. RLS for tariff_monthly_rate
-- =============================================================================

ALTER TABLE tariff_monthly_rate ENABLE ROW LEVEL SECURITY;

CREATE POLICY tariff_monthly_rate_org_policy ON tariff_monthly_rate
    FOR SELECT USING (is_org_member(
        (SELECT ct.organization_id FROM tariff_annual_rate tar
         JOIN clause_tariff ct ON ct.id = tar.clause_tariff_id
         WHERE tar.id = tariff_annual_rate_id)
    ));

CREATE POLICY tariff_monthly_rate_admin_modify_policy ON tariff_monthly_rate
    FOR ALL USING (is_org_admin(
        (SELECT ct.organization_id FROM tariff_annual_rate tar
         JOIN clause_tariff ct ON ct.id = tar.clause_tariff_id
         WHERE tar.id = tariff_annual_rate_id)
    ));

CREATE POLICY tariff_monthly_rate_service_policy ON tariff_monthly_rate
    FOR ALL USING (auth.role() = 'service_role');

COMMIT;
