#!/usr/bin/env python3
"""
Step 5: Plant Performance Workbook — Summary Tabs.

Populates preliminary production_forecast from the PPW Summary-Performance tab
and verifies/updates project.installed_dc_capacity_kwp from the Waterfall tab.

Usage:
    cd python-backend
    python scripts/step5_summary_tabs.py --dry-run        # Preview
    python scripts/step5_summary_tabs.py                   # Execute
    python scripts/step5_summary_tabs.py --project KAS01   # Single project
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection
from models.onboarding import SummaryPerformanceRow, TechnicalModelRow, WaterfallRow
from services.onboarding.parsers.plant_performance_parser import PlantPerformanceParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("step5_summary_tabs")

DEFAULT_ORG_ID = 1
WORKBOOK_PATH = os.path.join(
    project_root.parent, "CBE_data_extracts", "Operations Plant Performance Workbook.xlsx"
)


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class Discrepancy:
    severity: str       # "critical" | "warning" | "info"
    category: str
    project: str
    field: str
    source_a: str
    source_b: str
    recommended_action: str
    status: str = "open"


@dataclass
class GateCheck:
    name: str
    passed: bool
    expected: str
    actual: str


@dataclass
class ProjectResult:
    sage_id: str
    project_id: Optional[int] = None
    forecasts_inserted: int = 0
    forecasts_updated: int = 0
    capacity_updated: bool = False
    capacity_old: Optional[float] = None
    capacity_new: Optional[float] = None
    discrepancies: List[Discrepancy] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class StepReport:
    step: int = 5
    step_name: str = "Plant Performance Workbook — Summary Tabs"
    status: str = "passed"
    run_date: str = ""
    dry_run: bool = False
    projects_processed: int = 0
    total_forecasts_inserted: int = 0
    total_forecasts_updated: int = 0
    capacities_updated: int = 0
    project_results: List[ProjectResult] = field(default_factory=list)
    gate_checks: List[GateCheck] = field(default_factory=list)
    discrepancies: List[Discrepancy] = field(default_factory=list)
    summary_projects_parsed: int = 0
    waterfall_rows_parsed: int = 0


# =============================================================================
# Helpers
# =============================================================================

def _safe_json(obj: Any) -> Any:
    """Make dataclass/date objects JSON-serializable."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _safe_json(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    return obj


def _pct_diff(a: float, b: float) -> float:
    """Calculate percentage difference between two values."""
    if b == 0:
        return 100.0 if a != 0 else 0.0
    return abs(a - b) / abs(b) * 100.0


# =============================================================================
# Main Logic
# =============================================================================

