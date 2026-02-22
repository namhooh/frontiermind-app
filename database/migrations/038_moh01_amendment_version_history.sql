-- 038_moh01_amendment_version_history.sql
-- Amendment Version History: Populate pre-amendment original tariff row and link
-- the current (post-amendment) tariff to the First Amendment via supersedes chain.
--
-- Replaces 038_fix_moh01_min_solar_price_escalation.sql (merged here).
--
-- Background:
--   MOH01's First Amendment (2023-07-05) changed 4 things:
--     1. Contract term 20 -> 25 years
--     2. Solar discount 21% -> 22%
--     3. Removed min solar price escalation (FIXED 2.5% -> NONE)
--     4. Revised early termination charges
--
--   The contract_amendment record already exists with source_metadata.changes
--   capturing all four changes. However the versioning infrastructure (migration 033:
--   supersedes chains, is_current flags, triggers, views) was not populated -- the
--   current tariff has post-amendment values baked in with version=1 and no amendment
--   linkage. This migration creates the original (pre-amendment) row and links the
--   chain.
--
-- Lookup strategy:
--   All rows are resolved via stable business keys:
--     - Tariff: tariff_group_key = 'GH-MOH01-PPA-001-MAIN'
--     - Contract: external_contract_id = 'GH-MOH01-PPA-001'
--     - Amendment: amendment_number = 1 (on the resolved contract)
--   No hardcoded row IDs are used.
--
-- Safety:
--   - The AFTER INSERT trigger (trg_clause_tariff_supersede) won't fire for Step A
--     because supersedes_tariff_id=NULL on the original row.
--   - Partial unique index uq_clause_tariff_current_group_validity won't collide
--     because the original has is_current=false.
--   - clause_tariff_current_v view continues to show only the amended tariff.
--   - tariff_annual_rate rows (clause_tariff_id = amended tariff) stay correct.
--
-- Idempotency:
--   Guarded by checking whether the original row already exists. Safe to re-run.

BEGIN;

DO $$
DECLARE
    v_amended_id       bigint;   -- existing tariff (post-amendment, currently version=1)
    v_contract_id      bigint;   -- resolved contract
    v_amendment_id     bigint;   -- resolved contract_amendment
    v_original_id      bigint;   -- newly inserted pre-amendment original
    v_existing_original bigint;  -- idempotency check
