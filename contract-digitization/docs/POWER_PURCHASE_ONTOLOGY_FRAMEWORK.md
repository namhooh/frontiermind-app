# Power Purchase Ontology: Conceptual Framework

## The Challenge

You are building a **codifiable and actionable ontology system** for energy contract compliance that must:

1. Represent 13+ clause categories with their internal parameters
2. Model the **relationships between clauses** (dependencies, triggers, calculations)
3. Connect clauses to **external spheres** (other contracts, legal documents)
4. Enable a **rules engine** to evaluate compliance automatically
5. Scale across projects and contract types

This is essentially building a **knowledge graph** for energy contracts that is both human-readable and machine-executable.

---

## Core Formula

**"Must A (obligation), if X then Y (evidence/trigger & rule & result), except Z (excuse)"**

Every clause and compliance concept maps to this formula:

| Component | Meaning | Example |
|-----------|---------|---------|
| **Must A** | The obligation | "Maintain 95% availability annually" |
| **If X** | Trigger / Evidence | "Availability falls below 95%" |
| **Then Y** | Rule + Result | "Calculate LD = $50k × shortfall points" |
| **Except Z** | Excuse | "Force majeure, scheduled maintenance" |

### What Is the "Obligation"?

**Only "Must A" is the obligation.** The rest describes what happens around it:

| Component | What It Is | Is It An Obligation? |
|-----------|------------|----------------------|
| **Must A** | The obligation itself | ✅ Yes |
| **If X then Y** | Consequence logic (enforcement) | ❌ No |
| **Except Z** | Excuse logic (exception handling) | ❌ No |

### Clarifications: "By Whom" and "By When"

| Question | Answer | How Captured |
|----------|--------|--------------|
| **Must A by whom?** | Who is obligated | `responsible_party` field (Seller, Buyer, Both) |
| **Over what time?** | Evaluation period for the metric | `evaluation_period` in normalized_payload |
| **Y by when?** | Deadline for consequence/cure | In consequence clause's normalized_payload |

The formula remains simple. Party and timing details are attributes within each component, not separate formula elements.

---

## 1. Understanding the Complexity

### 1.1 Clause Category Roles

All 13 clause categories serve one of these formula roles:

| Role | Categories |
|------|------------|
| **Defines Obligation (Must A)** | AVAILABILITY, PERFORMANCE_GUARANTEE, PAYMENT_TERMS, MAINTENANCE, COMPLIANCE, SECURITY_PACKAGE |
| **Defines Consequence (If X then Y)** | LIQUIDATED_DAMAGES, DEFAULT, TERMINATION |
| **Defines Excuse (Except Z)** | FORCE_MAJEURE, MAINTENANCE (scheduled outages) |
| **Unlocks/Gates** | CONDITIONS_PRECEDENT |
| **Governs** | PRICING, GENERAL |

### 1.2 Clause Interdependencies (Internal Web)

Clauses form a complex web of relationships:

```
                    CONDITIONS_PRECEDENT
                           │
                           │ triggers
                           ▼
    ┌──────────────────────┴──────────────────────┐
    │                                              │
    ▼                                              ▼
SECURITY_PACKAGE ◀────────────────────────▶ TERMINATION
    │                                              ▲
    │                                              │
    ▼                                              │
DEFAULT ──────────────────────────────────────────┘
    │                     triggers
    │
    ▼
LIQUIDATED_DAMAGES ◀──────────┬──────────▶ FORCE_MAJEURE
    ▲                         │                    │
    │                         │                    │ excuses
    │ triggered by            │                    ▼
    │                         │              AVAILABILITY
    │                         │                    │
    │                         │                    │ measured against
PRICING ◀─────────────────────┘                    ▼
    │                                    PERFORMANCE_GUARANTEE
    │ inputs to                                    │
    ▼                                              │ degradation affects
PAYMENT_TERMS                                      ▼
    │                                        MAINTENANCE
    │ governed by                                  │
    ▼                                              │
GENERAL ◀──────────────────────────────────────────┘
(law, disputes, notices)                    (O&M responsibility)
```

### 1.3 Clause Input/Output Relationships

Each clause has **inputs** (parameters it needs) and **outputs** (values it produces). Parameters are categorized by type:

| Parameter Type | Description | Examples |
|----------------|-------------|----------|
| **Value** | Numeric measurements, amounts, rates | availability_percent, kwh_lost, ld_amount, rate |
| **Date** | Timestamps, deadlines, periods | COD_date, cure_deadline, payment_date |
| **Status** | Boolean or enum states | default_triggered, fm_period_active, contract_effective |

**Clause Input/Output Matrix:**

