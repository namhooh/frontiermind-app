-- Migration 058: Sage Business Partner import
-- Adds sage_bp_code to counterparty, new counterparty_types, imports all Sage BPs
-- Bulk vendor/supplier import handled by: python-backend/scripts/step12_sage_bp_import.py

-- ============================================================
-- 1. Add sage_bp_code column to counterparty
-- ============================================================
ALTER TABLE counterparty ADD COLUMN IF NOT EXISTS sage_bp_code VARCHAR(20);
CREATE UNIQUE INDEX IF NOT EXISTS idx_counterparty_sage_bp_code
  ON counterparty(sage_bp_code) WHERE sage_bp_code IS NOT NULL;

-- Drop overly restrictive unique index on (counterparty_type_id, lower(name))
-- sage_bp_code is now the proper dedup key; many Sage BPs share names with different codes
DROP INDEX IF EXISTS uq_counterparty_type_name;

-- ============================================================
-- 2. Add new counterparty_type entries
-- ============================================================
INSERT INTO counterparty_type (name, code, description) VALUES
  ('Vendor/Supplier', 'VENDOR', 'External service provider or goods supplier')
ON CONFLICT DO NOTHING;
INSERT INTO counterparty_type (name, code, description) VALUES
  ('Internal Entity', 'INTERNAL', 'CBE group company, SPV, or management entity')
ON CONFLICT DO NOTHING;
INSERT INTO counterparty_type (name, code, description) VALUES
  ('Takeon Placeholder', 'TAKEON', 'Sage migration placeholder account')
ON CONFLICT DO NOTHING;

-- ============================================================
-- 3. Fix NULL counterparty_type_id on existing offtakers
-- ============================================================
-- Heineken id 89 needs name disambiguation (id 58 already has 'Heineken')
UPDATE counterparty
SET counterparty_type_id = (SELECT id FROM counterparty_type WHERE code = 'OFFTAKER'),
    name = 'Heineken (Ibadan)'
WHERE id = 89 AND counterparty_type_id IS NULL;

UPDATE counterparty
SET counterparty_type_id = (SELECT id FROM counterparty_type WHERE code = 'OFFTAKER')
WHERE counterparty_type_id IS NULL
  AND id IN (93, 94, 95, 97);

-- ============================================================
-- 4. Populate sage_bp_code + registered_name for existing offtakers
--    Maps Sage CUSTOMER_NUMBER to existing FM counterparties via project.sage_id
-- ============================================================

-- Devki Group (id:50) — use MB01 as primary sage code; registered_name from main entity
UPDATE counterparty SET sage_bp_code = 'MB01',
  registered_name = 'Maisha Mabati Mills Limited'
WHERE id = 50;

-- Diageo (id:45)
UPDATE counterparty SET sage_bp_code = 'GBL01',
  registered_name = 'Guinness Ghana Breweries Limited'
WHERE id = 45;

-- Unilever (id:47)
UPDATE counterparty SET sage_bp_code = 'UGL01',
  registered_name = 'Uniliver Ghana Limited'
WHERE id = 47;

-- Kasapreko (id:46)
UPDATE counterparty SET sage_bp_code = 'KAS01',
  registered_name = 'Kasapreko Company Limited'
WHERE id = 46;

-- Polytanks / Mohinani (id:11)
UPDATE counterparty SET sage_bp_code = 'MOH01',
  registered_name = 'Polytanks Ghana Limited'
WHERE id = 11;

-- Indorama Ventures (id:44)
UPDATE counterparty SET sage_bp_code = 'IVL01',
  registered_name = 'IVL Dhunseri Polyester Company SAE'
WHERE id = 44;

-- GC Retail (id:41)
UPDATE counterparty SET sage_bp_code = 'GC001',
  registered_name = 'GC Retail Limited'
WHERE id = 41;

-- Ampersand (id:54)
UPDATE counterparty SET sage_bp_code = 'AMP01',
  registered_name = 'Ampersand E-Mobility Limited'
WHERE id = 54;

-- Arijiju Retreat (id:48)
UPDATE counterparty SET sage_bp_code = 'AR01',
  registered_name = 'Arijiju Management Limited'
WHERE id = 48;

-- Oryx Ltd / Loisaba (id:49)
UPDATE counterparty SET sage_bp_code = 'LOI01',
  registered_name = 'Loisaba Conservancy Laikip'
WHERE id = 49;

-- Brush Manufacturers (id:51)
UPDATE counterparty SET sage_bp_code = 'TBM01',
  registered_name = 'Brush Manufacturers Limited'
WHERE id = 51;

-- Lipton / eKaterra (id:52)
UPDATE counterparty SET sage_bp_code = 'UTK01',
  registered_name = 'Ekaterra Tea Kenya PLC'
WHERE id = 52;

-- Heineken / NBL01 (id:89)
UPDATE counterparty SET sage_bp_code = 'NBL01',
  registered_name = 'Nigeria Breweries Limited'
WHERE id = 89;

-- Heineken / NBL02 (id:58)
UPDATE counterparty SET sage_bp_code = 'NBL02',
  registered_name = 'Nigeria Breweries PLC (Ama)'
