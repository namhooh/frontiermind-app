"""
Contract Metadata Extraction Prompt

Goal: Extract contract-level metadata (type, parties, dates, term) from contract text.
This is a lightweight extraction pass focused on high-level contract information.

Output is used to:
1. Auto-populate contract_type_id from lookup table
2. Match counterparty to existing records via fuzzy matching
3. Store extraction metadata for audit and manual review
"""

from typing import Optional, List


METADATA_SYSTEM_PROMPT = """You are an expert contract analyst specializing in energy contracts.

Your task is to extract contract-level metadata from the document. Focus on:
1. Contract type classification
2. Party names (who is the seller/buyer)
3. Key dates (effective date, end date, term)
4. High-level contract parameters

Be precise and extract exact names as they appear in the contract.
Do NOT redact or anonymize party names - we need them for matching to our database."""


METADATA_USER_PROMPT = """Extract the contract-level metadata from this energy contract.

CONTRACT TEXT:
{contract_text}

---

## EXTRACTION REQUIREMENTS

### 1. Contract Type
Classify as one of:
- **PPA** - Power Purchase Agreement (sale/purchase of electricity)
- **O_M** - Operations & Maintenance agreement
- **EPC** - Engineering, Procurement, Construction agreement
- **LEASE** - Land or equipment lease
- **IA** - Interconnection Agreement (utility grid connection)
- **ESA** - Energy Storage Agreement
- **VPPA** - Virtual/Financial PPA (no physical delivery)
- **TOLLING** - Tolling agreement (offtaker provides fuel)
- **OTHER** - If none of the above fit

### 2. Party Names
Extract the exact legal names of:
- **seller_name**: The party selling/providing services (often "Seller", "Owner", "Provider", "Developer")
- **buyer_name**: The party buying/receiving services (often "Buyer", "Offtaker", "Customer", "Utility")

IMPORTANT: Extract the full legal entity name as stated in the contract (e.g., "SolarCo Energy LLC", not just "Seller")

### 3. Dates and Term
- **effective_date**: When the contract becomes effective (format: YYYY-MM-DD or null)
- **end_date**: When the contract terminates (format: YYYY-MM-DD or null)
- **term_years**: Duration in years (integer or null)

### 4. Project Information (if available)
- **project_name**: Name of the energy project
- **facility_location**: Location of the facility
- **capacity_mw**: Facility capacity in MW (numeric or null)

---

## RESPONSE FORMAT

Return a JSON object:

```json
{{
  "contract_metadata": {{
    "contract_type": "PPA",
    "contract_type_confidence": 0.95,
    "seller_name": "SolarCo Energy LLC",
    "buyer_name": "City of Greenville",
    "effective_date": "2024-01-01",
    "end_date": "2044-01-01",
    "term_years": 20,
    "project_name": "Greenville Solar Project",
    "facility_location": "Greenville County, SC",
    "capacity_mw": 50.0
  }},
  "extraction_notes": [
    "Seller is defined in Recitals paragraph A",
    "20-year term with two 5-year extension options"
  ],
  "confidence": 0.92
}}
```

### Confidence Guidelines
- 0.9-1.0: Clear, unambiguous information found
- 0.7-0.89: Information found but some ambiguity
- 0.5-0.69: Inferred from context, not explicitly stated
- Below 0.5: Unable to determine with confidence (use null instead)

---

## IMPORTANT NOTES

1. Extract party names EXACTLY as written (include "LLC", "Inc.", "Corp.", etc.)
2. If multiple dates are mentioned, use the Contract Effective Date (not execution date)
3. For PPAs, the seller is typically the power generator/owner
4. For O&M, the seller is typically the service provider
5. If you cannot determine a field with confidence, use null - do not guess
"""


def build_metadata_extraction_prompt(
    contract_text: str,
    max_chars: int = 15000
) -> dict:
    """
    Build the metadata extraction prompt.

    This is a lightweight extraction focused on contract-level metadata.
    Uses truncated text since metadata is typically in the first sections.

    Args:
        contract_text: The contract text to analyze (will be truncated if too long)
        max_chars: Maximum characters to include (default 15000, ~4000 tokens)

    Returns:
        Dict with 'system' and 'user' prompts
    """
    # Truncate text if too long - metadata is usually in first sections
    # Include a note if truncated
    if len(contract_text) > max_chars:
        truncated_text = contract_text[:max_chars]
        truncated_text += "\n\n[... CONTRACT TEXT TRUNCATED - metadata typically appears in first sections ...]"
    else:
        truncated_text = contract_text

    user_prompt = METADATA_USER_PROMPT.format(contract_text=truncated_text)

    return {
        'system': METADATA_SYSTEM_PROMPT,
        'user': user_prompt
    }


def parse_metadata_response(response_text: str) -> dict:
    """
    Parse the metadata extraction response from Claude.

    Args:
        response_text: Raw response text from Claude API

    Returns:
        Dict with extracted metadata fields

    Raises:
        ValueError: If response cannot be parsed
    """
    import json

    # Extract JSON from response (Claude may wrap it in markdown)
    if "```json" in response_text:
        json_start = response_text.find("```json") + 7
        json_end = response_text.find("```", json_start)
        response_text = response_text[json_start:json_end].strip()
    elif "```" in response_text:
        json_start = response_text.find("```") + 3
        json_end = response_text.find("```", json_start)
        response_text = response_text[json_start:json_end].strip()

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse metadata response as JSON: {e}")

    # Extract and validate metadata
    metadata = data.get("contract_metadata", {})

    # Normalize contract_type to uppercase
    if metadata.get("contract_type"):
        metadata["contract_type"] = metadata["contract_type"].upper().replace(" ", "_")

    # Add extraction notes and overall confidence
    metadata["extraction_notes"] = data.get("extraction_notes", [])
    metadata["overall_confidence"] = data.get("confidence", 0.0)

    return metadata


# Valid contract type codes for validation
VALID_CONTRACT_TYPES = [
    "PPA",
    "O_M",
    "EPC",
    "LEASE",
    "IA",
    "ESA",
    "VPPA",
    "TOLLING",
    "OTHER",
]


def validate_contract_type(contract_type: str) -> Optional[str]:
    """
    Validate and normalize contract type code.

    Args:
        contract_type: Extracted contract type code

    Returns:
        Normalized code if valid, None if invalid
    """
    if not contract_type:
        return None

    normalized = contract_type.upper().replace(" ", "_").replace("-", "_")

    # Handle common aliases
    aliases = {
        "O&M": "O_M",
        "OM": "O_M",
        "OPERATIONS_MAINTENANCE": "O_M",
        "INTERCONNECTION": "IA",
        "FINANCIAL_PPA": "VPPA",
        "STORAGE": "ESA",
    }

    if normalized in aliases:
        normalized = aliases[normalized]

    if normalized in VALID_CONTRACT_TYPES:
        return normalized

    return None
