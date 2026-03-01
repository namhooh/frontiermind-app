-- =============================================================================
-- 047_populate_sage_contract_ids.sql
-- =============================================================================
-- Part A: SAGE Contract IDs, Payment Terms & End Dates
--   Populates external_contract_id (SAGE contract number), payment_terms, and
--   end_date for the 27 primary contracts that have matching SAGE ERP records.
--   Source: CBE_data_extracts/Data Extracts/FrontierMind Extracts_dim_finance_contract.csv
--   Filtered: DIM_CURRENT_RECORD=1, CONTRACT_CATEGORY in (KWH, RENTAL)
--   Scope: 26 contracts get all 3 fields; MOH01 gets end_date only; 3 skipped
--   Uses project.sage_id joins (not hardcoded contract IDs) for environment stability.
--
-- Part B: Parent-Child Contract Line Hierarchy
--   Adds parent_contract_line_id self-referential FK to contract_line (mirrors
--   contract.parent_contract_id pattern). Inserts MOH01 line 1000 as a "mother"
--   site-level contract_line and links per-meter available lines as children.
--   Pattern: Mother line (site-level, meter_id NULL) -> children (per-meter lines)
--   Billing resolver detects mother lines (meter_id IS NULL) from Pass 1,
--   then queries children via parent_contract_line_id to find a child with a meter.
-- =============================================================================

BEGIN;

-- =============================================================================
-- PART A: SAGE CONTRACT IDS, PAYMENT TERMS & END DATES
-- =============================================================================

-- =============================================================================
-- STEP A1: UPDATE 26 CONTRACTS WITH FULL SAGE DATA
-- =============================================================================
-- Pattern: CTE of (sage_id, external_contract_id, payment_terms, end_date) tuples
-- joined to project.sage_id -> contract.project_id for FK-safe resolution.

WITH sage_data(sage_id, ext_id, terms, end_dt) AS (VALUES
  -- Ghana (facility GHA00)
  ('KAS01',  'CONGHA00-2021-00002', '30EOM',  '2030-02-28'::date),
  ('UGL01',  'CONGHA00-2021-00001', '90NET',  '2035-12-31'::date),
  ('GBL01',  'CONGHA00-2021-00004', '60NET',  '2047-05-31'::date),
  -- Ghana (facility CBCH0 — GC01 operated under CrossBoundary entity)
  ('GC01',   'CONCBCH0-2021-00001', '30EOM',  '2030-02-28'::date),
  -- Egypt (facility EGY00)
  ('IVL01',  'CONEGY00-2023-00001', '30NET',  '2048-08-30'::date),
  -- Kenya (facility KEN00)
  ('AR01',   'CONKEN00-2023-00008', '30NET',  '2035-11-01'::date),
  ('LOI01',  'CONKEN00-2021-00002', '30EOM',  '2037-05-31'::date),
  ('MB01',   'CONKEN00-2023-00009', '30NET',  '2044-12-31'::date),
  ('MF01',   'CONKEN00-2023-00011', '30NET',  '2043-11-01'::date),
  ('MP01',   'CONKEN00-2024-00014', '30NET',  '2044-03-31'::date),
  ('MP02',   'CONKEN00-2024-00012', '30NET',  '2044-02-29'::date),
  ('NC02',   'CONKEN00-2023-00010', '30NET',  '2043-11-01'::date),
  ('NC03',   'CONKEN00-2024-00013', '30NET',  '2044-02-29'::date),
  ('TBM01',  'CONKEN00-2023-00007', '30NET',  '2042-02-01'::date),
  ('UTK01',  'CONKEN00-2021-00001', '90EOM',  '2036-06-30'::date),
  ('AMP01',  'CONKEN00-2025-00013', '30EOM',  '2032-03-31'::date),
  -- Kenya — XFlora (4 SAGE sub-contracts -> 1 FM project; primary = XFAB contract)
  ('XF-AB',  'CONKEN00-2021-00003', '30EOM',  '2047-05-31'::date),
  -- Madagascar (facility MAD00)
  ('QMM01',  'CONMAD00-2023-00001', '75EOM',  '2043-05-03'::date),
  -- Madagascar (facility MAD02)
  ('ERG',    'CONMAD02-2023-00001', '30NET',  '2043-11-13'::date),
  -- Mozambique (facility MOZ00)
  ('TWG01',  'CONMOZ00-2023-00003', '30EOM',  '2033-11-01'::date),
  -- Nigeria (facility NIG00)
  ('JAB01',  'CONNIG00-2021-00001', '30EOM',  '2033-02-28'::date),
  ('NBL01',  'CONNIG00-2021-00002', '60NET',  '2036-03-31'::date),
  ('NBL02',  'CONNIG00-2023-00003', '60NET',  '2038-03-01'::date),
  -- Sierra Leone (facility SLL02)
  ('MIR01',  'CONSLL02-2023-00002', '30NET',  '2029-10-01'::date),
  -- Somalia (facility KUBE0)
  ('UNSOS',  'CONKUBE0-2024-00001', '30NET',  '2028-12-31'::date),
  -- Zimbabwe (facility ZIM00)
  ('CAL01',  'CONZIM00-2025-00002', '30NET',  '2041-12-31'::date)
)
UPDATE contract c
SET external_contract_id = s.ext_id,
    payment_terms = s.terms,
    end_date = s.end_dt,
    updated_at = NOW()
