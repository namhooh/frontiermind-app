# Power Purchase Ontology: Conceptual Framework

## The Challenge

You are building a **codifiable and actionable ontology system** for energy contract compliance that must:

1. Represent 13+ clause categories with their internal parameters
2. Model the **relationships between clauses** (dependencies, triggers, calculations)
3. Connect clauses to **external spheres** (other contracts, legal documents)
4. Enable a **rules engine** to evaluate compliance automatically
5. Scale across projects and contract types

This is essentially building a **knowledge graph** for energy contracts that is both human-readable and machine-executable.

### Design Motivation: Why Canonical Schemas?

The `normalized_payload` (JSONB on the `clause` table) stores extracted clause data. Without a defined schema, every downstream consumer must guess which fields exist and what they mean. Three concrete problems motivated the canonical schema design:

**1. Rules engine guesses field names with `.get()` defaults:**

Every rule class reads parameters using `.get()` with hardcoded defaults (e.g., `self.params.get('threshold', 95.0)` in `availability_rule.py:57`). If extraction names a field differently (e.g., `availability_threshold` instead of `threshold`), the `.get()` silently falls back to the default and the rule evaluates against a wrong threshold.

**2. Invoice generator tried multiple field names with fallback chains:**

`invoiceGenerator.ts` tried four different field names for the energy rate (`rate`, `price`, `tariff`, `energy_rate`), falling back to regex on `raw_text` when none matched. The extraction prompt had no contract with the consumer about what field name to produce.

**3. Obligation view used COALESCE across six possible field names:**

The original `015_obligation_view.sql` extracted threshold values by trying six different field names in a COALESCE chain. Each new contract variant with a slightly different name forced another branch.

**Solution:** Canonical schemas (implemented in `clause_examples.py:CANONICAL_SCHEMAS`) define expected fields per category with types, roles, and aliases. The extraction prompt produces canonical names; alias resolution maps contract-specific phrasing to canonical fields at extraction time; payload validation catches missing fields before they reach the rules engine.

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
| *(capacity_factor)* | irradiance (GHI) | Value | capacity_factor | Value |
| | degradation_rate | Value | | |
| | nameplate_capacity_mw | Value | | |
| **PERFORMANCE_GUARANTEE** | meter readings (kWh) | Value | actual_output_kwh | Value |
| *(energy_output)* | expected_energy_output_kwh | Value | shortfall_kwh | Value |
| | required_energy_output_percent | Value | shortfall_payment | Value |
| **PERFORMANCE_GUARANTEE** | irradiance (GHI per month) | Value | pr_actual_monthly | Value |
| *(performance_ratio)* | pr_schedule (monthly targets) | Value | pr_shortfall | Value |
| | capacity_adjustment_method | Status | | |
| **LIQUIDATED_DAMAGES** | availability_percent | Value | ld_amount_due | Value |
| | performance_ratio | Value | breach_detected | Status |
| | energy_output_shortfall | Value | | |
| | COD_date | Date | | |
| **PRICING** | energy_delivered | Value | invoice_amount | Value |
| | rate_schedule (tiered) | Value | current_rate | Value |
| | escalation (fixed/index) | Value | escalated_rate | Value |
| | billing_components | Status | line_items[] | Value |
| | payment_currency | Status | fx_adjusted_amount | Value |
| | fx_reference / fx_indemnity | Status | fx_gain_or_loss | Value |
| | deemed_energy_method | Status | deemed_energy_kwh | Value |
| **PAYMENT_TERMS** | invoice_amount | Value | payment_status | Status |
| | payment_date | Date | late_fee | Value |
| | take_or_pay_minimum | Value | shortfall_payment | Value |
| | billing_components | Status | invoice_line_items[] | Value |
| | deemed_energy_billing | Status | | |
| **DEFAULT** | payment_status | Status | default_triggered | Status |
| | payment_overdue_trigger_days | Value | cure_deadline | Date |
| | availability_percent | Value | cross_default_triggered | Status |
| | security_status | Status | consequences[] | Status |
| | cure_period_days | Value | | |
| **SECURITY_PACKAGE** | default_triggered | Status | security_draw_amount | Value |
| | COD_achieved | Status | release_schedule | Date |
| | security_type (bond/LC/guarantee/debenture) | Status | replenishment_deadline | Date |
| | draw_conditions | Status | draw_authorized | Status |
| **CONDITIONS_PRECEDENT** | permits_obtained | Status | contract_effective | Status |
| | security_posted | Status | obligations_unlocked | Status |
| | milestone_dates (COD, interconnection, transfer) | Date | billing_commences | Status |
| | enabling_works_completed | Status | | |
| **FORCE_MAJEURE** | event_type | Status | fm_period_active | Status |
| | notification_date | Date | obligations_suspended | Status |
| | fm_duration | Value | term_extension_days | Value |
| | payment_obligations_during_fm | Status | | |
| **TERMINATION** | default_triggered | Status | termination_right | Status |
| | fm_duration (>365 days) | Value | early_termination_charge | Value |
| | term_years | Value | buyout_calculation | Value |
| | termination_payment_structure | Status | termination_tier | Status |
| | termination_schedule (yearly) | Value | | |
| **MAINTENANCE** | outage_logs | Date | sla_met | Status |
| | response_times | Value | maintenance_penalty | Value |
| | scheduled_outage_hours | Value | excused_hours | Value |
| | panel_cleaning_compliance | Status | | |
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

### 1.5 Canonical Terminology

Every concept in the system has exactly one **canonical name** used in `normalized_payload`. Different contracts phrase the same concept differently — these are **aliases** resolved at extraction time, not stored as alternative field names.

**Canonical Terms Dictionary:**

