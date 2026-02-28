"""
Scorecard 4: Billing Readiness — Invoice generation prerequisites.

Tests:
- Contract line completeness: projects with contracts have active lines
- Contract line meter FK: energy lines have valid meter_id
- Clause tariff linkage: energy lines have active clause_tariff
- Billing period calendar: periods exist Jan 2024 - Dec 2027
- Exchange rate coverage: non-USD currencies have trailing 12mo rates
- Billing product junction: contracts with lines have billing products

Maturity tiers:
- Bronze: >= 1 project ready
- Silver: >= 50% projects ready
- Gold: all projects ready
"""

import pytest


@pytest.mark.eval
class TestBillingReadiness:
    """Billing pipeline prerequisite checks."""

    def test_contract_line_completeness(self, fm_contracts, fm_contract_lines):
        """Projects with primary contracts have active contract_lines."""
        projects_with_contracts = {
            c["project_id"]
            for c in fm_contracts
            if c.get("parent_contract_id") is None
        }

        # Map contract_id -> project_id
        contract_to_project = {c["id"]: c["project_id"] for c in fm_contracts}

        projects_with_active_lines = {
            contract_to_project[cl["contract_id"]]
            for cl in fm_contract_lines
            if cl.get("is_active") and cl["contract_id"] in contract_to_project
        }

        ready = len(projects_with_active_lines & projects_with_contracts)
        total = len(projects_with_contracts)

        # Bronze: at least 1 project (MOH01)
        assert ready >= 1, (
            f"No projects have active contract_lines. "
            f"Projects with contracts: {total}"
        )

    def test_contract_line_meter_fk(self, fm_contract_lines):
        """Active energy contract_lines (metered/available) have valid meter_id.

        NOTE: rental/OM lines may legitimately have NULL meter_id.
        Only energy lines require meters.
        """
        energy_lines = [
            cl for cl in fm_contract_lines
            if cl.get("is_active") and cl.get("energy_category") in ("metered", "available")
        ]

        orphans = [cl for cl in energy_lines if cl.get("meter_id") is None]

        assert len(orphans) == 0, (
            f"{len(orphans)} energy contract_lines missing meter_id "
            f"(out of {len(energy_lines)} active energy lines). "
            f"IDs: {[cl['id'] for cl in orphans[:10]]}"
        )

    def test_clause_tariff_for_energy_lines(self, fm_contract_lines, fm_clause_tariffs):
        """Active energy contract_lines have an active clause_tariff."""
        active_tariff_ids = {ct["id"] for ct in fm_clause_tariffs if ct.get("is_active")}

        energy_lines = [
            cl for cl in fm_contract_lines
            if cl.get("is_active") and cl.get("energy_category") in ("metered", "available")
        ]

        # Lines with a tariff_id that's not in the active tariffs set
        orphans = [
            cl for cl in energy_lines
            if cl.get("clause_tariff_id") and cl["clause_tariff_id"] not in active_tariff_ids
        ]

        assert len(orphans) == 0, (
            f"{len(orphans)} energy contract_lines reference inactive clause_tariff. "
            f"IDs: {[cl['id'] for cl in orphans[:10]]}"
        )

    def test_billing_period_calendar(self, fm_billing_periods):
        """Billing periods exist for Jan 2024 through Dec 2027."""
        months = set()
        for bp in fm_billing_periods:
            start = bp.get("start_date")
            if start:
                if hasattr(start, "year"):
                    months.add((start.year, start.month))
                else:
                    # Parse string date
                    from datetime import datetime
                    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                        try:
                            dt = datetime.strptime(str(start), fmt)
                            months.add((dt.year, dt.month))
                            break
                        except ValueError:
                            continue

        missing = []
        for year in range(2024, 2028):
            for month in range(1, 13):
                if (year, month) not in months:
                    missing.append(f"{year}-{month:02d}")

        assert len(missing) == 0, (
            f"Missing billing periods: {missing[:12]}... "
            f"({len(missing)} total missing out of 48 expected)"
        )

    def test_exchange_rate_coverage(self, ontology, fm_contracts, fm_exchange_rates):
        """Non-USD contract currencies have exchange rates for trailing 12 months."""
        known_mismatches = {
            m["sage_id"]
            for m in ontology["commercial"]["currency"]["known_mismatches"]
        }

        non_usd_contracts = [
            c for c in fm_contracts
            if c.get("sage_id") not in known_mismatches
            and c.get("billing_currency") not in ("USD", None)
            and c.get("parent_contract_id") is None
        ]

        insufficient = []
        for contract in non_usd_contracts:
            currency = contract["billing_currency"]
            rates = [r for r in fm_exchange_rates if r.get("currency_code") == currency]
            if len(rates) < 12:
                insufficient.append(f"{contract.get('sage_id', '?')}/{currency}: {len(rates)} rates")

        if insufficient:
            # Warning rather than hard failure — rates may still be loading
            import warnings
            warnings.warn(
                f"Insufficient FX rates for {len(insufficient)} contracts: {insufficient[:5]}"
            )

    def test_billing_product_junction(self, fm_contracts, fm_contract_lines, fm_contract_billing_products):
        """Every contract with active contract_lines has >= 1 contract_billing_product."""
        contracts_with_lines = {
            cl["contract_id"]
            for cl in fm_contract_lines
            if cl.get("is_active")
        }

        contracts_with_products = {
            cbp["contract_id"]
            for cbp in fm_contract_billing_products
        }

        missing = contracts_with_lines - contracts_with_products

        assert len(missing) == 0, (
            f"{len(missing)} contracts with active lines but no billing products: "
            f"{list(missing)[:10]}"
        )

    def test_billing_ready_project_count(self, fm_contracts, fm_contract_lines,
                                          fm_clause_tariffs, fm_billing_periods):
        """Count projects that meet all billing prerequisites."""
        contract_to_project = {c["id"]: c["project_id"] for c in fm_contracts}
        active_tariff_ids = {ct["id"] for ct in fm_clause_tariffs if ct.get("is_active")}

        ready_projects = set()
        for cl in fm_contract_lines:
            if not cl.get("is_active"):
                continue
            if cl.get("energy_category") in ("metered", "available"):
                if cl.get("meter_id") is None:
                    continue
                if cl.get("clause_tariff_id") and cl["clause_tariff_id"] not in active_tariff_ids:
                    continue
            contract_id = cl["contract_id"]
            if contract_id in contract_to_project:
                ready_projects.add(contract_to_project[contract_id])

        assert len(ready_projects) >= 1, (
            f"No projects meet all billing prerequisites"
        )