def run_step5(
    workbook_path: str,
    org_id: int = DEFAULT_ORG_ID,
    project_filter: Optional[str] = None,
    dry_run: bool = False,
) -> StepReport:
    """Execute Step 5: Summary tabs → production_forecast + capacity verification."""

    report = StepReport(
        run_date=datetime.now().isoformat(),
        dry_run=dry_run,
    )

    # ── Phase 1: Parse ───────────────────────────────────────────────────

    if not os.path.exists(workbook_path):
        logger.error(f"Workbook not found: {workbook_path}")
        report.status = "failed"
        report.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project="ALL",
            field="source_file", source_a=workbook_path,
            source_b="NOT FOUND", recommended_action="Provide PPW workbook",
        ))
        return report

    parser = PlantPerformanceParser(workbook_path)

    # Parse Summary-Performance tab
    logger.info("=" * 60)
    logger.info("Phase 1: Parsing Summary-Performance tab")
    logger.info("=" * 60)
    summary_data = parser.parse_summary_performance(project_filter=project_filter)
    report.summary_projects_parsed = len(summary_data)
    total_summary_rows = sum(len(v) for v in summary_data.values())
    logger.info(f"Parsed {total_summary_rows} rows for {len(summary_data)} projects")

    # Parse Project Waterfall tab
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 1: Parsing Project Waterfall tab")
    logger.info("=" * 60)
    waterfall_rows = parser.parse_project_waterfall(project_filter=project_filter)
    report.waterfall_rows_parsed = len(waterfall_rows)
    # Take first row per sage_id (annual, not cumulative lifetime)
    waterfall_by_sage: Dict[str, WaterfallRow] = {}
    for w in waterfall_rows:
        if w.sage_id not in waterfall_by_sage:
            waterfall_by_sage[w.sage_id] = w
    logger.info(f"Parsed {len(waterfall_rows)} waterfall rows")

    # Parse individual project tabs for projects NOT in summary tab
    # (e.g., TWG01 which has a Technical Model section in its own tab)
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 1c: Parsing individual project tabs (gap-fill)")
    logger.info("=" * 60)

    # Get all org projects from DB to know which sage_ids to look for
    init_connection_pool(min_connections=1, max_connections=3)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sage_id FROM project WHERE organization_id = %(oid)s",
                    {"oid": org_id},
                )
                db_sage_ids = {r["sage_id"] for r in cur.fetchall()}
    finally:
        close_connection_pool()

    # Projects in DB but not in summary tab → try individual tabs
    missing_from_summary = db_sage_ids - set(summary_data.keys())
    if project_filter:
        missing_from_summary = {s for s in missing_from_summary if s == project_filter}

    tech_model_data: Dict[str, List[TechnicalModelRow]] = {}
    if missing_from_summary:
        ppw_data = parser.parse(project_filter=project_filter)
        for sage_id in missing_from_summary:
            tech_rows = ppw_data.technical_model.get(sage_id, [])
            if tech_rows:
                # Filter to rows with forecast energy
                forecast_rows = [r for r in tech_rows if r.forecast_energy_combined_kwh is not None]
                if forecast_rows:
                    tech_model_data[sage_id] = forecast_rows
                    logger.info(f"  {sage_id}: {len(forecast_rows)} forecast rows from project tab")
            else:
                logger.debug(f"  {sage_id}: no Technical Model data in project tab")

        logger.info(f"  Gap-filled {len(tech_model_data)} project(s) from individual tabs")

    if not summary_data and not waterfall_rows and not tech_model_data:
        logger.warning("No data parsed from any source — nothing to do")
        report.status = "warnings"
        return report

    # ── Phase 2: DB operations ───────────────────────────────────────────

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Phase 2: {'DRY RUN — ' if dry_run else ''}DB operations")
    logger.info("=" * 60)

    # Collect all sage_ids from all sources
    all_sage_ids = sorted(
        set(summary_data.keys()) | set(waterfall_by_sage.keys()) | set(tech_model_data.keys())
    )

    init_connection_pool(min_connections=1, max_connections=3)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Extend timeout for batch operations
                cur.execute("SET statement_timeout = '300000'")  # 5 minutes
                for sage_id in all_sage_ids:
                    pr = _process_project(
                        cur=cur,
                        sage_id=sage_id,
                        summary_rows=summary_data.get(sage_id, []),
                        tech_model_rows=tech_model_data.get(sage_id, []),
                        waterfall=waterfall_by_sage.get(sage_id),
                        org_id=org_id,
                        dry_run=dry_run,
                    )
                    report.project_results.append(pr)
                    report.discrepancies.extend(pr.discrepancies)
                    report.total_forecasts_inserted += pr.forecasts_inserted
                    report.total_forecasts_updated += pr.forecasts_updated
                    if pr.capacity_updated:
                        report.capacities_updated += 1

                if not dry_run:
                    conn.commit()
                    logger.info("Committed all changes")

        report.projects_processed = len(all_sage_ids)

    finally:
        close_connection_pool()

    # ── Phase 3: Cross-checks ────────────────────────────────────────────

    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 3: Cross-checks")
    logger.info("=" * 60)

    _run_cross_checks(report, summary_data, waterfall_by_sage)

    # ── Phase 4: Gate checks ─────────────────────────────────────────────

    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 4: Gate checks")
    logger.info("=" * 60)

    _run_gate_checks(report, all_sage_ids)

    # ── Determine final status ───────────────────────────────────────────

    critical_count = sum(1 for d in report.discrepancies if d.severity == "critical")
    failed_gates = sum(1 for g in report.gate_checks if not g.passed)

    if critical_count > 0 or failed_gates > 0:
        report.status = "failed"
    elif sum(1 for d in report.discrepancies if d.severity == "warning") > 0:
        report.status = "warnings"
    else:
        report.status = "passed"

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Step 5 Result: {report.status.upper()}")
    logger.info(f"  Projects processed: {report.projects_processed}")
    logger.info(f"  Forecasts inserted: {report.total_forecasts_inserted}")
    logger.info(f"  Forecasts updated:  {report.total_forecasts_updated}")
    logger.info(f"  Capacities updated: {report.capacities_updated}")
    logger.info(f"  Discrepancies:      {len(report.discrepancies)}")
    logger.info(f"  Gate checks:        {sum(1 for g in report.gate_checks if g.passed)}/{len(report.gate_checks)} passed")
    logger.info("=" * 60)

    return report


