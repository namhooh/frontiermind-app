-- Migration 054: Sage ID alias reversal, data fixes, additional external IDs, phase_cod_date
--
-- Changes:
--   1. Reverse sage_id aliases: GC01 → GC001, ZO01 → ZL01
--   2. Data fix: MOH01 cod_date → 2025-12-12 (from xlsx)
--   3. Data fix: NBL01 counterparty name → Heineken (offtaker, not CBE SPV)
--   4. Schema: Add additional_external_ids TEXT[] for multi-phase project IDs
--   5. Schema: Add phase_cod_date to contract_line
--   6. Populate multi-phase external IDs for QMM01, NBL01

BEGIN;

-- ============================================================================
-- 1. Reverse sage_id aliases
-- ============================================================================

-- GC01 → GC001 (restore original SAGE customer number)
UPDATE project
SET sage_id = 'GC001'
WHERE sage_id = 'GC01' AND organization_id = 1;

-- ZO01 → ZL01 (restore original SAGE customer number)
UPDATE project
SET sage_id = 'ZL01'
WHERE sage_id = 'ZO01' AND organization_id = 1;

-- Update extraction_metadata: remove source_sage_customer_id since sage_id now matches source
UPDATE contract
SET extraction_metadata = extraction_metadata - 'source_sage_customer_id'
WHERE project_id IN (
    SELECT id FROM project WHERE sage_id IN ('GC001', 'ZL01') AND organization_id = 1
)
AND extraction_metadata ? 'source_sage_customer_id';

-- ============================================================================
-- 2. Data fix: MOH01 cod_date
-- ============================================================================

UPDATE project
SET cod_date = '2025-12-12'::date
WHERE sage_id = 'MOH01' AND organization_id = 1;

-- ============================================================================
-- 3. Data fix: NBL01 counterparty name
-- ============================================================================

UPDATE counterparty
SET name = 'Heineken'
WHERE id = (
    SELECT c.counterparty_id
    FROM contract c
    JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'NBL01'
      AND p.organization_id = 1
      AND c.parent_contract_id IS NULL
    LIMIT 1
);

-- ============================================================================
-- 4. Schema: Add additional_external_ids for multi-phase projects
-- ============================================================================
-- Keeps external_project_id as the primary scalar lookup key (used in ~30+ code paths).
-- additional_external_ids stores secondary phase/expansion IDs.

ALTER TABLE project
    ADD COLUMN IF NOT EXISTS additional_external_ids TEXT[];

COMMENT ON COLUMN project.additional_external_ids IS 'Secondary client-defined project identifiers for multi-phase projects (e.g., QMM01 Phase 2 ID). Primary ID stays in external_project_id.';

-- ============================================================================
-- 5. Schema: Add phase_cod_date to contract_line
-- ============================================================================

ALTER TABLE contract_line
    ADD COLUMN IF NOT EXISTS phase_cod_date DATE;

COMMENT ON COLUMN contract_line.phase_cod_date IS 'Phase-specific Commercial Operations Date. Use when a project has multiple phases with different COD dates (e.g., KAS01 Phase 1 vs Phase 2).';

-- ============================================================================
-- 6. Populate multi-phase external IDs
-- ============================================================================

-- QMM01: primary='MG 22017', Phase 2='MG 22452'
UPDATE project
SET additional_external_ids = ARRAY['MG 22452']
WHERE sage_id = 'QMM01' AND organization_id = 1;

-- NBL01: primary='NG 22016', Phase 2='NG 22051'
UPDATE project
SET additional_external_ids = ARRAY['NG 22051']
WHERE sage_id = 'NBL01' AND organization_id = 1;

COMMIT;

-- ============================================================================
-- Step 2: XF-AB Split + ZL02 Contracts
-- ============================================================================

BEGIN;

-- ─── Part A: Rename XF-AB → XFAB ────────────────────────────────────────────
-- Primary contract (id=31, CONKEN00-2021-00003) stays.
-- Ancillary contracts (id=53,54) stay as children.
UPDATE project SET sage_id = 'XFAB' WHERE sage_id = 'XF-AB' AND organization_id = 1;

-- Update counterparty name from "XFlora Group" to "Xflora Africa Blooms"
UPDATE counterparty
SET name = 'Xflora Africa Blooms'
WHERE id = (
    SELECT c.counterparty_id
    FROM contract c
    JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'XFAB'
      AND p.organization_id = 1
      AND c.parent_contract_id IS NULL
    LIMIT 1
);

-- ─── Part B: Create 3 new counterparties + projects + contracts ──────────────

-- XFBV: Xflora Bloom Valley
INSERT INTO counterparty (name)
VALUES ('Xflora Bloom Valley');

INSERT INTO project (name, sage_id, country, organization_id)
VALUES ('Xflora Bloom Valley', 'XFBV', 'Kenya', 1);

INSERT INTO contract (
    project_id, counterparty_id, name, external_contract_id,
    payment_terms, effective_date, end_date,
    extraction_metadata, organization_id
)
VALUES (
    (SELECT id FROM project WHERE sage_id = 'XFBV' AND organization_id = 1),
    (SELECT id FROM counterparty WHERE name = 'Xflora Bloom Valley' ORDER BY id DESC LIMIT 1),
    'Xflora Bloom Valley SSA',
    'CONKEN00-2021-00004',
    '30NET',
    '2021-04-01'::date,
    '2047-05-31'::date,
    '{"source": "sage_csv", "contract_currency": "USD"}'::jsonb,
    1
);

-- Contract lines for XFBV (metered + available)
INSERT INTO contract_line (contract_id, contract_line_number, product_desc, energy_category, is_active, organization_id)
VALUES
    ((SELECT id FROM contract WHERE external_contract_id = 'CONKEN00-2021-00004'), 1000, 'Metered Energy', 'metered', true, 1),
    ((SELECT id FROM contract WHERE external_contract_id = 'CONKEN00-2021-00004'), 2000, 'Available Energy', 'available', true, 1);

