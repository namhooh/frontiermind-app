"""
Pass 2: Clause Categorization & Normalization Prompt

Goal: Categorize discovered clauses and populate normalized_payload using examples.
This maximizes precision by using gold-standard examples to guide categorization.
"""

from typing import List, Dict, Optional
import json


CATEGORIZATION_SYSTEM_PROMPT = """You are an expert contract analyst specializing in energy contracts.

Your task is to CATEGORIZE and NORMALIZE previously discovered clauses. You will receive:
1. A list of discovered clauses with their raw text
2. Gold-standard examples showing how to categorize and normalize each category

Use the examples as templates for:
- Assigning the correct category
- Extracting the right normalized_payload fields
- Determining confidence scores"""


CATEGORIZATION_USER_PROMPT_TEMPLATE = """Categorize and normalize the following discovered clauses.

## DISCOVERED CLAUSES TO CATEGORIZE

{discovered_clauses_json}

---

## CATEGORY DEFINITIONS WITH EXAMPLES

{category_examples}

---

## RESPONSE FORMAT

For each discovered clause, return a categorized version:

```json
{{
  "categorized_clauses": [
    {{
      "original_clause_id": "disc_001",
      "clause_id": "clause_001",
      "clause_name": "Availability Guarantee",
      "category": "AVAILABILITY",
      "category_code": "AVAILABILITY",
      "category_confidence": 0.95,
      "section_reference": "Section 4.2",
      "raw_text": "Original text...",
      "normalized_payload": {{
        "threshold_percent": 95.0,
        "measurement_period": "annual",
        "calculation_method": "...",
        "excused_events": ["force_majeure", "grid_curtailment"]
      }},
      "responsible_party": "Seller",
      "beneficiary_party": "Buyer",
      "extraction_confidence": 0.92,
      "notes": "Clear availability guarantee with 95% threshold"
    }},
    {{
      "original_clause_id": "disc_015",
      "clause_id": "clause_002",
      "clause_name": "Quarterly Business Review",
      "category": "UNIDENTIFIED",
      "category_code": null,
      "category_confidence": 0.40,
      "suggested_category": "COMPLIANCE",
      "section_reference": "Section 15.3",
      "raw_text": "The parties shall conduct quarterly reviews...",
      "normalized_payload": {{
        "clause_summary": "Quarterly business review requirement",
        "key_terms": {{"frequency": "quarterly", "participants": ["Owner", "Utilities"]}},
        "ai_notes": "Administrative provision, closest match is COMPLIANCE"
      }},
      "responsible_party": "Both",
      "beneficiary_party": "Both",
      "extraction_confidence": 0.85,
      "notes": "Could not categorize with high confidence"
    }}
  ],
  "categorization_summary": {{
    "total_clauses_categorized": 25,
    "clauses_by_category": {{
      "CONDITIONS_PRECEDENT": 2,
      "AVAILABILITY": 1,
      "PERFORMANCE_GUARANTEE": 1,
      "LIQUIDATED_DAMAGES": 3,
      "PRICING": 2,
      "PAYMENT_TERMS": 2,
      "DEFAULT": 2,
      "FORCE_MAJEURE": 1,
      "TERMINATION": 2,
      "MAINTENANCE": 1,
      "COMPLIANCE": 2,
      "SECURITY_PACKAGE": 1,
      "GENERAL": 3,
      "UNIDENTIFIED": 2
    }},
    "average_category_confidence": 0.87,
    "low_confidence_clauses": ["disc_015", "disc_022"]
  }}
}}
```

---

## CATEGORIZATION RULES

1. **Match by Content**: Assign category based on clause content, not section title
2. **Use Examples**: Match the normalized_payload structure to the examples provided
3. **Confidence Threshold**: If confidence < 0.6, mark as UNIDENTIFIED with suggested_category
4. **Extract Values**: Pull specific numeric values, dates, percentages into normalized_payload
5. **Multiple Matches**: If a clause could fit multiple categories, choose the most specific one

## CATEGORY CODES
- CONDITIONS_PRECEDENT
- AVAILABILITY
- PERFORMANCE_GUARANTEE
- LIQUIDATED_DAMAGES
- PRICING
- PAYMENT_TERMS
- DEFAULT
- FORCE_MAJEURE
- TERMINATION
- MAINTENANCE
- COMPLIANCE
- SECURITY_PACKAGE
- GENERAL
- UNIDENTIFIED (for clauses that don't fit well)
"""


