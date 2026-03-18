#!/usr/bin/env python3
"""
Forecast Extension Engine — Auto-Populate Future Monthly Forecasts.

Extends existing production_forecast rows to the full contract term for all
projects. Uses the last full calendar year of existing forecasts as a baseline
and projects forward with degradation applied.

Usage:
    cd python-backend
    python scripts/extend_forecasts.py --dry-run        # Preview all projects
    python scripts/extend_forecasts.py                   # Execute all projects
    python scripts/extend_forecasts.py --project GBL01   # Single project
    python scripts/extend_forecasts.py --project GBL01 --dry-run
"""

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("extend_forecasts")

DEFAULT_ORG_ID = 1
# Cap implicit degradation at 1%/year — anything higher is likely a data artifact
MAX_IMPLICIT_DEGRADATION = 0.01


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ProjectResult:
    sage_id: str
    project_id: int
    last_existing_month: Optional[str] = None
    contract_end_month: Optional[str] = None
    end_date_source: Optional[str] = None
    baseline_year: Optional[int] = None
    degradation_pct: Optional[float] = None
    degradation_source: Optional[str] = None
    months_to_extend: int = 0
    rows_inserted: int = 0
    skipped_reason: Optional[str] = None
    errors: List[str] = field(default_factory=list)


@dataclass
class StepReport:
    step_name: str = "Forecast Extension Engine"
    status: str = "passed"
    run_date: str = ""
    dry_run: bool = False
    projects_processed: int = 0
    projects_extended: int = 0
    projects_skipped: int = 0
    total_rows_inserted: int = 0
    project_results: List[ProjectResult] = field(default_factory=list)


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


def _first_of_month(d: date) -> date:
    """Return first day of the month for a given date."""
    return date(d.year, d.month, 1)


def _compute_operating_year(forecast_month: date, oy_anchor: date) -> int:
    """Compute 1-based operating year from OY anchor date."""
    year_diff = forecast_month.year - oy_anchor.year
    if forecast_month.month < oy_anchor.month:
        year_diff -= 1
    return max(1, year_diff + 1)


def _get_contract_end_date(
    cur, project_id: int, cod_date: Optional[date]
) -> Tuple[Optional[date], Optional[str]]:
    """
    Determine contract end date using fallback chain:
    1. cod_date + contract_term_years_po (from clause_tariff.logic_parameters)
    2. contract.end_date (from PPA extraction)

    Returns (end_date, source_description) or (None, None).
    """
    # Try #1: cod_date + contract_term_years_po
    if cod_date:
        cur.execute("""
            SELECT ct.logic_parameters->>'contract_term_years_po' AS term
            FROM clause_tariff ct
            JOIN contract c ON ct.contract_id = c.id
            WHERE c.project_id = %s
              AND ct.logic_parameters->>'contract_term_years_po' IS NOT NULL
            LIMIT 1
        """, (project_id,))
        row = cur.fetchone()
        if row and row["term"]:
            try:
                term_years = float(row["term"])
                # Use relativedelta for precise year addition
                end_date = cod_date + relativedelta(years=int(term_years))
                # If there's a fractional part, add months
                frac_months = round((term_years - int(term_years)) * 12)
                if frac_months:
                    end_date = end_date + relativedelta(months=frac_months)
                return _first_of_month(end_date), f"cod_date + contract_term_years_po ({term_years}y)"
            except (ValueError, TypeError):
                pass

    # Try #2: contract.end_date
    cur.execute("""
        SELECT end_date
        FROM contract
        WHERE project_id = %s AND end_date IS NOT NULL
        ORDER BY end_date DESC
        LIMIT 1
    """, (project_id,))
    row = cur.fetchone()
    if row and row["end_date"]:
        return _first_of_month(row["end_date"]), "contract.end_date"

    return None, None


def _get_degradation_pct(cur, project_id: int) -> Tuple[Optional[float], str]:
    """
    Get explicit degradation_pct from clause_tariff.logic_parameters.
    Returns (pct_as_decimal, source) or (None, source).
    """
    cur.execute("""
        SELECT ct.logic_parameters->>'degradation_pct' AS deg
        FROM clause_tariff ct
        JOIN contract c ON ct.contract_id = c.id
        WHERE c.project_id = %s
          AND ct.logic_parameters->>'degradation_pct' IS NOT NULL
        LIMIT 1
    """, (project_id,))
    row = cur.fetchone()
    if row and row["deg"]:
        try:
            return float(row["deg"]), "clause_tariff.logic_parameters"
        except (ValueError, TypeError):
            pass
    return None, "none"