-- XFL01: Xpressions Flora
INSERT INTO counterparty (name)
VALUES ('Xpressions Flora');

INSERT INTO project (name, sage_id, country, organization_id)
VALUES ('Xpressions Flora', 'XFL01', 'Kenya', 1);

INSERT INTO contract (
    project_id, counterparty_id, name, external_contract_id,
    payment_terms, effective_date, end_date,
    extraction_metadata, organization_id
)
VALUES (
    (SELECT id FROM project WHERE sage_id = 'XFL01' AND organization_id = 1),
    (SELECT id FROM counterparty WHERE name = 'Xpressions Flora' ORDER BY id DESC LIMIT 1),
    'Xpressions Flora SSA',
    'CONKEN00-2021-00005',
    '30NET',
    '2021-04-01'::date,
    '2047-05-31'::date,
    '{"source": "sage_csv", "contract_currency": "USD"}'::jsonb,
    1
);

INSERT INTO contract_line (contract_id, contract_line_number, product_desc, energy_category, is_active, organization_id)
VALUES
    ((SELECT id FROM contract WHERE external_contract_id = 'CONKEN00-2021-00005'), 1000, 'Metered Energy', 'metered', true, 1),
    ((SELECT id FROM contract WHERE external_contract_id = 'CONKEN00-2021-00005'), 2000, 'Available Energy', 'available', true, 1);

-- XFSS: Sojanmi Spring
INSERT INTO counterparty (name)
VALUES ('Sojanmi Spring');

INSERT INTO project (name, sage_id, country, organization_id)
VALUES ('Sojanmi Spring', 'XFSS', 'Kenya', 1);

INSERT INTO contract (
    project_id, counterparty_id, name, external_contract_id,
    payment_terms, effective_date, end_date,
    extraction_metadata, organization_id
)
VALUES (
    (SELECT id FROM project WHERE sage_id = 'XFSS' AND organization_id = 1),
    (SELECT id FROM counterparty WHERE name = 'Sojanmi Spring' ORDER BY id DESC LIMIT 1),
    'Sojanmi Spring SSA',
    'CONKEN00-2021-00006',
    '30EOM',
    '2021-04-01'::date,
    '2047-05-31'::date,
    '{"source": "sage_csv", "contract_currency": "USD"}'::jsonb,
    1
);

INSERT INTO contract_line (contract_id, contract_line_number, product_desc, energy_category, is_active, organization_id)
VALUES
    ((SELECT id FROM contract WHERE external_contract_id = 'CONKEN00-2021-00006'), 1000, 'Metered Energy', 'metered', true, 1),
    ((SELECT id FROM contract WHERE external_contract_id = 'CONKEN00-2021-00006'), 2000, 'Available Energy', 'available', true, 1);

-- ─── Part C: ZL02 Contracts ─────────────────────────────────────────────────
-- ZL02 project already exists. Insert 4 SAGE contracts under existing counterparty.

-- Insert 4 contracts under ZL02 using existing counterparty
INSERT INTO contract (
    project_id, counterparty_id, name, external_contract_id,
    payment_terms, effective_date, end_date,
    extraction_metadata, organization_id
)
SELECT
    p.id,
    (SELECT c.counterparty_id FROM contract c WHERE c.project_id = p.id AND c.parent_contract_id IS NULL LIMIT 1),
    format('ZL02 %s (%s)', v.category, v.currency),
    v.ext_id,
    v.terms,
    v.start_dt::date,
    v.end_dt::date,
    format('{"source": "sage_csv", "contract_category": "%s", "contract_currency": "%s"}', v.category, v.currency)::jsonb,
    1
FROM project p
CROSS JOIN (VALUES
    ('CONCBCH0-2025-00002', 'RENTAL', 'USD', '30NET', '2025-03-01', '2035-11-30'),
    ('CONCBCH0-2025-00003', 'OM',     'USD', '30NET', '2025-03-01', '2035-11-30'),
    ('CONCBCH0-2025-00004', 'RENTAL', 'USD', '30NET', '2025-06-01', '2025-12-31'),
    ('CONSLL02-2025-00003', 'OM',     'SLE', '30NET', '2025-03-01', '2035-11-30')
) AS v(ext_id, category, currency, terms, start_dt, end_dt)
WHERE p.sage_id = 'ZL02' AND p.organization_id = 1;

-- ─── Part D: Assertions ─────────────────────────────────────────────────────
DO $$
DECLARE
    project_count INT;
    xfab_contracts INT;
    xfbv_contracts INT;
    xfl01_contracts INT;
    xfss_contracts INT;
    zl02_contracts INT;
    ancillary_on_xfab INT;
