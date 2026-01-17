-- NOT IMPLEMENTED YET
-- NOT IMPLEMENTED YET
-- NOT IMPLEMENTED YET
-- =====================================================
-- Migration: 013_seed_snowflake_datasource.sql
-- Purpose: Add Snowflake and Manual Upload data sources for Phase 4 integration
--
-- This migration adds data_source entries for:
-- - Snowflake (ID 5): Client Snowflake data warehouse integrations
-- - Manual Upload (ID 6): Direct file uploads via presigned URL
-- =====================================================
-- Insert Snowflake data source
-- Used for enterprise clients pushing data from their Snowflake warehouses
INSERT INTO
    data_source (id, name, description, updated_frequency)
VALUES
    (
        5,
        'Snowflake',
        'Client Snowflake data warehouse integration',
        'hourly'
    ) ON CONFLICT (id) DO
UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_frequency = EXCLUDED.updated_frequency;

-- Insert Manual Upload data source
-- Used for direct file uploads via the presigned URL API
INSERT INTO
    data_source (id, name, description, updated_frequency)
VALUES
    (
        6,
        'Manual Upload',
        'Manual file uploads via API',
        'daily'
    ) ON CONFLICT (id) DO
UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_frequency = EXCLUDED.updated_frequency;

-- Insert SolarEdge data source (for completeness with fetcher integrations)
INSERT INTO
    data_source (id, name, description, updated_frequency)
VALUES
    (
        7,
        'SolarEdge',
        'SolarEdge Monitoring API integration',
        '15min'
    ) ON CONFLICT (id) DO
UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_frequency = EXCLUDED.updated_frequency;

-- Insert Enphase data source
INSERT INTO
    data_source (id, name, description, updated_frequency)
VALUES
    (
        8,
        'Enphase',
        'Enphase Enlighten API integration',
        '15min'
    ) ON CONFLICT (id) DO
UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_frequency = EXCLUDED.updated_frequency;

-- Insert GoodWe data source
INSERT INTO
    data_source (id, name, description, updated_frequency)
VALUES
    (
        9,
        'GoodWe',
        'GoodWe SEMS API integration',
        '15min'
    ) ON CONFLICT (id) DO
UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_frequency = EXCLUDED.updated_frequency;

-- Insert SMA data source
INSERT INTO
    data_source (id, name, description, updated_frequency)
VALUES
    (
        10,
        'SMA',
        'SMA Sunny Portal API integration',
        '15min'
    ) ON CONFLICT (id) DO
UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_frequency = EXCLUDED.updated_frequency;

-- Verify insertion
DO $ $ DECLARE snowflake_exists BOOLEAN;

manual_exists BOOLEAN;

BEGIN
SELECT
    EXISTS(
        SELECT
            1
        FROM
            data_source
        WHERE
            id = 5
            AND name = 'Snowflake'
    ) INTO snowflake_exists;

SELECT
    EXISTS(
        SELECT
            1
        FROM
            data_source
        WHERE
            id = 6
            AND name = 'Manual Upload'
    ) INTO manual_exists;

IF NOT snowflake_exists THEN RAISE EXCEPTION 'Failed to insert Snowflake data source';

END IF;

IF NOT manual_exists THEN RAISE EXCEPTION 'Failed to insert Manual Upload data source';

END IF;

RAISE NOTICE 'Successfully seeded data sources: Snowflake (5), Manual Upload (6), SolarEdge (7), Enphase (8), GoodWe (9), SMA (10)';

END $ $;

-- =====================================================
-- Comments
-- =====================================================
COMMENT ON TABLE data_source IS 'Reference table for all supported data source integrations';

-- =====================================================
-- DOWN Migration (for rollback)
-- =====================================================
-- To rollback:
-- DELETE FROM data_source WHERE id IN (5, 6, 7, 8, 9, 10);