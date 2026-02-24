-- MOH01 December 2025 Fixture Data
-- Seeds meter_aggregate, contract_line tariff links, billing_taxes config,
-- plant_performance, reference_price (GRP), and billing_tax_rule for MOH01.
--
-- All lookups use stable keys (project code, meter name) — no hardcoded IDs.
-- Verified against invoice SINMOH012512037.
--
-- IDEMPOTENT: uses ON CONFLICT DO NOTHING / conditional updates.

BEGIN;

-- ============================================================================
-- 1. Set project.country = 'Ghana'
-- ============================================================================

UPDATE project
SET country = 'Ghana'
WHERE external_project_id = 'MOH01'
  AND (country IS NULL OR country != 'Ghana');

-- ============================================================================
-- 2. Fix contract_line.external_line_id to match CBE CONTRACT_LINE_UNIQUE_ID
-- ============================================================================

-- Metered lines: set actual CBE IDs
UPDATE contract_line cl
SET external_line_id = mapping.cbe_id
FROM (
    VALUES
        (4000, '16024898481453667312'),
        (5000, '11638393568522465456'),
        (6000, '14363463940112825663'),
        (7000, '2906294614673635232'),
        (8000, '12379399266877543057')
) AS mapping(line_no, cbe_id),
     contract c,
     project p
WHERE c.id = cl.contract_id
  AND p.id = c.project_id
  AND p.external_project_id = 'MOH01'
  AND cl.contract_line_number = mapping.line_no
  AND cl.is_active = true;

-- Available lines: set external_line_id to NULL (no CBE ID)
UPDATE contract_line cl
SET external_line_id = NULL
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE c.id = cl.contract_id
  AND p.external_project_id = 'MOH01'
  AND cl.energy_category = 'available'
  AND cl.is_active = true
  AND cl.external_line_id IS NOT NULL;

-- ============================================================================
-- 3. Link contract_lines to clause_tariff + billing_product
-- ============================================================================

-- Metered lines → clause_tariff (current), billing_product = 94 (ENER002)
UPDATE contract_line cl
SET clause_tariff_id = ct.id,
    billing_product_id = 94
FROM clause_tariff ct, contract c, project p
WHERE c.id = cl.contract_id
  AND p.id = c.project_id
  AND p.external_project_id = 'MOH01'
  AND ct.project_id = p.id
  AND ct.is_current = true
  AND cl.energy_category = 'metered'
  AND cl.is_active = true;

-- Available lines → clause_tariff (current), billing_product = 106 (ENER003)
UPDATE contract_line cl
SET clause_tariff_id = ct.id,
    billing_product_id = 106
FROM clause_tariff ct, contract c, project p
WHERE c.id = cl.contract_id
  AND p.id = c.project_id
  AND p.external_project_id = 'MOH01'
  AND ct.project_id = p.id
  AND ct.is_current = true
  AND cl.energy_category = 'available'
  AND cl.is_active = true;

-- ============================================================================
-- 4. Add test energy contract_line (3000) if not exists
-- ============================================================================

INSERT INTO contract_line (
    contract_id, contract_line_number, product_desc,
    energy_category, billing_product_id, meter_id,
    external_line_id, clause_tariff_id, organization_id, is_active
)
SELECT
    c.id,
    3000,
    'Early Operating / Test Energy',
    'test'::energy_category,
    97,    -- ENER001
    NULL,  -- no meter
    '8072385830860334585',
    ct.id,
    p.organization_id,
    true
FROM project p
JOIN contract c ON c.project_id = p.id
JOIN clause_tariff ct ON ct.project_id = p.id AND ct.is_current = true
WHERE p.external_project_id = 'MOH01'
  AND NOT EXISTS (
      SELECT 1 FROM contract_line cl2
      WHERE cl2.contract_id = c.id AND cl2.contract_line_number = 3000
  );

-- ============================================================================
-- 5. Seed billing_taxes into clause_tariff.logic_parameters
-- ============================================================================
-- Ghana tax chain (verified against invoice SINMOH012512037):
--   NHIL 2.5%, GETFund 2.5%, COVID 1% → on energy_subtotal
--   VAT 15% → on subtotal_after_levies
--   WHT 3% → on energy_subtotal, WHVAT 7% → on subtotal_after_levies

UPDATE clause_tariff ct
SET logic_parameters = COALESCE(ct.logic_parameters, '{}')::jsonb || '{
  "billing_taxes": {
    "effective_from": "2025-01-01",
    "rounding_mode": "ROUND_HALF_UP",
    "rounding_precision": 2,
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
  }
}'::jsonb
FROM project p
WHERE ct.project_id = p.id
  AND p.external_project_id = 'MOH01'
  AND ct.is_current = true;