BEGIN
    -- ========================================================================
    -- Resolve business keys
    -- ========================================================================

    -- Resolve the current (post-amendment) tariff via stable tariff_group_key
    SELECT id INTO v_amended_id
    FROM clause_tariff
    WHERE tariff_group_key = 'GH-MOH01-PPA-001-MAIN'
      AND is_current = true;

    IF v_amended_id IS NULL THEN
        RAISE EXCEPTION 'Tariff not found for tariff_group_key=GH-MOH01-PPA-001-MAIN (is_current=true)';
    END IF;

    -- Resolve the contract via the tariff's contract_id
    SELECT contract_id INTO v_contract_id
    FROM clause_tariff WHERE id = v_amended_id;

    -- Resolve the First Amendment via contract + amendment_number
    SELECT id INTO v_amendment_id
    FROM contract_amendment
    WHERE contract_id = v_contract_id
      AND amendment_number = 1;

    IF v_amendment_id IS NULL THEN
        RAISE EXCEPTION 'Amendment #1 not found for contract_id=%', v_contract_id;
    END IF;

    RAISE NOTICE 'Resolved: amended_tariff=%, contract=%, amendment=%',
        v_amended_id, v_contract_id, v_amendment_id;

    -- ========================================================================
    -- Idempotency: skip if original row already exists
    -- ========================================================================

    SELECT id INTO v_existing_original
    FROM clause_tariff
    WHERE tariff_group_key = 'GH-MOH01-PPA-001-MAIN'
      AND is_current = false
      AND version = 1
      AND contract_amendment_id IS NULL;

    IF v_existing_original IS NOT NULL THEN
        RAISE NOTICE 'Original tariff already exists (id=%), skipping insert', v_existing_original;

        -- Still ensure the amended tariff is properly linked (idempotent update)
        UPDATE clause_tariff
        SET version = 2,
            contract_amendment_id = v_amendment_id,
            supersedes_tariff_id = v_existing_original,
            change_action = 'MODIFIED',
            logic_parameters = jsonb_set(
                logic_parameters,
                '{escalation_rules}',
                '[{"type": "NONE", "component": "min_solar_price"},
                  {"type": "NONE", "component": "max_solar_price"}]'::jsonb
            )
        WHERE id = v_amended_id;

        RETURN;
    END IF;

    -- ========================================================================
    -- Step A: Insert the pre-amendment original tariff row
    -- ========================================================================
    -- Copy structure from the amended tariff with pre-amendment overrides:
    --   - discount_pct = 0.21 (was 0.22 after amendment)
    --   - escalation_rules includes FIXED 2.5% on min_solar_price (removed by amendment)
    --   - is_current = false (superseded by the amended version)
    --   - version = 1, contract_amendment_id = NULL, change_action = NULL

    INSERT INTO clause_tariff (
        contract_id, project_id, organization_id,
        name, base_rate, unit, currency_id,
        tariff_type_id, energy_sale_type_id, escalation_type_id,
        market_ref_currency_id,
        valid_from, valid_to,
        tariff_group_key, meter_id, is_active,
        logic_parameters,
        version, is_current, contract_amendment_id, supersedes_tariff_id, change_action,
        source_metadata
    )
    SELECT
        contract_id, project_id, organization_id,
        name || ' (Original)', base_rate, unit, currency_id,
        tariff_type_id, energy_sale_type_id, escalation_type_id,
        market_ref_currency_id,
        valid_from, valid_to,
        tariff_group_key, meter_id, is_active,
        -- Pre-amendment logic_parameters: discount=21%, min_solar_price has FIXED 2.5% escalation
        jsonb_set(
            jsonb_set(
                logic_parameters,
                '{discount_pct}',
                '0.21'::jsonb
            ),
            '{escalation_rules}',
            '[{"type": "FIXED", "value": 0.025, "component": "min_solar_price", "start_year": 2},
              {"type": "NONE", "component": "max_solar_price"}]'::jsonb
        ),
        1,       -- version (original)
        false,   -- is_current (superseded)
        NULL,    -- contract_amendment_id (original contract, no amendment)
        NULL,    -- supersedes_tariff_id (nothing before this)
        NULL,    -- change_action (original, not a change)
        '{"note": "Pre-amendment original tariff. Inserted by migration 038."}'::jsonb
    FROM clause_tariff
    WHERE id = v_amended_id;

    -- Capture the newly inserted original tariff ID via RETURNING equivalent
    SELECT id INTO v_original_id
    FROM clause_tariff
    WHERE tariff_group_key = 'GH-MOH01-PPA-001-MAIN'
      AND is_current = false
      AND version = 1
      AND contract_amendment_id IS NULL;

    IF v_original_id IS NULL THEN
        RAISE EXCEPTION 'Failed to insert original tariff row';
    END IF;

    RAISE NOTICE 'Original tariff inserted with id=%', v_original_id;

    -- ========================================================================
    -- Step B: Update amended tariff — link to amendment + escalation fix
    -- ========================================================================

    UPDATE clause_tariff
    SET version = 2,
        contract_amendment_id = v_amendment_id,
        supersedes_tariff_id = v_original_id,
        change_action = 'MODIFIED',
        logic_parameters = jsonb_set(
            logic_parameters,
            '{escalation_rules}',
            '[{"type": "NONE", "component": "min_solar_price"},
              {"type": "NONE", "component": "max_solar_price"}]'::jsonb
        )
    WHERE id = v_amended_id;

    -- ========================================================================
    -- Step C: Verify the version chain
    -- ========================================================================

    -- C.1: Original row exists with correct pre-amendment values
    PERFORM 1
    FROM clause_tariff
    WHERE id = v_original_id
      AND version = 1
      AND is_current = false
      AND contract_amendment_id IS NULL
      AND supersedes_tariff_id IS NULL
      AND (logic_parameters->>'discount_pct')::numeric = 0.21
      AND logic_parameters->'escalation_rules' @> '[{"type": "FIXED", "component": "min_solar_price"}]'::jsonb;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Assertion failed: original tariff (id=%) has incorrect values', v_original_id;
    END IF;

    -- C.2: Amended row has correct post-amendment values and chain links
    PERFORM 1
    FROM clause_tariff
    WHERE id = v_amended_id
      AND version = 2
      AND is_current = true
      AND contract_amendment_id = v_amendment_id
      AND supersedes_tariff_id = v_original_id
      AND change_action = 'MODIFIED'
      AND (logic_parameters->>'discount_pct')::numeric = 0.22
      AND logic_parameters->'escalation_rules' @> '[{"type": "NONE", "component": "min_solar_price"}]'::jsonb;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Assertion failed: amended tariff (id=%) has incorrect values or chain links', v_amended_id;
    END IF;

    -- C.3: Only one current tariff exists for this group
    PERFORM 1
    FROM clause_tariff
    WHERE tariff_group_key = 'GH-MOH01-PPA-001-MAIN'
      AND is_current = true
      AND id = v_amended_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Assertion failed: current tariff view should show only amended tariff (id=%)', v_amended_id;
    END IF;

    RAISE NOTICE 'Amendment version chain verified: original=% -> amended=%', v_original_id, v_amended_id;
END $$;

COMMIT;
