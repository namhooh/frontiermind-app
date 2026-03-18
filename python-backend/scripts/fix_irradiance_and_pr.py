#!/usr/bin/env python3
"""
Fix irradiance (GHI/POA) and PR values for all projects.

Root causes:
  1. Parser missed GHI irradiance — pattern "ghi irr phase" didn't match
     single-phase headers like "GHI Irr (Wh/m2)" (now fixed in parser).
  2. Step6 wrote POA in Wh/m² without converting to kWh/m².
  3. PR was hardcoded from PPW instead of calculated from formula.
  4. Multi-phase Phase 2 irradiance silently dropped — parser mapped both
     phases to the same field; first-match-wins dedup discarded Phase 2.

Fix:
  - Re-extract GHI and POA irradiance from PPW project tabs (Wh/m² → kWh/m²)
  - Calculate PR from formula: PR = forecast_energy_kwh / (irradiance_kWh_m2 × capacity_kWp)
  - PR naturally degrades because forecast_energy_kwh already incorporates degradation
  - Multi-phase projects: per-phase PR calculated and stored in source_metadata.phases

Usage:
    cd python-backend
    python scripts/fix_irradiance_and_pr.py --dry-run      # Preview
    python scripts/fix_irradiance_and_pr.py                  # Execute
    python scripts/fix_irradiance_and_pr.py --project LOI01  # Single project
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from psycopg2.extras import execute_values
from db.database import init_connection_pool, close_connection_pool, get_db_connection
from services.onboarding.parsers.plant_performance_parser import PlantPerformanceParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fix_irradiance_pr")

DEFAULT_ORG_ID = 1
WORKBOOK_PATH = os.path.join(
    project_root.parent, "CBE_data_extracts", "Operations Plant Performance Workbook.xlsx"
)

# Projects known to have multi-phase layouts in the PPW
MULTI_PHASE_SAGE_IDS = {"NBL01", "KAS01", "IVL01"}


@dataclass
class ProjectFixResult:
    sage_id: str
    rows_updated: int = 0
    is_multi_phase: bool = False
    ghi_source: str = ""  # "tech_model" or "none"
    poa_source: str = ""
    pr_method: str = ""   # "calculated" or "none"
    sample_month: Optional[str] = None
    sample_ghi: Optional[float] = None
    sample_poa: Optional[float] = None
    sample_pr_ghi: Optional[float] = None
    sample_pr_poa: Optional[float] = None
    errors: List[str] = field(default_factory=list)


class DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


def _get_phase_capacities(
    cur, project_id: int, total_capacity: float, site_params: dict
) -> Optional[Dict[str, float]]:
    """Get per-phase capacities from installed_capacity_breakdown or site_params."""
    # Try DB installed_capacity_breakdown JSONB first
    cur.execute(
        "SELECT installed_capacity_breakdown FROM project WHERE id = %s",
        (project_id,),
    )
    row = cur.fetchone()
    breakdown = row["installed_capacity_breakdown"] if row else None

    if breakdown and isinstance(breakdown, list) and len(breakdown) >= 2:
        caps = {}
        for entry in breakdown:
            label = str(entry.get("label", "")).lower()
            kwp = entry.get("kwp")
            if kwp is None:
                continue
            if "phase 1" in label or "phase1" in label:
                caps["phase1"] = float(kwp)
            elif "phase 2" in label or "phase2" in label:
                caps["phase2"] = float(kwp)
        if "phase1" in caps and "phase2" in caps:
            return caps

    # Fall back to site_params from PPW parser
    phases = site_params.get("phases", {})
    p1_cap = phases.get("phase1", {}).get("capacity_kwp")
    p2_cap = phases.get("phase2", {}).get("capacity_kwp")
    if p1_cap and p2_cap:
        return {"phase1": float(p1_cap), "phase2": float(p2_cap)}

    return None


def main():
    parser = argparse.ArgumentParser(description="Fix irradiance and PR for all projects")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--project", type=str, help="Single sage_id to process")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID)
    parser.add_argument("--workbook", type=str, default=WORKBOOK_PATH)
    args = parser.parse_args()

    logger.info(f"Fix Irradiance & PR {'(DRY RUN)' if args.dry_run else ''}")
    logger.info(f"Workbook: {args.workbook}")

    init_connection_pool()
    results: List[ProjectFixResult] = []

    try:
        # ── Phase 1: Parse PPW project tabs with fixed parser ──
        logger.info("Phase 1: Parsing PPW project tabs (with GHI + Phase 2 fix)...")
        ppw_parser = PlantPerformanceParser(args.workbook)
        ppw_data = ppw_parser.parse(project_filter=args.project)

        logger.info(
            f"  Parsed {len(ppw_data.technical_model)} projects with Technical Model data"
        )

        # ── Phase 2: For each project, update irradiance and calculate PR ──
        logger.info("Phase 2: Updating irradiance and calculating PR...")

        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout = '300000'")  # 5 min

                    # Get all projects with forecasts
                    cur.execute("""
                        SELECT p.id, p.sage_id, p.installed_dc_capacity_kwp
                        FROM project p
                        WHERE p.organization_id = %s
                          AND EXISTS (
                              SELECT 1 FROM production_forecast pf
                              WHERE pf.project_id = p.id
                          )
                        ORDER BY p.sage_id
                    """, (args.org_id,))
                    projects = cur.fetchall()

                    for proj in projects:
                        sage_id = proj["sage_id"]
                        project_id = proj["id"]
                        capacity_kwp = float(proj["installed_dc_capacity_kwp"]) if proj["installed_dc_capacity_kwp"] else None

                        if args.project and sage_id != args.project:
                            continue

                        result = ProjectFixResult(sage_id=sage_id)

                        # Get tech model rows from PPW
                        tech_rows = ppw_data.technical_model.get(sage_id, [])
                        if not tech_rows:
                            result.errors.append("No Technical Model data in PPW")
                            results.append(result)
                            logger.warning(f"  {sage_id}: No Technical Model data — skipping")
                            continue

                        if not capacity_kwp or capacity_kwp <= 0:
                            result.errors.append(f"Invalid capacity: {capacity_kwp}")
                            results.append(result)
                            logger.warning(f"  {sage_id}: No valid capacity — skipping")
                            continue

                        # Detect multi-phase project
                        site_params = ppw_data.site_parameters.get(sage_id, {})
                        has_phase2_irr = any(
                            tr.forecast_ghi_phase2_wm2 is not None or tr.forecast_poa_phase2_wm2 is not None
                            for tr in tech_rows
                        )
                        is_multi_phase = sage_id in MULTI_PHASE_SAGE_IDS or has_phase2_irr
                        result.is_multi_phase = is_multi_phase

                        phase_caps = None
                        if is_multi_phase:
                            phase_caps = _get_phase_capacities(cur, project_id, capacity_kwp, site_params)
                            if phase_caps:
                                logger.info(
                                    f"  {sage_id}: Multi-phase — "
                                    f"P1={phase_caps['phase1']} kWp, P2={phase_caps['phase2']} kWp"
                                )
                            else:
                                logger.warning(
                                    f"  {sage_id}: Multi-phase but no capacity breakdown found — "
                                    f"using total capacity for PR"
                                )

                        # Build lookup: month -> tech model row
                        tech_by_month: Dict[str, Any] = {}
                        for tr in tech_rows:
                            tech_by_month[tr.month.isoformat()] = tr

                        has_ghi = any(tr.forecast_ghi_wm2 is not None for tr in tech_rows)
                        has_poa = any(tr.forecast_poa_wm2 is not None for tr in tech_rows)
                        result.ghi_source = "tech_model" if has_ghi else "none"
                        result.poa_source = "tech_model" if has_poa else "none"

                        if not has_ghi and not has_poa:
                            result.errors.append("No irradiance data in Tech Model")
                            results.append(result)
                            logger.warning(f"  {sage_id}: No irradiance data — skipping")
                            continue

                        # Fetch existing forecast rows
                        cur.execute("""
                            SELECT id, forecast_month, forecast_energy_kwh,
                                   forecast_ghi_irradiance, forecast_poa_irradiance,
                                   source_metadata
                            FROM production_forecast
                            WHERE project_id = %s
                            ORDER BY forecast_month
                        """, (project_id,))
                        forecast_rows = cur.fetchall()

                        if not forecast_rows:
                            results.append(result)
                            continue

                        # Build batch updates: (id, ghi, poa, pr_ghi, pr_poa, source_metadata_json)
                        batch_updates: List[tuple] = []
                        sample_set = False

                        for row in forecast_rows:
                            fid = row["id"]
                            month_key = row["forecast_month"].isoformat()
                            energy_kwh = float(row["forecast_energy_kwh"]) if row["forecast_energy_kwh"] else None

                            tr = tech_by_month.get(month_key)

                            # Get Phase 1 irradiance from PPW Tech Model
                            ghi_wm2 = tr.forecast_ghi_wm2 if tr else None
                            poa_wm2 = tr.forecast_poa_wm2 if tr else None

                            # Convert Wh/m² to kWh/m²
                            ghi_kwh = ghi_wm2 / 1000.0 if ghi_wm2 else None
                            poa_kwh = poa_wm2 / 1000.0 if poa_wm2 else None

                            # Fall back to existing DB values if PPW didn't have data
                            existing_ghi = float(row["forecast_ghi_irradiance"]) if row["forecast_ghi_irradiance"] else None
                            existing_poa = float(row["forecast_poa_irradiance"]) if row["forecast_poa_irradiance"] else None

                            # Use new value if available, otherwise keep existing
                            # Fix existing values if stored in Wh/m² (>1000 means wrong unit)
                            if ghi_kwh:
                                final_ghi = ghi_kwh
                            elif existing_ghi and existing_ghi > 1000:
                                final_ghi = existing_ghi / 1000.0
                            else:
                                final_ghi = existing_ghi

                            if poa_kwh:
                                final_poa = poa_kwh
                            elif existing_poa and existing_poa > 1000:
                                final_poa = existing_poa / 1000.0
                            else:
                                final_poa = existing_poa

                            # Calculate PR from formula:
                            #   PR = forecast_energy_kwh / (irradiance_kWh_m2 × capacity_kWp)
                            pr_ghi = None
                            pr_poa = None
                            if energy_kwh and final_ghi and capacity_kwp:
                                pr_ghi = energy_kwh / (final_ghi * capacity_kwp)
                            if energy_kwh and final_poa and capacity_kwp:
                                pr_poa = energy_kwh / (final_poa * capacity_kwp)

                            # Build source_metadata with phase data for multi-phase projects
                            existing_meta = row["source_metadata"] or {}
                            if isinstance(existing_meta, str):
                                existing_meta = json.loads(existing_meta)
                            updated_meta = dict(existing_meta)

                            if is_multi_phase and tr and phase_caps:
                                p1_cap = phase_caps["phase1"]
                                p2_cap = phase_caps["phase2"]
                                p1_energy = tr.forecast_energy_phase1_kwh
                                p2_energy = tr.forecast_energy_phase2_kwh
                                p1_ghi_wm2 = tr.forecast_ghi_wm2
                                p2_ghi_wm2 = tr.forecast_ghi_phase2_wm2
                                p1_poa_wm2 = tr.forecast_poa_wm2
                                p2_poa_wm2 = tr.forecast_poa_phase2_wm2

                                p1_ghi_kwh = p1_ghi_wm2 / 1000.0 if p1_ghi_wm2 else None
                                p2_ghi_kwh = p2_ghi_wm2 / 1000.0 if p2_ghi_wm2 else None
                                p1_poa_kwh = p1_poa_wm2 / 1000.0 if p1_poa_wm2 else None
                                p2_poa_kwh = p2_poa_wm2 / 1000.0 if p2_poa_wm2 else None

                                phase1_data: Dict[str, Any] = {"capacity_kwp": p1_cap}
                                phase2_data: Dict[str, Any] = {"capacity_kwp": p2_cap}

                                if p1_ghi_kwh is not None:
                                    phase1_data["ghi_kwh_m2"] = round(p1_ghi_kwh, 3)
                                if p1_poa_kwh is not None:
                                    phase1_data["poa_kwh_m2"] = round(p1_poa_kwh, 3)
                                if p1_energy is not None:
                                    phase1_data["energy_kwh"] = round(p1_energy, 2)
                                    if p1_ghi_kwh and p1_cap:
                                        phase1_data["pr_ghi"] = round(p1_energy / (p1_ghi_kwh * p1_cap), 4)
                                    if p1_poa_kwh and p1_cap:
                                        phase1_data["pr_poa"] = round(p1_energy / (p1_poa_kwh * p1_cap), 4)

                                if p2_ghi_kwh is not None:
                                    phase2_data["ghi_kwh_m2"] = round(p2_ghi_kwh, 3)
                                if p2_poa_kwh is not None:
                                    phase2_data["poa_kwh_m2"] = round(p2_poa_kwh, 3)
                                if p2_energy is not None:
                                    phase2_data["energy_kwh"] = round(p2_energy, 2)
                                    if p2_ghi_kwh and p2_cap:
                                        phase2_data["pr_ghi"] = round(p2_energy / (p2_ghi_kwh * p2_cap), 4)
                                    if p2_poa_kwh and p2_cap:
                                        phase2_data["pr_poa"] = round(p2_energy / (p2_poa_kwh * p2_cap), 4)

                                updated_meta["phases"] = {
                                    "phase1": phase1_data,
                                    "phase2": phase2_data,
                                }
                                updated_meta["pr_formula"] = "forecast_energy_kwh / (irradiance_kwh_m2 * capacity_kwp)"

                            meta_json = json.dumps(updated_meta, cls=DateEncoder) if updated_meta != existing_meta else None

                            batch_updates.append((
                                fid,
                                final_ghi,
                                final_poa,
                                pr_ghi,
                                pr_poa,
                                meta_json,
                            ))

                            # Capture sample for reporting
                            if not sample_set:
                                result.sample_month = month_key
                                result.sample_ghi = round(final_ghi, 2) if final_ghi else None
                                result.sample_poa = round(final_poa, 2) if final_poa else None
                                result.sample_pr_ghi = round(pr_ghi, 4) if pr_ghi else None
                                result.sample_pr_poa = round(pr_poa, 4) if pr_poa else None
                                sample_set = True

                        if batch_updates:
                            result.pr_method = "calculated"
                            if not args.dry_run:
                                # Split into rows with/without metadata updates
                                meta_updates = [(r[0], r[5]) for r in batch_updates if r[5] is not None]
                                irr_updates = [(r[0], r[1], r[2], r[3], r[4]) for r in batch_updates]

                                execute_values(
                                    cur,
                                    """
                                    UPDATE production_forecast AS pf SET
                                        forecast_ghi_irradiance = v.ghi::numeric,
                                        forecast_poa_irradiance = v.poa::numeric,
                                        forecast_pr = v.pr_ghi::numeric,
                                        forecast_pr_poa = v.pr_poa::numeric,
                                        updated_at = NOW()
                                    FROM (VALUES %s) AS v(id, ghi, poa, pr_ghi, pr_poa)
                                    WHERE pf.id = v.id::bigint
                                    """,
                                    irr_updates,
                                    page_size=200,
                                )

                                if meta_updates:
                                    execute_values(
                                        cur,
                                        """
                                        UPDATE production_forecast AS pf SET
                                            source_metadata = v.meta::jsonb,
                                            updated_at = NOW()
                                        FROM (VALUES %s) AS v(id, meta)
                                        WHERE pf.id = v.id::bigint
                                        """,
                                        meta_updates,
                                        page_size=200,
                                    )

                            result.rows_updated = len(batch_updates)

                        results.append(result)
                        phase_label = " [MULTI-PHASE]" if is_multi_phase else ""
                        logger.info(
                            f"  {sage_id}{phase_label}: {result.rows_updated} rows | "
                            f"GHI={result.sample_ghi} POA={result.sample_poa} | "
                            f"PR_GHI={result.sample_pr_ghi} PR_POA={result.sample_pr_poa}"
                        )

                if not args.dry_run:
                    conn.commit()
                    logger.info("Changes committed.")
                else:
                    conn.rollback()
                    logger.info("DRY RUN — no changes committed.")

            except Exception:
                conn.rollback()
                raise

        # ── Summary ──
        logger.info("=" * 80)
        logger.info(f"Fix Irradiance & PR {'(DRY RUN) ' if args.dry_run else ''}Complete")
        total_updated = sum(r.rows_updated for r in results)
        projects_fixed = sum(1 for r in results if r.rows_updated > 0)
        projects_skipped = sum(1 for r in results if r.rows_updated == 0)
        multi_phase_count = sum(1 for r in results if r.is_multi_phase)
        logger.info(f"  Projects fixed: {projects_fixed} ({multi_phase_count} multi-phase)")
        logger.info(f"  Projects skipped: {projects_skipped}")
        logger.info(f"  Total rows updated: {total_updated}")

        # Show projects where GHI != POA (distinct values)
        logger.info("\nIrradiance comparison (first month):")
        logger.info(f"  {'SAGE_ID':<10} {'GHI kWh/m²':<14} {'POA kWh/m²':<14} {'PR GHI':<10} {'PR POA':<10} {'GHI≠POA?':<10} {'Phases':<8}")
        for r in sorted(results, key=lambda x: x.sage_id):
            if r.rows_updated == 0:
                continue
            diff = "YES" if (r.sample_ghi and r.sample_poa and abs(r.sample_ghi - r.sample_poa) > 0.01) else "same"
            phases = "2" if r.is_multi_phase else "1"
            logger.info(
                f"  {r.sage_id:<10} {str(r.sample_ghi):<14} {str(r.sample_poa):<14} "
                f"{str(r.sample_pr_ghi):<10} {str(r.sample_pr_poa):<10} {diff:<10} {phases:<8}"
            )

        # Report errors
        errors = [(r.sage_id, e) for r in results for e in r.errors]
        if errors:
            logger.info(f"\nErrors ({len(errors)}):")
            for sid, e in errors:
                logger.info(f"  {sid}: {e}")

        # Write report
        report_dir = project_root / "reports" / "cbe-population"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"fix_irradiance_pr_{date.today().isoformat()}.json"
        with open(report_path, "w") as f:
            json.dump([asdict(r) for r in results], f, indent=2, cls=DateEncoder)
        logger.info(f"\nReport: {report_path}")

    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
