-- =====================================================
-- LOOKUP TABLE PRE-POPULATION
-- =====================================================
-- Updated January 2026: 13-category flat structure
--
-- IMPORTANT: clause_type is DEPRECATED
-- Use clause_category only for new extractions.
-- =====================================================

-- Add unique constraints on code columns (if not exists)
ALTER TABLE clause_type DROP CONSTRAINT IF EXISTS clause_type_code_unique;
ALTER TABLE clause_type ADD CONSTRAINT clause_type_code_unique UNIQUE (code);

ALTER TABLE clause_category DROP CONSTRAINT IF EXISTS clause_category_code_unique;
ALTER TABLE clause_category ADD CONSTRAINT clause_category_code_unique UNIQUE (code);

-- Add key_terms column if not exists
ALTER TABLE clause_category ADD COLUMN IF NOT EXISTS key_terms TEXT[];

-- Clause Types (DEPRECATED - kept for historical data)
-- New extractions should use clause_category only
INSERT INTO clause_type (name, code, description, created_at) VALUES
('Commercial', 'COMMERCIAL', 'DEPRECATED: Commercial and business terms', NOW()),
('Legal', 'LEGAL', 'DEPRECATED: Legal terms and conditions', NOW()),
('Financial', 'FINANCIAL', 'DEPRECATED: Financial and payment terms', NOW()),
('Operational', 'OPERATIONAL', 'DEPRECATED: Operational and performance terms', NOW()),
('Regulatory', 'REGULATORY', 'DEPRECATED: Regulatory and compliance terms', NOW())
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;

-- 13-Category Flat Structure (January 2026)
INSERT INTO clause_category (name, code, description, key_terms, created_at) VALUES
(
    'Conditions Precedent',
    'CONDITIONS_PRECEDENT',
    'Requirements that must be satisfied before contract becomes effective',
    ARRAY['conditions precedent', 'CP', 'condition to', 'effectiveness', 'closing conditions', 'prerequisite'],
    NOW()
),
(
    'Availability',
    'AVAILABILITY',
    'System uptime, availability guarantees, meter accuracy, and curtailment provisions',
    ARRAY['availability', 'uptime', 'meter accuracy', 'curtailment', 'unavailability', 'outage hours'],
    NOW()
),
(
    'Performance Guarantee',
    'PERFORMANCE_GUARANTEE',
    'Output guarantees, capacity factor, performance ratio, and degradation allowances',
    ARRAY['performance ratio', 'capacity factor', 'degradation', 'output guarantee', 'energy production', 'PR guarantee'],
    NOW()
),
(
    'Liquidated Damages',
    'LIQUIDATED_DAMAGES',
    'Penalties for contract breaches including availability shortfall, delays, and performance failures',
    ARRAY['liquidated damages', 'LD', 'penalty', 'damages', 'shortfall payment', 'delay damages'],
    NOW()
),
(
    'Pricing',
    'PRICING',
    'Energy rates, price escalation, indexing, and adjustment mechanisms',
    ARRAY['price', 'rate', '$/kWh', '$/MWh', 'escalation', 'price adjustment', 'tariff'],
    NOW()
),
(
    'Payment Terms',
    'PAYMENT_TERMS',
    'Billing cycles, payment timing, take-or-pay obligations, and invoice procedures',
    ARRAY['payment', 'invoice', 'billing', 'take or pay', 'minimum purchase', 'due date', 'net days'],
    NOW()
),
(
    'Default',
    'DEFAULT',
    'Events of default, cure periods, remedies, and reimbursement provisions',
    ARRAY['default', 'breach', 'event of default', 'cure', 'remedy', 'reimbursement', 'failure to perform'],
    NOW()
),
(
    'Force Majeure',
    'FORCE_MAJEURE',
    'Excused events beyond party control and related relief provisions',
    ARRAY['force majeure', 'act of god', 'unforeseeable', 'beyond control', 'excused event'],
    NOW()
),
(
    'Termination',
    'TERMINATION',
    'Contract end provisions, early termination rights, purchase options, and fair market value',
    ARRAY['termination', 'expiration', 'early termination', 'purchase option', 'fair market value', 'buyout', 'FMV'],
    NOW()
),
(
    'Maintenance',
    'MAINTENANCE',
    'O&M obligations, service level agreements, scheduled outages, and party responsibilities',
    ARRAY['maintenance', 'O&M', 'service level', 'SLA', 'scheduled outage', 'repair', 'preventive maintenance'],
    NOW()
),
(
    'Compliance',
    'COMPLIANCE',
    'Regulatory, environmental, and legal compliance requirements',
    ARRAY['compliance', 'regulatory', 'permit', 'environmental', 'law', 'regulation', 'license'],
    NOW()
),
(
    'Security Package',
    'SECURITY_PACKAGE',
    'Financial security instruments including letters of credit, bonds, and guarantees',
    ARRAY['letter of credit', 'LC', 'bond', 'guarantee', 'security', 'collateral', 'parent guarantee'],
    NOW()
),
(
    'General',
    'GENERAL',
    'Standard contract terms including governing law, disputes, notices, assignments, and confidentiality',
    ARRAY['governing law', 'dispute', 'notice', 'assignment', 'amendment', 'waiver', 'confidential', 'severability'],
    NOW()
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    key_terms = EXCLUDED.key_terms;

-- Verify insertions
SELECT 'Clause Types (DEPRECATED):' AS info;
SELECT id, code, name FROM clause_type ORDER BY id;

SELECT '' AS separator;

SELECT 'Clause Categories (13-Category Structure):' AS info;
SELECT id, code, name, key_terms IS NOT NULL AS has_key_terms FROM clause_category ORDER BY id;
