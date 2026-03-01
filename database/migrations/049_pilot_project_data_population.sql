-- =============================================================================
-- 049_pilot_project_data_population.sql
-- =============================================================================
-- Populates contract_line, clause_tariff, meter_aggregate, and
-- contract_billing_product for 3 pilot projects: KAS01, NBL01, LOI01.
--
-- Source: CBE_data_extracts/Data Extracts/ CSV files
--   - dim_finance_contract_line.csv (DIM_CURRENT_RECORD=1)
--   - meter readings.csv
--
-- Pattern follows migration 047: CTE + sage_id joins, FK-safe, idempotent.
-- meter_id = NULL throughout (meters not available upfront).
--
-- Fixes applied from gap review:
--   - c.start_date → c.effective_date (contract table uses effective_date)
--   - total_production = utilized - discount - sourced (matches adapter math)
--   - WHERE NOT EXISTS on meter_aggregate inserts (idempotency)
--   - currency_id resolved by code subquery, not hardcoded
--   - billing_product_id resolved by name subquery, not hardcoded
--   - contract_line.billing_product_id set per line
-- =============================================================================

BEGIN;

-- =============================================================================
-- SECTION A: CONTRACT LINES
-- =============================================================================
-- Insert contract_line rows for KAS01, NBL01, LOI01 from CBE contract line CSV.
-- Only rows from active contracts (matched via external_contract_id).
-- Uses ON CONFLICT to be idempotent.

-- -----------------------------------------------------------------------------
-- A1: KAS01 — Kasapreko (contract CONGHA00-2021-00002, contract_id via join)
-- 4 lines: 1000 (metered), 2000 (available), 3000 (test/inactive), 4000 (metered)
-- -----------------------------------------------------------------------------
INSERT INTO contract_line (
    contract_id, contract_line_number, product_desc,
    energy_category, meter_id, external_line_id,
    effective_start_date, effective_end_date,
    billing_product_id, is_active, organization_id
)
SELECT
    c.id,
    v.line_num,
    v.product_desc,
    v.energy_cat::energy_category,
    NULL,  -- no meters yet
    v.ext_line_id,
    v.eff_start::date,
    v.eff_end::date,
    (SELECT id FROM billing_product WHERE name = v.bp_name ORDER BY id LIMIT 1),
    v.is_active,
    c.organization_id
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN (VALUES
    (1000, 'Metered Energy (EMetered) - Phase 1',     'metered',   '6183974810309858390',  '2021-01-01', '2030-02-28', true,  'Metered Energy (EMetered)'),
    (2000, 'Available Energy (EAvailable) Combined',   'available', '13961123603684840005', '2021-01-01', '2030-02-28', true,  'Available Energy (EAvailable)'),
    (3000, 'Inverter Energy - Phase 2',                'test',      '1681525089438628717',  '2021-01-01', '2030-02-28', false, 'Metered Energy (EMetered)'),
    (4000, 'Metered Energy (EMetered) - Phase 2',      'metered',   '12212917838699498756', '2025-02-01', '2030-02-28', true,  'Metered Energy (EMetered)')
) AS v(line_num, product_desc, energy_cat, ext_line_id, eff_start, eff_end, is_active, bp_name)
WHERE p.sage_id = 'KAS01'
  AND c.external_contract_id = 'CONGHA00-2021-00002'
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;

-- -----------------------------------------------------------------------------
-- A2: NBL01 — Nigerian Breweries Ibadan (contract CONNIG00-2021-00002)
-- 8 lines: mix of active/inactive grid and generator lines
-- -----------------------------------------------------------------------------
INSERT INTO contract_line (
    contract_id, contract_line_number, product_desc,
    energy_category, meter_id, external_line_id,
    effective_start_date, effective_end_date,
    billing_product_id, is_active, organization_id
)
SELECT
    c.id,
    v.line_num,
    v.product_desc,
    v.energy_cat::energy_category,
    NULL,
    v.ext_line_id,
    v.eff_start::date,
    v.eff_end::date,
    (SELECT id FROM billing_product WHERE name = v.bp_name ORDER BY id LIMIT 1),
    v.is_active,
    c.organization_id
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN (VALUES
    (1000,  'Grid (EMetered)',                           'metered',   '1788680542782056763',  '2021-03-01', '2036-03-31', false, 'Grid (EMetered)'),
    (3000,  'Grid (EAvailable)',                         'available', '708411035734251951',   '2021-03-01', '2036-03-31', false, 'Grid (EAvailable)'),
    (4000,  'Grid (EMetered)',                           'metered',   '14007392545771367849', '2021-02-01', '2021-03-01', false, 'Grid (EMetered)'),
    (5000,  'Grid (EAvailable)',                         'available', '18207875298225383549', '2021-02-01', '2021-03-01', false, 'Grid (EAvailable)'),
    (6000,  'Generator (EMetered) Phase 1',              'metered',   '9916550313842372826',  '2021-03-01', '2036-03-31', true,  'Generator (EMetered)'),
    (7000,  'Generator (EAvailable) Combined Facility',  'available', '16984048667943844105', '2021-03-01', '2036-03-31', true,  'Generator (EAvailable)'),
    (9000,  'Early Operating Energy Phase 2',            'test',      '14771095389500298754', '2024-11-01', '2036-03-31', false, 'Early Operating Energy'),
    (10000, 'Generator (EMetered) Phase 2',              'metered',   '6747506823328654925',  '2025-01-01', '2036-03-31', true,  'Generator (EMetered)')
) AS v(line_num, product_desc, energy_cat, ext_line_id, eff_start, eff_end, is_active, bp_name)
WHERE p.sage_id = 'NBL01'
  AND c.external_contract_id = 'CONNIG00-2021-00002'
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;

