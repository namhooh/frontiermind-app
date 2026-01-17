# Contract Extraction System Recommendations

## Overview

This document provides system recommendations for improving the contract clause extraction workflow. It focuses on:
1. Enhanced Claude API prompts for clause extraction
2. Clause category organization (flat structure)
3. Handling unidentified/unmapped clauses

---

## Recommendation 1: Enhanced Clause Extraction Prompt for Claude API

Use this prompt template when calling Claude API to extract structured clause data from contract text.

### Clause Category Structure

The system uses a **flat hierarchy** for clause categorization (no sub-categories).

#### Complete Category List

| ID | Code | Category | Description | Key Terms to Look For |
|----|------|----------|-------------|----------------------|
| 1 | CONDITIONS_PRECEDENT | **Conditions Precedent** | Requirements before contract becomes effective | "conditions precedent", "CP", "closing conditions" |
| 2 | AVAILABILITY | **Availability** | System uptime, availability guarantees, meter accuracy, curtailment | "availability", "uptime", "meter", "curtailment" |
| 3 | PERFORMANCE_GUARANTEE | **Performance Guarantee** | Output, capacity factor, performance ratio, degradation | "performance ratio", "capacity factor", "degradation" |
| 4 | LIQUIDATED_DAMAGES | **Liquidated Damages** | Penalties for breaches (availability, delay, performance) | "liquidated damages", "LD", "penalty" |
| 5 | PRICING | **Pricing** | Energy rates, escalation, price adjustments | "price", "rate", "$/kWh", "escalation" |
| 6 | PAYMENT_TERMS | **Payment Terms** | Billing, payment timing, take-or-pay obligations | "payment", "invoice", "take or pay", "billing" |
| 7 | DEFAULT | **Default** | Events of default, cure periods, remedies, reimbursement | "default", "breach", "cure", "remedy" |
| 8 | FORCE_MAJEURE | **Force Majeure** | Excused events and related provisions | "force majeure", "act of god", "unforeseeable" |
| 9 | TERMINATION | **Termination** | Contract end, early termination, purchase options, FMV | "termination", "expiration", "purchase option", "fair market value" |
| 10 | MAINTENANCE | **Maintenance** | O&M obligations, SLAs, scheduled outages, responsibilities | "maintenance", "O&M", "service level", "outage" |
| 11 | COMPLIANCE | **Compliance** | Regulatory, environmental, legal requirements | "compliance", "regulatory", "permit", "environmental" |
| 12 | SECURITY_PACKAGE | **Security Package** | Letters of credit, bonds, guarantees, collateral | "letter of credit", "LC", "bond", "guarantee", "security" |
| 13 | GENERAL | **General** | Governing law, disputes, notices, assignments, confidentiality | "governing law", "dispute", "notice", "confidential", "assignment" |

#### Category Design Notes

The following items were consolidated into main categories:

| Original Item | Merged Into | Rationale |
|---------------|-------------|-----------|
| Meter Accuracy Test | **Availability** | Meter accuracy directly affects availability measurement |
| Curtailment Cap | **Availability** | Curtailment impacts available generation hours |
| Take or Pay Conditions | **Payment Terms** | Payment obligation structure |
| Remedy Timeline | **Default** | Cure periods are part of default provisions |
| Reimbursement | **Default** | Cost recovery follows default events |
| Purchase Option | **Termination** | End-of-term purchase is termination-related |
| Fair Market Value | **Termination** | FMV methodology for buyouts at termination |
| Service Level Agreement | **Maintenance** | SLAs are maintenance performance standards |
| Scheduled Outage | **Maintenance** | Outage management is core maintenance |
| Responsibility | **Maintenance** | Party responsibilities for maintenance tasks |
| Confidentiality | **General** | Standard contract provision |

---

#### Database Schema

```sql
-- Clause categories (flat structure, no sub-categories)
CREATE TABLE clause_category (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(500),
    key_terms TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Clause table references category (nullable for UNIDENTIFIED)
-- clause_category_id can be NULL when category = 'UNIDENTIFIED'
```

#### Seed Data SQL