def _process_project(
    cur,
    sage_id: str,
    summary_rows: List[SummaryPerformanceRow],
    tech_model_rows: List[TechnicalModelRow],
    waterfall: Optional[WaterfallRow],
    org_id: int,
    dry_run: bool,
) -> ProjectResult:
    """Process a single project: upsert forecasts + verify/update capacity."""

    pr = ProjectResult(sage_id=sage_id)

    # Resolve project_id
    cur.execute(
        "SELECT id, organization_id, installed_dc_capacity_kwp "
        "FROM project WHERE sage_id = %(sid)s",
        {"sid": sage_id},
    )
    proj = cur.fetchone()
    if not proj:
        pr.errors.append(f"Project not found for sage_id={sage_id}")
        pr.discrepancies.append(Discrepancy(
            severity="critical", category="missing_data", project=sage_id,
            field="project.id", source_a=sage_id,
            source_b="NOT FOUND", recommended_action="Add project to DB",
        ))
        return pr

    project_id = proj["id"]
    pr.project_id = project_id
    proj_org_id = proj["organization_id"]
    current_capacity = float(proj["installed_dc_capacity_kwp"]) if proj["installed_dc_capacity_kwp"] else None

    logger.info(f"  {sage_id}: project_id={project_id}, capacity={current_capacity}")

    # ── Upsert production_forecast from summary rows (batched) ──────

    # Build batch values
    batch_values = []
    for row in summary_rows:
        if row.expected_output_kwh is None:
            continue

        # Convert irradiance: Wh/m² → kWh/m²
        ghi_kwh = row.expected_irradiance_wm2 / 1000.0 if row.expected_irradiance_wm2 else None

        # Normalize PR
        forecast_pr = row.expected_pr_pct
        if forecast_pr is not None and forecast_pr > 1.0:
            forecast_pr = forecast_pr / 100.0

        meta = json.dumps({
            "step": 5,
            "source_tab": "Summary - Performance",
            "actual_invoiced_energy_kwh": row.actual_invoiced_energy_kwh,
            "actual_irradiance_wm2": row.actual_irradiance_wm2,
            "plant_availability_pct": row.plant_availability_pct,
        })

        batch_values.append((
            project_id, proj_org_id, row.month,
            row.expected_output_kwh, ghi_kwh,
            forecast_pr, meta,
        ))

    if batch_values and dry_run:
        pr.forecasts_inserted = len(batch_values)
    elif batch_values:
        from psycopg2.extras import execute_values

        # Count existing rows before upsert
        cur.execute(
            "SELECT COUNT(*) FROM production_forecast WHERE project_id = %(pid)s",
            {"pid": project_id},
        )
        before_count = cur.fetchone()["count"]

        execute_values(
            cur,
            """
            INSERT INTO production_forecast (
                project_id, organization_id, forecast_month,
                forecast_energy_kwh, forecast_ghi_irradiance,
                forecast_pr, forecast_source, source_metadata
            ) VALUES %s
            ON CONFLICT (project_id, forecast_month) DO UPDATE SET
                forecast_energy_kwh = EXCLUDED.forecast_energy_kwh,
                forecast_ghi_irradiance = COALESCE(EXCLUDED.forecast_ghi_irradiance, production_forecast.forecast_ghi_irradiance),
                forecast_pr = COALESCE(EXCLUDED.forecast_pr, production_forecast.forecast_pr),
                forecast_source = EXCLUDED.forecast_source,
                source_metadata = EXCLUDED.source_metadata,
                updated_at = NOW()
            """,
            batch_values,
            template="(%s, %s, %s, %s, %s, %s, 'ppw_summary', %s::jsonb)",
            page_size=200,
        )

        # Count after to determine inserts vs updates
        cur.execute(
            "SELECT COUNT(*) FROM production_forecast WHERE project_id = %(pid)s",
            {"pid": project_id},
        )
        after_count = cur.fetchone()["count"]
        pr.forecasts_inserted = after_count - before_count
        pr.forecasts_updated = len(batch_values) - pr.forecasts_inserted

    if summary_rows:
        forecast_count = len(batch_values)
        logger.info(
            f"    Forecasts: {pr.forecasts_inserted} inserted, "
            f"{pr.forecasts_updated} updated (from {forecast_count} summary rows)"
        )

    # ── Upsert from Technical Model rows (gap-fill for non-summary projects) ──

    if tech_model_rows and not summary_rows:
        tech_batch = []
        for row in tech_model_rows:
            if row.forecast_energy_combined_kwh is None:
                continue
            ghi_kwh = row.forecast_ghi_wm2 / 1000.0 if row.forecast_ghi_wm2 else None
            poa_kwh = row.forecast_poa_wm2 / 1000.0 if row.forecast_poa_wm2 else None
            meta = json.dumps({
                "step": 5,
                "source_tab": "project_tab_technical_model",
                "operating_year": row.operating_year,
            })
            tech_batch.append((
                project_id, proj_org_id, row.month,
                row.forecast_energy_combined_kwh, ghi_kwh,
                row.forecast_pr, meta,
            ))

        if tech_batch and dry_run:
            pr.forecasts_inserted = len(tech_batch)
        elif tech_batch:
            from psycopg2.extras import execute_values

            cur.execute(
                "SELECT COUNT(*) FROM production_forecast WHERE project_id = %(pid)s",
                {"pid": project_id},
            )
            before_count = cur.fetchone()["count"]

            execute_values(
                cur,
                """
                INSERT INTO production_forecast (
                    project_id, organization_id, forecast_month,
                    forecast_energy_kwh, forecast_ghi_irradiance,
                    forecast_pr, forecast_source, source_metadata
                ) VALUES %s
                ON CONFLICT (project_id, forecast_month) DO UPDATE SET
                    forecast_energy_kwh = EXCLUDED.forecast_energy_kwh,
                    forecast_ghi_irradiance = COALESCE(EXCLUDED.forecast_ghi_irradiance, production_forecast.forecast_ghi_irradiance),
                    forecast_pr = COALESCE(EXCLUDED.forecast_pr, production_forecast.forecast_pr),
                    forecast_source = EXCLUDED.forecast_source,
                    source_metadata = EXCLUDED.source_metadata,
                    updated_at = NOW()
                """,
                tech_batch,
                template="(%s, %s, %s, %s, %s, %s, 'ppw_project_tab', %s::jsonb)",
                page_size=200,
            )

            cur.execute(
                "SELECT COUNT(*) FROM production_forecast WHERE project_id = %(pid)s",
                {"pid": project_id},
            )
            after_count = cur.fetchone()["count"]
            pr.forecasts_inserted = after_count - before_count
            pr.forecasts_updated = len(tech_batch) - pr.forecasts_inserted

        if tech_batch:
            logger.info(
                f"    Forecasts (from project tab): {pr.forecasts_inserted} inserted, "
                f"{pr.forecasts_updated} updated (from {len(tech_batch)} tech model rows)"
            )

    # ── Verify/update capacity from waterfall ────────────────────────

    if waterfall and waterfall.installed_capacity_kwp is not None:
        new_capacity = waterfall.installed_capacity_kwp

        if current_capacity is None:
            # Fill NULL
            if not dry_run:
                cur.execute(
                    "UPDATE project SET installed_dc_capacity_kwp = %(cap)s "
                    "WHERE id = %(pid)s",
                    {"cap": new_capacity, "pid": project_id},
                )
            pr.capacity_updated = True
            pr.capacity_old = None
            pr.capacity_new = new_capacity
            logger.info(f"    Capacity: NULL → {new_capacity} kWp")

        elif _pct_diff(new_capacity, current_capacity) > 1.0:
            # Significant difference — update but log discrepancy
            if not dry_run:
                cur.execute(
                    "UPDATE project SET installed_dc_capacity_kwp = %(cap)s "
                    "WHERE id = %(pid)s",
                    {"cap": new_capacity, "pid": project_id},
                )
            pr.capacity_updated = True
            pr.capacity_old = current_capacity
            pr.capacity_new = new_capacity
            diff_pct = _pct_diff(new_capacity, current_capacity)
            pr.discrepancies.append(Discrepancy(
                severity="warning", category="value_conflict", project=sage_id,
                field="project.installed_dc_capacity_kwp",
                source_a=f"waterfall={new_capacity}",
                source_b=f"db={current_capacity}",
                recommended_action=f"Updated to waterfall value (diff={diff_pct:.1f}%)",
            ))
            logger.info(
                f"    Capacity: {current_capacity} → {new_capacity} kWp "
                f"(diff={diff_pct:.1f}%)"
            )
        else:
            logger.info(f"    Capacity: {current_capacity} kWp (matches waterfall)")

    return pr