BEGIN
    -- 35 total projects (was 32, +3 XFlora sub-farms)
    SELECT COUNT(*) INTO project_count
    FROM project WHERE organization_id = 1;
    IF project_count != 35 THEN
        RAISE EXCEPTION 'Expected 35 projects, got %', project_count;
    END IF;

    -- XFAB has 1 primary contract
    SELECT COUNT(*) INTO xfab_contracts
    FROM contract c JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'XFAB' AND p.organization_id = 1 AND c.parent_contract_id IS NULL;
    IF xfab_contracts < 1 THEN
        RAISE EXCEPTION 'XFAB should have at least 1 primary contract, got %', xfab_contracts;
    END IF;

    -- XFBV, XFL01, XFSS each have 1 primary contract
    SELECT COUNT(*) INTO xfbv_contracts
    FROM contract c JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'XFBV' AND p.organization_id = 1 AND c.parent_contract_id IS NULL;
    IF xfbv_contracts != 1 THEN
        RAISE EXCEPTION 'XFBV should have 1 primary contract, got %', xfbv_contracts;
    END IF;

    SELECT COUNT(*) INTO xfl01_contracts
    FROM contract c JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'XFL01' AND p.organization_id = 1 AND c.parent_contract_id IS NULL;
    IF xfl01_contracts != 1 THEN
        RAISE EXCEPTION 'XFL01 should have 1 primary contract, got %', xfl01_contracts;
    END IF;

    SELECT COUNT(*) INTO xfss_contracts
    FROM contract c JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'XFSS' AND p.organization_id = 1 AND c.parent_contract_id IS NULL;
    IF xfss_contracts != 1 THEN
        RAISE EXCEPTION 'XFSS should have 1 primary contract, got %', xfss_contracts;
    END IF;

    -- ZL02 has ≥4 contracts
    SELECT COUNT(*) INTO zl02_contracts
    FROM contract c JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'ZL02' AND p.organization_id = 1;
    IF zl02_contracts < 4 THEN
        RAISE EXCEPTION 'ZL02 should have ≥4 contracts, got %', zl02_contracts;
    END IF;

    -- Ancillary contracts (id=53,54) still on XFAB
    SELECT COUNT(*) INTO ancillary_on_xfab
    FROM contract c JOIN project p ON p.id = c.project_id
    WHERE p.sage_id = 'XFAB' AND p.organization_id = 1 AND c.parent_contract_id IS NOT NULL;
    IF ancillary_on_xfab < 2 THEN
        RAISE EXCEPTION 'XFAB should have ≥2 ancillary contracts, got %', ancillary_on_xfab;
    END IF;

    RAISE NOTICE 'All Step 2 assertions passed: % projects, XFlora split OK, ZL02 contracts OK', project_count;
END $$;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Check sage_id alias reversal
SELECT sage_id, name, country
FROM project
WHERE sage_id IN ('GC001', 'ZL01') AND organization_id = 1;
-- Expected: GC001 (Garden City Mall, Kenya), ZL01 (Zoodlabs Group, Sierra Leone)

-- Check MOH01 cod_date
SELECT sage_id, cod_date FROM project WHERE sage_id = 'MOH01' AND organization_id = 1;
-- Expected: 2025-12-12

-- Check NBL01 counterparty
SELECT p.sage_id, cp.name
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
JOIN counterparty cp ON cp.id = c.counterparty_id
WHERE p.sage_id = 'NBL01' AND p.organization_id = 1;
-- Expected: Heineken

-- Check multi-phase external IDs
SELECT sage_id, external_project_id, additional_external_ids
FROM project
WHERE sage_id IN ('QMM01', 'NBL01') AND organization_id = 1;
-- Expected: QMM01 = 'MG 22017' + {'MG 22452'}, NBL01 = 'NG 22016' + {'NG 22051'}

-- Check phase_cod_date column exists
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'contract_line' AND column_name = 'phase_cod_date';
-- Expected: 1 row, type = date

-- Check XFlora split
SELECT sage_id, name, country FROM project
WHERE sage_id IN ('XFAB','XFBV','XFL01','XFSS') AND organization_id = 1;
-- Expected: 4 rows

-- Check ZL02 contracts
SELECT p.sage_id, c.external_contract_id, c.payment_terms
FROM contract c JOIN project p ON p.id = c.project_id
WHERE p.sage_id = 'ZL02' AND p.organization_id = 1;
-- Expected: ≥4 rows

-- Total project count
SELECT COUNT(*) FROM project WHERE organization_id = 1;
-- Expected: 35

-- ============================================================================
-- Step 4: Billing Product & Tariff Structure
-- (formerly migration 055)
-- ============================================================================
--
-- Depends on: Step 2 above (sage_id aliases, XFlora split, ZL02 contracts)
-- Depends on: Step 3 complete (114 contract_lines across 31 projects)
--
-- This section:
--   A. Fixes NULL contract_type_id on auto-created / split contracts
--   B. Links contract_line.billing_product_id to canonical billing products
--   C. Inserts contract_billing_product junction (distinct products per contract)
--   D. Inserts clause_tariff placeholders (one per contract, base_rate NULL)
--   E. Verification gates

BEGIN;

-- =============================================================================
-- SECTION A: Fix NULL contract_type_id
-- =============================================================================
-- Auto-created contracts from Step 3 and XFlora split contracts have NULL
-- contract_type_id. Set them based on their contract lines and SAGE context.

-- NBL01 pilot contract (NULL from original seeding)
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'PPA')
WHERE id = 36 AND contract_type_id IS NULL;

-- LOI01 pilot contract (ESA — BESS + metered energy)
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'ESA')
WHERE id = 22 AND contract_type_id IS NULL;

-- IVL01 O&M contract (auto-created in Step 3)
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'OTHER')
WHERE id = 100 AND contract_type_id IS NULL;

-- TWG01 O&M contract (auto-created in Step 3)
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'OTHER')
WHERE id = 101 AND contract_type_id IS NULL;

-- XFlora sub-farm contracts (split from XF-AB in migration 054)
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'PPA')
WHERE id IN (93, 94, 95) AND contract_type_id IS NULL;

-- ZL02 contracts (created in migration 054)
-- 96: CONCBCH0-2025-00002 → ESA Lease
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'LEASE')
WHERE id = 96 AND contract_type_id IS NULL;
-- 97: CONCBCH0-2025-00003 → O&M
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'OTHER')
WHERE id = 97 AND contract_type_id IS NULL;
-- 98: CONCBCH0-2025-00004 → Penalties
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'OTHER')
WHERE id = 98 AND contract_type_id IS NULL;
-- 99: CONSLL02-2025-00003 → Diesel supply
UPDATE contract SET contract_type_id = (SELECT id FROM contract_type WHERE code = 'OTHER')
WHERE id = 99 AND contract_type_id IS NULL;