-- -----------------------------------------------------------------------------
-- A3: LOI01 — Loisaba (contract CONKEN00-2021-00002, active only)
-- 3 lines: 2 metered + 1 BESS capacity (test/non-energy)
-- Legacy contract CONCBEH0-2021-00002 excluded (ACTIVE=0)
-- -----------------------------------------------------------------------------
INSERT INTO contract_line (
    contract_id, contract_line_number, product_desc,
    energy_category, meter_id, external_line_id,
    effective_start_date, effective_end_date,
    billing_product_id, is_active, organization_id
)
SELECT
    c.id,
    v.line_num,
    v.product_desc,
    v.energy_cat::energy_category,
    NULL,
    v.ext_line_id,
    v.eff_start::date,
    v.eff_end::date,
    (SELECT id FROM billing_product WHERE name = v.bp_name ORDER BY id LIMIT 1),
    v.is_active,
    c.organization_id
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN (VALUES
    (1000, 'Loisaba HQ (EMetered)',    'metered', '2069257994463054735',  '2021-04-01', '2029-10-31', true,  'Loisaba HQ (EMetered)'),
    (2000, 'Loisaba Camp (EMetered)',   'metered', '11449263803432932680', '2021-04-01', '2029-10-31', true,  'Loisaba Camp (EMetered)'),
    (3000, 'BESS Capacity Charge',     'test',    '9680882150994362553',  '2021-04-01', '2029-10-31', true,  'BESS Capacity Charge')
) AS v(line_num, product_desc, energy_cat, ext_line_id, eff_start, eff_end, is_active, bp_name)
WHERE p.sage_id = 'LOI01'
  AND c.external_contract_id = 'CONKEN00-2021-00002'
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;


-- =============================================================================
-- SECTION B: CLAUSE TARIFFS (placeholder — rates populated after PPA parsing)
-- =============================================================================
-- One clause_tariff per pilot contract. base_rate = NULL until PPA extraction.
-- currency_id resolved via subquery on currency.code.

-- B1: KAS01 tariff placeholder
INSERT INTO clause_tariff (
    project_id, contract_id, currency_id, name,
    tariff_group_key, valid_from, valid_to,
    base_rate, unit, is_active, version, is_current,
    organization_id, created_at, updated_at
)
SELECT
    p.id, c.id,
    (SELECT id FROM currency WHERE code = 'GHS'),
    'GH-KAS01 Main Tariff',
    'CONGHA00-2021-00002-MAIN',
    c.effective_date,
    c.end_date,
    NULL, 'kWh', true, 1, true,
    c.organization_id, NOW(), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'KAS01'
  AND c.external_contract_id = 'CONGHA00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM clause_tariff ct
    WHERE ct.contract_id = c.id
      AND ct.tariff_group_key = 'CONGHA00-2021-00002-MAIN'
      AND ct.is_current = true
  );

-- B2: NBL01 tariff placeholder
INSERT INTO clause_tariff (
    project_id, contract_id, currency_id, name,
    tariff_group_key, valid_from, valid_to,
    base_rate, unit, is_active, version, is_current,
    organization_id, created_at, updated_at
)
SELECT
    p.id, c.id,
    (SELECT id FROM currency WHERE code = 'NGN'),
    'NG-NBL01 Main Tariff',
    'CONNIG00-2021-00002-MAIN',
    c.effective_date,
    c.end_date,
    NULL, 'kWh', true, 1, true,
    c.organization_id, NOW(), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'NBL01'
  AND c.external_contract_id = 'CONNIG00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM clause_tariff ct
    WHERE ct.contract_id = c.id
      AND ct.tariff_group_key = 'CONNIG00-2021-00002-MAIN'
      AND ct.is_current = true
  );

-- B3: LOI01 tariff placeholder (USD — per contract)
INSERT INTO clause_tariff (
    project_id, contract_id, currency_id, name,
    tariff_group_key, valid_from, valid_to,
    base_rate, unit, is_active, version, is_current,
    organization_id, created_at, updated_at
)
SELECT
    p.id, c.id,
    (SELECT id FROM currency WHERE code = 'USD'),
    'KE-LOI01 Main Tariff',
    'CONKEN00-2021-00002-MAIN',
    c.effective_date,
    c.end_date,
    NULL, 'kWh', true, 1, true,
    c.organization_id, NOW(), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'LOI01'
  AND c.external_contract_id = 'CONKEN00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM clause_tariff ct
    WHERE ct.contract_id = c.id
      AND ct.tariff_group_key = 'CONKEN00-2021-00002-MAIN'
      AND ct.is_current = true
  );

