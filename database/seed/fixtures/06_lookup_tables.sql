-- =====================================================
-- LOOKUP TABLE PRE-POPULATION (CORRECTED)
-- =====================================================
-- Pre-populate clause types and categories with codes
-- expected by Claude AI extraction and lookup service.
--
-- IMPORTANT DISTINCTION:
-- - clause_type: High-level classification (commercial, legal, financial, operational, regulatory)
-- - clause_category: Specific clause categories (availability, pricing, liquidated_damages, etc.)
-- =====================================================

-- Add unique constraints on code columns (if not exists)
ALTER TABLE clause_type DROP CONSTRAINT IF EXISTS clause_type_code_unique;
ALTER TABLE clause_type ADD CONSTRAINT clause_type_code_unique UNIQUE (code);

ALTER TABLE clause_category DROP CONSTRAINT IF EXISTS clause_category_code_unique;
ALTER TABLE clause_category ADD CONSTRAINT clause_category_code_unique UNIQUE (code);

-- Clause Types (HIGH-LEVEL classifications)
INSERT INTO clause_type (name, code, description, created_at) VALUES
('Commercial', 'COMMERCIAL', 'Commercial and business terms', NOW()),
('Legal', 'LEGAL', 'Legal terms and conditions', NOW()),
('Financial', 'FINANCIAL', 'Financial and payment terms', NOW()),
('Operational', 'OPERATIONAL', 'Operational and performance terms', NOW()),
('Regulatory', 'REGULATORY', 'Regulatory and compliance terms', NOW())
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;

-- Clause Categories (SPECIFIC categories)
INSERT INTO clause_category (name, code, description, created_at) VALUES
('Availability', 'AVAILABILITY', 'Plant availability requirements and penalties', NOW()),
('Performance Guarantee', 'PERF_GUARANTEE', 'Performance guarantees and SLAs', NOW()),
('Liquidated Damages', 'LIQ_DAMAGES', 'Pre-determined damage amounts for breach', NOW()),
('Pricing', 'PRICING', 'Energy pricing and tariff terms', NOW()),
('Payment Terms', 'PAYMENT', 'Payment schedules and invoicing', NOW()),
('Force Majeure', 'FORCE_MAJEURE', 'Unforeseeable events excusing performance', NOW()),
('Termination', 'TERMINATION', 'Contract termination conditions', NOW()),
('Service Level Agreement', 'SLA', 'Service quality and response requirements', NOW()),
('Compliance', 'COMPLIANCE', 'Regulatory and compliance requirements', NOW()),
('General', 'GENERAL', 'General contract terms', NOW())
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;

-- Verify insertions
SELECT 'Clause Types (High-level Classifications):' AS info;
SELECT id, code, name FROM clause_type ORDER BY id;

SELECT '' AS separator;

SELECT 'Clause Categories (Specific):' AS info;
SELECT id, code, name FROM clause_category ORDER BY id;
