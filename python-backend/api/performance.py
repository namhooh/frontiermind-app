"""
Plant Performance API Endpoints

Provides plant-level performance analysis: actual vs forecast energy,
irradiance comparisons, PR calculations, and availability tracking.
"""

import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Path, status
from pydantic import BaseModel, Field

from db.database import get_db_connection, init_connection_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["performance"],
    responses={500: {"description": "Internal server error"}},
)

try:
    init_connection_pool()
    USE_DATABASE = True
except Exception as e:
    logger.error(f"Performance API: Database not available - {e}")
    USE_DATABASE = False


# ============================================================================
# Response / Request Models
# ============================================================================

class MeterPerformanceDetail(BaseModel):
    meter_id: int
    meter_name: Optional[str] = None
    metered_kwh: Optional[float] = None
    available_kwh: Optional[float] = None


class PerformanceMonth(BaseModel):
    billing_month: str  # YYYY-MM-DD
    operating_year: Optional[int] = None
    # Actuals (from meter_aggregate)
    total_metered_kwh: Optional[float] = None
    total_available_kwh: Optional[float] = None
    total_energy_kwh: Optional[float] = None
    actual_ghi_irradiance: Optional[float] = None
    actual_poa_irradiance: Optional[float] = None
    # Forecast (from production_forecast)
    forecast_energy_kwh: Optional[float] = None
    forecast_ghi_irradiance: Optional[float] = None
    forecast_poa_irradiance: Optional[float] = None
    forecast_pr: Optional[float] = None
    # Performance metrics (from plant_performance)
    actual_pr: Optional[float] = None
    actual_availability_pct: Optional[float] = None
    energy_comparison: Optional[float] = None
    irr_comparison: Optional[float] = None
    pr_comparison: Optional[float] = None
    comments: Optional[str] = None
    # Per-meter detail
    meter_details: List[MeterPerformanceDetail] = []


class PlantPerformanceResponse(BaseModel):
    success: bool = True
    installed_capacity_kwp: Optional[float] = None
    annual_degradation_pct: Optional[float] = None
    months: List[PerformanceMonth] = []
    summary: dict[str, Any] = {}
    # Canonical meter list (ordered by contract_line_number)
    meters: List[dict] = []


class ManualPerformanceEntry(BaseModel):
    billing_month: str = Field(..., description="YYYY-MM format")
    operating_year: Optional[int] = None
    # Per-meter readings (list of {meter_id, energy_kwh, available_energy_kwh, opening_reading, closing_reading})
    meter_readings: Optional[List[dict]] = None
    # Irradiance
    ghi_irradiance_wm2: Optional[float] = None
    poa_irradiance_wm2: Optional[float] = None
    # Performance
    actual_availability_pct: Optional[float] = None
    comments: Optional[str] = None


class ImportResponse(BaseModel):
    success: bool = True
    imported_rows: int = 0
    message: str = ""


def _d2f(val: Any) -> Optional[float]:
    """Decimal/number → float or None."""
    if val is None:
        return None
    return float(val)


# ============================================================================
# GET /projects/{project_id}/plant-performance
# ============================================================================

