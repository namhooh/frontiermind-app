-- =====================================================
-- MIGRATION 023: Simplify Obligation View (Canonical Ontology)
-- =====================================================
-- Simplifies the obligation_view COALESCE chains to prefer canonical
-- field names from the ontology layer, with minimal legacy fallbacks.
--
-- Before: 6-way COALESCE for threshold_value
-- After:  2-way COALESCE (canonical 'threshold' + legacy 'threshold_percent')
--
-- Legacy aliases remain as fallbacks for clauses extracted before this update.
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Drop dependent views first (reverse dependency order)
-- =====================================================

DROP VIEW IF EXISTS obligation_with_relationships;
DROP VIEW IF EXISTS obligation_view;

-- =====================================================
-- Step 2: Recreate obligation_view with simplified COALESCE
-- =====================================================

CREATE VIEW obligation_view AS
SELECT
    c.id AS clause_id,
    c.contract_id,
    c.project_id,
    con.name AS contract_name,
    cc.code AS category_code,
    cc.name AS category_name,
    c.name AS clause_name,
    c.section_ref,

    -- Metric: What is being measured
    CASE
        WHEN cc.code = 'AVAILABILITY' THEN 'availability_percent'
        WHEN cc.code = 'PERFORMANCE_GUARANTEE' THEN 'performance_ratio_percent'
        WHEN cc.code = 'PAYMENT_TERMS' THEN 'payment_amount'
        WHEN cc.code = 'MAINTENANCE' THEN 'response_time_hours'
        WHEN cc.code = 'COMPLIANCE' THEN 'compliance_status'
        WHEN cc.code = 'SECURITY_PACKAGE' THEN 'security_amount'
        ELSE COALESCE(c.normalized_payload->>'metric', 'unknown')
    END AS metric,

    -- Threshold: Canonical 'threshold' preferred, legacy 'threshold_percent' as fallback
    COALESCE(
        (c.normalized_payload->>'threshold')::NUMERIC,
        (c.normalized_payload->>'threshold_percent')::NUMERIC
    ) AS threshold_value,

    -- Comparison operator
    COALESCE(
        c.normalized_payload->>'comparison_operator',
        '>='
    ) AS comparison_operator,

    -- Evaluation period
    COALESCE(
        c.normalized_payload->>'measurement_period',
        c.normalized_payload->>'invoice_frequency',
        'annual'
    ) AS evaluation_period,

    -- Rate value: Canonical 'base_rate_per_kwh' preferred, legacy 'rate' as fallback
    COALESCE(
        (c.normalized_payload->>'base_rate_per_kwh')::NUMERIC,
        (c.normalized_payload->>'rate')::NUMERIC
    ) AS rate_value,

    -- Responsible party
    c.clause_responsibleparty_id AS responsible_party_id,
    rp.name AS responsible_party_name,

    -- Beneficiary party
    c.beneficiary_party,

    -- Metadata
    c.confidence_score,
    c.summary,
    c.created_at

FROM clause c
JOIN contract con ON con.id = c.contract_id
JOIN clause_category cc ON cc.id = c.clause_category_id
LEFT JOIN clause_responsibleparty rp ON rp.id = c.clause_responsibleparty_id
WHERE c.normalized_payload IS NOT NULL
  AND cc.code IN (
      'AVAILABILITY',
      'PERFORMANCE_GUARANTEE',
      'PAYMENT_TERMS',
      'MAINTENANCE',
      'COMPLIANCE',
      'SECURITY_PACKAGE',
      'DEFAULT',
      'TERMINATION'
  );

COMMENT ON VIEW obligation_view IS 'Exposes "Must A" obligations using canonical ontology field names. Consequences (TRIGGERS) and excuses (EXCUSES) come from clause_relationship joins.';

-- =====================================================
-- Step 3: Recreate obligation_with_relationships view
-- =====================================================

CREATE VIEW obligation_with_relationships AS
SELECT
    o.*,

    -- Count of excuse relationships
    (SELECT COUNT(*)
     FROM clause_relationship cr
     WHERE cr.target_clause_id = o.clause_id
       AND cr.relationship_type = 'EXCUSES') AS excuse_count,

    -- Count of trigger relationships (what this obligation triggers if breached)
    (SELECT COUNT(*)
     FROM clause_relationship cr
     WHERE cr.source_clause_id = o.clause_id
       AND cr.relationship_type = 'TRIGGERS') AS trigger_count,

    -- Excuse category codes (aggregated)
    (SELECT array_agg(DISTINCT cc.code)
     FROM clause_relationship cr
     JOIN clause c ON c.id = cr.source_clause_id
     JOIN clause_category cc ON cc.id = c.clause_category_id
     WHERE cr.target_clause_id = o.clause_id
       AND cr.relationship_type = 'EXCUSES') AS excuse_categories,

    -- Triggered consequence category codes (aggregated)
    (SELECT array_agg(DISTINCT cc.code)
     FROM clause_relationship cr
     JOIN clause c ON c.id = cr.target_clause_id
     JOIN clause_category cc ON cc.id = c.clause_category_id
     WHERE cr.source_clause_id = o.clause_id
       AND cr.relationship_type = 'TRIGGERS') AS triggered_categories,

    -- LD parameters from triggered LIQUIDATED_DAMAGES clause
    (SELECT jsonb_build_object(
        'ld_clause_id', ld.id,
        'ld_per_point', (ld.normalized_payload->>'ld_per_point')::NUMERIC,
        'ld_cap_annual', (ld.normalized_payload->>'ld_cap_annual')::NUMERIC,
        'ld_currency', ld.normalized_payload->>'ld_currency',
        'calculation_type', ld.normalized_payload->>'calculation_type',
        'cure_period_days', (ld.normalized_payload->>'cure_period_days')::INTEGER
    )
    FROM clause_relationship cr
    JOIN clause ld ON ld.id = cr.target_clause_id
    JOIN clause_category cc ON cc.id = ld.clause_category_id
    WHERE cr.source_clause_id = o.clause_id
      AND cr.relationship_type = 'TRIGGERS'
      AND cc.code = 'LIQUIDATED_DAMAGES'
    LIMIT 1) AS ld_parameters