```sql
INSERT INTO clause_category (id, code, name, description, key_terms) VALUES
(1, 'CONDITIONS_PRECEDENT', 'Conditions Precedent', 
   'Requirements that must be satisfied before contract becomes effective', 
   ARRAY['conditions precedent', 'CP', 'condition to', 'effectiveness', 'closing conditions', 'prerequisite']),

(2, 'AVAILABILITY', 'Availability', 
   'System uptime, availability guarantees, meter accuracy, and curtailment provisions', 
   ARRAY['availability', 'uptime', 'meter accuracy', 'curtailment', 'unavailability', 'outage hours']),

(3, 'PERFORMANCE_GUARANTEE', 'Performance Guarantee', 
   'Output guarantees, capacity factor, performance ratio, and degradation allowances', 
   ARRAY['performance ratio', 'capacity factor', 'degradation', 'output guarantee', 'energy production', 'PR guarantee']),

(4, 'LIQUIDATED_DAMAGES', 'Liquidated Damages', 
   'Penalties for contract breaches including availability shortfall, delays, and performance failures', 
   ARRAY['liquidated damages', 'LD', 'penalty', 'damages', 'shortfall payment', 'delay damages']),

(5, 'PRICING', 'Pricing', 
   'Energy rates, price escalation, indexing, and adjustment mechanisms', 
   ARRAY['price', 'rate', '$/kWh', '$/MWh', 'escalation', 'price adjustment', 'tariff']),

(6, 'PAYMENT_TERMS', 'Payment Terms', 
   'Billing cycles, payment timing, take-or-pay obligations, and invoice procedures', 
   ARRAY['payment', 'invoice', 'billing', 'take or pay', 'minimum purchase', 'due date', 'net days']),

(7, 'DEFAULT', 'Default', 
   'Events of default, cure periods, remedies, and reimbursement provisions', 
   ARRAY['default', 'breach', 'event of default', 'cure', 'remedy', 'reimbursement', 'failure to perform']),

(8, 'FORCE_MAJEURE', 'Force Majeure', 
   'Excused events beyond party control and related relief provisions', 
   ARRAY['force majeure', 'act of god', 'unforeseeable', 'beyond control', 'excused event']),

(9, 'TERMINATION', 'Termination', 
   'Contract end provisions, early termination rights, purchase options, and fair market value', 
   ARRAY['termination', 'expiration', 'early termination', 'purchase option', 'fair market value', 'buyout', 'FMV']),

(10, 'MAINTENANCE', 'Maintenance', 
    'O&M obligations, service level agreements, scheduled outages, and party responsibilities', 
    ARRAY['maintenance', 'O&M', 'service level', 'SLA', 'scheduled outage', 'repair', 'preventive maintenance']),

(11, 'COMPLIANCE', 'Compliance', 
    'Regulatory, environmental, and legal compliance requirements', 
    ARRAY['compliance', 'regulatory', 'permit', 'environmental', 'law', 'regulation', 'license']),

(12, 'SECURITY_PACKAGE', 'Security Package', 
    'Financial security instruments including letters of credit, bonds, and guarantees', 
    ARRAY['letter of credit', 'LC', 'bond', 'guarantee', 'security', 'collateral', 'parent guarantee']),

(13, 'GENERAL', 'General', 
    'Standard contract terms including governing law, disputes, notices, assignments, and confidentiality', 
    ARRAY['governing law', 'dispute', 'notice', 'assignment', 'amendment', 'waiver', 'confidential', 'severability']);

-- Reset sequence to continue after seed data
SELECT setval('clause_category_id_seq', 13);
```

---

### Handling Unidentified/Unmapped Clauses

When the extraction identifies a clause that doesn't match predefined categories:

1. Set `category` to `"UNIDENTIFIED"` in the extraction output
2. Set `clause_category_id` to `NULL` in the database
3. Store the AI's suggested category in `normalized_payload` for reference

#### Example: Unidentified Clause in Extraction Output

```json
{
  "clause_id": "clause_015",
  "category": "UNIDENTIFIED",
  "category_confidence": 0.35,
  "suggested_category": "Compliance",
  "section_reference": "Section 12.4",
  "raw_text": "The parties agree to participate in quarterly business reviews to discuss performance metrics and forecasting...",
  "normalized_payload": {
    "clause_summary": "Quarterly business review requirement",
    "key_terms": {
      "frequency": "quarterly",
      "participants": ["Owner", "Utilities"],
      "topics": ["performance", "issues", "forecasting"]
    },
    "ai_notes": "Does not fit standard categories. Closest match is Compliance or General."
  },
  "extraction_confidence": 0.80
}
```

#### Example: Database Storage for Unidentified Clause