| Canonical Name | Contract Aliases | Clause Categories | Consumer |
|---------------|-----------------|-------------------|----------|
| `commercial_operation_date` | "COD", "Transfer Date", "Energy Delivery Commencement", "Service Commencement Date" | CONDITIONS_PRECEDENT | Period calculation, obligation activation |
| `interconnection_date` | "Grid Connection Date", "Point of Connection Date", "Interconnection Completion" | CONDITIONS_PRECEDENT | Milestone tracking |
| `transfer_date` | "Transfer Date", "Handover Date", "Takeover Date" | CONDITIONS_PRECEDENT | Milestone tracking (Garden City pattern) |
| `anticipated_cod` | "Target COD", "Expected COD", "Scheduled COD" | CONDITIONS_PRECEDENT | Delay LD baseline |
| `cod_longstop` | "Longstop Date", "Outside Date", "Sunset Date" | CONDITIONS_PRECEDENT, TERMINATION | Termination trigger |
| `early_operating_start` | "Early Operating Date", "Interim Operating Period", "Pre-COD Generation Start" | CONDITIONS_PRECEDENT, PRICING | Early tariff application before formal COD |
| `base_rate_per_kwh` | "Tariff", "Energy Price", "Rate", "Index Tariff", "Solar Tariff", "Contract Price" | PRICING | `invoiceGenerator.ts`, pricing calc |
| `threshold` | "Guaranteed Availability", "Minimum Availability", "Availability Target" | AVAILABILITY | `AvailabilityRule.evaluate()` |
| `threshold` | "Guaranteed Output", "Minimum Performance Ratio", "Capacity Factor Target" | PERFORMANCE_GUARANTEE | `CapacityFactorRule.evaluate()` |
| `ld_per_point` | "Liquidated Damages Rate", "Penalty Rate", "Shortfall Rate" | LIQUIDATED_DAMAGES, AVAILABILITY, PERF_GUARANTEE | `BaseRule._calculate_ld_amount()` |
| `excused_events` | "Force Majeure Events", "Excluded Events", "Relief Events" | FORCE_MAJEURE | `BaseRule._calculate_excused_hours()` |
| `nameplate_capacity_mw` | "Contract Capacity", "Installed Capacity", "Facility Capacity", "Plant Capacity" | PERFORMANCE_GUARANTEE | `CapacityFactorRule.evaluate()` |
| `required_energy_output_kwh` | "Required Energy Output", "Minimum Energy Output", "Guaranteed Annual Energy" | PERFORMANCE_GUARANTEE | Energy output rule (new) |
| `billing_frequency` | "Billing Cycle", "Invoice Period", "Payment Period" | PAYMENT_TERMS, PRICING | Invoice scheduling |
| `deemed_energy_kwh` | "Deemed Energy", "Calculated Energy", "Estimated Output", "Deemed Delivery" | PRICING, PAYMENT_TERMS | Invoice generator — deemed energy line item |
| `environmental_attributes_owner` | "Carbon Credits", "Green Attributes", "RECs", "Environmental Attributes", "Renewable Energy Certificates" | PRICING | Commercial/audit — who retains credits |
| `enabling_works` | "Enabling Works", "Customer Works", "Pre-Construction Works", "Site Preparation" | MAINTENANCE, CONDITIONS_PRECEDENT | Customer pre-construction obligations |
| `early_termination_charge` | "Termination Payment", "ETC", "Buyout Price", "Early Termination Charge", "Termination Amount" | TERMINATION | Invoice generator — ETC calculation |
| `minimum_offtake_percent` | "Minimum Purchase", "Required Energy Output %", "Take-or-Pay Minimum", "Minimum Consumption" | PAYMENT_TERMS | Invoice generator — shortfall calculation |
| `payment_security_type` | "Letter of Credit", "Bank Bond", "Bank Guarantee", "Parent Company Guarantee", "Performance Bond", "Debenture" | SECURITY_PACKAGE | Relationship: DEFAULT → SECURITY draw |
| `billing_components` | "Energy Charge", "Capacity Charge", "BESS Charge", "Diesel Allocation", "O&M Fee" | PRICING, PAYMENT_TERMS | Invoice generator — multi-component line items |

**How aliases are resolved (end-to-end workflow):**

**Step 1 — Extraction prompt includes canonical terms:** The Claude extraction prompt includes `CANONICAL_TERMINOLOGY` (defined in `clause_examples.py`) mapping common contract phrases to canonical names. The prompt instructs Claude to produce canonical field names regardless of how the contract phrases concepts.

**Step 2 — Extraction produces canonical fields:** When Claude encounters "Transfer Date" in a Garden City ESA, the prompt maps it to `commercial_operation_date`. `normalized_payload` stores `{"commercial_operation_date": "2024-03-15", ...}`; `raw_text` preserves the original phrasing.

**Step 3 — Post-extraction alias resolution:** The `resolve_aliases()` function (in `clause_examples.py`) normalizes any remaining non-canonical field names. For example, if extraction produces `rate_tiers` instead of `rate_schedule`, the alias map resolves it to the canonical name.

**Step 4 — Downstream consumers use one name:** The rules engine reads `self.params['threshold']` — works for every contract. The obligation view reads `(c.normalized_payload->>'threshold')::NUMERIC` — no COALESCE chains needed. The invoice generator reads `payload.base_rate_per_kwh` — no fallback chains needed.

**Implementation files:**
- `python-backend/services/prompts/clause_examples.py` — `CANONICAL_TERMINOLOGY` dict, `resolve_aliases()` function
- `python-backend/services/prompts/clause_extraction_prompt.py` — Prompt includes canonical field lists per category
- `python-backend/services/ontology/payload_validator.py` — Validates payloads against `CANONICAL_SCHEMAS`

### 1.6 Party Roles

The system must support party roles beyond Buyer/Seller. Real contracts use varied terminology:

| Canonical Role | Contract Aliases | Example Contract |
|---------------|-----------------|------------------|
| `buyer` | "Buyer", "Offtaker", "Purchaser", "Client" | Standard PPA |
| `seller` | "Seller", "Generator", "Producer", "Developer" | Standard PPA |
| `operator` | "Operator", "O&M Provider", "Service Provider" | Garden City ESA |
| `system_owner` | "System Owner", "Asset Owner", "Facility Owner" | Garden City ESA |
| `funding_party` | "Funding Party", "Funder", "Lender", "Financier" | Garden City ESA |
| `client` | "Client", "Host", "Site Owner" | Garden City ESA, Rooftop PPAs |
| `epc_contractor` | "EPC Contractor", "Builder", "Construction Contractor" | EPC contracts |
| `grid_operator` | "Transmission Provider", "System Operator", "Utility" | Interconnection agreements |

**Mapping to existing schema:** The `clause_responsibleparty` table already supports arbitrary party names. The canonical roles above standardize what the extraction prompt produces, ensuring consistent downstream queries. `responsible_party` and `beneficiary_party` on the clause table store canonical role names, not free text.

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

### 5.1 Clause Table (Exists) — Enriched Normalized Payload Schemas

Each clause stores its own extracted data in `normalized_payload` (JSONB). Fields are annotated with **roles** that identify their downstream consumer:

| Role | Code | Consumer | Purpose |
|------|------|----------|---------|
| **Threshold** | T | Rules engine — breach detection | Numeric target for comparison |
| **Formula Input** | FI | Rules engine / pricing calc | Operand in a calculation |
| **Formula Definition** | FD | Rules engine — calc method | Defines HOW to calculate |
| **Schedule** | S | Pricing calc / rules engine — lookup | List of tiers, periods, brackets |
| **Configuration** | C | Rules engine — behavior control | Controls rule behavior |
| **Reference** | R | Audit/traceability only | Contract source reference |

**Role tracing to current code:**

| Role | Field example | Consumer function | Code location |
|------|--------------|-------------------|---------------|
| T | `threshold` (AVAILABILITY) | `AvailabilityRule.evaluate()` | `availability_rule.py:57` → comparison at `:112` |
| T | `threshold` (PERF_GUARANTEE) | `CapacityFactorRule.evaluate()` | `capacity_factor_rule.py:57` → comparison at `:110` |
| FI | `ld_per_point` | `BaseRule._calculate_ld_amount()` | `base_rule.py:218` → calculation at `:253` |
| FI | `nameplate_capacity_mw` | `CapacityFactorRule.evaluate()` | `capacity_factor_rule.py:58` → formula at `:87` |
| FI | `base_rate_per_kwh` | `invoiceGenerator.ts:extractPricingFromClauses()` | `invoiceGenerator.ts:46` |
| C | `excused_events` | `BaseRule._calculate_excused_hours()` | `base_rule.py:169` |
| C | `evaluation_period` | `obligation_view` | `023_simplify_obligation_view.sql` |
| C | `ld_currency` | `BaseRule._get_ld_parameters()` | `base_rule.py:229` |
| R | `schedule_reference` | Audit only | Not consumed by code |

**What role annotations achieve:**

1. **Extraction validation:** After extraction, the system checks: "For an AVAILABILITY clause, are all T and FI fields populated?" If `threshold` is missing, the extraction failed — instead of silently falling back to a hardcoded default.

2. **Elimination of guessing:** The rules engine does not need `.get('threshold', 95.0)` with a default. It reads `threshold` knowing it was validated at extraction time.

3. **Consumer documentation:** A developer looking at the schema knows that `ld_per_point` (FI) is consumed by `BaseRule._calculate_ld_amount()` — not just "some number in the payload."

**Implementation:** Roles are defined in `CANONICAL_SCHEMAS` (in `clause_examples.py`). Each field entry includes `"role": "T"` (or FI, FD, S, C, R). The `PayloadValidator` class (in `payload_validator.py`) uses these schemas to validate extracted payloads.

---

**AVAILABILITY clause normalized_payload:**

```json
{
  "threshold": 95.0,                          // T — breach detection (availability_rule.py:57)
  "threshold_unit": "percent",                // C — comparison unit
  "evaluation_period": "annual",              // C — determines date range
  "calculation_method": "(Total Hours - Forced Outage - Scheduled Maintenance) / Total Hours", // FD
  "excused_events": ["force_majeure", "scheduled_maintenance", "grid_curtailment"], // C — event filter
  "scheduled_outage_max_hours_per_year": 200, // FI — used in maintenance deduction
  "scheduled_outage_notice_days": 30,         // C — notification requirement
  "comparison_operator": ">=",                // C — comparison direction
  "ld_per_point": 50000,                      // FI — shortfall × ld_per_point (base_rule.py:253)
  "ld_cap_annual": 500000,                    // FI — max LD per year (base_rule.py:256)
  "ld_cap_period": null,                      // FI — max LD per period
  "ld_currency": "USD",                       // C — LD denomination
  "schedule_reference": "Schedule 2"          // R — audit trail
}
```

**PERFORMANCE_GUARANTEE clause normalized_payload:**

Uses a `guarantee_type` discriminator to support three sub-types:

*Capacity Factor variant:*
```json
{
  "guarantee_type": "capacity_factor",        // C — selects rule class
  "threshold": 85.0,                          // T — breach detection (capacity_factor_rule.py:57)
  "nameplate_capacity_mw": 50,               // FI — expected_generation formula (capacity_factor_rule.py:58)
  "efficiency_factor": 0.95,                  // FI — adjusts expected generation (capacity_factor_rule.py:59)
  "evaluation_period": "annual",              // C — date range
  "degradation_rate_percent_per_year": 0.5,   // FI — threshold adjustment per year
  "weather_adjustment_method": "GHI from on-site met station", // C
  "excused_events": ["force_majeure"],        // C — event filter
  "comparison_operator": ">=",                // C
  "ld_per_point": 25000,                      // FI
  "ld_cap_annual": 300000,                    // FI
  "ld_currency": "USD",                       // C
  "schedule_reference": "Schedule 3"          // R
}
```

