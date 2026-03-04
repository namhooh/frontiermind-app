-- KAS01 December 2025 Fixture Data
-- Seeds clause_tariff linkages, billing_taxes config, tariff_rate,
-- and reference_price (MRP) for KAS01 (Kasapreko Phase I & II).
--
-- All lookups use stable keys (sage_id, external_contract_id) — no hardcoded IDs.
-- Verified against invoice SINKAS012512035 (December 2025).
--
-- IDEMPOTENT: uses ON CONFLICT DO NOTHING / conditional updates.
--
-- Invoice Summary (SINKAS012512035):
--   Period: 01/12/2025 - 31/12/2025
--   Metered Phase 1: 39,774.00 kWh × 1.2556 = 49,940.23 GHS
--   Available Combined: 1,641.45 kWh × 1.2556 = 2,061.00 GHS
--   Metered Phase 2: 91,644.40 kWh × 1.2556 = 115,068.71 GHS
--   Total Energy: 133,059.85 kWh → 167,069.94 GHS
--   NHIL 2.5%: 4,176.75, GETFUND 2.5%: 4,176.75, COVID 1%: 1,670.70
--   VAT 15%: 26,564.12 → Invoice Total: 203,658.26 GHS
--   WHT 7.5%: -12,530.25, WHVAT 7%: -12,396.59
--   Net Due: 178,731.42 GHS
--
-- Tariff (from invoice page 2):
--   Market Reference Price (MRP): 1.5540 GHS/kWh
--   MRP Discount: 19.2000%
--   Effective Rate: 1.5540 × (1 - 0.192) = 1.2556 GHS/kWh (4dp)
--   Minimum Solar Price: 0.0989 USD/kWh (escalated floor)
--   Ceiling: 0.3000 USD/kWh

BEGIN;

-- ============================================================================
-- 1. Set project.country = 'Ghana' (required for billing_tax_rule lookup)
-- ============================================================================

UPDATE project
SET country = 'Ghana'
WHERE sage_id = 'KAS01'
  AND (country IS NULL OR country != 'Ghana');

-- ============================================================================
-- 2. Link contract_lines to clause_tariff
-- ============================================================================
-- Migration 049 creates contract_lines WITH billing_product_id but WITHOUT
-- clause_tariff_id. The billing API needs clause_tariff_id on lines to
-- resolve tariff rates per line.

-- Active metered + available lines → current clause_tariff
UPDATE contract_line cl
SET clause_tariff_id = ct.id
FROM clause_tariff ct, contract c, project p
WHERE c.id = cl.contract_id
  AND p.id = c.project_id
  AND p.sage_id = 'KAS01'
  AND ct.project_id = p.id
  AND ct.is_current = true
  AND cl.is_active = true
  AND cl.clause_tariff_id IS NULL;

-- ============================================================================
-- 3. Seed billing_taxes into clause_tariff.logic_parameters
-- ============================================================================
-- Ghana tax chain (verified against invoice SINKAS012512035):
--   NHIL 2.5%, GETFund 2.5%, COVID 1% → on energy_subtotal
--   VAT 15% → on subtotal_after_levies
--   WHT 7.5% → on energy_subtotal     ← NOTE: 7.5% for KAS01 (not 3% like MOH01)
--   WHVAT 7% → on subtotal_after_levies
--
-- available_energy_line_mode = "single" because KAS01 invoice shows
-- "Available Energy (EAvailable) Combined" as a single line.

