"""
Scorecard 2: Mapping Integrity — Identity chain coverage.

Tests coverage at each layer of the SAGE -> FM identity chain:
- Layer 1: CUSTOMER_NUMBER -> project.sage_id (with alias resolution)
- Layer 2: CONTRACT_NUMBER -> contract.external_contract_id
- Layer 3: CONTRACT_LINE_UNIQUE_ID -> contract_line.external_line_id
- Layer 4: Ambiguity detection + nondeterminism detection

Maturity tiers:
- Bronze: coverage >= 0.70
- Silver: coverage >= 0.90, no ambiguity
- Gold: coverage == 1.0
"""

import warnings
from collections import Counter

import pytest

from evals.conftest import load_exceptions
from evals.metrics import mapping_metrics
from evals.specs.filtering_policy import is_internal_entity, resolve_sage_id


@pytest.mark.eval
class TestMappingIntegrity:
    """Identity chain coverage tests."""

    # --- Layer 1: Customer -> Project ---

    def test_sage_customer_to_project(self, ontology, sage_customers, fm_projects):
        """Every active SAGE customer (after exclusions) maps to an FM project."""
        layer = mapping_metrics.compute_customer_coverage(
            sage_customers, fm_projects, ontology
        )

        assert layer.coverage >= 0.70, (
            f"Customer->Project coverage {layer.coverage:.3f} below bronze threshold 0.70. "
            f"Matched={layer.matched}, Unmatched={layer.unmatched}: {layer.unmatched_keys[:5]}"
        )

    def test_sage_customer_exclusions_not_in_fm(self, ontology, fm_projects):
        """Excluded SAGE customers should NOT have FM projects (validates exclusion list)."""
        exclusions = set(ontology["identity_keys"]["customer"]["exclusions"])
        aliases = ontology["identity_keys"]["customer"]["aliases"]

        found_in_fm = []
        for excl in exclusions:
            sage_id = aliases.get(excl, excl)
            if sage_id in fm_projects:
                found_in_fm.append(f"{excl} -> {sage_id}")

        if found_in_fm:
            warnings.warn(
                f"Excluded customers found in FM (may need exception list update): {found_in_fm}"
            )

    # --- Layer 2: Contract -> external_contract_id ---

    def test_contract_number_mapping(self, ontology, sage_contracts_filtered, fm_contracts, exceptions_registry):
        """Active KWH/RENTAL SAGE contracts map to FM external_contract_id.

        NOTE: With synthetic fixture data, coverage will be 0% because fixture
        contract numbers are synthetic. Run with SAGE_DATA_DIR for real evaluation.
        """
        import os

        # Build FM contracts lookup by sage_id
        fm_by_sage_id = {}
        for c in fm_contracts:
            sid = c.get("sage_id")
            if sid and c.get("parent_contract_id") is None:
                fm_by_sage_id[sid] = c

        exceptions = load_exceptions("contract mapping", exceptions_registry)
        layer = mapping_metrics.compute_contract_coverage(
            sage_contracts_filtered, fm_by_sage_id, ontology, exceptions
        )

        using_fixtures = not os.getenv("SAGE_DATA_DIR")
        if using_fixtures and layer.coverage < 0.50:
            warnings.warn(
                f"Contract mapping coverage {layer.coverage:.3f} (fixture data). "
                f"Matched={layer.matched}, Unmatched={layer.unmatched}. "
                f"Run with SAGE_DATA_DIR for real evaluation."
            )
        else:
            assert layer.coverage >= 0.50, (
                f"Contract mapping coverage {layer.coverage:.3f} below threshold 0.50. "
                f"Matched={layer.matched}, Unmatched={layer.unmatched}: {layer.unmatched_keys[:5]}"
            )

    # --- Layer 3: Contract Line -> external_line_id ---

    def test_contract_line_mapping(self, sage_contract_lines_filtered, fm_contract_lines):
        """SAGE CONTRACT_LINE_UNIQUE_ID maps to FM contract_line.external_line_id."""
        layer = mapping_metrics.compute_contract_line_coverage(
            sage_contract_lines_filtered, fm_contract_lines
        )

        # MOH01 has 11 lines; other projects pending 048
        assert layer.coverage >= 0.05, (
            f"Contract line coverage {layer.coverage:.3f} below threshold 0.05. "
            f"Matched={layer.matched}/{layer.total_source}"
        )

    # --- Layer 4: Ambiguity detection ---

    def test_no_ambiguous_contract_mapping(self, fm_contracts):
        """No project has > 1 primary contract with external_contract_id set."""
        ambiguous = mapping_metrics.detect_ambiguous_mappings(fm_contracts)
        assert len(ambiguous) == 0, (
            f"Ambiguous contract mapping detected: {ambiguous}"
        )

    # --- Multi-contract nondeterminism detection ---

    def test_billing_contract_determinism(self, db_conn):
        """Flag projects where billing.py LIMIT 1 would be nondeterministic."""
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT p.sage_id, COUNT(*) as primary_count
                FROM project p
                JOIN contract c ON c.project_id = p.id AND c.parent_contract_id IS NULL
                WHERE p.organization_id = 1
                GROUP BY p.sage_id
                HAVING COUNT(*) > 1
            """)
            multi = [dict(row) for row in cur.fetchall()]

        # This is a WARNING, not a hard failure (until 048 adds OM contracts)
        if multi:
            for row in multi:
                warnings.warn(
                    f"NONDETERMINISTIC: {row['sage_id']} has {row['primary_count']} primary contracts"
                )

    # --- Full chain report ---

    def test_identity_chain_report(self, ontology, sage_customers, sage_contracts_filtered,
                                    sage_contract_lines_filtered, fm_projects, fm_contracts,
                                    fm_contract_lines, exceptions_registry):
        """Build and verify the full identity chain report."""
        # Layer 1
        layer1 = mapping_metrics.compute_customer_coverage(
            sage_customers, fm_projects, ontology
        )

        # Layer 2
        fm_by_sage_id = {}
        for c in fm_contracts:
            sid = c.get("sage_id")
            if sid and c.get("parent_contract_id") is None:
                fm_by_sage_id[sid] = c

        exceptions = load_exceptions("contract mapping", exceptions_registry)
        layer2 = mapping_metrics.compute_contract_coverage(
            sage_contracts_filtered, fm_by_sage_id, ontology, exceptions
        )

        # Layer 3
        layer3 = mapping_metrics.compute_contract_line_coverage(
            sage_contract_lines_filtered, fm_contract_lines
        )

        report = mapping_metrics.build_identity_chain_report([layer1, layer2, layer3])

        # Report overall coverage
        assert report.overall_coverage >= 0.05, (
            f"Identity chain overall coverage {report.overall_coverage:.3f} too low. "
            f"Layer coverages: "
            + ", ".join(f"{name}={l.coverage:.3f}" for name, l in report.layers.items())
        )