-- B4: LOI01 BESS capacity tariff placeholder
INSERT INTO clause_tariff (
    project_id, contract_id, currency_id, name,
    tariff_group_key, valid_from, valid_to,
    base_rate, unit, is_active, version, is_current,
    organization_id, created_at, updated_at
)
SELECT
    p.id, c.id,
    (SELECT id FROM currency WHERE code = 'USD'),
    'KE-LOI01 BESS Capacity',
    'CONKEN00-2021-00002-BESS',
    c.effective_date,
    c.end_date,
    NULL, 'month', true, 1, true,
    c.organization_id, NOW(), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'LOI01'
  AND c.external_contract_id = 'CONKEN00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM clause_tariff ct
    WHERE ct.contract_id = c.id
      AND ct.tariff_group_key = 'CONKEN00-2021-00002-BESS'
      AND ct.is_current = true
  );

-- B5: Link contract_lines to clause_tariffs
-- KAS01: metered + available lines → main tariff
UPDATE contract_line cl
SET clause_tariff_id = ct.id
FROM clause_tariff ct
JOIN contract c ON c.id = ct.contract_id
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'KAS01'
  AND ct.tariff_group_key = 'CONGHA00-2021-00002-MAIN'
  AND ct.is_current = true
  AND cl.contract_id = c.id
  AND cl.energy_category IN ('metered', 'available')
  AND cl.clause_tariff_id IS NULL;

-- NBL01: metered + available lines → main tariff
UPDATE contract_line cl
SET clause_tariff_id = ct.id
FROM clause_tariff ct
JOIN contract c ON c.id = ct.contract_id
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'NBL01'
  AND ct.tariff_group_key = 'CONNIG00-2021-00002-MAIN'
  AND ct.is_current = true
  AND cl.contract_id = c.id
  AND cl.energy_category IN ('metered', 'available')
  AND cl.clause_tariff_id IS NULL;

-- LOI01: metered lines → main tariff
UPDATE contract_line cl
SET clause_tariff_id = ct.id
FROM clause_tariff ct
JOIN contract c ON c.id = ct.contract_id
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'LOI01'
  AND ct.tariff_group_key = 'CONKEN00-2021-00002-MAIN'
  AND ct.is_current = true
  AND cl.contract_id = c.id
  AND cl.energy_category = 'metered'
  AND cl.clause_tariff_id IS NULL;

-- LOI01: BESS line → BESS tariff
UPDATE contract_line cl
SET clause_tariff_id = ct.id
FROM clause_tariff ct
JOIN contract c ON c.id = ct.contract_id
JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'LOI01'
  AND ct.tariff_group_key = 'CONKEN00-2021-00002-BESS'
  AND ct.is_current = true
  AND cl.contract_id = c.id
  AND cl.contract_line_number = 3000
  AND cl.clause_tariff_id IS NULL;


-- =============================================================================
-- SECTION C: METER AGGREGATES from CBE meter readings CSV
-- =============================================================================
-- Transform meter reading rows into meter_aggregate records.
-- billing_period_id resolved via end_date matching.
-- contract_line_id resolved via external_line_id matching.
-- meter_id = NULL (no meters yet).
--
-- total_production = utilized - discount - sourced (matches adapter semantics)
-- energy_kwh / available_energy_kwh use total_production (not raw utilized)
--
-- Idempotency: WHERE NOT EXISTS on (contract_line_id, billing_period_id, external_reading_id)

-- C1: KAS01 meter aggregates (36 readings, Jan-Dec 2025)
INSERT INTO meter_aggregate (
    billing_period_id, contract_line_id, meter_id,
    period_type, period_start, period_end,
    energy_kwh, available_energy_kwh, total_production,
    opening_reading, closing_reading, utilized_reading,
    discount_reading, sourced_energy,
    source_system, source_metadata, organization_id,
    aggregated_at
)
SELECT
    bp.id,
    cl.id,
    NULL,  -- no meter yet
    'monthly',
    v.period_start::date,
    v.period_end::date,
    CASE WHEN cl.energy_category = 'metered' THEN v.utilized - v.discount - v.sourced ELSE NULL END,
    CASE WHEN cl.energy_category = 'available' THEN v.utilized - v.discount - v.sourced ELSE NULL END,
    v.utilized - v.discount - v.sourced,  -- total_production matches adapter: utilized - discount - sourced
    v.opening,
    v.closing,
    v.utilized,
    v.discount,
    v.sourced,
    'snowflake',
    jsonb_build_object('external_reading_id', v.reading_id, 'product_desc', v.product_desc),
    1,
    NOW()
