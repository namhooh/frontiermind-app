#!/usr/bin/env python3
"""
Step 9D: Plant Performance Enrichment from PPW Project Tabs.

Populates plant_performance AND meter_aggregate from the PPW Technical Model.

Phase 1 — plant_performance:
  Enriches existing rows (created by Step 9 Phase C) with actual_pr,
  actual_availability_pct, irr_comparison, pr_comparison, and comments.
  Inserts new rows for months not yet in the DB.

Phase 2 — meter_aggregate:
  For single-meter projects: writes PPW total_metered_kwh → energy_kwh,
  available_energy_kwh → available meter.
  For dual-phase projects: writes phase1/phase2 invoiced → respective meters.
  For all projects: writes PPW actual irradiance → ghi/poa_irradiance_wm2.

Prerequisite: Step 9 Phase C must have run first (creates plant_performance rows).

Usage:
    cd python-backend
    python scripts/step9d_plant_performance_enrichment.py --dry-run        # Preview
    python scripts/step9d_plant_performance_enrichment.py                   # Execute all
    python scripts/step9d_plant_performance_enrichment.py --project KAS01   # Single project
"""

import argparse
import json
import logging
import os
import sys
from calendar import monthrange
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
from services.onboarding.parsers.plant_performance_parser import PlantPerformanceParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("step9d_plant_performance")

DEFAULT_ORG_ID = 1
WORKBOOK_PATH = os.path.join(
    project_root.parent, "CBE_data_extracts", "Operations Plant Performance Workbook.xlsx"
)
REPORT_DIR = project_root / "reports" / "cbe-population"


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class Discrepancy:
    severity: str       # "critical" | "warning" | "info"
    category: str
    project: str
    field: str
    source_a: str       # PPW value
    source_b: str       # DB value
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
    forecast_upserted: int = 0
    rows_enriched: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    rows_no_data: int = 0
    tech_rows_parsed: int = 0
    meter_energy_written: int = 0
    meter_irradiance_written: int = 0
    discrepancies: List[Discrepancy] = field(default_factory=list)


@dataclass
class StepReport:
    step: str = "9d"
    step_name: str = "Plant Performance Enrichment from PPW Project Tabs"
    status: str = "passed"
    projects_processed: int = 0
    total_forecast_upserted: int = 0
    total_rows_enriched: int = 0
    total_rows_inserted: int = 0
    total_meter_energy: int = 0
    total_meter_irradiance: int = 0
    discrepancies: List[Discrepancy] = field(default_factory=list)
    gate_checks: List[GateCheck] = field(default_factory=list)
    project_results: List[ProjectResult] = field(default_factory=list)


class DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return super().default(o)


# =============================================================================
# Processing
# =============================================================================

def _has_any_perf_data(tr) -> bool:
    """Check if a TechnicalModelRow has at least one plant_performance field value."""
    return any([
        tr.actual_pr is not None,
        tr.actual_availability_pct is not None,
        tr.energy_comparison is not None,
        tr.irr_comparison is not None,
        tr.pr_comparison is not None,
        tr.comments is not None,
    ])


# Dual-phase projects where PPW has phase1_invoiced_kwh / phase2_invoiced_kwh
DUAL_PHASE_PROJECTS = {"KAS01", "IVL01", "NBL01"}

# Named sub-meter mapping: sage_id -> {ppw_header_fragment (lowered): DB product_desc fragment}
# Verified against actual DB product_desc values 2026-03-17
METER_NAME_MAP: Dict[str, Dict[str, str]] = {
    "LOI01": {"hq": "HQ", "tc": "Camp"},
    "GC001": {"sub-1": "Substation 1", "sub-3": "Substation 3"},
    "JAB01": {"generator": "Generator", "grid": "Grid"},
    "QMM01": {"ohl": "Expanded PV", "wind": "Wind"},
    "MOH01": {"ppl1": "PPL1", "ppl2": "PPL2", "bottles": "Bottles", "bbm1": "BBM1", "bbm2": "BBM2"},
    "UNSOS": {"logistics": "Logistics", "ph-7": "Powerhouse 7", "ph-17": "Powerhouse 17", "ph-20": "Powerhouse 20"},
    # Dual-site projects
    "MB01": {"site a": "Site A", "site b": "Site B"},
    "MF01": {"site a": "Site A", "site b": "Site B"},
    "MP02": {"site a": "Site A", "site b": "Site B"},
}

# Dual-site projects — treated same as named (sub-meter matching via METER_NAME_MAP)
DUAL_SITE_PROJECTS = {"MB01", "MF01", "MP02"}