FROM sage_data s
JOIN project p ON p.sage_id = s.sage_id
WHERE c.project_id = p.id
  AND c.parent_contract_id IS NULL
  AND c.organization_id = 1;


-- =============================================================================
-- STEP A2: UPDATE MOH01 end_date ONLY
-- =============================================================================
-- MOH01 already has external_contract_id = 'CONGHA00-2025-00005' and
-- payment_terms = '30NET' from prior onboarding. Only end_date is missing.

UPDATE contract c
SET end_date = '2045-12-31'::date,
    updated_at = NOW()
FROM project p
WHERE c.project_id = p.id
  AND p.sage_id = 'MOH01'
  AND c.parent_contract_id IS NULL
  AND c.organization_id = 1
  AND c.end_date IS NULL;


-- =============================================================================
-- STEP A3: SAGE POST-LOAD ASSERTIONS
-- =============================================================================

-- Assert: all 27 contracts with SAGE data now have external_contract_id
DO $$
DECLARE
  v_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM contract c
  JOIN project p ON p.id = c.project_id
  WHERE c.parent_contract_id IS NULL
    AND c.organization_id = 1
    AND c.external_contract_id IS NOT NULL;

  IF v_count < 27 THEN
    RAISE EXCEPTION '047 assertion failed: expected >= 27 contracts with external_contract_id, got %', v_count;
  END IF;
END $$;

-- Assert: all 27 contracts with SAGE data now have payment_terms
DO $$
DECLARE
  v_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM contract c
  JOIN project p ON p.id = c.project_id
  WHERE c.parent_contract_id IS NULL
    AND c.organization_id = 1
    AND c.payment_terms IS NOT NULL;

  IF v_count < 27 THEN
    RAISE EXCEPTION '047 assertion failed: expected >= 27 contracts with payment_terms, got %', v_count;
  END IF;
END $$;

-- Assert: all 27 contracts with SAGE data now have end_date
DO $$
DECLARE
  v_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM contract c
  JOIN project p ON p.id = c.project_id
  WHERE c.parent_contract_id IS NULL
    AND c.organization_id = 1
    AND c.end_date IS NOT NULL;

  IF v_count < 27 THEN
    RAISE EXCEPTION '047 assertion failed: expected >= 27 contracts with end_date, got %', v_count;
  END IF;
END $$;

-- Assert: MOH01 external_contract_id unchanged
DO $$
DECLARE
  v_ext_id VARCHAR;
BEGIN
  SELECT c.external_contract_id INTO v_ext_id
  FROM contract c
  JOIN project p ON p.id = c.project_id
  WHERE p.sage_id = 'MOH01'
    AND c.parent_contract_id IS NULL
    AND c.organization_id = 1;

  IF v_ext_id <> 'CONGHA00-2025-00005' THEN
    RAISE EXCEPTION '047 assertion failed: MOH01 external_contract_id should be CONGHA00-2025-00005, got %', v_ext_id;
  END IF;
END $$;

-- Assert: no ancillary contracts were modified (parent_contract_id IS NOT NULL should have 0 external_contract_id)
DO $$
DECLARE
  v_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM contract
  WHERE parent_contract_id IS NOT NULL
    AND organization_id = 1
    AND external_contract_id IS NOT NULL;

  IF v_count > 0 THEN
    RAISE EXCEPTION '047 assertion failed: % ancillary contracts have external_contract_id (should be 0)', v_count;
  END IF;
END $$;


-- =============================================================================
-- PART B: PARENT-CHILD CONTRACT LINE HIERARCHY
-- =============================================================================

-- =============================================================================
-- STEP B0: Drop old line_decomposition table (from prior version)
-- =============================================================================
DROP TABLE IF EXISTS line_decomposition;

-- =============================================================================
-- STEP B1: Schema — add parent_contract_line_id
-- =============================================================================
ALTER TABLE contract_line
    ADD COLUMN IF NOT EXISTS parent_contract_line_id BIGINT
        REFERENCES contract_line(id);

-- No self-parent
ALTER TABLE contract_line
    DROP CONSTRAINT IF EXISTS chk_contract_line_no_self_parent;