def _get_baseline_and_implicit_degradation(
    cur, project_id: int
) -> Tuple[Dict[int, dict], Optional[float], int, int]:
    """
    Extract the last full calendar year of forecasts as baseline,
    and compute implicit annual degradation from Year 1 vs last year.

    Returns:
        baseline: {month_num: {energy, ghi, poa, pr}} for 12 months
        implicit_degradation: float or None
        baseline_year: int
        first_year: int
    """
    # Get all existing forecast rows ordered by month
    cur.execute("""
        SELECT forecast_month, forecast_energy_kwh, forecast_ghi_irradiance,
               forecast_poa_irradiance, forecast_pr
        FROM production_forecast
        WHERE project_id = %s
        ORDER BY forecast_month
    """, (project_id,))
    rows = cur.fetchall()

    if not rows:
        return {}, None, 0, 0

    # Group by calendar year
    by_year: Dict[int, List[dict]] = {}
    for r in rows:
        yr = r["forecast_month"].year
        by_year.setdefault(yr, []).append(r)

    # Find the last full calendar year (12 months)
    sorted_years = sorted(by_year.keys(), reverse=True)
    baseline_year = None
    for yr in sorted_years:
        if len(by_year[yr]) == 12:
            baseline_year = yr
            break

    # If no full year, use the last year available (partial)
    if baseline_year is None:
        baseline_year = sorted_years[0]

    # Build baseline dict keyed by month number (1-12)
    baseline: Dict[int, dict] = {}
    for r in by_year[baseline_year]:
        m = r["forecast_month"].month
        baseline[m] = {
            "energy": float(r["forecast_energy_kwh"]) if r["forecast_energy_kwh"] else 0,
            "ghi": float(r["forecast_ghi_irradiance"]) if r["forecast_ghi_irradiance"] else None,
            "poa": float(r["forecast_poa_irradiance"]) if r["forecast_poa_irradiance"] else None,
            "pr": float(r["forecast_pr"]) if r["forecast_pr"] else None,
        }

    # Compute implicit degradation from Year 1 vs baseline year
    first_year = sorted(by_year.keys())[0]
    implicit_degradation = None

    if first_year != baseline_year and len(by_year[first_year]) >= 6:
        # Compare matching months between first and baseline year
        ratios = []
        for r1 in by_year[first_year]:
            m = r1["forecast_month"].month
            if m in baseline and r1["forecast_energy_kwh"] and float(r1["forecast_energy_kwh"]) > 0:
                bl_energy = baseline[m]["energy"]
                y1_energy = float(r1["forecast_energy_kwh"])
                if y1_energy > 0 and bl_energy > 0:
                    ratios.append(bl_energy / y1_energy)

        if ratios:
            avg_ratio = sum(ratios) / len(ratios)
            n_years = baseline_year - first_year
            if n_years > 0 and avg_ratio < 1.0:
                # ratio = (1 - d)^n → d = 1 - ratio^(1/n)
                implicit_degradation = 1.0 - avg_ratio ** (1.0 / n_years)

    return baseline, implicit_degradation, baseline_year, first_year


# =============================================================================
# Core Engine
# =============================================================================

