-- Migration 025: Meter Reading Business-Key Dedup Index
-- Date: 2026-02-11
-- Description: Adds a unique index on business keys to enable row-level
--   deduplication. The existing ON CONFLICT DO NOTHING in the loader
--   had no conflict target (PK uses auto-increment id), so duplicate
--   readings were never detected.
--
-- Pre-migration check: If existing duplicate rows exist, the index
-- creation will fail. Run this query first to identify duplicates:
--
--   SELECT organization_id, reading_timestamp,
--          COALESCE(external_site_id, ''),
--          COALESCE(external_device_id, ''),
--          COUNT(*)
--   FROM meter_reading
--   GROUP BY 1, 2, 3, 4
--   HAVING COUNT(*) > 1;
--
-- If duplicates exist, deduplicate before running this migration:
--
--   DELETE FROM meter_reading a
--   USING meter_reading b
--   WHERE a.id > b.id
--     AND a.organization_id = b.organization_id
--     AND a.reading_timestamp = b.reading_timestamp
--     AND COALESCE(a.external_site_id, '') = COALESCE(b.external_site_id, '')
--     AND COALESCE(a.external_device_id, '') = COALESCE(b.external_device_id, '');

CREATE UNIQUE INDEX IF NOT EXISTS idx_meter_reading_dedup
ON meter_reading (
    organization_id,
    reading_timestamp,
    COALESCE(external_site_id, ''),
    COALESCE(external_device_id, '')
);
