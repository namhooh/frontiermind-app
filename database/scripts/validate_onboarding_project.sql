-- =============================================================================
-- validate_onboarding_project.sql
-- Reusable onboarding validation query pack
--
-- Usage examples:
--   psql "$DATABASE_URL" -f database/scripts/validate_onboarding_project.sql
--   psql "$DATABASE_URL" \
--     -v external_project_id=GH-MOH01 \
--     -v expected_forecast_rows=12 \
--     -v expected_guarantee_rows=20 \
--     -v expected_meter_rows=5 \
--     -f database/scripts/validate_onboarding_project.sql
-- =============================================================================

\if :{?external_project_id}
\else
\set external_project_id GH-MOH01
\endif

\if :{?expected_forecast_rows}
\else
\set expected_forecast_rows 12
\endif

\if :{?expected_guarantee_rows}
\else
\set expected_guarantee_rows 20
\endif

\if :{?expected_meter_rows}
\else
\set expected_meter_rows 1
\endif

\echo
\echo Validating onboarding for external_project_id=:external_project_id
\echo

-- -----------------------------------------------------------------------------
-- 1) Core entity and row-count checks
-- -----------------------------------------------------------------------------
WITH ctx AS (
  SELECT p.id AS project_id
  FROM project p
  WHERE p.external_project_id = :'external_project_id'
  LIMIT 1
)
SELECT *
FROM (
  SELECT
    'core'::text AS check_group,
    'project_exists'::text AS check_name,
    CASE WHEN EXISTS (SELECT 1 FROM ctx) THEN 'PASS' ELSE 'FAIL' END AS status,
    (SELECT COUNT(*)::text FROM ctx) AS actual,
    '1'::text AS expected,
    'Project row must exist for external_project_id'::text AS details

  UNION ALL

  SELECT
    'core',
    'contract_exists',
    CASE
      WHEN (SELECT COUNT(*) FROM contract c WHERE c.project_id IN (SELECT project_id FROM ctx)) >= 1 THEN 'PASS'
      ELSE 'FAIL'
    END,
    (SELECT COUNT(*)::text FROM contract c WHERE c.project_id IN (SELECT project_id FROM ctx)),
    '>=1',
    'At least one contract must exist'

  UNION ALL

  SELECT
    'core',
    'tariff_exists',
    CASE
      WHEN (SELECT COUNT(*) FROM clause_tariff ct WHERE ct.project_id IN (SELECT project_id FROM ctx) AND ct.is_current IS TRUE) >= 1 THEN 'PASS'
      ELSE 'FAIL'
    END,
    (SELECT COUNT(*)::text FROM clause_tariff ct WHERE ct.project_id IN (SELECT project_id FROM ctx) AND ct.is_current IS TRUE),
    '>=1',
    'At least one current tariff row must exist'

  UNION ALL

  SELECT
    'core',
    'forecast_count',
    CASE
      WHEN (SELECT COUNT(*) FROM production_forecast pf WHERE pf.project_id IN (SELECT project_id FROM ctx)) = :expected_forecast_rows THEN 'PASS'
      ELSE 'FAIL'
    END,
    (SELECT COUNT(*)::text FROM production_forecast pf WHERE pf.project_id IN (SELECT project_id FROM ctx)),
    :expected_forecast_rows::text,
    'Monthly forecast row count'

  UNION ALL

  SELECT
    'core',
    'guarantee_count',
    CASE
      WHEN (SELECT COUNT(*) FROM production_guarantee pg WHERE pg.project_id IN (SELECT project_id FROM ctx)) = :expected_guarantee_rows THEN 'PASS'
      ELSE 'FAIL'
    END,
    (SELECT COUNT(*)::text FROM production_guarantee pg WHERE pg.project_id IN (SELECT project_id FROM ctx)),
    :expected_guarantee_rows::text,
    'Operating-year guarantee row count'

  UNION ALL

  SELECT
    'core',
    'meter_count',
    CASE
      WHEN (SELECT COUNT(*) FROM meter m WHERE m.project_id IN (SELECT project_id FROM ctx)) >= :expected_meter_rows THEN 'PASS'
      ELSE 'FAIL'
    END,
    (SELECT COUNT(*)::text FROM meter m WHERE m.project_id IN (SELECT project_id FROM ctx)),
    '>=' || :expected_meter_rows::text,
    'Billing meter count'

  UNION ALL

  SELECT
    'core',
    'asset_count',
    CASE
      WHEN (SELECT COUNT(*) FROM asset a WHERE a.project_id IN (SELECT project_id FROM ctx)) >= 1 THEN 'PASS'
      ELSE 'WARN'
    END,
    (SELECT COUNT(*)::text FROM asset a WHERE a.project_id IN (SELECT project_id FROM ctx)),
    '>=1',
    'At least one asset row expected from technical onboarding'

  UNION ALL

  SELECT
    'core',
    'contact_count',
    CASE
      WHEN (
        SELECT COUNT(*)
        FROM customer_contact cc
        JOIN contract c ON c.counterparty_id = cc.counterparty_id
        WHERE c.project_id IN (SELECT project_id FROM ctx)
      ) >= 1 THEN 'PASS'
      ELSE 'WARN'
    END,
    (
      SELECT COUNT(*)::text
      FROM customer_contact cc
      JOIN contract c ON c.counterparty_id = cc.counterparty_id
      WHERE c.project_id IN (SELECT project_id FROM ctx)
    ),
    '>=1',
    'Customer billing/escalation contacts'
) checks
ORDER BY
  CASE checks.status WHEN 'FAIL' THEN 1 WHEN 'WARN' THEN 2 ELSE 3 END,
  checks.check_group,
  checks.check_name;

