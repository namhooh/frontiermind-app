-- =====================================================
-- DUMMY DATA FOR CONTRACT COMPLIANCE & INVOICING ENGINE
-- =====================================================
-- SCENARIO: Solar PPA project with availability default event
-- - Developer: GreenPower Energy Corp
-- - Off-taker: TechCorp Industries (PPA buyer)
-- - Contractor: SolarMaint Services (O&M provider)
-- - Event: Plant availability falls below guaranteed 95%
-- - Impact: Liquidated damages applied to off-taker invoice
--          AND cross-checked against contractor's invoice
-- =====================================================

BEGIN;

-- =====================================================
-- 1. CORE ENTITIES
-- =====================================================

-- Organizations
INSERT INTO organization (id, name, address, country, created_at) VALUES
(1, 'GreenPower Energy Corp', '100 Solar Drive, Austin, TX', 'USA', '2023-01-15 10:00:00+00'),
(2, 'TechCorp Industries', '500 Innovation Blvd, San Francisco, CA', 'USA', '2023-01-15 10:00:00+00');

-- Roles
INSERT INTO role (id, organization_id, name, email, created_at) VALUES
(1, 1, 'Project Manager', 'pm@greenpower.com', '2023-01-15 10:00:00+00'),
(2, 1, 'Compliance Officer', 'compliance@greenpower.com', '2023-01-15 10:00:00+00'),
(3, 2, 'Energy Procurement Manager', 'energy@techcorp.com', '2023-01-15 10:00:00+00');

-- Project
INSERT INTO project (id, organization_id, name, created_at) VALUES
(1, 1, 'SunValley Solar Farm - 50MW', '2023-02-01 09:00:00+00');

-- Counterparty Types
INSERT INTO counterparty_type (id, name, code, description, created_at) VALUES
(1, 'Off-taker', 'OFFTAKER', 'Corporate electricity buyer under PPA', '2023-01-10 10:00:00+00'),
(2, 'O&M Contractor', 'OM_CONTRACTOR', 'Operations and Maintenance service provider', '2023-01-10 10:00:00+00');

-- Counterparties
INSERT INTO counterparty (id, counterparty_type_id, name, email, address, country, created_at) VALUES
(1, 1, 'TechCorp Industries', 'invoicing@techcorp.com', '500 Innovation Blvd, San Francisco, CA', 'USA', '2023-02-01 10:00:00+00'),
(2, 2, 'SolarMaint Services LLC', 'billing@solarmaint.com', '250 Service Road, Phoenix, AZ', 'USA', '2023-02-15 10:00:00+00');

-- =====================================================
-- 2. CONTRACTS
-- =====================================================

-- Contract Types
INSERT INTO contract_type (id, name, code, description, created_at) VALUES
(1, 'Power Purchase Agreement', 'PPA', 'Agreement for sale of electricity', '2023-01-10 10:00:00+00'),
(2, 'O&M Service Agreement', 'OM_SERVICE', 'Operations and maintenance service contract', '2023-01-10 10:00:00+00');

-- Contract Status
INSERT INTO contract_status (id, name, code, description, created_at) VALUES
(1, 'Active', 'ACTIVE', 'Contract is currently in effect', '2023-01-10 10:00:00+00'),
(2, 'Executed', 'EXECUTED', 'Contract signed and binding', '2023-01-10 10:00:00+00');

-- Contracts
INSERT INTO contract (id, project_id, organization_id, counterparty_id, contract_type_id, contract_status_id, 
                      name, description, effective_date, end_date, file_location, 
                      created_at, updated_at, updated_by, version) VALUES
(1, 1, 1, 1, 1, 1, 
 'TechCorp PPA - SunValley Solar', 
 '20-year Power Purchase Agreement with TechCorp Industries for 50MW solar facility',
 '2024-01-01', '2043-12-31', '/contracts/ppa/techcorp_sunvalley_2024.pdf',
 '2023-11-01 10:00:00+00', '2023-11-01 10:00:00+00', 'legal@greenpower.com', 1),
