# Contract Compliance & Invoicing Verification Engine

## Test Data Documentation

---

## Overview

This test dataset demonstrates a complete end-to-end workflow for detecting contract defaults, calculating liquidated damages, and reflecting these in invoices to both off-takers and contractors.

---

## Test Scenario Summary

### **Project:** SunValley Solar Farm - 50MW

- **Developer:** GreenPower Energy Corp
- **Location:** Texas, USA
- **Capacity:** 50 MW Solar PV

### **Contracts:**

1. **Power Purchase Agreement (PPA)**

   - Buyer: TechCorp Industries
   - Term: 2024-2043 (20 years)
   - Price: $0.045/kWh (2% annual escalation)
   - Availability Guarantee: 95% minimum
   - Liquidated Damages: $50,000 per percentage point below 95%

2. **O&M Service Agreement**
   - Contractor: SolarMaint Services LLC
   - Term: 2024-2028 (5 years)
   - Fee: $85,000/month fixed
   - SLA: Must maintain 95% availability
   - Liability: Responsible for LD passthrough if failure is due to contractor negligence

---

## Default Event: November 2024 Availability Shortfall

### **Root Cause**

- **Event:** Inverter 1 AC Contactor Failure
- **Start:** November 8, 2024 at 14:30 UTC
- **End:** November 12, 2024 at 16:45 UTC
- **Duration:** 100.25 hours (4.2 days)
- **Energy Loss:** 250,625 kWh

### **Contributing Factors**

1. Component wear in AC contactor
2. Spare part delivery delay (ordered 11/8, arrived 11/12)
3. No preventive maintenance performed on aging component

### **Performance Impact**

- **Total November Hours:** 720 hours
- **Actual Operating Hours:** 619.75 hours
- **Excused Outage Hours:** 0 (no grid events, normal weather)
- **Availability Achieved:** 91.5%
- **Availability Guaranteed:** 95.0%
- **Shortfall:** 3.5 percentage points

### **Financial Consequences**

#### To Off-Taker (TechCorp):

```
Energy Delivered: 4,850,000 kWh × $0.045/kWh = $218,250
Availability LD Credit: 3.5 points × $50,000 = ($175,000)
───────────────────────────────────────────────────────
Net Invoice Amount:                              $43,250
```

#### From Contractor (SolarMaint):