*Performance Ratio variant (with monthly schedule):*
```json
{
  "guarantee_type": "performance_ratio",      // C — selects rule class
  "threshold": 80.0,                          // T — annual PR target
  "pr_basis": "GHI",                          // C — irradiance basis
  "pr_schedule": [                            // S — monthly PR targets tied to GHI
    {"month": 1, "pr_target": 78.5, "expected_ghi_kwh_m2": 145},
    {"month": 2, "pr_target": 79.0, "expected_ghi_kwh_m2": 160},
    {"month": 3, "pr_target": 80.5, "expected_ghi_kwh_m2": 190}
  ],
  "capacity_adjustment_method": "pro_rata",   // C — adjust for capacity changes
  "degradation_rate_percent_per_year": 0.5,   // FI
  "evaluation_period": "monthly",             // C — PR measured monthly
  "nameplate_capacity_mw": 50,               // FI
  "excused_events": ["force_majeure"],        // C
  "ld_per_point": 25000,                      // FI
  "ld_currency": "USD",                       // C
  "schedule_reference": "Annexure C"          // R
}
```

*Energy Output variant:*
```json
{
  "guarantee_type": "energy_output",          // C — selects rule class
  "required_energy_output_percent": 90,       // T — % of expected output
  "expected_energy_output_kwh": 87600000,     // FI — annual expected
  "degradation_rate_percent_per_year": 0.5,   // FI — adjusts expected output per year
  "shortfall_payment_formula": "MAX[0, (Required - Actual)] × Rate", // FD
  "shortfall_rate_per_kwh": 0.045,            // FI — payment per kWh shortfall
  "shortfall_payment_cap_per_year": 500000,   // FI — max annual shortfall payment
  "shortfall_payment_declining": true,        // C — cap declines annually (IVL/MF01 pattern)
  "guarantee_period_years": 20,              // C — how many years the output guarantee applies (may differ from contract term)
  "evaluation_period": "annual",              // C — measurement frequency within guarantee period
  "excused_events": ["force_majeure", "grid_curtailment"], // C
  "deemed_energy_on_system_event": true,      // C — meter failure/curtailment → deemed energy calc
  "schedule_reference": "Schedule 4"          // R
}
```

**PRICING clause normalized_payload:**

```json
{
  "pricing_structure": "escalating",          // C — fixed | escalating | indexed | tiered | step_down
  "base_rate_per_kwh": 0.0603,               // FI — canonical rate field (replaces rate/price/tariff)
  "currency": "ZAR",                          // C — payment currency
  "rate_unit": "kWh",                         // C — rate denomination unit
  "rate_schedule": [                          // S — tiered/stepped rate schedule
    {"start_year": 1, "end_year": 5, "rate": 0.0603, "currency": "ZAR", "unit": "kWh"},
    {"start_year": 6, "end_year": 20, "rate": null, "escalation_applies": true}
  ],
  "escalation": {                             // FI/C — escalation model
    "type": "fixed_percent",                  // C — fixed_percent | index | compound
    "value": 5.0,                             // FI — annual escalation percentage
    "index_name": null,                       // C — "CPI" | "PPI" | null
    "base_date": "2024-01-01"                 // C — escalation start reference
  },
  "billing_components": [                     // C — invoice_line_item_type codes applicable
    "METERED_ENERGY",                         //   Maps to invoice_line_item_type table
    "DEEMED_ENERGY",                          //   (022_exchange_rate_and_invoice_validation.sql)
    "MIN_OFFTAKE"                             //   Drives multi-component invoice generation
  ],
  "deemed_energy_method": "irradiance_based", // C — how deemed energy is calculated on meter failure
  "environmental_attributes_owner": "system_owner", // C — who retains RECs/carbon credits
  "payment_currency": "ZAR",                  // C — invoicing currency
  "fx_reference": "SARB",                     // C — exchange rate source
  "fx_base_date": "2024-01-01",              // C — FX baseline date
  "fx_indemnity": {                           // C — FX risk allocation (IVL Egypt pattern)
    "tariff_currency": "USD",                 //   Tariff denominated in one currency
    "payment_currency": "EGP",                //   Payments in another
    "agreed_exchange_rate": 15.70,            //   Baseline FX rate at signing
    "fx_gain_treatment": "credit_to_customer",//   If local currency weakens
    "fx_loss_treatment": "indemnified_by_customer", // If local currency strengthens
    "fx_source": "Central Bank of Egypt",     //   Official rate source
    "fx_reconciliation_frequency": "monthly"  //   How often FX is trued up
  },
  "includes_environmental_attributes": true,  // C — RECs included in price
  "available_energy_billable": true,          // C — bill only available (non-curtailed) energy
  "billing_frequency": "monthly",             // C — invoice generation schedule
  "schedule_reference": "Annexure F"          // R — audit trail
}
```

**Multi-component billing note:** The `billing_components` array lists `invoice_line_item_type` codes from `022_exchange_rate_and_invoice_validation.sql`. The `invoice_line_item` table handles N line items per invoice header natively — the ontology specifies WHICH components apply; the database stores the actual line items. Available type codes: METERED_ENERGY, AVAILABLE_ENERGY, DEEMED_ENERGY, BESS_CAPACITY, MIN_OFFTAKE, DIESEL, OM_FEE, EQUIP_RENTAL, PENALTY, PRICE_CORRECTION, FLAT, TOU, TIERED, INDEXED.

**PAYMENT_TERMS clause normalized_payload:**