-- =============================================================================
-- SECTION B: Link contract_line.billing_product_id
-- =============================================================================
-- Maps each contract_line to its canonical billing_product based on product
-- description pattern + country/facility context.
--
-- Country-specific product code prefixes (from SAGE ERP):
--   Ghana:       GHREVS001/002 (metered/available), GHREV001/002 (grid avail/metered)
--   Kenya:       KEREVS001/002 (metered/available), KEREVS003-010 (site-specific)
--   Nigeria:     NIREVS008-011 (grid/generator × metered/available), NIREVS001/002
--   Egypt:       EGREVS001/002
--   Generic:     ENER001 (early/test), ENER002/003 (metered/available), ENER004 (min offtake)
--   Mozambique:  MOREVS001 (rent), MOREVS002 (O&M)
--   BESS:        MAREVS003

WITH bp_mapping(cl_id, bp_code) AS (
  VALUES
    -- AMP01 (Kenya, ESA, contract 32)
    (53, 'KEREVS008'),   -- Fixed Monthly Rental - Battery Equipment
    (55, 'KEREVS001'),   -- Metered Energy (EMetered)
    (54, 'ENER004'),     -- Minimum Offtake Shortfall

    -- AR01 (Kenya, LEASE, contract 21)
    (56, 'KEREVS008'),   -- Equipment Lease Rental

    -- CAL01 (Zimbabwe, PPA, contract 41)
    (59, 'ENER002'),     -- Green Metered Energy (EMetered)
    (57, 'ENER003'),     -- Green Available Energy (EAvailable)
    (60, 'ENER002'),     -- Green Metered Energy (EMetered) - 1 - 14 Apr
    (58, 'ENER003'),     -- Green Deemed Energy (EDeemed)

    -- ERG (Madagascar, ESA, contract 34)
    (62, 'ENER002'),     -- Metered Energy (EMetered)
    (61, 'ENER004'),     -- Minimum Offtake

    -- GBL01 (Ghana, PPA, contract 18)
    (63, 'GHREV001'),    -- Grid (EAvailable)
    (64, 'GHREV002'),    -- Grid (EMetered)

    -- GC001 (Kenya, LEASE, contract 16)
    (67, 'KEREVS006'),   -- Metered Energy (EMetered) - Substation 1
    (66, 'KEREVS007'),   -- Metered Energy (EMetered) - Substation 3
    (65, 'KEREVS001'),   -- Pricing Correction July 2025

    -- IVL01 (Egypt, PPA, contract 17)
    (70, 'EGREVS001'),   -- Metered Energy (EMetered)
    (69, 'EGREVS002'),   -- Available Energy (EAvailable)

    -- IVL01 (Egypt, OM auto-created, contract 100)
    (68, 'ENER001'),     -- COD Delay Penalty

    -- JAB01 (Nigeria, PPA, contract 35)
    (72, 'NIREVS008'),   -- Grid (EMetered)
    (74, 'NIREVS009'),   -- Generator (EMetered)
    (73, 'NIREVS010'),   -- Grid (EAvailable)
    (71, 'NIREVS011'),   -- Generator (EAvailable)

    -- KAS01 (Ghana, PPA, contract 19)
    (76, 'GHREVS001'),   -- Metered Energy (EMetered) - Phase 1
    (78, 'GHREVS002'),   -- Available Energy (EAvailable) Combined
    (77, 'ENER001'),     -- Inverter Energy - Phase 2
    (75, 'GHREVS001'),   -- Metered Energy (EMetered) - Phase 2

    -- LOI01 (Kenya, contract 22)
    (79, 'KEREVS003'),   -- Loisaba HQ (EMetered)
    (80, 'KEREVS004'),   -- Loisaba Camp (EMetered)
    (81, 'MAREVS003'),   -- BESS Capacity Charge

    -- MB01 (Kenya, PPA, contract 23)
    (85, 'KEREVS002'),   -- Available Energy (EAvailable) - Combined (inactive)
    (82, 'KEREVS001'),   -- Metered Energy (EMetered) - Combined (inactive)
    (84, 'ENER004'),     -- Minimum Offtake
    (86, 'KEREVS001'),   -- Metered Energy (EMetered) - Site A
    (83, 'KEREVS001'),   -- Metered Energy (EMetered) - Site B
    (88, 'KEREVS002'),   -- Available Energy (EAvailable) - Site A (inactive)
    (87, 'KEREVS002'),   -- Available Energy (EAvailable) - Site B (inactive)

    -- MF01 (Kenya, PPA, contract 24)
    (93, 'KEREVS002'),   -- Available Energy (EAvailable) - Combined (inactive)
    (92, 'KEREVS001'),   -- Metered Energy (EMetered) - Combined (inactive)
    (91, 'ENER004'),     -- Minimum Offtake (inactive)
    (89, 'KEREVS001'),   -- Metered Energy (EMetered) - Site A
    (90, 'KEREVS001'),   -- Metered Energy (EMetered) - Site B

    -- MIR01 (Sierra Leone, PPA, contract 38)
    (95, 'ENER002'),     -- Metered Energy (EMetered)
    (94, 'ENER003'),     -- Available Energy (EAvailable)

    -- MOH01 (Ghana, PPA, contract 7) — pilot: uses ENER* generic codes
    (96, 'ENER003'),     -- Available Energy (EAvailable)
    (97, 'ENER001'),     -- Early Operating Energy 15 Aug - 11 Dec
    (100, 'ENER002'),    -- Metered Energy (EMetered) - PPL1
    (101, 'ENER002'),    -- Metered Energy (EMetered) - PPL2
    (99, 'ENER002'),     -- Metered Energy (EMetered) - Bottles
    (102, 'ENER002'),    -- Metered Energy (EMetered) - BBM1
    (98, 'ENER002'),     -- Metered Energy (EMetered) - BBM2

    -- MP01 (Kenya, PPA, contract 26)
    (105, 'ENER004'),    -- Minimum Offtake
    (104, 'KEREVS002'),  -- Available Energy (EAvailable) (inactive)
    (103, 'KEREVS001'),  -- Metered Energy (EMetered)

    -- MP02 (Kenya, PPA, contract 25)
    (109, 'ENER004'),    -- Minimum Offtake
    (108, 'KEREVS001'),  -- Metered Energy (EMetered) - Combined (inactive)
    (110, 'KEREVS002'),  -- Available Energy (EAvailable) - Combined (inactive)
    (107, 'KEREVS001'),  -- Metered Energy (EMetered) - Site A
    (106, 'KEREVS001'),  -- Metered Energy (EMetered) - Site B

    -- NBL01 (Nigeria, PPA, contract 36)
    (117, 'NIREVS008'),  -- Grid (EMetered) (inactive)
    (116, 'NIREVS010'),  -- Grid (EAvailable) (inactive)
    (115, 'NIREVS008'),  -- Grid (EMetered) (inactive)
    (118, 'NIREVS010'),  -- Grid (EAvailable) (inactive)
    (112, 'NIREVS009'),  -- Generator (EMetered) Phase 1
    (113, 'NIREVS011'),  -- Generator (EAvailable) Combined Facility
    (111, 'ENER001'),    -- Early Operating Energy Phase 2 (inactive)
    (114, 'NIREVS009'),  -- Generator (EMetered) Phase 2

    -- NBL02 (Nigeria, PPA, contract 37)
    (119, 'NIREVS009'),  -- Generator (EMetered)
    (120, 'NIREVS011'),  -- Generator (EAvailable)

    -- NC02 (Kenya, PPA, contract 27)
    (121, 'KEREVS002'),  -- Available Energy (EAvailable) (inactive)
    (122, 'KEREVS001'),  -- Metered Energy (EMetered)
    (123, 'ENER004'),    -- Minimum Offtake

    -- NC03 (Kenya, PPA, contract 28)
    (126, 'ENER004'),    -- Minimum Offtake
    (124, 'KEREVS002'),  -- Available Energy (EAvailable) (inactive)
    (125, 'KEREVS001'),  -- Metered Energy (EMetered)

    -- QMM01 (Madagascar, PPA, contract 33)
    (131, 'ENER002'),    -- Metered Energy (EMetered) Phase 1 (inactive)
    (129, 'ENER003'),    -- Available Energy (EAvailable) Phase 1 (inactive)
    (127, 'MAREVS003'),  -- BESS Capacity Charge (inactive)
    (130, 'ENER001'),    -- Early Operating Energy - Wind
    (132, 'ENER002'),    -- Metered Energy (EMetered) Expanded PV
    (133, 'ENER003'),    -- Available Energy (EAvailable) Combined Facility
    (128, 'ENER002'),    -- Metered Energy (EMetered) Wind (inactive)
    (134, 'MAREVS003'),  -- Expanded BESS Capacity Charge

    -- TBM01 (Kenya, PPA, contract 29)
    (137, 'KEREVS001'),  -- Metered Energy (EMetered)
    (136, 'KEREVS002'),  -- Available Energy (EAvailable)
    (135, 'KEREVS001'),  -- Pricing Correction - July 2025

    -- TWG01 (Mozambique, OM auto-created, contract 101)
    (138, 'MOREVS002'),  -- Operations & Maintenance (O&M)

    -- TWG01 (Mozambique, LEASE, contract 40)
    (139, 'MOREVS001'),  -- Equipment Lease Rental

    -- UGL01 (Ghana, PPA, contract 20)
    (143, 'GHREVS001'),  -- Metered Energy (EMetered)
    (140, 'GHREVS002'),  -- Available Energy (EAvailable)
    (142, 'ENER001'),    -- Inverter Energy
    (141, 'ENER001'),    -- Pricing correction - July 2025

    -- UNSOS (Somalia, PPA, contract 39)
    (146, 'ENER002'),    -- Logistics (EMetered)
    (147, 'ENER002'),    -- Powerhouse 7 (EMetered)
    (144, 'ENER002'),    -- Powerhouse 17 (EMetered)
    (145, 'ENER002'),    -- Powerhouse 20 (EMetered)

    -- UTK01 (Kenya, PPA, contract 30)
    (149, 'KEREVS001'),  -- Metered Energy (EMetered)
    (148, 'KEREVS002'),  -- Available Energy (EAvailable)

    -- XFAB (Kenya, PPA, contract 31)
    (151, 'KEREVS001'),  -- Metered Energy (EMetered)
    (150, 'KEREVS002'),  -- Available Energy (EAvailable)

    -- XFBV (Kenya, PPA, contract 93)
    (153, 'KEREVS001'),  -- Metered Energy (EMetered)
    (152, 'KEREVS002'),  -- Available Energy (EAvailable)

    -- XFL01 (Kenya, PPA, contract 94)
    (154, 'KEREVS001'),  -- Metered Energy (EMetered)
    (155, 'KEREVS002'),  -- Available Energy (EAvailable)

    -- XFSS (Kenya, PPA, contract 95)
    (157, 'KEREVS001'),  -- Metered Energy (EMetered)
    (156, 'KEREVS002'),  -- Available Energy (EAvailable)

    -- ZL02 (Sierra Leone, contracts 96-99)
    (161, 'MOREVS001'),  -- ESA Lease Fee December (contract 96)
    (158, 'MOREVS002'),  -- O&M Service Fee - December (contract 97)
    (160, 'MOREVS002'),  -- O&M Service Fee - Hybrid (inactive, contract 97)
    (159, 'MOREVS002'),  -- O&M Service Fee incl penalties (inactive, contract 97)
    (162, 'ENER001'),    -- Site Readiness Delay Penalties (inactive, contract 98)
    (164, 'ENER001'),    -- Diesel Allocation - December 2025 (contract 99)
    (166, 'ENER001'),    -- Diesel Handling fee - December 2025 (contract 99)
    (163, 'ENER001'),    -- Diesel Allocation - May 2025 (inactive, contract 99)
    (165, 'ENER001')     -- Diesel Admin Fee - December 2025 (contract 99)
)
UPDATE contract_line cl
SET billing_product_id = bp.id,
    updated_at = NOW()
