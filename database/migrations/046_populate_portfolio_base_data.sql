-- =============================================================================
-- 046_populate_portfolio_base_data.sql
-- =============================================================================
-- Populates the FrontierMind database with CBE's full customer contract
-- portfolio: 33 projects, ~28 primary contracts, ~12 ancillary documents,
-- and ~18 amendments.
--
-- Source data:
--   - CBE_data_extracts/Customer summary.xlsx (33 deduplicated projects)
--   - CBE_data_extracts/Customer Offtake Agreements/ (62 contract PDFs)
--
-- Preserves:
--   - MOH01 (project id=8, contract id=7, amendment id=1)
--
-- Deletes:
--   - Solar Farm (placeholder, 1 orphan meter)
--   - Travis County (placeholder, no child data)
--
-- Execution: Single transaction (BEGIN/COMMIT), FK-ordered steps.
-- =============================================================================

BEGIN;

-- =============================================================================
-- STEP 1: SCHEMA PREPARATION
-- =============================================================================

-- 1A. Add parent_contract_id to contract (ancillary document hierarchy)
ALTER TABLE contract ADD COLUMN IF NOT EXISTS parent_contract_id BIGINT REFERENCES contract(id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_contract_no_self_parent'
  ) THEN
    ALTER TABLE contract ADD CONSTRAINT chk_contract_no_self_parent
      CHECK (parent_contract_id <> id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_contract_parent
  ON contract(parent_contract_id) WHERE parent_contract_id IS NOT NULL;

-- Trigger: parent contract must belong to same project
CREATE OR REPLACE FUNCTION contract_same_project_parent()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.parent_contract_id IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1 FROM contract
      WHERE id = NEW.parent_contract_id
        AND project_id = NEW.project_id
    ) THEN
      RAISE EXCEPTION 'parent_contract_id (%) belongs to a different project than contract project_id (%)',
        NEW.parent_contract_id, NEW.project_id;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_contract_same_project_parent ON contract;
CREATE TRIGGER trg_contract_same_project_parent
  BEFORE INSERT OR UPDATE ON contract
  FOR EACH ROW
  EXECUTE FUNCTION contract_same_project_parent();


-- 1B. Make amendment_date nullable (some amendments have unknown signing dates)
ALTER TABLE contract_amendment ALTER COLUMN amendment_date DROP NOT NULL;


-- 1C. Add missing currencies (idempotent)
INSERT INTO currency (code, name) VALUES
  ('MGA', 'Malagasy Ariary'),
  ('SOS', 'Somali Shilling'),
  ('ZWL', 'Zimbabwean Dollar')
ON CONFLICT (code) DO NOTHING;


-- 1D. Add legal entities (8 new, ON CONFLICT skip)
INSERT INTO legal_entity (organization_id, external_legal_entity_id, name, country, is_active)
VALUES
  (1, 'KEN0', 'CrossBoundary Energy Kenya Limited',          'Kenya',        true),
  (1, 'MAD0', 'CrossBoundary Energy Madagascar',             'Madagascar',   true),
  (1, 'MAD2', 'CrossBoundary Energy Madagascar II SA',       'Madagascar',   true),
  (1, 'NIG0', 'CrossBoundary Energy Nigeria Ltd',            'Nigeria',      true),
  (1, 'SL02', 'CrossBoundary Energy (SL) Limited',           'Sierra Leone', true),
  (1, 'SOM0', 'KUBE Energy Somalia LLC',                     'Somalia',      true),
  (1, 'MOZ0', 'Balama Renewables, Limitada',                 'Mozambique',   true),
  (1, 'ZIM0', 'CrossBoundary Energy Zimbabwe Limited',       'Zimbabwe',     true)
ON CONFLICT (organization_id, external_legal_entity_id) DO NOTHING;


-- =============================================================================
-- STEP 2: DELETE PLACEHOLDER PROJECTS
-- =============================================================================

-- Solar Farm (project org=1, name='Solar Farm') — 1 orphan meter, 0 contracts
DELETE FROM meter WHERE project_id IN (
  SELECT id FROM project WHERE name = 'Solar Farm' AND organization_id = 1
);
DELETE FROM project WHERE name = 'Solar Farm' AND organization_id = 1;

-- Travis County (project org=2, name='Travis County') — 0 everything
DELETE FROM project WHERE name = 'Travis County' AND organization_id = 2;

-- Assertion: placeholders gone, MOH01 intact
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM project WHERE name IN ('Solar Farm', 'Travis County')) THEN
    RAISE EXCEPTION 'Placeholder projects not deleted';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM project WHERE id = 8 AND sage_id = 'MOH01') THEN
    RAISE EXCEPTION 'MOH01 project missing after placeholder cleanup';
  END IF;
END $$;


-- =============================================================================
-- STEP 3: COUNTERPARTIES & PROJECTS (via staging table)
-- =============================================================================

-- 3A. Seed counterparties (~22 new)
-- Uses ON CONFLICT on unique index uq_counterparty_type_name(counterparty_type_id, LOWER(name))

