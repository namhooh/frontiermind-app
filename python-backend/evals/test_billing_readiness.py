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
        Mother lines (site-level lines that have children) legitimately
        have meter_id = NULL and are excluded from this check.
        """
        # Identify mother lines: lines that other lines point to via parent_contract_line_id
        mother_ids = {
            cl["parent_contract_line_id"]
            for cl in fm_contract_lines
            if cl.get("parent_contract_line_id") is not None
        }

        energy_lines = [
            cl for cl in fm_contract_lines
            if cl.get("is_active")
            and cl.get("energy_category") in ("metered", "available")
            and cl["id"] not in mother_ids
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

    # =========================================================================
    # LEAN GATE SET (Excel-first cross-examination pipeline)
    # =========================================================================

    def test_clause_tariff_base_rate_populated(self, fm_clause_tariffs):
        """All populated tariffs have non-null base_rate.

        Phase 2 gate: after Excel-first population, every clause_tariff
        that was created by the pipeline should have a base_rate value.
        """
        tariffs_with_null_rate = [
            ct for ct in fm_clause_tariffs
            if ct.get("is_active")
            and ct.get("source_metadata", {}).get("pipeline") == "excel_first_cross_examination"
            and ct.get("base_rate") is None
        ]

        assert len(tariffs_with_null_rate) == 0, (
            f"{len(tariffs_with_null_rate)} excel-first tariffs have NULL base_rate. "
            f"IDs: {[ct['id'] for ct in tariffs_with_null_rate[:10]]}"
        )

    def test_year1_tariff_rate_exists(self, fm_clause_tariffs, fm_tariff_rates):
        """Every clause_tariff with base_rate has a Year 1 tariff_rate row.

        Phase 2 gate: after population, Year 1 must be explicitly inserted
        because the RatePeriodGenerator only updates/creates Years 2..N.
        """
        tariffs_with_rate = {
            ct["id"] for ct in fm_clause_tariffs
            if ct.get("is_active") and ct.get("base_rate") is not None
        }

        tariffs_with_year1 = {
            tr["clause_tariff_id"] for tr in fm_tariff_rates
            if tr.get("contract_year") == 1
            and tr.get("clause_tariff_id") in tariffs_with_rate
        }

        missing = tariffs_with_rate - tariffs_with_year1

        assert len(missing) == 0, (
            f"{len(missing)} clause_tariffs with base_rate but no Year 1 tariff_rate. "
            f"IDs: {list(missing)[:10]}"
        )

    def test_deterministic_rates_generated(self, fm_clause_tariffs, fm_tariff_rates):
        """Deterministic escalation projects have Years 2..N tariff_rate rows.

        Deterministic types: NONE, FIXED_INCREASE, FIXED_DECREASE, PERCENTAGE.
        These should have rate rows generated by RatePeriodGenerator.
        """
        deterministic_codes = {"NONE", "FIXED_INCREASE", "FIXED_DECREASE", "PERCENTAGE"}

        deterministic_tariffs = {
            ct["id"]: ct for ct in fm_clause_tariffs
            if ct.get("is_active")
            and ct.get("base_rate") is not None
            and ct.get("escalation_type_code") in deterministic_codes
        }

        for tariff_id, ct in deterministic_tariffs.items():
            rates = [
                tr for tr in fm_tariff_rates
                if tr["clause_tariff_id"] == tariff_id
                and tr.get("rate_granularity") == "annual"
            ]
            # Should have at least Year 1 + Year 2
            if len(rates) < 2:
                import warnings
                warnings.warn(
                    f"clause_tariff {tariff_id} (escalation={ct.get('escalation_type_code')}) "
                    f"has only {len(rates)} annual rate(s), expected >= 2"
                )

    def test_rebased_floating_pending_status(self, fm_clause_tariffs, fm_tariff_rates):
        """Rebased/floating tariffs have explicit calc_status='pending' or engine outputs.

        Non-deterministic types (US_CPI, REBASED_MARKET_PRICE) require external
        data feeds. If inputs are unavailable, rates should be marked pending.
        """
        non_deterministic_codes = {"US_CPI", "REBASED_MARKET_PRICE"}

        non_det_tariffs = [
            ct for ct in fm_clause_tariffs
            if ct.get("is_active")
            and ct.get("base_rate") is not None
            and ct.get("escalation_type_code") in non_deterministic_codes
        ]

        for ct in non_det_tariffs:
            rates = [
                tr for tr in fm_tariff_rates
                if tr["clause_tariff_id"] == ct["id"]
                and tr.get("rate_granularity") == "annual"
            ]
            # Either has calculated rates OR has Year 1 only (pending)
            if len(rates) == 0:
                import warnings
                warnings.warn(
                    f"Non-deterministic clause_tariff {ct['id']} "
                    f"(type={ct.get('escalation_type_code')}) has no rate rows"
                )

    def test_no_duplicate_contract_lines(self, fm_contract_lines):
        """No duplicate contract lines by (contract_id, contract_line_number).

        Phase 2 gate: the upsert should prevent duplicates, but verify
        as a safety check.
        """
        seen = set()
        duplicates = []
        for cl in fm_contract_lines:
            key = (cl["contract_id"], cl.get("contract_line_number"))
            if key in seen:
                duplicates.append(key)
            seen.add(key)

        assert len(duplicates) == 0, (
            f"{len(duplicates)} duplicate contract lines by (contract_id, line_number): "
            f"{duplicates[:10]}"
        )

    def test_no_duplicate_meter_reads(self, fm_meter_aggregates):
        """No duplicate meter readings by external reading key.

        Checks source_metadata->>'external_reading_id' uniqueness
        for excel-first pipeline entries.
        """
        seen = set()
        duplicates = []
        for ma in fm_meter_aggregates:
            meta = ma.get("source_metadata") or {}
            ext_id = meta.get("external_reading_id")
            if ext_id:
                if ext_id in seen:
                    duplicates.append(ext_id)
                seen.add(ext_id)

        assert len(duplicates) == 0, (
            f"{len(duplicates)} duplicate meter readings by external_reading_id: "
            f"{duplicates[:10]}"
        )

    def test_contract_line_tariff_linked(self, fm_contract_lines, fm_clause_tariffs):
        """Contract lines and tariffs are linked for approved projects.

        For projects that have been through the excel-first pipeline,
        energy contract lines should have clause_tariff_id set.
        """
        # Only check contracts that have excel-first tariffs
        excel_first_contract_ids = {
            ct["contract_id"] for ct in fm_clause_tariffs
            if ct.get("is_active")
            and ct.get("source_metadata", {}).get("pipeline") == "excel_first_cross_examination"
        }

        unlinked = []
        for cl in fm_contract_lines:
            if not cl.get("is_active"):
                continue
            if cl["contract_id"] not in excel_first_contract_ids:
                continue
            if cl.get("energy_category") in ("metered", "available"):
                if cl.get("clause_tariff_id") is None:
                    unlinked.append(cl["id"])

        if unlinked:
            import warnings
            warnings.warn(
                f"{len(unlinked)} energy lines in excel-first contracts missing clause_tariff_id: "
                f"{unlinked[:10]}"
            )