```sql
INSERT INTO clause (
    contract_id,
    clause_category_id,  -- NULL for unidentified
    section_reference,
    raw_text,
    normalized_payload,
    confidence_score
) VALUES (
    123,
    NULL,  -- UNIDENTIFIED = NULL category
    'Section 12.4',
    'The parties agree to participate in quarterly business reviews...',
    '{
      "clause_summary": "Quarterly business review requirement",
      "key_terms": {"frequency": "quarterly"},
      "suggested_category": "Compliance",
      "category_confidence": 0.35,
      "ai_notes": "Does not fit standard categories"
    }'::jsonb,
    0.80
);
```

#### Querying Unidentified Clauses

```sql
-- Find all unidentified clauses for review
SELECT 
    c.id,
    c.section_reference,
    c.raw_text,
    c.normalized_payload->>'suggested_category' as suggested_category,
    c.normalized_payload->>'clause_summary' as summary,
    c.confidence_score
FROM clause c
WHERE c.clause_category_id IS NULL
ORDER BY c.created_at DESC;
```

---

### Claude API Prompt Template

**File:** `backend/services/prompts/clause_extraction_prompt.py`

```python
"""
Claude API Prompt for Contract Clause Extraction

This prompt should be used AFTER LlamaParse has converted the PDF to text.
It extracts structured clause data suitable for the rules engine.
"""

CLAUSE_EXTRACTION_SYSTEM_PROMPT = """You are an expert contract analyst specializing in energy contracts (PPAs, O&M agreements, EPC contracts). 

Your task is to extract specific clause types from contracts and return them in a structured JSON format that can be used by an automated compliance monitoring system.

IMPORTANT RULES:
1. Extract BOTH the raw text AND normalized numeric values
2. Provide confidence scores for each extraction
3. Note any ambiguities or uncertainties
4. Preserve section references for audit trails
5. Map each clause to the predefined categories when possible
6. If a clause doesn't fit predefined categories, set category to "UNIDENTIFIED" and include your suggested category
7. Extract ALL clauses found in the contract - every clause must be recorded"""


CLAUSE_EXTRACTION_USER_PROMPT = """Extract clauses from this energy contract. For each clause found, provide BOTH the raw text AND a normalized structure.

CONTRACT TEXT:
{contract_text}

---

## PREDEFINED CLAUSE CATEGORIES

Map each extracted clause to ONE of these 13 categories. If a clause doesn't fit any category with confidence >= 0.6, mark it as "UNIDENTIFIED".

### 1. CONDITIONS PRECEDENT
**Code:** CONDITIONS_PRECEDENT
**Description:** Requirements that must be satisfied before contract becomes effective
**Look for:** "conditions precedent", "CP", "condition to", "effectiveness", "closing conditions"

Extract and normalize:
- conditions_list: List of all CPs with descriptions
- responsible_party_by_condition: Who satisfies each CP
- satisfaction_deadline_days: Days to satisfy all CPs
- waiver_rights: Whether CPs can be waived
- failure_consequences: What happens if CPs not satisfied


### 2. AVAILABILITY
**Code:** AVAILABILITY
**Description:** System uptime, availability guarantees, meter accuracy, and curtailment provisions
**Look for:** "availability", "uptime", "meter accuracy", "curtailment", "unavailability", "outage hours"

Extract and normalize:
- threshold_percent: Guaranteed minimum availability (e.g., 95.0)
- measurement_period: "monthly", "quarterly", "annual"
- calculation_method: Formula or method description
- excused_events: List of events that don't count against availability
- meter_accuracy_threshold_percent: Error threshold for meter testing (e.g., 2.0)
- meter_test_frequency: How often meters are tested
- meter_adjustment_lookback_years: How far back adjustments apply
- curtailment_cap_hours: Maximum allowed curtailment hours per period
- curtailment_cap_percent: Maximum curtailment as percentage
- curtailment_compensation_rate: Payment for excess curtailment


### 3. PERFORMANCE GUARANTEE
**Code:** PERFORMANCE_GUARANTEE
**Description:** Output guarantees, capacity factor, performance ratio, and degradation allowances
**Look for:** "performance ratio", "capacity factor", "degradation", "output guarantee", "energy production"

Extract and normalize:
- guaranteed_performance_ratio_percent: PR guarantee (e.g., 80.0)
- guaranteed_capacity_factor_percent: CF guarantee (e.g., 25.0)
- guaranteed_annual_production_kwh: Annual energy guarantee
- measurement_period: "monthly", "quarterly", "annual"
- degradation_rate_percent_per_year: Annual degradation allowance
- weather_adjustment_method: How weather affects calculations
- test_conditions: Conditions for performance testing


### 4. LIQUIDATED DAMAGES
**Code:** LIQUIDATED_DAMAGES
**Description:** Penalties for contract breaches including availability shortfall, delays, and performance failures
**Look for:** "liquidated damages", "LD", "penalty", "damages", "shortfall payment", "delay damages"

Extract and normalize:
- trigger_type: "availability_shortfall", "performance_shortfall", "delay", "non_delivery"
- calculation_type: "per_point", "per_day", "per_kwh", "flat_fee", "formula"
- rate: The LD rate value
- rate_unit: Unit for the rate (e.g., "$/point", "$/day", "$/kWh")
- cap_type: "annual", "cumulative", "per_event", "percentage_of_contract"
- cap_amount: Cap value in dollars (if fixed)
- cap_percent: Cap as percentage of contract/revenue (if percentage)


### 5. PRICING
**Code:** PRICING
**Description:** Energy rates, price escalation, indexing, and adjustment mechanisms
**Look for:** "price", "rate", "$/kWh", "$/MWh", "escalation", "price adjustment", "tariff"

Extract and normalize:
- pricing_structure: "fixed", "escalating", "indexed", "tiered", "time_of_use"
- base_rate: Starting rate value
- base_rate_unit: "$/kWh" or "$/MWh"
- escalation_rate_percent_per_year: Annual escalation percentage
- escalation_index: Index name if indexed (e.g., "CPI", "PPI")
- escalation_start_year: When escalation begins
- price_schedule: Array of {year, rate} for each contract year


### 6. PAYMENT TERMS
**Code:** PAYMENT_TERMS
**Description:** Billing cycles, payment timing, take-or-pay obligations, and invoice procedures
**Look for:** "payment", "invoice", "billing", "take or pay", "minimum purchase", "due date"

Extract and normalize:
- billing_frequency: "monthly", "quarterly", "annual"
- invoice_timing: When invoices are issued (e.g., "5th business day")
- payment_due_days: Days after invoice to pay
- late_payment_interest_rate_percent: Interest rate on overdue amounts
- currency: Payment currency (e.g., "USD")
- minimum_purchase_percent: Minimum offtake obligation as percentage
- minimum_purchase_kwh: Minimum offtake in kWh
- take_or_pay_shortfall_rate: Rate for shortfall payment


### 7. DEFAULT
**Code:** DEFAULT
**Description:** Events of default, cure periods, remedies, and reimbursement provisions
**Look for:** "default", "breach", "event of default", "cure", "remedy", "reimbursement"

Extract and normalize:
- owner_default_events: List of seller/owner default triggers
- buyer_default_events: List of buyer/offtaker default triggers
- cure_period_days: Standard cure period
- extended_cure_period_days: Extended period for complex cures
- cure_notice_method: How cure notice must be given
- cross_default_applies: true/false
- reimbursable_costs: List of recoverable costs
- reimbursement_cap: Maximum reimbursement amount


### 8. FORCE MAJEURE
**Code:** FORCE_MAJEURE
**Description:** Excused events beyond party control and related relief provisions
**Look for:** "force majeure", "act of god", "unforeseeable", "beyond control", "excused event"

Extract and normalize:
- defined_events: List of qualifying FM events
- notification_period_hours: Time to notify other party
- documentation_required: What proof is needed
- max_duration_days: Maximum FM period before termination rights
- termination_notice_days: Notice required to terminate for FM
- payment_obligations_during_fm: Whether payments continue
- extension_of_term: Whether contract term extends


### 9. TERMINATION
**Code:** TERMINATION
**Description:** Contract end provisions, early termination rights, purchase options, and fair market value
**Look for:** "termination", "expiration", "early termination", "purchase option", "fair market value", "buyout"

Extract and normalize:
- initial_term_years: Primary contract duration
- extension_term_years: Extension period length
- extension_count: Number of extensions allowed
- extension_notice_days: Notice to exercise extension
- early_termination_by_owner: Conditions allowing owner termination
- early_termination_by_buyer: Conditions allowing buyer termination
- termination_notice_days: Required notice period
- termination_fee_formula: How termination fee is calculated
- purchase_option_exists: true/false
- purchase_option_timing: When option can be exercised
- purchase_price_basis: "fair_market_value", "book_value", "fixed_price"
- fmv_methodology: How FMV is determined
- fmv_appraiser_process: Process for selecting appraiser


### 10. MAINTENANCE
**Code:** MAINTENANCE
**Description:** O&M obligations, service level agreements, scheduled outages, and party responsibilities
**Look for:** "maintenance", "O&M", "service level", "SLA", "scheduled outage", "repair"

Extract and normalize:
- maintenance_responsible_party: "owner", "buyer", "third_party"
- maintenance_standard: Standard to be met (e.g., "prudent industry practice")
- response_time_hours: Response time for issues
- resolution_time_hours: Time to resolve issues
- sla_availability_percent: SLA availability target
- sla_penalties: Penalties for missing SLA
- scheduled_outage_notice_days: Advance notice for planned outages
- scheduled_outage_max_hours_per_year: Maximum scheduled outage hours
- scheduled_outage_window: When outages can be scheduled
- owner_maintenance_responsibilities: List of owner duties
- buyer_maintenance_responsibilities: List of buyer duties


### 11. COMPLIANCE
**Code:** COMPLIANCE
**Description:** Regulatory, environmental, and legal compliance requirements
**Look for:** "compliance", "regulatory", "permit", "environmental", "law", "regulation"

Extract and normalize:
- compliance_responsible_party: Who ensures compliance
- required_permits: List of required permits/licenses
- environmental_standards: Environmental requirements to meet
- reporting_obligations: Required reports and frequency
- change_in_law_provisions: How law changes are handled
- compliance_cost_allocation: Who bears compliance costs


### 12. SECURITY PACKAGE
**Code:** SECURITY_PACKAGE
**Description:** Financial security instruments including letters of credit, bonds, and guarantees
**Look for:** "letter of credit", "LC", "bond", "guarantee", "security", "collateral"

Extract and normalize:
- security_type: "letter_of_credit", "surety_bond", "parent_guarantee", "cash_deposit"
- security_amount: Dollar amount required
- security_amount_formula: If amount varies (e.g., "6 months revenue")
- issuer_requirements: Requirements for issuing institution
- security_term: Duration of security
- release_conditions: When security is released
- draw_conditions: When security can be drawn


### 13. GENERAL
**Code:** GENERAL
**Description:** Standard contract terms including governing law, disputes, notices, assignments, and confidentiality
**Look for:** "governing law", "dispute", "notice", "assignment", "amendment", "waiver", "confidential"

Extract and normalize:
- governing_law: Applicable law/jurisdiction
- dispute_resolution_method: "litigation", "arbitration", "mediation"
- dispute_venue: Where disputes are heard
- notice_method: How notices must be given
- notice_addresses: Party addresses for notices
- assignment_restrictions: Limitations on assignment
- assignment_consent_required: Whether consent needed
- amendment_requirements: How contract can be amended
- waiver_requirements: Conditions for waiving rights
- confidentiality_period_years: Duration of confidentiality obligation
- confidential_information_definition: What's considered confidential
- confidentiality_exclusions: What's not confidential
- permitted_disclosures: Allowed disclosures (e.g., to advisors, regulators)

---

## RESPONSE FORMAT

Return a JSON object with the following structure:

```json
{
  "clauses": [
    {
      "clause_id": "clause_001",
      "category": "AVAILABILITY",
      "category_code": "AVAILABILITY",
      "category_confidence": 0.95,
      "section_reference": "Section 4.2",
      "raw_text": "The exact text from the contract covering this clause...",
      "normalized_payload": {
        "threshold_percent": 95.0,
        "measurement_period": "annual",
        "meter_accuracy_threshold_percent": 2.0,
        "excused_events": ["force_majeure", "grid_curtailment", "scheduled_maintenance"]
      },
      "extraction_confidence": 0.90,
      "notes": "Availability measured annually with 95% guarantee"
    },
    {
      "clause_id": "clause_002",
      "category": "UNIDENTIFIED",
      "category_code": null,
      "category_confidence": 0.40,
      "suggested_category": "COMPLIANCE",
      "section_reference": "Section 15.3",
      "raw_text": "The parties shall conduct quarterly business reviews to discuss...",
      "normalized_payload": {
        "clause_summary": "Quarterly business review requirement",
        "key_terms": {
          "frequency": "quarterly",
          "participants": ["Owner", "Utilities"]
        },
        "ai_notes": "Does not fit standard categories. Closest match is Compliance or General."
      },
      "extraction_confidence": 0.85,
      "notes": "Could not confidently categorize - marked as UNIDENTIFIED for review"
    }
  ],
  
  "extraction_summary": {
    "contract_type_detected": "PPA",
    "total_clauses_extracted": 12,
    "clauses_by_category": {
      "CONDITIONS_PRECEDENT": 1,
      "AVAILABILITY": 1,
      "PERFORMANCE_GUARANTEE": 1,
      "LIQUIDATED_DAMAGES": 2,
      "PRICING": 1,
      "PAYMENT_TERMS": 1,
      "DEFAULT": 1,
      "FORCE_MAJEURE": 1,
      "TERMINATION": 1,
      "GENERAL": 1,
      "UNIDENTIFIED": 1
    },
    "unidentified_count": 1,
    "average_confidence": 0.85,
    "extraction_warnings": [
      "No SECURITY_PACKAGE clause found in contract",
      "Pricing rates appear to be placeholders ($0.xx)"
    ],
    "is_template": false
  }
}
```

---

## IMPORTANT INSTRUCTIONS

1. **Extract ALL Clauses:**
   - Every clause in the contract must be extracted and recorded
   - If a clause exists but doesn't clearly match a category, record it as UNIDENTIFIED
   - Do not skip clauses just because they are difficult to categorize

2. **Category Assignment:**
   - Assign ONE category per clause
   - Use category_confidence to indicate certainty (0.0-1.0)
   - If confidence < 0.6, set category to "UNIDENTIFIED"

3. **For UNIDENTIFIED clauses:**
   - Set `category` to `"UNIDENTIFIED"`
   - Set `category_code` to `null`
   - Include `suggested_category` with your best guess (use the category CODE)
   - In normalized_payload, include `clause_summary` and relevant `key_terms`
   - Add `ai_notes` explaining why it doesn't fit

4. **Confidence Scoring:**
   - `category_confidence`: Certainty about category match (0.0-1.0)
   - `extraction_confidence`: Certainty about extracted values (0.0-1.0)

5. **Always Include:**
   - `section_reference` for traceability
   - `raw_text` for audit purposes
   - `normalized_payload` with extracted values for rules engine

6. **Extraction Warnings:**
   - Note common clauses that were NOT found (e.g., "No Force Majeure clause found")
   - Flag template indicators (placeholder values like $0.xx or ___)
   - Identify potential issues for human review
"""


def build_extraction_prompt(contract_text: str, contract_type_hint: str = None) -> dict:
    """
    Build the complete prompt for Claude API.
    
    Args:
        contract_text: The anonymized contract text from LlamaParse
        contract_type_hint: Optional hint about contract type (PPA, O&M, EPC)
        
    Returns:
        Dict with 'system' and 'user' prompts ready for Claude API
    """
    
    user_prompt = CLAUSE_EXTRACTION_USER_PROMPT.format(
        contract_text=contract_text
    )
    
    if contract_type_hint:
        user_prompt = f"CONTRACT TYPE HINT: This appears to be a {contract_type_hint} agreement.\n\n" + user_prompt
    
    return {
        'system': CLAUSE_EXTRACTION_SYSTEM_PROMPT,
        'user': user_prompt
    }
```