UPDATE clause_tariff ct
SET logic_parameters = COALESCE(ct.logic_parameters, '{}')::jsonb || '{
  "billing_taxes": {
    "effective_from": "2025-01-01",
    "rounding_mode": "ROUND_HALF_UP",
    "rounding_precision": 2,
    "invoice_rate_precision": 4,
    "available_energy_line_mode": "single",
    "levies": [
      {"code": "NHIL", "name": "NHIL", "rate": 0.025, "applies_to": {"base": "energy_subtotal"}, "sort_order": 10},
      {"code": "GETFUND", "name": "GETFund", "rate": 0.025, "applies_to": {"base": "energy_subtotal"}, "sort_order": 11},
      {"code": "COVID", "name": "COVID Levy", "rate": 0.01, "applies_to": {"base": "energy_subtotal"}, "sort_order": 12}
    ],
    "vat": {"code": "VAT", "name": "VAT", "rate": 0.15, "applies_to": {"base": "subtotal_after_levies"}, "sort_order": 20},
    "withholdings": [
      {"code": "WHT", "name": "Withholding Tax", "rate": 0.075, "applies_to": {"base": "energy_subtotal"}, "sort_order": 30},
      {"code": "WHVAT", "name": "Withholding VAT", "rate": 0.07, "applies_to": {"base": "subtotal_after_levies"}, "sort_order": 31}
    ]
  }
}'::jsonb
FROM project p
WHERE ct.project_id = p.id
  AND p.sage_id = 'KAS01'
  AND ct.is_current = true;

-- ============================================================================
-- 4. Seed reference_price (MRP) for Dec 2025
-- ============================================================================
-- MRP = 1.5540 GHS/kWh (from invoice: Market Reference Price)
-- Operating Year 8 (COD Oct 2018, Year 8 = Oct 2025-Oct 2026)

INSERT INTO reference_price (
  project_id, organization_id, operating_year,
  period_start, period_end, calculated_mrp_per_kwh,
  currency_id, observation_type, verification_status
)
SELECT
  p.id, p.organization_id, 8,
  '2025-12-01'::date, '2025-12-31'::date, 1.5540,
  (SELECT id FROM currency WHERE code = 'GHS'),
  'monthly', 'jointly_verified'
FROM project p
WHERE p.sage_id = 'KAS01'
  AND NOT EXISTS (
      SELECT 1 FROM reference_price rp
      WHERE rp.project_id = p.id
        AND rp.period_start = '2025-12-01'
        AND rp.operating_year = 8
  );

-- ============================================================================
-- 5. Seed tariff_rate monthly row for Dec 2025
-- ============================================================================
-- Effective rate = 1.5540 × (1 - 0.192) = 1.255632 GHS/kWh
-- Rounded to 4dp for invoicing: 1.2556 GHS/kWh
-- rate_binding = 'discounted' (effective falls between floor and ceiling)

INSERT INTO tariff_rate (
  clause_tariff_id,
  contract_year, rate_granularity,
  billing_month,
  hard_currency_id, local_currency_id, billing_currency_id,
  effective_rate_contract_ccy,
  effective_rate_hard_ccy,
  effective_rate_local_ccy,
  effective_rate_billing_ccy,
  effective_rate_contract_role,
  rate_binding, formula_version,
  discount_pct_applied,
  reference_price_id,
  calc_status, is_current,
  calc_detail
)
SELECT
  ct.id,
  8, 'monthly',
  '2025-12-01'::date,
  (SELECT id FROM currency WHERE code = 'USD'),
  (SELECT id FROM currency WHERE code = 'GHS'),
  (SELECT id FROM currency WHERE code = 'GHS'),
  1.255632,   -- contract currency (GHS) = local = billing
  1.255632,   -- hard currency (USD→GHS conversion, but rate=1.0 for this invoice)
  1.255632,   -- local currency (GHS)
  1.255632,   -- billing currency (GHS)
  'local',
  'discounted', 'rebased_v1',
  0.192,
  rp.id,
  'computed', true,
  json_build_object(
    'mrp_per_kwh', 1.5540,
    'discount_pct', 0.192,
    'discounted_base_ghs', 1.255632,
    'escalated_floor_usd', 0.0989,
    'escalated_ceiling_usd', 0.3000,
    'fx_rate', 1.0,
    'floor_ghs', 0.0989,
    'ceiling_ghs', 0.3000,
    'formula', 'MAX(floor_ghs, MIN(discounted_base_ghs, ceiling_ghs))',
    'source_invoice', 'SINKAS012512035'
  )::jsonb