def _classify_meter_layout(sage_id: str, contract_lines: List[Dict]) -> str:
    """Classify the meter layout for a project based on its contract_lines.

    Returns: 'single', 'dual_phase', 'named', 'dual_site', or 'skip'.
    """
    metered_lines = [cl for cl in contract_lines if cl["energy_category"] == "metered"]

    if sage_id in DUAL_PHASE_PROJECTS:
        return "dual_phase" if len(metered_lines) >= 2 else "single"
    if sage_id in DUAL_SITE_PROJECTS:
        return "dual_site" if len(metered_lines) >= 2 else "single"
    if sage_id in METER_NAME_MAP:
        return "named" if len(metered_lines) >= 2 else "single"

    if len(metered_lines) == 1:
        return "single"
    if len(metered_lines) == 0:
        return "skip"

    return "skip"


def _populate_meter_aggregate(
    sage_id: str,
    tech_rows: list,
    project_id: int,
    org_id: int,
    bp_by_month: Dict[str, int],
    cur,
    dry_run: bool,
    result: "ProjectResult",
) -> None:
    """Populate meter_aggregate energy_kwh, available_energy_kwh, and irradiance from PPW."""

    # 1. Load contract lines for this project (via contract → project)
    cur.execute("""
        SELECT cl.id, cl.contract_line_number, cl.product_desc,
               cl.energy_category, cl.meter_id, cl.clause_tariff_id
        FROM contract_line cl
        JOIN contract c ON cl.contract_id = c.id
        WHERE c.project_id = %s AND cl.is_active = true
        ORDER BY cl.contract_line_number
    """, (project_id,))
    contract_lines = [dict(r) for r in cur.fetchall()]

    if not contract_lines:
        return

    metered_lines = [cl for cl in contract_lines if cl["energy_category"] == "metered"]
    available_lines = [cl for cl in contract_lines if cl["energy_category"] == "available"]

    layout = _classify_meter_layout(sage_id, contract_lines)
    logger.debug(f"  {sage_id}: meter layout={layout}, metered_lines={len(metered_lines)}, available_lines={len(available_lines)}")

    # 2. Load existing meter_aggregate rows for dedup check
    cl_ids = [cl["id"] for cl in contract_lines]
    if cl_ids:
        cur.execute("""
            SELECT id, contract_line_id, billing_period_id,
                   energy_kwh, available_energy_kwh,
                   ghi_irradiance_wm2, poa_irradiance_wm2
            FROM meter_aggregate
            WHERE contract_line_id = ANY(%s)
              AND period_type = 'monthly'
        """, (cl_ids,))
        existing_ma = {}
        for r in cur.fetchall():
            key = (r["contract_line_id"], r["billing_period_id"])
            existing_ma[key] = dict(r)
    else:
        existing_ma = {}

    # 3. For irradiance, pick a reference contract_line (first metered, or first available)
    irradiance_cl = metered_lines[0] if metered_lines else (available_lines[0] if available_lines else None)

    # 4. Process each tech row
    for tr in tech_rows:
        month_key = tr.month.isoformat()
        bp_id = bp_by_month.get(month_key)
        if not bp_id:
            continue

        # --- Energy population ---
        if layout == "single" and metered_lines:
            cl = metered_lines[0]
            _upsert_meter_energy(
                cur, existing_ma, cl, bp_id, org_id,
                tr.total_metered_kwh, tr.month, dry_run, result,
            )

        elif layout == "dual_phase":
            # Phase 1 → first metered line, Phase 2 → second metered line
            if len(metered_lines) >= 1 and tr.phase1_invoiced_kwh is not None:
                _upsert_meter_energy(
                    cur, existing_ma, metered_lines[0], bp_id, org_id,
                    tr.phase1_invoiced_kwh, tr.month, dry_run, result,
                )
            if len(metered_lines) >= 2 and tr.phase2_invoiced_kwh is not None:
                _upsert_meter_energy(
                    cur, existing_ma, metered_lines[1], bp_id, org_id,
                    tr.phase2_invoiced_kwh, tr.month, dry_run, result,
                )

        elif layout in ("named", "dual_site"):
            # Try per-sub-meter matching via sub_meter_kwh dict
            name_map = METER_NAME_MAP.get(sage_id, {})
            matched_any = False
            if tr.sub_meter_kwh and name_map:
                for header, kwh_val in tr.sub_meter_kwh.items():
                    if kwh_val is None:
                        continue
                    header_lower = header.lower()
                    # Find which name_map fragment matches this header
                    for frag, db_desc_frag in name_map.items():
                        if frag in header_lower:
                            # Find the DB contract_line whose product_desc contains db_desc_frag
                            target_cl = None
                            for cl in metered_lines:
                                if cl.get("product_desc") and db_desc_frag.lower() in cl["product_desc"].lower():
                                    target_cl = cl
                                    break
                            if target_cl:
                                _upsert_meter_energy(
                                    cur, existing_ma, target_cl, bp_id, org_id,
                                    kwh_val, tr.month, dry_run, result,
                                )
                                matched_any = True
                            break

            # Also write total_metered_kwh to first metered line if only one
            if not matched_any and len(metered_lines) == 1 and tr.total_metered_kwh is not None:
                _upsert_meter_energy(
                    cur, existing_ma, metered_lines[0], bp_id, org_id,
                    tr.total_metered_kwh, tr.month, dry_run, result,
                )

        # Available energy → available contract_line
        if available_lines and tr.available_energy_kwh is not None:
            _upsert_meter_available(
                cur, existing_ma, available_lines[0], bp_id, org_id,
                tr.available_energy_kwh, tr.month, dry_run, result,
            )

        # --- Irradiance population ---
        if irradiance_cl and (tr.actual_ghi_wm2 is not None or tr.actual_poa_wm2 is not None):
            _upsert_meter_irradiance(
                cur, existing_ma, irradiance_cl, bp_id, org_id,
                tr.actual_ghi_wm2, tr.actual_poa_wm2, tr.month, dry_run, result,
            )


