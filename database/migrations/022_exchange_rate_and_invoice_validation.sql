-- Migration 022: Exchange Rate & Invoice Validation Architecture
-- Date: 2026-01-31
-- Phase: 5.6 - Client Invoice Validation
--
-- Changes:
--   1. New table: exchange_rate (per org/currency/date, rate to USD)
--   2. Extend clause_tariff: organization_id, tariff_group_key, meter_id, is_active, source_metadata, updated_at
--   3. Extend meter_aggregate: clause_tariff_id, opening/closing/utilized/discount readings, sourced_energy, source_metadata
--   4. New enum: invoice_direction ('payable', 'receivable')
--   5. Extend expected/received invoice headers: invoice_direction
--   6. Extend invoice_comparison: invoice_direction
--   7. Extend expected/received invoice line items: clause_tariff_id, meter_aggregate_id, quantity, line_unit_price
--   8. Extend invoice_comparison_line_item: clause_tariff_id, variance_percent, variance_details
--   9. Seed currencies (11 currencies)
--  10. Seed tariff_type (14 types)

-- =============================================================================
-- 1. Seed Currencies
-- =============================================================================

INSERT INTO currency (name, code) VALUES
  ('US Dollar', 'USD'),
  ('Euro', 'EUR'),
  ('British Pound', 'GBP'),
  ('South African Rand', 'ZAR'),
  ('Ghanaian Cedi', 'GHS'),
  ('Nigerian Naira', 'NGN'),
  ('Kenyan Shilling', 'KES'),
  ('Rwandan Franc', 'RWF'),
  ('Sierra Leonean Leone', 'SLE'),
  ('Egyptian Pound', 'EGP'),
  ('Mozambican Metical', 'MZN')
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- 2. Seed Tariff Types
-- =============================================================================

-- NOT IMPLEMENTED YET (2026-02-01) =======

INSERT INTO tariff_type (name, code, description) VALUES
  ('Flat Rate', 'FLAT', 'Fixed price per unit'),
  ('Time of Use', 'TOU', 'Price varies by time period'),
  ('Tiered', 'TIERED', 'Price varies by consumption tier'),
  ('Indexed', 'INDEXED', 'Price linked to external index'),
  ('Metered Energy', 'METERED_ENERGY', 'Energy billed by meter reading'),
  ('Available Energy', 'AVAILABLE_ENERGY', 'Contracted available energy capacity'),
  ('Deemed Energy', 'DEEMED_ENERGY', 'Contractual deemed/guaranteed energy'),
  ('BESS Capacity', 'BESS_CAPACITY', 'Battery energy storage capacity charge'),
  ('Minimum Offtake', 'MIN_OFFTAKE', 'Minimum consumption guarantee'),
  ('Equipment Rental', 'EQUIP_RENTAL', 'Equipment lease/rental charge'),
  ('O&M Fee', 'OM_FEE', 'Operations and maintenance fee'),
  ('Diesel', 'DIESEL', 'Diesel fuel supply/handling charge'),
  ('Penalty', 'PENALTY', 'Contractual penalty or delay charge'),
  ('Pricing Correction', 'PRICE_CORRECTION', 'Retroactive pricing adjustment')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 3. Exchange Rate Table
-- =============================================================================
-- Convention: rate = how many units of currency_id per 1 USD.
-- Example: ZAR row with rate = 18.50 means 1 USD = 18.50 ZAR.
-- To get USD from local: local_amount / rate
-- To cross-convert (e.g. ZAR → GHS): zar_amount / zar_rate * ghs_rate

CREATE TABLE IF NOT EXISTS exchange_rate (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organization(id),
  currency_id BIGINT NOT NULL REFERENCES currency(id),
  rate_date DATE NOT NULL,
  rate DECIMAL NOT NULL,
  source VARCHAR(100) NOT NULL DEFAULT 'manual',
  created_by UUID,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, currency_id, rate_date)
);

CREATE INDEX IF NOT EXISTS idx_exchange_rate_lookup
  ON exchange_rate(organization_id, currency_id, rate_date DESC);

COMMENT ON TABLE exchange_rate IS 'Exchange rates per organization/currency/date. Rate is always to USD (1 USD = X local currency).';
COMMENT ON COLUMN exchange_rate.rate IS '1 USD = X units of this currency. To convert local to USD: local_amount / rate.';
COMMENT ON COLUMN exchange_rate.source IS 'Source of rate: manual, api, etc. Auto-fetch deferred to future phase.';