(2, 1, 1, 2, 2, 1,
 'SolarMaint O&M Agreement - SunValley',
 'Full-service O&M agreement for SunValley Solar Farm',
 '2024-01-01', '2028-12-31', '/contracts/om/solarmaint_sunvalley_2024.pdf',
 '2023-12-01 10:00:00+00', '2023-12-01 10:00:00+00', 'ops@greenpower.com', 1);

-- =====================================================
-- 3. CLAUSES
-- =====================================================

-- Clause Responsible Party
INSERT INTO clause_responsibleparty (id, name, address, country, created_at) VALUES
(1, 'GreenPower Energy Corp', '100 Solar Drive, Austin, TX', 'USA', '2023-01-15 10:00:00+00'),
(2, 'SolarMaint Services LLC', '250 Service Road, Phoenix, AZ', 'USA', '2023-02-15 10:00:00+00');

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

-- Clauses
INSERT INTO clause (id, project_id, contract_id, clause_responsibleparty_id, clause_type_id, clause_category_id,
                    name, section_ref, raw_text, normalized_payload, 
                    created_at, updated_at, updated_by, version) VALUES
-- PPA Availability Clause with LDs
(1, 1, 1, 1, 1, 1,
 'Guaranteed Availability',
 'Section 4.2',
 'Seller shall ensure the Facility achieves a minimum annual Availability of 95%. Availability shall be calculated as (Actual Operating Hours / (Total Hours - Excused Outage Hours)) × 100%. For each percentage point below 95%, Seller shall pay Buyer liquidated damages equal to $50,000 per percentage point per Contract Year.',
 '{"guarantee_type": "availability", "threshold": 95, "threshold_unit": "percent", "calculation_period": "annual", "formula": "(actual_hours - excused_hours) / (total_hours - excused_hours) * 100", "ld_per_point": 50000, "ld_currency": "USD", "excused_events": ["grid_outage", "force_majeure", "buyer_curtailment"]}'::jsonb,
 '2023-11-01 10:00:00+00', '2023-11-01 10:00:00+00', 'legal@greenpower.com', 1),
-- PPA Energy Pricing
(2, 1, 1, 1, 2, 2,
 'Energy Pricing',
 'Section 3.1',
 'Buyer shall pay Seller for Delivered Energy at a rate of $0.045 per kWh, escalating at 2% annually.',
 '{"rate_type": "energy", "base_rate": 0.045, "unit": "kWh", "currency": "USD", "escalation_rate": 0.02, "escalation_period": "annual"}'::jsonb,
 '2023-11-01 10:00:00+00', '2023-11-01 10:00:00+00', 'legal@greenpower.com', 1),
-- O&M Availability SLA
(3, 1, 2, 2, 3, 1,
 'O&M Availability Performance',
 'Schedule A, Section 2.1',
 'Contractor shall maintain the Facility to achieve minimum 95% annual Availability. If Availability falls below 95% due to Contractor negligence or failure to perform maintenance, Contractor shall compensate Owner for resulting lost revenue and liquidated damages.',
 '{"sla_type": "availability", "threshold": 95, "threshold_unit": "percent", "compensation_scope": ["lost_revenue", "ld_passthrough"], "exclusions": ["force_majeure", "equipment_defects", "owner_directed_outages"]}'::jsonb,
 '2023-12-01 10:00:00+00', '2023-12-01 10:00:00+00', 'ops@greenpower.com', 1),
-- O&M Service Fee
(4, 1, 2, 2, 2, 3,
 'Monthly Service Fee',
 'Section 5.1',
 'Owner shall pay Contractor a fixed monthly service fee of $85,000, payable within 30 days of invoice.',
 '{"fee_type": "fixed_monthly", "amount": 85000, "currency": "USD", "payment_terms": "net_30"}'::jsonb,
 '2023-12-01 10:00:00+00', '2023-12-01 10:00:00+00', 'ops@greenpower.com', 1);

-- =====================================================
-- 4. TARIFFS
-- =====================================================

-- Tariff Types
INSERT INTO tariff_type (id, name, code, description, created_at) VALUES
(1, 'Energy Charge', 'ENERGY', 'Per-kWh charge for delivered energy', '2023-01-10 10:00:00+00'),
(2, 'Capacity Charge', 'CAPACITY', 'Fixed charge for capacity availability', '2023-01-10 10:00:00+00');