def _period_end(bm: date) -> date:
    """Return first day of next month."""
    if bm.month == 12:
        return date(bm.year + 1, 1, 1)
    return date(bm.year, bm.month + 1, 1)


def _upsert_meter_energy(
    cur, existing_ma: Dict, cl: Dict, bp_id: int, org_id: int,
    energy_kwh: Optional[float], billing_month: date,
    dry_run: bool, result: "ProjectResult",
) -> None:
    """Write PPW energy_kwh to meter_aggregate for a metered contract_line."""
    if energy_kwh is None:
        return

    key = (cl["id"], bp_id)
    existing = existing_ma.get(key)

    if existing and existing["energy_kwh"] is not None:
        return  # Don't overwrite existing data

    if dry_run:
        result.meter_energy_written += 1
        return

    if existing:
        # UPDATE existing row — fill NULL energy_kwh
        cur.execute("""
            UPDATE meter_aggregate
            SET energy_kwh = %(val)s, source_system = COALESCE(source_system, 'ppw')
            WHERE id = %(ma_id)s AND energy_kwh IS NULL
        """, {"val": round(energy_kwh, 2), "ma_id": existing["id"]})
    else:
        # INSERT new row — include period_start/period_end for the Performance API query
        cur.execute("""
            INSERT INTO meter_aggregate (
                billing_period_id, contract_line_id, meter_id,
                clause_tariff_id, period_type,
                period_start, period_end,
                energy_kwh, source_system, organization_id, unit
            ) VALUES (
                %(bp)s, %(cl)s, %(mid)s,
                %(ct)s, 'monthly',
                %(ps)s, %(pe)s,
                %(val)s, 'ppw', %(oid)s, 'kWh'
            )
            ON CONFLICT DO NOTHING
        """, {
            "bp": bp_id,
            "cl": cl["id"],
            "mid": cl["meter_id"],
            "ct": cl["clause_tariff_id"],
            "ps": billing_month,
            "pe": _period_end(billing_month),
            "val": round(energy_kwh, 2),
            "oid": org_id,
        })

    result.meter_energy_written += 1


def _upsert_meter_available(
    cur, existing_ma: Dict, cl: Dict, bp_id: int, org_id: int,
    available_kwh: Optional[float], billing_month: date,
    dry_run: bool, result: "ProjectResult",
) -> None:
    """Write PPW available_energy_kwh to meter_aggregate for an available contract_line."""
    if available_kwh is None:
        return

    key = (cl["id"], bp_id)
    existing = existing_ma.get(key)

    if existing and existing["available_energy_kwh"] is not None:
        return

    if dry_run:
        result.meter_energy_written += 1
        return

    if existing:
        cur.execute("""
            UPDATE meter_aggregate
            SET available_energy_kwh = %(val)s, source_system = COALESCE(source_system, 'ppw')
            WHERE id = %(ma_id)s AND available_energy_kwh IS NULL
        """, {"val": round(available_kwh, 2), "ma_id": existing["id"]})
    else:
        cur.execute("""
            INSERT INTO meter_aggregate (
                billing_period_id, contract_line_id, meter_id,
                clause_tariff_id, period_type,
                period_start, period_end,
                available_energy_kwh, source_system, organization_id, unit
            ) VALUES (
                %(bp)s, %(cl)s, %(mid)s,
                %(ct)s, 'monthly',
                %(ps)s, %(pe)s,
                %(val)s, 'ppw', %(oid)s, 'kWh'
            )
            ON CONFLICT DO NOTHING
        """, {
            "bp": bp_id,
            "cl": cl["id"],
            "mid": cl["meter_id"],
            "ct": cl["clause_tariff_id"],
            "ps": billing_month,
            "pe": _period_end(billing_month),
            "val": round(available_kwh, 2),
            "oid": org_id,
        })

    result.meter_energy_written += 1