INSERT INTO counterparty (counterparty_type_id, name, industry, country)
VALUES
  -- GC01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'GC Retail',                         'Real Estate',       'Mauritius'),
  -- ZL01 / ZL02
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Zoodlabs Group',                    'Telecom',           'Mauritius'),
  -- TBC
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'iSAT Africa',                       'Telecom',           'Mauritius'),
  -- IVL01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Indorama Ventures',                 'Oil, Petrochemical','Egypt'),
  -- GBL01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Diageo',                            'Food & Drink',      'Ghana'),
  -- KAS01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Kasapreko Company',                 'Food & Drink',      'Ghana'),
  -- UGL01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Unilever',                          'Consumer Products', 'Ghana'),
  -- AR01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Arijiju Retreat',                   'Hospitality',       'Kenya'),
  -- LOI01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Oryx Ltd',                          'Hospitality',       'Kenya'),
  -- MB01, MF01, MP01, MP02, NC02, NC03
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Devki Group',                       'Manufacturing',     'Kenya'),
  -- TBM01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Brush Manufacturers',               'Manufacturing',     'Kenya'),
  -- UTK01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Lipton',                            'Food & Drink',      'Kenya'),
  -- XF-AB
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'XFlora Group',                      'Agriculture',       'Kenya'),
  -- AMP01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Ampersand',                         'Transport',         'Kenya'),
  -- QMM01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Rio Tinto',                         'Mining',            'Madagascar'),
  -- ERG
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Next Source Materials',              'Mining',            'Madagascar'),
  -- JAB01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Jabi Mall Development Co',          'Real Estate',       'Nigeria'),
  -- NBL01, NBL02
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Heineken',                          'Food & Drink',      'Nigeria'),
  -- MIR01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Miro Forestry and Timber Products', 'Forestry',          'Sierra Leone'),
  -- UNSOS
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'UNSOS',                             'NGO',               'Somalia'),
  -- TWG01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Twigg Exploration and Mining',      'Mining',            'Mozambique'),
  -- CAL01
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Blanket Mine',                      'Mining',            'Zimbabwe'),
  -- ABI01 (from PDFs only)
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Accra Breweries',                   'Food & Drink',      'Ghana'),
  -- BNT01 (from PDFs only)
  ((SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'), 'Izuba BNT',                         'Energy',            'Rwanda')
ON CONFLICT (counterparty_type_id, LOWER(name))
DO UPDATE SET
  industry = COALESCE(EXCLUDED.industry, counterparty.industry),
  country  = COALESCE(EXCLUDED.country,  counterparty.country);


-- 3B. Seed projects via staging temp table
CREATE TEMP TABLE stg_portfolio (
  sage_id                   VARCHAR(50) NOT NULL,
  external_project_id       VARCHAR(50),
  project_name              VARCHAR(255) NOT NULL,
  country                   VARCHAR(100),
  legal_entity_code         VARCHAR(10) NOT NULL,
  counterparty_name         VARCHAR(255),
  cod_date                  DATE,
  installed_dc_capacity_kwp DECIMAL,
  contract_term_years       INTEGER,
  contract_type_code        VARCHAR(50),
  agreement_name            VARCHAR(500),
  billing_currency_code     VARCHAR(10)
);

INSERT INTO stg_portfolio VALUES
  -- CBCH entity
  ('GC01',  'KE 22006',              'Garden City Mall',                          'Kenya',        'CBCH', 'GC Retail',                         '2016-06-01', 858.33,   12, 'LEASE',  'Garden City SolarAfrica Project Agreement',               'USD'),
  ('ZO01',  'SL 22030',              'Zoodlabs Group',                            'Sierra Leone', 'CBCH', 'Zoodlabs Group',                    '2024-04-01', NULL,     15, 'ESA',    'Zoodlabs ESA and O&M',                                   'USD'),
  ('TBC',   'DRC 23521',             'iSAT Africa',                               'DRC',          'CBCH', 'iSAT Africa',                       '2025-08-29', NULL,     NULL, 'LEASE', NULL,                                                     'USD'),
  -- EGY0 entity
  ('IVL01', 'EG 22008',              'Indorama Ventures - Expanded',              'Egypt',        'EGY0', 'Indorama Ventures',                 '2023-10-02', 3237.68,  26, 'PPA',    'IVL Dhunseri SSA',                                        'USD'),
  -- GHA0 entity
  ('GBL01', 'GH 22005',              'Guinness Ghana Breweries',                  'Ghana',        'GHA0', 'Diageo',                            '2021-03-19', 1095.12,  15, 'PPA',    'Guinness Ghana Breweries SSA',                            'GHS'),
  ('KAS01', 'GH 22010',              'Kasapreko - Phase I and II',                'Ghana',        'GHA0', 'Kasapreko Company',                 '2024-05-03', 1305.24,  18, 'PPA',    'Kasapreko SSA',                                           'GHS'),
  ('UGL01', 'GH 22022',              'Unilever Ghana',                            'Ghana',        'GHA0', 'Unilever',                          '2021-01-05', 970.2,    15, 'PPA',    'Unilever Ghana SSA',                                      'GHS'),
  -- MOH01 excluded — already onboarded (project id=8)
  -- KEN0 entity
  ('AR01',  'KE 22469',              'Arijiju Retreat',                           'Kenya',        'KEN0', 'Arijiju Retreat',                   '2023-10-24', 205,      12, 'LEASE',  'Arijiju Solar Equipment Lease Agreement',                 'USD'),
  ('LOI01', 'KE 22013',              'Loisaba',                                   'Kenya',        'KEN0', 'Oryx Ltd',                          '2019-03-01', 74.4,     10, 'PPA',    'Loisaba SSA',                                             'USD'),
  ('MB01',  'KE 22434',              'Maisha Mabati Mills LuKenya',               'Kenya',        'KEN0', 'Devki Group',                       '2025-01-01', 1172.52,  20, 'PPA',    'Maisha Mabati Mills SSA',                                 'USD'),
  ('MF01',  'KE 22435',              'Maisha Minerals & Fertilizer Athi River',   'Kenya',        'KEN0', 'Devki Group',                       '2023-10-24', 674,      20, 'PPA',    'Maisha Minerals and Fertilizers SSA',                     'USD'),
  ('MP02',  'KE 22436',              'Maisha Packaging LuKenya',                  'Kenya',        'KEN0', 'Devki Group',                       '2024-03-28', 1386,     20, 'PPA',    'Maisha Packaging Lukenya SSA',                            'USD'),
  ('MP01',  'KE 22471',              'Maisha Packaging Nakuru',                   'Kenya',        'KEN0', 'Devki Group',                       '2024-04-05', 680.8,    20, 'PPA',    'Maisha Packaging Nakuru SSA',                             'USD'),
  ('NC02',  'KE 22432',              'National Cement Athi River',                'Kenya',        'KEN0', 'Devki Group',                       '2023-10-24', 493.42,   20, 'PPA',    'National Cement Athi River SSA',                          'USD'),
  ('NC03',  'KE 22433',              'National Cement Nakuru',                    'Kenya',        'KEN0', 'Devki Group',                       '2024-04-08', 2236.92,  20, 'PPA',    'National Cement Nakuru SSA',                               'USD'),
  ('TBM01', 'KE 22021',              'TeePee Brushes',                            'Kenya',        'KEN0', 'Brush Manufacturers',               '2023-02-08', 1508,     20, 'PPA',    'TeePee Brushes SSA',                                      'KES'),
  ('UTK01', 'KE 22023',              'eKaterra Tea Kenya',                        'Kenya',        'KEN0', 'Lipton',                            '2019-05-27', 618.8,    15, 'PPA',    'Unilever Tea Kenya SSA',                                  'KES'),
  ('XF-AB', 'KE 22025',              'XFlora Group',                              'Kenya',        'KEN0', 'XFlora Group',                      '2021-02-01', 424.32,   20, 'PPA',    'XFlora Group SSA',                                        'KES'),
  ('AMP01', 'KE 23622',              'Ampersand',                                 'Kenya',        'KEN0', 'Ampersand',                         NULL,         36.9,     7,  'ESA',    'Ampersand ESA + Battery Lease',                           'USD'),
  -- MAD0 entity
  ('QMM01', 'MG 22017',              'Rio Tinto QMM',                             'Madagascar',   'MAD0', 'Rio Tinto',                         '2025-02-01', 14447.76, 20, 'PPA',    'QMM RESA',                                                'MGA'),
  -- MAD2 entity
  ('ERG',   'MG 22028',              'Molo Graphite',                             'Madagascar',   'MAD2', 'Next Source Materials',              '2023-11-16', 2696,     20, 'ESA',    'Molo ESA',                                                'MGA'),
  -- NIG0 entity
  ('JAB01', 'NG 22009',              'Jabi Lake Mall',                            'Nigeria',      'NIG0', 'Jabi Mall Development Co',          '2020-06-30', 609.84,   15, 'PPA',    'Jabi Lake Mall PPA',                                      'NGN'),
  ('NBL01', 'NG 22016',              'Nigerian Breweries - Ibadan Expanded',      'Nigeria',      'NIG0', 'Heineken',                          '2025-01-01', 3173,     15, 'PPA',    'Nigerian Breweries Ibadan SSA',                           'NGN'),
  ('NBL02', 'NG 22031',              'Nigerian Breweries - Ama',                  'Nigeria',      'NIG0', 'Heineken',                          '2023-02-27', 4006,     15, 'PPA',    'Nigerian Breweries Ama SSA',                              'NGN'),
  -- SL02 entity
  ('MIR01', 'SL 22014',              'Miro Forestry',                             'Sierra Leone', 'SL02', 'Miro Forestry and Timber Products', '2023-10-01', 235.52,   7,  'PPA',    'Miro Forestry SSA + Annexures',                           'SLE'),
  ('ZL02',  'SL 24702',              'Zoodlabs Energy Services',                  'Sierra Leone', 'SL02', 'Zoodlabs Group',                    '2025-03-01', NULL,     10, 'LEASE',  NULL,                                                      'USD'),
  -- SOM0 entity
  ('UNSOS', 'SO 22024',              'UNSOS Baidoa',                              'Somalia',      'SOM0', 'UNSOS',                             '2024-03-17', 2732.4,   10, 'PPA',    'UNSOS Baidoa SSA',                                        'USD'),
  -- MOZ0 entity
  ('TWG01', 'MZ 22003',              'Balama Graphite',                           'Mozambique',   'MOZ0', 'Twigg Exploration and Mining',      '2025-12-01', 11249,    10, 'LEASE',  'Balama Solar-BESS Hybrid BOOT Operating Lease',           'MZN'),
  -- ZIM0 entity
  ('CAL01', 'ZW 23541',              'Caledonia',                                 'Zimbabwe',     'ZIM0', 'Blanket Mine',                      '2025-04-15', 13895,    17, 'PPA',    'Amended and Restated PPA - Blanket Mine',                 'USD'),
  -- PDF-only projects (not in Excel)
  ('ABI01', NULL,                    'Accra Breweries Ghana',                     'Ghana',        'GHA0', 'Accra Breweries',                   NULL,         NULL,     NULL, 'PPA',  'Accra Breweries Ghana PPA',                               NULL),
  ('BNT01', NULL,                    'Izuba BNT',                                 'Rwanda',       'KEN0', 'Izuba BNT',                         NULL,         NULL,     NULL, 'PPA',  'Izuba BNT EUCL Wheeling Agreement',                       NULL);


-- 3C. Upsert projects from staging (skip MOH01)
INSERT INTO project (
  organization_id, external_project_id, sage_id, name, country,
  cod_date, installed_dc_capacity_kwp, legal_entity_id
)
SELECT
  1,
  s.external_project_id,
  s.sage_id,
  s.project_name,
  s.country,
  s.cod_date,
  s.installed_dc_capacity_kwp,
  le.id
FROM stg_portfolio s
JOIN legal_entity le ON le.external_legal_entity_id = s.legal_entity_code AND le.organization_id = 1
WHERE s.sage_id != 'MOH01'  -- MOH01 already onboarded
ON CONFLICT (organization_id, external_project_id)
  WHERE external_project_id IS NOT NULL
  DO UPDATE SET
    sage_id                   = EXCLUDED.sage_id,
    name                      = EXCLUDED.name,
    country                   = EXCLUDED.country,
    cod_date                  = COALESCE(EXCLUDED.cod_date, project.cod_date),
    installed_dc_capacity_kwp = COALESCE(EXCLUDED.installed_dc_capacity_kwp, project.installed_dc_capacity_kwp),
    legal_entity_id           = EXCLUDED.legal_entity_id;

-- For projects without external_project_id (ABI01, BNT01), insert by sage_id check
INSERT INTO project (organization_id, sage_id, name, country, legal_entity_id)
SELECT
  1, s.sage_id, s.project_name, s.country, le.id
FROM stg_portfolio s
JOIN legal_entity le ON le.external_legal_entity_id = s.legal_entity_code AND le.organization_id = 1
WHERE s.external_project_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM project p WHERE p.sage_id = s.sage_id AND p.organization_id = 1);


-- =============================================================================
-- STEP 4: PRIMARY CONTRACTS (~26, one per project)
-- =============================================================================
-- Projects with no contract PDFs (TBC, ZL02) get project + counterparty only, no contract row.
-- ZO01 has 2 PDFs: ESA+O&M (primary) and Solar Loan Agreement (ancillary in Step 5).
-- MOH01 already has contract id=7.

INSERT INTO contract (
  project_id, organization_id, counterparty_id, contract_type_id,
  contract_status_id, name, contract_term_years, effective_date,
  parent_contract_id, extraction_metadata
)
SELECT
  p.id,
  1,
  cp.id,
  ct.id,
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  s.agreement_name,
  s.contract_term_years,
  s.cod_date,  -- use COD as proxy for effective_date where we don't have exact signing date
  NULL,        -- primary contract has no parent
  jsonb_build_object(
    'source', 'migration_046',
    'billing_currency', s.billing_currency_code
  )
FROM stg_portfolio s
JOIN project p ON p.sage_id = s.sage_id AND p.organization_id = 1
JOIN counterparty cp ON LOWER(cp.name) = LOWER(s.counterparty_name)
  AND cp.counterparty_type_id = (SELECT id FROM counterparty_type WHERE code = 'OFFTAKER')
JOIN contract_type ct ON ct.code = s.contract_type_code
WHERE s.sage_id != 'MOH01'          -- already has contract id=7
  AND s.agreement_name IS NOT NULL   -- skip TBC, ZL02 (no contract docs)
  AND NOT EXISTS (                   -- idempotency: skip if contract already exists for project
    SELECT 1 FROM contract c WHERE c.project_id = p.id AND c.parent_contract_id IS NULL
  );


-- =============================================================================
-- STEP 5: ANCILLARY CONTRACTS (~11, child docs with parent_contract_id)
-- =============================================================================

-- Helper: get the primary contract for a project by sage_id
-- We'll insert ancillary docs referencing the primary contract

-- GC01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  ancillary.doc_name,
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', ancillary.doc_type)
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
CROSS JOIN (VALUES
  ('Garden City SolarAfrica-CBE Project Agreement Assignment', 'assignment_agreement'),
  ('Garden City Transaction Documents', 'transaction_documents')
) AS ancillary(doc_name, doc_type)
WHERE p.sage_id = 'GC01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = ancillary.doc_name
  );