FROM bp_mapping m
JOIN billing_product bp ON bp.code = m.bp_code AND bp.organization_id IS NULL
WHERE cl.id = m.cl_id
  AND cl.billing_product_id IS NULL;


-- =============================================================================
-- SECTION C: Insert contract_billing_product junction
-- =============================================================================
-- Derives distinct billing products per contract from the contract_line links.
-- Sets is_primary = true for the first metered energy product per contract.
-- Skips contracts that already have entries (pilot: MOH01, KAS01, LOI01, NBL01).

-- Step 1: Insert all distinct (contract_id, billing_product_id) pairs
INSERT INTO contract_billing_product (contract_id, billing_product_id, is_primary, notes)
SELECT DISTINCT
  cl.contract_id,
  cl.billing_product_id,
  false,  -- will set primary below
  'Step 4 auto-derived from contract_line'
FROM contract_line cl
WHERE cl.billing_product_id IS NOT NULL
ON CONFLICT (contract_id, billing_product_id) DO NOTHING;

-- Step 2: Set is_primary for the first metered energy billing product per contract.
-- For energy contracts: primary = metered energy product
-- For non-energy contracts: primary = first product by contract_line_number
-- Only set where no primary exists yet for the contract.
WITH primary_candidates AS (
  SELECT DISTINCT ON (cbp.contract_id)
    cbp.id as cbp_id
  FROM contract_billing_product cbp
  JOIN contract_line cl ON cl.contract_id = cbp.contract_id
                        AND cl.billing_product_id = cbp.billing_product_id
  WHERE NOT EXISTS (
    -- Skip contracts that already have a primary
    SELECT 1 FROM contract_billing_product ex
    WHERE ex.contract_id = cbp.contract_id AND ex.is_primary = true
  )
  ORDER BY cbp.contract_id,
    -- Prefer active lines, then metered energy category
    CASE WHEN cl.is_active THEN 0 ELSE 1 END,
    CASE cl.energy_category WHEN 'metered' THEN 0 WHEN 'available' THEN 1 ELSE 2 END,
    cl.contract_line_number
)
UPDATE contract_billing_product cbp
SET is_primary = true
FROM primary_candidates pc
WHERE cbp.id = pc.cbp_id;