-- =============================================================================
-- 4. Extend clause_tariff
-- =============================================================================
-- clause_tariff is a parallel table to clause, not a child.
-- tariff_group_key groups rows representing the same logical tariff line across time periods.

ALTER TABLE clause_tariff
  ADD COLUMN IF NOT EXISTS organization_id BIGINT REFERENCES organization(id),
  ADD COLUMN IF NOT EXISTS tariff_group_key VARCHAR(255),
  ADD COLUMN IF NOT EXISTS meter_id BIGINT REFERENCES meter(id),
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true,
  ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_clause_tariff_group_key
  ON clause_tariff(contract_id, tariff_group_key);

CREATE INDEX IF NOT EXISTS idx_clause_tariff_org
  ON clause_tariff(organization_id);

CREATE INDEX IF NOT EXISTS idx_clause_tariff_meter
  ON clause_tariff(meter_id);

COMMENT ON COLUMN clause_tariff.tariff_group_key IS 'Groups clause_tariff rows belonging to the same logical tariff line across time periods. Adapter maps client-specific line IDs here.';
COMMENT ON COLUMN clause_tariff.source_metadata IS 'Client-specific fields (e.g. CBE external_line_id, product_code). Core logic reads only generic columns.';
COMMENT ON COLUMN clause_tariff.meter_id IS 'Optional link to physical meter for metered tariffs. NULL for non-metered tariffs.';
COMMENT ON COLUMN clause_tariff.is_active IS 'Whether this tariff line is currently active.';

-- =============================================================================
-- 5. Extend meter_aggregate for Billing Readings
-- =============================================================================
-- Two usage patterns:
-- 1. Physical meter pipeline (existing): meter_id set, clause_tariff_id may be NULL
-- 2. Client billing data (new): clause_tariff_id set, meter_id optional
-- total_production (existing) serves as the final billable quantity.

ALTER TABLE meter_aggregate
  ADD COLUMN IF NOT EXISTS clause_tariff_id BIGINT REFERENCES clause_tariff(id),
  ADD COLUMN IF NOT EXISTS opening_reading DECIMAL,
  ADD COLUMN IF NOT EXISTS closing_reading DECIMAL,
  ADD COLUMN IF NOT EXISTS utilized_reading DECIMAL,
  ADD COLUMN IF NOT EXISTS discount_reading DECIMAL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS sourced_energy DECIMAL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS source_metadata JSONB DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_meter_aggregate_clause_tariff
  ON meter_aggregate(clause_tariff_id);

COMMENT ON COLUMN meter_aggregate.clause_tariff_id IS 'Links this aggregate to a specific billable tariff line. NULL for pure physical meter aggregates.';
COMMENT ON COLUMN meter_aggregate.opening_reading IS 'Meter reading at billing period start.';
COMMENT ON COLUMN meter_aggregate.closing_reading IS 'Meter reading at billing period end.';
COMMENT ON COLUMN meter_aggregate.utilized_reading IS 'Net consumption (closing - opening, or client-provided).';
COMMENT ON COLUMN meter_aggregate.discount_reading IS 'Discounted/waived quantity.';
COMMENT ON COLUMN meter_aggregate.sourced_energy IS 'Self-sourced energy to deduct from billable quantity.';
COMMENT ON COLUMN meter_aggregate.source_metadata IS 'Client-specific metadata for this reading.';

-- =============================================================================
-- 6. Invoice Direction Enum
-- =============================================================================
-- payable = AP (what contractor bills us / what we expect contractor to bill)
-- receivable = AR (what we bill client / what ERP generated)

DO $$ BEGIN
  CREATE TYPE invoice_direction AS ENUM ('payable', 'receivable');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- 7. Extend Invoice Headers with Direction
-- =============================================================================

ALTER TABLE expected_invoice_header
  ADD COLUMN IF NOT EXISTS invoice_direction invoice_direction NOT NULL DEFAULT 'payable';

ALTER TABLE received_invoice_header
  ADD COLUMN IF NOT EXISTS invoice_direction invoice_direction NOT NULL DEFAULT 'payable';

ALTER TABLE invoice_comparison
  ADD COLUMN IF NOT EXISTS invoice_direction invoice_direction NOT NULL DEFAULT 'payable';

COMMENT ON COLUMN expected_invoice_header.invoice_direction IS 'payable = what we expect contractor to bill us; receivable = what we calculate we should bill client.';
COMMENT ON COLUMN received_invoice_header.invoice_direction IS 'payable = what contractor actually billed; receivable = what ERP (e.g. Sage) actually generated.';
COMMENT ON COLUMN invoice_comparison.invoice_direction IS 'payable = expected vs contractor bill; receivable = our calculation vs ERP output.';