-- LOI01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  ancillary.doc_name,
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', ancillary.doc_type)
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
CROSS JOIN (VALUES
  ('Loisaba SSA Revised Annexures',                'revised_annexures'),
  ('Loisaba SolarAfrica COD Acceptance Certificate','cod_certificate'),
  ('Loisaba Transfer Acceptance Certificates',      'transfer_certificate')
) AS ancillary(doc_name, doc_type)
WHERE p.sage_id = 'LOI01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = ancillary.doc_name
  );

-- QMM01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  'QMM Permission Agreement',
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', 'permission_agreement')
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
WHERE p.sage_id = 'QMM01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = 'QMM Permission Agreement'
  );

-- UGL01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  ancillary.doc_name,
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', ancillary.doc_type)
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
CROSS JOIN (VALUES
  ('Unilever Ghana SSA Schedules', 'ssa_schedules'),
  ('Unilever Ghana COD Notice',    'cod_notice')
) AS ancillary(doc_name, doc_type)
WHERE p.sage_id = 'UGL01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = ancillary.doc_name
  );

-- UTK01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  'Unilever Tea Kenya SSA Schedules',
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', 'ssa_schedules')
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
WHERE p.sage_id = 'UTK01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = 'Unilever Tea Kenya SSA Schedules'
  );

