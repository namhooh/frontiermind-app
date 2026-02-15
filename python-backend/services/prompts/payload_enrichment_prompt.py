"""
Payload Enrichment Prompt

Goal: Use gold-standard examples to improve normalized_payload quality.
Takes clauses with basic payloads and enriches them with complete field extraction.
"""

from typing import List, Dict, Optional
import json
from .clause_examples import CLAUSE_EXAMPLES, get_required_fields, format_schema_for_prompt


ENRICHMENT_SYSTEM_PROMPT = """You are an expert contract analyst specializing in extracting structured data from energy contract clauses.

Your task is to ENRICH the normalized_payload of previously extracted clauses. You will receive:
1. A clause with basic extracted data
2. An example showing the IDEAL payload structure for that category

Use the example as a template to extract ALL relevant fields from the raw_text.
Do NOT change the category assignment - only improve the normalized_payload."""


ENRICHMENT_USER_PROMPT_TEMPLATE = """Enrich the normalized_payload for this clause using the example as a guide.

## CLAUSE TO ENRICH
```json
{clause_json}
```

---

## EXAMPLE FOR {category} CATEGORY

**Example Raw Text:**
{example_raw_text}

**Example Extraction:**
```json
{example_extraction}
```

**Expected Payload Fields:**
{expected_fields}

---

## INSTRUCTIONS

1. Extract ALL fields shown in the example that are present in the clause's raw_text
2. Use the same field names and value formats as the example
3. If a field is not applicable or not mentioned, set it to null
4. Add any additional relevant fields you discover
5. Preserve the original clause_id, clause_name, and other metadata

## RESPONSE FORMAT

Return the enriched clause:
```json
{{
  "clause_id": "{clause_id}",
  "clause_name": "{clause_name}",
  "category": "{category}",
  "category_confidence": {category_confidence},
  "section_reference": "{section_reference}",
  "raw_text": "...",
  "normalized_payload": {{
    // ENRICHED PAYLOAD - include all relevant fields
  }},
  "responsible_party": "...",
  "beneficiary_party": "...",
  "extraction_confidence": 0.95,
  "enrichment_applied": true,
  "enrichment_notes": "Added X, Y, Z fields from raw text"
}}
```
"""


def _get_expected_fields(category: str) -> str:
    """Get the expected payload fields for a category from canonical schema."""
    # Use canonical schema for authoritative field list with role annotations
    schema_text = format_schema_for_prompt(category)
    if schema_text:
        required = get_required_fields(category)
        if required:
            schema_text += f"\n\nREQUIRED fields: {', '.join(required)}"
        return schema_text

    # Fallback to example if no schema
    example = CLAUSE_EXAMPLES.get(category)
    if not example:
        return "No example available - extract all relevant fields"

    payload = example.get("example_extraction", {}).get("normalized_payload", {})
    fields = []
    for key, value in payload.items():
        value_type = type(value).__name__
        if isinstance(value, list):
            value_type = "list"
        elif isinstance(value, dict):
            value_type = "object"
        elif isinstance(value, (int, float)):
            value_type = "number"
        elif isinstance(value, str):
            value_type = "string"
        fields.append(f"- {key}: {value_type}")

    return "\n".join(fields) if fields else "Extract all relevant fields"


def build_enrichment_prompt(clause: Dict) -> Optional[dict]:
    """
    Build an enrichment prompt for a single clause.

    Args:
        clause: The extracted clause to enrich

    Returns:
        Dict with 'system' and 'user' prompts, or None if no example exists
    """
    category = clause.get("category", "")

    # Skip categories without examples or UNIDENTIFIED clauses
    if category in ["UNIDENTIFIED", "GENERAL"] or category not in CLAUSE_EXAMPLES:
        return None

    example = CLAUSE_EXAMPLES[category]
    example_extraction = example.get("example_extraction", {})

    user_prompt = ENRICHMENT_USER_PROMPT_TEMPLATE.format(
        clause_json=json.dumps(clause, indent=2),
        category=category,
        example_raw_text=example.get("example_raw_text", "")[:500],  # Truncate for token efficiency
        example_extraction=json.dumps(example_extraction, indent=2),
        expected_fields=_get_expected_fields(category),
        clause_id=clause.get("clause_id", ""),
        clause_name=clause.get("clause_name", ""),
        category_confidence=clause.get("category_confidence", 0.8),
        section_reference=clause.get("section_reference", "")
    )

    return {
        'system': ENRICHMENT_SYSTEM_PROMPT,
        'user': user_prompt
    }


def build_batch_enrichment_prompt(clauses: List[Dict]) -> dict:
    """
    Build a batch enrichment prompt for multiple clauses at once.
    More efficient than individual calls for many clauses.

    Args:
        clauses: List of clauses to enrich

    Returns:
        Dict with 'system' and 'user' prompts
    """
    # Group clauses by category
    clauses_by_category = {}
    for clause in clauses:
        category = clause.get("category", "UNIDENTIFIED")
        if category in ["UNIDENTIFIED", "GENERAL"]:
            continue
        if category not in clauses_by_category:
            clauses_by_category[category] = []
        clauses_by_category[category].append(clause)

    # Build examples section
    examples_section = ""
    for category in clauses_by_category.keys():
        if category in CLAUSE_EXAMPLES:
            example = CLAUSE_EXAMPLES[category]
            payload = example.get("example_extraction", {}).get("normalized_payload", {})
            # Only show first 3 fields for brevity
            payload_preview = {k: v for k, v in list(payload.items())[:3]}
            examples_section += f"""
### {category}
Expected fields: {list(payload.keys())}
Example: {json.dumps(payload_preview)}
"""

    user_prompt = f"""Enrich the normalized_payload for each of these clauses.

## CLAUSES TO ENRICH
```json
{json.dumps(clauses, indent=2)}
```

---

## CATEGORY EXAMPLES
{examples_section}

---

## RESPONSE FORMAT

Return ALL clauses with enriched payloads:
```json
{{
  "enriched_clauses": [
    {{
      "clause_id": "clause_001",
      "normalized_payload": {{
        // ENRICHED - all fields extracted
      }},
      "enrichment_applied": true,
      "enrichment_notes": "Added rate_unit, cap_amount fields"
    }},
    // ... all clauses
  ]
}}
```

## INSTRUCTIONS
1. For each clause, extract ALL fields shown in the category example
2. Preserve clause_id exactly - do not change it
3. Only return the enriched normalized_payload and metadata
4. Set fields to null if not found in raw_text
"""

    return {
        'system': ENRICHMENT_SYSTEM_PROMPT,
        'user': user_prompt
    }


def get_enrichment_candidates(clauses: List[Dict]) -> List[Dict]:
    """
    Filter clauses that are candidates for enrichment.

    Args:
        clauses: List of extracted clauses

    Returns:
        List of clauses that can be enriched (have examples and are not GENERAL/UNIDENTIFIED)
    """
    candidates = []
    for clause in clauses:
        category = clause.get("category", "")
        # Skip if no example or generic category
        if category in ["UNIDENTIFIED", "GENERAL"]:
            continue
        if category not in CLAUSE_EXAMPLES:
            continue
        # Skip if already well-populated
        payload = clause.get("normalized_payload", {})
        if len(payload) >= 5:  # Already has many fields
            continue
        candidates.append(clause)
    return candidates