```json
{
  "billing_frequency": "monthly",             // C — invoice cycle
  "invoice_timing": "10 business days after month end", // C
  "payment_due_days": 30,                     // C — days after invoice receipt
  "late_payment_interest_rate": "Prime + 2%", // FI — penalty rate
  "currency": "USD",                          // C — payment currency
  "billing_components": [                     // C — which invoice_line_item_type codes apply
    "METERED_ENERGY",                         //   Maps to invoice_line_item_type table
    "DEEMED_ENERGY",                          //   (022_exchange_rate_and_invoice_validation.sql)
    "MIN_OFFTAKE"                             //   Drives multi-component invoice generation
  ],
  "minimum_purchase_percent": 80,             // T — take-or-pay threshold
  "take_or_pay_shortfall_rate": 0.75,         // FI — shortfall payment as fraction of contract price
  "take_or_pay_shortfall_formula": "MAX[0, (Minimum - Actual)] × Rate × Shortfall_Rate", // FD
  "deemed_energy_billing": true,              // C — whether deemed energy is billable during system events
  "fx_reference": null,                       // C — null if single-currency
  "schedule_reference": "Section 8"           // R
}
```

**`billing_components` and `invoice_line_item`:**

Multi-component billing is handled by the `invoice_line_item` table (N line items per `invoice_header`), not by duplicating structure in the ontology. The `billing_components` array in PAYMENT_TERMS lists which `invoice_line_item_type` codes are applicable to this contract — the invoice generator creates a separate line item for each component. See `000_baseline.sql:375-387` for the `invoice_line_item` table and `022_exchange_rate_and_invoice_validation.sql` for the 14 seeded type codes (METERED_ENERGY, AVAILABLE_ENERGY, DEEMED_ENERGY, BESS_CAPACITY, MIN_OFFTAKE, DIESEL, OM_FEE, EQUIP_RENTAL, PENALTY, PRICE_CORRECTION, etc.).

**LIQUIDATED_DAMAGES clause normalized_payload:**

```json
{
  "trigger_type": "availability_shortfall",   // C — what breach triggers this LD
  "calculation_type": "per_point",            // C — per_point | lump_sum | formula
  "ld_per_point": 50000,                      // FI — $/percentage point (base_rule.py:218)
  "rate_unit": "$/percentage_point",          // C — unit label
  "threshold": 95.0,                          // T — reference threshold
  "cap_type": "annual",                       // C — annual | cumulative | per_period
  "ld_cap_annual": 500000,                    // FI — max per year (base_rule.py:219-222)
  "ld_cap_cumulative": 10000000,              // FI — max over contract term
  "cure_period_days": 30,                     // C — time to cure before LD applies
  "payment_due_days": 15,                     // C — days after LD assessment
  "ld_currency": "USD",                       // C — denomination
  "schedule_reference": "Section 11.2"        // R
}
```

**CONDITIONS_PRECEDENT clause normalized_payload:**

```json
{
  "conditions_list": [                        // C — list of CPs
    "All permits and approvals obtained",
    "Interconnection agreement executed",
    "Evidence of insurance provided",
    "72-hour continuous operation at 90% capacity"
  ],
  "responsible_party_by_condition": "Seller",  // C
  "satisfaction_deadline_days": null,          // C — days from effective date
  "waiver_rights": false,                     // C
  "failure_consequences": "Buyer obligations not effective", // C
  "milestone_dates": {                        // C — canonical milestone dates
    "anticipated_cod": "2025-06-01",
    "cod_longstop": "2025-12-31",
    "interconnection_date": "2025-03-01",
    "transfer_date": null,
    "early_operating_start": null             // Pre-COD generation start (if applicable)
  },
  "schedule_reference": "Section 3"           // R
}
```

**SECURITY_PACKAGE clause normalized_payload:**

```json
{
  "payment_security_type": "letter_of_credit", // C — letter_of_credit | bank_bond | parent_guarantee | performance_bond
  "security_amount": 2000000,                 // FI — face value
  "security_currency": "USD",                 // C — denomination of security instrument
  "security_amount_formula": null,            // FD — formula if amount varies
  "issuer_requirements": "Bank with S&P rating A- or better", // C
  "release_conditions": "12 months after COD", // C
  "replenishment_days": 30,                   // C — days to replenish after draw
  "draw_conditions": [                        // C — events enabling draw
    "Uncured Event of Default",
    "Failure to achieve COD by Longstop Date"
  ],
  "expiry_date": null,                        // C — absolute expiry if applicable
  "schedule_reference": "Section 14"          // R
}
```

**FORCE_MAJEURE clause normalized_payload:**

```json
{
  "defined_events": [                         // C — qualifying events
    "Acts of God, earthquakes, floods",
    "War, terrorism, civil unrest",
    "Grid emergencies declared by System Operator"
  ],
  "notification_period_hours": 48,            // C — notice requirement
  "max_duration_days": 365,                   // C — termination trigger
  "documentation_required": true,             // C
  "payment_obligations_during_fm": "suspended", // C — suspended | continues | partial
  "term_extension_on_fm": true,               // C — extend term by FM duration
  "schedule_reference": "Section 15"          // R
}
```

**DEFAULT clause normalized_payload:**

```json
{
  "buyer_default_events": [                   // C — what constitutes buyer default
    "Failure to pay any undisputed amount within 60 days of due date",
    "Material breach not cured within cure period",
    "Insolvency, bankruptcy, or winding-up proceedings",
    "Failure to maintain required insurance"
  ],
  "seller_default_events": [                  // C — what constitutes seller default
    "Failure to achieve COD by Longstop Date",
    "System produces zero output for 30+ consecutive days (non-FM)",
    "Material breach not cured within cure period",
    "Insolvency, bankruptcy, or winding-up proceedings"
  ],
  "payment_overdue_trigger_days": 60,         // T — days of non-payment before default
  "cure_period_days": 30,                     // C — time to cure before consequences
  "cure_notice_method": "Written notice per Section 27", // C
  "cross_default": false,                     // C — whether related agreement defaults trigger here
  "security_draw_on_default": true,           // C — enables SECURITY_PACKAGE draw
  "interest_on_overdue": "Prime + 2%",        // FI — late payment interest formula
  "consequences": [                           // C — enumerated consequences
    "termination_right",
    "security_draw",
    "interest_accrual"
  ],
  "schedule_reference": "Section 22"          // R
}
```