-- XF-AB ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  ancillary.doc_name,
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', ancillary.doc_type)
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
CROSS JOIN (VALUES
  ('XFlora SSA 1st Amendment COD Extension', 'cod_extension'),
  ('XFlora SSA Adherence Agreement',         'adherence_agreement')
) AS ancillary(doc_name, doc_type)
WHERE p.sage_id = 'XF-AB' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = ancillary.doc_name
  );

-- ZO01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  'Zoodlabs Solar Loan Agreement',
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', 'loan_agreement')
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
WHERE p.sage_id = 'ZO01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = 'Zoodlabs Solar Loan Agreement'
  );

-- CAL01 ancillary docs
INSERT INTO contract (project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, name, parent_contract_id, extraction_metadata)
SELECT
  p.id, 1, c.counterparty_id,
  (SELECT id FROM contract_type WHERE code = 'OTHER'),
  (SELECT id FROM contract_status WHERE code = 'ACTIVE'),
  'CMS Sale of Shares and Sale Claims Agreement',
  c.id,
  jsonb_build_object('source', 'migration_046', 'document_type', 'share_sale_agreement')
FROM project p
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
WHERE p.sage_id = 'CAL01' AND p.organization_id = 1
  AND NOT EXISTS (
    SELECT 1 FROM contract x WHERE x.project_id = p.id AND x.name = 'CMS Sale of Shares and Sale Claims Agreement'
  );