def extend_project(
    cur,
    project_id: int,
    sage_id: str,
    org_id: int,
    cod_date: Optional[date],
    dry_run: bool,
) -> ProjectResult:
    """Extend forecasts for a single project to its contract end date."""

    result = ProjectResult(sage_id=sage_id, project_id=project_id)

    # 1. Check existing forecasts
    cur.execute("""
        SELECT MIN(forecast_month) AS first_month, MAX(forecast_month) AS last_month,
               COUNT(*) AS cnt
        FROM production_forecast
        WHERE project_id = %s
    """, (project_id,))
    stats = cur.fetchone()

    if not stats or stats["cnt"] == 0:
        result.skipped_reason = "no existing forecast rows"
        return result

    last_existing = stats["last_month"]
    result.last_existing_month = last_existing.isoformat()

    # 2. Determine contract end date
    contract_end, end_source = _get_contract_end_date(cur, project_id, cod_date)
    if not contract_end:
        result.skipped_reason = "no contract end date (no term or contract.end_date)"
        return result

    result.contract_end_month = contract_end.isoformat()
    result.end_date_source = end_source

    # 3. Check if already covered
    if last_existing >= contract_end:
        result.skipped_reason = f"already covered (last={last_existing}, end={contract_end})"
        return result

    # 4. Get baseline and degradation
    baseline, implicit_deg, baseline_year, first_year = \
        _get_baseline_and_implicit_degradation(cur, project_id)

    if not baseline:
        result.skipped_reason = "could not extract baseline from existing forecasts"
        return result

    result.baseline_year = baseline_year

    # 5. Determine degradation rate
    explicit_deg, deg_source = _get_degradation_pct(cur, project_id)
    if explicit_deg is not None:
        degradation = explicit_deg
        result.degradation_source = f"explicit ({deg_source})"
    elif implicit_deg is not None and implicit_deg > 0:
        if implicit_deg > MAX_IMPLICIT_DEGRADATION:
            logger.warning(
                f"  {sage_id}: implicit degradation {implicit_deg:.4%} exceeds cap "
                f"{MAX_IMPLICIT_DEGRADATION:.1%} — capping"
            )
            degradation = MAX_IMPLICIT_DEGRADATION
            result.degradation_source = (
                f"implicit-capped (raw={implicit_deg:.6f}, "
                f"year1={first_year}, baseline={baseline_year})"
            )
        else:
            degradation = implicit_deg
            result.degradation_source = f"implicit (year1={first_year}, baseline={baseline_year})"
    else:
        degradation = 0.0
        result.degradation_source = "flat (no degradation data)"

    result.degradation_pct = round(degradation, 6)

    # 6. Generate new months
    new_rows = []
    current = _first_of_month(last_existing) + relativedelta(months=1)

    while current <= contract_end:
        month_num = current.month

        # Use baseline for this calendar month; fall back to any available month
        if month_num in baseline:
            bl = baseline[month_num]
        else:
            # Partial baseline year — use average of available months
            avg_energy = sum(b["energy"] for b in baseline.values()) / len(baseline)
            avg_ghi = None
            ghis = [b["ghi"] for b in baseline.values() if b["ghi"] is not None]
            if ghis:
                avg_ghi = sum(ghis) / len(ghis)
            avg_poa = None
            poas = [b["poa"] for b in baseline.values() if b["poa"] is not None]
            if poas:
                avg_poa = sum(poas) / len(poas)
            avg_pr = None
            prs = [b["pr"] for b in baseline.values() if b["pr"] is not None]
            if prs:
                avg_pr = sum(prs) / len(prs)
            bl = {"energy": avg_energy, "ghi": avg_ghi, "poa": avg_poa, "pr": avg_pr}

        # Years beyond the baseline year
        years_beyond = current.year - baseline_year
        if current.month < list(baseline.keys())[0] if baseline else 1:
            # Edge case: if baseline starts mid-year, adjust
            pass

        # Degradation factor relative to baseline
        deg_factor = (1.0 - degradation) ** years_beyond if years_beyond > 0 else 1.0

        forecast_energy = bl["energy"] * deg_factor
        forecast_ghi = bl["ghi"]  # GHI is constant across years
        forecast_poa = bl["poa"]  # POA is constant across years
        forecast_pr = bl["pr"] * deg_factor if bl["pr"] else None

        # Operating year
        oy = _compute_operating_year(current, cod_date) if cod_date else None

        # Cumulative degradation factor from Year 1
        cumulative_deg_factor = None
        if oy and degradation > 0:
            cumulative_deg_factor = round((1.0 - degradation) ** (oy - 1), 6)

        source_meta = json.dumps({
            "engine": "extend_forecasts",
            "baseline_year": baseline_year,
            "degradation_pct": round(degradation, 6),
            "degradation_source": result.degradation_source,
            "years_beyond_baseline": years_beyond,
        })

        new_rows.append((
            project_id,
            org_id,
            current,                                    # forecast_month
            round(forecast_energy, 2),                  # forecast_energy_kwh
            round(forecast_ghi, 4) if forecast_ghi else None,  # forecast_ghi_irradiance
            round(forecast_poa, 4) if forecast_poa else None,  # forecast_poa_irradiance
            round(forecast_pr, 6) if forecast_pr else None,    # forecast_pr
            oy,                                         # operating_year
            cumulative_deg_factor,                      # degradation_factor
            source_meta,                                # source_metadata
        ))

        current += relativedelta(months=1)

    result.months_to_extend = len(new_rows)

    if not new_rows:
        result.skipped_reason = "no new months to add"
        return result

    # 7. Batch insert
    if not dry_run:
        execute_values(
            cur,
            """
            INSERT INTO production_forecast (
                project_id, organization_id, forecast_month,
                forecast_energy_kwh, forecast_ghi_irradiance, forecast_poa_irradiance,
                forecast_pr, operating_year, degradation_factor,
                forecast_source, source_metadata
            ) VALUES %s
            ON CONFLICT (project_id, forecast_month) DO NOTHING
            """,
            new_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, 'projected', %s::jsonb)",
            page_size=200,
        )
        result.rows_inserted = len(new_rows)
    else:
        result.rows_inserted = 0  # Dry run, nothing inserted

    return result


