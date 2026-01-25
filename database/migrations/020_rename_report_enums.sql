-- Migration: 020_rename_report_enums.sql
-- Description: Simplify enum names where context is unambiguous
-- Version: v5.3
-- Date: 2026-01-25
-- Depends on: 019_invoice_comparison_final_amount.sql

-- =============================================================================
-- RATIONALE
-- =============================================================================
-- Rename enums to simpler names where there's no ambiguity:
--   invoice_report_type    → report_type      (clearly scoped to reports)
--   export_file_format     → file_format      (no conflict in schema)
--   report_delivery_method → delivery_method  (no conflict in schema)
--
-- Keep prefixed names where ambiguity exists:
--   report_frequency  (differentiates from meter data frequency)
--   report_status     (differentiates from contract/invoice status)
--   generation_source (already clean, no prefix)
--
-- PostgreSQL ALTER TYPE ... RENAME TO automatically updates all columns
-- that reference the enum type.

-- =============================================================================
-- SECTION 1: RENAME ENUMS
-- =============================================================================

-- Rename invoice_report_type → report_type
ALTER TYPE invoice_report_type RENAME TO report_type;

-- Rename export_file_format → file_format
ALTER TYPE export_file_format RENAME TO file_format;

-- Rename report_delivery_method → delivery_method
ALTER TYPE report_delivery_method RENAME TO delivery_method;

-- =============================================================================
-- SECTION 2: UPDATE FUNCTION SIGNATURES
-- =============================================================================

-- The calculate_next_run_time function uses report_frequency which is unchanged.
-- No function updates needed for the renamed enums since they're only used
-- in table columns (which are auto-updated by ALTER TYPE RENAME).

-- =============================================================================
-- SECTION 3: UPDATE COMMENTS
-- =============================================================================

COMMENT ON TYPE report_type IS
    'Invoice-focused report types: invoice_to_client, invoice_expected, invoice_received, invoice_comparison';

COMMENT ON TYPE file_format IS
    'Export file formats: csv, xlsx, json, pdf';

COMMENT ON TYPE delivery_method IS
    'Report delivery methods: email, s3, both';

-- =============================================================================
-- VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_old_exists BOOLEAN;
    v_new_exists BOOLEAN;
BEGIN
    -- Verify old enum names no longer exist
    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'invoice_report_type') INTO v_old_exists;
    IF v_old_exists THEN
        RAISE EXCEPTION 'Old enum invoice_report_type still exists';
    END IF;

    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'export_file_format') INTO v_old_exists;
    IF v_old_exists THEN
        RAISE EXCEPTION 'Old enum export_file_format still exists';
    END IF;

    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_delivery_method') INTO v_old_exists;
    IF v_old_exists THEN
        RAISE EXCEPTION 'Old enum report_delivery_method still exists';
    END IF;

    -- Verify new enum names exist
    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_type') INTO v_new_exists;
    IF NOT v_new_exists THEN
        RAISE EXCEPTION 'New enum report_type not found';
    END IF;

    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'file_format') INTO v_new_exists;
    IF NOT v_new_exists THEN
        RAISE EXCEPTION 'New enum file_format not found';
    END IF;

    SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'delivery_method') INTO v_new_exists;
    IF NOT v_new_exists THEN
        RAISE EXCEPTION 'New enum delivery_method not found';
    END IF;

    -- Verify columns still work (spot check)
    PERFORM column_name, udt_name
    FROM information_schema.columns
    WHERE table_name = 'report_template'
      AND column_name = 'report_type'
      AND udt_name = 'report_type';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'report_template.report_type column not using report_type enum';
    END IF;

    RAISE NOTICE 'Migration 020_rename_report_enums (v5.3) completed successfully';
END $$;
