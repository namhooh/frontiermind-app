#!/usr/bin/env python3
"""
Populate performance data from the Operations Plant Performance Workbook.

Reads the Technical Model section of the workbook and populates:
  1. meter (Phase 1 + Phase 2)
  2. contract_line.meter_id FK updates
  3. production_forecast (monthly P50 forecasts)
  4. meter_aggregate (actual meter readings per phase)
  5. plant_performance (PR, availability, comparisons)

Usage:
    cd python-backend
    python scripts/populate_performance_data.py --project KAS01
    python scripts/populate_performance_data.py --project KAS01 --dry-run
    python scripts/populate_performance_data.py --all
"""

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import get_db_connection, init_connection_pool, close_connection_pool
from models.onboarding import TechnicalModelRow
from services.onboarding.parsers.plant_performance_parser import PlantPerformanceParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("populate_performance")

DEFAULT_ORG_ID = 1
WORKBOOK_PATH = os.path.join(
    project_root.parent, "CBE_data_extracts", "Operations Plant Performance Workbook.xlsx"
)

# ─── Project-specific meter/contract_line configuration ─────────────────
# Maps sage_id -> list of {name, serial_number, contract_line_numbers}
# contract_line_numbers: which contract_line_number(s) to link this meter to
PROJECT_METER_CONFIG: Dict[str, List[Dict[str, Any]]] = {
    "KAS01": [
        {
            "name": "Phase 1",
            "serial_number": "KAS01-P1",
            "meter_type": "production",
            "contract_line_numbers": [1000],  # Metered Energy Phase 1
        },
        {
            "name": "Phase 2",
            "serial_number": "KAS01-P2",
            "meter_type": "production",
            "contract_line_numbers": [4000],  # Metered Energy Phase 2
        },
    ],
}


def _period_end(bm: date) -> date:
    """Return the first day of the next month."""
    if bm.month == 12:
        return date(bm.year + 1, 1, 1)
    return date(bm.year, bm.month + 1, 1)


def _lookup_billing_period_id(cur, bm: date) -> Optional[int]:
    """Look up billing_period_id for a month, or None if not found."""
    cur.execute(
        "SELECT id FROM billing_period WHERE start_date = %(bm)s LIMIT 1",
        {"bm": bm},
    )
    row = cur.fetchone()
    return row["id"] if row else None


