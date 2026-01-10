-- =====================================================
-- TEST ORGANIZATIONS & ENTITIES
-- =====================================================
-- Organizations, roles, counterparties, vendors, and
-- other entity-level test data.
-- =====================================================

BEGIN;

-- Organizations
INSERT INTO organization (id, name, address, country, created_at) VALUES
(1, 'GreenPower Energy Corp', '100 Solar Drive, Austin, TX', 'USA', '2023-01-15 10:00:00+00'),
(2, 'TechCorp Industries', '500 Innovation Blvd, San Francisco, CA', 'USA', '2023-01-15 10:00:00+00');

-- Roles
INSERT INTO role (id, organization_id, name, email, created_at) VALUES
(1, 1, 'Project Manager', 'pm@greenpower.com', '2023-01-15 10:00:00+00'),
(2, 1, 'Compliance Officer', 'compliance@greenpower.com', '2023-01-15 10:00:00+00'),
(3, 2, 'Energy Procurement Manager', 'energy@techcorp.com', '2023-01-15 10:00:00+00');

-- Counterparties
INSERT INTO counterparty (id, counterparty_type_id, name, email, address, country, created_at) VALUES
(1, 1, 'TechCorp Industries', 'invoicing@techcorp.com', '500 Innovation Blvd, San Francisco, CA', 'USA', '2023-02-01 10:00:00+00'),
(2, 2, 'SolarMaint Services LLC', 'billing@solarmaint.com', '250 Service Road, Phoenix, AZ', 'USA', '2023-02-15 10:00:00+00');

-- Vendors
INSERT INTO vendor (id, name, address, country, created_at) VALUES
(1, 'FirstSolar Manufacturing', 'Tempe, Arizona', 'USA', '2023-01-10 10:00:00+00'),
(2, 'ABB Power Systems', 'Zurich', 'Switzerland', '2023-01-10 10:00:00+00'),
(3, 'Schneider Electric', 'Rueil-Malmaison', 'France', '2023-01-10 10:00:00+00');

-- Grid Operator
INSERT INTO grid_operator (id, name, address, country, created_at) VALUES
(1, 'Texas Grid Operator', 'Austin, TX', 'USA', '2023-01-10 10:00:00+00');

-- Clause Responsible Party
INSERT INTO clause_responsibleparty (id, name, address, country, created_at) VALUES
(1, 'GreenPower Energy Corp', '100 Solar Drive, Austin, TX', 'USA', '2023-01-15 10:00:00+00'),
(2, 'SolarMaint Services LLC', '250 Service Road, Phoenix, AZ', 'USA', '2023-02-15 10:00:00+00');

COMMIT;