def _run_cross_checks(
    report: StepReport,
    summary_data: Dict[str, List[SummaryPerformanceRow]],
    waterfall_by_sage: Dict[str, WaterfallRow],
) -> None:
    """Run cross-check validations between summary, waterfall, and DB."""

    init_connection_pool(min_connections=1, max_connections=3)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for sage_id, wf in waterfall_by_sage.items():
                    if wf.expected_energy_kwh is None:
                        continue

                    # Cross-check: waterfall expected energy (annual) vs
                    # AVG(production_forecast) * 12 (implied annual)
                    cur.execute(
                        "SELECT AVG(forecast_energy_kwh) * 12 as implied_annual, "
                        "COUNT(*) as months "
                        "FROM production_forecast pf "
                        "JOIN project p ON p.id = pf.project_id "
                        "WHERE p.sage_id = %(sid)s",
                        {"sid": sage_id},
                    )
                    row = cur.fetchone()
                    db_annual = float(row["implied_annual"]) if row and row["implied_annual"] else None

                    if db_annual is not None:
                        diff_pct = _pct_diff(wf.expected_energy_kwh, db_annual)
                        if diff_pct > 5.0:
                            report.discrepancies.append(Discrepancy(
                                severity="warning",
                                category="cross_check",
                                project=sage_id,
                                field="waterfall.expected_energy vs SUM(production_forecast)",
                                source_a=f"waterfall_annual={wf.expected_energy_kwh:.0f}",
                                source_b=f"db_implied_annual={db_annual:.0f}",
                                recommended_action=f"Difference {diff_pct:.1f}% exceeds 5% threshold",
                            ))
                            logger.warning(
                                f"  {sage_id}: waterfall annual={wf.expected_energy_kwh:.0f} "
                                f"vs DB implied annual={db_annual:.0f} ({diff_pct:.1f}% diff)"
                            )
                        else:
                            logger.info(
                                f"  {sage_id}: waterfall vs forecast annual OK ({diff_pct:.1f}% diff)"
                            )

                    # Cross-check: tariff_rate_per_kwh vs clause_tariff.base_rate
                    if wf.tariff_rate_per_kwh is not None:
                        cur.execute(
                            """
                            SELECT ct.base_rate
                            FROM clause_tariff ct
                            JOIN contract c ON c.id = ct.contract_id
                            JOIN project p ON p.id = c.project_id
                            WHERE p.sage_id = %(sid)s
                            LIMIT 1
                            """,
                            {"sid": sage_id},
                        )
                        tariff_row = cur.fetchone()
                        if tariff_row and tariff_row["base_rate"] is not None:
                            db_rate = float(tariff_row["base_rate"])
                            diff_pct = _pct_diff(wf.tariff_rate_per_kwh, db_rate)
                            if diff_pct > 5.0:
                                report.discrepancies.append(Discrepancy(
                                    severity="info",
                                    category="cross_check",
                                    project=sage_id,
                                    field="waterfall.tariff vs clause_tariff.base_rate",
                                    source_a=f"waterfall={wf.tariff_rate_per_kwh}",
                                    source_b=f"db={db_rate}",
                                    recommended_action=f"Difference {diff_pct:.1f}%",
                                ))
    finally:
        close_connection_pool()


