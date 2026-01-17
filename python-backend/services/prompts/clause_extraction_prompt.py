"""
Claude API Prompt for Contract Clause Extraction

This prompt should be used AFTER LlamaParse has converted the PDF to text.
It extracts structured clause data suitable for the rules engine.

Updated January 2026: 13-category flat structure per CONTRACT_EXTRACTION_RECOMMENDATIONS.
"""

from typing import Optional


CLAUSE_EXTRACTION_SYSTEM_PROMPT = """You are an expert contract analyst specializing in energy contracts (PPAs, O&M agreements, EPC contracts).

Your task is to extract specific clause types from contracts and return them in a structured JSON format that can be used by an automated compliance monitoring system.

IMPORTANT RULES:
1. Extract BOTH the raw text AND normalized numeric values
2. Provide confidence scores for each extraction
3. Note any ambiguities or uncertainties
4. Preserve section references for audit trails
5. Map each clause to the predefined categories when possible
6. If a clause doesn't fit predefined categories, set category to "UNIDENTIFIED" and include your suggested category
7. Extract ALL clauses found in the contract - every clause must be recorded
8. IMPORTANT: Extract MULTIPLE clauses per category when applicable:
   - Multiple LIQUIDATED_DAMAGES clauses (availability LD, delay LD, performance LD)
   - Multiple DEFAULT events (seller defaults, buyer defaults)
   - Multiple TERMINATION triggers (early termination, expiration, default termination)
   - Multiple PRICING provisions (base rate, escalation, adjustments)
   - Multiple COMPLIANCE requirements (permits, reporting, environmental)
9. Aim to extract 20-30 clauses from a typical PPA contract"""


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
- curtailment_cap_hours: Maximum allowed curtailment hours per period
- curtailment_cap_percent: Maximum curtailment as percentage


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


### 8. FORCE MAJEURE
**Code:** FORCE_MAJEURE
**Description:** Excused events beyond party control and related relief provisions
**Look for:** "force majeure", "act of god", "unforeseeable", "beyond control", "excused event"

Extract and normalize:
- defined_events: List of qualifying FM events
- notification_period_hours: Time to notify other party
- documentation_required: What proof is needed
- max_duration_days: Maximum FM period before termination rights
- payment_obligations_during_fm: Whether payments continue


### 9. TERMINATION
**Code:** TERMINATION
**Description:** Contract end provisions, early termination rights, purchase options, and fair market value
**Look for:** "termination", "expiration", "early termination", "purchase option", "fair market value", "buyout"

Extract and normalize:
- initial_term_years: Primary contract duration
- extension_term_years: Extension period length
- extension_count: Number of extensions allowed
- early_termination_by_owner: Conditions allowing owner termination
- early_termination_by_buyer: Conditions allowing buyer termination
- termination_notice_days: Required notice period
- purchase_option_exists: true/false
- purchase_price_basis: "fair_market_value", "book_value", "fixed_price"


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
- scheduled_outage_notice_days: Advance notice for planned outages
- scheduled_outage_max_hours_per_year: Maximum scheduled outage hours


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


### 12. SECURITY PACKAGE
**Code:** SECURITY_PACKAGE
**Description:** Financial security instruments including letters of credit, bonds, and guarantees
**Look for:** "letter of credit", "LC", "bond", "guarantee", "security", "collateral"

Extract and normalize:
- security_type: "letter_of_credit", "surety_bond", "parent_guarantee", "cash_deposit"
- security_amount: Dollar amount required
- security_amount_formula: If amount varies (e.g., "6 months revenue")
- issuer_requirements: Requirements for issuing institution
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
- assignment_restrictions: Limitations on assignment
- confidentiality_period_years: Duration of confidentiality obligation

---

## RESPONSE FORMAT

Return a JSON object with the following structure:

