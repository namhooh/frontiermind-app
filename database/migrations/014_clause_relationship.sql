-- =====================================================
-- MIGRATION 014: Clause Relationship & Event Enhancements
-- =====================================================
-- Implements Power Purchase Ontology Framework:
-- 1. clause_relationship table - defines explicit relationships between clauses
-- 2. Event table enhancements for verification
-- 3. Additional event types for excuse tracking
--
-- Relationship types:
--   TRIGGERS - Obligation breach causes consequence (availability breach -> LD)
--   EXCUSES  - Event excuses obligation (force majeure -> availability)
--   GOVERNS  - Sets context for other clauses (CP -> all obligations)
--   INPUTS   - Data flows between clauses (pricing -> payment)
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: Create relationship_type ENUM
-- =====================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'relationship_type') THEN
        CREATE TYPE relationship_type AS ENUM ('TRIGGERS', 'EXCUSES', 'GOVERNS', 'INPUTS');
    END IF;
END$$;

-- =====================================================
-- Step 2: Create clause_relationship table
-- =====================================================

CREATE TABLE IF NOT EXISTS clause_relationship (
    id BIGSERIAL PRIMARY KEY,
    source_clause_id BIGINT NOT NULL REFERENCES clause(id) ON DELETE CASCADE,
    target_clause_id BIGINT NOT NULL REFERENCES clause(id) ON DELETE CASCADE,
    relationship_type relationship_type NOT NULL,
    is_cross_contract BOOLEAN NOT NULL DEFAULT FALSE,
    parameters JSONB DEFAULT '{}',
    is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
    confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    inferred_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    CONSTRAINT uq_clause_relationship UNIQUE (source_clause_id, target_clause_id, relationship_type)
);

-- Indexes for clause_relationship
CREATE INDEX IF NOT EXISTS idx_clause_rel_source ON clause_relationship(source_clause_id);
CREATE INDEX IF NOT EXISTS idx_clause_rel_target ON clause_relationship(target_clause_id);
CREATE INDEX IF NOT EXISTS idx_clause_rel_type ON clause_relationship(relationship_type);
CREATE INDEX IF NOT EXISTS idx_clause_rel_cross ON clause_relationship(is_cross_contract) WHERE is_cross_contract = TRUE;
CREATE INDEX IF NOT EXISTS idx_clause_rel_inferred ON clause_relationship(is_inferred) WHERE is_inferred = TRUE;

-- Comments
COMMENT ON TABLE clause_relationship IS 'Explicit relationships between clauses. This IS the ontology layer that defines how clauses interact.';
COMMENT ON COLUMN clause_relationship.source_clause_id IS 'The clause that initiates the relationship';
COMMENT ON COLUMN clause_relationship.target_clause_id IS 'The clause that is affected by the relationship';
COMMENT ON COLUMN clause_relationship.relationship_type IS 'TRIGGERS=causes action, EXCUSES=negates obligation, GOVERNS=sets context, INPUTS=provides data';
COMMENT ON COLUMN clause_relationship.is_cross_contract IS 'TRUE if relationship spans multiple contracts (e.g., O&M maintenance -> PPA availability)';
COMMENT ON COLUMN clause_relationship.parameters IS 'Relationship-specific parameters (e.g., {condition: "scheduled", limit_hours: 100})';
COMMENT ON COLUMN clause_relationship.is_inferred IS 'TRUE if relationship was auto-detected, FALSE if explicitly defined';
COMMENT ON COLUMN clause_relationship.confidence IS 'Confidence score for inferred relationships (0.0-1.0)';
COMMENT ON COLUMN clause_relationship.inferred_by IS 'Source of inference: pattern_matcher, claude_extraction, human';

-- =====================================================
-- Step 3: Add verification columns to event table
-- =====================================================

ALTER TABLE event
    ADD COLUMN IF NOT EXISTS contract_id BIGINT REFERENCES contract(id),
    ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verified_by UUID,
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_event_contract ON event(contract_id) WHERE contract_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_event_verified ON event(verified) WHERE verified = TRUE;

COMMENT ON COLUMN event.contract_id IS 'Optional contract reference for contract-specific events';
COMMENT ON COLUMN event.verified IS 'Whether event has been verified for excuse purposes';
COMMENT ON COLUMN event.verified_by IS 'User who verified the event';
COMMENT ON COLUMN event.verified_at IS 'Timestamp when event was verified';

-- Add unique constraint on event_type.code (required for ON CONFLICT)                                                               
 ALTER TABLE event_type ADD CONSTRAINT uq_event_type_code UNIQUE (code);    

-- =====================================================
-- Step 4: Seed additional event types for excuse tracking
-- =====================================================