-- Currency
INSERT INTO currency (id, name, code) VALUES
(1, 'US Dollar', 'USD'),
(2, 'Euro', 'EUR');

-- Clause Tariffs
INSERT INTO clause_tariff (id, project_id, contract_id, tariff_type_id, currency_id,
                          name, valid_from, valid_to, base_rate, unit, logic_parameters, created_at) VALUES
(1, 1, 1, 1, 1,
 'PPA Energy Rate - Year 1',
 '2024-01-01', '2024-12-31', 0.045, 'kWh',
 '{"escalation_rate": 0.02, "annual_adjustment": true}'::jsonb,
 '2023-11-01 10:00:00+00');

-- =====================================================
-- 5. ASSETS & METERS
-- =====================================================

-- Vendors
INSERT INTO vendor (id, name, address, country, created_at) VALUES
(1, 'FirstSolar Manufacturing', 'Tempe, Arizona', 'USA', '2023-01-10 10:00:00+00'),
(2, 'ABB Power Systems', 'Zurich', 'Switzerland', '2023-01-10 10:00:00+00'),
(3, 'Schneider Electric', 'Rueil-Malmaison', 'France', '2023-01-10 10:00:00+00');

-- Asset Types
INSERT INTO asset_type (id, name, code, description, created_at) VALUES
(1, 'Solar PV Module', 'PV_MODULE', 'Photovoltaic solar panel', '2023-01-10 10:00:00+00'),
(2, 'Inverter', 'INVERTER', 'DC to AC power inverter', '2023-01-10 10:00:00+00'),
(3, 'Transformer', 'TRANSFORMER', 'Voltage transformation equipment', '2023-01-10 10:00:00+00');

-- Assets
INSERT INTO asset (id, project_id, asset_type_id, vendor_id, name, description, model, serial_code, created_at) VALUES
(1, 1, 2, 2, 'Central Inverter 1', 'Primary 2.5MW central inverter', 'PVS980-58', 'INV-001-2023', '2023-08-15 10:00:00+00'),
(2, 1, 2, 2, 'Central Inverter 2', 'Secondary 2.5MW central inverter', 'PVS980-58', 'INV-002-2023', '2023-08-15 10:00:00+00');

-- Meter Types
INSERT INTO meter_type (id, name, code, description, created_at) VALUES
(1, 'Revenue Meter', 'REVENUE', 'Grid interconnection revenue meter', '2023-01-10 10:00:00+00'),
(2, 'Production Meter', 'PRODUCTION', 'Plant production monitoring meter', '2023-01-10 10:00:00+00'),
(3, 'Irradiance Sensor', 'IRRADIANCE', 'Solar irradiance measurement', '2023-01-10 10:00:00+00');

-- Meters
INSERT INTO meter (id, project_id, asset_id, vendor_id, meter_type_id, model, unit, created_at) VALUES
(1, 1, NULL, 3, 1, 'PM5560', 'kWh', '2023-09-01 10:00:00+00'),
(2, 1, NULL, 3, 2, 'PM5560', 'kWh', '2023-09-01 10:00:00+00');

-- =====================================================
-- 6. DATA SOURCES
-- =====================================================

INSERT INTO data_source (id, name, description, updated_frequency, created_at) VALUES
(1, 'SCADA System', 'Plant supervisory control and data acquisition system', '15min', '2023-09-01 10:00:00+00'),
(2, 'Weather Station', 'On-site meteorological station', '15min', '2023-09-01 10:00:00+00'),
(3, 'Revenue Meter', 'Utility interconnection revenue meter', 'hourly', '2023-09-01 10:00:00+00'),
(4, 'Contractor Report', 'Monthly O&M contractor reports', 'daily', '2023-09-01 10:00:00+00');

-- =====================================================
-- 7. BILLING PERIOD & METER DATA
-- =====================================================

-- Billing Period (November 2024)
INSERT INTO billing_period (id, name, start_date, end_date, created_at) VALUES
(1, 'November 2024', '2024-11-01', '2024-11-30', '2024-11-01 00:00:00+00');