WHERE id = 58;

-- Jabi Mall (id:57)
UPDATE counterparty SET sage_bp_code = 'JAB01',
  registered_name = 'Jabi Mall Development Co. Limited'
WHERE id = 57;

-- Miro Forestry (id:59)
UPDATE counterparty SET sage_bp_code = 'MIR01',
  registered_name = 'Miro Forestry (SL) Limited'
WHERE id = 59;

-- Next Source Materials / ERG (id:56)
UPDATE counterparty SET sage_bp_code = 'ERG',
  registered_name = 'ERG MADAGASCAR SARLU'
WHERE id = 56;

-- Rio Tinto / QMM (id:55)
UPDATE counterparty SET sage_bp_code = 'QMM01',
  registered_name = 'QIT MADAGASCAR MINERALS SA'
WHERE id = 55;

-- Blanket Mine / Caledonia (id:62)
UPDATE counterparty SET sage_bp_code = 'CAL01',
  registered_name = 'Blanket Mine (1983) (Private) Limited'
WHERE id = 62;

-- UNSOS (id:60)
UPDATE counterparty SET sage_bp_code = 'UNSOS',
  registered_name = 'UN Support Office in Somalia'
WHERE id = 60;

-- Xflora Africa Blooms (id:53)
UPDATE counterparty SET sage_bp_code = 'XFAB',
  registered_name = 'Xflora Africa Blooms'
WHERE id = 53;

-- Xflora Bloom Valley (id:93)
UPDATE counterparty SET sage_bp_code = 'XFBV',
  registered_name = 'Xflora Bloom Valley'
WHERE id = 93;

-- Xpressions Flora (id:94)
UPDATE counterparty SET sage_bp_code = 'XFL01',
  registered_name = 'Xpressions Flora'
WHERE id = 94;

-- Sojanmi Spring (id:95)
UPDATE counterparty SET sage_bp_code = 'XFSS',
  registered_name = 'Sojanmi Spring'
WHERE id = 95;

-- Zoodlabs Group (id:42)
UPDATE counterparty SET sage_bp_code = 'ZL01',
  registered_name = 'Zoodlabs (SL) Limited'
WHERE id = 42;

-- Twigg Exploration (id:61)
UPDATE counterparty SET sage_bp_code = 'TWG',
  registered_name = 'Twigg Exploration and Mining, Limitada'
WHERE id = 61;

-- Accra Breweries (id:63) — ABI01 not in Sage CSV but exists in FM
UPDATE counterparty SET registered_name = 'Accra Breweries'
WHERE id = 63 AND registered_name IS NULL;

-- Izuba BNT (id:64) — BNT01 not in Sage CSV
UPDATE counterparty SET registered_name = 'Izuba BNT'
WHERE id = 64 AND registered_name IS NULL;

-- iSAT Africa (id:43)
UPDATE counterparty SET sage_bp_code = 'IA01',
  registered_name = 'iSAT Africa Limited'
WHERE id = 43;

-- Maisha Mabati Mills Limited (id:97) — duplicate of Devki, just set registered_name
UPDATE counterparty SET registered_name = 'Maisha Mabati Mills Limited'
WHERE id = 97 AND registered_name IS NULL;

-- ============================================================
-- 5. Import CBE internal entities
-- ============================================================
INSERT INTO counterparty (name, sage_bp_code, registered_name, counterparty_type_id, country)
SELECT v.name, v.sage_bp_code, v.registered_name,
       (SELECT id FROM counterparty_type WHERE code = 'INTERNAL'),
       v.country