-- ============================================================================
-- 6. Seed billing_tax_rule (org/country default for FrontierSolar, GH)
-- ============================================================================

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
-- 7. Insert meter_aggregate rows for Dec 2025
-- ============================================================================
-- 5 metered rows (with opening/closing readings from CBE invoice)

WITH
  proj AS (
    SELECT id AS project_id, organization_id
    FROM project WHERE external_project_id = 'MOH01'
    LIMIT 1
  ),
  bp AS (
    SELECT id AS billing_period_id
    FROM billing_period
    WHERE start_date = '2025-12-01' AND end_date = '2025-12-31'
    LIMIT 1
  ),
  ct AS (
    SELECT ct.id AS clause_tariff_id
    FROM clause_tariff ct
    JOIN proj p ON ct.project_id = p.project_id
    WHERE ct.is_current = true
    LIMIT 1
  ),
  meter_data (meter_name_pattern, energy_kwh, opening, closing) AS (
    VALUES
      ('%PPL1%'::text,  27028.297::numeric, 190301.203::numeric, 217329.500::numeric),
      ('%PPL2%'::text,  28254.406,          178250.297,          206504.703),
      ('%Bottle%'::text, 22925.406,         148069.094,          170994.500),
      ('%BBM1%'::text,  46677.219,          287936.594,          334613.813),
      ('%BBM2%'::text,  24097.000,          140627.203,          164724.203)
  ),
  resolved_meters AS (
    SELECT
      cl.id AS contract_line_id,
      cl.meter_id,
      md.energy_kwh,
      md.opening,
      md.closing
    FROM meter_data md
    JOIN contract_line cl ON cl.is_active = true
    JOIN contract c ON c.id = cl.contract_id
    JOIN proj p ON c.project_id = p.project_id
    JOIN meter m ON m.id = cl.meter_id
    WHERE cl.energy_category = 'metered'
      AND m.name ILIKE md.meter_name_pattern
  )
INSERT INTO meter_aggregate (
  organization_id, meter_id, billing_period_id, clause_tariff_id,
  contract_line_id, period_type, period_start, period_end,
  energy_kwh, total_production, available_energy_kwh,
  opening_reading, closing_reading,
  source_system
)
SELECT
  (SELECT organization_id FROM proj),
  rm.meter_id,
  (SELECT billing_period_id FROM bp),
  (SELECT clause_tariff_id FROM ct),
  rm.contract_line_id,
  'monthly',
  '2025-12-01'::date,
  '2025-12-31'::date,
  rm.energy_kwh,
  rm.energy_kwh,
  0,
  rm.opening,
  rm.closing,
  'fixture_moh01_dec2025'
FROM resolved_meters rm
WHERE EXISTS (SELECT 1 FROM bp) AND EXISTS (SELECT 1 FROM ct)
ON CONFLICT DO NOTHING;

-- Available energy aggregate (22,613.90 kWh linked to first available contract_line)
WITH
  proj AS (
    SELECT id AS project_id, organization_id
    FROM project WHERE external_project_id = 'MOH01'
    LIMIT 1
  ),
  bp AS (
    SELECT id AS billing_period_id
    FROM billing_period
    WHERE start_date = '2025-12-01' AND end_date = '2025-12-31'
    LIMIT 1
  ),
  ct AS (
    SELECT ct.id AS clause_tariff_id
    FROM clause_tariff ct
    JOIN proj p ON ct.project_id = p.project_id
    WHERE ct.is_current = true
    LIMIT 1
  ),
  avail_line AS (
    SELECT cl.id AS contract_line_id, cl.meter_id
    FROM contract_line cl
    JOIN contract c ON c.id = cl.contract_id
    JOIN proj p ON c.project_id = p.project_id
    WHERE cl.energy_category = 'available'
      AND cl.is_active = true
    ORDER BY cl.contract_line_number
    LIMIT 1
  )
INSERT INTO meter_aggregate (
  organization_id, meter_id, billing_period_id, clause_tariff_id,
  contract_line_id, period_type, period_start, period_end,
  energy_kwh, available_energy_kwh, source_system
)
SELECT
  (SELECT organization_id FROM proj),
  al.meter_id,
  (SELECT billing_period_id FROM bp),
  (SELECT clause_tariff_id FROM ct),
  al.contract_line_id,
  'monthly',
  '2025-12-01'::date,
  '2025-12-31'::date,
  0,
  22613.90,
  'fixture_moh01_dec2025'