```json
{{
  "clauses": [
    {{
      "clause_id": "clause_001",
      "clause_name": "Availability Guarantee",
      "category": "AVAILABILITY",
      "category_code": "AVAILABILITY",
      "category_confidence": 0.95,
      "section_reference": "Section 4.2",
      "raw_text": "The exact text from the contract covering this clause...",
      "normalized_payload": {{
        "threshold_percent": 95.0,
        "measurement_period": "annual",
        "excused_events": ["force_majeure", "grid_curtailment", "scheduled_maintenance"]
      }},
      "responsible_party": "Seller",
      "beneficiary_party": "Buyer",
      "extraction_confidence": 0.90,
      "notes": "Availability measured annually with 95% guarantee"
    }},
    {{
      "clause_id": "clause_002",
      "clause_name": "Business Review Meeting",
      "category": "UNIDENTIFIED",
      "category_code": null,
      "category_confidence": 0.40,
      "suggested_category": "COMPLIANCE",
      "section_reference": "Section 15.3",
      "raw_text": "The parties shall conduct quarterly business reviews to discuss...",
      "normalized_payload": {{
        "clause_summary": "Quarterly business review requirement",
        "key_terms": {{
          "frequency": "quarterly",
          "participants": ["Owner", "Utilities"]
        }},
        "ai_notes": "Does not fit standard categories. Closest match is Compliance or General."
      }},
      "responsible_party": "Both",
      "beneficiary_party": null,
      "extraction_confidence": 0.85,
      "notes": "Could not confidently categorize - marked as UNIDENTIFIED for review"
    }}
  ],

  "extraction_summary": {{
    "contract_type_detected": "PPA",
    "total_clauses_extracted": 12,
    "clauses_by_category": {{
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
    }},
    "unidentified_count": 1,
    "average_confidence": 0.85,
    "extraction_warnings": [
      "No SECURITY_PACKAGE clause found in contract",
      "Pricing rates appear to be placeholders ($0.xx)"
    ],
    "is_template": false
  }}
}}
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


def _build_examples_section() -> str:
    """Build the few-shot examples section for the prompt."""
    from .clause_examples import CLAUSE_EXAMPLES

    examples_text = """

---

## FEW-SHOT EXAMPLES

The following are gold-standard extraction examples. Use these as reference for how to extract and structure clauses:

"""
    # Add compact examples for high-priority categories
    priority_categories = [
        "LIQUIDATED_DAMAGES",
        "AVAILABILITY",
        "PERFORMANCE_GUARANTEE",
        "PRICING",
        "SECURITY_PACKAGE",
        "DEFAULT"
    ]

    for cat_code in priority_categories:
        example = CLAUSE_EXAMPLES.get(cat_code)
        if example:
            raw = example["example_raw_text"].strip()[:300]
            ext = example["example_extraction"]
            payload = ext["normalized_payload"]

            # Get first 3 payload items
            payload_preview = {k: v for k, v in list(payload.items())[:3] if v is not None}

            examples_text += f"""
### {cat_code} Example
**Raw text:** "{raw}..."
**Extracted:** clause_name="{ext['clause_name']}", normalized_payload includes: {payload_preview}

"""

    return examples_text


def build_extraction_prompt(
    contract_text: str,
    contract_type_hint: Optional[str] = None,
    valid_categories: Optional[list] = None,
    include_examples: bool = False  # Disabled: examples reduced clause count from 19→15
) -> dict:
    """
    Build the complete prompt for Claude API.

    Args:
        contract_text: The anonymized contract text from LlamaParse
        contract_type_hint: Optional hint about contract type (PPA, O&M, EPC)
        valid_categories: Optional list of valid category codes from database
        include_examples: Whether to include few-shot examples (default True)

    Returns:
        Dict with 'system' and 'user' prompts ready for Claude API
    """
    user_prompt = CLAUSE_EXTRACTION_USER_PROMPT.format(
        contract_text=contract_text
    )

    # Add few-shot examples section
    if include_examples:
        examples_section = _build_examples_section()
        # Insert examples before the RESPONSE FORMAT section
        user_prompt = user_prompt.replace(
            "---\n\n## RESPONSE FORMAT",
            examples_section + "---\n\n## RESPONSE FORMAT"
        )

    if contract_type_hint:
        user_prompt = f"CONTRACT TYPE HINT: This appears to be a {contract_type_hint} agreement.\n\n" + user_prompt

    if valid_categories:
        categories_str = ', '.join(valid_categories)
        user_prompt = f"VALID DATABASE CATEGORIES: {categories_str}\nPlease use these category codes when possible.\n\n" + user_prompt

    return {
        'system': CLAUSE_EXTRACTION_SYSTEM_PROMPT,
        'user': user_prompt
    }


def build_chunk_extraction_prompt(
    contract_text: str,
    chunk_index: int,
    total_chunks: int,
    chunk_context: Optional[str] = None,
    contract_type_hint: Optional[str] = None,
    valid_categories: Optional[list] = None,
    include_examples: bool = False  # Disabled: examples reduced clause count from 19→15
) -> dict:
    """
    Build prompt for extracting clauses from a contract chunk.

    This variant adds chunk awareness to help Claude understand it's processing
    a portion of a larger document.

    Args:
        contract_text: The chunk text to extract from
        chunk_index: Index of this chunk (0-based)
        total_chunks: Total number of chunks
        chunk_context: Optional context about what sections this chunk contains
        contract_type_hint: Optional hint about contract type
        valid_categories: Optional list of valid category codes
        include_examples: Whether to include few-shot examples (default True)

    Returns:
        Dict with 'system' and 'user' prompts ready for Claude API
    """
    # Add chunk awareness to system prompt
    chunk_system = CLAUSE_EXTRACTION_SYSTEM_PROMPT + f"""

CHUNK CONTEXT:
You are analyzing chunk {chunk_index + 1} of {total_chunks} from a longer contract.
- Extract ALL clauses found in this chunk
- Some clauses may be partial (text continues in next chunk) - extract what you can see
- Do NOT skip clauses because they seem incomplete
- Include section references for all clauses to enable deduplication across chunks"""

    # Build user prompt with chunk prefix
    chunk_prefix = ""
    if chunk_context:
        chunk_prefix += f"CHUNK SECTIONS: {chunk_context}\n\n"
    if contract_type_hint:
        chunk_prefix += f"CONTRACT TYPE: {contract_type_hint}\n\n"
    if valid_categories:
        chunk_prefix += f"VALID CATEGORIES: {', '.join(valid_categories)}\n\n"

    user_prompt = chunk_prefix + CLAUSE_EXTRACTION_USER_PROMPT.format(
        contract_text=contract_text
    )

    # Add few-shot examples section
    if include_examples:
        examples_section = _build_examples_section()
        # Insert examples before the RESPONSE FORMAT section
        user_prompt = user_prompt.replace(
            "---\n\n## RESPONSE FORMAT",
            examples_section + "---\n\n## RESPONSE FORMAT"
        )

    return {
        'system': chunk_system,
        'user': user_prompt
    }