| Clause | Key Inputs | Type | Key Outputs | Type |
|--------|------------|------|-------------|------|
| **AVAILABILITY** | meter readings | Value | availability_percent | Value |
| | outage logs | Date | hours_available | Value |
| | curtailment events | Status | | |
| **PERFORMANCE_GUARANTEE** | energy production | Value | performance_ratio | Value |
| | irradiance | Value | capacity_factor | Value |
| | degradation_rate | Value | | |
| **LIQUIDATED_DAMAGES** | availability_percent | Value | ld_amount_due | Value |
| | performance_ratio | Value | breach_detected | Status |
| | COD_date | Date | | |
| **PRICING** | energy_delivered | Value | invoice_amount | Value |
| | escalation_rate | Value | current_rate | Value |
| | base_rate | Value | | |
| **PAYMENT_TERMS** | invoice_amount | Value | payment_status | Status |
| | payment_date | Date | late_fee | Value |
| **DEFAULT** | payment_status | Status | default_triggered | Status |
| | availability_percent | Value | cure_deadline | Date |
| | security_status | Status | | |
| **SECURITY_PACKAGE** | default_triggered | Status | security_draw_amount | Value |
| | COD_achieved | Status | release_schedule | Date |
| **CONDITIONS_PRECEDENT** | permits_obtained | Status | contract_effective | Status |
| | security_posted | Status | obligations_unlocked | Status |
| **FORCE_MAJEURE** | event_type | Status | fm_period_active | Status |
| | notification_date | Date | obligations_suspended | Status |
| **TERMINATION** | default_triggered | Status | termination_right | Status |
| | fm_duration | Value | buyout_price | Value |
| | term_years | Value | | |
| **MAINTENANCE** | outage_logs | Date | sla_met | Status |
| | response_times | Value | maintenance_penalty | Value |
| **COMPLIANCE** | permit_status | Status | compliance_status | Status |
| | reports_filed | Status | violation_detected | Status |
| **GENERAL** | dispute_filed | Status | dispute_resolution_path | Status |
| | notice_sent | Date | notice_valid | Status |

**Capturing Parameter Types in Ontology:**

Parameter types are captured in the `normalized_payload` schema for each clause category:

```json
{
  "threshold_percent": {
    "value": 95.0,
    "type": "Value",
    "unit": "percent"
  },
  "measurement_period": {
    "value": "annual",
    "type": "Date"
  },
  "excused_events": {
    "value": ["force_majeure", "scheduled_maintenance"],
    "type": "Status"
  }
}
```

Alternatively, parameter types can be defined in the relationship patterns configuration (YAML) for validation and rules engine use.

### 1.4 External Connections

Clauses connect to external spheres:

```
                         PROJECT
                            │
           ┌────────────────┼────────────────┐
           │                │                │
           ▼                ▼                ▼
    ┌───────────┐    ┌───────────┐    ┌───────────┐
    │    PPA    │    │    EPC    │    │    O&M    │
    │ Contract  │    │ Contract  │    │ Agreement │
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                           ▼
                    ┌───────────┐
                    │  SHARED   │
                    │  ENTITIES │
                    │           │
                    │ • Parties │
                    │ • Dates   │
                    │ • Assets  │
                    │ • Meters  │
                    └───────────┘

CROSS-CONTRACT DEPENDENCIES:
• EPC warranty period → PPA performance guarantee baseline
• O&M SLA → PPA availability calculation (excused outages)
• EPC delay LD → PPA COD conditions precedent
• O&M termination → PPA maintenance responsibility shift
```

---

## 2. Ontology Structure

### 2.1 Architecture Overview

The system separates **static structure** (ontology) from **dynamic evaluation** (rules engine):

```
┌─────────────────────────────────────────────────────────────────┐
│                     STATIC: ONTOLOGY LAYER                       │
│                  (defines what to check)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   clause table                    clause_relationship table      │
│   ┌─────────────────────┐        ┌─────────────────────┐        │
│   │ • category          │        │ • source_clause     │        │
│   │ • raw_text          │        │ • target_clause     │        │
│   │ • normalized_payload│        │ • relationship_type │        │
│   │ • responsible_party │        │ • is_cross_contract │        │
│   └─────────────────────┘        └─────────────────────┘        │
│              │                              │                    │
│              └──────────────┬───────────────┘                    │
│                             │                                    │
│                             ▼                                    │
│                    obligation_view                               │
│                    (Must A only)                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ defines what to evaluate
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OPERATIONAL DATA LAYER                         │
│                 (inputs for evaluation)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   meter_reading                        event                     │
│   (raw data)                      (FM, maintenance,              │
│        │                           curtailment)                  │
│        ▼                                                         │
│   meter_aggregate                                                │
│   (for rules engine)                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ provides actuals + context
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   DYNAMIC: RULES ENGINE                          │
│                 (computes verdicts)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   INPUTS:                                                        │
│   • obligation_view (thresholds)                                 │
│   • clause_relationship (triggers, excuses)                      │
│   • meter_aggregate (actuals)                                    │
│   • event (FM events, maintenance, curtailment)                  │
│                                                                  │
│   EVALUATION:                                                    │
│   1. Did X happen? (compare actual vs threshold)                 │
│   2. Is Z applicable? (check EXCUSES + event log)                │
│   3. If breach confirmed → create default_event                  │
│   4. Calculate Y (apply consequence formula) → rule_output       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ records defaults and verdicts
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RESULTS: OUTPUT TABLES                        │
│            (only when default situation exists)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   default_event                    rule_output                   │
│   (the default situation)          (verdict/consequence)         │
│   ┌─────────────────────┐         ┌─────────────────────┐       │
│   │ • obligation_ref    │────────▶│ • default_event_id  │       │
│   │ • breach_type       │         │ • ld_amount         │       │
│   │ • shortfall_amount  │         │ • cure_deadline     │       │
│   │ • evidence JSONB    │         │ • payment_due_date  │       │
│   │ • created_at        │         │ • verdict JSONB     │       │
│   └─────────────────────┘         └─────────────────────┘       │
│                                                                  │
│   Note: If no breach → no default_event → no rule_output         │
│   (everything in order, nothing to record)                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Entities

```
LEVEL 1: ORGANIZATIONAL
├── organization
└── project

