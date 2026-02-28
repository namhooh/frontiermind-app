"""
Ingestion fidelity metrics: completeness, accuracy, resolver diagnostics.

Measures:
- Completeness: unique {CONTRACT_LINE_UNIQUE_ID, BILL_DATE} records ingested
- Accuracy: transformed canonical values match source values
- Unresolved reason distribution from BillingResolver
- Semantic classification accuracy (energy category assignment)
"""

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CompletenessResult:
    """Completeness of ingested records vs source."""
    expected_count: int = 0
    actual_count: int = 0
    matched_count: int = 0
    completeness: float = 0.0
    missing_keys: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class AccuracyResult:
    """Value accuracy of transformed records."""
    total_comparisons: int = 0
    accurate: int = 0
    inaccurate: int = 0
    accuracy: float = 0.0
    errors: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ResolverDiagnostics:
    """Distribution of unresolved FK reasons."""
    total_records: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    resolution_rate: float = 0.0
    reason_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class ClassificationResult:
    """Semantic classification accuracy for energy categories."""
    total_records: int = 0
    correct: int = 0
    incorrect: int = 0
    accuracy: float = 0.0
    misclassified: List[Dict[str, Any]] = field(default_factory=list)


def compute_completeness(
    source_records: List[Dict[str, Any]],
    target_records: List[Dict[str, Any]],
    source_key_fields: Tuple[str, ...] = ("CONTRACT_LINE_UNIQUE_ID", "BILL_DATE"),
    target_key_fields: Tuple[str, ...] = ("external_line_id", "period_end"),
    max_missing: int = 50,
) -> CompletenessResult:
    """Compute ingestion completeness.

    Denominator: unique key tuples from filtered source records.
    Numerator: key tuples present in target (FM) records.
    """
    expected = set()
    for r in source_records:
        key = tuple(str(r.get(f, "")).strip() for f in source_key_fields)
        if all(k for k in key):
            expected.add(key)

    actual = set()
    for r in target_records:
        key = tuple(str(r.get(f, "")).strip() for f in target_key_fields)
        if all(k for k in key):
            actual.add(key)

    matched = expected & actual
    missing = expected - actual

    result = CompletenessResult(
        expected_count=len(expected),
        actual_count=len(actual),
        matched_count=len(matched),
        completeness=len(matched) / len(expected) if expected else 1.0,
    )

    if missing:
        result.missing_keys = sorted(list(missing))[:max_missing]

    return result


def compute_value_accuracy(
    source_records: List[Dict[str, Any]],
    canonical_records: List[Dict[str, Any]],
    field_pairs: List[Tuple[str, str]],
    numeric_tolerance: float = 0.01,
) -> AccuracyResult:
    """Compare source values against transformed canonical values.

    Args:
        source_records: Raw SAGE records.
        canonical_records: Output of CBEBillingAdapter.transform().
        field_pairs: List of (source_field, canonical_field) pairs to compare.
        numeric_tolerance: Absolute tolerance for numeric comparison.
    """
    result = AccuracyResult()

    for source, canonical in zip(source_records, canonical_records):
        for source_field, canonical_field in field_pairs:
            source_val = source.get(source_field)
            canonical_val = canonical.get(canonical_field)

            # Skip if both are None/empty
            if _is_empty(source_val) and _is_empty(canonical_val):
                continue

            result.total_comparisons += 1

            try:
                s_num = float(source_val) if source_val is not None and source_val != "" else 0.0
                c_num = float(canonical_val) if canonical_val is not None else 0.0

                if abs(c_num - s_num) <= numeric_tolerance:
                    result.accurate += 1
                else:
                    result.inaccurate += 1
                    if len(result.errors) < 50:
                        result.errors.append({
                            "source_field": source_field,
                            "canonical_field": canonical_field,
                            "source_value": source_val,
                            "canonical_value": canonical_val,
                            "delta": abs(c_num - s_num),
                        })
            except (ValueError, TypeError):
                # Non-numeric comparison
                if str(source_val).strip() == str(canonical_val).strip():
                    result.accurate += 1
                else:
                    result.inaccurate += 1

    result.accuracy = result.accurate / result.total_comparisons if result.total_comparisons > 0 else 1.0
    return result