-- =============================================================================
-- STEP 6: AMENDMENTS (~18)
-- =============================================================================
-- MOH01 amendment id=1 already exists — skip.
-- Uses ON CONFLICT (contract_id, amendment_number) DO NOTHING for idempotency.

-- Helper: create staging table for amendments
CREATE TEMP TABLE stg_amendments (
  project_sage_id    VARCHAR(50) NOT NULL,
  amendment_number   INTEGER NOT NULL,
  amendment_date     DATE,          -- NULL where unknown
  description        TEXT,
  file_hint          TEXT,          -- for source_metadata
  effective_date     DATE
);

INSERT INTO stg_amendments VALUES
  -- GBL01: 2 amendments
  ('GBL01', 1, '2019-12-19', '1st Amendment to Guinness Ghana Breweries SSA',            'GBL01_SSA_1st_Amendment_Stamped_20191219.pdf',    NULL),
  ('GBL01', 2, '2020-12-17', '2nd Amendment to Guinness Ghana Breweries SSA',            'GBL01_SSA_2nd_Amendment_Stamped_20201217.pdf',    NULL),
  -- IVL01: 1 amendment
  ('IVL01', 1, '2022-08-18', 'Amendment & Restatement of IVL Dhunseri SSA',              'IVL01_SSA_Amendment_Restatement_20220818.pdf',    NULL),
  -- KAS01: 4 amendments (earliest = Solar Africa amendment; original SSA not available)
  ('KAS01', 1, '2017-05-31', 'Kasapreko SSA Amendment (Solar Africa)',                   'KAS01_SSA_Amendment_Stamped_20170531.pdf',        NULL),
  ('KAS01', 2, '2019-04-26', '1st Amendment Solar Phase II',                             'KAS01_SSA_1st_Amendment_20190426.pdf',            NULL),
  ('KAS01', 3, '2020-07-06', '2nd Amendment - Reinforcement Works',                      'KAS01_SSA_2nd_Amendment_20200706.pdf',            NULL),
  ('KAS01', 4, '2021-03-01', '3rd Amendment - Interconnection Works',                    'KAS01_SSA_3rd_Amendment_20210301.pdf',            NULL),
  -- LOI01: 1 amendment
  ('LOI01', 1, '2018-10-16', '1st Amendment to Loisaba SSA',                             'LOI01_SSA_1st_Amendment_20181016.pdf',            NULL),
  -- MIR01: 1 amendment
  ('MIR01', 1, '2021-11-11', '1st Amendment to Miro Forestry SSA',                       'MIR01_SSA_1st_Amendment_20211111.pdf',            NULL),
  -- NBL01: 3 amendments
  ('NBL01', 1, '2019-02-01', '1st Amendment to Nigerian Breweries Ibadan SSA',           'NBL01_SSA_1st_Amendment_201902.pdf',              NULL),
  ('NBL01', 2, '2021-05-07', '2nd Amendment to Nigerian Breweries Ibadan SSA',           'NBL01_SSA_2nd_Amendment_20210507.pdf',            NULL),
  ('NBL01', 3, '2022-10-22', '3rd Amendment to Nigerian Breweries Ibadan SSA',           'NBL01_SSA_3rd_Amendment_20221022.pdf',            NULL),
  -- NBL02: 1 amendment (date anomaly: amendment dated before SSA; numbered as 2nd per source doc)
  ('NBL02', 2, '2021-05-01', '2nd Amendment to Nigerian Breweries Ama SSA',              'NBL02_SSA_2nd_Amendment_20210501.pdf',            NULL),
  -- QMM01: 2 amendments (dates unknown for both)
  ('QMM01', 1, NULL,         '1st Amendment to QMM RESA',                                'QMM01_RESA_1st_Amendment.pdf',                    NULL),
  ('QMM01', 2, NULL,         '2nd Amendment to QMM RESA',                                'QMM01_RESA_2nd_Amendment.pdf',                    NULL),
  -- UNSOS: 2 amendments (original + 1st missing; numbered per source docs)
  ('UNSOS', 2, NULL,         '2nd Amendment to UNSOS Baidoa SSA',                        'UNSOS_Baidoa_SSA_2nd_Amendment.pdf',              NULL),
  ('UNSOS', 3, '2023-11-14', '3rd Amendment to UNSOS Baidoa SSA (Kube)',                 'UNSOS_Baidoa_Amendment_3_Kube_20231114.pdf',      NULL),
  -- XF-AB: 1 amendment
  ('XF-AB', 1, '2020-06-20', '1st Amendment to XFlora Group SSA',                        'XF-AB_SSA_1st_Amendment_20200620.pdf',            NULL);