FROM obligation_view o;

COMMENT ON VIEW obligation_with_relationships IS 'Obligations enriched with relationship summary (excuse/trigger counts and categories)';

-- =====================================================
-- Step 4: Recreate get_obligation_details function
-- =====================================================

DROP FUNCTION IF EXISTS get_obligation_details(BIGINT);

CREATE FUNCTION get_obligation_details(
    p_clause_id BIGINT
) RETURNS TABLE (
    -- Obligation data
    clause_id BIGINT,
    contract_id BIGINT,
    contract_name VARCHAR,
    clause_name VARCHAR,
    category_code VARCHAR,
    metric VARCHAR,
    threshold_value NUMERIC,
    comparison_operator VARCHAR,
    evaluation_period VARCHAR,
    responsible_party VARCHAR,
    beneficiary_party VARCHAR,

    -- Relationships
    excuse_clauses JSONB,
    triggered_clauses JSONB,
    governing_clauses JSONB,
    input_clauses JSONB,

    -- LD parameters
    ld_parameters JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        o.clause_id,
        o.contract_id,
        o.contract_name::VARCHAR,
        o.clause_name::VARCHAR,
        o.category_code::VARCHAR,
        o.metric::VARCHAR,
        o.threshold_value,
        o.comparison_operator::VARCHAR,
        o.evaluation_period::VARCHAR,
        o.responsible_party_name::VARCHAR,
        o.beneficiary_party::VARCHAR,

        -- Excuse relationships
        (SELECT jsonb_agg(jsonb_build_object(
            'clause_id', cr.source_clause_id,
            'clause_name', c.name,
            'category_code', cc.code,
            'confidence', cr.confidence,
            'parameters', cr.parameters
        ))
        FROM clause_relationship cr
        JOIN clause c ON c.id = cr.source_clause_id
        LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
        WHERE cr.target_clause_id = o.clause_id
          AND cr.relationship_type = 'EXCUSES') AS excuse_clauses,

        -- Triggered relationships
        (SELECT jsonb_agg(jsonb_build_object(
            'clause_id', cr.target_clause_id,
            'clause_name', c.name,
            'category_code', cc.code,
            'confidence', cr.confidence,
            'parameters', cr.parameters
        ))
        FROM clause_relationship cr
        JOIN clause c ON c.id = cr.target_clause_id
        LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
        WHERE cr.source_clause_id = o.clause_id
          AND cr.relationship_type = 'TRIGGERS') AS triggered_clauses,

        -- Governing relationships
        (SELECT jsonb_agg(jsonb_build_object(
            'clause_id', cr.source_clause_id,
            'clause_name', c.name,
            'category_code', cc.code,
            'confidence', cr.confidence,
            'parameters', cr.parameters
        ))
        FROM clause_relationship cr
        JOIN clause c ON c.id = cr.source_clause_id
        LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
        WHERE cr.target_clause_id = o.clause_id
          AND cr.relationship_type = 'GOVERNS') AS governing_clauses,

        -- Input relationships
        (SELECT jsonb_agg(jsonb_build_object(
            'clause_id', cr.source_clause_id,
            'clause_name', c.name,
            'category_code', cc.code,
            'confidence', cr.confidence,
            'parameters', cr.parameters
        ))
        FROM clause_relationship cr
        JOIN clause c ON c.id = cr.source_clause_id
        LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
        WHERE cr.target_clause_id = o.clause_id
          AND cr.relationship_type = 'INPUTS') AS input_clauses,

        -- LD parameters from triggered LIQUIDATED_DAMAGES clause
        (SELECT jsonb_build_object(
            'ld_clause_id', ld.id,
            'ld_clause_name', ld.name,
            'ld_per_point', (ld.normalized_payload->>'ld_per_point')::NUMERIC,
            'ld_cap_annual', (ld.normalized_payload->>'ld_cap_annual')::NUMERIC,
            'ld_currency', ld.normalized_payload->>'ld_currency',
            'calculation_type', ld.normalized_payload->>'calculation_type',
            'cure_period_days', (ld.normalized_payload->>'cure_period_days')::INTEGER,
            'confidence', cr.confidence
        )
        FROM clause_relationship cr
        JOIN clause ld ON ld.id = cr.target_clause_id
        JOIN clause_category cc ON cc.id = ld.clause_category_id
        WHERE cr.source_clause_id = o.clause_id
          AND cr.relationship_type = 'TRIGGERS'
          AND cc.code = 'LIQUIDATED_DAMAGES'
        LIMIT 1) AS ld_parameters

    FROM obligation_view o
    WHERE o.clause_id = p_clause_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_obligation_details IS 'Returns full obligation details including all relationship types and LD parameters';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
    view_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'obligation_view'
    ) INTO view_exists;

    IF view_exists THEN
        RAISE NOTICE 'Migration 023 successful: obligation_view recreated with canonical field names';
    ELSE
        RAISE WARNING 'Migration 023 failed: obligation_view not found';
    END IF;
END $$;

COMMIT;