---

## Database Mapper

**File:** `backend/services/database_mapper.py`

Maps the Claude extraction output to database table rows, including handling UNIDENTIFIED clauses.

```python
"""
Database Schema Mapper

Maps extracted contract JSON to database table rows.
Handles category mapping including UNIDENTIFIED clauses.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import json


class DatabaseMapper:
    """Map extracted contract data to database schema"""
    
    # Category code to ID mapping (must match clause_category table)
    CATEGORY_ID_MAP = {
        'CONDITIONS_PRECEDENT': 1,
        'AVAILABILITY': 2,
        'PERFORMANCE_GUARANTEE': 3,
        'LIQUIDATED_DAMAGES': 4,
        'PRICING': 5,
        'PAYMENT_TERMS': 6,
        'DEFAULT': 7,
        'FORCE_MAJEURE': 8,
        'TERMINATION': 9,
        'MAINTENANCE': 10,
        'COMPLIANCE': 11,
        'SECURITY_PACKAGE': 12,
        'GENERAL': 13,
        'UNIDENTIFIED': None,  # NULL in database
    }

    def map_clauses_to_database(
        self, 
        extracted_data: Dict[str, Any],
        contract_id: int
    ) -> List[Dict]:
        """
        Map extracted clauses to database rows.
        
        Handles:
        - Identified clauses → clause_category_id set to mapped ID
        - UNIDENTIFIED clauses → clause_category_id = NULL, suggested_category in normalized_payload
        
        Args:
            extracted_data: Full extracted JSON from Claude
            contract_id: ID of the contract record
            
        Returns:
            List of clause rows ready for database insert
        """
        clause_rows = []
        clauses = extracted_data.get('clauses', [])
        
        for clause in clauses:
            row = self._map_single_clause(clause, contract_id)
            clause_rows.append(row)
        
        return clause_rows

    def _map_single_clause(self, clause: Dict, contract_id: int) -> Dict:
        """Map a single clause to database row"""
        
        category = clause.get('category')
        category_code = clause.get('category_code')
        is_unidentified = (category == 'UNIDENTIFIED')
        
        # Get category ID (None for UNIDENTIFIED)
        category_id = self.CATEGORY_ID_MAP.get(category_code or category)
        
        # Build normalized_payload
        normalized_payload = clause.get('normalized_payload', {})
        
        # For UNIDENTIFIED, add suggested category info to payload
        if is_unidentified:
            normalized_payload['suggested_category'] = clause.get('suggested_category')
            normalized_payload['category_confidence'] = clause.get('category_confidence')
            normalized_payload['ai_notes'] = clause.get('notes', 'Could not match to predefined category')
        
        # Build the row
        row = {
            'contract_id': contract_id,
            'clause_category_id': category_id,  # NULL for UNIDENTIFIED
            'section_reference': clause.get('section_reference'),
            'raw_text': clause.get('raw_text'),
            'normalized_payload': normalized_payload,
            'confidence_score': clause.get('extraction_confidence'),
        }
        
        return row

    def map_extraction_to_database(
        self,
        extracted_data: Dict[str, Any],
        contract_id: int,
        project_id: int
    ) -> Dict[str, Any]:
        """
        Map full extraction output to all relevant database tables.
        
        Args:
            extracted_data: Full extracted JSON from Claude
            contract_id: ID of the contract record
            project_id: ID of the project
            
        Returns:
            Dict with rows for each table
        """
        return {
            'clauses': self.map_clauses_to_database(extracted_data, contract_id),
            'extraction_metadata': {
                'contract_id': contract_id,
                'project_id': project_id,
                'extracted_at': datetime.utcnow().isoformat(),
                'total_clauses': extracted_data.get('extraction_summary', {}).get('total_clauses_extracted', 0),
                'unidentified_count': extracted_data.get('extraction_summary', {}).get('unidentified_count', 0),
                'average_confidence': extracted_data.get('extraction_summary', {}).get('average_confidence', 0),
                'is_template': extracted_data.get('extraction_summary', {}).get('is_template', False),
                'warnings': extracted_data.get('extraction_summary', {}).get('extraction_warnings', []),
            }
        }
```