-- Meter Readings (Sample hourly data for November)
-- Production is lower than expected due to inverter failures
INSERT INTO meter_reading (id, project_id, meter_id, meter_type_id, value, reading_timestamp, created_at) 
SELECT 
    generate_series(1, 720) as id,
    1 as project_id,
    1 as meter_id,
    1 as meter_type_id,
    -- Simulating reduced production: normal would be ~200 kWh/hour during day, but we have failures
    CASE 
        WHEN EXTRACT(hour FROM timestamp_val) BETWEEN 6 AND 18 THEN 
            RANDOM() * 150 + 50  -- Reduced production during daylight
        ELSE 0 
    END as value,
    timestamp_val as reading_timestamp,
    timestamp_val + interval '1 minute' as created_at
FROM generate_series(
    '2024-11-01 00:00:00'::timestamp,
    '2024-11-30 23:00:00'::timestamp,
    interval '1 hour'
) as timestamp_val;

-- Meter Aggregate for November 2024
INSERT INTO meter_aggregate (id, billing_period_id, meter_id, data_source_id, 
                            total_production, total_consumption, peak, off_peak, unit, created_at) VALUES
(1, 1, 1, 1,
 4850000.00,  -- 4.85 GWh produced (below expected 5.2 GWh for 95%+ availability)
 0,
 2100000.00,
 2750000.00,
 'kWh',
 '2024-12-01 08:00:00+00');

-- =====================================================
-- 8. EVENTS & FAULTS
-- =====================================================

-- Event Types
INSERT INTO event_type (id, name, code, description, created_at) VALUES
(1, 'Equipment Failure', 'EQUIP_FAIL', 'Asset or component failure event', '2023-01-10 10:00:00+00'),
(2, 'Underperformance', 'UNDERPERF', 'Production below expected levels', '2023-01-10 10:00:00+00'),
(3, 'Grid Outage', 'GRID_OUTAGE', 'Utility grid outage preventing export', '2023-01-10 10:00:00+00');

-- Fault Types
INSERT INTO fault_type (id, name, code, description, created_at) VALUES
(1, 'Inverter Failure', 'INV_FAIL', 'Central inverter offline or fault', '2023-01-10 10:00:00+00'),
(2, 'Communication Loss', 'COMM_LOSS', 'Loss of communication with equipment', '2023-01-10 10:00:00+00');

-- Fault (Inverter failure causing availability issue)
INSERT INTO fault (id, project_id, asset_id, data_source_id, fault_type_id, 
                  description, severity, time_start, time_end, metadata_detail, created_at) VALUES
(1, 1, 1, 1, 1,
 'Central Inverter 1 - AC Contactor Failure',
 'high',
 '2024-11-08 14:30:00+00',
 '2024-11-12 16:45:00+00',
 '{"fault_code": "E3041", "alarm_description": "AC contactor failure", "power_loss_mw": 2.5, "root_cause": "Component wear"}'::jsonb,
 '2024-11-08 14:35:00+00');

-- Event (Equipment failure event)
INSERT INTO event (id, project_id, organization_id, data_source_id, event_type_id,
                  description, raw_data, metric_outcome, 
                  time_start, time_acknowledged, time_fixed, time_end, status,
                  created_at, updated_at, created_by, updated_by) VALUES
(1, 1, 1, 1, 1,
 'Inverter 1 AC Contactor Failure - 4.2 days outage',
 '{"scada_alarm": "E3041", "location": "Central Inverter 1", "initial_operator": "John Smith"}'::jsonb,
 '{"downtime_hours": 100.25, "energy_loss_kwh": 250625, "availability_impact": 3.5}'::jsonb,
 '2024-11-08 14:30:00+00',
 '2024-11-08 14:45:00+00',
 '2024-11-12 16:45:00+00',
 '2024-11-12 17:00:00+00',
 'closed',
 '2024-11-08 14:35:00+00',
 '2024-11-12 17:00:00+00',
 'scada@greenpower.com',
 'ops@greenpower.com');

-- =====================================================
-- 9. DEFAULT EVENT
-- =====================================================

