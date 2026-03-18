-- Migration 061: CBE Baseline Gap Resolution
-- Addresses gaps found in baseline mapping review (Steps 1-9, 12)
--
-- GAP 2 (revised): Link contract_line.billing_product_id via junction table
-- GAP 11: Create meter records for METERED contract_lines missing meters
-- Both are prerequisites for Step 9A (meter_aggregate insertion)

BEGIN;

-- ============================================================================
-- GAP 2: Link contract_line.billing_product_id
-- 110 of 114 contract_lines have NULL billing_product_id.
-- Strategy: match via contract_billing_product junction + product_desc name.
-- billing_product.organization_id = NULL is correct (canonical/platform-level).
-- ============================================================================

-- Phase 1: Exact name match through junction
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND bp.name = cl2.product_desc
    ORDER BY cl2.id, cbp.is_primary DESC NULLS LAST
) sub
WHERE cl.id = sub.cl_id;

-- Phase 2: product_desc starts with bp.name (e.g. "Metered Energy (EMetered) - PPL1")
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND (cl2.product_desc LIKE bp.name || ' -%'
           OR cl2.product_desc LIKE bp.name || ' Combined%')
    ORDER BY cl2.id, cbp.is_primary DESC NULLS LAST
) sub
WHERE cl.id = sub.cl_id;

-- Phase 3: Fuzzy match for "Green" prefixed variants (CAL01)
-- "Green Metered Energy (EMetered)" → ENER002 "Metered Energy (EMetered)"
-- "Green Available Energy (EAvailable)" → ENER003 "Available Energy (EAvailable)"
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND cl2.product_desc LIKE 'Green %'
      AND bp.name = REPLACE(cl2.product_desc, 'Green ', '')
    ORDER BY cl2.id, cbp.is_primary DESC NULLS LAST
) sub
WHERE cl.id = sub.cl_id;

-- Phase 4: Match GBL01 "Grid (EMetered)" → GHREV002, "Grid (EAvailable)" → GHREV001
-- The junction has these products but names differ slightly ("Grid (E Metered)" vs "Grid (EMetered)")
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND (
        -- "Grid (EMetered)" matches "Grid (E Metered)"
        (cl2.product_desc = 'Grid (EMetered)' AND bp.name LIKE 'Grid (E Metered%')
        OR (cl2.product_desc = 'Grid (EAvailable)' AND bp.name LIKE 'Grid (E Available%')
      )
    ORDER BY cl2.id, cbp.is_primary DESC NULLS LAST
) sub
WHERE cl.id = sub.cl_id;

-- Phase 5: Match IVL01 "Available Energy (EAvailable)" → EGREVS002 via junction
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND cl2.energy_category::text = CASE
          WHEN bp.name LIKE '%Metered%' OR bp.name LIKE '%EMetered%' THEN 'metered'
          WHEN bp.name LIKE '%Available%' OR bp.name LIKE '%EAvailable%' THEN 'available'
          WHEN bp.name LIKE '%Test%' OR bp.name LIKE '%Early%' THEN 'test'
          ELSE 'unknown'
      END
      -- Only for contracts with a single billing_product per energy_category
      AND (SELECT COUNT(*) FROM contract_billing_product cbp2
           JOIN billing_product bp2 ON cbp2.billing_product_id = bp2.id
           WHERE cbp2.contract_id = cl2.contract_id
             AND CASE
                 WHEN bp2.name LIKE '%Metered%' OR bp2.name LIKE '%EMetered%' THEN 'metered'
                 WHEN bp2.name LIKE '%Available%' OR bp2.name LIKE '%EAvailable%' THEN 'available'
                 WHEN bp2.name LIKE '%Test%' OR bp2.name LIKE '%Early%' THEN 'test'
                 ELSE 'unknown'
             END = cl2.energy_category::text
          ) = 1
    ORDER BY cl2.id
) sub
WHERE cl.id = sub.cl_id;

-- Phase 6: NBL01 phase-specific lines → match to base product via energy_category + junction
-- "Generator (EMetered) Phase 1" → NIREVS009 "Generator (EMetered)"
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND cl2.product_desc ~ ' Phase [0-9]'
      AND bp.name = regexp_replace(cl2.product_desc, ' Phase [0-9]+$', '')
    ORDER BY cl2.id, cbp.is_primary DESC NULLS LAST
) sub
WHERE cl.id = sub.cl_id;

-- Phase 7: QMM01 phase-specific and technology-specific variants
-- "Metered Energy (EMetered) Phase 1" → ENER002
-- "Metered Energy (EMetered) Wind" → ENER002
-- "Metered Energy (EMetered) Expanded PV" → ENER002
-- "Available Energy (EAvailable) Phase 1" → ENER003
UPDATE contract_line cl
SET billing_product_id = sub.bp_id
FROM (
    SELECT DISTINCT ON (cl2.id)
        cl2.id AS cl_id,
        cbp.billing_product_id AS bp_id
    FROM contract_line cl2
    JOIN contract_billing_product cbp ON cbp.contract_id = cl2.contract_id
    JOIN billing_product bp ON cbp.billing_product_id = bp.id
    WHERE cl2.organization_id = 1
      AND cl2.billing_product_id IS NULL
      AND (
        cl2.product_desc LIKE bp.name || ' Phase%'
        OR cl2.product_desc LIKE bp.name || ' Wind%'
        OR cl2.product_desc LIKE bp.name || ' Expanded%'
      )
    ORDER BY cl2.id, cbp.is_primary DESC NULLS LAST
) sub
WHERE cl.id = sub.cl_id;


-- ============================================================================
-- GAP 11: Create meter records for METERED contract_lines without meters
-- Only 7 meters exist but 87 active METERED contract_lines need them.
-- meter_aggregate.meter_id FK requires these records.
-- ============================================================================

-- Create meters from active METERED contract_lines that don't have one
INSERT INTO meter (project_id, name, unit, created_at)
SELECT DISTINCT ON (c.project_id, cl.product_desc)
    c.project_id,
    COALESCE(
        -- Extract meter name from product_desc suffix (e.g. "Metered Energy (EMetered) - PPL1" → "PPL1")
        CASE
            WHEN cl.product_desc LIKE '% - %'
            THEN substring(cl.product_desc FROM ' - (.+)$')
            ELSE cl.product_desc
        END,
        'Main Meter'
    ),
    'kWh',
    NOW()
FROM contract_line cl
JOIN contract c ON cl.contract_id = c.id
JOIN project p ON c.project_id = p.id
WHERE cl.organization_id = 1
  AND cl.is_active = true
  AND cl.energy_category IN ('metered', 'available')
  AND cl.meter_id IS NULL
  AND p.organization_id = 1
ORDER BY c.project_id, cl.product_desc, cl.id;

-- Link contract_lines to their newly created meters
-- Match by project_id + meter name derived from product_desc
UPDATE contract_line cl
SET meter_id = m.id
FROM contract c, project p, meter m
WHERE cl.contract_id = c.id
  AND c.project_id = p.id
  AND m.project_id = p.id
  AND cl.organization_id = 1
  AND cl.is_active = true
  AND cl.energy_category IN ('metered', 'available')
  AND cl.meter_id IS NULL
  AND m.name = COALESCE(
      CASE
          WHEN cl.product_desc LIKE '% - %'
          THEN substring(cl.product_desc FROM ' - (.+)$')
          ELSE cl.product_desc
      END,
      'Main Meter'
  );

COMMIT;