# =============================================================================
# Main
# =============================================================================

def run_extension(
    org_id: int = DEFAULT_ORG_ID,
    project_filter: Optional[str] = None,
    dry_run: bool = False,
) -> StepReport:
    """Run forecast extension for all (or one) project(s)."""

    report = StepReport(
        run_date=datetime.now().isoformat(),
        dry_run=dry_run,
    )

    init_connection_pool(min_connections=1, max_connections=3)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Extended timeout for batch operations
                cur.execute("SET statement_timeout = '300000'")  # 5 minutes

                # Fetch projects with their OY anchor dates
                if project_filter:
                    cur.execute("""
                        SELECT p.id, p.sage_id, p.cod_date,
                               ct.logic_parameters->>'oy_start_date' AS oy_start_date
                        FROM project p
                        LEFT JOIN clause_tariff ct
                            ON ct.project_id = p.id AND ct.is_current = true
                        WHERE p.organization_id = %s AND p.sage_id = %s
                    """, (org_id, project_filter))
                else:
                    cur.execute("""
                        SELECT p.id, p.sage_id, p.cod_date,
                               ct.logic_parameters->>'oy_start_date' AS oy_start_date
                        FROM project p
                        LEFT JOIN clause_tariff ct
                            ON ct.project_id = p.id AND ct.is_current = true
                        WHERE p.organization_id = %s
                        ORDER BY p.sage_id
                    """, (org_id,))

                projects = cur.fetchall()

                logger.info(f"Found {len(projects)} project(s) to process")
                logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
                logger.info("=" * 70)

                for proj in projects:
                    project_id = proj["id"]
                    sage_id = proj["sage_id"]
                    # Use oy_start_date as canonical anchor, fall back to cod_date
                    cod_date = proj["cod_date"]
                    if proj.get("oy_start_date"):
                        cod_date = date.fromisoformat(proj["oy_start_date"])

                    logger.info(f"\n--- {sage_id} (id={project_id}) ---")

                    result = extend_project(
                        cur, project_id, sage_id, org_id, cod_date, dry_run
                    )

                    report.projects_processed += 1

                    if result.skipped_reason:
                        report.projects_skipped += 1
                        logger.info(f"  SKIP: {result.skipped_reason}")
                    else:
                        report.projects_extended += 1
                        report.total_rows_inserted += result.months_to_extend
                        action = "would insert" if dry_run else "inserted"
                        logger.info(
                            f"  {action} {result.months_to_extend} months "
                            f"({result.last_existing_month} → {result.contract_end_month})"
                        )
                        logger.info(
                            f"  baseline_year={result.baseline_year}, "
                            f"degradation={result.degradation_pct} ({result.degradation_source})"
                        )
                        logger.info(f"  end_date via: {result.end_date_source}")

                    report.project_results.append(result)

                if not dry_run:
                    conn.commit()
                    logger.info(f"\nCommitted {report.total_rows_inserted} new forecast rows.")
                else:
                    logger.info(f"\nDRY RUN complete. Would insert {report.total_rows_inserted} rows.")

    finally:
        close_connection_pool()

    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"SUMMARY: {report.projects_extended} extended, "
                f"{report.projects_skipped} skipped, "
                f"{report.total_rows_inserted} rows {'to insert' if dry_run else 'inserted'}")
    logger.info("=" * 70)

    # Write report
    report_dir = project_root / "reports" / "cbe-population"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"extend_forecasts_{date.today().isoformat()}.json"
    with open(report_path, "w") as f:
        json.dump(_safe_json(report), f, indent=2)
    logger.info(f"Report written to: {report_path}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Extend production forecasts to contract end date"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Single project sage_id to process (e.g., GBL01)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to DB",
    )
    parser.add_argument(
        "--org-id",
        type=int,
        default=DEFAULT_ORG_ID,
        help="Organization ID (default: 1)",
    )
    args = parser.parse_args()

    run_extension(
        org_id=args.org_id,
        project_filter=args.project,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
