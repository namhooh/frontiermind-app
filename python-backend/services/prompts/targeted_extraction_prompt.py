"""
Targeted Extraction Prompt for Missing Categories

Goal: Find specific clause types that main extraction commonly misses.
Used as a post-processing step after main extraction.
"""

from typing import List, Dict, Optional


# =============================================================================
# TARGETED CATEGORIES - All 13 clause categories with search terms
# =============================================================================
# Each category has search terms to find commonly-missed clauses and section hints
# for where to look. Used for targeted extraction post-processing.

TARGETED_CATEGORIES = {
    # -------------------------------------------------------------------------
    # FINANCIAL & SECURITY CATEGORIES (high priority - often missed)
    # -------------------------------------------------------------------------
    "SECURITY_PACKAGE": {
        "search_terms": [
            "letter of credit", "LC", "L/C",
            "surety bond", "performance bond",
            "parent guarantee", "parent company guarantee",
            "performance security", "credit support",
            "collateral", "security deposit",
            "guaranty", "guarantee agreement",
            "creditworthiness", "credit requirements"
        ],
        "section_hints": [
            "Security", "Credit Support", "Financial Assurances",
            "Performance Assurance", "Collateral", "Guarantees"
        ],
        "description": "Financial security instruments protecting against counterparty default"
    },
    "LIQUIDATED_DAMAGES": {
        "search_terms": [
            "liquidated damages", "LD", "L.D.", "LDs",
            "delay damages", "delay LD",
            "availability shortfall", "performance shortfall",
            "shortfall payment", "shortfall damages",
            "penalty", "per diem", "per day",
            "per percentage point", "per MWh",
            "damages cap", "aggregate cap"
        ],
        "section_hints": [
            "Liquidated Damages", "Damages", "Remedies",
            "Performance", "Delay", "Shortfall", "Penalties"
        ],
        "description": "Monetary penalties for contract breaches including delay, availability, and performance shortfalls"
    },
    "PRICING": {
        "search_terms": [
            "price", "rate", "$/kWh", "$/MWh", "cents/kWh",
            "contract price", "energy price", "PPA price",
            "escalation", "escalator", "indexation",
            "CPI", "consumer price index", "inflation adjustment",
            "price adjustment", "annual escalation",
            "fixed price", "variable price", "tariff"
        ],
        "section_hints": [
            "Pricing", "Price", "Payment", "Compensation",
            "Energy Price", "Contract Price", "Rates"
        ],
        "description": "Energy pricing structure including base rates, escalation mechanisms, and adjustments"
    },
    "PAYMENT_TERMS": {
        "search_terms": [
            "payment", "invoice", "billing", "bill",
            "take or pay", "take-or-pay", "minimum purchase",
            "due date", "payment due", "net 30", "net 45",
            "late payment", "interest", "late fee",
            "billing cycle", "monthly invoice",
            "payment schedule", "payment terms"
        ],
        "section_hints": [
            "Payment", "Billing", "Invoice", "Invoicing",
            "Payment Terms", "Accounts"
        ],
        "description": "Billing cycles, payment timing, late fees, and minimum purchase obligations"
    },

    # -------------------------------------------------------------------------
    # PERFORMANCE CATEGORIES
    # -------------------------------------------------------------------------
    "PERFORMANCE_GUARANTEE": {
        "search_terms": [
            "performance ratio", "PR guarantee", "PR",
            "capacity factor", "CF guarantee", "CF",
            "degradation rate", "degradation guarantee",
            "output guarantee", "guaranteed output",
            "minimum generation", "guaranteed generation",
            "energy production guarantee", "annual output"
        ],
        "section_hints": [
            "Performance", "Output Guarantee", "Generation",
            "Performance Guarantee", "Capacity", "Production"
        ],
        "description": "Guarantees related to facility performance metrics like PR, CF, and degradation"
    },
    "AVAILABILITY": {
        "search_terms": [
            "availability", "availability guarantee",
            "uptime", "system availability",
            "forced outage", "unforced outage",
            "unavailability", "availability shortfall",
            "availability rate", "annual availability",
            "monthly availability", "availability calculation",
            "equivalent availability", "EAF"
        ],
        "section_hints": [
            "Availability", "Performance", "Operations",
            "Outages", "System Performance"
        ],
        "description": "System availability guarantees, uptime requirements, and outage provisions"
    },
    "MAINTENANCE": {
        "search_terms": [
            "maintenance", "O&M", "operation and maintenance",
            "operations and maintenance",
            "service level", "SLA", "service level agreement",
            "scheduled outage", "planned outage",
            "scheduled maintenance", "preventive maintenance",
            "repair", "repairs", "prudent utility practice",
            "good utility practice", "industry standard"
        ],
        "section_hints": [
            "Maintenance", "Operations", "O&M",
            "Service", "Operating", "Outages"
        ],
        "description": "O&M obligations, service levels, scheduled maintenance, and repair requirements"
    },

    # -------------------------------------------------------------------------
    # CONTRACT LIFECYCLE CATEGORIES
    # -------------------------------------------------------------------------
    "CONDITIONS_PRECEDENT": {
        "search_terms": [
            "conditions precedent", "CP", "CPs",
            "condition to", "conditions to closing",
            "conditions to effectiveness", "effectiveness",
            "closing conditions", "closing",
            "prior to", "prerequisite", "precondition",
            "subject to satisfaction", "satisfaction of conditions"
        ],
        "section_hints": [
            "Conditions Precedent", "Effectiveness", "Closing",
            "Conditions", "Prerequisites"
        ],
        "description": "Requirements that must be satisfied before contract becomes effective"
    },
    "DEFAULT": {
        "search_terms": [
            "default", "event of default", "events of default",
            "breach", "material breach",
            "cure", "cure period", "cure rights",
            "remedy", "remedies", "reimbursement",
            "termination for default", "termination for cause",
            "cross default", "cross-default"
        ],
        "section_hints": [
            "Default", "Events of Default", "Breach",
            "Remedies", "Cure", "Termination"
        ],
        "description": "Events of default, cure periods, and available remedies"
    },
    "TERMINATION": {
        "search_terms": [
            "termination", "terminate", "term",
            "expiration", "expire", "initial term",
            "early termination", "termination for convenience",
            "renewal", "extension", "extend",
            "buyout", "purchase option", "buy-out",
            "fair market value", "FMV", "termination payment"
        ],
        "section_hints": [
            "Term", "Termination", "Extension",
            "Expiration", "Renewal", "Purchase Option"
        ],
        "description": "Contract term, early termination rights, renewal options, and buyout provisions"
    },
    "FORCE_MAJEURE": {
        "search_terms": [
            "force majeure", "FM", "FM event",
            "act of god", "acts of god",
            "unforeseeable", "beyond control",
            "excused event", "excused performance",
            "extraordinary event", "natural disaster",
            "epidemic", "pandemic", "war", "terrorism"
        ],
        "section_hints": [
            "Force Majeure", "Excused Events",
            "Excused Performance", "Unforeseen Events"
        ],
        "description": "Events beyond party control that excuse performance obligations"
    },

    # -------------------------------------------------------------------------
    # REGULATORY & GENERAL CATEGORIES
    # -------------------------------------------------------------------------
    "COMPLIANCE": {
        "search_terms": [
            "compliance", "comply", "compliant",
            "regulatory", "regulation", "regulations",
            "permit", "permits", "license", "licenses",
            "environmental", "environmental compliance",
            "law", "laws", "applicable law",
            "approval", "approvals", "reporting",
            "governmental", "government approval"
        ],
        "section_hints": [
            "Compliance", "Regulatory", "Environmental",
            "Permits", "Licenses", "Approvals", "Laws"
        ],
        "description": "Regulatory requirements, permits, environmental compliance, and reporting obligations"
    },
    "GENERAL": {
        "search_terms": [
            "governing law", "choice of law",
            "dispute", "disputes", "dispute resolution",
            "arbitration", "mediation", "litigation",
            "notice", "notices", "notification",
            "assignment", "assign", "assignable",
            "amendment", "amend", "modify",
            "waiver", "waive", "confidential", "confidentiality",
            "jurisdiction", "venue", "forum"
        ],
        "section_hints": [
            "General", "Miscellaneous", "Governing Law",
            "Disputes", "Notices", "Assignment", "Boilerplate"
        ],
        "description": "Standard contract terms including governing law, disputes, notices, and assignment"
    }
}