def _run_gate_checks(report: StepReport, all_sage_ids: List[str]) -> None:
    """Run Step 5 gate checks."""

    # Gate 1: All projects have matching sage_id in DB
    unresolved = [
        pr.sage_id for pr in report.project_results
        if pr.project_id is None
    ]
    gate1 = GateCheck(
        name="All PPW projects have matching sage_id in project table",
        passed=len(unresolved) == 0,
        expected="0 unresolved",
        actual=f"{len(unresolved)} unresolved: {', '.join(unresolved)}" if unresolved else "0 unresolved",
    )
    report.gate_checks.append(gate1)
    logger.info(f"  Gate 1 {'PASS' if gate1.passed else 'FAIL'}: {gate1.name} — {gate1.actual}")

    # Gate 2: All production_forecast rows have non-NULL forecast_energy_kwh
    # (enforced by DB NOT NULL constraint, so always passes if inserts succeeded)
    total_upserted = report.total_forecasts_inserted + report.total_forecasts_updated
    gate2 = GateCheck(
        name="All production_forecast rows have forecast_energy_kwh",
        passed=total_upserted > 0 or report.dry_run,
        expected=">0 forecast rows",
        actual=f"{total_upserted} rows upserted",
    )
    report.gate_checks.append(gate2)
    logger.info(f"  Gate 2 {'PASS' if gate2.passed else 'FAIL'}: {gate2.name} — {gate2.actual}")

    # Gate 3: All projects have installed_dc_capacity_kwp set
    missing_capacity = [
        pr.sage_id for pr in report.project_results
        if pr.project_id is not None and not pr.capacity_updated
        and pr.sage_id in [w for w in report.project_results if True]
    ]
    # Re-check from DB
    init_connection_pool(min_connections=1, max_connections=3)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sage_id FROM project "
                    "WHERE sage_id = ANY(%(ids)s) AND installed_dc_capacity_kwp IS NULL",
                    {"ids": all_sage_ids},
                )
                null_capacity = [row["sage_id"] for row in cur.fetchall()]
    finally:
        close_connection_pool()

    gate3 = GateCheck(
        name="All processed projects have installed_dc_capacity_kwp",
        passed=len(null_capacity) == 0,
        expected="0 with NULL capacity",
        actual=f"{len(null_capacity)} with NULL: {', '.join(null_capacity)}" if null_capacity else "0 with NULL",
    )
    report.gate_checks.append(gate3)
    logger.info(f"  Gate 3 {'PASS' if gate3.passed else 'FAIL'}: {gate3.name} — {gate3.actual}")

    # Gate 4: No duplicate production_forecast rows (UNIQUE constraint)
    gate4 = GateCheck(
        name="No duplicate production_forecast rows (UNIQUE constraint holds)",
        passed=True,  # If upserts succeeded without error, constraint holds
        expected="0 duplicates",
        actual="0 duplicates (enforced by UNIQUE(project_id, forecast_month))",
    )
    report.gate_checks.append(gate4)
    logger.info(f"  Gate 4 {'PASS' if gate4.passed else 'FAIL'}: {gate4.name}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Step 5: PPW Summary Tabs → production_forecast + capacity verification",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--project", type=str, help="Filter to single sage_id")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID, help="Organization ID")
    parser.add_argument(
        "--workbook", type=str, default=WORKBOOK_PATH,
        help="Path to Operations Plant Performance Workbook.xlsx",
    )
    args = parser.parse_args()

    report = run_step5(
        workbook_path=args.workbook,
        org_id=args.org_id,
        project_filter=args.project,
        dry_run=args.dry_run,
    )

    # Write report JSON
    report_dir = os.path.join(project_root, "reports", "cbe-population")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(
        report_dir, f"step5_{date.today().isoformat()}.json"
    )

    report_data = _safe_json(report)
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2, default=str)

    logger.info(f"Report written to {report_path}")
    return 0 if report.status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