FROM (VALUES
  ('CrossBoundary Energy Holdings', 'CBEH0', 'CrossBoundary Energy Holdings', 'Mauritius'),
  ('CrossBoundary Energy Management', 'CBMM0', 'CrossBoundary Energy Management', 'Mauritius'),
  ('CrossBoundary Energy Management Australia', 'CBMA0', 'CrossBoundary Energy Management Australia Pty Ltd', 'Australia'),
  ('CrossBoundary Energy Credit Holding', 'CBCH0', 'CrossBoundary Energy Credit Holding', 'Mauritius'),
  ('CBE Management South Africa', 'CBMSA', 'CBE Management South Africa', 'South Africa'),
  ('CBE Management South Africa', 'CMSA', 'CBE Management South Africa', 'South Africa'),
  ('CBE Management Kenya', 'CBMMK', 'CBE Management Kenya', 'Kenya'),
  ('CBE Solar Management Nigeria', 'CBSMN', 'CBE Solar Management Nigeria Limited', 'Nigeria'),
  ('CrossBoundary Energy Telecom Solutions Nigeria', 'CBTS0', 'CrossBoundary Energy Telecom Solutions Nigeria Ltd', 'Nigeria'),
  ('CrossBoundary LLC', 'CBLLC', 'CrossBounday LLC', 'United States'),
  ('CrossBoundary LLC', 'MAS024', 'CrossBoundary LLC', 'Mauritius'),
  ('CrossBoundary Energy Rwanda', 'CBER', 'CrossBoundary Energy Rwanda Limited', 'Rwanda'),
  ('CrossBoundary Energy Madagascar', 'CBMG', 'CrossBoundary Energy Madagascar', 'Madagascar'),
  ('CrossBoundary Energy Sierra Leone', 'CBESL', 'CrossBoundary Sierra Leone', 'Sierra Leone'),
  ('CrossBoundary Energy Kenya', 'KEN00', 'CrossBoundary Energy Kenya Limited', 'Kenya'),
  ('CrossBoundary Energy Ghana', 'GHA00', 'CrossBoundary Energy Ghana Limited Company', 'Ghana'),
  ('CrossBoundary Energy Nigeria', 'NIG00', 'CrossBoundary Energy Nigeria', 'Nigeria'),
  ('CrossBoundary Energy DRC', 'DRC00', 'CrossBoundary Energy DRC I', 'DRC'),
  ('CrossBoundary Energy Sierra Leone', 'SL0', 'CrossBoundary Energy Sierra Leone', 'Sierra Leone'),
  ('CrossBoundary Energy Sierra Leone II', 'SL02', 'CrossBoundary Energy Sierra Leone', 'Sierra Leone'),
  ('CrossBoundary Energy Madagascar', 'MD00', 'CrossBoundary Energy Madagascar', 'Madagascar'),
  ('CrossBoundary Energy Madagascar II', 'MD02', 'CrossBoundary Energy Madagascar II', 'Madagascar'),
  ('CrossBoundary Energy Egypt', 'EGY0', 'CrossBoundary Energy Egypt', 'Egypt'),
  ('CrossBoundary Energy Senegal', 'SEN00', 'CrossBoundary Energy Senegal', 'Senegal'),
  ('CBE Management Australia', 'CBMA', 'CBE Management Australia', 'Australia'),
  ('CBE Australia', 'CBA', 'CBE Australia', 'Australia'),
  ('CrossBoundary Energy Rwanda', 'RWA00', 'CrossBoundary Energy Rwanda Limited', 'Rwanda'),
  ('CrossBoundary Energy Rwanda', 'RWA11', 'CrossBoundary Energy Rwanda Limited', 'Rwanda'),
  ('CBEM', 'MAS022', 'CBEM', 'Mauritius'),
  ('CBEH Kenya', 'KES012', 'CBEH Kenya', 'Kenya')
) AS v(name, sage_bp_code, registered_name, country)
WHERE NOT EXISTS (
  SELECT 1 FROM counterparty c WHERE c.sage_bp_code = v.sage_bp_code
);

-- ============================================================
-- 6. Import Takeon placeholder entries
-- ============================================================
INSERT INTO counterparty (name, sage_bp_code, registered_name, counterparty_type_id)
SELECT v.name, v.sage_bp_code, v.registered_name,
       (SELECT id FROM counterparty_type WHERE code = 'TAKEON')
FROM (VALUES
  ('CBEH Takeon Customer', 'ZEHTOC', 'CBEH Takeon Customer'),
  ('CBeH Takeon Supplier', 'ZEHTOS', 'CBeH Takeon Supplier'),
  ('CBCH Takeon Customer', 'ZCHTOC', 'CBCH Takeon Customer'),
  ('CBCH Takeon Supplier', 'ZCHTOS', 'CBCH Takeon Supplier'),
  ('CBMM Takeon Customer', 'ZMMTOC', 'CBMM Takeon Customer'),
  ('CBMM Takeon Supplier', 'ZMMTOS', 'CBMM Takeon Supplier'),
  ('NIG0 Takeon Customer', 'ZNITOC', 'NIG0 Takeon Customer'),
  ('NIG0 Takeon Supplier', 'ZNITOS', 'NIG0 Takeon Supplier'),
  ('GHA0 Takeon Customer', 'ZGHTOC', 'GHA0 Takeon Customer'),
  ('GHA0 Takeon Supplier', 'ZGHTOS', 'GHA0 Takeon Supplier'),
  ('RWA0 Takeon Customer', 'ZRWTOC', 'RWA0 Takeon Customer'),
  ('RWA0 Takeon Supplier', 'ZRWTOS', 'RWA0 Takeon Supplier'),
  ('SL02 Take on Customer', 'ZSLTOC', 'SL02 Take on Customer'),
  ('SL02 Take on Supplier', 'ZSLTOS', 'SL02 Take on Supplier')
) AS v(name, sage_bp_code, registered_name)
WHERE NOT EXISTS (
  SELECT 1 FROM counterparty c WHERE c.sage_bp_code = v.sage_bp_code
);

-- ============================================================
-- 7. Merge amendment_date into effective_date, drop amendment_date
--    amendment_date and effective_date on contract_amendment are redundant.
--    amendment_date holds the signing date (17/20 rows populated),
--    effective_date is NULL for 19/20 rows. Consolidate into effective_date only.
-- ============================================================

-- Copy amendment_date → effective_date where effective_date is NULL
UPDATE contract_amendment
SET effective_date = amendment_date
WHERE effective_date IS NULL AND amendment_date IS NOT NULL;

-- Drop the redundant column
ALTER TABLE contract_amendment DROP COLUMN amendment_date;