# Priority categories for targeted extraction (run these first)
PRIORITY_TARGETED_CATEGORIES = [
    "SECURITY_PACKAGE",       # Often in exhibits, commonly missed
    "PERFORMANCE_GUARANTEE",  # Complex calculations, often under-extracted
    "LIQUIDATED_DAMAGES",     # Multiple LD types (delay, performance, availability)
    "CONDITIONS_PRECEDENT",   # Often at contract start, may be missed
    "DEFAULT",                # Multiple default events, commonly missed
]


TARGETED_EXTRACTION_SYSTEM_PROMPT = """You are an expert contract analyst specializing in energy contracts.

Your task is to find SPECIFIC clause types that may have been missed in a prior extraction.
Focus ONLY on the categories specified - do not extract other clause types.

Be thorough - these clauses are often embedded in longer sections or have non-standard naming."""


TARGETED_EXTRACTION_USER_PROMPT_TEMPLATE = """Search this contract for {category_name} clauses.

## CATEGORY: {category_name}
{category_description}

## SEARCH TERMS TO LOOK FOR
{search_terms}

## SECTIONS TO CHECK
{section_hints}

---

## CONTRACT TEXT
{contract_text}

---

## RESPONSE FORMAT

If you find any {category_name} clauses, return them in this format:

```json
{{
  "found_clauses": [
    {{
      "clause_id": "targeted_001",
      "clause_name": "Performance Security Letter of Credit",
      "category": "{category_code}",
      "category_confidence": 0.90,
      "section_reference": "Section 8.3",
      "raw_text": "Seller shall provide and maintain a Letter of Credit in the amount of...",
      "normalized_payload": {{
        "security_type": "letter_of_credit",
        "security_amount": 500000,
        "amount_unit": "USD",
        "issuer_requirements": "investment grade bank",
        "renewal_terms": "annual renewal required",
        "release_conditions": ["COD achieved", "performance test passed"]
      }},
      "responsible_party": "Seller",
      "beneficiary_party": "Buyer",
      "extraction_confidence": 0.88,
      "notes": "LC required for performance security"
    }}
  ],
  "search_summary": {{
    "sections_searched": ["Section 8", "Section 12", "Exhibit C"],
    "terms_found": ["letter of credit", "performance security"],
    "terms_not_found": ["surety bond", "parent guarantee"]
  }}
}}
```

If NO {category_name} clauses are found, return:
```json
{{
  "found_clauses": [],
  "search_summary": {{
    "sections_searched": ["..."],
    "terms_found": [],
    "terms_not_found": ["all searched terms"],
    "notes": "No {category_name} clauses found in this contract"
  }}
}}
```

---

## EXTRACTION GUIDELINES

1. **Be Thorough**: Check all sections, including exhibits and schedules
2. **Look for Variations**: Security clauses may use different terminology
3. **Extract Full Context**: Include the complete clause text, not just the trigger sentence
4. **Note Amounts**: Always extract specific dollar amounts, percentages, or formulas
5. **Identify Parties**: Note who provides security and who benefits
"""