**TERMINATION clause normalized_payload:**

Termination payment structures vary by contract type (see examples below).

```json
{
  "term_years": 20,                           // C — contract duration
  "renewal_option": "5-year extension by mutual agreement", // C
  "renewal_notice_days": 180,                 // C — advance notice for renewal
  "termination_for_convenience": false,       // C — whether party can terminate without cause
  "termination_notice_days": 90,              // C — required notice period
  "termination_payment_structure": "per_wp_declining", // C — per_wp_declining | tiered_by_event | amortized_linear | formula
  "termination_schedule": [                   // S — payment lookup by year
    {"year": 1, "rate_per_wp": 0.74, "currency": "USD"},
    {"year": 5, "rate_per_wp": 0.52, "currency": "USD"},
    {"year": 10, "rate_per_wp": 0.28, "currency": "USD"},
    {"year": 15, "rate_per_wp": 0.02, "currency": "USD"}
  ],
  "installed_capacity_wp": 3240000,           // FI — used in per-Wp calculation
  "buyout_option": {                          // C — end-of-term asset purchase
    "available": true,
    "price_method": "fair_market_value",
    "notice_period_months": 12
  },
  "schedule_reference": "Annexure G"          // R
}
```

*Tiered by event variant (ERG Molo pattern — project-financed):*

```json
{
  "term_years": 20,
  "termination_payment_structure": "tiered_by_event",
  "buyer_default_termination": {              // FD — buyer-caused termination
    "formula": "Project Debt + Equity IRR (lower of actual or 10%) + Contractor Costs",
    "schedule": [
      {"year": 1, "amount": 7563000, "currency": "USD"},
      {"year": 5, "amount": 5200000, "currency": "USD"}
    ]
  },
  "seller_default_termination": {             // FD — seller-caused termination
    "formula": "Project Debt + reduced Equity IRR",
    "schedule": [
      {"year": 1, "amount": 4911000, "currency": "USD"},
      {"year": 5, "amount": 3100000, "currency": "USD"}
    ]
  },
  "fm_termination": {                         // FD — FM-caused termination
    "formula": "Midpoint between buyer default and seller default",
    "schedule": [
      {"year": 1, "amount": 6237000, "currency": "USD"}
    ]
  },
  "pre_cod_termination": {                    // FD — pre-COD seller default
    "formula": "Full recovery of costs incurred",
    "schedule": []
  },
  "schedule_reference": "Schedule 6"
}
```

**MAINTENANCE clause normalized_payload:**

```json
{
  "maintenance_responsibility": "system_owner",  // C — system_owner | customer | third_party
  "scheduled_outage_max_hours_per_year": 200, // FI — deductible maintenance hours
  "scheduled_outage_notice_days": 30,         // C — advance notice for planned maintenance
  "emergency_maintenance_notice_hours": 4,    // C — notice for unplanned maintenance
  "maintenance_window": "daytime_preferred",  // C — preferred maintenance time
  "response_time_hours": 24,                  // T — SLA max hours to respond
  "resolution_time_hours": 72,               // T — SLA max hours to resolve
  "spare_parts_obligation": "System Owner maintains critical spares on-site", // C
  "panel_cleaning_frequency": "quarterly",    // C — required cleaning schedule
  "panel_cleaning_water_supply": "Customer provides ~35m³/year/MW", // C
  "performance_reporting_frequency": "monthly", // C
  "warranty_period_years": 5,                 // C — equipment warranty post-COD
  "schedule_reference": "Annexure D"          // R
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

### 5.5 Implementation: Canonical Schemas and Validation

The canonical schema system is implemented across four files:

**1. Schema Definitions — `python-backend/services/prompts/clause_examples.py`**

`CANONICAL_SCHEMAS` dict defines the expected fields for each of the 13 clause categories. Each field entry includes:
- `name` — canonical field name (e.g., `threshold`, `base_rate_per_kwh`)
- `type` — data type (`number`, `string`, `boolean`, `list`, `object`)
- `role` — consumer role code (T, FI, FD, S, C, R)
- `required` — whether the field must be present (`True`/`False`)
- `aliases` — list of alternative names that map to this canonical name
- `description` — human-readable purpose

`CANONICAL_TERMINOLOGY` dict maps common contract phrases to canonical names across all categories. `resolve_aliases(category, payload)` normalizes field names in a payload using the alias mappings.

**2. Extraction Prompt — `python-backend/services/prompts/clause_extraction_prompt.py`**

`build_extraction_prompt()` includes per-category field lists with role annotations (e.g., `threshold [T]`, `ld_per_point [FI]`). This tells the extraction model exactly which fields to produce and what role each serves.

**3. Payload Validation — `python-backend/services/ontology/payload_validator.py`**

`PayloadValidator` class validates extracted payloads against `CANONICAL_SCHEMAS`:
- Checks required fields are present
- Validates field types match schema definitions
- Resolves aliases to canonical names
- Reports validation errors for missing or malformed fields

**4. Contract Type Profiles — `python-backend/services/contract_parser.py`**

`CONTRACT_TYPE_PROFILES` dict maps contract types (ESA, SSA, PPA, Project Agreement, O&M) to:
- `mandatory_categories` — clause categories that must be extracted
- `optional_categories` — clause categories that may be present
- `distinctive_fields` — fields that distinguish this contract type

After the metadata extraction pass classifies the contract type, the main extraction adjusts which categories are searched with higher priority and which fields are required vs. optional.

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
| CONDITIONS_PRECEDENT | PRICING | TRIGGERS | Milestone date (COD) unlocks pricing/payment start |
| CONDITIONS_PRECEDENT | PAYMENT_TERMS | TRIGGERS | Milestone date unlocks billing obligations |
| AVAILABILITY | LIQUIDATED_DAMAGES | TRIGGERS | Shortfall triggers availability LD |
| PERFORMANCE_GUARANTEE | LIQUIDATED_DAMAGES | TRIGGERS | Shortfall triggers performance LD (all sub-types: capacity_factor, performance_ratio, energy_output) |
| PERFORMANCE_GUARANTEE | PAYMENT_TERMS | TRIGGERS | Energy output shortfall triggers shortfall payment (take-or-pay) |
| PAYMENT_TERMS | DEFAULT | TRIGGERS | Non-payment triggers event of default |
| DEFAULT | TERMINATION | TRIGGERS | Default enables termination right |
| DEFAULT | SECURITY_PACKAGE | TRIGGERS | Default enables security draw |
| COMPLIANCE | DEFAULT | TRIGGERS | Non-compliance can trigger default |
| PRICING | PRICING | TRIGGERS | Escalation triggers price change |
| FORCE_MAJEURE | AVAILABILITY | EXCUSES | FM excuses availability shortfall |
| FORCE_MAJEURE | PERFORMANCE_GUARANTEE | EXCUSES | FM excuses performance shortfall (all sub-types) |
| FORCE_MAJEURE | PAYMENT_TERMS | EXCUSES | FM may suspend payment obligations |
| FORCE_MAJEURE | TERMINATION | TRIGGERS | Extended FM (>365 days, or >180 for Garden City) triggers termination right |
| FORCE_MAJEURE | CONDITIONS_PRECEDENT | TRIGGERS | FM extends milestone dates (COD longstop, interconnection) |
| MAINTENANCE | AVAILABILITY | EXCUSES | Scheduled maintenance excuses downtime |
| PRICING | PAYMENT_TERMS | INPUTS | Price feeds invoice calculation |
| PRICING | LIQUIDATED_DAMAGES | INPUTS | Some LDs reference contract price |
| SECURITY_PACKAGE | DEFAULT | INPUTS | Security instrument status feeds default assessment |
| TERMINATION | SECURITY_PACKAGE | INPUTS | Termination payment may be secured by security instrument |
| DEFAULT | TERMINATION | TRIGGERS | Uncured default after cure_period_days grants termination right |
| DEFAULT | SECURITY_PACKAGE | TRIGGERS | Uncured default enables security draw per draw_conditions |
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

### 6.4 Enhanced Relationship Patterns: Security Trigger Chain

The following relationship edges connect DEFAULT events to their downstream consequences. These extend the existing `relationship_patterns.yaml` configuration.

```
PAYMENT_TERMS ──[non-payment > cure_period]──→ DEFAULT
                                                │
                                           ┌────┴────┐
                                           │         │
                                           ▼         ▼
                                  SECURITY_PACKAGE  TERMINATION
                                  (draw on uncured  (right after
                                   default)          cure expires)
                                                      │
                                                      ▼
                                            termination_schedule
                                            (tier by event type)