-- =============================================================================
-- 8. Extend Expected Invoice Line Items
-- =============================================================================

ALTER TABLE expected_invoice_line_item
  ADD COLUMN IF NOT EXISTS clause_tariff_id BIGINT REFERENCES clause_tariff(id),
  ADD COLUMN IF NOT EXISTS meter_aggregate_id BIGINT REFERENCES meter_aggregate(id),
  ADD COLUMN IF NOT EXISTS quantity DECIMAL,
  ADD COLUMN IF NOT EXISTS line_unit_price DECIMAL;

CREATE INDEX IF NOT EXISTS idx_expected_line_clause_tariff
  ON expected_invoice_line_item(clause_tariff_id);

CREATE INDEX IF NOT EXISTS idx_expected_line_meter_aggregate
  ON expected_invoice_line_item(meter_aggregate_id);

COMMENT ON COLUMN expected_invoice_line_item.clause_tariff_id IS 'Links to the tariff definition used for pricing this line.';
COMMENT ON COLUMN expected_invoice_line_item.meter_aggregate_id IS 'Links to meter readings for metered tariffs. NULL for non-metered tariffs (capacity, O&M, etc).';
COMMENT ON COLUMN expected_invoice_line_item.quantity IS 'Billable quantity. For metered: from meter_aggregate.total_production. For non-metered: from contract terms.';
COMMENT ON COLUMN expected_invoice_line_item.line_unit_price IS 'Unit price used at calculation time. Captures clause_tariff.base_rate for audit trail.';

-- =============================================================================
-- 9. Extend Received Invoice Line Items
-- =============================================================================

ALTER TABLE received_invoice_line_item
  ADD COLUMN IF NOT EXISTS clause_tariff_id BIGINT REFERENCES clause_tariff(id),
  ADD COLUMN IF NOT EXISTS meter_aggregate_id BIGINT REFERENCES meter_aggregate(id),
  ADD COLUMN IF NOT EXISTS quantity DECIMAL,
  ADD COLUMN IF NOT EXISTS line_unit_price DECIMAL;

CREATE INDEX IF NOT EXISTS idx_received_line_clause_tariff
  ON received_invoice_line_item(clause_tariff_id);

CREATE INDEX IF NOT EXISTS idx_received_line_meter_aggregate
  ON received_invoice_line_item(meter_aggregate_id);

COMMENT ON COLUMN received_invoice_line_item.clause_tariff_id IS 'Links to the tariff definition for this line.';
COMMENT ON COLUMN received_invoice_line_item.meter_aggregate_id IS 'Links to meter readings for metered tariffs. NULL for non-metered tariffs.';
COMMENT ON COLUMN received_invoice_line_item.quantity IS 'Quantity as stated on received invoice.';
COMMENT ON COLUMN received_invoice_line_item.line_unit_price IS 'Unit price as stated on received invoice.';

-- =============================================================================
-- 10. Extend Invoice Comparison Line Items
-- =============================================================================

ALTER TABLE invoice_comparison_line_item
  ADD COLUMN IF NOT EXISTS clause_tariff_id BIGINT REFERENCES clause_tariff(id),
  ADD COLUMN IF NOT EXISTS variance_percent DECIMAL,
  ADD COLUMN IF NOT EXISTS variance_details JSONB DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_comparison_line_clause_tariff
  ON invoice_comparison_line_item(clause_tariff_id);

COMMENT ON COLUMN invoice_comparison_line_item.clause_tariff_id IS 'Links to the tariff definition for variance analysis.';
COMMENT ON COLUMN invoice_comparison_line_item.variance_percent IS 'Percentage variance between expected and received amounts.';
COMMENT ON COLUMN invoice_comparison_line_item.variance_details IS 'Method-specific variance breakdown (e.g. multi-method calculation details, rounding differences).';

-- =============================================================================
-- 11. RLS Policies for exchange_rate
-- =============================================================================

ALTER TABLE exchange_rate ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS exchange_rate_org_policy ON exchange_rate;
CREATE POLICY exchange_rate_org_policy ON exchange_rate
  FOR SELECT
  USING (is_org_member(organization_id));

DROP POLICY IF EXISTS exchange_rate_admin_modify_policy ON exchange_rate;
CREATE POLICY exchange_rate_admin_modify_policy ON exchange_rate
  FOR ALL
  USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS exchange_rate_service_policy ON exchange_rate;
CREATE POLICY exchange_rate_service_policy ON exchange_rate
  FOR ALL
  USING (auth.role() = 'service_role');