def compute_resolver_diagnostics(
    resolved: List[Dict[str, Any]],
    unresolved: List[Dict[str, Any]],
) -> ResolverDiagnostics:
    """Analyze resolver outcomes and categorize unresolved reasons."""
    total = len(resolved) + len(unresolved)
    diagnostics = ResolverDiagnostics(
        total_records=total,
        resolved_count=len(resolved),
        unresolved_count=len(unresolved),
        resolution_rate=len(resolved) / total if total else 0.0,
    )

    for record in unresolved:
        for fk in record.get("_unresolved_fks", []):
            # Extract the FK category (e.g., "billing_period_id", "contract_line_id")
            key = fk.split("(")[0].strip()
            diagnostics.reason_distribution[key] = diagnostics.reason_distribution.get(key, 0) + 1

    return diagnostics


def classify_product(
    product_desc: str,
    metered_available: str,
    product_rules: Dict[str, Any],
) -> str:
    """Classify a product according to ontology rules.

    Returns: "metered_energy", "available_energy", or "non_energy"
    """
    if not product_desc:
        return "non_energy"

    ma = metered_available.strip().lower()

    for category_name, rules in product_rules.items():
        rule_ma_values = [v.lower() for v in rules.get("metered_available", [])]
        patterns = rules.get("product_patterns", [])

        if ma in rule_ma_values:
            # Check if product matches any pattern in this category
            for pattern in patterns:
                if fnmatch.fnmatch(product_desc, pattern):
                    return category_name

    # If metered_available is clear, use that
    if ma == "metered":
        return "metered_energy"
    if ma == "available":
        return "available_energy"

    # Default: if N/A or empty, classify as non_energy
    return "non_energy"


def compute_classification_accuracy(
    records: List[Dict[str, Any]],
    product_rules: Dict[str, Any],
    adapter_categories: set,
) -> ClassificationResult:
    """Evaluate whether energy_category assignment matches ontology product classification.

    Detects the cbe_billing_adapter.py:47 bug where N/A is treated as available_energy
    for non-energy products.
    """
    result = ClassificationResult()

    for record in records:
        ma = (record.get("METERED_AVAILABLE") or "").strip().lower()
        product = record.get("PRODUCT_DESC", "")

        expected = classify_product(product, ma, product_rules)

        # Simulate what the adapter would produce
        adapter_category = "available" if ma in adapter_categories else "metered"

        result.total_records += 1

        # Map ontology category to adapter-level category
        expected_adapter = {
            "metered_energy": "metered",
            "available_energy": "available",
            "non_energy": "non_energy",  # Adapter has no "non_energy" -- this is the bug
        }.get(expected, "non_energy")

        if expected == "non_energy" and adapter_category == "available":
            result.incorrect += 1
            result.misclassified.append({
                "product": product,
                "metered_available": ma,
                "expected": "non_energy",
                "adapter_says": adapter_category,
            })
        elif expected_adapter == adapter_category:
            result.correct += 1
        else:
            # Other misclassification (metered ↔ available)
            result.incorrect += 1
            if len(result.misclassified) < 50:
                result.misclassified.append({
                    "product": product,
                    "metered_available": ma,
                    "expected": expected_adapter,
                    "adapter_says": adapter_category,
                })

    result.accuracy = result.correct / result.total_records if result.total_records > 0 else 1.0
    return result


def compute_dedup_check(
    records: List[Dict[str, Any]],
    key_fields: Tuple[str, ...] = ("organization_id", "meter_id", "billing_period_id", "contract_line_id"),
) -> Dict[str, Any]:
    """Check for duplicate records based on full composite key.

    The correct dedup key is (organization_id, meter_id, billing_period_id, contract_line_id),
    NOT just (meter_id, billing_period_id).
    """
    from collections import Counter

    keys = Counter(
        tuple(r.get(f) for f in key_fields)
        for r in records
        if all(r.get(f) is not None for f in key_fields)
    )

    duplicates = {str(k): v for k, v in keys.items() if v > 1}
    return {
        "total_keyed_records": sum(1 for r in records if all(r.get(f) is not None for f in key_fields)),
        "unique_keys": len(keys),
        "duplicate_keys": len(duplicates),
        "duplicates": dict(list(duplicates.items())[:20]),
    }


def _is_empty(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False
