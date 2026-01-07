// lib/testQueries.ts
// Test queries for Contract Compliance & Invoicing Engine

export type TestQuery = {
  id: number;
  title: string;
  description: string;
  sql: string;
};

export const testQueries: TestQuery[] = [
  {
    id: 1,
    title: "Complete Event → Default → Rule → Invoice Chain",
    description: "Shows the full flow from physical event to financial impact, tracking how an equipment failure triggers default events, rule outputs, and invoice adjustments.",
    sql: `SELECT
    e.id as event_id,
    e.description as event_description,
    e.time_start as event_start,
    e.time_end as event_end,
    (e.metric_outcome ->> 'downtime_hours')::decimal as downtime_hours,
    de.id as default_event_id,
    de.description as default_description,
    (de.metadata_detail ->> 'availability_achieved')::decimal as availability_achieved,
    (de.metadata_detail ->> 'availability_guaranteed')::decimal as availability_guaranteed,
    (de.metadata_detail ->> 'shortfall_percentage_points')::decimal as shortfall_points,
    c.name as clause_name,
    c.section_ref,
    (c.normalized_payload ->> 'ld_per_point')::decimal as ld_per_point,
    ro.id as rule_output_id,
    ro.ld_amount,
    ro.invoice_adjustment,
    ih.invoice_number,
    ih.invoice_date,
    ih.total_amount as invoice_total,
    ili.description as line_item_description,
    ili.line_total_amount
FROM event e
JOIN default_event de ON de.event_id = e.id
JOIN clause c ON c.id = ANY(
    SELECT jsonb_array_elements_text(de.metadata_detail -> 'affected_clauses')::bigint
)
JOIN rule_output ro ON ro.default_event_id = de.id AND ro.clause_id = c.id
JOIN invoice_line_item ili ON ili.rule_output_id = ro.id
JOIN invoice_header ih ON ili.invoice_header_id = ih.id
WHERE e.project_id = 1
    AND e.time_start >= '2024-11-01'
    AND e.time_start < '2024-12-01'
ORDER BY e.time_start;`
  },
  {
    id: 2,
    title: "Default Event Summary with Financial Impact",
    description: "Summary view of all default events showing their type, status, affected contracts, counterparties, and total financial impact including liquidated damages.",
    sql: `SELECT
    de.id,
    de.description,
    det.name as default_type,
    de.time_start,
    de.status,
    ct.name as contract_name,
    cp.name as counterparty_name,
    COUNT(ro.id) as rule_outputs_count,
    SUM(ro.ld_amount) as total_ld_amount,
    SUM(ro.invoice_adjustment) as total_invoice_adjustment,
    STRING_AGG(DISTINCT e.description, '; ') as related_events
FROM default_event de
JOIN default_event_type det ON de.default_event_type_id = det.id
JOIN contract ct ON de.contract_id = ct.id
JOIN counterparty cp ON ct.counterparty_id = cp.id
LEFT JOIN rule_output ro ON ro.default_event_id = de.id
LEFT JOIN event e ON de.event_id = e.id
WHERE de.project_id = 1
GROUP BY de.id, de.description, det.name, de.time_start, de.status, ct.name, cp.name
ORDER BY de.time_start DESC;`
  },
  {
    id: 3,
    title: "Invoice to Off-Taker with Line Item Details",
    description: "Complete invoice breakdown showing energy charges, liquidated damage credits, and other adjustments with references to triggering contract clauses.",
    sql: `SELECT
    ih.invoice_number,
    ih.invoice_date,
    ih.due_date,
    ih.status,
    cp.name as billed_to,
    cu.code as currency,
    bp.name as billing_period,
    ilit.name as line_item_type,
    ili.description,
    ili.quantity,
    ili.line_unit_price,
    ili.line_total_amount,
    ro.description as rule_output_description,
    c.section_ref as clause_reference,
    ih.total_amount as invoice_total
FROM invoice_header ih
JOIN counterparty cp ON ih.counterparty_id = cp.id
JOIN currency cu ON ih.currency_id = cu.id
JOIN billing_period bp ON ih.billing_period_id = bp.id
JOIN invoice_line_item ili ON ili.invoice_header_id = ih.id
JOIN invoice_line_item_type ilit ON ili.invoice_line_item_type_id = ilit.id
LEFT JOIN rule_output ro ON ili.rule_output_id = ro.id
LEFT JOIN clause c ON ro.clause_id = c.id
WHERE ih.project_id = 1 AND bp.start_date >= '2024-11-01'
ORDER BY ih.invoice_date, ili.id;`
  },
  {
    id: 4,
    title: "Contractor Invoice Comparison & Discrepancies",
    description: "Compares expected vs. received contractor invoices, highlighting variances and linking to related default events and contractor responsibility.",
    sql: `SELECT
    ic.id as comparison_id,
    ct.name as contract_name,
    cp.name as contractor_name,
    bp.name as billing_period,
    eih.total_amount as expected_amount,
    eili.description as expected_line_description,
    eili.line_total_amount as expected_line_amount,
    rih.invoice_number as received_invoice_number,
    rih.total_amount as received_amount,
    rili.description as received_line_description,
    rili.line_total_amount as received_line_amount,
    ic.status as comparison_status,
    ic.variance_amount as header_variance,
    icli.variance_amount as line_variance,
    icli.description as variance_notes,
    de.description as related_default_event,
    (de.metadata_detail ->> 'contractor_responsible')::boolean as contractor_responsible
FROM invoice_comparison ic
JOIN expected_invoice_header eih ON ic.expected_invoice_header_id = eih.id
JOIN received_invoice_header rih ON ic.received_invoice_header_id = rih.id
JOIN contract ct ON eih.contract_id = ct.id
JOIN counterparty cp ON ct.counterparty_id = cp.id
JOIN billing_period bp ON eih.billing_period_id = bp.id
LEFT JOIN expected_invoice_line_item eili ON eili.expected_invoice_header_id = eih.id
LEFT JOIN received_invoice_line_item rili ON rili.received_invoice_header_id = rih.id
LEFT JOIN invoice_comparison_line_item icli ON icli.invoice_comparison_id = ic.id
LEFT JOIN default_event de ON de.contract_id = ct.id
    AND de.time_start >= bp.start_date
    AND de.time_start <= bp.end_date
WHERE eih.project_id = 1
ORDER BY bp.start_date DESC, ic.id;`
  },
  {
    id: 5,
    title: "Notifications Log with Recipients",
    description: "Tracks all notifications sent for default events, showing recipients, priorities, delivery times, and action requirements.",
    sql: `SELECT
    n.id,
    n.time_notified,
    n.time_due,
    nt.name as notification_type,
    n.description,
    n.metadata_detail ->> 'recipient_email' as recipient_email,
    n.metadata_detail ->> 'recipient_organization' as recipient_organization,
    n.metadata_detail ->> 'recipient_role' as recipient_role,
    n.metadata_detail ->> 'priority' as priority,
    n.metadata_detail ->> 'subject' as subject,
    LEFT(n.metadata_detail ->> 'message_body', 100) as message_preview,
    o.name as notifying_organization,
    p.name as project_name,
    de.description as default_event,
    det.name as default_type,
    ro.ld_amount as associated_ld_amount,
    n.metadata_detail ->> 'requires_acknowledgment' as requires_acknowledgment,
    n.metadata_detail ->> 'requires_response' as requires_response,
    n.metadata_detail ->> 'response_deadline' as response_deadline
FROM notification n
JOIN notification_type nt ON n.notification_type_id = nt.id
LEFT JOIN organization o ON n.organization_id = o.id
LEFT JOIN project p ON n.project_id = p.id
LEFT JOIN default_event de ON n.default_event_id = de.id
LEFT JOIN default_event_type det ON de.default_event_type_id = det.id
LEFT JOIN rule_output ro ON n.rule_output_id = ro.id
WHERE n.project_id = 1
ORDER BY n.time_notified DESC;`
  },
  {
    id: 6,
    title: "Availability Calculation Verification",
    description: "Verifies the availability calculation that triggered the default, showing total hours, outage hours, production, and calculated vs. guaranteed availability.",
    sql: `SELECT
    bp.name as period,
    bp.start_date,
    bp.end_date,
    EXTRACT(EPOCH FROM (bp.end_date - bp.start_date + INTERVAL '1 day'))/3600 as total_hours,
    ma.total_production as actual_production_kwh,
    SUM(COALESCE(EXTRACT(EPOCH FROM (e.time_end - e.time_start))/3600, 0)) as total_outage_hours,
    (de.metadata_detail ->> 'availability_achieved')::decimal as calculated_availability,
    (de.metadata_detail ->> 'availability_guaranteed')::decimal as guaranteed_availability,
    (de.metadata_detail ->> 'shortfall_percentage_points')::decimal as shortfall
FROM billing_period bp
JOIN meter_aggregate ma ON ma.billing_period_id = bp.id
LEFT JOIN event e ON e.project_id = 1
    AND e.time_start >= bp.start_date
    AND e.time_start <= bp.end_date
LEFT JOIN default_event de ON de.time_start >= bp.start_date
    AND de.time_start <= bp.end_date
WHERE bp.id = 1
GROUP BY bp.name, bp.start_date, bp.end_date, ma.total_production, de.metadata_detail;`
  },
  {
    id: 7,
    title: "Clause Analysis - Most Triggered Clauses",
    description: "Identifies problem clauses showing how often they're breached, their financial impact, and trends over time.",
    sql: `SELECT
    c.name as clause_name,
    c.section_ref,
    ct.name as contract_name,
    cc.name as clause_category,
    cty.name as clause_type,
    COUNT(DISTINCT de.id) as times_breached,
    COUNT(DISTINCT ro.id) as rule_outputs_generated,
    SUM(ro.ld_amount) as total_ld_amount,
    AVG(ro.ld_amount) as avg_ld_per_breach,
    MIN(ro.ld_amount) as min_ld_amount,
    MAX(ro.ld_amount) as max_ld_amount,
    MAX(de.time_start) as most_recent_breach
FROM clause c
JOIN contract ct ON c.contract_id = ct.id
JOIN clause_category cc ON c.clause_category_id = cc.id
JOIN clause_type cty ON c.clause_type_id = cty.id
LEFT JOIN rule_output ro ON ro.clause_id = c.id
LEFT JOIN default_event de ON ro.default_event_id = de.id
WHERE c.project_id = 1
GROUP BY c.name, c.section_ref, ct.name, cc.name, cty.name
HAVING COUNT(DISTINCT de.id) > 0
ORDER BY total_ld_amount DESC, times_breached DESC;`
  },
  {
    id: 8,
    title: "Contractor Performance Scorecard",
    description: "Evaluates contractor performance based on events caused, financial exposure, and invoice verification accuracy.",
    sql: `SELECT
    cp.name as contractor,
    ct.name as contract,
    COUNT(DISTINCT CASE WHEN (de.metadata_detail ->> 'contractor_responsible')::boolean = true THEN de.id END) as defaults_caused,
    COUNT(DISTINCT e.id) as total_events,
    SUM(CASE WHEN (de.metadata_detail ->> 'contractor_responsible')::boolean = true THEN ro.ld_amount ELSE 0 END) as ld_exposure,
    SUM(rih.total_amount) as total_invoiced,
    COUNT(DISTINCT ic.id) as invoice_comparisons,
    COUNT(DISTINCT CASE WHEN ic.status = 'matched' THEN ic.id END) as matched_invoices,
    COUNT(DISTINCT CASE WHEN ic.status IN ('underbilled', 'overbilled') THEN ic.id END) as discrepant_invoices
FROM counterparty cp
JOIN contract ct ON ct.counterparty_id = cp.id
LEFT JOIN default_event de ON (de.metadata_detail ->> 'contractor_id')::bigint = cp.id
LEFT JOIN event e ON de.event_id = e.id
LEFT JOIN rule_output ro ON ro.default_event_id = de.id
LEFT JOIN received_invoice_header rih ON rih.counterparty_id = cp.id
LEFT JOIN invoice_comparison ic ON ic.received_invoice_header_id = rih.id
WHERE cp.counterparty_type_id = 2 AND ct.project_id = 1
GROUP BY cp.name, ct.name;`
  },
  {
    id: 9,
    title: "Monthly Financial Summary",
    description: "Executive summary showing revenue from off-taker, contractor costs, liquidated damage credits, and net position by month.",
    sql: `SELECT
    bp.name as billing_period,
    bp.start_date,
    bp.end_date,
    SUM(CASE WHEN ct.contract_type_id = 1 AND ili.invoice_line_item_type_id = 1 THEN ili.line_total_amount ELSE 0 END) as energy_revenue,
    SUM(CASE WHEN ct.contract_type_id = 1 AND ili.invoice_line_item_type_id = 3 THEN ili.line_total_amount ELSE 0 END) as ld_credits_applied,
    SUM(CASE WHEN ct.contract_type_id = 1 THEN ih.total_amount ELSE 0 END) as net_revenue_from_offtaker,
    SUM(CASE WHEN ct.contract_type_id = 2 THEN rih.total_amount ELSE 0 END) as contractor_costs,
    SUM(CASE WHEN ct.contract_type_id = 1 THEN ih.total_amount WHEN ct.contract_type_id = 2 THEN -rih.total_amount ELSE 0 END) as net_position,
    MAX(ma.total_production) as energy_produced_kwh,
    COUNT(DISTINCT de.id) as default_events_count
FROM billing_period bp
LEFT JOIN invoice_header ih ON ih.billing_period_id = bp.id
LEFT JOIN contract ct ON ih.contract_id = ct.id
LEFT JOIN invoice_line_item ili ON ili.invoice_header_id = ih.id
LEFT JOIN received_invoice_header rih ON rih.billing_period_id = bp.id
LEFT JOIN meter_aggregate ma ON ma.billing_period_id = bp.id
LEFT JOIN default_event de ON de.time_start >= bp.start_date AND de.time_start <= bp.end_date
GROUP BY bp.name, bp.start_date, bp.end_date
ORDER BY bp.start_date DESC;`
  },
  {
    id: 10,
    title: "Audit Trail - Complete Transaction History",
    description: "Full audit trail for a specific default event showing all related records chronologically: events, rule outputs, notifications, and invoices.",
    sql: `WITH default_detail AS (
    SELECT de.id as default_id, de.description, de.time_start, de.created_at, de.created_by,
           de.updated_at, de.updated_by, de.status, det.name as default_type
    FROM default_event de
    JOIN default_event_type det ON de.default_event_type_id = det.id
    WHERE de.id = 1
)
SELECT 'Default Event' as record_type, dd.default_id::text as record_id, dd.description,
       dd.created_at as timestamp, dd.created_by as user_action,
       jsonb_build_object('status', dd.status, 'default_type', dd.default_type) as details
FROM default_detail dd
UNION ALL
SELECT 'Related Event', e.id::text, e.description, e.created_at, e.created_by,
       jsonb_build_object('event_type', et.name, 'downtime_hours', e.metric_outcome->'downtime_hours', 'status', e.status)
FROM event e
JOIN event_type et ON e.event_type_id = et.id
WHERE e.id = (SELECT event_id FROM default_event WHERE id = 1)
UNION ALL
SELECT 'Rule Output', ro.id::text, ro.description, ro.created_at, ro.created_by,
       jsonb_build_object('ld_amount', ro.ld_amount, 'invoice_adjustment', ro.invoice_adjustment, 'clause_id', ro.clause_id)
FROM rule_output ro
WHERE ro.default_event_id = 1
UNION ALL
SELECT 'Notification', n.id::text, n.description, n.time_notified, n.metadata_detail->>'recipient_email',
       jsonb_build_object('notification_type', nt.name, 'priority', n.metadata_detail->>'priority',
                         'recipient_organization', n.metadata_detail->>'recipient_organization',
                         'time_due', n.time_due, 'requires_response', n.metadata_detail->>'requires_response')
FROM notification n
JOIN notification_type nt ON n.notification_type_id = nt.id
WHERE n.default_event_id = 1
UNION ALL
SELECT 'Invoice Line Item', ili.id::text, ili.description, ili.created_at, ih.invoice_number,
       jsonb_build_object('quantity', ili.quantity, 'unit_price', ili.line_unit_price, 'total', ili.line_total_amount, 'invoice_number', ih.invoice_number)
FROM invoice_line_item ili
JOIN invoice_header ih ON ili.invoice_header_id = ih.id
WHERE ili.rule_output_id IN (SELECT id FROM rule_output WHERE default_event_id = 1)
ORDER BY timestamp;`
  },
  {
    id: 11,
    title: "Notification Response Tracking",
    description: "Tracks notifications requiring responses, showing which are overdue, due soon, or on-time with action requirements and potential liability.",
    sql: `SELECT
    n.id as notification_id,
    n.time_notified,
    n.time_due as response_due,
    CASE
        WHEN n.time_due < NOW() THEN 'OVERDUE'
        WHEN n.time_due < NOW() + INTERVAL '24 hours' THEN 'DUE_SOON'
        ELSE 'ON_TIME'
    END as status,
    n.metadata_detail ->> 'recipient_email' as recipient,
    n.metadata_detail ->> 'recipient_organization' as organization,
    n.metadata_detail ->> 'priority' as priority,
    (n.metadata_detail ->> 'requires_acknowledgment')::boolean as requires_ack,
    (n.metadata_detail ->> 'requires_response')::boolean as requires_response,
    n.metadata_detail ->> 'action_required' as action_required,
    nt.name as notification_type,
    n.description as notification_description,
    de.description as related_default_event,
    (n.metadata_detail ->> 'potential_liability')::numeric as potential_liability,
    n.metadata_detail ->> 'contract_reference' as contract_ref
FROM notification n
JOIN notification_type nt ON n.notification_type_id = nt.id
LEFT JOIN default_event de ON n.default_event_id = de.id
WHERE n.project_id = 1
    AND ((n.metadata_detail ->> 'requires_acknowledgment')::boolean = true
         OR (n.metadata_detail ->> 'requires_response')::boolean = true)
ORDER BY CASE WHEN n.time_due < NOW() THEN 1 WHEN n.time_due < NOW() + INTERVAL '24 hours' THEN 2 ELSE 3 END, n.time_due;`
  },
  {
    id: 12,
    title: "Notification Distribution by Type and Priority",
    description: "Analyzes notification patterns showing distribution by type, priority, recipient organization, and associated financial impacts.",
    sql: `SELECT
    nt.name as notification_type,
    n.metadata_detail ->> 'priority' as priority,
    n.metadata_detail ->> 'recipient_organization' as recipient_org,
    COUNT(*) as notification_count,
    COUNT(CASE WHEN (n.metadata_detail ->> 'requires_response')::boolean THEN 1 END) as requires_response_count,
    AVG((n.metadata_detail ->> 'potential_liability')::numeric) as avg_liability,
    SUM((n.metadata_detail ->> 'credit_amount')::numeric) as total_credits_notified,
    MIN(n.time_notified) as first_notification,
    MAX(n.time_notified) as last_notification
FROM notification n
JOIN notification_type nt ON n.notification_type_id = nt.id
WHERE n.project_id = 1
GROUP BY nt.name, n.metadata_detail ->> 'priority', n.metadata_detail ->> 'recipient_organization'
ORDER BY notification_count DESC, priority;`
  }
];