LEVEL 2: CONTRACTUAL (STATIC)
├── contract
│   ├── contract_type (PPA, EPC, O&M, Interconnection, Lease)
│   ├── counterparty_id (FK to counterparty table)
│   ├── effective_date
│   ├── term
│   └── status
│
├── clause
│   ├── category (13 types)
│   ├── raw_text
│   ├── normalized_payload (clause-specific data only)
│   ├── responsible_party_id (FK to clause_responsible_party table)
│   └── beneficiary_party_id (FK to clause_responsible_party table)
│
└── clause_relationship
    ├── source_clause_id
    ├── target_clause_id
    ├── relationship_type (TRIGGERS, EXCUSES, GOVERNS, INPUTS)
    ├── is_cross_contract
    └── parameters

LEVEL 3: OPERATIONAL (DATA + VIEWS)
├── meter_reading (raw meter data)
├── meter_aggregate (aggregated data for rules engine)
├── event (FM events, maintenance, curtailment)
└── obligation_view
    ├── Filters to obligation-generating categories
    ├── Exposes "Must A" only (metric, threshold, period)
    └── Does NOT include consequences or excuses

LEVEL 4: RESULTS (ONLY WHEN DEFAULT EXISTS)
├── default_event (the default situation - Loss of Expected Output (LEO) or breach confirmed)
└── rule_output (verdict/consequence of the default - LD amount, cure deadline)
```

### 2.3 Relationship Types

Four core relationship types:

| Type | Meaning | Has Direct Action? | Example |
|------|---------|-------------------|---------|
| **TRIGGERS** | A causes/activates/changes B | ✅ Yes | Availability shortfall TRIGGERS LD |
| **EXCUSES** | A negates/suspends obligation in B | ✅ Yes | Force Majeure EXCUSES Availability |
| **GOVERNS** | A sets rules/context for B | ✅ Yes | General GOVERNS all clauses |
| **INPUTS** | A provides data/reference to B | ❌ No direct action | Pricing INPUTS Payment Terms |

**INPUTS vs TRIGGERS distinction:**
- TRIGGERS = causes something to happen (action)
- INPUTS = provides data used by another clause (no action)

**Cross-contract scope:** Handled via `is_cross_contract` boolean attribute, not a separate relationship type.

---

## 3. How the Formula Is Assembled

The full formula **"Must A, if X then Y, except Z"** is assembled through **joins**, not embedded in a single row:

```
┌─────────────────────┐
│   obligation_view   │  ← "Must A" (the obligation)
│                     │
│ clause_id: 001      │
│ category: AVAIL     │
│ threshold: 95%      │
│ period: annual      │
└──────────┬──────────┘
           │
           │ JOIN clause_relationship WHERE type = 'TRIGGERS'
           ▼
┌─────────────────────┐
│  clause (LD)        │  ← "If X then Y" (consequence)
│                     │
│ clause_id: 012      │
│ category: LD        │
│ rate: $50k/point    │
│ cap: $500k          │
└─────────────────────┘
           ▲
           │ JOIN clause_relationship WHERE type = 'EXCUSES'
           │