-- Default Event Types
INSERT INTO default_event_type (id, name, code, description, created_at) VALUES
(1, 'Availability Below Guarantee', 'AVAIL_DEFAULT', 'Plant availability falls below contractual guarantee', '2023-01-10 10:00:00+00'),
(2, 'Performance Ratio Default', 'PR_DEFAULT', 'Performance ratio below guarantee', '2023-01-10 10:00:00+00'),
(3, 'Delayed Response', 'DELAY_DEFAULT', 'Contractor response time exceeds SLA', '2023-01-10 10:00:00+00');

-- Default Event (Availability shortfall)
INSERT INTO default_event (id, project_id, organization_id, contract_id, event_id, default_event_type_id,
                          description, metadata_detail, cure_deadline, 
                          time_start, time_acknowledged, time_cured, status,
                          created_at, updated_at, created_by, updated_by) VALUES
(1, 1, 1, 1, 1, 1,
 'November 2024 Availability Shortfall - 91.5% vs 95% Guarantee',
 '{
   "calculation_period": "2024-11-01 to 2024-11-30",
   "total_hours": 720,
   "actual_operating_hours": 619.75,
   "excused_outage_hours": 0,
   "availability_achieved": 91.5,
   "availability_guaranteed": 95.0,
   "shortfall_percentage_points": 3.5,
   "affected_clauses": [1],
   "root_cause_event_ids": [1],
   "contractor_responsible": true,
   "contractor_id": 2
 }'::jsonb,
 '2024-12-15 23:59:59+00',
 '2024-12-01 08:00:00+00',
 '2024-12-02 10:30:00+00',
 NULL,
 'open',
 '2024-12-01 08:00:00+00',
 '2024-12-02 10:30:00+00',
 'compliance@greenpower.com',
 'compliance@greenpower.com');

-- =====================================================
-- 10. RULE OUTPUTS
-- =====================================================

-- Rule Output Types
INSERT INTO rule_output_type (id, name, code, description, created_at) VALUES
(1, 'Liquidated Damages', 'LD', 'Contractual liquidated damages payment', '2023-01-10 10:00:00+00'),
(2, 'Performance Bonus', 'BONUS', 'Performance-based bonus payment', '2023-01-10 10:00:00+00'),
(3, 'Invoice Adjustment', 'INV_ADJ', 'Adjustment to standard invoice amount', '2023-01-10 10:00:00+00');

-- Rule Output (Liquidated damages calculation)
INSERT INTO rule_output (id, project_id, default_event_id, clause_id, rule_output_type_id, currency_id,
                        description, metadata_detail, ld_amount, invoice_adjustment, breach, excuse,
                        created_at, updated_at, created_by, updated_by) VALUES
(1, 1, 1, 1, 1, 1,
 'LD for 3.5% Availability Shortfall - November 2024',
 '{
   "calculation_method": "per_percentage_point",
   "ld_rate_per_point": 50000,
   "shortfall_points": 3.5,
   "calculation": "3.5 × $50,000 = $175,000",
   "applies_to_contract": 1,
   "applies_to_counterparty": 1,
   "invoice_impact": "credit_to_buyer",
   "prorated": false
 }'::jsonb,
 175000.00,  -- $50k per point × 3.5 points
 -175000.00, -- Negative adjustment reduces invoice to off-taker
 true,
 false,
 '2024-12-02 11:00:00+00',
 '2024-12-02 11:00:00+00',
 'compliance@greenpower.com',
 'compliance@greenpower.com');

-- =====================================================
-- 11. NOTIFICATIONS
-- =====================================================

-- Notification Types
INSERT INTO notification_type (id, name, code, description, created_at) VALUES
(1, 'Default Event Alert', 'DEFAULT_ALERT', 'Notification of contract default event', '2023-01-10 10:00:00+00'),
(2, 'Invoice Ready', 'INV_READY', 'Invoice ready for review', '2023-01-10 10:00:00+00'),
(3, 'Payment Due', 'PMT_DUE', 'Payment due date reminder', '2023-01-10 10:00:00+00');