-- -----------------------------------------------------------------------------
-- 2) Critical null/missing-field checks
-- -----------------------------------------------------------------------------
WITH ctx AS (
  SELECT p.id AS project_id
  FROM project p
  WHERE p.external_project_id = :'external_project_id'
  LIMIT 1
),
proj AS (
  SELECT p.*
  FROM project p
  JOIN ctx ON ctx.project_id = p.id
),
con AS (
  SELECT c.*
  FROM contract c
  JOIN ctx ON ctx.project_id = c.project_id
  ORDER BY c.id DESC
  LIMIT 1
),
cp AS (
  SELECT cp.*
  FROM counterparty cp
  JOIN con ON con.counterparty_id = cp.id
  LIMIT 1
),
tariff AS (
  SELECT ct.*
  FROM clause_tariff ct
  JOIN ctx ON ctx.project_id = ct.project_id
  WHERE ct.is_current IS TRUE
  ORDER BY ct.id DESC
  LIMIT 1
)
SELECT *
FROM (
  SELECT
    'fields'::text AS check_group,
    'project.cod_date'::text AS field_name,
    CASE WHEN (SELECT cod_date FROM proj) IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS status,
    COALESCE((SELECT cod_date::text FROM proj), 'NULL') AS actual,
    'non-null'::text AS expected

  UNION ALL

  SELECT
    'fields',
    'project.installed_dc_capacity_kwp',
    CASE WHEN (SELECT installed_dc_capacity_kwp FROM proj) IS NOT NULL THEN 'PASS' ELSE 'FAIL' END,
    COALESCE((SELECT installed_dc_capacity_kwp::text FROM proj), 'NULL'),
    'non-null'

  UNION ALL

  SELECT
    'fields',
    'project.installed_ac_capacity_kw',
    CASE WHEN (SELECT installed_ac_capacity_kw FROM proj) IS NOT NULL THEN 'PASS' ELSE 'FAIL' END,
    COALESCE((SELECT installed_ac_capacity_kw::text FROM proj), 'NULL'),
    'non-null'

  UNION ALL

  SELECT
    'fields',
    'contract.contract_term_years',
    CASE WHEN (SELECT contract_term_years FROM con) IS NOT NULL THEN 'PASS' ELSE 'WARN' END,
    COALESCE((SELECT contract_term_years::text FROM con), 'NULL'),
    'non-null'

  UNION ALL

  SELECT
    'fields',
    'contract.payment_security_details',
    CASE
      WHEN (SELECT payment_security_required FROM con) IS TRUE
       AND COALESCE(NULLIF((SELECT payment_security_details FROM con), ''), NULL) IS NULL THEN 'FAIL'
      WHEN (SELECT payment_security_required FROM con) IS TRUE THEN 'PASS'
      ELSE 'WARN'
    END,
    COALESCE((SELECT payment_security_details FROM con), 'NULL'),
    'required when payment_security_required=true'

  UNION ALL

  SELECT
    'fields',
    'counterparty.name',
    CASE
      WHEN LOWER(COALESCE((SELECT name FROM cp), '')) = 'unknown customer' OR (SELECT name FROM cp) IS NULL THEN 'FAIL'
      ELSE 'PASS'
    END,
    COALESCE((SELECT name FROM cp), 'NULL'),
    'non-placeholder legal customer name'

  UNION ALL

  SELECT
    'fields',
    'tariff.logic_parameters.discount_pct',
    CASE
      WHEN COALESCE(NULLIF((SELECT logic_parameters->>'discount_pct' FROM tariff), ''), NULL) IS NOT NULL THEN 'PASS'
      ELSE 'WARN'
    END,
    COALESCE((SELECT logic_parameters->>'discount_pct' FROM tariff), 'NULL'),
    'present for discount-to-reference contracts'

  UNION ALL

  SELECT
    'fields',
    'tariff.logic_parameters.floor_rate',
    CASE
      WHEN COALESCE(NULLIF((SELECT logic_parameters->>'floor_rate' FROM tariff), ''), NULL) IS NOT NULL THEN 'PASS'
      ELSE 'WARN'
    END,
    COALESCE((SELECT logic_parameters->>'floor_rate' FROM tariff), 'NULL'),
    'present when floor/ceiling clauses apply'

  UNION ALL

  SELECT
    'fields',
    'tariff.logic_parameters.ceiling_rate',
    CASE
      WHEN COALESCE(NULLIF((SELECT logic_parameters->>'ceiling_rate' FROM tariff), ''), NULL) IS NOT NULL THEN 'PASS'
      ELSE 'WARN'
    END,
    COALESCE((SELECT logic_parameters->>'ceiling_rate' FROM tariff), 'NULL'),
    'present when floor/ceiling clauses apply'

  UNION ALL

  SELECT
    'fields',
    'production_guarantee.shortfall_cap_usd',
    CASE
      WHEN (
        SELECT COUNT(*)
        FROM production_guarantee pg
        JOIN ctx ON ctx.project_id = pg.project_id
        WHERE pg.shortfall_cap_usd IS NOT NULL
      ) = :expected_guarantee_rows THEN 'PASS'
      ELSE 'WARN'
    END,
    (
      SELECT COUNT(*)::text
      FROM production_guarantee pg
      JOIN ctx ON ctx.project_id = pg.project_id
      WHERE pg.shortfall_cap_usd IS NOT NULL
    ),
    :expected_guarantee_rows::text || ' rows populated'

  UNION ALL

  SELECT
    'fields',
    'meter.location_description',
    CASE
      WHEN (
        SELECT COUNT(*)
        FROM meter m
        JOIN ctx ON ctx.project_id = m.project_id
        WHERE COALESCE(NULLIF(m.location_description, ''), NULL) IS NOT NULL
      ) >= :expected_meter_rows THEN 'PASS'
      ELSE 'WARN'
    END,
    (
      SELECT COUNT(*)::text
      FROM meter m
      JOIN ctx ON ctx.project_id = m.project_id
      WHERE COALESCE(NULLIF(m.location_description, ''), NULL) IS NOT NULL
    ),
    '>=' || :expected_meter_rows::text || ' rows populated'
) field_checks
ORDER BY
  CASE field_checks.status WHEN 'FAIL' THEN 1 WHEN 'WARN' THEN 2 ELSE 3 END,
  field_checks.field_name;

