"""
Validation Pass Prompt

Goal: Review extracted clauses against original contract text to identify
clauses that may have been missed in the initial extraction passes.

This is a post-processing step that runs after main extraction and targeted
extraction to maximize recall.
"""

from typing import List, Dict, Optional


VALIDATION_SYSTEM_PROMPT = """You are a contract review specialist with expertise in energy contracts (PPAs, O&M agreements).

Your task is to find clauses that may have been MISSED in a prior extraction pass.

IMPORTANT: Focus on finding ADDITIONAL clauses not already in the extracted list.
Do NOT re-extract clauses that are already captured.

Common reasons clauses get missed:
1. Located in exhibits, schedules, or appendices
2. Nested within other sections as sub-clauses
3. Use non-standard terminology or naming
4. Part of definition sections with material terms
5. Buried in boilerplate sections at the end
6. Split across multiple sections/pages"""


VALIDATION_USER_PROMPT_TEMPLATE = """Review this contract for MISSED clauses that were not captured in the initial extraction.

## ALREADY EXTRACTED CLAUSES
The following clauses have already been extracted - DO NOT re-extract these:

{extracted_clauses_summary}

---

## CONTRACT TEXT
{contract_text}

---

## TASK

Carefully scan the contract for ANY material clauses NOT already extracted. Look especially for:

1. **Exhibits/Schedules/Appendices**: Often contain pricing details, security requirements, performance tests
2. **Nested Sub-Clauses**: Material terms buried within larger sections (e.g., "4.2(a)(iii)")
3. **Definition Sections**: Defined terms with material obligations ("Guaranteed Capacity" means...)
4. **Financial Terms**: Pricing escalators, true-up mechanisms, settlement calculations
5. **Security Provisions**: LC requirements, parent guarantees, collateral often in separate exhibits
6. **Conditions Precedent**: CP lists often at contract start or in conditions section
7. **Default Events**: Multiple default triggers often listed in subsections
8. **Boilerplate with Material Terms**: Notice provisions, assignment restrictions with specific conditions

## RESPONSE FORMAT

```json
{{
  "missed_clauses": [
    {{
      "clause_id": "validation_001",
      "clause_name": "Name describing the clause",
      "category": "CATEGORY_CODE",
      "category_confidence": 0.85,
      "section_reference": "Exhibit B, Section 2.1",
      "raw_text": "Complete clause text...",
      "normalized_payload": {{
        "key_field": "value",
        "another_field": "value"
      }},
      "responsible_party": "Seller/Buyer/Both",
      "beneficiary_party": "Buyer/Seller/Both",
      "extraction_confidence": 0.80,
      "why_missed": "Brief explanation (e.g., 'In exhibit', 'Nested sub-clause', 'Non-standard terminology')"
    }}
  ],
  "validation_summary": {{
    "sections_reviewed": ["List of sections checked"],
    "exhibits_reviewed": ["List of exhibits checked"],
    "additional_clauses_found": 3,
    "confidence_complete": 0.92,
    "notes": "Any observations about contract completeness"
  }}
}}
```

If NO additional clauses are found, return:
```json
{{
  "missed_clauses": [],
  "validation_summary": {{
    "sections_reviewed": ["..."],
    "exhibits_reviewed": ["..."],
    "additional_clauses_found": 0,
    "confidence_complete": 0.95,
    "notes": "Initial extraction appears comprehensive"
  }}
}}
```

---

## CATEGORY CODES

Use these category codes for categorization:
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
- UNIDENTIFIED (if no category fits)
"""


def build_validation_prompt(
    contract_text: str,
    extracted_clauses: List[Dict],
    max_summary_clauses: int = 50
) -> dict:
    """
    Build validation prompt to find missed clauses.

    Args:
        contract_text: Full contract text to review
        extracted_clauses: List of already-extracted clause dicts
        max_summary_clauses: Maximum clauses to include in summary (to save tokens)

    Returns:
        Dict with 'system' and 'user' prompts
    """
    # Create summary of extracted clauses for reference
    summary_lines = []
    for i, clause in enumerate(extracted_clauses[:max_summary_clauses]):
        section = clause.get("section_reference") or clause.get("section_ref") or "N/A"
        name = clause.get("clause_name") or clause.get("name") or "Unnamed"
        category = clause.get("category") or clause.get("clause_category") or "UNIDENTIFIED"
        summary_lines.append(f"{i+1}. [{section}] {name} ({category})")

    if len(extracted_clauses) > max_summary_clauses:
        summary_lines.append(f"... and {len(extracted_clauses) - max_summary_clauses} more clauses")

    extracted_summary = "\n".join(summary_lines) if summary_lines else "No clauses extracted yet."

    user_prompt = VALIDATION_USER_PROMPT_TEMPLATE.format(
        extracted_clauses_summary=extracted_summary,
        contract_text=contract_text
    )

    return {
        'system': VALIDATION_SYSTEM_PROMPT,
        'user': user_prompt
    }


def parse_validation_response(response_text: str) -> tuple[List[Dict], Dict]:
    """
    Parse validation response JSON.

    Args:
        response_text: Raw response text from Claude

    Returns:
        Tuple of (list of missed clause dicts, validation summary dict)
    """
    import json

    # Extract JSON from response
    if "```json" in response_text:
        json_start = response_text.find("```json") + 7
        json_end = response_text.find("```", json_start)
        if json_end == -1:
            json_end = len(response_text)
        response_text = response_text[json_start:json_end].strip()
    elif "```" in response_text:
        json_start = response_text.find("```") + 3
        json_end = response_text.find("```", json_start)
        if json_end == -1:
            json_end = len(response_text)
        response_text = response_text[json_start:json_end].strip()

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # Try to repair truncated JSON
        last_valid = response_text.rfind('},')
        if last_valid > 0:
            repaired = response_text[:last_valid + 1] + '],"validation_summary":{}}'
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                return [], {"error": "Failed to parse validation response"}
        else:
            return [], {"error": "Failed to parse validation response"}

    missed_clauses = data.get("missed_clauses", [])
    validation_summary = data.get("validation_summary", {})

    return missed_clauses, validation_summary