-- Insert amendments (joining through project → primary contract)
INSERT INTO contract_amendment (
  contract_id, organization_id, amendment_number, amendment_date,
  effective_date, description, source_metadata
)
SELECT
  c.id,
  1,
  sa.amendment_number,
  sa.amendment_date,
  sa.effective_date,
  sa.description,
  jsonb_build_object('source', 'migration_046', 'file_hint', sa.file_hint)
FROM stg_amendments sa
JOIN project p ON p.sage_id = sa.project_sage_id AND p.organization_id = 1
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
ON CONFLICT (contract_id, amendment_number) DO NOTHING;

-- Mark contracts that have amendments
UPDATE contract SET has_amendments = true
WHERE id IN (
  SELECT DISTINCT contract_id FROM contract_amendment
) AND (has_amendments IS NULL OR has_amendments = false);


-- =============================================================================
-- STEP 7: POPULATE FILE PATHS
-- =============================================================================
-- Sets contract.file_location and contract_amendment.file_path to the
-- relative path within the repo's CBE_data_extracts directory.

-- 7A. Primary contracts — file_location
UPDATE contract SET file_location = paths.file_location
FROM (VALUES
  ('GC01',  'CBE - GC01_Garden City SolarAfrica Project Agreement Signed.pdf'),
  ('IVL01', 'CBE - IVL01_IVL Dhunseri SSA Signed_20211111.pdf'),
  ('GBL01', 'CBE - GBL01_Guiness Ghana Breweries SSA Stamped_20190109.pdf'),
  ('UGL01', 'CBE - UGL01_Unilever Ghana_SSA Stamped_20180924.pdf'),
  ('AR01',  'CBE - AR01_Arijuju Solar Equipment Lease Agreement Signed_20230620.pdf'),
  ('LOI01', 'CBE - LOI01_Loisaba SSA Signed_20151103.pdf'),
  ('MB01',  'CBE - MB01_Maisha Mabati Mills SSA Signed.pdf'),
  ('MF01',  'CBE - MF01_Maisha Minerals and Fertilizers SSA Signed.pdf'),
  ('MP02',  'CBE - MP02_Maisha Packaging Lukenya SSA Signed.pdf'),
  ('MP01',  'CBE - MP01_Maisha Packaging Nakuru SSA Signed.pdf'),
  ('NC02',  'CBE - NC02_National Cement Athi River SSA Signed.pdf'),
  ('NC03',  'CBE - NC03_National Cement Nakuru SSA Signed.pdf'),
  ('TBM01', 'CBE - TBM01_Teepee SSA Signed_20211129.pdf'),
  ('UTK01', 'CBE - UTK01_Unilever Tea Kenya SSA Signed_20180205.pdf'),
  ('XF-AB', 'CBE - XF-AB_BV_SS_LO1_ SSA Signed_20190701.pdf'),
  ('AMP01', 'CBE - AMP01_Ampersand ESA + Battery Lease - 22-8-2024 vF - signed.pdf'),
  ('QMM01', 'CBE - QMM01_QMM RESA Signed_20210611.pdf'),
  ('ERG',   'CBE - ERG _Molo ESA Signed_20220516.pdf'),
  ('JAB01', 'CBE - JAB01_Jabi Lake Mall PPA Signed_20190606.pdf'),
  ('NBL01', 'CBE - NBL01_Nigerian Breweries Ibadan SSA Stamped_20181211.pdf'),
  ('NBL02', 'CBE - NBL02_Nigerian Breweries Ama SSA Signed_20211210.pdf'),
  ('MIR01', 'CBE - MIR01_Miro Forestry SSA + Annexures_20201201.pdf'),
  ('TWG01', 'CBE - TWG01_Balama Solar-BESS Hybrid Project_BOOT Operating Lease_20220405.pdf'),
  ('CAL01', 'CBE - CAL01_Amended and Restated PPA - Blanket Mine vExecution - vExecuted.pdf'),
  ('ABI01', 'CBE - ABI01_Accra Breweries Ghana PPA Signed.pdf'),
  ('BNT01', 'CBE - BNT01_Izuba BNT EUCL WA_Executed 301224.pdf'),
  ('ZO01',  'CBE_ZO01_Zoodlabs ESA and O&M signed.pdf')
) AS paths(sage_id, file_location)
JOIN project p ON p.sage_id = paths.sage_id AND p.organization_id = 1
WHERE contract.project_id = p.id
  AND contract.parent_contract_id IS NULL
  AND contract.file_location IS NULL;