---

## Summary

### What's Included

1. **13 Clause Categories** - Flat structure with code, name, description, and key_terms
2. **Unidentified Clause Handling** - Set `category: "UNIDENTIFIED"` and `clause_category_id = NULL`
3. **Claude API Prompt** - Complete extraction prompt for all categories
4. **Database Mapper** - Maps extraction output to database schema

### Files to Create

```
backend/
└── services/
    ├── database_mapper.py
    └── prompts/
        └── clause_extraction_prompt.py
```

### Database Schema

```sql
CREATE TABLE clause_category (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(500),
    key_terms TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Category Quick Reference

| ID | Code | Category |
|----|------|----------|
| 1 | CONDITIONS_PRECEDENT | Conditions Precedent |
| 2 | AVAILABILITY | Availability |
| 3 | PERFORMANCE_GUARANTEE | Performance Guarantee |
| 4 | LIQUIDATED_DAMAGES | Liquidated Damages |
| 5 | PRICING | Pricing |
| 6 | PAYMENT_TERMS | Payment Terms |
| 7 | DEFAULT | Default |
| 8 | FORCE_MAJEURE | Force Majeure |
| 9 | TERMINATION | Termination |
| 10 | MAINTENANCE | Maintenance |
| 11 | COMPLIANCE | Compliance |
| 12 | SECURITY_PACKAGE | Security Package |
| 13 | GENERAL | General |