```
Monthly Service Fee:                             $85,000
Potential Backcharge (under investigation):     ($175,000)
───────────────────────────────────────────────────────
Status: Disputed - Pending contractor explanation
```

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. EVENT DETECTION                          │
│  ┌──────────────┐                                               │
│  │ SCADA System │──→ Fault Detected: Inverter AC Contactor     │
│  └──────────────┘                                               │
│         ↓                                                        │
│  ┌──────────────┐                                               │
│  │    Event     │──→ Logged: 100.25 hour outage                │
│  └──────────────┘     Fault ID: 1, Event ID: 1                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              2. AVAILABILITY CALCULATION                        │
│                                                                  │
│  Meter Readings → Aggregate for Billing Period                  │
│    • Total Hours: 720                                           │
│    • Operating Hours: 619.75                                    │
│    • Availability = 619.75 / 720 = 86.08%                       │
│    • Adjusted for Excused Outages: 0 hours                      │
│    • Final Availability: 91.5%                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│             3. DEFAULT EVENT TRIGGERED                          │
│                                                                  │
│  Compliance Engine Detects:                                     │
│    • Availability (91.5%) < Guarantee (95%)                     │
│    • Shortfall: 3.5 percentage points                          │
│    • Affected Clause: Section 4.2 (PPA)                        │
│    • Contractor Responsible: Yes (per Schedule A)               │
│                                                                  │
│  Default Event Created: ID #1                                   │
│  Status: Open (cure deadline: Dec 15, 2024)                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              4. RULE ENGINE EXECUTION                           │
│                                                                  │
│  Clause Analysis:                                               │
│    • PPA Section 4.2: Performance Guarantee                     │
│    • Formula: $50,000 per percentage point                      │
│    • Calculation: 3.5 × $50,000 = $175,000                     │
│    • Rule Output Type: Liquidated Damages                       │
│                                                                  │
│  Rule Output Created: ID #1                                     │
│    • LD Amount: $175,000                                        │
│    • Invoice Adjustment: -$175,000 (credit to buyer)           │
│    • Breach: True, Excuse: False                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              5. NOTIFICATION DISPATCH                           │
│                                                                  │
│  Three notifications sent with structured metadata:             │
│                                                                  │
│  1. Internal (Org ID: 1, Project ID: 1)                        │
│     To: compliance@greenpower.com                               │
│     Type: Default Event Alert                                   │
│     Priority: High                                              │
│     Action: Review Required (acknowledgment due same day)       │
│     Metadata: {recipient_role, priority, requires_ack...}      │
│                                                                  │
│  2. Off-Taker (Org ID: 2, Project ID: 1)                      │
│     To: energy@techcorp.com (TechCorp Industries)              │
│     Type: Default Event Alert                                   │
│     Priority: Medium                                            │
│     Content: "$175,000 credit on November invoice"             │
│     Metadata: {credit_amount, invoice_impact, contract_ref...} │
│                                                                  │
│  3. Contractor (Org ID: 1, Project ID: 1)                     │
│     To: billing@solarmaint.com (SolarMaint Services)           │
│     Type: Default Event Alert                                   │
│     Priority: Urgent                                            │
│     Action: Root cause analysis required (due Dec 9)           │
│     Metadata: {potential_liability, response_deadline...}      │
│                                                                  │
│  All notifications linked to:                                   │
│    • Default Event ID: 1                                       │
│    • Rule Output ID: 1                                         │
│    • Organization and Project context                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│           6A. INVOICE TO OFF-TAKER (PPA)                       │
│                                                                  │
│  Invoice Header: INV-2024-11-001                               │
│    • Date: Dec 3, 2024                                         │
│    • Due: Dec 31, 2024                                         │
│    • Status: Verified                                          │
│                                                                  │
│  Line Items:                                                    │
│    1. Energy Delivered                                         │
│       4,850,000 kWh × $0.045       = $218,250                 │
│                                                                  │
│    2. Availability LD Credit                                   │
│       [Linked to Rule Output #1]   = ($175,000)               │
│       Reference: PPA Section 4.2                               │
│       ──────────────────────────────────────────                │
│    TOTAL:                             $43,250                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│        6B. INVOICE VERIFICATION - CONTRACTOR (O&M)             │
│                                                                  │
│  Expected Invoice (System Calculation):                         │
│    • Monthly Fee: $85,000                                      │
│    • Potential LD Passthrough: ($175,000) [under review]      │
│                                                                  │
│  Received Invoice: SM-2024-11-050                              │
│    • Date: Dec 2, 2024                                         │
│    • Amount: $85,000                                           │
│    • Line: Monthly Service Fee                                 │
│                                                                  │
│  Comparison Result:                                             │
│    • Variance: $0 (amounts match)                              │
│    • Status: DISPUTED                                          │
│    • Reason: Per Schedule A Section 2.1, contractor may be     │
│      liable for $175k LD due to failure to maintain equipment  │
│      (inverter contactor). Pending investigation.              │
│                                                                  │
│  Action Required:                                               │
│    → Review contractor monthly report                           │
│    → Determine if failure was preventable                       │
│    → Issue backcharge if negligence confirmed                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│              7. CONTRACTOR REPORT REVIEW                        │
│                                                                  │
│  Contractor's Explanation (from monthly report):                │
│    "Inverter 1 AC contactor failed on 11/8. Spare part         │
│     ordered immediately but supplier had delivery delay.        │
│     Part arrived 11/12, unit restored same day."               │
│                                                                  │
│  Key Questions for Investigation:                               │
│    • Was preventive maintenance performed per schedule?         │
│    • Was component approaching end of life?                     │
│    • Could failure have been predicted?                         │
│    • Were spare parts maintained on-site per contract?          │
│                                                                  │
│  Recommendation in Report:                                      │
│    "Preventively replace Inverter 2 contactor (showing wear)"  │
│    → Suggests contractor was aware of aging components          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Relationships Tested

### Primary Entity Chain

```
Organization → Project → Contract → Clause → Rule Output → Invoice Line Item
     ↓            ↓          ↓
   Role         Asset      Counterparty
                 ↓
               Meter → Meter Reading → Meter Aggregate
                                           ↓
                                    Billing Period
```

### Default Event Flow

```
Event ──→ Default Event ──→ Rule Output ──→ Invoice Line Item
  ↓             ↓                ↓                  ↓
Fault      Notifications    Clause Ref       Invoice Header
  ↓                                               ↓
Asset                                       Expected Invoice
                                                  ↓
                                          Invoice Comparison
```

---

## Key Tables Populated

### Core Entities (13 tables)

- ✅ organization (2 records)
- ✅ role (3 records)
- ✅ project (1 record)
- ✅ counterparty_type (2 records)
- ✅ counterparty (2 records)
- ✅ contract_type (2 records)
- ✅ contract_status (2 records)
- ✅ contract (2 records: PPA + O&M)
- ✅ clause_responsibleparty (2 records)
- ✅ clause_type (3 records)
- ✅ clause_category (3 records)
- ✅ clause (4 records: 2 PPA clauses + 2 O&M clauses)
- ✅ currency (2 records)

### Assets & Metering (11 tables)

- ✅ vendor (3 records)
- ✅ asset_type (3 records)
- ✅ asset (2 inverters)
- ✅ meter_type (3 records)
- ✅ meter (2 meters)
- ✅ data_source (4 records)
- ✅ meter_reading (720 hourly readings for November)
- ✅ meter_aggregate (1 monthly summary)
- ✅ billing_period (1 period: November 2024)
- ✅ tariff_type (2 records)
- ✅ clause_tariff (1 energy tariff)

### Events & Defaults (8 tables)

- ✅ event_type (3 records)
- ✅ event (1 equipment failure)
- ✅ fault_type (2 records)
- ✅ fault (1 inverter failure)
- ✅ default_event_type (3 records)
- ✅ default_event (1 availability shortfall)
- ✅ rule_output_type (3 records)
- ✅ rule_output (1 LD calculation)

### Notifications (2 tables)

- ✅ notification_type (3 records)
- ✅ notification (3 sent with metadata: internal, off-taker, contractor)

### Invoicing (10 tables)

- ✅ invoice_header (1 to off-taker)
- ✅ invoice_line_item_type (4 records)
- ✅ invoice_line_item (2 lines: energy + LD credit)
- ✅ expected_invoice_header (1 from contractor)
- ✅ expected_invoice_line_item (1 line)
- ✅ received_invoice_header (1 from contractor)
- ✅ received_invoice_line_item (1 line)
- ✅ invoice_comparison (1 comparison)
- ✅ invoice_comparison_line_item (1 line comparison)
- ✅ contractor_report (1 monthly report)

### Contextual Data (8 tables)

- ✅ grid_event_type (2 records)
- ✅ grid_operator (1 record)
- ✅ weather_data_type (2 records)
- ✅ weather_data (120 readings showing normal conditions)
- ⬜ grid_event (0 - no grid outages)
- ⬜ regulatory_fee_type (0 - not relevant to scenario)
- ⬜ market_price_type (0 - not relevant to scenario)

---

## Test Coverage

### ✅ Fully Tested Workflows

1. **Event Detection → Default Logging**

   - Physical fault captured in SCADA
   - Downtime tracked with timestamps
   - Event linked to project and assets

2. **Availability Calculation**

   - Hourly meter readings aggregated
   - Outage hours accumulated
   - Availability percentage computed
   - Compared against contractual guarantee

3. **Default Event Creation**

   - Automatic triggering when threshold breached
   - Metadata capture (shortfall, responsible party)
   - Contractor responsibility flagged
   - Cure deadline set

4. **Rule Engine Execution**

   - Clause identification and parsing
   - LD formula application
   - Financial impact calculation
   - Invoice adjustment determination

5. **Notification System**

   - Multi-recipient notification dispatch
   - Role-based messaging (internal vs external)
   - Contextual information included

6. **Invoice Generation to Off-Taker**

   - Energy charge calculation
   - LD credit application
   - Rule output linkage
   - Net amount computation

7. **Invoice Verification from Contractor**

   - Expected invoice generation
   - Received invoice capture
   - Line-by-line comparison
   - Variance identification and flagging

8. **Audit Trail**
   - Complete event-to-invoice traceability
   - User actions logged
   - Timestamps preserved
   - Document references maintained

---

## Test Queries Provided

The `test_queries.sql` file contains 10 comprehensive queries plus KPIs:

1. **Complete Chain Query** - Event → Default → Rule → Invoice
2. **Default Event Summary** - Financial impact overview
3. **Invoice to Off-Taker** - Full invoice breakdown
4. **Contractor Invoice Comparison** - Variance analysis
5. **Notifications Log** - Communication tracking
6. **Availability Calculation** - Verification of math
7. **Clause Analysis** - Problem clause identification
8. **Contractor Performance Scorecard** - Vendor evaluation
9. **Monthly Financial Summary** - Executive dashboard
10. **Audit Trail** - Complete transaction history

Plus 3 KPIs:

- Contract compliance rate
- Average LD per default
- Invoice verification success rate

---

## How to Use This Test Data

### Step 1: Create the Schema

```sql
psql -U your_user -d your_database -f schema.txt
```

### Step 2: Load the Test Data

```sql
psql -U your_user -d your_database -f dummy_data.sql
```

### Step 3: Run Test Queries

```sql
psql -U your_user -d your_database -f test_queries.sql
```

### Step 4: Verify Key Results

**Query 1 should show:**

- Event: Inverter failure, 100.25 hours downtime
- Default: 3.5 point availability shortfall
- Clause: Section 4.2, $50k per point
- Rule Output: $175,000 LD
- Invoice: $43,250 net (after $175k credit)

**Query 4 should show:**

- Expected contractor invoice: $85,000
- Received contractor invoice: $85,000
- Variance: $0
- Status: Disputed (due to potential LD passthrough)

---

## Expected System Behaviors

### ✅ Correctly Implemented

1. Events linked to faults and assets
2. Default events triggered by threshold breach
3. Liquidated damages calculated per contract formula
4. Invoice adjustments applied based on rule outputs
5. Contractor invoices flagged when performance issues exist
6. Complete audit trail maintained
7. Notifications sent to appropriate parties

### 🔄 Ready for Enhancement

1. Automated cure period tracking
2. Contractor backcharge calculation logic
3. Performance trending and prediction
4. Multi-period LD accumulation
5. Excuse/waiver workflow
6. Dispute resolution tracking

---

## Scenario Extensions (Future Test Cases)

### Variation 1: Grid Outage (Excused Event)

- Add grid event during outage period
- Recalculate availability excluding excused hours
- Verify LD calculation adjusts correctly

### Variation 2: Multiple Contractors

- Add backup contractor
- Split responsibility for different assets
- Test liability allocation logic

### Variation 3: Multi-Period Default

- Create availability shortfall across multiple months
- Test cumulative LD calculation
- Verify annual vs monthly guarantees

### Variation 4: Performance Bonus

- Create scenario where availability exceeds guarantee
- Implement bonus payment clause
- Test positive invoice adjustments

### Variation 5: Contractor Backcharge

- Complete investigation showing contractor negligence
- Issue formal backcharge
- Adjust contractor invoice accordingly

---

## Data Quality Notes

### Realistic Values

- **Energy Production:** 4.85 GWh for 50 MW plant in November is realistic

  - Capacity factor: ~13.5% (typical for winter month in Texas)
  - Actual lower due to 100-hour outage

- **Inverter Outage:** 4.2 days is realistic for:

  - Component failure requiring spare part
  - Supply chain delay
  - Replacement and testing

- **LD Amount:** $175,000 is material but not catastrophic
  - Represents ~80% of energy revenue for the month
  - Incentivizes performance without being punitive

### Intentional Gaps

- No second month of data (for trending analysis)
- No seasonal variation examples
- No force majeure events
- No partial excuse scenarios
- No contractor backcharge resolution (left open for workflow testing)

---

## Success Criteria for System

Your contract compliance engine should be able to:

1. ✅ **Detect** the availability shortfall automatically
2. ✅ **Calculate** the correct LD amount ($175,000)
3. ✅ **Link** the default event to the triggering physical event
4. ✅ **Apply** the invoice adjustment correctly
5. ✅ **Flag** the contractor invoice for further review
6. ✅ **Notify** all relevant parties
7. ✅ **Maintain** complete audit trail
8. ✅ **Generate** reports showing end-to-end flow
9. ✅ **Compare** invoices and identify discrepancies
10. ✅ **Track** cure deadlines and resolution status

---

## Contact & Questions

This test data was designed to be comprehensive yet focused on a single, clear scenario. If you need:

- Additional test scenarios
- More complex multi-party contracts
- Extended time series data
- Additional clause types
- Different default event types

Please document your requirements and the data can be extended accordingly.

---

## Version History

**v1.0** (2024-12-05)

- Initial release
- Single default event scenario
- Complete invoice workflow
- Contractor performance tracking

---

## License & Usage

This test data is provided for development and testing purposes. All company names, addresses, and scenarios are fictional. Any resemblance to real entities is coincidental.