def populate_project(
    sage_id: str,
    tech_rows: List[TechnicalModelRow],
    site_params: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Populate all performance data for a single project.

    Returns summary dict with counts.
    """
    summary = {
        "sage_id": sage_id,
        "meters_created": 0,
        "contract_lines_linked": 0,
        "forecasts_upserted": 0,
        "meter_aggregates_upserted": 0,
        "plant_performance_upserted": 0,
        "errors": [],
    }

    if not tech_rows:
        summary["errors"].append("No Technical Model rows to populate")
        return summary

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # ─── Resolve project ──────────────────────────────────────
            cur.execute(
                "SELECT id, organization_id, installed_dc_capacity_kwp "
                "FROM project WHERE sage_id = %(sid)s",
                {"sid": sage_id},
            )
            proj = cur.fetchone()
            if not proj:
                summary["errors"].append(f"Project not found for sage_id={sage_id}")
                return summary

            project_id = proj["id"]
            org_id = proj["organization_id"]
            capacity_kwp = float(proj["installed_dc_capacity_kwp"]) if proj["installed_dc_capacity_kwp"] else None

            logger.info(f"Project {sage_id}: id={project_id}, org={org_id}, capacity={capacity_kwp}")

            # ─── Resolve contract ─────────────────────────────────────
            cur.execute(
                "SELECT id FROM contract WHERE project_id = %(pid)s LIMIT 1",
                {"pid": project_id},
            )
            contract_row = cur.fetchone()
            if not contract_row:
                summary["errors"].append(f"No contract found for project_id={project_id}")
                return summary
            contract_id = contract_row["id"]

            if dry_run:
                logger.info("[DRY RUN] Would populate data — listing planned actions:")
                logger.info(f"  Meters to create: {len(PROJECT_METER_CONFIG.get(sage_id, []))}")
                logger.info(f"  Forecast rows: {sum(1 for r in tech_rows if r.forecast_energy_combined_kwh)}")
                logger.info(f"  Actual rows: {sum(1 for r in tech_rows if r.total_metered_kwh or r.phase1_invoiced_kwh)}")
                return summary

            # ─── Step 1: Create meters ────────────────────────────────
            meter_config = PROJECT_METER_CONFIG.get(sage_id, [])
            meter_map: Dict[str, int] = {}  # meter name -> meter_id
            line_to_meter: Dict[int, int] = {}  # contract_line_number -> meter_id

            for mc in meter_config:
                # Check if meter already exists
                cur.execute(
                    "SELECT id FROM meter WHERE project_id = %(pid)s AND name = %(name)s",
                    {"pid": project_id, "name": mc["name"]},
                )
                existing = cur.fetchone()

                if existing:
                    meter_id = existing["id"]
                    logger.info(f"  Meter '{mc['name']}' already exists: id={meter_id}")
                else:
                    cur.execute(
                        """
                        INSERT INTO meter (project_id, name, serial_number, unit)
                        VALUES (%(pid)s, %(name)s, %(serial)s, 'kWh')
                        RETURNING id
                        """,
                        {"pid": project_id, "name": mc["name"], "serial": mc["serial_number"]},
                    )
                    meter_id = cur.fetchone()["id"]
                    summary["meters_created"] += 1
                    logger.info(f"  Created meter '{mc['name']}': id={meter_id}")

                meter_map[mc["name"]] = meter_id
                for cln in mc["contract_line_numbers"]:
                    line_to_meter[cln] = meter_id

            # ─── Step 2: Link contract_lines to meters ────────────────
            for cln, mid in line_to_meter.items():
                cur.execute(
                    """
                    UPDATE contract_line
                    SET meter_id = %(mid)s, updated_at = NOW()
                    WHERE contract_id = %(cid)s
                      AND contract_line_number = %(cln)s
                      AND (meter_id IS NULL OR meter_id != %(mid)s)
                    """,
                    {"mid": mid, "cid": contract_id, "cln": cln},
                )
                if cur.rowcount > 0:
                    summary["contract_lines_linked"] += cur.rowcount
                    logger.info(f"  Linked contract_line {cln} -> meter_id={mid}")

            conn.commit()

            # ─── Step 3: Populate production_forecast ─────────────────
            for row in tech_rows:
                if not row.forecast_energy_combined_kwh:
                    continue

                # Convert GHI/POA from Wh/m² to kWh/m² for production_forecast
                ghi_kwh = row.forecast_ghi_wm2 / 1000.0 if row.forecast_ghi_wm2 else None
                poa_kwh = row.forecast_poa_wm2 / 1000.0 if row.forecast_poa_wm2 else None

                # Compute degradation factor from operating year
                # Typical solar degradation is 0.3-0.7%/year
                degradation_pct = site_params.get("phases", {}).get("phase1", {}).get(
                    "degradation_pct",
                    site_params.get("degradation_pct", 0.4)
                )
                # Normalize to decimal fraction: 0.4 → 0.004 (0.4%/yr)
                if degradation_pct > 0.05:
                    degradation_pct = degradation_pct / 100.0
                degradation_factor = (1 - degradation_pct) ** (row.operating_year - 1)

                cur.execute(
                    """
                    INSERT INTO production_forecast (
                        project_id, organization_id, forecast_month, operating_year,
                        forecast_energy_kwh, forecast_ghi_irradiance, forecast_poa_irradiance,
                        forecast_pr, degradation_factor, forecast_source
                    ) VALUES (
                        %(pid)s, %(oid)s, %(fm)s, %(oy)s,
                        %(energy)s, %(ghi)s, %(poa)s,
                        %(pr)s, %(deg)s, 'p50'
                    )
                    ON CONFLICT (project_id, forecast_month) DO UPDATE SET
                        operating_year = EXCLUDED.operating_year,
                        forecast_energy_kwh = EXCLUDED.forecast_energy_kwh,
                        forecast_ghi_irradiance = EXCLUDED.forecast_ghi_irradiance,
                        forecast_poa_irradiance = EXCLUDED.forecast_poa_irradiance,
                        forecast_pr = EXCLUDED.forecast_pr,
                        degradation_factor = EXCLUDED.degradation_factor,
                        updated_at = NOW()
                    """,
                    {
                        "pid": project_id, "oid": org_id,
                        "fm": row.month, "oy": row.operating_year,
                        "energy": row.forecast_energy_combined_kwh,
                        "ghi": ghi_kwh, "poa": poa_kwh,
                        "pr": row.forecast_pr,
                        "deg": round(degradation_factor, 5),
                    },
                )
                summary["forecasts_upserted"] += 1

            conn.commit()
            logger.info(f"  Upserted {summary['forecasts_upserted']} production_forecast rows")

            # ─── Step 4: Populate meter_aggregate ─────────────────────
            phase1_meter_id = meter_map.get("Phase 1")
            phase2_meter_id = meter_map.get("Phase 2")

            # Look up contract_line IDs for FK
            cl_map: Dict[int, int] = {}  # contract_line_number -> contract_line.id
            cur.execute(
                "SELECT id, contract_line_number FROM contract_line WHERE contract_id = %(cid)s",
                {"cid": contract_id},
            )
            for cl_row in cur.fetchall():
                cl_map[cl_row["contract_line_number"]] = cl_row["id"]

            for row in tech_rows:
                has_phase1 = row.phase1_invoiced_kwh is not None
                has_phase2 = row.phase2_invoiced_kwh is not None
                if not has_phase1 and not has_phase2:
                    continue

                bp_id = _lookup_billing_period_id(cur, row.month)
                pe = _period_end(row.month)

                # Phase 1 meter_aggregate
                if phase1_meter_id and has_phase1:
                    cl_id = cl_map.get(1000)
                    summary["meter_aggregates_upserted"] += _upsert_meter_aggregate(
                        cur,
                        meter_id=phase1_meter_id,
                        org_id=org_id,
                        billing_period_id=bp_id,
                        contract_line_id=cl_id,
                        period_start=row.month,
                        period_end=pe,
                        energy_kwh=row.phase1_invoiced_kwh,
                        available_energy_kwh=row.available_energy_kwh,
                        opening_reading=row.phase1_meter_opening,
                        closing_reading=row.phase1_meter_closing,
                        ghi_irradiance_wm2=row.actual_ghi_wm2,
                        poa_irradiance_wm2=row.actual_poa_wm2,
                    )

                # Phase 2 meter_aggregate
                if phase2_meter_id and has_phase2:
                    cl_id = cl_map.get(4000)
                    summary["meter_aggregates_upserted"] += _upsert_meter_aggregate(
                        cur,
                        meter_id=phase2_meter_id,
                        org_id=org_id,
                        billing_period_id=bp_id,
                        contract_line_id=cl_id,
                        period_start=row.month,
                        period_end=pe,
                        energy_kwh=row.phase2_invoiced_kwh,
                        available_energy_kwh=None,
                        opening_reading=row.phase2_meter_opening,
                        closing_reading=row.phase2_meter_closing,
                        ghi_irradiance_wm2=None,
                        poa_irradiance_wm2=None,
                    )

            conn.commit()
            logger.info(f"  Upserted {summary['meter_aggregates_upserted']} meter_aggregate rows")

            # ─── Step 5: Populate plant_performance ───────────────────
            for row in tech_rows:
                # Need at least PR or availability or a comparison value
                has_perf = any([
                    row.actual_pr, row.actual_availability_pct,
                    row.energy_comparison, row.irr_comparison, row.pr_comparison,
                ])
                if not has_perf:
                    continue

                # Look up production_forecast_id for this month
                cur.execute(
                    "SELECT id FROM production_forecast WHERE project_id = %(pid)s AND forecast_month = %(fm)s",
                    {"pid": project_id, "fm": row.month},
                )
                fc_row = cur.fetchone()
                forecast_id = fc_row["id"] if fc_row else None

                bp_id = _lookup_billing_period_id(cur, row.month)

                cur.execute(
                    """
                    INSERT INTO plant_performance (
                        project_id, organization_id, billing_month, operating_year,
                        production_forecast_id, billing_period_id,
                        actual_pr, actual_availability_pct,
                        energy_comparison, irr_comparison, pr_comparison,
                        comments
                    ) VALUES (
                        %(pid)s, %(oid)s, %(bm)s, %(oy)s,
                        %(fc_id)s, %(bp_id)s,
                        %(pr)s, %(avail)s,
                        %(e_comp)s, %(i_comp)s, %(pr_comp)s,
                        %(comments)s
                    )
                    ON CONFLICT (project_id, billing_month) DO UPDATE SET
                        operating_year = EXCLUDED.operating_year,
                        production_forecast_id = COALESCE(EXCLUDED.production_forecast_id, plant_performance.production_forecast_id),
                        billing_period_id = COALESCE(EXCLUDED.billing_period_id, plant_performance.billing_period_id),
                        actual_pr = EXCLUDED.actual_pr,
                        actual_availability_pct = EXCLUDED.actual_availability_pct,
                        energy_comparison = EXCLUDED.energy_comparison,
                        irr_comparison = EXCLUDED.irr_comparison,
                        pr_comparison = EXCLUDED.pr_comparison,
                        comments = COALESCE(EXCLUDED.comments, plant_performance.comments),
                        updated_at = NOW()
                    """,
                    {
                        "pid": project_id, "oid": org_id,
                        "bm": row.month, "oy": row.operating_year,
                        "fc_id": forecast_id, "bp_id": bp_id,
                        "pr": row.actual_pr,
                        "avail": row.actual_availability_pct * 100 if row.actual_availability_pct else None,
                        "e_comp": row.energy_comparison,
                        "i_comp": row.irr_comparison,
                        "pr_comp": row.pr_comparison,
                        "comments": row.comments,
                    },
                )
                summary["plant_performance_upserted"] += 1

            conn.commit()
            logger.info(f"  Upserted {summary['plant_performance_upserted']} plant_performance rows")

    return summary


def _upsert_meter_aggregate(
    cur,
    meter_id: int,
    org_id: int,
    billing_period_id: Optional[int],
    contract_line_id: Optional[int],
    period_start: date,
    period_end: date,
    energy_kwh: Optional[float],
    available_energy_kwh: Optional[float],
    opening_reading: Optional[float],
    closing_reading: Optional[float],
    ghi_irradiance_wm2: Optional[float],
    poa_irradiance_wm2: Optional[float],
) -> int:
    """Upsert a meter_aggregate row. Returns 1 if upserted, 0 otherwise."""
    # Check for existing row by meter_id + period_start (handles rows with/without billing_period_id)
    cur.execute(
        """
        SELECT id FROM meter_aggregate
        WHERE meter_id = %(mid)s
          AND date_trunc('month', period_start) = %(ps)s
          AND COALESCE(contract_line_id, -1) = COALESCE(%(cl_id)s, -1)
        LIMIT 1
        """,
        {"mid": meter_id, "ps": period_start, "cl_id": contract_line_id},
    )
    existing = cur.fetchone()

    if existing:
        cur.execute(
            """
            UPDATE meter_aggregate SET
                energy_kwh = COALESCE(%(energy)s, energy_kwh),
                total_production = COALESCE(%(energy)s, total_production),
                available_energy_kwh = COALESCE(%(avail)s, available_energy_kwh),
                opening_reading = COALESCE(%(opening)s, opening_reading),
                closing_reading = COALESCE(%(closing)s, closing_reading),
                ghi_irradiance_wm2 = COALESCE(%(ghi)s, ghi_irradiance_wm2),
                poa_irradiance_wm2 = COALESCE(%(poa)s, poa_irradiance_wm2),
                billing_period_id = COALESCE(%(bp_id)s, billing_period_id),
                contract_line_id = COALESCE(%(cl_id)s, contract_line_id),
                source_system = 'workbook_import'
            WHERE id = %(id)s
            """,
            {
                "energy": energy_kwh, "avail": available_energy_kwh,
                "opening": opening_reading, "closing": closing_reading,
                "ghi": ghi_irradiance_wm2, "poa": poa_irradiance_wm2,
                "bp_id": billing_period_id, "cl_id": contract_line_id,
                "id": existing["id"],
            },
        )
    else:
        cur.execute(
            """
            INSERT INTO meter_aggregate (
                meter_id, organization_id, billing_period_id, contract_line_id,
                period_start, period_end,
                energy_kwh, total_production, available_energy_kwh,
                opening_reading, closing_reading,
                ghi_irradiance_wm2, poa_irradiance_wm2,
                period_type, source_system, unit
            ) VALUES (
                %(mid)s, %(oid)s, %(bp_id)s, %(cl_id)s,
                %(ps)s, %(pe)s,
                %(energy)s, %(energy)s, %(avail)s,
                %(opening)s, %(closing)s,
                %(ghi)s, %(poa)s,
                'monthly', 'workbook_import', 'kWh'
            )
            """,
            {
                "mid": meter_id, "oid": org_id,
                "bp_id": billing_period_id, "cl_id": contract_line_id,
                "ps": period_start, "pe": period_end,
                "energy": energy_kwh, "avail": available_energy_kwh,
                "opening": opening_reading, "closing": closing_reading,
                "ghi": ghi_irradiance_wm2, "poa": poa_irradiance_wm2,
            },
        )

    return 1


def main():
    parser = argparse.ArgumentParser(description="Populate performance data from workbook")
    parser.add_argument("--project", type=str, help="Sage ID to populate (e.g. KAS01)")
    parser.add_argument("--all", action="store_true", help="Populate all projects with Technical Model data")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    parser.add_argument("--workbook", type=str, default=WORKBOOK_PATH, help="Path to workbook")
    args = parser.parse_args()

    if not args.project and not args.all:
        parser.error("Must specify --project <SAGE_ID> or --all")

    if not os.path.exists(args.workbook):
        logger.error(f"Workbook not found: {args.workbook}")
        sys.exit(1)

    init_connection_pool(min_connections=1, max_connections=5)

    try:
        # Parse workbook
        logger.info(f"Parsing workbook: {args.workbook}")
        wb_parser = PlantPerformanceParser(args.workbook)
        data = wb_parser.parse(project_filter=args.project if args.project else None)

        if not data.technical_model:
            logger.warning("No Technical Model data found in workbook")
            # Fall back to generic projects data if available
            if data.projects:
                logger.info(f"Found keyword-based data for: {list(data.projects.keys())}")
            sys.exit(0)

        logger.info(f"Technical Model data found for: {list(data.technical_model.keys())}")

        # Populate each project
        results: Dict[str, Any] = {}
        projects_to_process = (
            list(data.technical_model.keys())
            if args.all
            else [args.project]
        )

        for sage_id in projects_to_process:
            tech_rows = data.technical_model.get(sage_id, [])
            site_params = data.site_parameters.get(sage_id, {})

            if not tech_rows:
                logger.warning(f"No Technical Model rows for {sage_id}, skipping")
                continue

            if sage_id not in PROJECT_METER_CONFIG:
                logger.warning(
                    f"No meter config for {sage_id} — add to PROJECT_METER_CONFIG to populate. Skipping."
                )
                continue

            logger.info(f"\n{'='*60}")
            logger.info(f"Populating {sage_id}: {len(tech_rows)} Technical Model rows")
            logger.info(f"{'='*60}")

            result = populate_project(
                sage_id=sage_id,
                tech_rows=tech_rows,
                site_params=site_params,
                dry_run=args.dry_run,
            )
            results[sage_id] = result

            if result["errors"]:
                logger.error(f"  Errors: {result['errors']}")

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("SUMMARY")
        logger.info(f"{'='*60}")
        for sid, r in results.items():
            logger.info(
                f"  {sid}: meters={r['meters_created']}, "
                f"lines_linked={r['contract_lines_linked']}, "
                f"forecasts={r['forecasts_upserted']}, "
                f"aggregates={r['meter_aggregates_upserted']}, "
                f"performance={r['plant_performance_upserted']}"
            )
            if r["errors"]:
                for e in r["errors"]:
                    logger.error(f"    ERROR: {e}")

        # Write report
        report_dir = os.path.join(project_root, "reports", "performance")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, "populate_summary.json")
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\nReport written to: {report_path}")

    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