-- 7B. Ancillary contracts — file_location
UPDATE contract SET file_location = paths.file_location
FROM (VALUES
  ('GC01',  'Garden City SolarAfrica-CBE Project Agreement Assignment',  'CBE - GC01_Garden City SolarAfrica-CBE Project Agreement Assignment.pdf'),
  ('GC01',  'Garden City Transaction Documents',                         'CBE - GC01_ Garden City Transaction Documents (updated for LLC error).pdf'),
  ('LOI01', 'Loisaba SSA Revised Annexures',                             'CBE - LOI01_Loisaba SSA Revised Annexures Signed_20181016.pdf'),
  ('LOI01', 'Loisaba SolarAfrica COD Acceptance Certificate',            'CBE - LOI01_Loisaba SolarAfrica COD acceptance certificate_20190301.pdf'),
  ('LOI01', 'Loisaba Transfer Acceptance Certificates',                  'CBE - LOI01_Loisaba Transfer Acceptance Certficates Signed_20191031.pdf'),
  ('QMM01', 'QMM Permission Agreement',                                  'CBE - QMM01_QMM Permission Agreement Executed.pdf'),
  ('UGL01', 'Unilever Ghana SSA Schedules',                              'CBE - UGL01_Unilever Ghana SSA Schedules_20180829.pdf'),
  ('UGL01', 'Unilever Ghana COD Notice',                                 'CBE - UGL01_Unilever Ghana COD Notice Signed_20200112.pdf'),
  ('UTK01', 'Unilever Tea Kenya SSA Schedules',                          'CBE - UTK01_Unilever Tea Kenya SSA Schedules Signed_20180205.pdf'),
  ('XF-AB', 'XFlora SSA 1st Amendment COD Extension',                    'CBE - XF-AB_BV_SS_LO1 SSA 1st Amendment COD extension Signed_20200622.pdf'),
  ('XF-AB', 'XFlora SSA Adherence Agreement',                            'CBE - XF-AB_BV_SS_LO1 SSA Adherence Agreement Signed - 14 January.pdf'),
  ('CAL01', 'CMS Sale of Shares and Sale Claims Agreement',              'CBE - CAL01_CMS Sale of Shares and Sale Claims Agreement vExecuted.pdf'),
  ('ZO01',  'Zoodlabs Solar Loan Agreement',                             'CBE - ZO01_Zoodlabs solar loan agreement signed.pdf')
) AS paths(sage_id, contract_name, file_location)
JOIN project p ON p.sage_id = paths.sage_id AND p.organization_id = 1
WHERE contract.project_id = p.id
  AND contract.name = paths.contract_name
  AND contract.file_location IS NULL;

-- 7C. Amendments — file_path
UPDATE contract_amendment SET file_path = paths.file_path
FROM (VALUES
  ('GBL01', 1,  'CBE - GBL01_Guiness Ghana Breweries SSA 1st Amendment_Stamped_20191219.pdf'),
  ('GBL01', 2,  'CBE - GBL01_Guiness Ghana Breweries SSA 2nd Amendment_Stamped_20201217.pdf'),
  ('IVL01', 1,  'CBE - IVL01_IVL Dhunseri SSA Amendment & Restatement Signed_20220818.pdf'),
  ('KAS01', 1,  'CBE - KAS01_Kasapreko SSA Amendment Stamped_20170531 (Solar Africa).pdf'),
  ('KAS01', 2,  'CBE - KAS01_Kasapreko SSA 1st Amendment Solar Phase II Signed_20190426.pdf'),
  ('KAS01', 3,  'CBE - KAS01_Kasapreko SSA 2nd Amendment_Reinforcement Works Signed_20200706.pdf'),
  ('KAS01', 4,  'CBE - KAS01_Kasapreko SSA 3rd Amendment_Interconnection Works Signed_20210301.pdf'),
  ('LOI01', 1,  'CBE - LOI01_ Loisaba SSA 1st Amendment Signed_20181016.pdf'),
  ('MIR01', 1,  'CBE - MIR01_Miro SSA 1st Amendment Signed_20211111.pdf'),
  ('NBL01', 1,  'CBE - NBL01_Nigerian Breweries Ibadan SSA 1st Amendment Signed_201902.pdf'),
  ('NBL01', 2,  'CBE - NBL01_Nigerian Breweries Ibadan SSA 2nd Amendment_20210507.pdf'),
  ('NBL01', 3,  'CBE - NBL01_Nigerian Breweries Ibadan SSA 3rd Amendment Signed_20221022.pdf'),
  ('NBL02', 2,  'CBE - NBL02_Nigerian Breweries Ama SSA 2nd Amendment_20210501.pdf'),
  ('QMM01', 1,  'CBE - QMM01_QMM RESA 1st Amendment Stamped.pdf'),
  ('QMM01', 2,  'CBE - QMM01_ QMM RESA 2nd Amendment Signed.pdf'),
  ('UNSOS', 2,  'CBE - UNSOS_Baidoa_ SSA 2nd Amendment.pdf'),
  ('UNSOS', 3,  'CBE - UNSOS_Baidoa Amendment 3_Kube_14 Nov 2023.pdf'),
  ('XF-AB', 1,  'CBE - XF-AB_BV_SS_LO1 SSA 1st Amendment Signed_20200620.pdf')
) AS paths(sage_id, amend_num, file_path)
JOIN project p ON p.sage_id = paths.sage_id AND p.organization_id = 1
JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
WHERE contract_amendment.contract_id = c.id
  AND contract_amendment.amendment_number = paths.amend_num
  AND contract_amendment.file_path IS NULL;