-- Notifications
INSERT INTO notification (id, organization_id, project_id, default_event_id, rule_output_id, notification_type_id,
                         description, metadata_detail, time_notified, time_due, created_at) VALUES
(1, 1, 1, 1, 1, 1,
 'Default Event: Availability Shortfall - SunValley Solar - November 2024',
 '{
   "recipient_email": "compliance@greenpower.com",
   "recipient_role": "Compliance Officer",
   "subject": "Default Event: Availability Shortfall - SunValley Solar - November 2024",
   "message_body": "A default event has been detected for SunValley Solar Farm. Plant availability for November 2024 was 91.5%, falling below the 95% guarantee. Liquidated damages of $175,000 apply per Contract Section 4.2. Please review and acknowledge.",
   "priority": "high",
   "notification_channel": ["email", "dashboard"],
   "requires_acknowledgment": true
 }'::jsonb,
 '2024-12-02 11:15:00+00',
 '2024-12-02 17:00:00+00',
 '2024-12-02 11:15:00+00'),
(2, 2, 1, 1, 1, 1,
 'Notice: Availability Credit - November 2024 Invoice',
 '{
   "recipient_email": "energy@techcorp.com",
   "recipient_organization": "TechCorp Industries",
   "subject": "Notice: Availability Credit - November 2024 Invoice",
   "message_body": "Dear TechCorp, per our PPA Section 4.2, a $175,000 credit will be applied to your November 2024 invoice due to availability shortfall (91.5% vs 95% guarantee). Detailed calculation available upon request.",
   "priority": "medium",
   "notification_channel": ["email"],
   "contract_reference": "Section 4.2",
   "credit_amount": 175000,
   "invoice_impact": "credit_applied"
 }'::jsonb,
 '2024-12-02 11:20:00+00',
 NULL,
 '2024-12-02 11:20:00+00'),
(3, 1, 1, 1, 1, 1,
 'URGENT: Performance Issue - Availability Shortfall November 2024',
 '{
   "recipient_email": "billing@solarmaint.com",
   "recipient_organization": "SolarMaint Services LLC",
   "recipient_type": "contractor",
   "subject": "URGENT: Performance Issue - Availability Shortfall November 2024",
   "message_body": "SolarMaint Services: Plant availability fell to 91.5% in November 2024 due to 4.2-day inverter outage. This resulted in $175,000 LD to off-taker. Per O&M contract Schedule A Section 2.1, please explain root cause and remediation plan. Potential backcharge may apply.",
   "priority": "urgent",
   "notification_channel": ["email", "registered_mail"],
   "requires_response": true,
   "response_deadline": "2024-12-09T23:59:59Z",
   "contract_reference": "Schedule A Section 2.1",
   "potential_liability": 175000,
   "action_required": "root_cause_analysis_and_remediation_plan"
 }'::jsonb,
 '2024-12-02 11:25:00+00',
 '2024-12-09 23:59:59+00',
 '2024-12-02 11:25:00+00');

-- =====================================================
-- 12. INVOICES TO OFF-TAKER (PPA)
-- =====================================================

-- Invoice Line Item Types
INSERT INTO invoice_line_item_type (id, name, code, description, created_at) VALUES
(1, 'Energy Delivered', 'ENERGY', 'Charge for electricity delivered', '2023-01-10 10:00:00+00'),
(2, 'Capacity Payment', 'CAPACITY', 'Fixed capacity payment', '2023-01-10 10:00:00+00'),
(3, 'Liquidated Damages Credit', 'LD_CREDIT', 'Credit for liquidated damages', '2023-01-10 10:00:00+00'),
(4, 'O&M Service Fee', 'OM_FEE', 'Operations and maintenance fee', '2023-01-10 10:00:00+00');

-- Invoice Header (to off-taker)
INSERT INTO invoice_header (id, project_id, contract_id, billing_period_id, counterparty_id, currency_id,
                           invoice_number, invoice_date, due_date, total_amount, status, created_at) VALUES
(1, 1, 1, 1, 1, 1,
 'INV-2024-11-001',
 '2024-12-03',
 '2024-12-31',
 43250.00,  -- $218,250 energy - $175,000 LD credit = $43,250
 'verified',
 '2024-12-03 09:00:00+00');

