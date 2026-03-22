-- XF-AB Available Energy Discount Integration
-- Adds AVAILABLE_ENERGY_DISCOUNT line item type, updates logic_parameters,
-- inserts tariff formulas, and updates monthly PR values for all 4 XF-AB tariffs.
--
-- Run against: Supabase (production)
-- Date: 2026-03-22

BEGIN;

-- =============================================================================
-- Step 1: Add AVAILABLE_ENERGY_DISCOUNT line item type
-- =============================================================================
INSERT INTO invoice_line_item_type (code, name)
VALUES ('AVAILABLE_ENERGY_DISCOUNT', 'Available Energy Discount')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Step 2: Update logic_parameters for all 4 XF-AB tariffs
-- Add available_energy_discount config + monthly PR values from Annexure E
-- =============================================================================

-- XFAB (clause_tariff_id = 34)
UPDATE clause_tariff
SET logic_parameters = jsonb_set(
    jsonb_set(
        COALESCE(logic_parameters, '{}'::jsonb),
        '{available_energy_discount}',
        '{"method": "curtailment_allowance", "threshold_pct": 0.05}'::jsonb
    ),
    '{performance_ratio_monthly}',
    '{"1": 0.787, "2": 0.775, "3": 0.774, "4": 0.794, "5": 0.798, "6": 0.804, "7": 0.807, "8": 0.800, "9": 0.788, "10": 0.795, "11": 0.798, "12": 0.795}'::jsonb
)
WHERE id = 34;

-- XFBV (clause_tariff_id = 35)
UPDATE clause_tariff
SET logic_parameters = jsonb_set(
    jsonb_set(
        COALESCE(logic_parameters, '{}'::jsonb),
        '{available_energy_discount}',
        '{"method": "curtailment_allowance", "threshold_pct": 0.05}'::jsonb
    ),
    '{performance_ratio_monthly}',
    '{"1": 0.786, "2": 0.773, "3": 0.769, "4": 0.790, "5": 0.794, "6": 0.801, "7": 0.806, "8": 0.797, "9": 0.784, "10": 0.796, "11": 0.796, "12": 0.797}'::jsonb
)
WHERE id = 35;

-- XFSS (clause_tariff_id = 55)
UPDATE clause_tariff
SET logic_parameters = jsonb_set(
    jsonb_set(
        COALESCE(logic_parameters, '{}'::jsonb),
        '{available_energy_discount}',
        '{"method": "curtailment_allowance", "threshold_pct": 0.05}'::jsonb
    ),
    '{performance_ratio_monthly}',
    '{"1": 0.791, "2": 0.785, "3": 0.794, "4": 0.805, "5": 0.809, "6": 0.811, "7": 0.817, "8": 0.815, "9": 0.798, "10": 0.803, "11": 0.803, "12": 0.802}'::jsonb
)
WHERE id = 55;

-- XFL01 (clause_tariff_id = 60)
UPDATE clause_tariff
SET logic_parameters = jsonb_set(
    jsonb_set(
        COALESCE(logic_parameters, '{}'::jsonb),
        '{available_energy_discount}',
        '{"method": "curtailment_allowance", "threshold_pct": 0.05}'::jsonb
    ),
    '{performance_ratio_monthly}',
    '{"1": 0.808, "2": 0.806, "3": 0.805, "4": 0.821, "5": 0.825, "6": 0.829, "7": 0.835, "8": 0.829, "9": 0.812, "10": 0.820, "11": 0.824, "12": 0.817}'::jsonb
)
WHERE id = 60;

-- =============================================================================
-- Step 4: Add tariff_formula for AVAILABLE_ENERGY_DISCOUNT on all 4 tariffs
-- =============================================================================

-- Get org_id from one of the tariffs
DO $$
DECLARE
    v_org_id BIGINT;
