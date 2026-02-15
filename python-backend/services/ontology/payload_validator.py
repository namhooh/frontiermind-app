"""
Payload Validator & Normalizer

Validates and normalizes clause normalized_payload dicts against the canonical
ontology schemas. Ensures consistent field names and types across the extraction
pipeline.

Usage:
    from services.ontology.payload_validator import normalize_payload, validate_payload

    # Normalize aliases and types
    normalized = normalize_payload("PRICING", {"tariff": 0.045, "escalation_rate_percent_per_year": 2.0})
    # -> {"base_rate_per_kwh": 0.045, "escalation_rate": 2.0}

    # Validate required fields and types
    result = validate_payload("PRICING", normalized)
    # -> ValidationResult(valid=True, missing_required=[], type_errors=[], warnings=[])
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from services.prompts.clause_examples import (
    CANONICAL_SCHEMAS,
    resolve_aliases,
    get_required_fields,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of payload validation."""
    valid: bool
    missing_required: list = field(default_factory=list)
    type_errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def validate_payload(category: str, payload: dict) -> ValidationResult:
    """
    Validate a normalized_payload against the canonical schema for its category.

    Checks:
    1. Required fields are present and non-null
    2. Field types match schema expectations (where safely checkable)

    Args:
        category: Clause category code (e.g., "AVAILABILITY")
        payload: The normalized_payload dict (should already be alias-resolved)

    Returns:
        ValidationResult with details on any issues
    """
    schema = CANONICAL_SCHEMAS.get(category)
    if not schema:
        return ValidationResult(
            valid=True,
            warnings=[f"No canonical schema for category '{category}' — skipping validation"]
        )

    missing_required = []
    type_errors = []
    warnings = []

    # Build field lookup
    field_map = {f["name"]: f for f in schema["fields"]}

    # Check required fields
    required = get_required_fields(category)
    for req_field in required:
        if req_field not in payload or payload[req_field] is None:
            missing_required.append(req_field)

    # Check types for present fields
    type_checkers = {
        "number": (int, float),
        "string": (str,),
        "boolean": (bool,),
        "list": (list,),
        "object": (dict,),
    }

    for key, value in payload.items():
        if value is None:
            continue
        if key.startswith("_"):
            # Skip internal metadata fields
            continue

        field_def = field_map.get(key)
        if not field_def:
            # Field not in schema — could be extra data from extraction
            continue

        expected_type = field_def.get("type")
        if expected_type and expected_type in type_checkers:
            expected_types = type_checkers[expected_type]
            if not isinstance(value, expected_types):
                type_errors.append(
                    f"Field '{key}': expected {expected_type}, got {type(value).__name__}"
                )

    # Detect unknown fields
    known_fields = set(field_map.keys())
    for key in payload:
        if key.startswith("_"):
            continue
        if key not in known_fields:
            warnings.append(f"Unknown field '{key}' not in canonical schema for {category}")

    valid = len(missing_required) == 0 and len(type_errors) == 0

    return ValidationResult(
        valid=valid,
        missing_required=missing_required,
        type_errors=type_errors,
        warnings=warnings,
    )


def normalize_payload(category: str, payload: dict) -> dict:
    """
    Normalize a clause payload by resolving aliases and coercing types.

    Steps:
    1. Resolve field name aliases to canonical names
    2. Coerce types where safe (e.g., string "95" → float 95.0 for number fields)
    3. Log warnings for unknown keys

    Args:
        category: Clause category code
        payload: The raw normalized_payload dict

    Returns:
        New dict with canonical field names and coerced types
    """
    if not payload:
        return {}

    # Step 1: Resolve aliases
    resolved = resolve_aliases(payload, category)

    # Step 2: Coerce types where safe
    schema = CANONICAL_SCHEMAS.get(category)
    if schema:
        field_map = {f["name"]: f for f in schema["fields"]}

        for key in list(resolved.keys()):
            if key.startswith("_"):
                continue

            value = resolved[key]
            if value is None:
                continue

            field_def = field_map.get(key)
            if not field_def:
                continue

            expected_type = field_def.get("type")

            # Coerce string → number where safe
            if expected_type == "number" and isinstance(value, str):
                try:
                    resolved[key] = float(value)
                except (ValueError, TypeError):
                    pass  # Leave as-is if can't coerce

            # Coerce int → float for number fields
            if expected_type == "number" and isinstance(value, int):
                resolved[key] = float(value)

            # Coerce string → list for list fields (single item)
            if expected_type == "list" and isinstance(value, str):
                resolved[key] = [value]

    return resolved