def _upsert_meter_irradiance(
    cur, existing_ma: Dict, cl: Dict, bp_id: int, org_id: int,
    ghi_wm2: Optional[float], poa_wm2: Optional[float],
    billing_month: date, dry_run: bool, result: "ProjectResult",
) -> None:
    """Write PPW actual irradiance to meter_aggregate."""
    key = (cl["id"], bp_id)
    existing = existing_ma.get(key)

    # Only write if at least one value is new
    ghi_new = ghi_wm2 is not None and (not existing or existing.get("ghi_irradiance_wm2") is None)
    poa_new = poa_wm2 is not None and (not existing or existing.get("poa_irradiance_wm2") is None)

    if not ghi_new and not poa_new:
        return

    if dry_run:
        result.meter_irradiance_written += 1
        return

    if existing:
        sets = []
        params: Dict[str, Any] = {"ma_id": existing["id"]}
        if ghi_new:
            sets.append("ghi_irradiance_wm2 = %(ghi)s")
            params["ghi"] = round(ghi_wm2, 2)
        if poa_new:
            sets.append("poa_irradiance_wm2 = %(poa)s")
            params["poa"] = round(poa_wm2, 2)
        if sets:
            cur.execute(
                f"UPDATE meter_aggregate SET {', '.join(sets)} WHERE id = %(ma_id)s",
                params,
            )
    else:
        cur.execute("""
            INSERT INTO meter_aggregate (
                billing_period_id, contract_line_id, meter_id,
                clause_tariff_id, period_type,
                period_start, period_end,
                ghi_irradiance_wm2, poa_irradiance_wm2,
                source_system, organization_id
            ) VALUES (
                %(bp)s, %(cl)s, %(mid)s,
                %(ct)s, 'monthly',
                %(ps)s, %(pe)s,
                %(ghi)s, %(poa)s,
                'ppw', %(oid)s
            )
            ON CONFLICT DO NOTHING
        """, {
            "bp": bp_id,
            "cl": cl["id"],
            "mid": cl["meter_id"],
            "ct": cl["clause_tariff_id"],
            "ps": billing_month,
            "pe": _period_end(billing_month),
            "ghi": round(ghi_wm2, 2) if ghi_wm2 is not None else None,
            "poa": round(poa_wm2, 2) if poa_wm2 is not None else None,
            "oid": org_id,
        })

    result.meter_irradiance_written += 1


def _f(v) -> Optional[float]:
    """Coerce Decimal/int/float to float, None passthrough."""
    if v is None:
        return None
    return float(v)


def _compute_pr(total_energy_kwh, ghi_wm2, capacity_kwp) -> Optional[float]:
    """PR = total_energy / (GHI_kWh_m2 * capacity_kWp).

    PPW stores GHI in Wh/m², so divide by 1000 to get kWh/m².
    """
    e, g, c = _f(total_energy_kwh), _f(ghi_wm2), _f(capacity_kwp)
    if not e or not g or not c:
        return None
    ghi_kwh = g / 1000.0
    if ghi_kwh <= 0 or c <= 0:
        return None
    pr = e / (ghi_kwh * c)
    return pr if 0 < pr < 2.0 else None  # sanity bound


def _compute_comparison(actual, forecast) -> Optional[float]:
    """Comparison ratio = actual / forecast."""
    a, f = _f(actual), _f(forecast)
    if a is None or f is None or f == 0:
        return None
    ratio = a / f
    return ratio if 0 < ratio < 5.0 else None  # sanity bound