```

**New patterns for `relationship_patterns.yaml`:**

| Source | Target | Type | Confidence | Trigger Condition |
|--------|--------|------|------------|-------------------|
| DEFAULT | SECURITY_PACKAGE | TRIGGERS | 0.90 | Uncured event of default → security draw |
| PERFORMANCE_GUARANTEE | PAYMENT_TERMS | TRIGGERS | 0.85 | Energy output < required_energy_output_percent → shortfall payment |
| FORCE_MAJEURE | CONDITIONS_PRECEDENT | TRIGGERS | 0.80 | FM extends milestone dates (COD longstop) |
| FORCE_MAJEURE | PAYMENT_TERMS | EXCUSES | 0.85 | Active FM suspends payment obligations |
| CONDITIONS_PRECEDENT | PRICING | TRIGGERS | 0.90 | COD/transfer date activates billing |
| DEFAULT | TERMINATION | TRIGGERS | 0.90 | Uncured default after cure period → termination right (with cure_period_days parameter) |

---

### 6.5 Contract Type Classification and Schema Influence

Different contract types (observed in CBE portfolio) imply different mandatory clause categories and payload fields. The `metadata_extraction_prompt.py` classifier output should influence which extraction templates and validation rules are applied.

**Contract type → mandatory fields mapping:**

| Contract Type | Example | Mandatory Categories | Distinctive Fields |
|---|---|---|---|
| **ESA** (Energy Services Agreement) | ERG Molo | PRICING, PAYMENT_TERMS, PERFORMANCE_GUARANTEE, AVAILABILITY, TERMINATION, DEFAULT, SECURITY_PACKAGE | `termination_payment_structure: tiered_by_event`, `billing_components` includes BESS_CAPACITY + DIESEL |
| **SSA** (Solar Services Agreement) | IVL, MF01 | PRICING, PAYMENT_TERMS, PERFORMANCE_GUARANTEE, TERMINATION, DEFAULT, MAINTENANCE | `minimum_offtake_percent`, `deemed_energy_method`, `enabling_works`, `environmental_attributes_owner` |
| **PPA** (Power Purchase Agreement) | Standard utility-scale | PRICING, AVAILABILITY, PERFORMANCE_GUARANTEE, LIQUIDATED_DAMAGES, FORCE_MAJEURE | `base_rate_per_kwh`, `threshold` (availability), `ld_per_point` |
| **Project Agreement** (three-party) | Garden City | PRICING, PAYMENT_TERMS, MAINTENANCE, SECURITY_PACKAGE, CONDITIONS_PRECEDENT | Party roles include `operator`, `funding_party`, `client`; `maintenance_responsibility` split |
| **O&M Agreement** | O&M service contracts | MAINTENANCE, AVAILABILITY, COMPLIANCE | `response_time_hours`, `resolution_time_hours`, SLA metrics |

**Party role implications:**

| Contract Type | Typical Party Roles | `responsible_party` Mapping |
|---|---|---|
| ESA | Seller, Buyer | `seller` → System Owner, `buyer` → Customer |
| SSA | System Owner, Customer | `system_owner` → CBE entity, `customer` → Client |
| Project Agreement | SFA (Operator), Funding Party, Client | `operator` → SFA, `funding_party` → Solar4Africa, `client` → GC Retail |
| PPA | Seller, Buyer/Offtaker | `seller` → Generator, `buyer` → Offtaker |

**How this affects extraction:** After the metadata extraction pass classifies the contract type, the main extraction prompt selects the appropriate template variant:
- Template adjusts which clause categories are searched with higher priority
- Template specifies which `normalized_payload` fields are required vs optional
- Validation pass checks mandatory fields for the classified type
- Gold-standard examples in `clause_examples.py` are filtered by contract type

**Implementation:** `CONTRACT_TYPE_PROFILES` in `python-backend/services/contract_parser.py` encodes the mapping above as a Python dict. After `metadata_extraction_prompt.py` classifies the contract type, the parser uses the profile to set extraction priorities and validation rules.

### 6.6 Before / After: Canonical Payload Design

The following examples demonstrate how canonical schemas simplify downstream consumers.

**Rules engine parameter access:**

```python
# BEFORE — guesses field name, uses hardcoded default:
threshold = float(self.params.get('threshold', 95.0))
# If extraction names it 'availability_threshold', silently uses 95.0