@router.get(
    "/projects/{project_id}/plant-performance",
    response_model=PlantPerformanceResponse,
    summary="Get plant performance analysis",
)
async def get_plant_performance(
    project_id: int = Path(..., description="Project ID"),
) -> PlantPerformanceResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1) Project metadata
                cur.execute("""
                    SELECT p.installed_dc_capacity_kwp,
                           ct.logic_parameters->>'degradation_pct' AS degradation_pct
                    FROM project p
                    LEFT JOIN clause_tariff ct
                        ON ct.project_id = p.id AND ct.is_current = true
                    WHERE p.id = %(pid)s
                    LIMIT 1
                """, {"pid": project_id})
                proj = cur.fetchone()
                if not proj:
                    raise HTTPException(status_code=404, detail="Project not found")

                capacity = _d2f(proj.get("installed_dc_capacity_kwp"))
                degradation_pct = float(proj["degradation_pct"]) if proj.get("degradation_pct") else None

                # 2) Get canonical meter list from contract_line (ordered by contract_line_number)
                cur.execute("""
                    SELECT cl.meter_id, m.name AS meter_name,
                           cl.energy_category::text AS energy_category,
                           cl.contract_line_number
                    FROM contract_line cl
                    JOIN contract c ON c.id = cl.contract_id
                    JOIN meter m ON m.id = cl.meter_id
                    WHERE c.project_id = %(pid)s
                      AND cl.is_active = true
                      AND cl.energy_category = 'metered'
                    ORDER BY cl.contract_line_number
                """, {"pid": project_id})
                meter_rows = cur.fetchall()
                meters_list = [
                    {"meter_id": r["meter_id"], "meter_name": r["meter_name"], "energy_category": r["energy_category"]}
                    for r in meter_rows
                ]
                meter_ids_ordered = [r["meter_id"] for r in meter_rows]

                # 3) Get all months from meter_aggregate + production_forecast + plant_performance
                cur.execute("""
                    WITH project_meters AS (
                        SELECT id FROM meter WHERE project_id = %(pid)s
                    ),
                    all_months AS (
                        SELECT DISTINCT date_trunc('month', ma.period_start)::date AS billing_month
                        FROM meter_aggregate ma
                        WHERE ma.meter_id IN (SELECT id FROM project_meters)
                          AND ma.period_start IS NOT NULL
                        UNION
                        SELECT DISTINCT forecast_month
                        FROM production_forecast
                        WHERE project_id = %(pid)s
                        UNION
                        SELECT DISTINCT billing_month
                        FROM plant_performance
                        WHERE project_id = %(pid)s
                    ),
                    -- Aggregate actuals per month
                    monthly_actuals AS (
                        SELECT
                            date_trunc('month', ma.period_start)::date AS billing_month,
                            SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS total_metered_kwh,
                            SUM(COALESCE(ma.available_energy_kwh, 0)) AS total_available_kwh
                        FROM meter_aggregate ma
                        WHERE ma.meter_id IN (SELECT id FROM project_meters)
                          AND ma.period_start IS NOT NULL
                        GROUP BY date_trunc('month', ma.period_start)::date
                    ),
                    -- Irradiance from pyranometer meter (aggregate level)
                    -- ghi_irradiance_wm2 is Wh/m² (monthly cumulative); convert to kWh/m² for comparison
                    monthly_irradiance AS (
                        SELECT
                            date_trunc('month', ma.period_start)::date AS billing_month,
                            MAX(ma.ghi_irradiance_wm2) AS ghi_irradiance_wm2,
                            MAX(ma.poa_irradiance_wm2) AS poa_irradiance_wm2
                        FROM meter_aggregate ma
                        WHERE ma.meter_id IN (SELECT id FROM project_meters)
                          AND ma.period_start IS NOT NULL
                          AND (ma.ghi_irradiance_wm2 IS NOT NULL OR ma.poa_irradiance_wm2 IS NOT NULL)
                        GROUP BY date_trunc('month', ma.period_start)::date
                    ),
                    -- Forecasts
                    monthly_forecasts AS (
                        SELECT
                            pf.forecast_month AS billing_month,
                            pf.id AS forecast_id,
                            pf.forecast_energy_kwh,
                            pf.forecast_ghi_irradiance,
                            pf.forecast_poa_irradiance,
                            pf.forecast_pr
                        FROM production_forecast pf
                        WHERE pf.project_id = %(pid)s
                    )
                    SELECT
                        am.billing_month,
                        act.total_metered_kwh,
                        act.total_available_kwh,
                        irr.ghi_irradiance_wm2 AS actual_ghi,
                        irr.poa_irradiance_wm2 AS actual_poa,
                        fc.forecast_id,
                        fc.forecast_energy_kwh,
                        fc.forecast_ghi_irradiance,
                        fc.forecast_poa_irradiance,
                        fc.forecast_pr,
                        pp.operating_year,
                        pp.actual_pr,
                        pp.actual_availability_pct,
                        pp.energy_comparison,
                        pp.irr_comparison,
                        pp.pr_comparison,
                        pp.comments
                    FROM all_months am
                    LEFT JOIN monthly_actuals act ON act.billing_month = am.billing_month
                    LEFT JOIN monthly_irradiance irr ON irr.billing_month = am.billing_month
                    LEFT JOIN monthly_forecasts fc ON fc.billing_month = am.billing_month
                    LEFT JOIN plant_performance pp ON pp.project_id = %(pid)s AND pp.billing_month = am.billing_month
                    ORDER BY am.billing_month DESC
                """, {"pid": project_id})
                month_rows = cur.fetchall()

                # 4) Get per-meter breakdown for all months
                per_meter_data: dict[str, dict[int, dict]] = {}  # billing_month → {meter_id → {metered, available}}
                if meter_ids_ordered:
                    cur.execute("""
                        SELECT
                            date_trunc('month', ma.period_start)::date AS billing_month,
                            ma.meter_id,
                            COALESCE(ma.energy_kwh, ma.total_production, 0) AS metered_kwh
                        FROM meter_aggregate ma
                        JOIN contract_line cl ON cl.id = ma.contract_line_id
                        WHERE ma.meter_id = ANY(%(mids)s)
                          AND ma.period_start IS NOT NULL
                          AND cl.energy_category = 'metered'
                    """, {"mids": meter_ids_ordered})
                    for row in cur.fetchall():
                        bm = row["billing_month"]
                        bm_key = bm.strftime("%Y-%m-%d") if isinstance(bm, date) else str(bm)
                        if bm_key not in per_meter_data:
                            per_meter_data[bm_key] = {}
                        per_meter_data[bm_key][row["meter_id"]] = {
                            "metered_kwh": _d2f(row["metered_kwh"]),
                        }

                # Meter name lookup
                meter_name_map = {r["meter_id"]: r["meter_name"] for r in meter_rows}

                # 5) Assemble response
                months: list[PerformanceMonth] = []
                totals = {
                    "total_metered_kwh": 0.0,
                    "total_available_kwh": 0.0,
                    "total_energy_kwh": 0.0,
                }

                for mr in month_rows:
                    bm = mr["billing_month"]
                    bm_str = bm.strftime("%Y-%m-%d") if isinstance(bm, date) else str(bm)

                    metered = _d2f(mr["total_metered_kwh"])
                    available = _d2f(mr["total_available_kwh"])
                    total_energy = None
                    if metered is not None:
                        total_energy = metered + (available or 0)

                    if metered:
                        totals["total_metered_kwh"] += metered
                    if available:
                        totals["total_available_kwh"] += available
                    if total_energy:
                        totals["total_energy_kwh"] += total_energy

                    # Build per-meter details for this month
                    month_meters = per_meter_data.get(bm_str, {})
                    meter_details = []
                    for mid in meter_ids_ordered:
                        md = month_meters.get(mid, {})
                        meter_details.append(MeterPerformanceDetail(
                            meter_id=mid,
                            meter_name=meter_name_map.get(mid),
                            metered_kwh=md.get("metered_kwh"),
                        ))

                    # GHI normalization: actual_ghi is Wh/m² (monthly cumulative)
                    # Convert to kWh/m² for comparison with forecast_ghi (already kWh/m²)
                    actual_ghi_wm2 = _d2f(mr.get("actual_ghi"))
                    actual_ghi_kwh = actual_ghi_wm2 / 1000.0 if actual_ghi_wm2 is not None else None

                    months.append(PerformanceMonth(
                        billing_month=bm_str,
                        operating_year=mr.get("operating_year"),
                        total_metered_kwh=metered,
                        total_available_kwh=available,
                        total_energy_kwh=total_energy,
                        actual_ghi_irradiance=actual_ghi_kwh,
                        actual_poa_irradiance=_d2f(mr.get("actual_poa")),
                        forecast_energy_kwh=_d2f(mr.get("forecast_energy_kwh")),
                        forecast_ghi_irradiance=_d2f(mr.get("forecast_ghi_irradiance")),
                        forecast_poa_irradiance=_d2f(mr.get("forecast_poa_irradiance")),
                        forecast_pr=_d2f(mr.get("forecast_pr")),
                        actual_pr=_d2f(mr.get("actual_pr")),
                        actual_availability_pct=_d2f(mr.get("actual_availability_pct")),
                        energy_comparison=_d2f(mr.get("energy_comparison")),
                        irr_comparison=_d2f(mr.get("irr_comparison")),
                        pr_comparison=_d2f(mr.get("pr_comparison")),
                        comments=mr.get("comments"),
                        meter_details=meter_details,
                    ))

                return PlantPerformanceResponse(
                    success=True,
                    installed_capacity_kwp=capacity,
                    annual_degradation_pct=degradation_pct,
                    months=months,
                    summary=totals,
                    meters=meters_list,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching plant performance for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/plant-performance/manual
# ============================================================================

@router.post(
    "/projects/{project_id}/plant-performance/manual",
    response_model=ImportResponse,
    summary="Add/update plant performance data for a month",
)
async def add_performance_manual(
    project_id: int = Path(..., description="Project ID"),
    body: ManualPerformanceEntry = ...,
) -> ImportResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        parts = body.billing_month.split("-")
        bm_date = date(int(parts[0]), int(parts[1]), 1)
    except Exception:
        raise HTTPException(status_code=400, detail="billing_month must be YYYY-MM or YYYY-MM-DD")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get project org + capacity
                cur.execute("""
                    SELECT organization_id, installed_dc_capacity_kwp
                    FROM project WHERE id = %(pid)s
                """, {"pid": project_id})
                proj = cur.fetchone()
                if not proj:
                    raise HTTPException(status_code=404, detail="Project not found")
                org_id = proj["organization_id"]
                capacity = _d2f(proj.get("installed_dc_capacity_kwp"))

                count = 0

                # Period end
                if bm_date.month == 12:
                    period_end = date(bm_date.year + 1, 1, 1)
                else:
                    period_end = date(bm_date.year, bm_date.month + 1, 1)

                # Upsert per-meter readings
                if body.meter_readings:
                    for mr in body.meter_readings:
                        m_id = mr.get("meter_id")
                        if not m_id:
                            continue

                        energy = mr.get("energy_kwh")
                        avail = mr.get("available_energy_kwh")
                        opening = mr.get("opening_reading")
                        closing = mr.get("closing_reading")

                        # Upsert meter_aggregate
                        cur.execute("""
                            SELECT id FROM meter_aggregate
                            WHERE meter_id = %(mid)s
                              AND date_trunc('month', period_start) = %(bm)s
                            LIMIT 1
                        """, {"mid": m_id, "bm": bm_date})
                        existing = cur.fetchone()

                        if existing:
                            cur.execute("""
                                UPDATE meter_aggregate SET
                                    energy_kwh = COALESCE(%(energy)s, energy_kwh),
                                    total_production = COALESCE(%(energy)s, total_production),
                                    available_energy_kwh = COALESCE(%(avail)s, available_energy_kwh),
                                    opening_reading = COALESCE(%(opening)s, opening_reading),
                                    closing_reading = COALESCE(%(closing)s, closing_reading)
                                WHERE id = %(id)s
                            """, {
                                "energy": energy, "avail": avail,
                                "opening": opening, "closing": closing,
                                "id": existing["id"],
                            })
                        else:
                            cur.execute("""
                                INSERT INTO meter_aggregate (
                                    meter_id, organization_id, period_start, period_end,
                                    energy_kwh, total_production, available_energy_kwh,
                                    opening_reading, closing_reading, unit
                                ) VALUES (
                                    %(mid)s, %(oid)s, %(ps)s, %(pe)s,
                                    %(energy)s, %(energy)s, %(avail)s,
                                    %(opening)s, %(closing)s, 'kWh'
                                )
                            """, {
                                "mid": m_id, "oid": org_id,
                                "ps": bm_date, "pe": period_end,
                                "energy": energy, "avail": avail,
                                "opening": opening, "closing": closing,
                            })
                        count += 1

                # Upsert irradiance (find pyranometer meter or any project meter)
                if body.ghi_irradiance_wm2 is not None or body.poa_irradiance_wm2 is not None:
                    cur.execute("""
                        SELECT m.id FROM meter m
                        LEFT JOIN meter_type mt ON mt.id = m.meter_type_id
                        WHERE m.project_id = %(pid)s
                        ORDER BY (mt.name ILIKE '%%pyranometer%%' OR mt.name ILIKE '%%irradiance%%') DESC
                        LIMIT 1
                    """, {"pid": project_id})
                    irr_meter = cur.fetchone()

                    if irr_meter:
                        cur.execute("""
                            SELECT id FROM meter_aggregate
                            WHERE meter_id = %(mid)s
                              AND date_trunc('month', period_start) = %(bm)s
                            LIMIT 1
                        """, {"mid": irr_meter["id"], "bm": bm_date})
                        existing = cur.fetchone()

                        if existing:
                            cur.execute("""
                                UPDATE meter_aggregate SET
                                    ghi_irradiance_wm2 = COALESCE(%(ghi)s, ghi_irradiance_wm2),
                                    poa_irradiance_wm2 = COALESCE(%(poa)s, poa_irradiance_wm2)
                                WHERE id = %(id)s
                            """, {
                                "ghi": body.ghi_irradiance_wm2,
                                "poa": body.poa_irradiance_wm2,
                                "id": existing["id"],
                            })
                        else:
                            cur.execute("""
                                INSERT INTO meter_aggregate (
                                    meter_id, organization_id, period_start, period_end,
                                    ghi_irradiance_wm2, poa_irradiance_wm2, unit
                                ) VALUES (%(mid)s, %(oid)s, %(ps)s, %(pe)s, %(ghi)s, %(poa)s, 'Wh/m2')
                            """, {
                                "mid": irr_meter["id"], "oid": org_id,
                                "ps": bm_date, "pe": period_end,
                                "ghi": body.ghi_irradiance_wm2,
                                "poa": body.poa_irradiance_wm2,
                            })

                # Compute performance metrics and upsert plant_performance
                total_metered = 0.0
                total_available = 0.0
                cur.execute("""
                    SELECT
                        SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS metered,
                        SUM(COALESCE(ma.available_energy_kwh, 0)) AS available
                    FROM meter_aggregate ma
                    JOIN meter m ON m.id = ma.meter_id
                    WHERE m.project_id = %(pid)s
                      AND date_trunc('month', ma.period_start) = %(bm)s
                """, {"pid": project_id, "bm": bm_date})
                agg = cur.fetchone()
                if agg:
                    total_metered = float(agg["metered"] or 0)
                    total_available = float(agg["available"] or 0)
                total_energy = total_metered + total_available

                # Get irradiance
                cur.execute("""
                    SELECT MAX(ghi_irradiance_wm2) AS ghi
                    FROM meter_aggregate ma
                    JOIN meter m ON m.id = ma.meter_id
                    WHERE m.project_id = %(pid)s
                      AND date_trunc('month', ma.period_start) = %(bm)s
                      AND ghi_irradiance_wm2 IS NOT NULL
                """, {"pid": project_id, "bm": bm_date})
                irr_row = cur.fetchone()
                actual_ghi = _d2f(irr_row["ghi"]) if irr_row else None

                # Get forecast
                cur.execute("""
                    SELECT id, forecast_energy_kwh, forecast_ghi_irradiance, forecast_pr
                    FROM production_forecast
                    WHERE project_id = %(pid)s AND forecast_month = %(bm)s
                    LIMIT 1
                """, {"pid": project_id, "bm": bm_date})
                fc = cur.fetchone()

                forecast_id = fc["id"] if fc else None
                forecast_energy = _d2f(fc["forecast_energy_kwh"]) if fc else None
                forecast_ghi = _d2f(fc["forecast_ghi_irradiance"]) if fc else None
                forecast_pr = _d2f(fc["forecast_pr"]) if fc else None

                # Compute derived metrics
                actual_pr = None
                if total_energy > 0 and actual_ghi and actual_ghi > 0 and capacity and capacity > 0:
                    actual_pr = (total_energy * 1000) / (actual_ghi * capacity)

                energy_comparison = None
                if total_energy > 0 and forecast_energy and forecast_energy > 0:
                    energy_comparison = total_energy / forecast_energy

                irr_comparison = None
                if actual_ghi and actual_ghi > 0 and forecast_ghi and forecast_ghi > 0:
                    # actual_ghi is in Wh/m², forecast_ghi is in kWh/m² — convert to same unit
                    irr_comparison = (actual_ghi / 1000) / forecast_ghi

                pr_comparison = None
                if actual_pr and forecast_pr and forecast_pr > 0:
                    pr_comparison = actual_pr / forecast_pr

                # Resolve billing_period_id
                cur.execute("""
                    SELECT id FROM billing_period
                    WHERE start_date <= %(bm)s AND end_date >= %(bm)s
                    LIMIT 1
                """, {"bm": bm_date})
                bp_row = cur.fetchone()
                bp_id = bp_row["id"] if bp_row else None

                # Upsert plant_performance
                cur.execute("""
                    SELECT id FROM plant_performance
                    WHERE project_id = %(pid)s AND billing_month = %(bm)s
                    LIMIT 1
                """, {"pid": project_id, "bm": bm_date})
                existing_pp = cur.fetchone()

                if existing_pp:
                    cur.execute("""
                        UPDATE plant_performance SET
                            billing_period_id = COALESCE(%(bp_id)s, billing_period_id),
                            production_forecast_id = COALESCE(%(fc_id)s, production_forecast_id),
                            operating_year = COALESCE(%(oy)s, operating_year),
                            actual_pr = COALESCE(%(pr)s, actual_pr),
                            actual_availability_pct = COALESCE(%(avail_pct)s, actual_availability_pct),
                            energy_comparison = %(e_comp)s,
                            irr_comparison = %(i_comp)s,
                            pr_comparison = %(pr_comp)s,
                            comments = COALESCE(%(comments)s, comments),
                            updated_at = NOW()
                        WHERE id = %(id)s
                    """, {
                        "bp_id": bp_id,
                        "fc_id": forecast_id,
                        "oy": body.operating_year,
                        "pr": actual_pr,
                        "avail_pct": body.actual_availability_pct,
                        "e_comp": energy_comparison,
                        "i_comp": irr_comparison,
                        "pr_comp": pr_comparison,
                        "comments": body.comments,
                        "id": existing_pp["id"],
                    })
                else:
                    cur.execute("""
                        INSERT INTO plant_performance (
                            project_id, organization_id, billing_period_id,
                            production_forecast_id,
                            billing_month, operating_year,
                            actual_pr, actual_availability_pct,
                            energy_comparison, irr_comparison, pr_comparison,
                            comments
                        ) VALUES (
                            %(pid)s, %(oid)s, %(bp_id)s,
                            %(fc_id)s,
                            %(bm)s, %(oy)s,
                            %(pr)s, %(avail_pct)s,
                            %(e_comp)s, %(i_comp)s, %(pr_comp)s,
                            %(comments)s
                        )
                    """, {
                        "pid": project_id, "oid": org_id, "bp_id": bp_id,
                        "fc_id": forecast_id,
                        "bm": bm_date, "oy": body.operating_year,
                        "pr": actual_pr, "avail_pct": body.actual_availability_pct,
                        "e_comp": energy_comparison, "i_comp": irr_comparison,
                        "pr_comp": pr_comparison, "comments": body.comments,
                    })
                count += 1

                return ImportResponse(
                    success=True,
                    imported_rows=count,
                    message=f"Saved performance data for {bm_date.strftime('%Y-%m')}",
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving performance data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/plant-performance/import
# ============================================================================

@router.post(
    "/projects/{project_id}/plant-performance/import",
    response_model=ImportResponse,
    summary="Import plant performance from Operations workbook",
)
async def import_plant_performance(
    project_id: int = Path(..., description="Project ID"),
    file: UploadFile = File(...),
) -> ImportResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .csv files accepted")

    try:
        import pandas as pd

        content = await file.read()

        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            # Try to read the project sheet (e.g. "MOH01") or first sheet
            try:
                xl = pd.ExcelFile(io.BytesIO(content))
                # Look for a sheet matching common patterns
                sheet_name = xl.sheet_names[0]
                for sn in xl.sheet_names:
                    if sn.upper() not in ('LISTS', 'TEMPLATE', 'README'):
                        sheet_name = sn
                        break
                df = pd.read_excel(io.BytesIO(content), sheet_name=sheet_name)
            except Exception:
                df = pd.read_excel(io.BytesIO(content))

        # Normalize column names
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

        # Look for billing_month or month column
        month_col = None
        for candidate in ['billing_month', 'month', 'date', 'period']:
            if candidate in df.columns:
                month_col = candidate
                break

        if not month_col:
            raise HTTPException(
                status_code=400,
                detail=f"Missing month column. Found columns: {list(df.columns)[:20]}",
            )

        imported = 0
        errors = []

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get project info
                cur.execute("SELECT organization_id FROM project WHERE id = %(pid)s", {"pid": project_id})
                proj = cur.fetchone()
                if not proj:
                    raise HTTPException(status_code=404, detail="Project not found")

                # Get project meters
                cur.execute("""
                    SELECT id, name FROM meter WHERE project_id = %(pid)s ORDER BY id
                """, {"pid": project_id})
                meters = cur.fetchall()

                for _, row in df.iterrows():
                    try:
                        bm_raw = str(row[month_col]).strip()
                        try:
                            bm_date = pd.to_datetime(bm_raw).date().replace(day=1)
                        except Exception:
                            parts = bm_raw.split("-")
                            bm_date = date(int(parts[0]), int(parts[1]), 1)

                        # Build meter_readings from column patterns
                        meter_readings = []
                        for meter in meters:
                            m_name = (meter.get("name") or "").lower()
                            if not m_name:
                                continue

                            energy_col = None
                            avail_col = None
                            for c in df.columns:
                                cl = c.lower()
                                if m_name in cl and ('energy' in cl or 'metered' in cl or 'kwh' in cl) and 'avail' not in cl:
                                    energy_col = c
                                elif m_name in cl and 'avail' in cl:
                                    avail_col = c

                            if energy_col or avail_col:
                                mr_data: dict[str, Any] = {"meter_id": meter["id"]}
                                if energy_col and pd.notna(row.get(energy_col)):
                                    mr_data["energy_kwh"] = float(row[energy_col])
                                if avail_col and pd.notna(row.get(avail_col)):
                                    mr_data["available_energy_kwh"] = float(row[avail_col])
                                if mr_data.get("energy_kwh") or mr_data.get("available_energy_kwh"):
                                    meter_readings.append(mr_data)

                        # Extract scalar fields
                        ghi = None
                        for c in df.columns:
                            if 'ghi' in c.lower() or ('irradiance' in c.lower() and 'poa' not in c.lower()):
                                if pd.notna(row.get(c)):
                                    ghi = float(row[c])
                                break

                        poa = None
                        for c in df.columns:
                            if 'poa' in c.lower():
                                if pd.notna(row.get(c)):
                                    poa = float(row[c])
                                break

                        avail_pct = None
                        for c in df.columns:
                            if 'availability' in c.lower() or 'avail_pct' in c.lower():
                                if pd.notna(row.get(c)):
                                    avail_pct = float(row[c])
                                break

                        oy = None
                        for c in df.columns:
                            if c in ('operating_year', 'oy', 'op_year'):
                                if pd.notna(row.get(c)):
                                    oy = int(row[c])
                                break

                        entry = ManualPerformanceEntry(
                            billing_month=bm_date.strftime("%Y-%m"),
                            operating_year=oy,
                            meter_readings=meter_readings if meter_readings else None,
                            ghi_irradiance_wm2=ghi,
                            poa_irradiance_wm2=poa,
                            actual_availability_pct=avail_pct,
                        )

                        await add_performance_manual(project_id, entry)
                        imported += 1

                    except HTTPException:
                        raise
                    except Exception as ex:
                        errors.append(f"Row {_}: {ex}")

        msg = f"Imported {imported} rows"
        if errors:
            msg += f" ({len(errors)} errors: {errors[0]})"

        return ImportResponse(success=True, imported_rows=imported, message=msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing performance data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