-- 7D. Preserve original spreadsheet identifiers where Sage ID was normalized
UPDATE contract SET extraction_metadata = extraction_metadata || '{"source_sage_customer_id": "GC001"}'::jsonb
WHERE project_id = (SELECT id FROM project WHERE sage_id = 'GC01' AND organization_id = 1)
  AND parent_contract_id IS NULL;

UPDATE contract SET extraction_metadata = extraction_metadata || '{"source_sage_customer_id": "ZL01"}'::jsonb
WHERE project_id = (SELECT id FROM project WHERE sage_id = 'ZO01' AND organization_id = 1)
  AND parent_contract_id IS NULL;

UPDATE contract SET extraction_metadata = extraction_metadata || '{"source_sage_customer_id": "XF-AB/BV/L01/SS"}'::jsonb
WHERE project_id = (SELECT id FROM project WHERE sage_id = 'XF-AB' AND organization_id = 1)
  AND parent_contract_id IS NULL;


-- =============================================================================
-- STEP 8: POST-LOAD ASSERTIONS
-- =============================================================================

-- MOH01 integrity check
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM project WHERE id = 8 AND sage_id = 'MOH01') THEN
    RAISE EXCEPTION 'ASSERTION FAILED: MOH01 project missing (id=8)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM contract WHERE id = 7 AND project_id = 8) THEN
    RAISE EXCEPTION 'ASSERTION FAILED: MOH01 contract missing (id=7)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM contract_amendment WHERE id = 1 AND contract_id = 7) THEN
    RAISE EXCEPTION 'ASSERTION FAILED: MOH01 amendment missing (id=1)';
  END IF;
END $$;

-- Count assertions (approximate — allow some flexibility)
DO $$
DECLARE
  v_le_count    INT;
  v_cp_count    INT;
  v_proj_count  INT;
  v_primary     INT;
  v_ancillary   INT;
  v_amend_count INT;
BEGIN
  SELECT count(*) INTO v_le_count FROM legal_entity WHERE organization_id = 1;
  SELECT count(*) INTO v_cp_count FROM counterparty;
  SELECT count(*) INTO v_proj_count FROM project WHERE organization_id = 1;
  SELECT count(*) INTO v_primary FROM contract WHERE parent_contract_id IS NULL;
  SELECT count(*) INTO v_ancillary FROM contract WHERE parent_contract_id IS NOT NULL;
  SELECT count(*) INTO v_amend_count FROM contract_amendment;

  -- Legal entities: 3 existing + 8 new = 11
  IF v_le_count < 11 THEN
    RAISE EXCEPTION 'ASSERTION FAILED: Expected >= 11 legal entities, got %', v_le_count;
  END IF;

  -- Counterparties: 6 existing + ~22 new (some may merge) = ~28
  IF v_cp_count < 25 THEN
    RAISE EXCEPTION 'ASSERTION FAILED: Expected >= 25 counterparties, got %', v_cp_count;
  END IF;

  -- Projects: 1 existing (MOH01) + 31 new = 32 (TBC has no external_project_id collision)
  IF v_proj_count < 30 THEN
    RAISE EXCEPTION 'ASSERTION FAILED: Expected >= 30 projects (org=1), got %', v_proj_count;
  END IF;

  -- Primary contracts: 1 existing (MOH01) + ~27 new = ~28
  IF v_primary < 27 THEN
    RAISE EXCEPTION 'ASSERTION FAILED: Expected >= 27 primary contracts, got %', v_primary;
  END IF;

  -- Ancillary contracts: ~13 (incl ZO01 loan)
  IF v_ancillary < 12 THEN
    RAISE EXCEPTION 'ASSERTION FAILED: Expected >= 12 ancillary contracts, got %', v_ancillary;
  END IF;

  -- Amendments: 1 existing (MOH01) + ~18 new = ~19
  IF v_amend_count < 18 THEN
    RAISE EXCEPTION 'ASSERTION FAILED: Expected >= 18 amendments, got %', v_amend_count;
  END IF;

  RAISE NOTICE '=== Migration 046 Summary ===';
  RAISE NOTICE 'Legal entities:       %', v_le_count;
  RAISE NOTICE 'Counterparties:       %', v_cp_count;
  RAISE NOTICE 'Projects (org=1):     %', v_proj_count;
  RAISE NOTICE 'Primary contracts:    %', v_primary;
  RAISE NOTICE 'Ancillary contracts:  %', v_ancillary;
  RAISE NOTICE 'Amendments:           %', v_amend_count;
END $$;


-- Cleanup temp tables
DROP TABLE IF EXISTS stg_portfolio;
DROP TABLE IF EXISTS stg_amendments;

COMMIT;