def _build_category_examples_section() -> str:
    """Build compact examples section from clause_examples.py"""
    from .clause_examples import CLAUSE_EXAMPLES

    examples_text = ""

    # Only include 6 highest-priority categories to keep prompt manageable
    priority_categories = [
        "LIQUIDATED_DAMAGES",
        "AVAILABILITY",
        "PERFORMANCE_GUARANTEE",
        "PRICING",
        "DEFAULT",
        "TERMINATION"
    ]

    for cat_code in priority_categories:
        example_data = CLAUSE_EXAMPLES.get(cat_code)
        if not example_data:
            continue

        raw_text = example_data["example_raw_text"].strip()[:200]  # Shorter
        extraction = example_data["example_extraction"]
        payload = extraction["normalized_payload"]

        # Get only first 3 most important payload fields (compact)
        payload_preview = {k: v for k, v in list(payload.items())[:3] if v is not None}

        examples_text += f"""
### {cat_code}
Raw: "{raw_text}..."
Extracted: clause_name="{extraction['clause_name']}", key_payload={payload_preview}

"""

    # Add brief note about other categories
    examples_text += """
### OTHER CATEGORIES (no examples, use similar patterns):
- CONDITIONS_PRECEDENT: conditions_list, satisfaction_deadline_days
- PAYMENT_TERMS: billing_frequency, payment_due_days
- FORCE_MAJEURE: defined_events, max_duration_days
- MAINTENANCE: response_time_hours, scheduled_outage_notice_days
- COMPLIANCE: required_permits, reporting_obligations
- SECURITY_PACKAGE: security_type, security_amount
- GENERAL: governing_law, dispute_resolution_method
"""

    return examples_text


def build_categorization_prompt(
    discovered_clauses: List[Dict],
    include_examples: bool = True
) -> dict:
    """
    Build the categorization prompt for Pass 2.

    Args:
        discovered_clauses: List of clauses from Pass 1 discovery
        include_examples: Whether to include gold-standard examples

    Returns:
        Dict with 'system' and 'user' prompts
    """
    # Format discovered clauses as JSON
    clauses_json = json.dumps(discovered_clauses, indent=2)

    # Build examples section
    category_examples = ""
    if include_examples:
        category_examples = _build_category_examples_section()
    else:
        category_examples = "No examples provided. Use your knowledge to categorize clauses."

    user_prompt = CATEGORIZATION_USER_PROMPT_TEMPLATE.format(
        discovered_clauses_json=clauses_json,
        category_examples=category_examples
    )

    return {
        'system': CATEGORIZATION_SYSTEM_PROMPT,
        'user': user_prompt
    }


def build_batch_categorization_prompt(
    discovered_clauses: List[Dict],
    batch_start: int,
    batch_size: int,
    include_examples: bool = True
) -> dict:
    """
    Build categorization prompt for a batch of clauses.

    Use this when there are too many clauses to process in one API call.
    """
    batch_clauses = discovered_clauses[batch_start:batch_start + batch_size]

    batch_system = CATEGORIZATION_SYSTEM_PROMPT + f"""

BATCH CONTEXT:
You are categorizing clauses {batch_start + 1} to {batch_start + len(batch_clauses)} of {len(discovered_clauses)} total discovered clauses."""

    clauses_json = json.dumps(batch_clauses, indent=2)

    category_examples = ""
    if include_examples:
        category_examples = _build_category_examples_section()
    else:
        category_examples = "No examples provided."

    user_prompt = CATEGORIZATION_USER_PROMPT_TEMPLATE.format(
        discovered_clauses_json=clauses_json,
        category_examples=category_examples
    )

    return {
        'system': batch_system,
        'user': user_prompt
    }