INSERT INTO event_type (name, code, description, created_at) VALUES
('Force Majeure', 'FORCE_MAJEURE', 'Act of God, war, natural disaster - typically excuses obligations', NOW()),
('Scheduled Maintenance', 'SCHEDULED_MAINT', 'Planned maintenance outage - may excuse availability', NOW()),
('Grid Curtailment', 'GRID_CURTAIL', 'Utility-ordered output reduction - typically excuses availability', NOW()),
('Unscheduled Maintenance', 'UNSCHED_MAINT', 'Emergency repairs - may or may not excuse', NOW()),
('Weather Event', 'WEATHER', 'Extreme weather affecting performance', NOW()),
('Permit Delay', 'PERMIT_DELAY', 'Regulatory delay affecting conditions precedent', NOW()),
('Equipment Failure', 'EQUIP_FAILURE', 'Equipment malfunction or breakdown', NOW()),
('Grid Outage', 'GRID_OUTAGE', 'Grid unavailability not caused by plant', NOW())
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description;

-- =====================================================
-- Step 5: Helper functions for relationship queries
-- =====================================================

-- Get all clauses that excuse a given clause
CREATE OR REPLACE FUNCTION get_excuses_for_clause(
    p_clause_id BIGINT
) RETURNS TABLE (
    source_clause_id BIGINT,
    source_clause_name VARCHAR,
    source_category_code VARCHAR,
    relationship_type relationship_type,
    confidence NUMERIC,
    parameters JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cr.source_clause_id,
        c.name AS source_clause_name,
        cc.code AS source_category_code,
        cr.relationship_type,
        cr.confidence,
        cr.parameters
    FROM clause_relationship cr
    JOIN clause c ON c.id = cr.source_clause_id
    LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
    WHERE cr.target_clause_id = p_clause_id
      AND cr.relationship_type = 'EXCUSES';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_excuses_for_clause IS 'Returns all clauses/categories that can excuse the given clause';

-- Get all clauses triggered by a given clause
CREATE OR REPLACE FUNCTION get_triggers_for_clause(
    p_clause_id BIGINT
) RETURNS TABLE (
    target_clause_id BIGINT,
    target_clause_name VARCHAR,
    target_category_code VARCHAR,
    relationship_type relationship_type,
    confidence NUMERIC,
    parameters JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cr.target_clause_id,
        c.name AS target_clause_name,
        cc.code AS target_category_code,
        cr.relationship_type,
        cr.confidence,
        cr.parameters
    FROM clause_relationship cr
    JOIN clause c ON c.id = cr.target_clause_id
    LEFT JOIN clause_category cc ON cc.id = c.clause_category_id
    WHERE cr.source_clause_id = p_clause_id
      AND cr.relationship_type = 'TRIGGERS';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_triggers_for_clause IS 'Returns all clauses/consequences triggered by breach of the given clause';

-- Get relationship graph for a contract
CREATE OR REPLACE FUNCTION get_contract_relationship_graph(
    p_contract_id BIGINT
) RETURNS TABLE (
    source_clause_id BIGINT,
    source_name VARCHAR,
    source_category VARCHAR,
    target_clause_id BIGINT,
    target_name VARCHAR,
    target_category VARCHAR,
    relationship_type relationship_type,
    is_cross_contract BOOLEAN,
    confidence NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cr.source_clause_id,
        sc.name AS source_name,
        scc.code AS source_category,
        cr.target_clause_id,
        tc.name AS target_name,
        tcc.code AS target_category,
        cr.relationship_type,
        cr.is_cross_contract,
        cr.confidence
    FROM clause_relationship cr
    JOIN clause sc ON sc.id = cr.source_clause_id
    JOIN clause tc ON tc.id = cr.target_clause_id
    LEFT JOIN clause_category scc ON scc.id = sc.clause_category_id
    LEFT JOIN clause_category tcc ON tcc.id = tc.clause_category_id
    WHERE sc.contract_id = p_contract_id
       OR tc.contract_id = p_contract_id
    ORDER BY cr.relationship_type, sc.name;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_contract_relationship_graph IS 'Returns all clause relationships for a contract (including cross-contract)';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
    table_exists BOOLEAN;
    enum_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'clause_relationship'
    ) INTO table_exists;

    SELECT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'relationship_type'
    ) INTO enum_exists;

    IF table_exists AND enum_exists THEN
        RAISE NOTICE 'Migration 014 successful: clause_relationship table and relationship_type enum created';
    ELSE
        RAISE WARNING 'Migration 014 may have issues: table_exists=%, enum_exists=%', table_exists, enum_exists;
    END IF;
END $$;

COMMIT;

-- Display created objects
SELECT 'clause_relationship columns:' AS info;
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'clause_relationship'
ORDER BY ordinal_position;

SELECT 'event_type count (should include new excuse types):' AS info;
SELECT COUNT(*) AS count FROM event_type;