FROM (VALUES
    -- Jan 2025
    ('2025-01-01', '2025-01-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2735897, 2762251, 26354, 0, 0, '9997204856296035681'),
    ('2025-01-01', '2025-01-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 0, 0, 0, 0, '1530125809868713239'),
    ('2025-01-01', '2025-01-31', '1681525089438628717',  'Inverter Energy - Phase 2',               0, 67929.8103, 67929.8103, 0, 0, '6765776976078496565'),
    -- Feb 2025
    ('2025-02-01', '2025-02-28', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2762251, 2798073, 35822, 0, 0, '18258341241870950988'),
    ('2025-02-01', '2025-02-28', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 6675.98, 6675.98, 0, 0, '9553405900544065296'),
    ('2025-02-01', '2025-02-28', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    114650.5, 190948, 76297.5, 0, 0, '4052834461890800937'),
    -- Mar 2025
    ('2025-03-01', '2025-03-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2798073, 2845597, 47524, 0, 0, '3444062266570621341'),
    ('2025-03-01', '2025-03-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 5511.95, 5511.95, 0, 0, '18235003632098122499'),
    ('2025-03-01', '2025-03-31', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    190948, 296341.4, 105393.4, 0, 0, '2614531399507329235'),
    -- Apr 2025
    ('2025-04-01', '2025-04-30', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2845597, 2891405, 45808, 0, 0, '6276515739091839801'),
    ('2025-04-01', '2025-04-30', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 5833.34, 5833.34, 0, 0, '17822509079849248834'),
    ('2025-04-01', '2025-04-30', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    296341.4, 400325.4, 103984, 0, 0, '11128548851056908756'),
    -- May 2025
    ('2025-05-01', '2025-05-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2891405, 2937283, 45878, 0, 0, '15902658590716180657'),
    ('2025-05-01', '2025-05-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 4756, 4756, 0, 0, '17273431662276838112'),
    ('2025-05-01', '2025-05-31', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    400325.4, 502896.4, 102571, 0, 0, '5738675442565820191'),
    -- Jun 2025
    ('2025-06-01', '2025-06-30', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2937283, 2973403, 36120, 0, 0, '8451108502510195892'),
    ('2025-06-01', '2025-06-30', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 3048.44, 3048.44, 0, 0, '17771345643190989554'),
    ('2025-06-01', '2025-06-30', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    502896.4, 583851.4, 80955, 0, 0, '10540670025914596170'),
    -- Jul 2025
    ('2025-07-01', '2025-07-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    2973403, 3001999, 28596, 0, 0, '5769443794383733634'),
    ('2025-07-01', '2025-07-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 9275.0935, 9275.0935, 0, 0, '9399448073924979628'),
    ('2025-07-01', '2025-07-31', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    583851.4, 649418.3, 65566.9, 0, 0, '9671247581909135971'),
    -- Aug 2025
    ('2025-08-01', '2025-08-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    3001999, 3029129, 27130, 0, 0, '6211999590639699347'),
    ('2025-08-01', '2025-08-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 5542, 5542, 0, 0, '18374924299640310570'),
    ('2025-08-01', '2025-08-31', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    649418.3, 710891.9, 61473.6, 0, 0, '8967725211112017182'),
    -- Sep 2025
    ('2025-09-01', '2025-09-30', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    3029129, 3064876, 35747, 0, 0, '16726191833265538204'),
    ('2025-09-01', '2025-09-30', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 9971, 9971, 0, 0, '8876475363197172983'),
    ('2025-09-01', '2025-09-30', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    710891.9, 788922.6, 78030.7, 0, 0, '15138179436843790486'),
    -- Oct 2025
    ('2025-10-01', '2025-10-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    3064876, 3103911, 39035, 0, 0, '17702026636486459845'),
    ('2025-10-01', '2025-10-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 17447.81, 17447.81, 0, 0, '11426624414786549395'),
    ('2025-10-01', '2025-10-31', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    788922.6, 880168.8, 91246.2, 0, 0, '13152079359420032497'),
    -- Nov 2025
    ('2025-11-01', '2025-11-30', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    3103911, 3138669, 34758, 0, 0, '16536756609014912153'),
    ('2025-11-01', '2025-11-30', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 12450.9328, 12450.9328, 0, 0, '13454704126612369234'),
    ('2025-11-01', '2025-11-30', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    880168.8, 970114.3, 89945.5, 0, 0, '3735891979203939956'),
    -- Dec 2025
    ('2025-12-01', '2025-12-31', '6183974810309858390',  'Metered Energy (EMetered) - Phase 1',    3138669, 3178443, 39774, 0, 0, '5066988737315413732'),
    ('2025-12-01', '2025-12-31', '13961123603684840005', 'Available Energy (EAvailable) Combined',  0, 1641.45, 1641.45, 0, 0, '924194683965567652'),
    ('2025-12-01', '2025-12-31', '12212917838699498756', 'Metered Energy (EMetered) - Phase 2',    970114.3, 1061758.7, 91644.4, 0, 0, '16839886419650345040')
) AS v(period_start, period_end, ext_line_id, product_desc, opening, closing, utilized, discount, sourced, reading_id)
JOIN contract_line cl ON cl.external_line_id = v.ext_line_id AND cl.organization_id = 1
JOIN billing_period bp ON bp.end_date = v.period_end::date
WHERE NOT EXISTS (
    SELECT 1 FROM meter_aggregate ma
    WHERE ma.contract_line_id = cl.id
      AND ma.billing_period_id = bp.id
      AND ma.source_metadata->>'external_reading_id' = v.reading_id
);

-- C2: NBL01 meter aggregates (34 readings, Jan-Dec 2025)
INSERT INTO meter_aggregate (
    billing_period_id, contract_line_id, meter_id,
    period_type, period_start, period_end,
    energy_kwh, available_energy_kwh, total_production,
    opening_reading, closing_reading, utilized_reading,
    discount_reading, sourced_energy,
    source_system, source_metadata, organization_id,
    aggregated_at
)
SELECT
    bp.id,
    cl.id,
    NULL,
    'monthly',
    v.period_start::date,
    v.period_end::date,
    CASE WHEN cl.energy_category = 'metered' THEN v.utilized - v.discount - v.sourced ELSE NULL END,
    CASE WHEN cl.energy_category = 'available' THEN v.utilized - v.discount - v.sourced ELSE NULL END,
    v.utilized - v.discount - v.sourced,
    v.opening,
    v.closing,
    v.utilized,
    v.discount,
    v.sourced,
    'snowflake',
    jsonb_build_object('external_reading_id', v.reading_id, 'product_desc', v.product_desc),
    1,
    NOW()
FROM (VALUES
    -- Jan 2025 (lines 6000, 10000 only — no 7000 reading)
    ('2025-01-01', '2025-01-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    60802.71, 99573.79, 38771.08, 0, 0, '7014989119993323392'),
    ('2025-01-01', '2025-01-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    367190.91, 636993.98, 269803.07, 0, 3014.45, '5078969396236206240'),
    -- Feb 2025 (lines 6000, 10000)
    ('2025-02-01', '2025-02-28', '9916550313842372826',  'Generator (EMetered) Phase 1',    99573.79, 129862.38, 30288.59, 0, 0, '409584081230313346'),
    ('2025-02-01', '2025-02-28', '6747506823328654925',  'Generator (EMetered) Phase 2',    636993.98, 824675.71, 187681.73, 0, 5818.67, '5567950380068349647'),
    -- Mar 2025 (lines 6000, 7000, 10000)
    ('2025-03-01', '2025-03-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    129862.38, 163640.03, 33777.65, 0, 0, '1198702742455694959'),
    ('2025-03-01', '2025-03-31', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 15059.57, 15059.57, 0, 0, '4045882812866716537'),
    ('2025-03-01', '2025-03-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    824675.71, 1025708.86, 201033.15, 0, 2241.35, '7555875360116862910'),
    -- Apr 2025
    ('2025-04-01', '2025-04-30', '9916550313842372826',  'Generator (EMetered) Phase 1',    163640.03, 199091.95, 35451.92, 0, 0, '14376411332326369452'),
    ('2025-04-01', '2025-04-30', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 979.36, 979.36, 0, 0, '1048364972610550800'),
    ('2025-04-01', '2025-04-30', '6747506823328654925',  'Generator (EMetered) Phase 2',    1025708.86, 1253969.79, 228260.93, 0, 1853.18, '17093843518450062877'),
    -- May 2025
    ('2025-05-01', '2025-05-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    199091.95, 231792.59, 32700.64, 0, 0, '10617040933392408004'),
    ('2025-05-01', '2025-05-31', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 0, 0, 0, 0, '7614289095009719415'),
    ('2025-05-01', '2025-05-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    1253969.79, 1477423.23, 223453.44, 0, 3616.82, '2049904665065989146'),
    -- Jun 2025
    ('2025-06-01', '2025-06-30', '9916550313842372826',  'Generator (EMetered) Phase 1',    231792.59, 257916.77, 26124.18, 0, 0, '272398775852691818'),
    ('2025-06-01', '2025-06-30', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 0, 0, 0, 0, '1560385651272158068'),
    ('2025-06-01', '2025-06-30', '6747506823328654925',  'Generator (EMetered) Phase 2',    1477423.23, 1636822.14, 159398.91, 0, 2567.35, '12872972008536017316'),
    -- Jul 2025
    ('2025-07-01', '2025-07-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    257916.77, 280462.25, 22545.48, 0, 0, '7883143474821490152'),
    ('2025-07-01', '2025-07-31', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 0, 0, 0, 0, '8020137830011119809'),
    ('2025-07-01', '2025-07-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    1636822.14, 1802872.45, 166050.31, 0, 3576.26, '15089578000395156333'),
    -- Aug 2025
    ('2025-08-01', '2025-08-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    280462.25, 298474.44, 18012.19, 0, 0, '5692031391785397389'),
    ('2025-08-01', '2025-08-31', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 6282.5172, 6282.5172, 0, 0, '4009922972112033890'),
    ('2025-08-01', '2025-08-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    1802872.45, 1951865.86, 148993.41, 0, 5478.88, '2589989198986415914'),
    -- Sep 2025
    ('2025-09-01', '2025-09-30', '9916550313842372826',  'Generator (EMetered) Phase 1',    298474.44, 318908.48, 20434.04, 0, 0, '11856440102081302160'),
    ('2025-09-01', '2025-09-30', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 2392, 2392, 0, 0, '12737703883680320419'),
    ('2025-09-01', '2025-09-30', '6747506823328654925',  'Generator (EMetered) Phase 2',    1951865.86, 2137442.3, 185576.44, 0, 4103.24, '15540838550789339006'),
    -- Oct 2025
    ('2025-10-01', '2025-10-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    318908.48, 345814.92, 26906.44, 0, 0, '9383759931898510894'),
    ('2025-10-01', '2025-10-31', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 1807.46, 1807.46, 0, 0, '284225150392792542'),
    ('2025-10-01', '2025-10-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    2137442.3, 2385257.47, 247815.17, 0, 3989.83, '16285321709640365961'),
    -- Nov 2025
    ('2025-11-01', '2025-11-30', '9916550313842372826',  'Generator (EMetered) Phase 1',    345814.92, 392154.15, 46339.23, 0, 0, '6892374773177493375'),
    ('2025-11-01', '2025-11-30', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 4038.07, 4038.07, 0, 0, '6617854830933949608'),
    ('2025-11-01', '2025-11-30', '6747506823328654925',  'Generator (EMetered) Phase 2',    2385257.47, 2618653.95, 233396.48, 0, 3588.82, '6801938206157734031'),
    -- Dec 2025
    ('2025-12-01', '2025-12-31', '9916550313842372826',  'Generator (EMetered) Phase 1',    392154.15, 441890.54, 49736.39, 0, 0, '13118212614742454598'),
    ('2025-12-01', '2025-12-31', '16984048667943844105', 'Generator (EAvailable) Combined Facility', 0, 20.61, 20.61, 0, 0, '7718026587635248781'),
    ('2025-12-01', '2025-12-31', '6747506823328654925',  'Generator (EMetered) Phase 2',    2618653.95, 2882704.13, 264050.18, 0, 3860.3, '11898475359202176076')
) AS v(period_start, period_end, ext_line_id, product_desc, opening, closing, utilized, discount, sourced, reading_id)
JOIN contract_line cl ON cl.external_line_id = v.ext_line_id AND cl.organization_id = 1
JOIN billing_period bp ON bp.end_date = v.period_end::date
WHERE NOT EXISTS (
    SELECT 1 FROM meter_aggregate ma
    WHERE ma.contract_line_id = cl.id
      AND ma.billing_period_id = bp.id
      AND ma.source_metadata->>'external_reading_id' = v.reading_id
);

-- C3: LOI01 meter aggregates (24 readings, Jan-Dec 2025)
INSERT INTO meter_aggregate (
    billing_period_id, contract_line_id, meter_id,
    period_type, period_start, period_end,
    energy_kwh, available_energy_kwh, total_production,
    opening_reading, closing_reading, utilized_reading,
    discount_reading, sourced_energy,
    source_system, source_metadata, organization_id,
    aggregated_at
)
SELECT
    bp.id,
    cl.id,
    NULL,
    'monthly',
    v.period_start::date,
    v.period_end::date,
    CASE WHEN cl.energy_category = 'metered' THEN v.utilized - v.discount - v.sourced ELSE NULL END,
    CASE WHEN cl.energy_category = 'available' THEN v.utilized - v.discount - v.sourced ELSE NULL END,
    v.utilized - v.discount - v.sourced,
    v.opening,
    v.closing,
    v.utilized,
    v.discount,
    v.sourced,
    'snowflake',
    jsonb_build_object('external_reading_id', v.reading_id, 'product_desc', v.product_desc),
    1,
    NOW()
FROM (VALUES
    -- Jan 2025
    ('2025-01-01', '2025-01-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   271761, 275665.5, 3904.5, 0, 0, '14186277746286783122'),
    ('2025-01-01', '2025-01-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  409359.53, 414357.5, 4997.97, 0, 0, '9088369743393643673'),
    -- Feb 2025
    ('2025-02-01', '2025-02-28', '2069257994463054735',  'Loisaba HQ (EMetered)',   275665.5, 279618.5, 3953, 0, 0, '13220260937506521547'),
    ('2025-02-01', '2025-02-28', '11449263803432932680', 'Loisaba Camp (EMetered)',  414357.5, 418677.56, 4320.06, 0, 0, '14559153407594795759'),
    -- Mar 2025
    ('2025-03-01', '2025-03-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   279618.5, 283469.5, 3851, 0, 0, '11461846954743279415'),
    ('2025-03-01', '2025-03-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  418677.56, 422676.719, 3999.159, 0, 0, '13160763862015000255'),
    -- Apr 2025
    ('2025-04-01', '2025-04-30', '2069257994463054735',  'Loisaba HQ (EMetered)',   0, 4122.39, 4122.39, 206.12, 0, '14668976168999033843'),
    ('2025-04-01', '2025-04-30', '11449263803432932680', 'Loisaba Camp (EMetered)',  422676.719, 426816.531, 4139.812, 0, 0, '7245399423099733750'),
    -- May 2025
    ('2025-05-01', '2025-05-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   0, 3828.19, 3828.19, 191.41, 0, '185393571606220702'),
    ('2025-05-01', '2025-05-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  426816.531, 431033.906, 4217.375, 0, 0, '685402882604405198'),
    -- Jun 2025
    ('2025-06-01', '2025-06-30', '2069257994463054735',  'Loisaba HQ (EMetered)',   284141.7, 287774.6, 3632.9, 0, 0, '15022239677123811906'),
    ('2025-06-01', '2025-06-30', '11449263803432932680', 'Loisaba Camp (EMetered)',  431033.906, 435728.062, 4694.156, 0, 0, '10219187509416247193'),
    -- Jul 2025
    ('2025-07-01', '2025-07-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   287774.6, 291068.7, 3294.1, 0, 0, '4736932462258833879'),
    ('2025-07-01', '2025-07-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  435728.062, 440738.41, 5010.348, 0, 0, '2473569453163514097'),
    -- Aug 2025
    ('2025-08-01', '2025-08-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   291068.7, 294174.3, 3105.6, 0, 0, '215692166689733356'),
    ('2025-08-01', '2025-08-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  440738.41, 446401, 5662.59, 0, 0, '14165498573357701464'),
    -- Sep 2025
    ('2025-09-01', '2025-09-30', '2069257994463054735',  'Loisaba HQ (EMetered)',   294174.3, 297529.7, 3355.4, 0, 0, '11783785040977080650'),
    ('2025-09-01', '2025-09-30', '11449263803432932680', 'Loisaba Camp (EMetered)',  446401, 451371.56, 4970.56, 0, 0, '8897199064412147747'),
    -- Oct 2025
    ('2025-10-01', '2025-10-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   297529.7, 301394.1, 3864.4, 0, 0, '15036510615093864951'),
    ('2025-10-01', '2025-10-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  451371.56, 456467.81, 5096.25, 0, 0, '17469518881359736203'),
    -- Nov 2025
    ('2025-11-01', '2025-11-30', '2069257994463054735',  'Loisaba HQ (EMetered)',   301394.1, 305470.9, 4076.8, 0, 0, '6736695084717220403'),
    ('2025-11-01', '2025-11-30', '11449263803432932680', 'Loisaba Camp (EMetered)',  456467.81, 461445.13, 4977.32, 0, 0, '218593608235938106'),
    -- Dec 2025
    ('2025-12-01', '2025-12-31', '2069257994463054735',  'Loisaba HQ (EMetered)',   305470.9, 309499.5, 4028.6, 0, 0, '9218458139359345048'),
    ('2025-12-01', '2025-12-31', '11449263803432932680', 'Loisaba Camp (EMetered)',  461445.13, 467310.34, 5865.21, 0, 0, '10978446530736145201')
) AS v(period_start, period_end, ext_line_id, product_desc, opening, closing, utilized, discount, sourced, reading_id)
JOIN contract_line cl ON cl.external_line_id = v.ext_line_id AND cl.organization_id = 1
JOIN billing_period bp ON bp.end_date = v.period_end::date
WHERE NOT EXISTS (
    SELECT 1 FROM meter_aggregate ma
    WHERE ma.contract_line_id = cl.id
      AND ma.billing_period_id = bp.id
      AND ma.source_metadata->>'external_reading_id' = v.reading_id
);


-- =============================================================================
-- SECTION D: CONTRACT BILLING PRODUCTS
-- =============================================================================
-- Link each pilot contract to its billing products (junction records).
-- Resolved by name lookup, not hardcoded IDs.

-- D1: KAS01 — Metered Energy + Available Energy
INSERT INTO contract_billing_product (contract_id, billing_product_id, is_primary, created_at)
SELECT c.id, bp.id, (bp.name = 'Metered Energy (EMetered)'), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN (
    SELECT DISTINCT ON (name) id, name
    FROM billing_product
    WHERE name IN ('Metered Energy (EMetered)', 'Available Energy (EAvailable)')
    ORDER BY name, id
) bp
WHERE p.sage_id = 'KAS01'
  AND c.external_contract_id = 'CONGHA00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM contract_billing_product cbp
    WHERE cbp.contract_id = c.id AND cbp.billing_product_id = bp.id
  );

-- D2: NBL01 — Generator Metered + Generator Available
INSERT INTO contract_billing_product (contract_id, billing_product_id, is_primary, created_at)
SELECT c.id, bp.id, (bp.name = 'Generator (EMetered)'), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN (
    SELECT DISTINCT ON (name) id, name
    FROM billing_product
    WHERE name IN ('Generator (EMetered)', 'Generator (EAvailable)')
    ORDER BY name, id
) bp
WHERE p.sage_id = 'NBL01'
  AND c.external_contract_id = 'CONNIG00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM contract_billing_product cbp
    WHERE cbp.contract_id = c.id AND cbp.billing_product_id = bp.id
  );

-- D3: LOI01 — Loisaba HQ Metered + Loisaba Camp Metered + BESS Capacity
INSERT INTO contract_billing_product (contract_id, billing_product_id, is_primary, created_at)
SELECT c.id, bp.id, (bp.name = 'Loisaba HQ (EMetered)'), NOW()
FROM contract c
JOIN project p ON p.id = c.project_id
CROSS JOIN (
    SELECT DISTINCT ON (name) id, name
    FROM billing_product
    WHERE name IN ('Loisaba HQ (EMetered)', 'Loisaba Camp (EMetered)', 'BESS Capacity Charge')
    ORDER BY name, id
) bp
WHERE p.sage_id = 'LOI01'
  AND c.external_contract_id = 'CONKEN00-2021-00002'
  AND NOT EXISTS (
    SELECT 1 FROM contract_billing_product cbp
    WHERE cbp.contract_id = c.id AND cbp.billing_product_id = bp.id
  );


-- =============================================================================
-- SECTION E: POST-LOAD ASSERTIONS
-- =============================================================================

-- E1: Each pilot project has >= 1 active contract_line
DO $$
DECLARE
    v_sage_id VARCHAR;
    v_count INTEGER;
BEGIN
    FOR v_sage_id IN SELECT unnest(ARRAY['KAS01', 'NBL01', 'LOI01'])
    LOOP
        SELECT COUNT(*) INTO v_count
        FROM contract_line cl
        JOIN contract c ON c.id = cl.contract_id
        JOIN project p ON p.id = c.project_id
        WHERE p.sage_id = v_sage_id
          AND cl.is_active = true;

        IF v_count = 0 THEN
            RAISE EXCEPTION '049 assertion failed: % has 0 active contract_lines', v_sage_id;
        END IF;

        RAISE NOTICE '049: % has % active contract_lines', v_sage_id, v_count;
    END LOOP;
END $$;

-- E2: Each pilot contract has >= 1 clause_tariff
DO $$
DECLARE
    v_sage_id VARCHAR;
    v_count INTEGER;
BEGIN
    FOR v_sage_id IN SELECT unnest(ARRAY['KAS01', 'NBL01', 'LOI01'])
    LOOP
        SELECT COUNT(*) INTO v_count
        FROM clause_tariff ct
        JOIN project p ON p.id = ct.project_id
        WHERE p.sage_id = v_sage_id
          AND ct.is_current = true;

        IF v_count = 0 THEN
            RAISE EXCEPTION '049 assertion failed: % has 0 current clause_tariffs', v_sage_id;
        END IF;

        RAISE NOTICE '049: % has % current clause_tariffs', v_sage_id, v_count;
    END LOOP;
END $$;

-- E3: Each pilot project has >= 1 meter_aggregate
DO $$
DECLARE
    v_sage_id VARCHAR;
    v_count INTEGER;
BEGIN
    FOR v_sage_id IN SELECT unnest(ARRAY['KAS01', 'NBL01', 'LOI01'])
    LOOP
        SELECT COUNT(*) INTO v_count
        FROM meter_aggregate ma
        JOIN contract_line cl ON cl.id = ma.contract_line_id
        JOIN contract c ON c.id = cl.contract_id
        JOIN project p ON p.id = c.project_id
        WHERE p.sage_id = v_sage_id;

        IF v_count = 0 THEN
            RAISE EXCEPTION '049 assertion failed: % has 0 meter_aggregates', v_sage_id;
        END IF;

        RAISE NOTICE '049: % has % meter_aggregate records', v_sage_id, v_count;
    END LOOP;
END $$;

-- E4: No duplicate external_line_id within organization
DO $$
DECLARE
    v_dup_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_dup_count
    FROM (
        SELECT external_line_id
        FROM contract_line
        WHERE external_line_id IS NOT NULL
          AND organization_id = 1
        GROUP BY external_line_id
        HAVING COUNT(*) > 1
    ) dupes;

    IF v_dup_count > 0 THEN
        RAISE EXCEPTION '049 assertion failed: % duplicate external_line_id values found', v_dup_count;
    END IF;
END $$;

-- E5: No duplicate meter_aggregate rows (external_reading_id uniqueness)
DO $$
DECLARE
    v_dup_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_dup_count
    FROM (
        SELECT source_metadata->>'external_reading_id' AS rid
        FROM meter_aggregate
        WHERE source_metadata->>'external_reading_id' IS NOT NULL
          AND organization_id = 1
        GROUP BY source_metadata->>'external_reading_id'
        HAVING COUNT(*) > 1
    ) dupes;

    IF v_dup_count > 0 THEN
        RAISE EXCEPTION '049 assertion failed: % duplicate external_reading_id values found', v_dup_count;
    END IF;
END $$;

-- E6: Summary counts
DO $$
DECLARE
    v_lines INTEGER;
    v_tariffs INTEGER;
    v_aggregates INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_lines
    FROM contract_line cl
    JOIN contract c ON c.id = cl.contract_id
    JOIN project p ON p.id = c.project_id
    WHERE p.sage_id IN ('KAS01', 'NBL01', 'LOI01');

    SELECT COUNT(*) INTO v_tariffs
    FROM clause_tariff ct
    JOIN project p ON p.id = ct.project_id
    WHERE p.sage_id IN ('KAS01', 'NBL01', 'LOI01');

    SELECT COUNT(*) INTO v_aggregates
    FROM meter_aggregate ma
    JOIN contract_line cl ON cl.id = ma.contract_line_id
    JOIN contract c ON c.id = cl.contract_id
    JOIN project p ON p.id = c.project_id
    WHERE p.sage_id IN ('KAS01', 'NBL01', 'LOI01');

    RAISE NOTICE '049 SUMMARY: % contract_lines, % clause_tariffs, % meter_aggregates for 3 pilot projects',
        v_lines, v_tariffs, v_aggregates;
END $$;

COMMIT;