-- Invoice Line Items (to off-taker)
INSERT INTO invoice_line_item (id, invoice_header_id, rule_output_id, clause_tariff_id, meter_aggregate_id,
                              invoice_line_item_type_id, description, quantity, line_unit_price, line_total_amount,
                              created_at) VALUES
(1, 1, NULL, 1, 1, 1,
 'Energy Delivered - November 2024',
 4850000.00,  -- kWh
 0.045,
 218250.00,
 '2024-12-03 09:00:00+00'),
(2, 1, 1, NULL, NULL, 3,
 'Availability LD Credit - 91.5% vs 95% Guarantee',
 1,
 -175000.00,
 -175000.00,
 '2024-12-03 09:00:00+00');

-- =====================================================
-- 13. INVOICES FROM CONTRACTOR (O&M)
-- =====================================================

-- Expected Invoice (what we calculate contractor should bill)
INSERT INTO expected_invoice_header (id, project_id, contract_id, billing_period_id, counterparty_id, currency_id,
                                    total_amount, created_at) VALUES
(1, 1, 2, 1, 2, 1,
 85000.00,  -- Standard monthly fee (before any performance deductions)
 '2024-12-01 10:00:00+00');

-- Expected Invoice Line Items
INSERT INTO expected_invoice_line_item (id, expected_invoice_header_id, invoice_line_item_type_id,
                                       description, line_total_amount, created_at) VALUES
(1, 1, 4,
 'Monthly O&M Service Fee - November 2024',
 85000.00,
 '2024-12-01 10:00:00+00');

-- Received Invoice (what contractor actually submitted)
INSERT INTO received_invoice_header (id, project_id, contract_id, billing_period_id, counterparty_id, currency_id,
                                    invoice_number, invoice_date, due_date, total_amount, status, created_at) VALUES
(1, 1, 2, 1, 2, 1,
 'SM-2024-11-050',
 '2024-12-02',
 '2025-01-01',
 85000.00,  -- Contractor billed full amount despite availability issue
 'disputed',
 '2024-12-02 15:00:00+00');

-- Received Invoice Line Items
INSERT INTO received_invoice_line_item (id, received_invoice_header_id, invoice_line_item_type_id,
                                       description, line_total_amount, created_at) VALUES
(1, 1, 4,
 'Monthly Service Fee - November 2024',
 85000.00,
 '2024-12-02 15:00:00+00');

-- Invoice Comparison
INSERT INTO invoice_comparison (id, expected_invoice_header_id, received_invoice_header_id, 
                               variance_amount, status, created_at) VALUES
(1, 1, 1,
 0.00,  -- No variance on face amount, but context matters
 'matched',  -- Amounts match, but need to discuss performance issue
 '2024-12-02 16:00:00+00');

-- Invoice Comparison Line Item
INSERT INTO invoice_comparison_line_item (id, invoice_comparison_id, expected_invoice_line_item_id,
                                         received_invoice_line_item_id, variance_amount, description, created_at) VALUES
(1, 1, 1, 1,
 0.00,
 'Line amounts match. However, per Schedule A Section 2.1, contractor may be liable for $175,000 LD passthrough due to availability failure caused by delayed inverter repair. Pending investigation and contractor response.',
 '2024-12-02 16:00:00+00');

-- =====================================================
-- 14. CONTRACTOR REPORT
-- =====================================================

INSERT INTO contractor_report (id, project_id, counterparty_id, raw_text, metadata_detail, 
                              file_location, created_at) VALUES
(1, 1, 2,
 'Monthly O&M Report - November 2024. Inverter 1 experienced AC contactor failure on 11/8. Spare part ordered same day but supplier delivery delayed until 11/12. Unit restored to service 11/12 at 16:45. Total downtime: 100.25 hours. Recommended preventive replacement of Inverter 2 contactor (showing wear).',
 '{
   "report_type": "monthly_om",
   "report_period": "2024-11",
   "total_site_visits": 8,
   "corrective_maintenance_events": 1,
   "preventive_maintenance_completed": true,
   "parts_replaced": ["AC Contactor - ABB Part #XYZ-123"],
   "equipment_downtime_hours": 100.25,
   "recommendations": ["Replace Inverter 2 contactor preventively"]
 }'::jsonb,
 '/reports/solarmaint/2024/november_om_report.pdf',
 '2024-12-01 17:00:00+00');