BEGIN
    SELECT organization_id INTO v_org_id FROM clause_tariff WHERE id = 34;

    -- XFAB
    INSERT INTO tariff_formula (
        clause_tariff_id, organization_id, formula_name, formula_text, formula_type,
        variables, operations, conditions, section_ref, extraction_confidence
    ) VALUES (
        34, v_org_id,
        'Available Energy Discount (5% Curtailment Allowance)',
        'Discount = IF(E_avail > (E_met + E_avail) × 0.05, -(E_met + E_avail) × 0.05, -E_avail)',
        'AVAILABLE_ENERGY_DISCOUNT',
        '[{"symbol": "E_avail", "role": "input", "variable_type": "energy", "description": "Available energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.available_energy_kwh"},
          {"symbol": "E_met", "role": "input", "variable_type": "energy", "description": "Metered energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.energy_kwh"},
          {"symbol": "threshold", "role": "constant", "variable_type": "ratio", "description": "Curtailment allowance threshold", "unit": "pct", "maps_to": null}]'::jsonb,
        '["SUM", "MULTIPLY", "COMPARE", "IF_ELSE", "NEGATE"]'::jsonb,
        '[{"type": "threshold", "description": "5% curtailment allowance — if available energy exceeds 5% of total output, discount is capped at 5% of total", "threshold_value": 0.05, "threshold_unit": "pct"}]'::jsonb,
        'PPW Billing Model (not in contract text)',
        0.85
    );

    -- XFBV
    INSERT INTO tariff_formula (
        clause_tariff_id, organization_id, formula_name, formula_text, formula_type,
        variables, operations, conditions, section_ref, extraction_confidence
    ) VALUES (
        35, v_org_id,
        'Available Energy Discount (5% Curtailment Allowance)',
        'Discount = IF(E_avail > (E_met + E_avail) × 0.05, -(E_met + E_avail) × 0.05, -E_avail)',
        'AVAILABLE_ENERGY_DISCOUNT',
        '[{"symbol": "E_avail", "role": "input", "variable_type": "energy", "description": "Available energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.available_energy_kwh"},
          {"symbol": "E_met", "role": "input", "variable_type": "energy", "description": "Metered energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.energy_kwh"},
          {"symbol": "threshold", "role": "constant", "variable_type": "ratio", "description": "Curtailment allowance threshold", "unit": "pct", "maps_to": null}]'::jsonb,
        '["SUM", "MULTIPLY", "COMPARE", "IF_ELSE", "NEGATE"]'::jsonb,
        '[{"type": "threshold", "description": "5% curtailment allowance — if available energy exceeds 5% of total output, discount is capped at 5% of total", "threshold_value": 0.05, "threshold_unit": "pct"}]'::jsonb,
        'PPW Billing Model (not in contract text)',
        0.85
    );

    -- XFSS
    INSERT INTO tariff_formula (
        clause_tariff_id, organization_id, formula_name, formula_text, formula_type,
        variables, operations, conditions, section_ref, extraction_confidence
    ) VALUES (
        55, v_org_id,
        'Available Energy Discount (5% Curtailment Allowance)',
        'Discount = IF(E_avail > (E_met + E_avail) × 0.05, -(E_met + E_avail) × 0.05, -E_avail)',
        'AVAILABLE_ENERGY_DISCOUNT',
        '[{"symbol": "E_avail", "role": "input", "variable_type": "energy", "description": "Available energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.available_energy_kwh"},
          {"symbol": "E_met", "role": "input", "variable_type": "energy", "description": "Metered energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.energy_kwh"},
          {"symbol": "threshold", "role": "constant", "variable_type": "ratio", "description": "Curtailment allowance threshold", "unit": "pct", "maps_to": null}]'::jsonb,
        '["SUM", "MULTIPLY", "COMPARE", "IF_ELSE", "NEGATE"]'::jsonb,
        '[{"type": "threshold", "description": "5% curtailment allowance — if available energy exceeds 5% of total output, discount is capped at 5% of total", "threshold_value": 0.05, "threshold_unit": "pct"}]'::jsonb,
        'PPW Billing Model (not in contract text)',
        0.85
    );

    -- XFL01
    INSERT INTO tariff_formula (
        clause_tariff_id, organization_id, formula_name, formula_text, formula_type,
        variables, operations, conditions, section_ref, extraction_confidence
    ) VALUES (
        60, v_org_id,
        'Available Energy Discount (5% Curtailment Allowance)',
        'Discount = IF(E_avail > (E_met + E_avail) × 0.05, -(E_met + E_avail) × 0.05, -E_avail)',
        'AVAILABLE_ENERGY_DISCOUNT',
        '[{"symbol": "E_avail", "role": "input", "variable_type": "energy", "description": "Available energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.available_energy_kwh"},
          {"symbol": "E_met", "role": "input", "variable_type": "energy", "description": "Metered energy kWh", "unit": "kWh", "maps_to": "meter_aggregate.energy_kwh"},
          {"symbol": "threshold", "role": "constant", "variable_type": "ratio", "description": "Curtailment allowance threshold", "unit": "pct", "maps_to": null}]'::jsonb,
        '["SUM", "MULTIPLY", "COMPARE", "IF_ELSE", "NEGATE"]'::jsonb,
        '[{"type": "threshold", "description": "5% curtailment allowance — if available energy exceeds 5% of total output, discount is capped at 5% of total", "threshold_value": 0.05, "threshold_unit": "pct"}]'::jsonb,
        'PPW Billing Model (not in contract text)',
        0.85
    );
END $$;

-- =============================================================================
-- Verification queries
-- =============================================================================

-- Verify line item type
SELECT id, code, name FROM invoice_line_item_type WHERE code = 'AVAILABLE_ENERGY_DISCOUNT';

-- Verify logic_parameters updates
SELECT id, logic_parameters->'available_energy_discount' AS discount_config,
       logic_parameters->'performance_ratio_monthly' AS pr_monthly
FROM clause_tariff
WHERE id IN (34, 35, 55, 60);

-- Verify tariff formulas
SELECT id, clause_tariff_id, formula_type, formula_name, extraction_confidence
FROM tariff_formula
WHERE formula_type = 'AVAILABLE_ENERGY_DISCOUNT'
ORDER BY clause_tariff_id;

COMMIT;