-- =============================================================================
-- SECTION D: Insert clause_tariff placeholders
-- =============================================================================
-- One clause_tariff per primary contract (parent_contract_id IS NULL).
-- Skips contracts that already have clause_tariff entries (KAS01, LOI01, MOH01, NBL01).
-- base_rate = NULL per workflow (populated in Step 7/9).
-- energy_sale_type, escalation_type, currency from PO Summary tab of Revenue Masterfile.
--
-- Tariff structure derivation (PO Summary cols E+F):
--   "PPA" + "Grid"      → FLOATING_GRID      (energy_sale_type_id = 6)
--   "PPA" + "Generator"  → FLOATING_GENERATOR  (energy_sale_type_id = 7)
--   "PPA" + "Grid+Gen"   → FLOATING_GRID_GEN   (energy_sale_type_id = 8)
--   "PPA" + "Off-Grid"   → FIXED_SOLAR          (energy_sale_type_id = 5)
--   "Finance Lease"       → NOT_ENERGY_SALES     (energy_sale_type_id = 9)
--   Non-energy contracts  → NOT_ENERGY_SALES     (energy_sale_type_id = 9)

INSERT INTO clause_tariff (
  project_id, contract_id, tariff_type_id, currency_id, name,
  energy_sale_type_id, escalation_type_id, is_current, unit,
  logic_parameters, source_metadata
)
SELECT
  v.project_id, v.contract_id, v.tariff_type_id, v.currency_id, v.name,
  v.energy_sale_type_id, v.escalation_type_id, true, v.unit,
  v.logic_parameters::jsonb, v.source_metadata::jsonb