FROM avail_line al
WHERE EXISTS (SELECT 1 FROM bp) AND EXISTS (SELECT 1 FROM ct)
ON CONFLICT DO NOTHING;

-- Test energy aggregate (945,184.39 kWh linked to line 3000, meter_id=NULL)
WITH
  proj AS (
    SELECT id AS project_id, organization_id
    FROM project WHERE external_project_id = 'MOH01'
    LIMIT 1
  ),
  bp AS (
    SELECT id AS billing_period_id
    FROM billing_period
    WHERE start_date = '2025-12-01' AND end_date = '2025-12-31'
    LIMIT 1
  ),
  ct AS (
    SELECT ct.id AS clause_tariff_id
    FROM clause_tariff ct
    JOIN proj p ON ct.project_id = p.project_id
    WHERE ct.is_current = true
    LIMIT 1
  ),
  test_line AS (
    SELECT cl.id AS contract_line_id
    FROM contract_line cl
    JOIN contract c ON c.id = cl.contract_id
    JOIN proj p ON c.project_id = p.project_id
    WHERE cl.contract_line_number = 3000
      AND cl.energy_category = 'test'
      AND cl.is_active = true
    LIMIT 1
  )
INSERT INTO meter_aggregate (
  organization_id, meter_id, billing_period_id, clause_tariff_id,
  contract_line_id, period_type, period_start, period_end,
  energy_kwh, total_production, available_energy_kwh, source_system
)
SELECT
  (SELECT organization_id FROM proj),
  NULL,  -- no meter for test energy
  (SELECT billing_period_id FROM bp),
  (SELECT clause_tariff_id FROM ct),
  tl.contract_line_id,
  'monthly',
  '2025-12-01'::date,
  '2025-12-31'::date,
  945184.39,
  945184.39,
  0,
  'fixture_moh01_dec2025'
FROM test_line tl
WHERE EXISTS (SELECT 1 FROM bp) AND EXISTS (SELECT 1 FROM ct)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 8. Seed post-COD GRP (reference_price) for Sep-Dec 2025
-- ============================================================================
-- Carry forward Aug 2025 estimated GRP (2.0349 GHS/kWh) as operating_year=1

INSERT INTO reference_price (
  project_id, organization_id, operating_year,
  period_start, period_end, calculated_grp_per_kwh,
  currency_id, observation_type, verification_status
)
SELECT
  p.id, p.organization_id, 1,
  m.period_start, m.period_end, 2.0349,
  1, 'monthly', 'estimated'
FROM project p,
  (VALUES
    ('2025-09-01'::date, '2025-09-30'::date),
    ('2025-10-01'::date, '2025-10-31'::date),
    ('2025-11-01'::date, '2025-11-30'::date),
    ('2025-12-01'::date, '2025-12-31'::date)
  ) AS m(period_start, period_end)
WHERE p.external_project_id = 'MOH01'
  AND NOT EXISTS (
      SELECT 1 FROM reference_price rp
      WHERE rp.project_id = p.id
        AND rp.period_start = m.period_start
        AND rp.operating_year = 1
  );

-- ============================================================================
-- 9. Insert plant_performance for Dec 2025
-- ============================================================================
-- Regular generation only (excluding test energy):
--   Total metered = 27028.297 + 28254.406 + 22925.406 + 46677.219 + 24097.000 = 148982.328 kWh
--   Total available = 22613.900 kWh
--   Total energy = 171596.228 kWh
--   Forecast (Dec 2025) = 292826.089 kWh
--   energy_comparison = 171596.228 / 292826.089 ≈ 0.586

INSERT INTO plant_performance (
  project_id, organization_id, production_forecast_id,
  billing_period_id, billing_month, operating_year,
  energy_comparison
)
SELECT
  p.id,
  p.organization_id,
  pf.id,
  bp.id,
  '2025-12-01'::date,
  1,
  ROUND(171596.228 / pf.forecast_energy_kwh, 6)
FROM project p
JOIN production_forecast pf ON pf.project_id = p.id AND pf.forecast_month = '2025-12-01'
JOIN billing_period bp ON bp.start_date = '2025-12-01' AND bp.end_date = '2025-12-31'
WHERE p.external_project_id = 'MOH01'
  AND NOT EXISTS (
      SELECT 1 FROM plant_performance pp
      WHERE pp.project_id = p.id AND pp.billing_month = '2025-12-01'
  );

-- ============================================================================
-- 10. Clean up blank customer_contact rows
-- ============================================================================

DELETE FROM customer_contact
WHERE full_name IS NULL
  AND email IS NULL
  AND phone IS NULL;

COMMIT;