-- =====================================================
-- 15. ADDITIONAL CONTEXT DATA
-- =====================================================

-- Grid Events (none during November - no excused outages)
INSERT INTO grid_event_type (id, name, code, description, created_at) VALUES
(1, 'Transmission Outage', 'TRANS_OUT', 'Transmission line outage', '2023-01-10 10:00:00+00'),
(2, 'Curtailment Order', 'CURTAIL', 'Grid operator curtailment instruction', '2023-01-10 10:00:00+00');

INSERT INTO grid_operator (id, name, address, country, created_at) VALUES
(1, 'Texas Grid Operator', 'Austin, TX', 'USA', '2023-01-10 10:00:00+00');

-- Weather Data Type
INSERT INTO weather_data_type (id, name, code, description, updated_frequency, created_at) VALUES
(1, 'Solar Irradiance', 'GHI', 'Global Horizontal Irradiance', '15min', '2023-01-10 10:00:00+00'),
(2, 'Temperature', 'TEMP', 'Ambient temperature', '15min', '2023-01-10 10:00:00+00');

-- Sample weather data showing normal conditions (no weather-related excuses)
INSERT INTO weather_data (id, weather_data_type_id, country, region, source, unit, unit_value, 
                         reading_timestamp, created_at)
SELECT 
    generate_series(1, 120) as id,
    1 as weather_data_type_id,
    'USA' as country,
    'Texas' as region,
    'OnSite WeatherStation' as source,
    'W/m2' as unit,
    CASE 
        WHEN EXTRACT(hour FROM timestamp_val) BETWEEN 7 AND 17 THEN 
            RANDOM() * 400 + 400  -- Normal irradiance 400-800 W/m2
        ELSE 0
    END as unit_value,
    timestamp_val as reading_timestamp,
    timestamp_val as created_at
FROM generate_series(
    '2024-11-08 00:00:00'::timestamp,
    '2024-11-12 23:00:00'::timestamp,
    interval '1 hour'
) as timestamp_val;

COMMIT;

-- =====================================================
-- SUMMARY OF TEST SCENARIO
-- =====================================================
/*
TEST FLOW DEMONSTRATED:

1. EVENT DETECTION:
   - Inverter failure occurs (11/8 - 11/12)
   - SCADA system logs fault and downtime
   - Event recorded with 100.25 hour outage

2. DEFAULT EVENT TRIGGERED:
   - Monthly availability calculated: 91.5% vs 95% guarantee
   - Default event created automatically
   - Shortfall: 3.5 percentage points

3. RULE ENGINE CALCULATES PENALTY:
   - Clause 1 (PPA): $50,000 per point × 3.5 = $175,000 LD
   - Rule output generated
   - Linked to default event and triggering clause

4. NOTIFICATIONS SENT:
   - Internal compliance team alerted
   - Off-taker (TechCorp) notified of credit
   - Contractor (SolarMaint) notified of performance issue

5. INVOICE TO OFF-TAKER ADJUSTED:
   - Energy charge: $218,250 (4.85 GWh × $0.045)
   - LD credit: -$175,000
   - Net invoice: $43,250
   - Status: verified

6. CONTRACTOR INVOICE CROSS-CHECK:
   - Contractor billed $85,000 (full monthly fee)
   - System compares against expected $85,000
   - Amounts match but system flags:
     * Performance failure in November
     * Potential LD passthrough per O&M contract
     * Invoice marked "disputed" pending resolution

7. AUDIT TRAIL:
   - Complete linkage: Event → Default → Rule Output → Invoice Adjustment
   - Contractor report provides context
   - Weather data confirms no excusable conditions

QUERIES TO TEST:
- Find all default events for a project and period
- Calculate total LD impact on off-taker invoices
- Identify contractor performance issues
- Generate compliance reports
- Track event → financial impact chain
*/