FROM (VALUES
  -- -----------------------------------------------------------------------
  -- ENERGY SALES CONTRACTS (tariff_type = ENERGY_SALES = 8)
  -- -----------------------------------------------------------------------

  -- GBL01 (Ghana, PPA, Grid tariff)
  (52::bigint, 18::bigint, 8, 5, 'GH-GBL01 Main Tariff',
   6, NULL::integer, 'GHS/kWh',
   '{}', '{"source": "PO Summary", "step": 4}'),

  -- GC001 (Kenya, Finance Lease / Loan structure, fixed rate)
  (48, 16, 10, 1, 'KE-GC001 Main Tariff',
   5, 9, 'USD/kWh',
   '{}', '{"source": "PO Summary", "revenue_type": "Loan - Energy Output", "step": 4}'),

  -- IVL01 PPA (Egypt, fixed tariff)
  (51, 17, 8, 1, 'EG-IVL01 Main Tariff',
   5, NULL, 'USD/kWh',
   '{}', '{"source": "PO Summary", "step": 4}'),

  -- IVL01 OM (Egypt, auto-created, non-energy)
  (51, 100, 13, 1, 'EG-IVL01 OM Tariff',
   9, 11, 'USD',
   '{}', '{"source": "Step 3 auto-created contract", "step": 4}'),

  -- JAB01 (Nigeria, Grid + Generator tariff)
  (69, 35, 8, 6, 'NG-JAB01 Main Tariff',
   8, NULL, 'NGN/kWh',
   '{}', '{"source": "PO Summary", "step": 4}'),

  -- MB01 (Kenya, Fixed, Min Offtake)
  (57, 23, 8, 1, 'KE-MB01 Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.01}', '{"source": "PO Summary", "sale_type": "Min Offtake", "step": 4}'),

  -- MF01 (Kenya, Fixed, Min Offtake)
  (58, 24, 8, 1, 'KE-MF01 Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.01}', '{"source": "PO Summary", "sale_type": "Min Offtake", "step": 4}'),

  -- MP01 (Kenya, Fixed, Min Offtake — Devki Group)
  (60, 26, 8, 1, 'KE-MP01 Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.01}', '{"source": "PO Summary inferred (Devki Group)", "step": 4}'),

  -- MP02 (Kenya, Fixed, Min Offtake — Devki Group)
  (59, 25, 8, 1, 'KE-MP02 Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.01}', '{"source": "PO Summary inferred (Devki Group)", "step": 4}'),

  -- NC02 (Kenya, Fixed, Min Offtake — Devki Group)
  (61, 27, 8, 1, 'KE-NC02 Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.01}', '{"source": "PO Summary inferred (Devki Group)", "step": 4}'),

  -- NC03 (Kenya, Fixed, Min Offtake — Devki Group)
  (62, 28, 8, 1, 'KE-NC03 Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.01}', '{"source": "PO Summary inferred (Devki Group)", "step": 4}'),

  -- NBL02 (Nigeria, Generator tariff)
  (71, 37, 8, 6, 'NG-NBL02 Main Tariff',
   7, 8, 'NGN/kWh',
   '{"escalation_rate": 0.025}', '{"source": "PO Summary", "step": 4}'),

  -- QMM01 Main Tariff (Madagascar, Fixed)
  (67, 33, 8, 15, 'MG-QMM01 Main Tariff',
   5, 9, 'MGA/kWh',
   '{}', '{"source": "PO Summary", "step": 4}'),

  -- QMM01 BESS Capacity (Madagascar)
  (67, 33, 11, 15, 'MG-QMM01 BESS Capacity',
   9, 11, 'MGA/kWh',
   '{}', '{"source": "PO Summary", "step": 4}'),

  -- CAL01 (Zimbabwe, Fixed, US CPI)
  (76, 41, 8, 1, 'ZW-CAL01 Main Tariff',
   5, 9, 'USD/kWh',
   '{}', '{"source": "PO Summary", "step": 4}'),

  -- UGL01 (Ghana, Grid tariff, 2% escalation)
  (54, 20, 8, 5, 'GH-UGL01 Main Tariff',
   6, 8, 'GHS/kWh',
   '{"escalation_rate": 0.02}', '{"source": "PO Summary", "step": 4}'),

  -- UNSOS (Somalia, Fixed, 2.5% escalation)
  (74, 39, 8, 1, 'SO-UNSOS Main Tariff',
   5, 8, 'USD/kWh',
   '{"escalation_rate": 0.025}', '{"source": "PO Summary", "step": 4}'),

  -- TBM01 (Kenya, Fixed)
  (63, 29, 8, 7, 'KE-TBM01 Main Tariff',
   5, NULL, 'KES/kWh',
   '{}', '{"source": "PO Summary inferred", "step": 4}'),

  -- UTK01 (Kenya, Fixed)
  (64, 30, 8, 7, 'KE-UTK01 Main Tariff',
   5, NULL, 'KES/kWh',
   '{}', '{"source": "PO Summary inferred", "step": 4}'),

  -- XFAB (Kenya, Fixed, US CPI)
  (65, 31, 8, 7, 'KE-XFAB Main Tariff',
   5, 9, 'KES/kWh',
   '{}', '{"source": "PO Summary (XF*)", "step": 4}'),

  -- XFBV (Kenya, Fixed, US CPI)
  (113, 93, 8, 7, 'KE-XFBV Main Tariff',
   5, 9, 'KES/kWh',
   '{}', '{"source": "PO Summary (XF*)", "step": 4}'),

  -- XFL01 (Kenya, Fixed, US CPI)
  (114, 94, 8, 7, 'KE-XFL01 Main Tariff',
   5, 9, 'KES/kWh',
   '{}', '{"source": "PO Summary (XF*)", "step": 4}'),

  -- XFSS (Kenya, Fixed, US CPI)
  (115, 95, 8, 7, 'KE-XFSS Main Tariff',
   5, 9, 'KES/kWh',
   '{}', '{"source": "PO Summary (XF*)", "step": 4}'),

  -- MIR01 (Sierra Leone, Fixed)
  (72, 38, 8, 9, 'SL-MIR01 Main Tariff',
   5, NULL, 'SLE/kWh',
   '{}', '{"source": "PO Summary inferred", "step": 4}'),

  -- ERG (Madagascar, ESA, Fixed)
  (68, 34, 12, 15, 'MG-ERG Main Tariff',
   5, NULL, 'MGA/kWh',
   '{}', '{"source": "PO Summary inferred", "step": 4}'),

  -- AMP01 (Kenya, ESA)
  (66, 32, 12, 1, 'KE-AMP01 Main Tariff',
   5, NULL, 'USD/kWh',
   '{}', '{"source": "PO Summary inferred", "step": 4}'),

  -- -----------------------------------------------------------------------
  -- NON-ENERGY / SERVICE CONTRACTS
  -- -----------------------------------------------------------------------

  -- AR01 (Kenya, Lease)
  (55, 21, 9, 1, 'KE-AR01 Lease Tariff',
   9, 11, 'USD',
   '{}', '{"source": "contract_type=LEASE", "step": 4}'),

  -- TWG01 O&M (Mozambique, auto-created)
  (75, 101, 13, 11, 'MZ-TWG01 O&M Tariff',
   9, 11, 'MZN',
   '{}', '{"source": "Step 3 auto-created contract", "step": 4}'),

  -- TWG01 Lease (Mozambique)
  (75, 40, 9, 11, 'MZ-TWG01 Lease Tariff',
   9, 11, 'MZN',
   '{}', '{"source": "contract_type=LEASE", "step": 4}'),

  -- ZL01 ESA (Sierra Leone)
  (49, 56, 12, 1, 'SL-ZL01 ESA Tariff',
   9, NULL, 'USD',
   '{}', '{"source": "contract_type=ESA", "step": 4}'),

  -- ZL02 Lease (Sierra Leone, contract 96)
  (73, 96, 9, 1, 'SL-ZL02 Lease Tariff',
   9, 11, 'USD',
   '{}', '{"source": "ZL02 ESA Lease Fee", "step": 4}'),

  -- ZL02 O&M (Sierra Leone, contract 97)
  (73, 97, 13, 1, 'SL-ZL02 O&M Tariff',
   9, 11, 'USD',
   '{}', '{"source": "ZL02 O&M Service Fees", "step": 4}'),

  -- ZL02 Penalties (Sierra Leone, contract 98)
  (73, 98, 13, 1, 'SL-ZL02 Penalties',
   9, 11, 'USD',
   '{}', '{"source": "ZL02 Site Readiness Delay Penalties", "step": 4}'),

  -- ZL02 Diesel (Sierra Leone, contract 99)
  (73, 99, 13, 1, 'SL-ZL02 Diesel Tariff',
   9, 11, 'USD',
   '{}', '{"source": "ZL02 Diesel supply contract", "step": 4}'),

  -- -----------------------------------------------------------------------
  -- PLACEHOLDER CONTRACTS (no SAGE data, limited metadata)
  -- -----------------------------------------------------------------------

  -- ABI01 (Ghana, PPA — no SAGE contract, PDF-only)
  (77, 42, 8, 5, 'GH-ABI01 Main Tariff',
   NULL, NULL, 'GHS/kWh',
   '{}', '{"source": "placeholder - no SAGE data", "step": 4}'),

  -- BNT01 (Rwanda, PPA — no SAGE contract, PDF-only)
  (78, 43, 8, 8, 'RW-BNT01 Main Tariff',
   NULL, NULL, 'RWF/kWh',
   '{}', '{"source": "placeholder - no SAGE data", "step": 4}')

) AS v(project_id, contract_id, tariff_type_id, currency_id, name,
       energy_sale_type_id, escalation_type_id, unit,
       logic_parameters, source_metadata)