# AFTER — schema guarantees 'threshold' exists for AVAILABILITY clauses:
threshold = float(self.params['threshold'])
# KeyError if missing → caught at extraction time, not evaluation time
```

**Invoice pricing extraction:**

```typescript
// BEFORE — 4 field names + regex fallback (invoiceGenerator.ts):
if (typeof payload.rate === 'number') { energyRate = payload.rate }
else if (typeof payload.price === 'number') { energyRate = payload.price }
else if (typeof payload.tariff === 'number') { energyRate = payload.tariff }
// Falls through to regex on raw_text if none match

// AFTER — single canonical field name:
if (typeof payload.base_rate_per_kwh === 'number') {
  energyRate = payload.base_rate_per_kwh
}
```

**Obligation view threshold extraction:**

```sql
-- BEFORE — 6-way COALESCE (015_obligation_view.sql):
COALESCE(
    (c.normalized_payload->>'threshold_percent')::NUMERIC,
    (c.normalized_payload->>'guaranteed_performance_ratio_percent')::NUMERIC,
    (c.normalized_payload->>'guaranteed_capacity_factor_percent')::NUMERIC,
    (c.normalized_payload->>'guaranteed_availability_percent')::NUMERIC,
    (c.normalized_payload->>'threshold')::NUMERIC,
    (c.normalized_payload->>'minimum_availability_percent')::NUMERIC
) AS threshold_value

-- AFTER — single canonical field (023_simplify_obligation_view.sql):
(c.normalized_payload->>'threshold')::NUMERIC AS threshold_value
```

### 6.7 Data Ingestion Pipeline Integration

Role-annotated payload fields integrate with the data ingestion pipeline as follows:

```
meter_reading (from S3 via validator-lambda)
  → meter_aggregate (aggregated per billing period)
    → Rules Engine reads clause.normalized_payload fields by role:
        │
        ├─ T fields (Thresholds)
        │   └─ threshold → "Is availability >= 95%?"
        │
        ├─ FI fields (Formula Inputs)
        │   └─ nameplate_capacity_mw → expected = capacity × hours × efficiency
        │   └─ ld_per_point → ld_amount = shortfall × ld_per_point
        │
        ├─ S fields (Schedules)
        │   └─ rate_schedule → look up rate for current operating year
        │
        ├─ C fields (Configuration)
        │   └─ excused_events → filter event table
        │   └─ evaluation_period → select date range
        │
        └─ R fields (Reference) — not consumed by rules engine
```

**How each role type is consumed at each stage:**

| Stage | T | FI | FD | S | C | R |
|-------|---|----|----|---|---|---|
| **Extraction** | Validated: required | Validated: required | Optional | Optional | Validated: required | Stored |
| **Payload enrichment** | Filled if missing | Filled if missing | — | — | Filled if missing | — |
| **Rules engine — evaluate** | Compared against actual | Used in calculations | Defines calculation | Looked up by period | Controls logic branches | Ignored |
| **Invoice generator** | — | Used as rate/price | — | Looked up by year | Used as currency/unit | Ignored |
| **Obligation view** | Displayed as target | — | — | — | Displayed as period | — |
| **Audit/review** | — | — | — | — | — | Displayed for traceability |

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

**Implementation Files:**

| File | Purpose |
|------|---------|
| `python-backend/services/prompts/clause_examples.py` | `CANONICAL_SCHEMAS`, `CANONICAL_TERMINOLOGY`, `resolve_aliases()`, clause examples |
| `python-backend/services/prompts/clause_extraction_prompt.py` | Extraction prompt with per-category canonical field lists |
| `python-backend/services/ontology/payload_validator.py` | `PayloadValidator` — validates payloads against schemas |
| `python-backend/services/contract_parser.py` | `CONTRACT_TYPE_PROFILES` — contract type → required categories/fields |
| `python-backend/config/relationship_patterns.yaml` | Category-level relationship patterns for auto-detection |
| `lib/workflow/invoiceGenerator.ts` | Client-side invoice generation using canonical payload fields |
| `database/migrations/023_simplify_obligation_view.sql` | Simplified obligation view using canonical field names |

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
| Canonical field names | Single name per concept + alias resolution | Eliminates COALESCE chains, fallback if/else, regex fallbacks |
| Role annotations | T/FI/FD/S/C/R per field | Documents consumer, enables extraction validation |
| Payload validation | Schema-driven at extraction time | Catches missing fields before rules engine sees them |
| Contract type profiles | Type → mandatory categories + fields | Different contract types have different required schemas |
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