-- -----------------------------------------------------------------------------
-- 3) Data quality checks
-- -----------------------------------------------------------------------------
WITH ctx AS (
  SELECT p.id AS project_id
  FROM project p
  WHERE p.external_project_id = :'external_project_id'
  LIMIT 1
),
guarantee_series AS (
  SELECT
    pg.operating_year,
    pg.guaranteed_kwh,
    LAG(pg.guaranteed_kwh) OVER (ORDER BY pg.operating_year) AS prev_guaranteed_kwh
  FROM production_guarantee pg
  JOIN ctx ON ctx.project_id = pg.project_id
)
SELECT *
FROM (
  SELECT
    'quality'::text AS check_group,
    'guarantee_monotonic_non_increasing'::text AS check_name,
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM guarantee_series
        WHERE prev_guaranteed_kwh IS NOT NULL
          AND guaranteed_kwh > prev_guaranteed_kwh
      ) THEN 'FAIL'
      ELSE 'PASS'
    END AS status,
    (
      SELECT COUNT(*)::text
      FROM guarantee_series
      WHERE prev_guaranteed_kwh IS NOT NULL
        AND guaranteed_kwh > prev_guaranteed_kwh
    ) AS actual,
    '0'::text AS expected,
    'Any increasing year-over-year guarantee indicates bad degradation schedule'::text AS details

  UNION ALL

  SELECT
    'quality',
    'tariff_floor_lte_ceiling',
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM clause_tariff ct
        JOIN ctx ON ctx.project_id = ct.project_id
        WHERE ct.is_current IS TRUE
          AND ct.logic_parameters ? 'floor_rate'
          AND ct.logic_parameters ? 'ceiling_rate'
          AND (ct.logic_parameters->>'floor_rate')::numeric > (ct.logic_parameters->>'ceiling_rate')::numeric
      ) THEN 'FAIL'
      ELSE 'PASS'
    END,
    (
      SELECT COUNT(*)::text
      FROM clause_tariff ct
      JOIN ctx ON ctx.project_id = ct.project_id
      WHERE ct.is_current IS TRUE
        AND ct.logic_parameters ? 'floor_rate'
        AND ct.logic_parameters ? 'ceiling_rate'
        AND (ct.logic_parameters->>'floor_rate')::numeric > (ct.logic_parameters->>'ceiling_rate')::numeric
    ),
    '0',
    'Floor cannot exceed ceiling'

  UNION ALL

  SELECT
    'quality',
    'forecast_source_metadata_nonempty',
    CASE
      WHEN (
        SELECT COUNT(*)
        FROM production_forecast pf
        JOIN ctx ON ctx.project_id = pf.project_id
        WHERE COALESCE(pf.source_metadata, '{}'::jsonb) = '{}'::jsonb
      ) > 0 THEN 'WARN'
      ELSE 'PASS'
    END,
    (
      SELECT COUNT(*)::text
      FROM production_forecast pf
      JOIN ctx ON ctx.project_id = pf.project_id
      WHERE COALESCE(pf.source_metadata, '{}'::jsonb) = '{}'::jsonb
    ),
    '0',
    'Empty source_metadata reduces auditability'
) quality_checks
ORDER BY
  CASE quality_checks.status WHEN 'FAIL' THEN 1 WHEN 'WARN' THEN 2 ELSE 3 END,
  quality_checks.check_name;

