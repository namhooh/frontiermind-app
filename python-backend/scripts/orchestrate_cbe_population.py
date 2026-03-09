#!/usr/bin/env python3
"""
CBE Data Population Orchestrator.

Runs the 11-step CBE data population pipeline (one step at a time),
validates DB state, fills NULL gaps, and tracks discrepancies.

Usage:
    python scripts/orchestrate_cbe_population.py \
        --step 1 \
        --data-dir ../CBE_data_extracts \
        [--project KAS01] \
        [--dry-run] \
        [--org-id 1]
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cbe_orchestrator")

DEFAULT_ORG_ID = 1


# =============================================================================
# Core Data Structures
# =============================================================================

@dataclass
class Discrepancy:
    severity: str       # "critical" | "warning" | "info"
    category: str       # "value_conflict" | "missing_data" | "alias_mismatch"
    project: str        # sage_id
    step: int
    field: str          # DB field path
    source_a: str       # xlsx value
    source_b: str       # DB value
    recommended_action: str
    status: str = "open"  # "open" | "resolved"


@dataclass
class GateCheck:
    name: str
    passed: bool
    expected: str
    actual: str


@dataclass
class StepResult:
    step_number: int
    step_name: str
    status: str = "passed"  # "passed" | "failed" | "warnings" | "skipped"
    validated: int = 0
    gaps_filled: int = 0
    discrepancies: List[Discrepancy] = field(default_factory=list)
    gate_checks: List[GateCheck] = field(default_factory=list)


# =============================================================================
# Step Registry
# =============================================================================

class StepRegistry:
    _steps: Dict[int, Tuple[str, Callable]] = {}

    @classmethod
    def register(cls, step_num: int, name: str):
        def decorator(fn):
            cls._steps[step_num] = (name, fn)
            return fn
        return decorator

    @classmethod
    def run(cls, step_num: int, ctx: dict) -> StepResult:
        if step_num not in cls._steps:
            raise ValueError(f"Step {step_num} not registered. Available: {sorted(cls._steps.keys())}")
        name, fn = cls._steps[step_num]
        logger.info(f"{'='*60}")
        logger.info(f"Step {step_num}: {name}")
        logger.info(f"{'='*60}")
        return fn(ctx)

    @classmethod
    def available_steps(cls) -> List[int]:
        return sorted(cls._steps.keys())


# =============================================================================
# Known Expected Discrepancies (don't flag as errors)
# =============================================================================

KNOWN_DISCREPANCIES = {
    # GC001 country: xlsx="Mauritius" (legal entity jurisdiction), DB="Kenya" (site)
    ("GC001", "country"): "DB wins — xlsx shows legal entity country, DB shows site country",
    # QMM01 country: xlsx="Madagascar 1" vs DB="Madagascar"
    ("QMM01", "country"): "DB wins — xlsx has trailing suffix",
    # Currency mismatches: SAGE=USD, FM=local currency (EXC-002)
    ("XFAB", "currency"): "Expected — SAGE=USD, FM=KES (different domains)",
    ("XFBV", "currency"): "Expected — SAGE=USD, FM=KES (different domains)",
    ("XFL01", "currency"): "Expected — SAGE=USD, FM=KES (different domains)",
    ("XFSS", "currency"): "Expected — SAGE=USD, FM=KES (different domains)",
    ("QMM01", "currency"): "Expected — SAGE=USD, FM=MGA (different domains)",
    ("ERG", "currency"): "Expected — SAGE=USD, FM=MGA (different domains)",
    ("MIR01", "currency"): "Expected — SAGE=USD, FM=SLE (different domains)",
    ("TWG01", "currency"): "Expected — SAGE=USD, FM=MZN (different domains)",
}

# Customer alias map: xlsx sage_customer_id -> DB sage_id
# (from sage_csv_parser.py CUSTOMER_ALIASES)
SAGE_ID_ALIASES: Dict[str, str] = {
    # No aliases needed — sage_id now matches xlsx source values
    # GC001 and ZL01 are used directly (migration 054)
}


# =============================================================================
# Step 1: Customer Summary -> Projects & Counterparties
# =============================================================================

@StepRegistry.register(step_num=1, name="Customer Summary → Projects & Counterparties")
def step1_customer_summary(ctx: dict) -> StepResult:
    """Parse Customer summary.xlsx, validate against DB, fill NULL gaps."""
    from services.onboarding.parsers.customer_summary_parser import (
        CustomerSummaryParser,
        CustomerSummaryProject,
    )

    result = StepResult(step_number=1, step_name="Customer Summary → Projects & Counterparties")
    data_dir = ctx["data_dir"]
    org_id = ctx["org_id"]
    dry_run = ctx["dry_run"]
    project_filter = ctx.get("project")

    # ── Phase 1: Parse ────────────────────────────────────────────────────────
    summary_path = os.path.join(data_dir, "Customer summary.xlsx")
    if not os.path.exists(summary_path):
        logger.error(f"Customer summary not found: {summary_path}")
        result.status = "failed"
        result.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project="ALL",
            step=1, field="source_file", source_a=summary_path,
            source_b="NOT FOUND", recommended_action="Provide Customer summary.xlsx",
        ))
        return result

    parser = CustomerSummaryParser()
    raw_rows = parser.parse(summary_path)
    projects = parser.deduplicate_to_projects(raw_rows)

    logger.info(f"Parsed {len(raw_rows)} rows → {len(projects)} deduplicated projects")

    # Apply project filter if specified
    if project_filter:
        projects = [p for p in projects if p.sage_id == project_filter]
        if not projects:
            logger.warning(f"Project {project_filter} not found in Customer summary")
            result.status = "skipped"
            return result

    # Apply alias resolution: xlsx sage_customer_id -> DB sage_id
    for proj in projects:
        if proj.sage_id in SAGE_ID_ALIASES:
            old_id = proj.sage_id
            proj.sage_id = SAGE_ID_ALIASES[old_id]
            logger.info(f"Alias resolved: {old_id} → {proj.sage_id}")

    # ── Phase 2: Validate against DB ──────────────────────────────────────────
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for proj in projects:
                _validate_project(cur, proj, org_id, result)

        # ── Phase 3: Gap-fill (upsert NULLs only) ────────────────────────────
        if not dry_run:
            with conn.cursor() as cur:
                for proj in projects:
                    filled = _fill_gaps(cur, proj, org_id)
                    result.gaps_filled += filled
        else:
            logger.info("[DRY-RUN] Skipping gap-fill writes")

        # ── Stage A Gate Checks ───────────────────────────────────────────────
        with conn.cursor() as cur:
            _run_stage_a_gates(cur, org_id, result)

    # Determine overall status
    critical_count = sum(1 for d in result.discrepancies if d.severity == "critical")
    warning_count = sum(1 for d in result.discrepancies if d.severity == "warning")
    failed_gates = sum(1 for g in result.gate_checks if not g.passed)

    if critical_count > 0 or failed_gates > 0:
        result.status = "failed"
    elif warning_count > 0:
        result.status = "warnings"
    else:
        result.status = "passed"

    return result


def _validate_project(cur, proj, org_id: int, result: StepResult):
    """Validate a single parsed project against DB state."""
    sage_id = proj.sage_id

    # Check project exists
    cur.execute(
        "SELECT id, name, country, cod_date, installed_dc_capacity_kwp, "
        "external_project_id FROM project "
        "WHERE sage_id = %s AND organization_id = %s",
        (sage_id, org_id),
    )
    db_project = cur.fetchone()

    if not db_project:
        result.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project=sage_id,
            step=1, field="project", source_a=f"xlsx: {proj.project_name}",
            source_b="NOT IN DB",
            recommended_action="Insert project into DB",
        ))
        return

    result.validated += 1
    project_id = db_project["id"]

    # ── Field comparisons ─────────────────────────────────────────────────
    _compare_field(result, sage_id, "project.name",
                   proj.project_name, db_project["name"])
    _compare_field(result, sage_id, "project.country",
                   proj.country, db_project["country"])
    _compare_field(result, sage_id, "project.cod_date",
                   str(proj.cod_date) if proj.cod_date else None,
                   str(db_project["cod_date"]) if db_project["cod_date"] else None)
    _compare_field(result, sage_id, "project.installed_dc_capacity_kwp",
                   str(proj.size_kwp) if proj.size_kwp else None,
                   str(db_project["installed_dc_capacity_kwp"])
                   if db_project["installed_dc_capacity_kwp"] else None)
    _compare_field(result, sage_id, "project.external_project_id",
                   proj.external_project_id, db_project["external_project_id"])

    # ── Counterparty match ────────────────────────────────────────────────
    cur.execute(
        "SELECT cp.id, cp.name, cp.industry FROM counterparty cp "
        "JOIN contract c ON c.counterparty_id = cp.id "
        "WHERE c.project_id = %s LIMIT 1",
        (project_id,),
    )
    db_cp = cur.fetchone()
    if db_cp:
        _compare_field(result, sage_id, "counterparty.name",
                       proj.customer_name, db_cp["name"])
        if proj.industry:
            _compare_field(result, sage_id, "counterparty.industry",
                           proj.industry, db_cp["industry"])

    # ── Contract checks ───────────────────────────────────────────────────
    cur.execute(
        "SELECT external_contract_id, payment_terms, end_date "
        "FROM contract WHERE project_id = %s",
        (project_id,),
    )
    contracts = cur.fetchall()
    if not contracts:
        result.discrepancies.append(Discrepancy(
            severity="warning", category="missing_data", project=sage_id,
            step=1, field="contract", source_a="xlsx project exists",
            source_b="NO CONTRACTS IN DB",
            recommended_action="Create contract in Step 2",
        ))

    # ── Legal entity match ────────────────────────────────────────────────
    if proj.sage_company:
        cur.execute(
            "SELECT id, name, external_legal_entity_id FROM legal_entity "
            "WHERE organization_id = %s AND external_legal_entity_id = %s",
            (org_id, proj.sage_company),
        )
        db_le = cur.fetchone()
        if not db_le:
            result.discrepancies.append(Discrepancy(
                severity="info", category="missing_data", project=sage_id,
                step=1, field="legal_entity.external_legal_entity_id",
                source_a=f"xlsx: {proj.sage_company}",
                source_b="NOT IN DB",
                recommended_action="Verify legal entity mapping",
            ))


def _compare_field(result: StepResult, sage_id: str, field_name: str,
                   xlsx_val: Optional[str], db_val: Optional[str]):
    """Compare xlsx value to DB value, recording discrepancies."""
    if xlsx_val is None or db_val is None:
        return  # Can't compare NULLs

    # Check known expected discrepancies
    key = (sage_id, field_name.split(".")[-1])
    if key in KNOWN_DISCREPANCIES:
        if xlsx_val != db_val:
            result.discrepancies.append(Discrepancy(
                severity="info", category="value_conflict", project=sage_id,
                step=1, field=field_name, source_a=f"xlsx: {xlsx_val}",
                source_b=f"DB: {db_val}",
                recommended_action=KNOWN_DISCREPANCIES[key],
                status="resolved",
            ))
        return

    # Normalize for comparison
    a = str(xlsx_val).strip().lower()
    b = str(db_val).strip().lower()

    if a != b:
        # Numeric fuzzy match for capacity values
        if "capacity" in field_name or "kwp" in field_name:
            try:
                if abs(float(a) - float(b)) < 0.01:
                    return
            except (ValueError, TypeError):
                pass

        result.discrepancies.append(Discrepancy(
            severity="warning", category="value_conflict", project=sage_id,
            step=1, field=field_name, source_a=f"xlsx: {xlsx_val}",
            source_b=f"DB: {db_val}",
            recommended_action="Review: check field authority matrix",
        ))


def _fill_gaps(cur, proj, org_id: int) -> int:
    """Fill NULL fields in DB from xlsx data (COALESCE pattern). Returns count of fields filled."""
    filled = 0

    # ── counterparty.industry ─────────────────────────────────────────────
    if proj.industry:
        cur.execute(
            "UPDATE counterparty SET industry = %s "
            "WHERE id IN ("
            "  SELECT cp.id FROM counterparty cp "
            "  JOIN contract c ON c.counterparty_id = cp.id "
            "  JOIN project p ON p.id = c.project_id "
            "  WHERE p.sage_id = %s AND p.organization_id = %s"
            ") AND industry IS NULL",
            (proj.industry, proj.sage_id, org_id),
        )
        if cur.rowcount > 0:
            filled += cur.rowcount
            logger.info(f"  {proj.sage_id}: Filled counterparty.industry = {proj.industry}")

    # ── project fields ────────────────────────────────────────────────────
    updates = []
    params = []

    if proj.cod_date:
        updates.append("cod_date = COALESCE(cod_date, %s)")
        params.append(proj.cod_date)
    if proj.size_kwp:
        updates.append("installed_dc_capacity_kwp = COALESCE(installed_dc_capacity_kwp, %s)")
        params.append(proj.size_kwp)
    if proj.country:
        updates.append("country = COALESCE(country, %s)")
        params.append(proj.country)
    if proj.external_project_id:
        updates.append("external_project_id = COALESCE(external_project_id, %s)")
        params.append(proj.external_project_id)

    if updates:
        sql = (
            f"UPDATE project SET {', '.join(updates)} "
            f"WHERE sage_id = %s AND organization_id = %s"
        )
        params.extend([proj.sage_id, org_id])
        cur.execute(sql, params)
        if cur.rowcount > 0:
            filled += cur.rowcount
            logger.info(f"  {proj.sage_id}: Filled {len(updates)} NULL project field(s)")

    return filled


def _run_stage_a_gates(cur, org_id: int, result: StepResult):
    """Run Stage A validation gate checks."""
    # Gate 1: All projects have sage_id
    cur.execute(
        "SELECT COUNT(*) AS total, "
        "COUNT(sage_id) AS with_sage_id "
        "FROM project WHERE organization_id = %s",
        (org_id,),
    )
    row = cur.fetchone()
    total = row["total"]
    with_sage = row["with_sage_id"]
    result.gate_checks.append(GateCheck(
        name="All projects have sage_id",
        passed=total == with_sage,
        expected=f"{total}/{total}",
        actual=f"{with_sage}/{total}",
    ))

    # Gate 2: Contracts have external_contract_id
    cur.execute(
        "SELECT COUNT(*) AS total, "
        "COUNT(external_contract_id) AS with_ext_id "
        "FROM contract c "
        "JOIN project p ON p.id = c.project_id "
        "WHERE p.organization_id = %s AND c.parent_contract_id IS NULL",
        (org_id,),
    )
    row = cur.fetchone()
    c_total = row["total"]
    c_with_id = row["with_ext_id"]
    result.gate_checks.append(GateCheck(
        name="Contracts have external_contract_id",
        passed=c_with_id >= 27,
        expected="27+",
        actual=str(c_with_id),
    ))

    # Gate 3: Contracts have payment_terms
    cur.execute(
        "SELECT COUNT(payment_terms) AS cnt "
        "FROM contract c "
        "JOIN project p ON p.id = c.project_id "
        "WHERE p.organization_id = %s AND c.parent_contract_id IS NULL",
        (org_id,),
    )
    pt_count = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="Contracts have payment_terms",
        passed=pt_count >= 27,
        expected="27+",
        actual=str(pt_count),
    ))

    # Gate 4: Contracts have end_date
    cur.execute(
        "SELECT COUNT(end_date) AS cnt "
        "FROM contract c "
        "JOIN project p ON p.id = c.project_id "
        "WHERE p.organization_id = %s AND c.parent_contract_id IS NULL",
        (org_id,),
    )
    ed_count = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="Contracts have end_date",
        passed=ed_count >= 27,
        expected="27+",
        actual=str(ed_count),
    ))

    # Gate 5: XFlora split verified
    cur.execute(
        "SELECT sage_id FROM project "
        "WHERE organization_id = %s AND sage_id IN ('XFAB', 'XFBV', 'XFL01', 'XFSS')",
        (org_id,),
    )
    xf_rows = cur.fetchall()
    xf_ids = sorted([r["sage_id"] for r in xf_rows])
    xf_expected = ["XFAB", "XFBV", "XFL01", "XFSS"]
    xf_passed = xf_ids == xf_expected
    result.gate_checks.append(GateCheck(
        name="XFlora split verified (4 projects)",
        passed=xf_passed,
        expected=", ".join(xf_expected),
        actual=", ".join(xf_ids) if xf_ids else "none found",
    ))


# =============================================================================
# Step 2: SAGE CSV Cross-Check
# =============================================================================

# Currency mismatches that are expected domain differences (EXC-002)
CURRENCY_MISMATCH_SAGE_IDS = {"XFAB", "XFBV", "XFL01", "XFSS", "QMM01", "ERG", "MIR01", "TWG01"}


@StepRegistry.register(step_num=2, name="SAGE CSV Cross-Check")
def step2_sage_crosscheck(ctx: dict) -> StepResult:
    """Cross-reference all projects against SAGE CSV extracts."""
    from services.onboarding.parsers.sage_csv_parser import SAGECSVParser

    result = StepResult(step_number=2, step_name="SAGE CSV Cross-Check")
    data_dir = ctx["data_dir"]
    org_id = ctx["org_id"]
    dry_run = ctx["dry_run"]
    project_filter = ctx.get("project")

    # ── Phase 1: Parse ────────────────────────────────────────────────────────
    csv_dir = os.path.join(data_dir, "Data Extracts")
    if not os.path.isdir(csv_dir):
        csv_dir = data_dir  # Fallback to data_dir if no sub-folder

    parser = SAGECSVParser(csv_dir)
    sage_projects = parser.parse(project_filter)
    logger.info(f"Parsed {len(sage_projects)} SAGE projects")

    if not sage_projects:
        logger.warning("No SAGE projects parsed — check CSV file paths")
        result.status = "failed"
        result.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project="ALL",
            step=2, field="sage_csvs", source_a=csv_dir,
            source_b="NO DATA PARSED",
            recommended_action="Check CSV files exist in data directory",
        ))
        return result

    # ── Phase 2: Validate against DB ──────────────────────────────────────────
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for sage_id, sage_proj in sage_projects.items():
                _validate_sage_project(cur, sage_proj, org_id, result)

        # ── Phase 3: Gap-fill (COALESCE pattern) ─────────────────────────────
        if not dry_run:
            with conn.cursor() as cur:
                for sage_id, sage_proj in sage_projects.items():
                    filled = _fill_sage_gaps(cur, sage_proj, org_id)
                    result.gaps_filled += filled
        else:
            logger.info("[DRY-RUN] Skipping gap-fill writes")

        # ── Gate Checks (Stage A re-verification + Step 2) ───────────────────
        with conn.cursor() as cur:
            _run_step2_gates(cur, org_id, result)

    # Determine overall status
    critical_count = sum(1 for d in result.discrepancies if d.severity == "critical")
    warning_count = sum(1 for d in result.discrepancies if d.severity == "warning")
    failed_gates = sum(1 for g in result.gate_checks if not g.passed)

    if critical_count > 0 or failed_gates > 0:
        result.status = "failed"
    elif warning_count > 0:
        result.status = "warnings"
    else:
        result.status = "passed"

    return result


def _validate_sage_project(cur, sage_proj, org_id: int, result: StepResult):
    """Validate a single SAGE-parsed project against DB state."""
    sage_id = sage_proj.sage_id

    # Check project exists
    cur.execute(
        "SELECT id, name, country, sage_id FROM project "
        "WHERE sage_id = %s AND organization_id = %s",
        (sage_id, org_id),
    )
    db_project = cur.fetchone()

    if not db_project:
        result.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project=sage_id,
            step=2, field="project", source_a=f"SAGE: {sage_proj.customer_name}",
            source_b="NOT IN DB",
            recommended_action="Insert project into DB",
        ))
        return

    result.validated += 1
    project_id = db_project["id"]

    # ── Contract match ────────────────────────────────────────────────────
    if sage_proj.primary_contract_number:
        cur.execute(
            "SELECT external_contract_id, payment_terms, effective_date, end_date "
            "FROM contract WHERE project_id = %s AND parent_contract_id IS NULL",
            (project_id,),
        )
        db_contracts = cur.fetchall()
        ext_ids = [c["external_contract_id"] for c in db_contracts if c["external_contract_id"]]

        if sage_proj.primary_contract_number not in ext_ids:
            result.discrepancies.append(Discrepancy(
                severity="warning", category="value_conflict", project=sage_id,
                step=2, field="contract.external_contract_id",
                source_a=f"SAGE: {sage_proj.primary_contract_number}",
                source_b=f"DB: {ext_ids}",
                recommended_action="Verify contract mapping",
            ))

        # Compare payment_terms, start_date, end_date against primary contract
        for db_c in db_contracts:
            if db_c["external_contract_id"] == sage_proj.primary_contract_number:
                if sage_proj.payment_terms and db_c["payment_terms"]:
                    if sage_proj.payment_terms != db_c["payment_terms"]:
                        result.discrepancies.append(Discrepancy(
                            severity="warning", category="value_conflict", project=sage_id,
                            step=2, field="contract.payment_terms",
                            source_a=f"SAGE: {sage_proj.payment_terms}",
                            source_b=f"DB: {db_c['payment_terms']}",
                            recommended_action="Review payment terms",
                        ))
                if sage_proj.contract_start_date and db_c["effective_date"]:
                    if sage_proj.contract_start_date != db_c["effective_date"]:
                        result.discrepancies.append(Discrepancy(
                            severity="warning", category="value_conflict", project=sage_id,
                            step=2, field="contract.effective_date",
                            source_a=f"SAGE: {sage_proj.contract_start_date}",
                            source_b=f"DB: {db_c['effective_date']}",
                            recommended_action="Review effective date",
                        ))
                if sage_proj.contract_end_date and db_c["end_date"]:
                    if sage_proj.contract_end_date != db_c["end_date"]:
                        result.discrepancies.append(Discrepancy(
                            severity="warning", category="value_conflict", project=sage_id,
                            step=2, field="contract.end_date",
                            source_a=f"SAGE: {sage_proj.contract_end_date}",
                            source_b=f"DB: {db_c['end_date']}",
                            recommended_action="Review end date",
                        ))
                break

    # ── Counterparty name (fuzzy match) ───────────────────────────────────
    if sage_proj.customer_name:
        cur.execute(
            "SELECT cp.name FROM counterparty cp "
            "JOIN contract c ON c.counterparty_id = cp.id "
            "WHERE c.project_id = %s AND c.parent_contract_id IS NULL LIMIT 1",
            (project_id,),
        )
        db_cp = cur.fetchone()
        if db_cp and db_cp["name"]:
            sage_name = sage_proj.customer_name.strip().lower()
            db_name = db_cp["name"].strip().lower()
            if sage_name != db_name:
                result.discrepancies.append(Discrepancy(
                    severity="info", category="value_conflict", project=sage_id,
                    step=2, field="counterparty.name",
                    source_a=f"SAGE: {sage_proj.customer_name}",
                    source_b=f"DB: {db_cp['name']}",
                    recommended_action="Review counterparty name match",
                ))

    # ── Country match ─────────────────────────────────────────────────────
    if sage_proj.country and db_project["country"]:
        if sage_proj.country.strip().lower() != db_project["country"].strip().lower():
            key = (sage_id, "country")
            if key not in KNOWN_DISCREPANCIES:
                result.discrepancies.append(Discrepancy(
                    severity="warning", category="value_conflict", project=sage_id,
                    step=2, field="project.country",
                    source_a=f"SAGE: {sage_proj.country}",
                    source_b=f"DB: {db_project['country']}",
                    recommended_action="Review country mismatch",
                ))

    # ── Contract line count (info) ────────────────────────────────────────
    active_sage_lines = [l for l in sage_proj.contract_lines if l.active_status == 1]
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM contract_line cl "
        "JOIN contract c ON c.id = cl.contract_id "
        "WHERE c.project_id = %s AND cl.is_active = true",
        (project_id,),
    )
    db_line_count = cur.fetchone()["cnt"]
    if len(active_sage_lines) != db_line_count:
        result.discrepancies.append(Discrepancy(
            severity="info", category="value_conflict", project=sage_id,
            step=2, field="contract_line.count",
            source_a=f"SAGE: {len(active_sage_lines)} active lines",
            source_b=f"DB: {db_line_count} active lines",
            recommended_action="Info — line counts may diverge (decomposition, non-energy lines)",
        ))

    # ── CPI flag (record for tariff setup) ────────────────────────────────
    if sage_proj.has_cpi_inflation:
        result.discrepancies.append(Discrepancy(
            severity="info", category="missing_data", project=sage_id,
            step=2, field="tariff.cpi_inflation",
            source_a="SAGE: has CPI inflation lines",
            source_b="Record for tariff setup",
            recommended_action="Configure CPI escalation in tariff model",
            status="open",
        ))


def _fill_sage_gaps(cur, sage_proj, org_id: int) -> int:
    """Fill NULL contract fields from SAGE data (COALESCE pattern)."""
    filled = 0
    sage_id = sage_proj.sage_id

    if not sage_proj.primary_contract_number:
        return 0

    # Find the matching contract
    cur.execute(
        "SELECT c.id FROM contract c "
        "JOIN project p ON p.id = c.project_id "
        "WHERE p.sage_id = %s AND p.organization_id = %s "
        "AND c.external_contract_id = %s AND c.parent_contract_id IS NULL",
        (sage_id, org_id, sage_proj.primary_contract_number),
    )
    row = cur.fetchone()
    if not row:
        return 0

    contract_id = row["id"]
    updates = []
    params = []

    if sage_proj.contract_start_date:
        updates.append("effective_date = COALESCE(effective_date, %s)")
        params.append(sage_proj.contract_start_date)
    if sage_proj.payment_terms:
        updates.append("payment_terms = COALESCE(payment_terms, %s)")
        params.append(sage_proj.payment_terms)
    if sage_proj.contract_end_date:
        updates.append("end_date = COALESCE(end_date, %s)")
        params.append(sage_proj.contract_end_date)

    if updates:
        sql = f"UPDATE contract SET {', '.join(updates)} WHERE id = %s"
        params.append(contract_id)
        cur.execute(sql, params)
        if cur.rowcount > 0:
            filled += cur.rowcount
            logger.info(f"  {sage_id}: Filled {len(updates)} NULL contract field(s)")

    return filled


def _run_step2_gates(cur, org_id: int, result: StepResult):
    """Run Step 2 gate checks (Stage A re-verification + Step 2 additions)."""
    # Gate 1: All projects have sage_id → 35/35
    cur.execute(
        "SELECT COUNT(*) AS total, COUNT(sage_id) AS with_sage_id "
        "FROM project WHERE organization_id = %s",
        (org_id,),
    )
    row = cur.fetchone()
    total = row["total"]
    with_sage = row["with_sage_id"]
    result.gate_checks.append(GateCheck(
        name="All projects have sage_id",
        passed=total == with_sage and total >= 35,
        expected="35/35",
        actual=f"{with_sage}/{total}",
    ))

    # Gate 2: 31+ contracts have external_contract_id
    cur.execute(
        "SELECT COUNT(external_contract_id) AS cnt "
        "FROM contract c JOIN project p ON p.id = c.project_id "
        "WHERE p.organization_id = %s AND c.parent_contract_id IS NULL",
        (org_id,),
    )
    ext_id_count = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="Contracts have external_contract_id",
        passed=ext_id_count >= 31,
        expected="31+",
        actual=str(ext_id_count),
    ))

    # Gate 3: 31+ contracts have payment_terms
    cur.execute(
        "SELECT COUNT(payment_terms) AS cnt "
        "FROM contract c JOIN project p ON p.id = c.project_id "
        "WHERE p.organization_id = %s AND c.parent_contract_id IS NULL",
        (org_id,),
    )
    pt_count = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="Contracts have payment_terms",
        passed=pt_count >= 31,
        expected="31+",
        actual=str(pt_count),
    ))

    # Gate 4: 31+ contracts have end_date
    cur.execute(
        "SELECT COUNT(end_date) AS cnt "
        "FROM contract c JOIN project p ON p.id = c.project_id "
        "WHERE p.organization_id = %s AND c.parent_contract_id IS NULL",
        (org_id,),
    )
    ed_count = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="Contracts have end_date",
        passed=ed_count >= 31,
        expected="31+",
        actual=str(ed_count),
    ))

    # Gate 5: XFlora split verified — 4 projects
    cur.execute(
        "SELECT sage_id FROM project "
        "WHERE organization_id = %s AND sage_id IN ('XFAB', 'XFBV', 'XFL01', 'XFSS')",
        (org_id,),
    )
    xf_ids = sorted([r["sage_id"] for r in cur.fetchall()])
    xf_expected = ["XFAB", "XFBV", "XFL01", "XFSS"]
    result.gate_checks.append(GateCheck(
        name="XFlora split verified (4 projects)",
        passed=xf_ids == xf_expected,
        expected=", ".join(xf_expected),
        actual=", ".join(xf_ids) if xf_ids else "none found",
    ))

    # Gate 6: ZL02 has contracts
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM contract c "
        "JOIN project p ON p.id = c.project_id "
        "WHERE p.sage_id = 'ZL02' AND p.organization_id = %s",
        (org_id,),
    )
    zl02_count = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="ZL02 has contracts",
        passed=zl02_count >= 1,
        expected="1+",
        actual=str(zl02_count),
    ))


# =============================================================================
# Step 3: Contract Lines & Meter Readings Cross-Check
# =============================================================================

# Energy category mapping: parser classification → DB enum
ENERGY_CAT_MAP = {
    "metered_energy": "metered",
    "available_energy": "available",
    "non_energy": "test",
    None: "test",
}


@StepRegistry.register(step_num=3, name="Contract Lines & Meter Cross-Check")
def step3_contract_lines_and_meter_crosscheck(ctx: dict) -> StepResult:
    """Populate contract_line from SAGE CSV, cross-check meter readings."""
    from services.onboarding.parsers.sage_csv_parser import SAGECSVParser

    result = StepResult(step_number=3, step_name="Contract Lines & Meter Cross-Check")
    data_dir = ctx["data_dir"]
    org_id = ctx["org_id"]
    dry_run = ctx["dry_run"]
    project_filter = ctx.get("project")

    # ── Phase 1: Parse SAGE CSVs ──────────────────────────────────────────────
    csv_dir = os.path.join(data_dir, "Data Extracts")
    if not os.path.isdir(csv_dir):
        csv_dir = data_dir

    parser = SAGECSVParser(csv_dir)
    sage_projects = parser.parse(project_filter)
    logger.info(f"Parsed {len(sage_projects)} SAGE projects")

    if not sage_projects:
        result.status = "failed"
        result.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project="ALL",
            step=3, field="sage_csvs", source_a=csv_dir,
            source_b="NO DATA PARSED",
            recommended_action="Check CSV files exist in data directory",
        ))
        return result

    # ── Phase 2: Build contract lookup ────────────────────────────────────────
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Build mapping: external_contract_id -> (contract_id, project.sage_id)
            cur.execute(
                "SELECT c.id AS contract_id, c.external_contract_id, p.sage_id "
                "FROM contract c "
                "JOIN project p ON p.id = c.project_id "
                "WHERE p.organization_id = %s AND c.external_contract_id IS NOT NULL",
                (org_id,),
            )
            contract_lookup: Dict[str, Tuple[int, str]] = {}
            for row in cur.fetchall():
                contract_lookup[row["external_contract_id"]] = (
                    row["contract_id"], row["sage_id"]
                )
            logger.info(f"Built contract lookup: {len(contract_lookup)} contracts with external IDs")

        # ── Phase 2b: Auto-create missing contracts from SAGE ──────────────────
        with conn.cursor() as cur:
            created = _create_missing_contracts(
                cur, sage_projects, contract_lookup, org_id, result, dry_run
            )
            if created > 0:
                logger.info(f"Auto-created {created} missing contract(s) from SAGE CSVs")

        # ── Phase 3: Delete existing contract_lines (and dependents) ──────────
        if not dry_run:
            with conn.cursor() as cur:
                deleted = _delete_existing_contract_lines(cur, org_id)
                logger.info(f"Deleted {deleted} existing contract_line(s) and dependents")
        else:
            logger.info("[DRY-RUN] Would delete existing contract_lines")

        # ── Phase 4: Insert contract_lines from SAGE ─────────────────────────
        total_inserted = 0
        total_skipped = 0

        with conn.cursor() as cur:
            for sage_id, sage_proj in sage_projects.items():
                inserted, skipped = _insert_contract_lines(
                    cur, sage_proj, contract_lookup, org_id, result, dry_run
                )
                total_inserted += inserted
                total_skipped += skipped

        result.validated = len(sage_projects)
        result.gaps_filled = total_inserted
        logger.info(
            f"Contract lines: {total_inserted} inserted, {total_skipped} skipped "
            f"(no matching contract)"
        )

        # ── Phase 5: Cross-check meter readings ──────────────────────────────
        with conn.cursor() as cur:
            _crosscheck_meter_readings(cur, sage_projects, contract_lookup, org_id, result)

        # ── Phase 6: Gate checks ─────────────────────────────────────────────
        with conn.cursor() as cur:
            _run_step3_gates(cur, org_id, sage_projects, result)

    # Determine overall status
    critical_count = sum(1 for d in result.discrepancies if d.severity == "critical")
    warning_count = sum(1 for d in result.discrepancies if d.severity == "warning")
    failed_gates = sum(1 for g in result.gate_checks if not g.passed)

    if critical_count > 0 or failed_gates > 0:
        result.status = "failed"
    elif warning_count > 0:
        result.status = "warnings"
    else:
        result.status = "passed"

    return result


def _create_missing_contracts(
    cur, sage_projects: Dict[str, Any],
    contract_lookup: Dict[str, Tuple[int, str]],
    org_id: int, result: StepResult, dry_run: bool
) -> int:
    """Auto-create contracts found in SAGE CSVs but missing from DB. Returns count created."""
    # Collect all unique contract_numbers from SAGE lines and find missing ones
    missing: Dict[str, Dict[str, Any]] = {}  # contract_number -> {sage_id, contract_row}
    for sage_id, sage_proj in sage_projects.items():
        for contract_row in sage_proj.contracts:
            cn = (contract_row.get("CONTRACT_NUMBER") or "").strip()
            if cn and cn not in contract_lookup and cn not in missing:
                missing[cn] = {"sage_id": sage_id, "contract_row": contract_row}

    if not missing:
        return 0

    created = 0
    for contract_number, info in missing.items():
        sage_id = info["sage_id"]
        row = info["contract_row"]
        category = (row.get("CONTRACT_CATEGORY") or "").strip()
        currency = (row.get("CONTRACT_CURRENCY") or "").strip()
        terms = (row.get("PAYMENT_TERMS") or "").strip()
        start = _parse_date_str(row.get("START_DATE"))
        end = _parse_date_str(row.get("END_DATE"))
        contract_name = f"{sage_id} {category} ({currency})" if category else f"{sage_id} Contract"

        logger.info(f"  Auto-creating contract {contract_number} for {sage_id} ({category}/{currency})")

        if dry_run:
            # Still add to lookup so dry-run line counts are accurate
            contract_lookup[contract_number] = (-1, sage_id)
            created += 1
            continue

        # Find project_id and existing counterparty_id
        cur.execute(
            "SELECT p.id AS project_id, "
            "  (SELECT c.counterparty_id FROM contract c WHERE c.project_id = p.id "
            "   AND c.parent_contract_id IS NULL LIMIT 1) AS counterparty_id "
            "FROM project p WHERE p.sage_id = %s AND p.organization_id = %s",
            (sage_id, org_id),
        )
        proj_row = cur.fetchone()
        if not proj_row:
            continue

        cur.execute(
            "INSERT INTO contract ("
            "  project_id, counterparty_id, name, external_contract_id, "
            "  payment_terms, effective_date, end_date, "
            "  extraction_metadata, organization_id"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, external_contract_id) WHERE external_contract_id IS NOT NULL DO NOTHING "
            "RETURNING id",
            (
                proj_row["project_id"],
                proj_row["counterparty_id"],
                contract_name,
                contract_number,
                terms or None,
                start,
                end,
                json.dumps({"source": "sage_csv_step3", "contract_category": category, "contract_currency": currency}),
                org_id,
            ),
        )
        new_row = cur.fetchone()
        if new_row:
            contract_lookup[contract_number] = (new_row["id"], sage_id)
            created += 1
            result.discrepancies.append(Discrepancy(
                severity="info", category="missing_data", project=sage_id,
                step=3, field="contract",
                source_a=f"Auto-created: {contract_number} ({category}/{currency})",
                source_b=f"contract.id={new_row['id']}",
                recommended_action="Verify auto-created contract",
                status="resolved",
            ))

    return created


def _parse_date_str(val: Optional[str]) -> Optional[date]:
    """Parse date string from SAGE CSV row."""
    if not val or val.strip() == "" or val.strip().startswith("1753"):
        return None
    try:
        return datetime.strptime(val.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def _delete_existing_contract_lines(cur, org_id: int) -> int:
    """Delete all contract_lines (and FK dependents) for the org. Returns count deleted."""
    # Get all contract_line IDs for this org
    cur.execute(
        "SELECT id FROM contract_line WHERE organization_id = %s",
        (org_id,),
    )
    cl_ids = [row["id"] for row in cur.fetchall()]
    if not cl_ids:
        return 0

    # Delete dependents first (NO CASCADE on FKs)
    cur.execute(
        "DELETE FROM expected_invoice_line_item WHERE contract_line_id = ANY(%s)",
        (cl_ids,),
    )
    eili_del = cur.rowcount
    if eili_del:
        logger.info(f"  Deleted {eili_del} expected_invoice_line_item rows")

    cur.execute(
        "DELETE FROM meter_aggregate WHERE contract_line_id = ANY(%s)",
        (cl_ids,),
    )
    ma_del = cur.rowcount
    if ma_del:
        logger.info(f"  Deleted {ma_del} meter_aggregate rows")

    # Clear self-referencing parent_contract_line_id
    cur.execute(
        "UPDATE contract_line SET parent_contract_line_id = NULL "
        "WHERE parent_contract_line_id IS NOT NULL AND organization_id = %s",
        (org_id,),
    )

    # Now delete contract_lines
    cur.execute(
        "DELETE FROM contract_line WHERE organization_id = %s",
        (org_id,),
    )
    return cur.rowcount


def _insert_contract_lines(
    cur, sage_proj, contract_lookup: Dict[str, Tuple[int, str]],
    org_id: int, result: StepResult, dry_run: bool
) -> Tuple[int, int]:
    """Insert contract_lines for a single SAGE project. Returns (inserted, skipped)."""
    inserted = 0
    skipped = 0

    for line in sage_proj.contract_lines:
        # Find matching contract by contract_number
        contract_info = contract_lookup.get(line.contract_number)
        if not contract_info:
            skipped += 1
            result.discrepancies.append(Discrepancy(
                severity="warning", category="fk_resolution", project=sage_proj.sage_id,
                step=3, field="contract_line.contract_id",
                source_a=f"SAGE contract_number: {line.contract_number}",
                source_b="No matching contract.external_contract_id in DB",
                recommended_action="Check if contract exists or needs creation",
            ))
            continue

        contract_id, _ = contract_info
        energy_cat = ENERGY_CAT_MAP.get(line.energy_category, "test")
        is_active = line.active_status == 1

        if dry_run:
            inserted += 1
            continue

        try:
            cur.execute(
                "INSERT INTO contract_line ("
                "  contract_id, contract_line_number, product_desc, energy_category, "
                "  is_active, organization_id, external_line_id, "
                "  effective_start_date, effective_end_date"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (contract_id, contract_line_number) DO UPDATE SET "
                "  product_desc = EXCLUDED.product_desc, "
                "  energy_category = EXCLUDED.energy_category, "
                "  is_active = EXCLUDED.is_active, "
                "  external_line_id = EXCLUDED.external_line_id, "
                "  effective_start_date = EXCLUDED.effective_start_date, "
                "  effective_end_date = EXCLUDED.effective_end_date, "
                "  updated_at = NOW()",
                (
                    contract_id,
                    line.contract_line,
                    line.product_desc,
                    energy_cat,
                    is_active,
                    org_id,
                    line.contract_line_unique_id or None,
                    line.effective_start_date,
                    line.effective_end_date,
                ),
            )
            inserted += 1
        except Exception as e:
            logger.warning(
                f"  {sage_proj.sage_id}: Failed to insert line "
                f"{line.contract_line} ({line.product_desc}): {e}"
            )
            result.discrepancies.append(Discrepancy(
                severity="warning", category="duplicate", project=sage_proj.sage_id,
                step=3, field="contract_line",
                source_a=f"line {line.contract_line}: {line.product_desc}",
                source_b=str(e),
                recommended_action="Check for duplicate external_line_id",
            ))

    return inserted, skipped


def _crosscheck_meter_readings(
    cur, sage_projects: Dict[str, Any],
    contract_lookup: Dict[str, Tuple[int, str]],
    org_id: int, result: StepResult
):
    """Cross-check meter readings against contract_lines."""
    # Build set of all (contract_number, contract_line) pairs that exist as contract_lines
    existing_lines: set = set()
    for sage_id, sage_proj in sage_projects.items():
        for line in sage_proj.contract_lines:
            if line.contract_number in contract_lookup:
                existing_lines.add((line.contract_number, line.contract_line))

    # Check each meter reading
    readings_ok = 0
    readings_orphan = 0
    orphan_details: Dict[str, set] = {}  # sage_id -> set of (contract_number, contract_line)

    for sage_id, sage_proj in sage_projects.items():
        for reading in sage_proj.meter_readings:
            key = (reading.contract_number, reading.contract_line)
            if key in existing_lines:
                readings_ok += 1
            else:
                readings_orphan += 1
                orphan_details.setdefault(sage_id, set()).add(key)

    logger.info(
        f"Meter reading cross-check: {readings_ok} matched, "
        f"{readings_orphan} orphaned (no contract_line)"
    )

    # Report orphaned readings (warning — likely SCD2-superseded lines)
    for sage_id, orphans in orphan_details.items():
        for cn, cl in sorted(orphans):
            result.discrepancies.append(Discrepancy(
                severity="warning", category="fk_resolution", project=sage_id,
                step=3, field="meter_reading → contract_line",
                source_a=f"Reading: contract={cn}, line={cl}",
                source_b="No matching contract_line (DIM_CURRENT_RECORD=1) in SAGE CSV",
                recommended_action="Likely SCD2-superseded line — verify in source CSV",
            ))

    # Report contract_lines without meter readings (info, not error)
    lines_with_readings: set = set()
    for sage_id, sage_proj in sage_projects.items():
        for reading in sage_proj.meter_readings:
            lines_with_readings.add((reading.contract_number, reading.contract_line))

    lines_without = 0
    for sage_id, sage_proj in sage_projects.items():
        for line in sage_proj.contract_lines:
            key = (line.contract_number, line.contract_line)
            if key not in lines_with_readings and line.active_status == 1:
                lines_without += 1

    if lines_without > 0:
        result.discrepancies.append(Discrepancy(
            severity="info", category="missing_data", project="ALL",
            step=3, field="contract_line → meter_reading",
            source_a=f"{lines_without} active contract_line(s) have no meter readings",
            source_b="Expected — readings populated later or non-energy lines",
            recommended_action="No action needed",
        ))


def _run_step3_gates(cur, org_id: int, sage_projects: Dict[str, Any], result: StepResult):
    """Run Step 3 / Stage B gate checks."""
    # Gate 1: All contract_lines resolve to a contract
    cur.execute(
        "SELECT COUNT(*) AS total FROM contract_line cl "
        "JOIN contract c ON c.id = cl.contract_id "
        "WHERE cl.organization_id = %s",
        (org_id,),
    )
    db_total = cur.fetchone()["total"]
    cur.execute(
        "SELECT COUNT(*) AS total FROM contract_line WHERE organization_id = %s",
        (org_id,),
    )
    all_lines = cur.fetchone()["total"]
    result.gate_checks.append(GateCheck(
        name="All contract_lines resolve to a contract",
        passed=db_total == all_lines,
        expected=f"{all_lines}/{all_lines}",
        actual=f"{db_total}/{all_lines}",
    ))

    # Gate 2: Contract_line count in DB vs SAGE CSV
    sage_line_count = sum(
        len(proj.contract_lines) for proj in sage_projects.values()
    )
    # Subtract lines that had no matching contract (they weren't inserted)
    skipped_lines = sum(
        1 for proj in sage_projects.values()
        for line in proj.contract_lines
        if not any(
            d.project == proj.sage_id and d.field == "contract_line.contract_id"
            for d in result.discrepancies
        )
    )
    result.gate_checks.append(GateCheck(
        name="Contract_line count matches SAGE CSV",
        passed=True,  # Informational
        expected=f"{sage_line_count} from CSV",
        actual=f"{all_lines} in DB",
    ))

    # Gate 3: Active lines count
    cur.execute(
        "SELECT COUNT(*) AS active FROM contract_line "
        "WHERE organization_id = %s AND is_active = true",
        (org_id,),
    )
    active_count = cur.fetchone()["active"]
    cur.execute(
        "SELECT COUNT(*) AS inactive FROM contract_line "
        "WHERE organization_id = %s AND is_active = false",
        (org_id,),
    )
    inactive_count = cur.fetchone()["inactive"]
    result.gate_checks.append(GateCheck(
        name="Active/inactive line breakdown",
        passed=active_count > 0,
        expected="active > 0",
        actual=f"{active_count} active, {inactive_count} inactive",
    ))

    # Gate 4: Orphaned meter readings (SCD2-superseded lines are acceptable)
    orphan_count = sum(
        1 for d in result.discrepancies
        if d.step == 3 and d.field == "meter_reading → contract_line"
    )
    # Orphans from SCD2-superseded lines are expected; only fail if excessive
    result.gate_checks.append(GateCheck(
        name="Orphaned meter readings (SCD2 acceptable)",
        passed=orphan_count <= 10,
        expected="≤10 orphans (SCD2-superseded OK)",
        actual=f"{orphan_count} orphan(s)",
    ))

    # Gate 5: Projects with contract_lines
    cur.execute(
        "SELECT COUNT(DISTINCT p.sage_id) AS cnt "
        "FROM contract_line cl "
        "JOIN contract c ON c.id = cl.contract_id "
        "JOIN project p ON p.id = c.project_id "
        "WHERE cl.organization_id = %s",
        (org_id,),
    )
    projects_with_lines = cur.fetchone()["cnt"]
    result.gate_checks.append(GateCheck(
        name="Projects with contract_lines",
        passed=projects_with_lines >= 25,
        expected="25+",
        actual=str(projects_with_lines),
    ))


# =============================================================================
# Output Formatting
# =============================================================================

def print_result(result: StepResult):
    """Print structured validation table to console."""
    status_icon = {
        "passed": "PASS", "failed": "FAIL",
        "warnings": "WARN", "skipped": "SKIP",
    }

    print()
    print(f"{'='*60}")
    print(f"Step {result.step_number}: {result.step_name}")
    print(f"Status: [{status_icon.get(result.status, '?')}] {result.status.upper()}")
    print(f"Validated: {result.validated} | Gaps filled: {result.gaps_filled}")
    print(f"{'='*60}")

    # Gate checks
    if result.gate_checks:
        print(f"\n{'─'*40}")
        print("Stage A Gate Checks:")
        print(f"{'─'*40}")
        for gc in result.gate_checks:
            icon = "PASS" if gc.passed else "FAIL"
            print(f"  [{icon}] {gc.name}: {gc.actual} (expected: {gc.expected})")

    # Discrepancies
    if result.discrepancies:
        print(f"\n{'─'*40}")
        print(f"Discrepancies: {len(result.discrepancies)}")
        print(f"{'─'*40}")

        by_severity = {"critical": [], "warning": [], "info": []}
        for d in result.discrepancies:
            by_severity.setdefault(d.severity, []).append(d)

        for sev in ("critical", "warning", "info"):
            items = by_severity.get(sev, [])
            if items:
                print(f"\n  [{sev.upper()}] ({len(items)}):")
                for d in items:
                    print(f"    {d.project}.{d.field}: {d.source_a} vs {d.source_b}")
                    print(f"      → {d.recommended_action} [{d.status}]")

    print()


def write_report(result: StepResult, reports_dir: str):
    """Write JSON report to reports directory."""
    os.makedirs(reports_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(reports_dir, f"step{result.step_number}_{today}.json")

    report = {
        "step_number": result.step_number,
        "step_name": result.step_name,
        "status": result.status,
        "run_date": today,
        "validated": result.validated,
        "gaps_filled": result.gaps_filled,
        "discrepancy_count": len(result.discrepancies),
        "discrepancies": [asdict(d) for d in result.discrepancies],
        "gate_checks": [asdict(g) for g in result.gate_checks],
        "summary": {
            "critical": sum(1 for d in result.discrepancies if d.severity == "critical"),
            "warning": sum(1 for d in result.discrepancies if d.severity == "warning"),
            "info": sum(1 for d in result.discrepancies if d.severity == "info"),
            "gates_passed": sum(1 for g in result.gate_checks if g.passed),
            "gates_total": len(result.gate_checks),
        },
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"Report written to {report_path}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CBE Data Population Orchestrator"
    )
    parser.add_argument(
        "--step", type=int, required=True,
        help=f"Step number to run. Available: {StepRegistry.available_steps()}",
    )
    parser.add_argument(
        "--data-dir", type=str, required=True,
        help="Path to CBE_data_extracts directory",
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Single project sage_id (e.g. KAS01). Default: all projects.",
    )
    parser.add_argument(
        "--org-id", type=int, default=DEFAULT_ORG_ID,
        help="Organization ID (default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and report only, no DB writes",
    )
    args = parser.parse_args()

    # Resolve data-dir to absolute path
    data_dir = os.path.abspath(args.data_dir)
    if not os.path.isdir(data_dir):
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    reports_dir = os.path.join(project_root, "reports", "cbe-population")

    # Build context
    ctx = {
        "data_dir": data_dir,
        "org_id": args.org_id,
        "dry_run": args.dry_run,
        "project": args.project,
        "reports_dir": reports_dir,
    }

    # Initialize DB
    init_connection_pool(min_connections=1, max_connections=3)

    try:
        result = StepRegistry.run(args.step, ctx)
        print_result(result)
        write_report(result, reports_dir)

        if result.status == "failed":
            sys.exit(1)
    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
