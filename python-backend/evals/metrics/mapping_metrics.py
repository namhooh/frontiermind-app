"""
Identity chain coverage metrics.

Measures coverage at each layer of the SAGE → FM identity chain:
- Layer 1: CUSTOMER_NUMBER → project.sage_id (with alias resolution)
- Layer 2: CONTRACT_NUMBER → contract.external_contract_id
- Layer 3: CONTRACT_LINE_UNIQUE_ID → contract_line.external_line_id
- Layer 4: METER_READING_UNIQUE_ID → meter_aggregate.source_metadata

Reports: matched / unmatched / ambiguous per layer.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class LayerCoverage:
    """Coverage metrics for a single identity chain layer."""
    layer_name: str
    source_key: str
    target_key: str
    total_source: int = 0
    matched: int = 0
    unmatched: int = 0
    ambiguous: int = 0  # >1 FM record for 1 SAGE key
    coverage: float = 0.0
    unmatched_keys: List[str] = field(default_factory=list)
    ambiguous_keys: List[str] = field(default_factory=list)


@dataclass
class IdentityChainReport:
    """Full identity chain coverage report."""
    layers: Dict[str, LayerCoverage] = field(default_factory=dict)
    overall_coverage: float = 0.0
    has_ambiguity: bool = False


def compute_customer_coverage(
    sage_customers: List[Dict[str, Any]],
    fm_projects: Dict[str, Any],
    ontology: Dict[str, Any],
    max_unmatched: int = 20,
) -> LayerCoverage:
    """Layer 1: CUSTOMER_NUMBER → project.sage_id.

    Args:
        sage_customers: Filtered SAGE customer records.
        fm_projects: Dict mapping sage_id → project record.
        ontology: Full ontology dict.
    """
    from evals.specs.filtering_policy import is_internal_entity, resolve_sage_id

    customer_config = ontology.get("identity_keys", {}).get("customer", {})
    exclusions = set(customer_config.get("exclusions", []))

    layer = LayerCoverage(
        layer_name="customer_to_project",
        source_key="CUSTOMER_NUMBER",
        target_key="project.sage_id",
    )

    seen = set()
    for cust in sage_customers:
        cust_num = cust.get("CUSTOMER_NUMBER", "").strip()
        if not cust_num or cust_num in exclusions:
            continue
        if is_internal_entity(cust_num, ontology):
            continue
        if cust_num in seen:
            continue
        seen.add(cust_num)

        sage_id = resolve_sage_id(cust_num, ontology)
        layer.total_source += 1

        if sage_id in fm_projects:
            layer.matched += 1
        else:
            layer.unmatched += 1
            if len(layer.unmatched_keys) < max_unmatched:
                layer.unmatched_keys.append(f"{cust_num} -> {sage_id}")

    layer.coverage = layer.matched / layer.total_source if layer.total_source > 0 else 1.0
    return layer


def compute_contract_coverage(
    sage_contracts: List[Dict[str, Any]],
    fm_contracts: Dict[str, Any],
    ontology: Dict[str, Any],
    exceptions: Optional[List[Dict]] = None,
    max_unmatched: int = 20,
) -> LayerCoverage:
    """Layer 2: CONTRACT_NUMBER → contract.external_contract_id.

    Args:
        sage_contracts: Filtered SAGE contract records (KWH + RENTAL scope).
        fm_contracts: Dict mapping sage_id → contract record(s).
        ontology: Full ontology dict.
        exceptions: Exception registry entries for "contract mapping" scope.
    """
    from evals.specs.filtering_policy import resolve_sage_id

    exception_sage_ids = set()
    if exceptions:
        for exc in exceptions:
            for sid in exc.get("sage_ids", []):
                exception_sage_ids.add(sid)

    layer = LayerCoverage(
        layer_name="contract_to_external_id",
        source_key="CONTRACT_NUMBER",
        target_key="contract.external_contract_id",
    )

    seen_contracts = set()
    for sc in sage_contracts:
        contract_num = (sc.get("CONTRACT_NUMBER") or "").strip()
        if not contract_num or contract_num in seen_contracts:
            continue
        seen_contracts.add(contract_num)

        sage_id = resolve_sage_id(sc.get("CUSTOMER_NUMBER", ""), ontology)
        layer.total_source += 1

        # Check if this is a known exception
        if sage_id in exception_sage_ids:
            layer.matched += 1  # Don't penalize known exceptions
            continue

        # Check if FM has this contract
        fm = fm_contracts.get(sage_id)
        if fm and fm.get("external_contract_id") == contract_num:
            layer.matched += 1
        elif fm:
            # FM project exists but contract ID doesn't match
            layer.unmatched += 1
            if len(layer.unmatched_keys) < max_unmatched:
                layer.unmatched_keys.append(
                    f"{contract_num} (sage_id={sage_id}, fm_ext_id={fm.get('external_contract_id')})"
                )
        else:
            layer.unmatched += 1
            if len(layer.unmatched_keys) < max_unmatched:
                layer.unmatched_keys.append(f"{contract_num} (sage_id={sage_id}, no FM project)")

    layer.coverage = layer.matched / layer.total_source if layer.total_source > 0 else 1.0
    return layer


def compute_contract_line_coverage(
    sage_contract_lines: List[Dict[str, Any]],
    fm_contract_lines: List[Dict[str, Any]],
    max_unmatched: int = 20,
) -> LayerCoverage:
    """Layer 3: CONTRACT_LINE_UNIQUE_ID → contract_line.external_line_id."""
    layer = LayerCoverage(
        layer_name="contract_line_to_external_line_id",
        source_key="CONTRACT_LINE_UNIQUE_ID",
        target_key="contract_line.external_line_id",
    )

    fm_line_ids = {
        (cl.get("external_line_id") or "").strip()
        for cl in fm_contract_lines
        if cl.get("external_line_id")
    }

    sage_line_ids = set()
    for cl in sage_contract_lines:
        line_id = (cl.get("CONTRACT_LINE_UNIQUE_ID") or "").strip()
        if line_id:
            sage_line_ids.add(line_id)

    layer.total_source = len(sage_line_ids)
    matched = sage_line_ids & fm_line_ids
    unmatched = sage_line_ids - fm_line_ids

    layer.matched = len(matched)
    layer.unmatched = len(unmatched)
    layer.unmatched_keys = sorted(list(unmatched))[:max_unmatched]
    layer.coverage = layer.matched / layer.total_source if layer.total_source > 0 else 1.0

    return layer


def compute_meter_reading_coverage(
    sage_readings: List[Dict[str, Any]],
    fm_meter_aggregates: List[Dict[str, Any]],
    max_unmatched: int = 20,
) -> LayerCoverage:
    """Layer 4: METER_READING_UNIQUE_ID → meter_aggregate.source_metadata->>'external_reading_id'."""
    layer = LayerCoverage(
        layer_name="meter_reading_to_aggregate",
        source_key="METER_READING_UNIQUE_ID",
        target_key="meter_aggregate.source_metadata.external_reading_id",
    )

    # Extract external_reading_id from FM source_metadata
    fm_reading_ids: Set[str] = set()
    for ma in fm_meter_aggregates:
        metadata = ma.get("source_metadata") or {}
        if isinstance(metadata, str):
            import json
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        reading_id = (metadata.get("external_reading_id") or "").strip()
        if reading_id:
            fm_reading_ids.add(reading_id)

    sage_reading_ids: Set[str] = set()
    for r in sage_readings:
        reading_id = (r.get("METER_READING_UNIQUE_ID") or "").strip()
        if reading_id:
            sage_reading_ids.add(reading_id)

    layer.total_source = len(sage_reading_ids)
    matched = sage_reading_ids & fm_reading_ids
    unmatched = sage_reading_ids - fm_reading_ids

    layer.matched = len(matched)
    layer.unmatched = len(unmatched)
    layer.unmatched_keys = sorted(list(unmatched))[:max_unmatched]
    layer.coverage = layer.matched / layer.total_source if layer.total_source > 0 else 1.0

    return layer


def detect_ambiguous_mappings(
    fm_contracts: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Detect projects with >1 primary contract with external_contract_id set.

    This indicates ambiguous mapping where billing.py LIMIT 1 would be nondeterministic.
    """
    project_counts = Counter(
        c["project_id"]
        for c in fm_contracts
        if c.get("parent_contract_id") is None
        and c.get("external_contract_id")
    )
    return {str(pid): cnt for pid, cnt in project_counts.items() if cnt > 1}


def build_identity_chain_report(
    layers: List[LayerCoverage],
) -> IdentityChainReport:
    """Build a full identity chain coverage report from individual layer results."""
    report = IdentityChainReport()

    for layer in layers:
        report.layers[layer.layer_name] = layer
        if layer.ambiguous > 0:
            report.has_ambiguity = True

    coverages = [l.coverage for l in layers if l.total_source > 0]
    report.overall_coverage = min(coverages) if coverages else 1.0

    return report
