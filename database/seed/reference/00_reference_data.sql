-- =====================================================
-- REFERENCE DATA (Lookup Tables)
-- =====================================================
-- Static reference data that defines types, categories,
-- and classifications used throughout the system.
-- =====================================================

BEGIN;

-- Counterparty Types
INSERT INTO counterparty_type (id, name, code, description, created_at) VALUES
(1, 'Off-taker', 'OFFTAKER', 'Corporate electricity buyer under PPA', '2023-01-10 10:00:00+00'),
(2, 'O&M Contractor', 'OM_CONTRACTOR', 'Operations and Maintenance service provider', '2023-01-10 10:00:00+00');

-- Contract Types
INSERT INTO contract_type (id, name, code, description, created_at) VALUES
(1, 'Power Purchase Agreement', 'PPA', 'Agreement for sale of electricity', '2023-01-10 10:00:00+00'),
(2, 'O&M Service Agreement', 'OM_SERVICE', 'Operations and maintenance service contract', '2023-01-10 10:00:00+00');

-- Contract Status
INSERT INTO contract_status (id, name, code, description, created_at) VALUES
(1, 'Active', 'ACTIVE', 'Contract is currently in effect', '2023-01-10 10:00:00+00'),
(2, 'Executed', 'EXECUTED', 'Contract signed and binding', '2023-01-10 10:00:00+00');

-- Clause Types
INSERT INTO clause_type (id, name, code, description, created_at) VALUES
(1, 'Performance Guarantee', 'PERF_GUARANTEE', 'Performance metrics and guarantees', '2023-01-10 10:00:00+00'),
(2, 'Liquidated Damages', 'LIQ_DAMAGES', 'Pre-determined damage amounts for breach', '2023-01-10 10:00:00+00'),
(3, 'Service Level Agreement', 'SLA', 'Service quality and response time requirements', '2023-01-10 10:00:00+00');

-- Clause Categories
INSERT INTO clause_category (id, name, code, description, created_at) VALUES
(1, 'Availability', 'AVAILABILITY', 'Plant availability requirements and penalties', '2023-01-10 10:00:00+00'),
(2, 'Pricing', 'PRICING', 'Tariff and pricing terms', '2023-01-10 10:00:00+00'),
(3, 'Payment Terms', 'PAYMENT', 'Payment schedules and conditions', '2023-01-10 10:00:00+00');

-- Asset Types
INSERT INTO asset_type (id, name, code, description, created_at) VALUES
(1, 'Solar PV Module', 'PV_MODULE', 'Photovoltaic solar panel', '2023-01-10 10:00:00+00'),
(2, 'Inverter', 'INVERTER', 'DC to AC power inverter', '2023-01-10 10:00:00+00'),
(3, 'Transformer', 'TRANSFORMER', 'Voltage transformation equipment', '2023-01-10 10:00:00+00');

-- Meter Types
INSERT INTO meter_type (id, name, code, description, created_at) VALUES
(1, 'Revenue Meter', 'REVENUE', 'Grid interconnection revenue meter', '2023-01-10 10:00:00+00'),
(2, 'Production Meter', 'PRODUCTION', 'Plant production monitoring meter', '2023-01-10 10:00:00+00'),
(3, 'Irradiance Sensor', 'IRRADIANCE', 'Solar irradiance measurement', '2023-01-10 10:00:00+00');

-- Event Types
INSERT INTO event_type (id, name, code, description, created_at) VALUES
(1, 'Equipment Failure', 'EQUIP_FAIL', 'Asset or component failure event', '2023-01-10 10:00:00+00'),
(2, 'Underperformance', 'UNDERPERF', 'Production below expected levels', '2023-01-10 10:00:00+00'),
(3, 'Grid Outage', 'GRID_OUTAGE', 'Utility grid outage preventing export', '2023-01-10 10:00:00+00');

-- Fault Types
INSERT INTO fault_type (id, name, code, description, created_at) VALUES
(1, 'Inverter Failure', 'INV_FAIL', 'Central inverter offline or fault', '2023-01-10 10:00:00+00'),
(2, 'Communication Loss', 'COMM_LOSS', 'Loss of communication with equipment', '2023-01-10 10:00:00+00');

-- Default Event Types
INSERT INTO default_event_type (id, name, code, description, created_at) VALUES
(1, 'Availability Below Guarantee', 'AVAIL_DEFAULT', 'Plant availability falls below contractual guarantee', '2023-01-10 10:00:00+00'),
(2, 'Performance Ratio Default', 'PR_DEFAULT', 'Performance ratio below guarantee', '2023-01-10 10:00:00+00'),
(3, 'Delayed Response', 'DELAY_DEFAULT', 'Contractor response time exceeds SLA', '2023-01-10 10:00:00+00');

-- Rule Output Types
INSERT INTO rule_output_type (id, name, code, description, created_at) VALUES
(1, 'Liquidated Damages', 'LD', 'Contractual liquidated damages payment', '2023-01-10 10:00:00+00'),
(2, 'Performance Bonus', 'BONUS', 'Performance-based bonus payment', '2023-01-10 10:00:00+00'),
(3, 'Invoice Adjustment', 'INV_ADJ', 'Adjustment to standard invoice amount', '2023-01-10 10:00:00+00');

-- Notification Types
INSERT INTO notification_type (id, name, code, description, created_at) VALUES
(1, 'Default Event Alert', 'DEFAULT_ALERT', 'Notification of contract default event', '2023-01-10 10:00:00+00'),
(2, 'Invoice Ready', 'INV_READY', 'Invoice ready for review', '2023-01-10 10:00:00+00'),
(3, 'Payment Due', 'PMT_DUE', 'Payment due date reminder', '2023-01-10 10:00:00+00');

-- Invoice Line Item Types
INSERT INTO invoice_line_item_type (id, name, code, description, created_at) VALUES
(1, 'Energy Delivered', 'ENERGY', 'Charge for electricity delivered', '2023-01-10 10:00:00+00'),
(2, 'Capacity Payment', 'CAPACITY', 'Fixed capacity payment', '2023-01-10 10:00:00+00'),
(3, 'Liquidated Damages Credit', 'LD_CREDIT', 'Credit for liquidated damages', '2023-01-10 10:00:00+00'),
(4, 'O&M Service Fee', 'OM_FEE', 'Operations and maintenance fee', '2023-01-10 10:00:00+00');

-- Tariff Types
INSERT INTO tariff_type (id, name, code, description, created_at) VALUES
(1, 'Energy Charge', 'ENERGY', 'Per-kWh charge for delivered energy', '2023-01-10 10:00:00+00'),
(2, 'Capacity Charge', 'CAPACITY', 'Fixed charge for capacity availability', '2023-01-10 10:00:00+00');

-- Currency
INSERT INTO currency (id, name, code) VALUES
(1, 'US Dollar', 'USD'),
(2, 'Euro', 'EUR');

-- Grid Event Types
INSERT INTO grid_event_type (id, name, code, description, created_at) VALUES
(1, 'Transmission Outage', 'TRANS_OUT', 'Transmission line outage', '2023-01-10 10:00:00+00'),
(2, 'Curtailment Order', 'CURTAIL', 'Grid operator curtailment instruction', '2023-01-10 10:00:00+00');

-- Weather Data Types
INSERT INTO weather_data_type (id, name, code, description, updated_frequency, created_at) VALUES
(1, 'Solar Irradiance', 'GHI', 'Global Horizontal Irradiance', '15min', '2023-01-10 10:00:00+00'),
(2, 'Temperature', 'TEMP', 'Ambient temperature', '15min', '2023-01-10 10:00:00+00');

COMMIT;
