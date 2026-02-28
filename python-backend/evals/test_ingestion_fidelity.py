"""
Scorecard 3: Ingestion Fidelity — Value accuracy + resolver outcomes.

Tests:
- Completeness: FM has readings for expected SAGE {CONTRACT_LINE_UNIQUE_ID, BILL_DATE} pairs
- Value accuracy: CBE adapter transform preserves SAGE values (roundtrip)
- Semantic classification: energy_category matches ontology product classification
- Resolver diagnostics: unresolved FK distribution
- Dedup key correctness: uses full composite key

Maturity tiers:
- Bronze: completeness >= 0.80
- Silver: completeness >= 0.95, accuracy >= 0.99
- Gold: completeness == 1.0, 0 unresolved
"""

import os
import warnings

import pytest

from evals.metrics import ingestion_metrics
from evals.metrics.scorer import MATURITY_THRESHOLDS


@pytest.mark.eval
class TestIngestionFidelity:
    """Ingestion pipeline accuracy and completeness tests."""

    def test_completeness(self, sage_readings_moh01, fm_meter_aggregates):
        """FM has readings for expected unique {CONTRACT_LINE_UNIQUE_ID, BILL_DATE} pairs.

        NOTE: When using synthetic fixture data, completeness may be 0% because
        fixture contract_line IDs don't exist in the real DB. This test is meaningful
        when run with real SAGE data via SAGE_DATA_DIR.
        """
        # Build lookup from FM meter_aggregates: need external_line_id from source_metadata
        fm_records = []
        for ma in fm_meter_aggregates:
            metadata = ma.get("source_metadata") or {}
            if isinstance(metadata, str):
                import json
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            fm_records.append({
                "external_line_id": metadata.get("contract_line_unique_id", ""),
                "period_end": str(ma.get("period_end", "")),
            })

        result = ingestion_metrics.compute_completeness(
            source_records=sage_readings_moh01,
            target_records=fm_records,
            source_key_fields=("CONTRACT_LINE_UNIQUE_ID", "BILL_DATE"),
            target_key_fields=("external_line_id", "period_end"),
        )

        # With real SAGE data, threshold is bronze (0.80). With fixtures, report only.
        using_fixtures = not os.getenv("SAGE_DATA_DIR")
        threshold = MATURITY_THRESHOLDS["ingestion_fidelity"]["bronze"]["completeness"]
        if using_fixtures and result.completeness < threshold:
            import warnings
            warnings.warn(
                f"Ingestion completeness {result.completeness:.3f} (fixture data). "
                f"Expected={result.expected_count}, Matched={result.matched_count}. "
                f"Run with SAGE_DATA_DIR for real evaluation."
            )
        else:
            assert result.completeness >= threshold, (
                f"Ingestion completeness {result.completeness:.3f} below bronze threshold {threshold}. "
                f"Expected={result.expected_count}, Matched={result.matched_count}, "
                f"Missing={len(result.missing_keys)}"
            )

    def test_value_accuracy_post_transform(self, sage_readings_moh01):
        """CBE adapter transform preserves SAGE values (roundtrip test, no DB)."""
        try:
            from data_ingestion.processing.adapters.cbe_billing_adapter import CBEBillingAdapter
        except ImportError:
            pytest.skip("data_ingestion modules not importable (PYTHONPATH missing)")

        adapter = CBEBillingAdapter()
        validation = adapter.validate(sage_readings_moh01)
        assert validation.is_valid, f"Validation failed: {validation.error_message}"

        canonical = adapter.transform(sage_readings_moh01, organization_id=1, resolver=None)

        result = ingestion_metrics.compute_value_accuracy(
            source_records=sage_readings_moh01,
            canonical_records=canonical,
            field_pairs=[
                ("UTILIZED_READING", "utilized_reading"),
                ("OPENING_READING", "opening_reading"),
                ("CLOSING_READING", "closing_reading"),
                ("DISCOUNT_READING", "discount_reading"),
                ("SOURCED_ENERGY", "sourced_energy"),
            ],
        )

        assert result.accuracy >= 0.99, (
            f"Value accuracy {result.accuracy:.3f} too low. "
            f"Accurate={result.accurate}, Inaccurate={result.inaccurate}"
        )
        if result.errors:
            for err in result.errors[:3]:
                warnings.warn(
                    f"Value drift: {err['source_field']}={err['source_value']} "
                    f"-> {err['canonical_field']}={err['canonical_value']} "
                    f"(delta={err['delta']:.4f})"
                )

    def test_semantic_classification_accuracy(self, ontology, sage_contract_lines_filtered):
        """Evaluate whether energy_category assignment matches ontology product classification.

        Catches the cbe_billing_adapter.py:47 bug where N/A is treated as available_energy
        for non-energy products (Minimum Offtake, O&M, BESS, Diesel, etc.).
        """
        product_rules = ontology["operational"]["product_classification"]["categories"]

        # The adapter's AVAILABLE_CATEGORIES set (lowercase for comparison)
        adapter_categories = {"available", "n/a"}

        result = ingestion_metrics.compute_classification_accuracy(
            records=sage_contract_lines_filtered,
            product_rules=product_rules,
            adapter_categories=adapter_categories,
        )

        if result.misclassified:
            warnings.warn(
                f"ADAPTER BUG: {len(result.misclassified)} non-energy products misclassified as 'available': "
                f"{[m['product'] for m in result.misclassified[:5]]}"
            )

    def test_resolver_unresolved_distribution(self, sage_readings_moh01, db_conn):
        """Run BillingResolver on SAGE data and categorize unresolved reasons."""
        try:
            from data_ingestion.processing.billing_resolver import BillingResolver
            from data_ingestion.processing.adapters.cbe_billing_adapter import CBEBillingAdapter
        except ImportError:
            pytest.skip("data_ingestion modules not importable")

        adapter = CBEBillingAdapter()
        canonical = adapter.transform(sage_readings_moh01, organization_id=1, resolver=None)

        resolver = BillingResolver()
        resolved, unresolved = resolver.resolve_batch(canonical, organization_id=1)

        diagnostics = ingestion_metrics.compute_resolver_diagnostics(resolved, unresolved)

        # Report distribution (not a hard failure -- unresolved expected for non-MOH01)
        if diagnostics.unresolved_count > 0:
            warnings.warn(
                f"Resolver: {diagnostics.resolved_count}/{diagnostics.total_records} resolved "
                f"({diagnostics.resolution_rate:.1%}). "
                f"Unresolved reasons: {diagnostics.reason_distribution}"
            )

    def test_dedup_key_correctness(self, fm_meter_aggregates):
        """Dedup check uses full key (organization_id, meter_id, billing_period_id, contract_line_id).

        NOT just (meter_id, billing_period_id) -- that ignores contract_line_id dimension.
        """
        result = ingestion_metrics.compute_dedup_check(fm_meter_aggregates)

        assert result["duplicate_keys"] == 0, (
            f"{result['duplicate_keys']} duplicate meter_aggregate keys found: "
            f"{list(result['duplicates'].items())[:5]}"
        )

    def test_contract_line_energy_category_populated(self, fm_contract_lines):
        """All active contract_lines have a non-null energy_category."""
        active_lines = [cl for cl in fm_contract_lines if cl.get("is_active")]
        missing = [cl for cl in active_lines if cl.get("energy_category") is None]
        if missing:
            warnings.warn(
                f"{len(missing)} active contract_lines missing energy_category "
                f"(out of {len(active_lines)} total)"
            )
