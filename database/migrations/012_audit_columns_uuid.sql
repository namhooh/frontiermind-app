-- =====================================================
-- MIGRATION 012: Standardize Audit Columns to UUID FK
-- =====================================================
-- Migrates created_by/updated_by from VARCHAR to UUID
-- with FK reference to auth.users(id) for consistency
-- with Supabase Auth integration.
--
-- Affected tables:
-- - contract (updated_by)
-- - clause (updated_by)
-- - event (created_by, updated_by)
-- - default_event (created_by, updated_by)
-- - rule_output (created_by, updated_by)
--
-- Note: Existing VARCHAR data will be dropped as it
-- cannot be automatically mapped to auth.users UUIDs.
-- =====================================================

BEGIN;

-- =====================================================
-- Step 1: contract table
-- =====================================================

ALTER TABLE contract DROP COLUMN IF EXISTS updated_by;
ALTER TABLE contract ADD COLUMN updated_by UUID REFERENCES auth.users(id);

-- =====================================================
-- Step 2: clause table
-- =====================================================

ALTER TABLE clause DROP COLUMN IF EXISTS updated_by;
ALTER TABLE clause ADD COLUMN updated_by UUID REFERENCES auth.users(id);

-- =====================================================
-- Step 3: event table
-- =====================================================

ALTER TABLE event DROP COLUMN IF EXISTS created_by;
ALTER TABLE event DROP COLUMN IF EXISTS updated_by;
ALTER TABLE event ADD COLUMN created_by UUID REFERENCES auth.users(id);
ALTER TABLE event ADD COLUMN updated_by UUID REFERENCES auth.users(id);

-- =====================================================
-- Step 4: default_event table
-- =====================================================

ALTER TABLE default_event DROP COLUMN IF EXISTS created_by;
ALTER TABLE default_event DROP COLUMN IF EXISTS updated_by;
ALTER TABLE default_event ADD COLUMN created_by UUID REFERENCES auth.users(id);
ALTER TABLE default_event ADD COLUMN updated_by UUID REFERENCES auth.users(id);

-- =====================================================
-- Step 5: rule_output table
-- =====================================================

ALTER TABLE rule_output DROP COLUMN IF EXISTS created_by;
ALTER TABLE rule_output DROP COLUMN IF EXISTS updated_by;
ALTER TABLE rule_output ADD COLUMN created_by UUID REFERENCES auth.users(id);
ALTER TABLE rule_output ADD COLUMN updated_by UUID REFERENCES auth.users(id);

-- =====================================================
-- Step 6: Add comments
-- =====================================================

COMMENT ON COLUMN contract.updated_by IS 'UUID of auth.users who last updated this record';
COMMENT ON COLUMN clause.updated_by IS 'UUID of auth.users who last updated this record';
COMMENT ON COLUMN event.created_by IS 'UUID of auth.users who created this record';
COMMENT ON COLUMN event.updated_by IS 'UUID of auth.users who last updated this record';
COMMENT ON COLUMN default_event.created_by IS 'UUID of auth.users who created this record';
COMMENT ON COLUMN default_event.updated_by IS 'UUID of auth.users who last updated this record';
COMMENT ON COLUMN rule_output.created_by IS 'UUID of auth.users who created this record';
COMMENT ON COLUMN rule_output.updated_by IS 'UUID of auth.users who last updated this record';

-- =====================================================
-- Verification
-- =====================================================

DO $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    -- Check contract.updated_by
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_name = 'contract' AND column_name = 'updated_by' AND data_type = 'uuid';
    IF v_count = 1 THEN
        RAISE NOTICE 'contract.updated_by migrated to UUID';
    END IF;

    -- Check clause.updated_by
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_name = 'clause' AND column_name = 'updated_by' AND data_type = 'uuid';
    IF v_count = 1 THEN
        RAISE NOTICE 'clause.updated_by migrated to UUID';
    END IF;

    -- Check event columns
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_name = 'event' AND column_name IN ('created_by', 'updated_by') AND data_type = 'uuid';
    IF v_count = 2 THEN
        RAISE NOTICE 'event.created_by/updated_by migrated to UUID';
    END IF;

    -- Check default_event columns
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_name = 'default_event' AND column_name IN ('created_by', 'updated_by') AND data_type = 'uuid';
    IF v_count = 2 THEN
        RAISE NOTICE 'default_event.created_by/updated_by migrated to UUID';
    END IF;

    -- Check rule_output columns
    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_name = 'rule_output' AND column_name IN ('created_by', 'updated_by') AND data_type = 'uuid';
    IF v_count = 2 THEN
        RAISE NOTICE 'rule_output.created_by/updated_by migrated to UUID';
    END IF;

    RAISE NOTICE 'Migration 012 completed: Audit columns standardized to UUID FK';
END $$;

COMMIT;