def process_project(
    sage_id: str,
    tech_rows: list,
    site_params: dict,
    org_id: int,
    dry_run: bool,
) -> ProjectResult:
    """Full PPW → DB pipeline for one project.

    Phase 0: production_forecast — UPSERT forecast rows from PPW.
    Phase 1: plant_performance — enrichment + formula-based computation.
    Phase 2: meter_aggregate — energy (with named sub-meters) + irradiance.
    """
    result = ProjectResult(sage_id=sage_id, tech_rows_parsed=len(tech_rows))

    with get_db_connection() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '0'")

                # ── 0. Look up project + capacity ──
                cur.execute("""
                    SELECT id, cod_date, installed_dc_capacity_kwp
                    FROM project
                    WHERE sage_id = %s AND organization_id = %s
                """, (sage_id, org_id))
                proj = cur.fetchone()
                if not proj:
                    result.discrepancies.append(Discrepancy(
                        severity="info", category="missing_project",
                        project=sage_id, field="project",
                        source_a=sage_id, source_b="NOT FOUND",
                        recommended_action="PPW tab has no matching FM project — skip",
                    ))
                    conn.commit()
                    return result

                project_id = proj["id"]
                result.project_id = project_id
                capacity_kwp = float(proj["installed_dc_capacity_kwp"]) if proj.get("installed_dc_capacity_kwp") else None
                # Fallback: capacity from PPW site_params
                if not capacity_kwp and site_params.get("capacity_kwp"):
                    capacity_kwp = site_params["capacity_kwp"]

                # Pre-load billing_period lookup
                cur.execute("SELECT id, start_date FROM billing_period")
                bp_by_month = {
                    r["start_date"].isoformat(): r["id"]
                    for r in cur.fetchall()
                }

                # ── Phase 0: production_forecast ──
                cur.execute("""
                    SELECT id, forecast_month,
                           forecast_energy_kwh, forecast_ghi_irradiance,
                           forecast_poa_irradiance, forecast_pr, forecast_pr_poa,
                           operating_year
                    FROM production_forecast
                    WHERE project_id = %s
                """, (project_id,))
                fc_rows = {
                    r["forecast_month"].isoformat(): dict(r)
                    for r in cur.fetchall()
                }

                for tr in tech_rows:
                    month_key = tr.month.isoformat()
                    bp_id = bp_by_month.get(month_key)
                    existing_fc = fc_rows.get(month_key)

                    # Determine forecast energy: combined > phase1+phase2
                    fc_energy = tr.forecast_energy_combined_kwh
                    if fc_energy is None and tr.forecast_energy_phase1_kwh is not None:
                        fc_energy = (tr.forecast_energy_phase1_kwh or 0) + (tr.forecast_energy_phase2_kwh or 0)

                    # Convert irradiance: PPW Wh/m² → DB kWh/m²
                    fc_ghi = tr.forecast_ghi_wm2 / 1000.0 if tr.forecast_ghi_wm2 else None
                    fc_poa = tr.forecast_poa_wm2 / 1000.0 if tr.forecast_poa_wm2 else None

                    # Compute PR from formula if PPW didn't provide it
                    fc_pr = tr.forecast_pr
                    if fc_pr is None and fc_energy and fc_ghi and capacity_kwp:
                        fc_pr = fc_energy / (fc_ghi * capacity_kwp) if fc_ghi > 0 else None
                    fc_pr_poa = tr.forecast_pr_poa
                    if fc_pr_poa is None and fc_energy and fc_poa and capacity_kwp:
                        fc_pr_poa = fc_energy / (fc_poa * capacity_kwp) if fc_poa > 0 else None

                    has_forecast = fc_energy is not None

                    if existing_fc:
                        # UPDATE NULLs only
                        updates = {}
                        if existing_fc["forecast_ghi_irradiance"] is None and fc_ghi is not None:
                            updates["forecast_ghi_irradiance"] = round(fc_ghi, 4)
                        if existing_fc["forecast_poa_irradiance"] is None and fc_poa is not None:
                            updates["forecast_poa_irradiance"] = round(fc_poa, 4)
                        if existing_fc["forecast_pr"] is None and fc_pr is not None:
                            updates["forecast_pr"] = round(fc_pr, 4)
                        if existing_fc["forecast_pr_poa"] is None and fc_pr_poa is not None:
                            updates["forecast_pr_poa"] = round(fc_pr_poa, 4)
                        if existing_fc["operating_year"] is None:
                            updates["operating_year"] = tr.operating_year

                        if updates and not dry_run:
                            set_clauses = ", ".join(f"{col} = %({col})s" for col in updates)
                            updates["fc_id"] = existing_fc["id"]
                            cur.execute(
                                f"UPDATE production_forecast SET {set_clauses}, updated_at = NOW() WHERE id = %(fc_id)s",
                                updates,
                            )
                            result.forecast_upserted += 1
                        # Update local cache so Phase 1 sees it
                        for k, v in updates.items():
                            existing_fc[k] = v

                    elif has_forecast:
                        # INSERT new forecast row
                        if not dry_run:
                            cur.execute("""
                                INSERT INTO production_forecast (
                                    project_id, organization_id, billing_period_id,
                                    forecast_month, operating_year,
                                    forecast_energy_kwh, forecast_ghi_irradiance,
                                    forecast_poa_irradiance, forecast_pr, forecast_pr_poa,
                                    forecast_source, source_metadata
                                ) VALUES (
                                    %(pid)s, %(oid)s, %(bp)s,
                                    %(fm)s, %(oy)s,
                                    %(fe)s, %(ghi)s,
                                    %(poa)s, %(pr)s, %(prp)s,
                                    'ppw_tech_model', '{"step": "9d"}'::jsonb
                                )
                                ON CONFLICT (project_id, forecast_month) DO UPDATE SET
                                    forecast_ghi_irradiance = COALESCE(production_forecast.forecast_ghi_irradiance, EXCLUDED.forecast_ghi_irradiance),
                                    forecast_poa_irradiance = COALESCE(production_forecast.forecast_poa_irradiance, EXCLUDED.forecast_poa_irradiance),
                                    forecast_pr = COALESCE(production_forecast.forecast_pr, EXCLUDED.forecast_pr),
                                    forecast_pr_poa = COALESCE(production_forecast.forecast_pr_poa, EXCLUDED.forecast_pr_poa),
                                    operating_year = COALESCE(production_forecast.operating_year, EXCLUDED.operating_year),
                                    updated_at = NOW()
                            """, {
                                "pid": project_id, "oid": org_id, "bp": bp_id,
                                "fm": tr.month, "oy": tr.operating_year,
                                "fe": round(fc_energy, 2),
                                "ghi": round(fc_ghi, 4) if fc_ghi else None,
                                "poa": round(fc_poa, 4) if fc_poa else None,
                                "pr": round(fc_pr, 4) if fc_pr else None,
                                "prp": round(fc_pr_poa, 4) if fc_pr_poa else None,
                            })
                        result.forecast_upserted += 1
                        # Update local cache
                        fc_rows[month_key] = {
                            "id": None, "forecast_month": tr.month,
                            "forecast_energy_kwh": fc_energy,
                            "forecast_ghi_irradiance": fc_ghi,
                            "forecast_poa_irradiance": fc_poa,
                            "forecast_pr": fc_pr, "forecast_pr_poa": fc_pr_poa,
                            "operating_year": tr.operating_year,
                        }

                # Refresh fc_by_month id lookup after Phase 0 inserts
                cur.execute("""
                    SELECT id, forecast_month FROM production_forecast
                    WHERE project_id = %s
                """, (project_id,))
                fc_id_by_month = {
                    r["forecast_month"].isoformat(): r["id"]
                    for r in cur.fetchall()
                }

                # ── Phase 1: plant_performance ──
                cur.execute("""
                    SELECT id, billing_month,
                           actual_pr, actual_availability_pct,
                           energy_comparison, irr_comparison, pr_comparison,
                           comments
                    FROM plant_performance
                    WHERE project_id = %s ORDER BY billing_month
                """, (project_id,))
                pp_by_month: Dict[str, Dict] = {}
                for row in cur.fetchall():
                    pp_by_month[row["billing_month"].isoformat()] = dict(row)

                for tr in tech_rows:
                    month_key = tr.month.isoformat()
                    pp_row = pp_by_month.get(month_key)
                    fc = fc_rows.get(month_key, {})

                    # ── Compute derived fields via formulas ──
                    # total_energy: prefer PPW total_energy_kwh, else total_metered + available
                    total_energy = tr.total_energy_kwh
                    if total_energy is None and tr.total_metered_kwh is not None:
                        total_energy = tr.total_metered_kwh + (tr.available_energy_kwh or 0)

                    # actual_pr: prefer PPW value, else compute from formula
                    actual_pr = tr.actual_pr
                    if actual_pr is None:
                        actual_pr = _compute_pr(total_energy, tr.actual_ghi_wm2, capacity_kwp)

                    # Comparisons: compute from underlying data, fallback to PPW
                    fc_energy = fc.get("forecast_energy_kwh")
                    fc_ghi_kwh = fc.get("forecast_ghi_irradiance")  # already kWh/m²
                    fc_pr_val = fc.get("forecast_pr")

                    actual_ghi_kwh = tr.actual_ghi_wm2 / 1000.0 if tr.actual_ghi_wm2 else None

                    energy_comp = _compute_comparison(total_energy, fc_energy)
                    if energy_comp is None:
                        energy_comp = tr.energy_comparison

                    irr_comp = _compute_comparison(actual_ghi_kwh, fc_ghi_kwh)
                    if irr_comp is None:
                        irr_comp = tr.irr_comparison

                    pr_comp = _compute_comparison(actual_pr, fc_pr_val)
                    if pr_comp is None:
                        pr_comp = tr.pr_comparison

                    if pp_row:
                        # --- UPDATE path: fill NULLs only ---
                        updates = {}

                        if pp_row["actual_pr"] is None and actual_pr is not None:
                            updates["actual_pr"] = round(actual_pr, 4)
                        if pp_row["actual_availability_pct"] is None and tr.actual_availability_pct is not None:
                            updates["actual_availability_pct"] = round(tr.actual_availability_pct * 100, 2)
                        if pp_row["energy_comparison"] is None and energy_comp is not None:
                            updates["energy_comparison"] = round(energy_comp, 4)
                        if pp_row["irr_comparison"] is None and irr_comp is not None:
                            updates["irr_comparison"] = round(irr_comp, 4)
                        if pp_row["pr_comparison"] is None and pr_comp is not None:
                            updates["pr_comparison"] = round(pr_comp, 4)
                        if pp_row["comments"] is None and tr.comments is not None:
                            updates["comments"] = tr.comments

                        if not updates:
                            result.rows_skipped += 1
                            continue

                        if not dry_run:
                            set_clauses = ", ".join(f"{col} = %({col})s" for col in updates)
                            updates["updated_at"] = datetime.utcnow()
                            set_clauses += ", updated_at = %(updated_at)s"
                            updates["pp_id"] = pp_row["id"]
                            cur.execute(
                                f"UPDATE plant_performance SET {set_clauses} WHERE id = %(pp_id)s",
                                updates,
                            )

                        result.rows_enriched += 1

                    else:
                        # --- INSERT path ---
                        has_data = any(v is not None for v in [
                            actual_pr, tr.actual_availability_pct,
                            energy_comp, irr_comp, pr_comp, tr.comments,
                        ])
                        if not has_data:
                            result.rows_no_data += 1
                            continue

                        pf_id = fc_id_by_month.get(month_key)
                        bp_id = bp_by_month.get(month_key)

                        if not dry_run:
                            cur.execute("""
                                INSERT INTO plant_performance (
                                    project_id, organization_id,
                                    production_forecast_id, billing_period_id,
                                    billing_month, operating_year,
                                    actual_pr, actual_availability_pct,
                                    energy_comparison, irr_comparison,
                                    pr_comparison, comments
                                ) VALUES (
                                    %(pid)s, %(oid)s,
                                    %(pf_id)s, %(bp_id)s,
                                    %(bm)s, %(oy)s,
                                    %(apr)s, %(avail)s,
                                    %(ec)s, %(ic)s,
                                    %(prc)s, %(cmt)s
                                )
                                ON CONFLICT (project_id, billing_month) DO UPDATE SET
                                    actual_pr = COALESCE(plant_performance.actual_pr, EXCLUDED.actual_pr),
                                    actual_availability_pct = COALESCE(plant_performance.actual_availability_pct, EXCLUDED.actual_availability_pct),
                                    energy_comparison = COALESCE(plant_performance.energy_comparison, EXCLUDED.energy_comparison),
                                    irr_comparison = COALESCE(plant_performance.irr_comparison, EXCLUDED.irr_comparison),
                                    pr_comparison = COALESCE(plant_performance.pr_comparison, EXCLUDED.pr_comparison),
                                    comments = COALESCE(plant_performance.comments, EXCLUDED.comments),
                                    production_forecast_id = COALESCE(EXCLUDED.production_forecast_id, plant_performance.production_forecast_id),
                                    updated_at = NOW()
                            """, {
                                "pid": project_id, "oid": org_id,
                                "pf_id": pf_id, "bp_id": bp_id,
                                "bm": tr.month, "oy": tr.operating_year,
                                "apr": round(actual_pr, 4) if actual_pr is not None else None,
                                "avail": round(tr.actual_availability_pct * 100, 2) if tr.actual_availability_pct is not None else None,
                                "ec": round(energy_comp, 4) if energy_comp is not None else None,
                                "ic": round(irr_comp, 4) if irr_comp is not None else None,
                                "prc": round(pr_comp, 4) if pr_comp is not None else None,
                                "cmt": tr.comments,
                            })

                        result.rows_inserted += 1

                # ── Phase 2: meter_aggregate ──
                _populate_meter_aggregate(
                    sage_id, tech_rows, project_id, org_id,
                    bp_by_month, cur, dry_run, result,
                )

                if not dry_run:
                    conn.commit()
                else:
                    conn.rollback()

        except Exception:
            conn.rollback()
            raise

    logger.info(
        f"  {sage_id}: forecast={result.forecast_upserted}, "
        f"enriched={result.rows_enriched}, inserted={result.rows_inserted}, "
        f"skipped={result.rows_skipped}, no_data={result.rows_no_data}, "
        f"meter_energy={result.meter_energy_written}, "
        f"meter_irradiance={result.meter_irradiance_written}"
    )
    return result


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Step 9D: Enrich plant_performance from PPW project tabs",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--project", type=str, help="Single project sage_id")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID, help="Organization ID")
    parser.add_argument("--workbook", type=str, default=WORKBOOK_PATH, help="PPW file path")

    args = parser.parse_args()

    if not os.path.exists(args.workbook):
        logger.error(f"Workbook not found: {args.workbook}")
        return 1

    report = StepReport()

    # 1. Parse PPW
    logger.info("=== Step 9D: Plant Performance Enrichment from PPW ===")
    logger.info(f"Workbook: {args.workbook}")
    if args.dry_run:
        logger.info("[DRY RUN] No changes will be written")

    ppw_parser = PlantPerformanceParser(args.workbook)
    ppw_data = ppw_parser.parse(project_filter=args.project)

    if not ppw_data.technical_model:
        logger.warning("No Technical Model data found in PPW")
        report.status = "skipped"
        report.gate_checks.append(GateCheck(
            name="technical_model_data",
            passed=False,
            expected=">0 projects with Technical Model",
            actual="0",
        ))
        _write_report(report)
        return 0

    logger.info(
        f"Parsed {len(ppw_data.technical_model)} projects with Technical Model data"
    )

    # 2. Process each project
    init_connection_pool()
    try:
        for sage_id, tech_rows in sorted(ppw_data.technical_model.items()):
            if args.project and sage_id != args.project:
                continue

            site_params = ppw_data.site_parameters.get(sage_id, {})
            proj_result = process_project(
                sage_id=sage_id,
                tech_rows=tech_rows,
                site_params=site_params,
                org_id=args.org_id,
                dry_run=args.dry_run,
            )
            report.project_results.append(proj_result)
            report.projects_processed += 1
            report.total_forecast_upserted += proj_result.forecast_upserted
            report.total_rows_enriched += proj_result.rows_enriched
            report.total_rows_inserted += proj_result.rows_inserted
            report.total_meter_energy += proj_result.meter_energy_written
            report.total_meter_irradiance += proj_result.meter_irradiance_written
            report.discrepancies.extend(proj_result.discrepancies)

    finally:
        close_connection_pool()

    # 3. Gate checks
    report.gate_checks.append(GateCheck(
        name="projects_with_tech_model",
        passed=report.projects_processed > 0,
        expected=">0",
        actual=str(report.projects_processed),
    ))

    report.gate_checks.append(GateCheck(
        name="forecast_rows_upserted",
        passed=report.total_forecast_upserted > 0,
        expected=">0 production_forecast rows",
        actual=str(report.total_forecast_upserted),
    ))

    enriched_projects = sum(
        1 for pr in report.project_results if pr.rows_enriched > 0
    )
    report.gate_checks.append(GateCheck(
        name="projects_enriched",
        passed=enriched_projects > 0,
        expected=">0 projects with enriched rows",
        actual=str(enriched_projects),
    ))

    total_rows = report.total_rows_enriched + report.total_rows_inserted
    report.gate_checks.append(GateCheck(
        name="total_rows_written",
        passed=total_rows > 0,
        expected=">0 rows enriched or inserted",
        actual=f"{report.total_rows_enriched} enriched, {report.total_rows_inserted} inserted",
    ))

    report.gate_checks.append(GateCheck(
        name="meter_aggregate_populated",
        passed=report.total_meter_energy > 0 or report.total_meter_irradiance > 0,
        expected=">0 meter_aggregate rows written",
        actual=f"{report.total_meter_energy} energy, {report.total_meter_irradiance} irradiance",
    ))

    critical = [d for d in report.discrepancies if d.severity == "critical"]
    if critical:
        report.status = "failed"

    # 4. Report
    _write_report(report)

    logger.info(f"\n{'='*60}")
    logger.info(f"Step 9D complete: {report.projects_processed} projects processed")
    logger.info(f"  Forecast upserted: {report.total_forecast_upserted}")
    logger.info(f"  Perf enriched: {report.total_rows_enriched}")
    logger.info(f"  Perf inserted: {report.total_rows_inserted}")
    logger.info(f"  Meter energy rows: {report.total_meter_energy}")
    logger.info(f"  Meter irradiance rows: {report.total_meter_irradiance}")
    for gc in report.gate_checks:
        status = "PASS" if gc.passed else "FAIL"
        logger.info(f"  Gate [{status}] {gc.name}: {gc.actual}")
    logger.info(f"{'='*60}")

    return 0


def _write_report(report: StepReport):
    """Write step report JSON."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = date.today().isoformat()
    report_path = REPORT_DIR / f"step9d_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(asdict(report), f, indent=2, cls=DateEncoder)
    logger.info(f"Report: {report_path}")


if __name__ == "__main__":
    sys.exit(main())