def build_targeted_extraction_prompt(
    contract_text: str,
    target_category: str,
    existing_clauses: Optional[List[Dict]] = None
) -> dict:
    """
    Build a targeted extraction prompt for a specific missing category.

    Args:
        contract_text: The contract text to search
        target_category: The category code to search for (e.g., "SECURITY_PACKAGE")
        existing_clauses: Optional list of already-extracted clauses to avoid duplicates

    Returns:
        Dict with 'system' and 'user' prompts
    """
    category_config = TARGETED_CATEGORIES.get(target_category)
    if not category_config:
        raise ValueError(f"Unknown target category: {target_category}")

    search_terms = "\n".join(f"- {term}" for term in category_config["search_terms"])
    section_hints = "\n".join(f"- {hint}" for hint in category_config["section_hints"])

    system_prompt = TARGETED_EXTRACTION_SYSTEM_PROMPT

    # Add context about existing clauses if provided
    if existing_clauses:
        existing_refs = [c.get("section_reference", "") for c in existing_clauses]
        system_prompt += f"\n\nNOTE: The following sections have already been extracted: {', '.join(existing_refs)}. Focus on sections NOT in this list."

    user_prompt = TARGETED_EXTRACTION_USER_PROMPT_TEMPLATE.format(
        category_name=target_category.replace("_", " ").title(),
        category_code=target_category,
        category_description=category_config["description"],
        search_terms=search_terms,
        section_hints=section_hints,
        contract_text=contract_text
    )

    return {
        'system': system_prompt,
        'user': user_prompt
    }


def get_missing_categories(extracted_categories: List[str]) -> List[str]:
    """
    Determine which categories should have targeted extraction.

    Args:
        extracted_categories: List of category codes already extracted

    Returns:
        List of category codes to run targeted extraction for
    """
    missing = []
    for category in TARGETED_CATEGORIES.keys():
        if category not in extracted_categories:
            missing.append(category)
    return missing
