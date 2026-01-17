"""
Pass 1: Clause Discovery Prompt

Goal: Extract ALL clauses from the contract without category constraints.
This maximizes recall by not forcing clauses into predefined categories.
"""

from typing import Optional


DISCOVERY_SYSTEM_PROMPT = """You are an expert contract analyst specializing in energy contracts (PPAs, O&M agreements, EPC contracts).

Your task is to identify and extract EVERY distinct clause from the contract. A clause is any contractual provision that:
- Establishes an obligation, right, or condition
- Defines a term or process
- Specifies a requirement, limit, or threshold
- Describes a consequence or remedy

CRITICAL INSTRUCTIONS:
1. Extract EVERY clause you find - do not skip any
2. Do NOT try to categorize clauses yet - just identify them
3. Look for multiple clauses within the same section
4. Include both major provisions and smaller sub-clauses
5. When in doubt, extract it - it's better to over-extract than miss clauses"""


DISCOVERY_USER_PROMPT = """Extract ALL clauses from this energy contract. Do not categorize them yet - just identify every distinct contractual provision.

CONTRACT TEXT:
{contract_text}

---

## WHAT TO EXTRACT

For each clause found, extract:
1. **clause_name**: A descriptive name for the clause (e.g., "Availability Guarantee", "Late Payment Interest")
2. **section_reference**: The section number/title where this clause appears
3. **raw_text**: The exact text of the clause (can be a paragraph or multiple paragraphs)
4. **responsible_party**: Who has the obligation (Owner/Seller, Buyer/Utilities, Both, or null)
5. **beneficiary_party**: Who benefits from this clause (Owner/Seller, Buyer/Utilities, Both, or null)
6. **clause_type**: One of: "obligation", "right", "definition", "condition", "remedy", "limitation", "process"

---

## RESPONSE FORMAT

Return a JSON object with the following structure:

```json
{{
  "discovered_clauses": [
    {{
      "clause_id": "disc_001",
      "clause_name": "Availability Guarantee",
      "section_reference": "Section 4.2",
      "raw_text": "The exact text from the contract...",
      "responsible_party": "Seller",
      "beneficiary_party": "Buyer",
      "clause_type": "obligation",
      "key_terms": ["availability", "95%", "annual"],
      "extraction_confidence": 0.95
    }},
    {{
      "clause_id": "disc_002",
      "clause_name": "Late Payment Interest",
      "section_reference": "Section 6.3",
      "raw_text": "Late payments shall accrue interest at...",
      "responsible_party": "Both",
      "beneficiary_party": "Both",
      "clause_type": "remedy",
      "key_terms": ["interest", "late payment", "prime rate"],
      "extraction_confidence": 0.90
    }}
  ],
  "discovery_summary": {{
    "total_clauses_found": 25,
    "sections_analyzed": ["Section 1", "Section 2", "..."],
    "clause_types_found": {{
      "obligation": 10,
      "right": 5,
      "definition": 3,
      "condition": 3,
      "remedy": 2,
      "limitation": 1,
      "process": 1
    }},
    "extraction_notes": [
      "Found multiple payment-related clauses in Section 6",
      "Section 11 contains many standard boilerplate clauses"
    ]
  }}
}}
```

---

## EXTRACTION GUIDELINES

1. **Be Exhaustive**: Extract every clause, even if it seems minor
2. **Separate Related Clauses**: If a section has multiple distinct provisions, extract each separately
3. **Include Definitions**: Contract definitions that establish key terms are clauses too
4. **Look for Nested Clauses**: Subsections often contain important sub-clauses
5. **Don't Merge**: Keep clauses separate even if they relate to the same topic

## EXAMPLES OF CLAUSE TYPES

- **Obligation**: "Seller shall maintain the facility..."
- **Right**: "Buyer may terminate this agreement if..."
- **Definition**: "'Force Majeure' means any event..."
- **Condition**: "Subject to the satisfaction of the following conditions..."
- **Remedy**: "In the event of default, the non-defaulting party may..."
- **Limitation**: "Liability shall not exceed..."
- **Process**: "Invoices shall be submitted within 10 days..."
"""


def build_discovery_prompt(
    contract_text: str,
    contract_type_hint: Optional[str] = None
) -> dict:
    """
    Build the discovery prompt for Pass 1 extraction.

    Args:
        contract_text: The contract text to analyze
        contract_type_hint: Optional hint about contract type (PPA, O&M, EPC)

    Returns:
        Dict with 'system' and 'user' prompts
    """
    user_prompt = DISCOVERY_USER_PROMPT.format(contract_text=contract_text)

    if contract_type_hint:
        user_prompt = f"CONTRACT TYPE: This appears to be a {contract_type_hint} agreement.\n\n" + user_prompt

    return {
        'system': DISCOVERY_SYSTEM_PROMPT,
        'user': user_prompt
    }


def build_chunk_discovery_prompt(
    contract_text: str,
    chunk_index: int,
    total_chunks: int,
    contract_type_hint: Optional[str] = None
) -> dict:
    """
    Build discovery prompt for a contract chunk.
    """
    chunk_system = DISCOVERY_SYSTEM_PROMPT + f"""

CHUNK CONTEXT:
You are analyzing chunk {chunk_index + 1} of {total_chunks} from a longer contract.
- Extract ALL clauses found in this chunk
- Some clauses may be partial - extract what you can see
- Include section references for deduplication across chunks"""

    user_prompt = DISCOVERY_USER_PROMPT.format(contract_text=contract_text)

    if contract_type_hint:
        user_prompt = f"CONTRACT TYPE: {contract_type_hint}\n\n" + user_prompt

    return {
        'system': chunk_system,
        'user': user_prompt
    }