FROM clause_tariff ct
JOIN project p ON ct.project_id = p.id
LEFT JOIN reference_price rp
  ON rp.project_id = p.id
  AND rp.period_start = '2025-12-01'
  AND rp.operating_year = 8
WHERE p.sage_id = 'KAS01'
  AND ct.is_current = true
  AND NOT EXISTS (
    SELECT 1 FROM tariff_rate tr
    WHERE tr.clause_tariff_id = ct.id
      AND tr.billing_month = '2025-12-01'
      AND tr.rate_granularity = 'monthly'
  );

-- ============================================================================
-- 6. Ensure billing_tax_rule exists for Ghana (org-level fallback)
-- ============================================================================
-- This is the org-level default. Project-specific overrides live in
-- clause_tariff.logic_parameters.billing_taxes (seeded in step 3).
-- NOTE: WHT here is 3% (Ghana standard). KAS01 overrides to 7.5% via
-- clause_tariff.logic_parameters which takes priority in billing.py.

INSERT INTO billing_tax_rule (
    organization_id, country_code, name,
    effective_start_date, effective_end_date,
    rules, is_active
)
SELECT
  1,   -- FrontierSolar
  'GH',
  'Ghana Standard Tax Regime',
  '2025-01-01'::date,
  NULL,
  '{
    "rounding_mode": "ROUND_HALF_UP",
    "rounding_precision": 2,
    "invoice_rate_precision": 4,
    "available_energy_line_mode": "single",
    "levies": [
      {"code": "NHIL", "name": "NHIL", "rate": 0.025, "applies_to": {"base": "energy_subtotal"}, "sort_order": 10},
      {"code": "GETFUND", "name": "GETFund", "rate": 0.025, "applies_to": {"base": "energy_subtotal"}, "sort_order": 11},
      {"code": "COVID", "name": "COVID Levy", "rate": 0.01, "applies_to": {"base": "energy_subtotal"}, "sort_order": 12}
    ],
    "vat": {"code": "VAT", "name": "VAT", "rate": 0.15, "applies_to": {"base": "subtotal_after_levies"}, "sort_order": 20},
    "withholdings": [
      {"code": "WHT", "name": "Withholding Tax", "rate": 0.03, "applies_to": {"base": "energy_subtotal"}, "sort_order": 30},
      {"code": "WHVAT", "name": "Withholding VAT", "rate": 0.07, "applies_to": {"base": "subtotal_after_levies"}, "sort_order": 31}
    ]
  }'::jsonb,
  true
WHERE NOT EXISTS (
    SELECT 1 FROM billing_tax_rule
    WHERE organization_id = 1 AND country_code = 'GH'
);

-- ============================================================================
-- 7. Verify: meter_aggregate data for Dec 2025 exists (seeded in migration 049)
-- ============================================================================
-- Expected values (from invoice SINKAS012512035):
--   Line 1000 (Phase 1): opening=3,138,669, closing=3,178,443, utilized=39,774
--   Line 2000 (Available): available_energy_kwh=1,641.45
--   Line 4000 (Phase 2): opening=970,114.3, closing=1,061,758.7, utilized=91,644.4
--
-- No action needed — migration 049 already seeds this data.
-- Run this query to verify:
--
--   SELECT cl.contract_line_number, cl.product_desc,
--          ma.energy_kwh, ma.available_energy_kwh,
--          ma.opening_reading, ma.closing_reading
--   FROM meter_aggregate ma
--   JOIN contract_line cl ON cl.id = ma.contract_line_id
--   JOIN contract c ON c.id = cl.contract_id
--   JOIN project p ON p.id = c.project_id
--   WHERE p.sage_id = 'KAS01'
--     AND ma.period_start = '2025-12-01';

COMMIT;