WHERE NOT EXISTS (
  SELECT 1 FROM clause_tariff ct
  WHERE ct.contract_id = v.contract_id
    AND ct.name = v.name
);


-- =============================================================================
-- SECTION E: Verification Gates
-- =============================================================================

-- Gate 1: All contract_lines have billing_product_id
DO $$
DECLARE
  v_null_count integer;
BEGIN
  SELECT COUNT(*) INTO v_null_count
  FROM contract_line
  WHERE billing_product_id IS NULL;

  IF v_null_count > 0 THEN
    RAISE WARNING 'GATE 1 WARNING: % contract_lines still have NULL billing_product_id', v_null_count;
  ELSE
    RAISE NOTICE 'GATE 1 PASSED: All contract_lines have billing_product_id';
  END IF;
END $$;

-- Gate 2: Every contract with contract_lines has at least one contract_billing_product
DO $$
DECLARE
  v_missing integer;
BEGIN
  SELECT COUNT(DISTINCT cl.contract_id) INTO v_missing
  FROM contract_line cl
  WHERE NOT EXISTS (
    SELECT 1 FROM contract_billing_product cbp
    WHERE cbp.contract_id = cl.contract_id
  );

  IF v_missing > 0 THEN
    RAISE WARNING 'GATE 2 WARNING: % contracts with lines but no contract_billing_product', v_missing;
  ELSE
    RAISE NOTICE 'GATE 2 PASSED: All contracts with lines have contract_billing_product entries';
  END IF;
END $$;

-- Gate 3: Every contract with contract_lines has exactly one primary billing product
DO $$
DECLARE
  v_no_primary integer;
  v_multi_primary integer;
BEGIN
  SELECT COUNT(*) INTO v_no_primary
  FROM (
    SELECT cl.contract_id
    FROM contract_line cl
    GROUP BY cl.contract_id
    HAVING NOT EXISTS (
      SELECT 1 FROM contract_billing_product cbp
      WHERE cbp.contract_id = cl.contract_id AND cbp.is_primary = true
    )
  ) t;

  SELECT COUNT(*) INTO v_multi_primary
  FROM (
    SELECT contract_id FROM contract_billing_product
    WHERE is_primary = true
    GROUP BY contract_id HAVING COUNT(*) > 1
  ) t;

  IF v_no_primary > 0 THEN
    RAISE WARNING 'GATE 3 WARNING: % contracts have no primary billing product', v_no_primary;
  ELSIF v_multi_primary > 0 THEN
    RAISE WARNING 'GATE 3 WARNING: % contracts have multiple primary billing products', v_multi_primary;
  ELSE
    RAISE NOTICE 'GATE 3 PASSED: Every contract has exactly one primary billing product';
  END IF;
END $$;

-- Gate 4: Every primary contract (no parent) has a clause_tariff
DO $$
DECLARE
  v_missing integer;
  v_missing_list text;
BEGIN
  SELECT COUNT(*), string_agg(p.sage_id || ' (' || c.id || ')', ', ')
  INTO v_missing, v_missing_list
  FROM contract c
  JOIN project p ON p.id = c.project_id
  WHERE c.parent_contract_id IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM clause_tariff ct WHERE ct.contract_id = c.id
    )
    -- Exclude TBC (iSAT) and ZL01 ancillary — no contract lines
    AND p.sage_id NOT IN ('TBC');

  IF v_missing > 0 THEN
    RAISE WARNING 'GATE 4 WARNING: % primary contracts missing clause_tariff: %', v_missing, v_missing_list;
  ELSE
    RAISE NOTICE 'GATE 4 PASSED: All primary contracts have clause_tariff entries';
  END IF;
END $$;

-- Gate 5: No NULL contract_type_id on contracts with contract_lines
DO $$
DECLARE
  v_null_type integer;
BEGIN
  SELECT COUNT(DISTINCT c.id) INTO v_null_type
  FROM contract c
  JOIN contract_line cl ON cl.contract_id = c.id
  WHERE c.contract_type_id IS NULL;

  IF v_null_type > 0 THEN
    RAISE WARNING 'GATE 5 WARNING: % contracts with lines have NULL contract_type_id', v_null_type;
  ELSE
    RAISE NOTICE 'GATE 5 PASSED: All contracts with lines have contract_type_id set';
  END IF;
END $$;

COMMIT;