-- -----------------------------------------------------------------------------
-- 4) Snapshot output (for human review)
-- -----------------------------------------------------------------------------
SELECT
  p.id AS project_id,
  p.external_project_id,
  p.name,
  p.country,
  p.cod_date,
  p.installed_dc_capacity_kwp,
  p.installed_ac_capacity_kw
FROM project p
WHERE p.external_project_id = :'external_project_id';

SELECT
  c.id AS contract_id,
  c.external_contract_id,
  c.name,
  c.contract_term_years,
  c.effective_date,
  c.end_date,
  c.payment_security_required,
  c.payment_security_details
FROM contract c
JOIN project p ON p.id = c.project_id
WHERE p.external_project_id = :'external_project_id'
ORDER BY c.id;

SELECT
  ct.id AS tariff_id,
  ct.tariff_group_key,
  ct.base_rate,
  ct.unit,
  tst.code AS tariff_structure,
  est.code AS energy_sale_type,
  esc.code AS escalation_type,
  bc.code AS billing_currency,
  mrc.code AS market_ref_currency,
  ct.logic_parameters
FROM clause_tariff ct
JOIN project p ON p.id = ct.project_id
LEFT JOIN tariff_structure_type tst ON tst.id = ct.tariff_structure_id
LEFT JOIN energy_sale_type est ON est.id = ct.energy_sale_type_id
LEFT JOIN escalation_type esc ON esc.id = ct.escalation_type_id
LEFT JOIN currency bc ON bc.id = ct.currency_id
LEFT JOIN currency mrc ON mrc.id = ct.market_ref_currency_id
WHERE p.external_project_id = :'external_project_id'
  AND ct.is_current IS TRUE
ORDER BY ct.id;

SELECT
  pg.operating_year,
  pg.p50_annual_kwh,
  pg.guaranteed_kwh,
  pg.guarantee_pct_of_p50,
  pg.shortfall_cap_usd,
  pg.shortfall_cap_fx_rule
FROM production_guarantee pg
JOIN project p ON p.id = pg.project_id
WHERE p.external_project_id = :'external_project_id'
ORDER BY pg.operating_year;

SELECT
  m.id,
  m.serial_number,
  m.location_description,
  m.metering_type,
  m.model,
  m.meter_type_id
FROM meter m
JOIN project p ON p.id = m.project_id
WHERE p.external_project_id = :'external_project_id'
ORDER BY m.id;
