"""
Ontology-aware field comparison with source filtering.

All comparisons use filtering policy from sage_to_fm_ontology.yaml:
- Source records filtered: DIM_CURRENT_RECORD=1 AND ACTIVE=1
- Date-valid records: within EFFECTIVE_START_DATE/EFFECTIVE_END_DATE window
- Metric denominators defined by filtered source records, not raw row counts
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FieldComparisonResult:
    """Result of comparing a single field across source and target records."""
    field_name: str
    total_source_records: int = 0
    total_target_records: int = 0
    matched: int = 0
    mismatched: int = 0
    source_only: int = 0  # In source but not target
    target_only: int = 0  # In target but not source
    accuracy: float = 0.0
    coverage: float = 0.0
    mismatches: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class FieldComparisonSuite:
    """Results of comparing multiple fields."""
    fields: Dict[str, FieldComparisonResult] = field(default_factory=dict)
    overall_accuracy: float = 0.0
    overall_coverage: float = 0.0


def compare_field(
    source_records: List[Dict[str, Any]],
    target_records: List[Dict[str, Any]],
    source_field: str,
    target_field: str,
    join_key_source: str,
    join_key_target: str,
    value_transform: Optional[callable] = None,
    numeric_tolerance: float = 0.001,
    max_mismatches: int = 20,
) -> FieldComparisonResult:
    """Compare a field between source and target record sets.

    Args:
        source_records: Filtered SAGE records.
        target_records: FM database records.
        source_field: Field name in source records.
        target_field: Field name in target records.
        join_key_source: Key field in source to join on.
        join_key_target: Key field in target to join on.
        value_transform: Optional transform applied to source value before comparison.
        numeric_tolerance: Tolerance for numeric comparisons.
        max_mismatches: Maximum number of mismatches to report in detail.
    """
    result = FieldComparisonResult(field_name=f"{source_field} -> {target_field}")
    result.total_source_records = len(source_records)
    result.total_target_records = len(target_records)

    # Build target lookup
    target_by_key: Dict[str, Any] = {}
    for rec in target_records:
        key = str(rec.get(join_key_target, "")).strip()
        if key:
            target_by_key[key] = rec

    for source_rec in source_records:
        source_key = str(source_rec.get(join_key_source, "")).strip()
        if not source_key:
            continue

        target_rec = target_by_key.get(source_key)
        if target_rec is None:
            result.source_only += 1
            continue

        source_val = source_rec.get(source_field)
        target_val = target_rec.get(target_field)

        if value_transform:
            source_val = value_transform(source_val)

        if _values_equivalent(source_val, target_val, numeric_tolerance):
            result.matched += 1
        else:
            result.mismatched += 1
            if len(result.mismatches) < max_mismatches:
                result.mismatches.append({
                    "key": source_key,
                    "source_value": source_val,
                    "target_value": target_val,
                })

    # Target records not in source
    source_keys = {str(r.get(join_key_source, "")).strip() for r in source_records}
    result.target_only = sum(
        1 for r in target_records
        if str(r.get(join_key_target, "")).strip() not in source_keys
    )

    total_compared = result.matched + result.mismatched
    result.accuracy = result.matched / total_compared if total_compared > 0 else 1.0
    result.coverage = total_compared / result.total_source_records if result.total_source_records > 0 else 0.0

    return result


def compare_multiple_fields(
    source_records: List[Dict[str, Any]],
    target_records: List[Dict[str, Any]],
    field_mappings: List[Dict[str, Any]],
    join_key_source: str,
    join_key_target: str,
) -> FieldComparisonSuite:
    """Compare multiple fields between source and target.

    Args:
        field_mappings: List of dicts with keys:
            - source_field: str
            - target_field: str
            - value_transform: Optional[callable]
            - numeric_tolerance: Optional[float]
    """
    suite = FieldComparisonSuite()

    for mapping in field_mappings:
        result = compare_field(
            source_records=source_records,
            target_records=target_records,
            source_field=mapping["source_field"],
            target_field=mapping["target_field"],
            join_key_source=join_key_source,
            join_key_target=join_key_target,
            value_transform=mapping.get("value_transform"),
            numeric_tolerance=mapping.get("numeric_tolerance", 0.001),
        )
        suite.fields[mapping["source_field"]] = result

    # Overall metrics (average across fields)
    accuracies = [r.accuracy for r in suite.fields.values() if (r.matched + r.mismatched) > 0]
    coverages = [r.coverage for r in suite.fields.values() if r.total_source_records > 0]
    suite.overall_accuracy = sum(accuracies) / len(accuracies) if accuracies else 1.0
    suite.overall_coverage = sum(coverages) / len(coverages) if coverages else 0.0

    return suite


def _values_equivalent(
    source_val: Any,
    target_val: Any,
    numeric_tolerance: float = 0.001,
) -> bool:
    """Compare two values with type-appropriate equivalence."""
    # Both None/empty
    if _is_empty(source_val) and _is_empty(target_val):
        return True
    if _is_empty(source_val) or _is_empty(target_val):
        return False

    # Numeric comparison
    try:
        s_num = float(source_val)
        t_num = float(target_val)
        if s_num == 0 and t_num == 0:
            return True
        if s_num == 0:
            return abs(t_num) < numeric_tolerance
        return abs(t_num - s_num) / abs(s_num) <= numeric_tolerance
    except (ValueError, TypeError):
        pass

    # String comparison (case-insensitive, whitespace-normalized)
    return str(source_val).strip().lower() == str(target_val).strip().lower()


def _is_empty(val: Any) -> bool:
    """Check if a value is None, empty string, or whitespace-only."""
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False