ALTER TABLE contract_line
    ADD CONSTRAINT chk_contract_line_no_self_parent
        CHECK (parent_contract_line_id <> id);

-- Partial index for child lookups
CREATE INDEX IF NOT EXISTS idx_contract_line_parent
    ON contract_line(parent_contract_line_id)
    WHERE parent_contract_line_id IS NOT NULL;

COMMENT ON COLUMN contract_line.parent_contract_line_id IS
    'Self-referential FK to parent (mother) contract line. '
    'Used when a client models a single site-level line that FrontierMind '
    'decomposes into per-meter child lines. Mirrors contract.parent_contract_id pattern.';

-- Trigger: parent must belong to the same contract
CREATE OR REPLACE FUNCTION contract_line_same_contract_parent()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.parent_contract_line_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM contract_line
            WHERE id = NEW.parent_contract_line_id
              AND contract_id = NEW.contract_id
        ) THEN
            RAISE EXCEPTION 'parent_contract_line_id (%) must belong to the same contract_id (%)',
                NEW.parent_contract_line_id, NEW.contract_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_contract_line_same_contract_parent ON contract_line;
CREATE TRIGGER trg_contract_line_same_contract_parent
    BEFORE INSERT OR UPDATE OF parent_contract_line_id ON contract_line
    FOR EACH ROW
    EXECUTE FUNCTION contract_line_same_contract_parent();

-- =============================================================================
-- STEP B2: Revert broken external_line_id from old version
-- =============================================================================
-- The old version set external_line_id = '11481428495164935368' on ALL
-- per-meter available lines. Clear it — the unique index uq_contract_line_external_line_id
-- only allows one row per external_line_id per org.
UPDATE contract_line cl
SET external_line_id = NULL
FROM contract c
WHERE cl.contract_id = c.id
  AND c.external_contract_id = 'CONGHA00-2025-00005'
  AND cl.energy_category = 'available'
  AND cl.external_line_id = '11481428495164935368';

-- =============================================================================
-- STEP B3: Insert mother line 1000 (site-level Available Energy)
-- =============================================================================
INSERT INTO contract_line (
    contract_id, contract_line_number, product_desc,
    energy_category, meter_id, external_line_id,
    effective_start_date, effective_end_date,
    billing_product_id, is_active, organization_id
)
SELECT
    c.id,
    1000,
    'Available Energy (EAvailable) - Site Level',
    'available'::energy_category,
    NULL,                           -- site-level, no specific meter
    '11481428495164935368',         -- CBE CONTRACT_LINE_UNIQUE_ID
    '2025-12-01'::date,
    '2045-12-31'::date,
    NULL,                           -- site-level, no specific product
    true,
    c.organization_id
FROM contract c
WHERE c.external_contract_id = 'CONGHA00-2025-00005'
ON CONFLICT (contract_id, contract_line_number) DO NOTHING;

-- =============================================================================
-- STEP B4: Link children to mother line
-- =============================================================================
UPDATE contract_line cl
SET parent_contract_line_id = mother.id
FROM contract_line mother
JOIN contract c ON c.id = mother.contract_id
WHERE c.external_contract_id = 'CONGHA00-2025-00005'
  AND mother.contract_line_number = 1000
  AND mother.energy_category = 'available'
  AND cl.contract_id = mother.contract_id
  AND cl.energy_category = 'available'
  AND cl.contract_line_number != 1000
  AND cl.parent_contract_line_id IS NULL;

-- =============================================================================
-- STEP B5: Parent-child verification
-- =============================================================================

-- Verify: mother line 1000 exists
DO $$
DECLARE
    mother_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO mother_count
    FROM contract_line cl
    JOIN contract c ON c.id = cl.contract_id
    WHERE c.external_contract_id = 'CONGHA00-2025-00005'
      AND cl.contract_line_number = 1000
      AND cl.energy_category = 'available'
      AND cl.external_line_id = '11481428495164935368';

    IF mother_count = 0 THEN
        RAISE WARNING '047-B: Mother line 1000 not found for MOH01';
    ELSE
        RAISE NOTICE '047-B: Mother line 1000 created for MOH01 Available Energy';
    END IF;
END $$;

-- Verify: 5 children linked to mother
DO $$
DECLARE
    child_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO child_count
    FROM contract_line cl
    JOIN contract c ON c.id = cl.contract_id
    WHERE c.external_contract_id = 'CONGHA00-2025-00005'
      AND cl.energy_category = 'available'
      AND cl.parent_contract_line_id IS NOT NULL;

    IF child_count != 5 THEN
        RAISE WARNING '047-B: Expected 5 child lines, found %', child_count;
    ELSE
        RAISE NOTICE '047-B: Linked 5 child available lines to mother line 1000';
    END IF;
END $$;

COMMIT;