┌─────────────────────┐
│  clause (FM)        │  ← "Except Z" (excuse)
│                     │
│ clause_id: 022      │
│ category: FM        │
│ defined_events: [...│
└─────────────────────┘
```

**Key insight:** `clause_relationship` IS the ontology. It defines:
- Which obligations exist (via obligation_view)
- What triggers their consequences (TRIGGERS relationships)
- What excuses them (EXCUSES relationships)

---

## 4. Rules Engine: Evaluation Flow

The Python rules engine computes verdicts and records results.

### 4.1 Evaluation Process

```
┌─────────────────────────────────────────────────────────────────┐
│                    PYTHON RULES ENGINE                           │
└─────────────────────────────────────────────────────────────────┘

STEP 1: LOAD CONTEXT
├── Get obligation from obligation_view
│   └── e.g., AVAILABILITY: threshold=95%, period=annual
├── Get consequence via TRIGGERS relationship
│   └── e.g., LD clause: rate=$50k/point, cap=$500k
└── Get excuses via EXCUSES relationships
    └── e.g., FM clause, MAINTENANCE clause

STEP 2: GATHER ACTUALS
├── Query meter_aggregate for evaluation period
├── Query event table for relevant events (FM, maintenance, curtailment)
└── Calculate actual metric
    └── e.g., availability_percent = 91.8%

STEP 3: EVALUATE "DID X HAPPEN?"
├── Compare actual vs threshold
│   └── 91.8% < 95% → YES, potential breach
└── Record preliminary result

STEP 4: EVALUATE "IS Z APPLICABLE?"
├── Check each EXCUSES relationship
│   ├── Query event table for matching event_type
│   ├── Any active FM event during period? (event.event_type = 'force_majeure')
│   ├── Any scheduled maintenance? (event.event_type = 'scheduled_maintenance')
│   └── Calculate excused hours from event.metric_outcome
├── Adjust actual metric if excuses apply
│   └── e.g., 91.8% → 94.2% after excusing FM hours
└── Re-evaluate: 94.2% < 95% → still breach (or not)

STEP 5: IF BREACH CONFIRMED → CREATE DEFAULT_EVENT
├── Create default_event record
│   └── breach_type, obligation_ref, shortfall_amount, evidence JSONB
└── This represents the default situation itself

STEP 6: CALCULATE VERDICT → CREATE RULE_OUTPUT
├── Get consequence clause via TRIGGERS
├── Apply formula from consequence normalized_payload
│   └── shortfall = 95% - 91.8% = 3.2 points
│   └── ld_amount = 3.2 × $50,000 = $160,000
│   └── cap check: $160,000 < $500,000 → no cap applied
├── Determine cure period, payment deadline
└── Create rule_output linked to default_event
    └── ld_amount, cure_deadline, payment_due_date, verdict JSONB

NOTE: If no breach detected in Step 4, STOP.
      No default_event created, no rule_output needed.
      Everything is in order.
```

### 4.2 Data Flow Diagram

```
                    ONTOLOGY (static)
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
    ▼                     ▼                     ▼
obligation_view    clause_relationship    clause (LD, FM)
(Must A)           (TRIGGERS, EXCUSES)    (consequence data)
    │                     │                     │
    └─────────────────────┼─────────────────────┘
                          │
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
       meter_aggregate             event
       (aggregated actuals)   (FM, maintenance,
              │                curtailment)
              │                       │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   PYTHON RULES ENGINE  │
              │                        │
              │   Breach detected?     │
              │        │               │
              │   NO ──┴── YES         │
              │   │        │           │
              │ STOP    Continue       │
              └─────────┬──────────────┘
                        │
                        ▼
                  default_event
               (the default situation)
                        │
                        ▼
                   rule_output
              (verdict/consequence)
```

### 4.3 Result Tables

| Table | When Written | What It Stores |
|-------|--------------|----------------|
| `default_event` | Only when breach confirmed | The default situation: breach_type, obligation_ref, shortfall_amount, evidence JSONB |
| `rule_output` | Only when default_event exists | Verdict/consequence: default_event_id, ld_amount, cure_deadline, payment_due_date, verdict JSONB |

**Key Logic:** No breach → No default_event → No rule_output. When obligations are met, nothing is recorded.

---

## 5. Data Model

### 5.1 Clause Table (Exists)

Each clause stores only its own extracted data:

**AVAILABILITY clause normalized_payload:**
```json
{
  "threshold_percent": 95.0,
  "measurement_period": "annual",
  "calculation_method": "percentage of time facility capable of delivering",
  "excused_events": ["force_majeure", "scheduled_maintenance"]
}
```

**LIQUIDATED_DAMAGES clause normalized_payload:**
```json
{
  "trigger_type": "availability_shortfall",
  "calculation_type": "per_point",
  "rate": 50000,
  "rate_unit": "$/point",
  "cap_amount": 500000,
  "cap_type": "annual",
  "cure_period_days": 30,
  "payment_due_days": 15
}
```

**FORCE_MAJEURE clause normalized_payload:**
```json
{
  "defined_events": ["act_of_god", "war", "grid_failure"],
  "notification_period_hours": 48,
  "max_duration_days": 180,
  "documentation_required": true
}
```

### 5.2 Clause Relationship Table (New)

**Purpose:** Store explicit relationships between clauses — this IS the ontology

**Key Fields:**
- `source_clause_id` - The clause that initiates the relationship
- `target_clause_id` - The clause that is affected
- `relationship_type` - TRIGGERS, EXCUSES, GOVERNS, INPUTS
- `is_cross_contract` - Boolean flag for cross-contract relationships
- `parameters` - JSONB with relationship-specific data
- `is_inferred` - Whether this was AI-detected or human-defined
- `confidence` - Confidence score if AI-detected

### 5.3 Event Table (Exists)

**Purpose:** Log operational events that may excuse obligations or trigger consequences

**Schema:**

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| id | bigserial | PK | Primary key |
| project_id | bigint | FK | Which project this event affects |
| organization_id | bigint | FK | Organization |
| data_source_id | bigint | FK | Source system (inverter API, O&M system, manual) |
| event_type_id | bigint | FK | Type of event (lookup table) |
| description | varchar | | Human-readable description |
| raw_data | JSONB | | Original data from source system |
| metric_outcome | JSONB | | Calculated impact (downtime_hours, kwh_lost) |
| time_start | timestamptz | | When event began |
| time_acknowledged | timestamptz | | When event was acknowledged |
| time_fixed | timestamptz | | When issue was resolved |
| time_end | timestamptz | | When event period ended |
| status | enum | | Current status |
| created_at | timestamptz | | Record creation |
| updated_at | timestamptz | | Last update |
| created_by | uuid | | User who created |
| updated_by | uuid | | User who last updated |

**Suggested additions for compliance use:**

| Column | Type | Purpose |
|--------|------|---------|
| contract_id | bigint (FK, nullable) | Link to specific contract if applicable |
| verified | boolean | Whether event has been verified for excuse purposes |
| verified_by | uuid | Who verified |
| verified_at | timestamptz | When verified |

**Event Types (event_type lookup table):**

| Event Type | Description | Typically Excuses |
|------------|-------------|-------------------|
| force_majeure | FM event (storm, grid failure, war) | AVAILABILITY, PERFORMANCE |
| scheduled_maintenance | Planned maintenance outage | AVAILABILITY |
| unscheduled_maintenance | Emergency repairs | Depends on contract |
| grid_curtailment | Utility-ordered curtailment | AVAILABILITY, PERFORMANCE |
| grid_outage | Grid unavailable | AVAILABILITY |
| equipment_failure | Inverter, transformer failure | May or may not excuse |
| weather | Extreme weather (non-FM) | PERFORMANCE (irradiance adjustment) |
| permit_delay | Regulatory delay | CONDITIONS_PRECEDENT |
| interconnection_delay | Grid connection delay | CONDITIONS_PRECEDENT |

**Event Status (enum):**

| Status | Meaning |
|--------|---------|
| reported | Event logged, not yet acknowledged |
| acknowledged | Event seen, being investigated |
| verified | Event confirmed with documentation |
| disputed | Counterparty disputes the event |
| resolved | Event ended and closed |
| rejected | Event claim rejected |

**metric_outcome JSONB Structure:**

The `metric_outcome` field captures the calculated impact of the event:

```json
{
  "downtime_hours": 8.5,
  "kwh_lost": 42500,
  "availability_impact_percent": 0.097,
  "affected_capacity_mw": 50
}
```

This is used by the rules engine to calculate excused hours when evaluating obligations.

**Example Event Record:**

```json
{
  "id": 1,
  "project_id": 101,
  "organization_id": 1,
  "data_source_id": 3,
  "event_type_id": 1,
  "description": "Transmission line fault - utility confirmed",
  "raw_data": {
    "utility_reference": "OUTAGE-2025-4521",
    "grid_operator": "ERCOT",
    "notification_received": "2025-07-15T14:15:00Z"
  },
  "metric_outcome": {
    "downtime_hours": 8,
    "kwh_lost": 40000,
    "availability_impact_percent": 0.091
  },
  "time_start": "2025-07-15T14:00:00Z",
  "time_acknowledged": "2025-07-15T14:30:00Z",
  "time_fixed": null,
  "time_end": "2025-07-15T22:00:00Z",
  "status": "verified",
  "verified": true,
  "verified_by": "user-uuid-123",
  "verified_at": "2025-07-16T09:00:00Z"
}
```

### 5.4 How Event Table Is Populated

Events are logged from multiple sources via the `data_source` lookup table:

| Source | Method | Event Types | Automation Level |
|--------|--------|-------------|------------------|
| **Inverter API** | Automatic via fetcher workers | equipment_failure, unscheduled_maintenance | Fully automated |
| **Grid operator alerts** | Webhook or manual entry | grid_curtailment, grid_outage | Semi-automated |
| **O&M system integration** | API sync | scheduled_maintenance, equipment_failure | Automated |
| **Weather service API** | Automatic polling | weather, force_majeure (storms) | Automated |
| **Manual entry (UI)** | User input | Any type | Manual |
| **Email parsing** | AI extraction from notices | force_majeure, grid_curtailment | Semi-automated |
| **Document upload** | AI extraction from PDFs | Any type | Semi-automated |

**Event Population Flow:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    EVENT SOURCES                                 │
└─────────────────────────────────────────────────────────────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
   Inverter API   Grid Operator   O&M System    Manual Entry
   (automatic)    (webhook)       (API sync)    (UI form)
        │              │              │              │
        └──────────────┴──────────────┴──────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Event Ingestion │
                    │     Service      │
                    │                  │
                    │ • Validate event │
                    │ • Deduplicate    │
                    │ • Calculate      │
                    │   metric_outcome │
                    │ • Set status     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   event table    │
                    │                  │
                    │ status: reported │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Verification    │
                    │  (manual or      │
                    │   automated)     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   event table    │
                    │                  │
                    │ status: verified │
                    │ verified: true   │
                    └─────────────────┘
                             │
                             │ (used by rules engine)
                             ▼
                    ┌─────────────────┐
                    │  Rules Engine    │
                    │                  │
                    │ "Is Z applicable?"│
                    │ Uses metric_outcome│
                    │ for excuse calc   │
                    └─────────────────┘
```

**Verification Requirements:**

| Event Type | Verification Required | Typical Documentation |
|------------|----------------------|----------------------|
| force_majeure | Yes - strict | Utility notice, news report, government declaration |
| scheduled_maintenance | Yes - basic | Maintenance schedule, work order |
| grid_curtailment | Yes - strict | Utility curtailment order |
| grid_outage | Yes - moderate | Utility outage report |
| equipment_failure | Yes - moderate | Maintenance ticket, inverter logs |
| weather | Auto-verified | Weather API data |

### 5.6 Obligation View (New)

**Purpose:** Expose "Must A" obligations only — no consequences or excuses

**What it does:**
- Filters to obligation-generating categories:
  - AVAILABILITY
  - PERFORMANCE_GUARANTEE
  - PAYMENT_TERMS
  - MAINTENANCE
  - COMPLIANCE
  - SECURITY_PACKAGE
- Extracts key fields from normalized_payload as columns
- Joins responsible_party from clause table
- Single source of truth — clause table is the master

**What it exposes:**
- clause_id, contract_id, category
- metric (e.g., "availability_percent")
- threshold_value
- comparison_operator (>=, <=, =)
- evaluation_period (monthly, quarterly, annual)
- responsible_party

**What it does NOT include:**
- Consequence details (those come from TRIGGERS relationships)
- Excuse details (those come from EXCUSES relationships)

### 5.7 Cross-Contract Link Table

**Purpose:** Connect clauses across different contracts (subset of clause_relationship where is_cross_contract = true)

**Key Fields:**
- `project_id` - The project these contracts belong to
- `source_contract_id` - First contract
- `source_clause_id` - Clause in first contract
- `target_contract_id` - Second contract
- `target_clause_id` - Clause in second contract
- `relationship_type` - TRIGGERS, EXCUSES, GOVERNS, INPUTS
- `parameters` - JSONB with relationship-specific data

---

## 6. Clause Category Relationship Matrix

### 6.1 Intra-Contract Relationships (PPA)

| Source Category | Target Category | Type | Description |
|-----------------|-----------------|------|-------------|
| CONDITIONS_PRECEDENT | All others | TRIGGERS | CP satisfaction activates all obligations |
| AVAILABILITY | LIQUIDATED_DAMAGES | TRIGGERS | Shortfall triggers availability LD |
| PERFORMANCE_GUARANTEE | LIQUIDATED_DAMAGES | TRIGGERS | Shortfall triggers performance LD |
| DEFAULT | TERMINATION | TRIGGERS | Default enables termination right |
| DEFAULT | SECURITY_PACKAGE | TRIGGERS | Default enables security draw |
| COMPLIANCE | DEFAULT | TRIGGERS | Non-compliance can trigger default |
| PRICING | PRICING | TRIGGERS | Escalation triggers price change |
| FORCE_MAJEURE | AVAILABILITY | EXCUSES | FM excuses availability shortfall |
| FORCE_MAJEURE | PERFORMANCE_GUARANTEE | EXCUSES | FM excuses performance shortfall |
| FORCE_MAJEURE | PAYMENT_TERMS | EXCUSES | FM may suspend payment obligations |
| MAINTENANCE | AVAILABILITY | EXCUSES | Scheduled maintenance excuses downtime |
| PRICING | PAYMENT_TERMS | INPUTS | Price feeds invoice calculation |
| PRICING | LIQUIDATED_DAMAGES | INPUTS | Some LDs reference contract price |
| GENERAL | All others | GOVERNS | Law, disputes, notices govern all |

### 6.2 Cross-Contract Relationships (PPA + O&M)

| Source Contract | Source Category | Target Contract | Target Category | Type |
|-----------------|-----------------|-----------------|-----------------|------|
| O&M | MAINTENANCE | PPA | AVAILABILITY | EXCUSES |
| O&M | SLA | PPA | AVAILABILITY | INPUTS |
| O&M | TERMINATION | PPA | MAINTENANCE | TRIGGERS |

### 6.3 Future Cross-Contract Relationships (Phase 2: EPC)

| Source Contract | Source Category | Target Contract | Target Category | Type |
|-----------------|-----------------|-----------------|-----------------|------|
| EPC | WARRANTY | PPA | PERFORMANCE_GUARANTEE | INPUTS |
| EPC | DELAY_LD | PPA | CONDITIONS_PRECEDENT | TRIGGERS |
| Interconnection | APPROVAL | PPA | CONDITIONS_PRECEDENT | TRIGGERS |
| Lease | TERM | PPA | TERMINATION | INPUTS |
| Financing | SECURITY | PPA | SECURITY_PACKAGE | INPUTS |

---

## 7. Implementation Recommendations

### 7.1 Start Simple, Evolve Complexity

**Phase 1 Focus:**
- Single contract (PPA) clause extraction
- Known relationships from category patterns
- Simple threshold-based rules engine

**Phase 2 Focus:**
- Add O&M contract support
- Cross-contract relationships
- Excuse evaluation logic

**Defer:**
- EPC and other documents (Phase 4)
- AI-inferred relationships
- Complex calculation chains

### 7.2 Use Configuration Over Code

Store relationship patterns in configuration (JSON/YAML), not hardcoded:

```yaml
relationship_patterns:
  - source_category: AVAILABILITY
    target_category: LIQUIDATED_DAMAGES
    relationship_type: TRIGGERS
    
  - source_category: FORCE_MAJEURE
    target_category: AVAILABILITY
    relationship_type: EXCUSES
    
  - source_category: PRICING
    target_category: PAYMENT_TERMS
    relationship_type: INPUTS
```

### 7.3 Evidence-First Design

Every compliance evaluation must capture evidence:
- What obligation was evaluated
- What actual data was used
- What threshold was compared
- Whether excuses were checked and applied
- What the final verdict was
- When it was evaluated

This is critical for disputes and audits.

### 7.4 Human-in-the-Loop

For the initial phase:
- AI extracts clauses
- System suggests relationships from category patterns
- Human reviews and confirms
- Confirmed relationships improve future suggestions

### 7.5 Versioning

Contracts are amended. Ontology must support:
- Clause versioning (amendments)
- Relationship versioning (changes over time)
- Historical compliance evaluation (as-of-date queries)

**Strategy:** New clause version with effective dates, soft-delete old

---

## 8. API Endpoints

### Obligations

```
GET /api/ontology/contracts/{id}/obligations
    → List all obligations for a contract

GET /api/ontology/clauses/{id}/obligation
    → Get full obligation details with relationships
```

### Relationships

```
GET /api/ontology/clauses/{id}/relationships
    → Get all relationships (incoming + outgoing)

GET /api/ontology/clauses/{id}/triggers
    → Get consequences triggered by this clause

GET /api/ontology/clauses/{id}/excuses
    → Get clauses/events that can excuse this obligation

POST /api/ontology/relationships
    → Create explicit relationship

DELETE /api/ontology/relationships/{id}
    → Delete a relationship
```

### Detection

```
POST /api/ontology/contracts/{id}/detect-relationships
    → Auto-detect relationships from clause categories

DELETE /api/ontology/contracts/{id}/inferred-relationships
    → Delete all auto-detected relationships (for re-detection)
```

### Graph

```
GET /api/ontology/contracts/{id}/relationship-graph
    → Get full relationship graph for visualization
```

---

## 9. Best Practices

### When to Use Explicit Relationships

Create explicit (non-inferred) relationships when:
- Pattern detection misses a relationship
- Contract has unusual clause structure
- Cross-contract relationships need custom parameters

### When to Re-Run Detection

Re-run relationship detection when:
- Patterns are updated in `relationship_patterns.yaml`
- New clause categories are added
- Confidence thresholds change

### Confidence Scores

- `>= 0.95`: High confidence, likely correct
- `0.85 - 0.95`: Good confidence, review if time permits
- `0.70 - 0.85`: Moderate confidence, should review
- `< 0.70`: Not created (below threshold)

---

## 10. Troubleshooting

### No Relationships Detected

1. Check clause categories are populated: `SELECT clause_category_id FROM clause WHERE contract_id = X`
2. Verify patterns match categories in `relationship_patterns.yaml`
3. Check detection logs for errors

### Excuse Hours Not Calculated

1. Verify EXCUSES relationships exist: `GET /api/ontology/clauses/{id}/excuses`
2. Check event_type codes match mapping
3. Verify events exist in period

### Performance Issues

1. Check indexes exist on `clause_relationship`
2. Review `get_contract_relationship_graph` query plan
3. Consider limiting cross-contract detection for large portfolios

---

## 11. Tables Summary

| Table/View | Status | Purpose |
|------------|--------|---------|
| `organization` | Exists | Client organizations |
| `project` | Exists | Energy projects |
| `contract` | Exists | Contract metadata (FK to counterparty) |
| `counterparty` | Exists | Contract parties lookup |
| `clause` | Exists | Extracted clauses with normalized_payload |
| `clause_responsible_party` | Exists | Clause responsibility lookup |
| `event` | Exists | Operational events (FM, maintenance, curtailment) |
| `event_type` | Exists | Lookup table for event types |
| `data_source` | Exists | Lookup table for event sources |
| `meter_reading` | Exists | Raw meter data |
| `meter_aggregate` | Exists | Aggregated data for rules engine |
| `default_event` | Exists | The default situation (breach confirmed) |
| `rule_output` | Exists | Verdict/consequence of default (LD amount, cure deadline) |
| `clause_relationship` | **New** | Relationships between clauses (THE ontology) |
| `obligation_view` | **New (View)** | Exposes "Must A" obligations only |

**Note:** Only one new table (`clause_relationship`) plus one new view. Existing tables handle operational data and results.

---

## 12. Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Relationship granularity | Category-level patterns, clause-level instances | Store patterns in config, derive instances per contract |
| Obligation storage | View on clause table | Single source of truth, no data duplication |
| Formula assembly | Joins via clause_relationship | Keep clauses independent, relationships define structure |
| Evaluation logic | Python rules engine | Flexible, testable, can handle complex excuse logic |
| Result storage | default_event → rule_output | default_event is the breach situation, rule_output is its verdict |
| Result trigger | Only on breach | No default_event/rule_output when obligations are met |
| Initial contract scope | PPA + O&M for MVP | Two contract types covers core use case |
| Database | PostgreSQL + JSONB | No graph DB initially; evaluate at scale |
| Versioning | New version + soft delete | Add version, effective_from, superseded_by columns |

---

## 13. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Clause extraction accuracy | >90% | Manual review of sample |
| Relationship detection accuracy | >80% | Manual review of sample |
| Obligation coverage | >95% | % of obligation clauses exposed in view |
| Rule evaluation correctness | 100% | Unit tests + manual verification |
| Cross-contract link coverage | >80% | % of known dependencies captured |
| Time to onboard new contract | <2 hours | From upload to active monitoring |

---

## 14. Immediate Next Steps

| Priority | Task | Duration |
|----------|------|----------|
| 1 | Design database schema for clause_relationship table | 1 week |
| 2 | Add verification columns to existing event table | 1 day |
| 3 | Define relationship patterns for PPA contracts in YAML config | 1 week |
| 4 | Create obligation_view on clause table | 1 day |
| 5 | Build event ingestion service (integrate with existing data_source) | 2 weeks |
| 6 | Build Python rules engine MVP (threshold evaluation) | 2 weeks |
| 7 | Add excuse evaluation logic (event table + metric_outcome integration) | 1 week |
| 8 | Integrate with existing rule_output and default_event tables | 1 week |
| 9 | Add O&M contract support and cross-contract relationships | 2 weeks |
| 10 | Test with sample PPA + O&M contracts | 1 week |

---

## Summary

| Layer | Component | What It Does |
|-------|-----------|--------------|
| **Ontology (static)** | `clause` | Stores extracted clause data |
| **Ontology (static)** | `clause_relationship` | Defines TRIGGERS, EXCUSES, INPUTS, GOVERNS |
| **Ontology (static)** | `obligation_view` | Exposes "Must A" obligations |
| **Operational (dynamic)** | `meter_reading` | Raw meter data |
| **Operational (dynamic)** | `meter_aggregate` | Aggregated data for rules engine |
| **Operational (dynamic)** | `event` | FM events, maintenance, curtailment logs |
| **Evaluation (dynamic)** | Python rules engine | Computes: did X happen? is Z applicable? |
| **Results (on breach only)** | `default_event` | The default situation (breach confirmed) |
| **Results (on breach only)** | `rule_output` | Verdict/consequence (LD amount, cure deadline) |

**Core Formula:** Must A (obligation), if X then Y (consequence), except Z (excuse)

**Where each part lives:**
- **Must A** → `obligation_view`
- **If X then Y** → `clause_relationship` (TRIGGERS) → consequence clause
- **Except Z** → `clause_relationship` (EXCUSES) → excuse clause + `event` table
- **Breach detected?** → Python rules engine
- **Yes → default_event** (the situation) → **rule_output** (the verdict)
- **No → nothing recorded** (obligations met)
