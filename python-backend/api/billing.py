"""
Monthly Billing API Endpoints

Assembles billing data per month: actual generation, forecasts, variance,
and per-product billing amounts computed as kWh × effective_rate.
"""

import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Path, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db.database import get_db_connection, init_connection_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["billing"],
    responses={500: {"description": "Internal server error"}},
)

try:
    init_connection_pool()
    USE_DATABASE = True
except Exception as e:
    logger.error(f"Billing API: Database not available - {e}")
    USE_DATABASE = False


# ============================================================================
# Response / Request Models
# ============================================================================

class ProductColumn(BaseModel):
    billing_product_id: int
    product_code: str
    product_name: str
    clause_tariff_id: Optional[int] = None
    tariff_name: Optional[str] = None
    is_metered: bool = True  # False for fixed-fee products


class MonthlyBillingRow(BaseModel):
    billing_month: str  # YYYY-MM-DD
    billing_period_id: Optional[int] = None
    actual_kwh: Optional[float] = None
    forecast_kwh: Optional[float] = None
    variance_kwh: Optional[float] = None
    variance_pct: Optional[float] = None
    product_amounts: dict[str, Optional[float]] = {}  # product_code -> amount
    product_rates: dict[str, Optional[float]] = {}    # product_code -> rate used
    total_billing_amount: Optional[float] = None


class MonthlyBillingResponse(BaseModel):
    success: bool = True
    rows: List[MonthlyBillingRow] = []
    products: List[ProductColumn] = []
    currency_code: Optional[str] = None
    degradation_pct: Optional[float] = None
    summary: dict[str, Any] = {}


class ManualEntryRequest(BaseModel):
    billing_month: str = Field(..., description="YYYY-MM format")
    actual_kwh: Optional[float] = None
    forecast_kwh: Optional[float] = None


class ImportResponse(BaseModel):
    success: bool = True
    imported_rows: int = 0
    message: str = ""


# Fixed-fee product codes (flat per month, not kWh-based)
FIXED_FEE_PRODUCT_CODES = {
    "EQUIPMENT_RENTAL_LEASE",
    "BESS_LEASE",
    "LOAN",
    "EQUIPMENT_LEASE",
    "BESS",
}


def _decimal_to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


# ============================================================================
# GET /projects/{project_id}/monthly-billing
# ============================================================================

@router.get(
    "/projects/{project_id}/monthly-billing",
    response_model=MonthlyBillingResponse,
    summary="Get monthly billing data",
)
async def get_monthly_billing(
    project_id: int = Path(..., description="Project ID"),
) -> MonthlyBillingResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1) Get project's billing products with their tariff linkage
                cur.execute("""
                    SELECT
                        cbp.billing_product_id,
                        bp.code  AS product_code,
                        bp.name  AS product_name,
                        ct.id    AS clause_tariff_id,
                        ct.name  AS tariff_name,
                        ct.base_rate
                    FROM contract_billing_product cbp
                    JOIN billing_product bp ON bp.id = cbp.billing_product_id
                    JOIN contract c ON c.id = cbp.contract_id
                    LEFT JOIN clause_tariff ct
                        ON ct.contract_id = c.id
                       AND ct.is_current = true
                    WHERE c.project_id = %(pid)s
                    ORDER BY cbp.is_primary DESC, bp.code
                """, {"pid": project_id})
                product_rows = cur.fetchall()

                # Build product columns
                products: list[ProductColumn] = []
                seen_codes: set[str] = set()
                for pr in product_rows:
                    code = pr["product_code"]
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)
                    is_metered = code not in FIXED_FEE_PRODUCT_CODES
                    products.append(ProductColumn(
                        billing_product_id=pr["billing_product_id"],
                        product_code=code,
                        product_name=pr["product_name"] or code,
                        clause_tariff_id=pr["clause_tariff_id"],
                        tariff_name=pr["tariff_name"],
                        is_metered=is_metered,
                    ))

                # 2) Get currency from first tariff
                cur.execute("""
                    SELECT cur.code,
                           ct.logic_parameters->>'degradation_pct' AS degradation_pct
                    FROM clause_tariff ct
                    JOIN currency cur ON cur.id = ct.currency_id
                    WHERE ct.project_id = %(pid)s AND ct.is_current = true
                    LIMIT 1
                """, {"pid": project_id})
                currency_row = cur.fetchone()
                currency_code = currency_row["code"] if currency_row else None
                degradation_pct = float(currency_row["degradation_pct"]) if currency_row and currency_row["degradation_pct"] else None

                # 3) Main billing data query
                cur.execute("""
                    WITH project_meters AS (
                        SELECT id FROM meter WHERE project_id = %(pid)s
                    ),
                    -- Get all distinct billing months from meter_aggregate and forecasts
                    all_months AS (
                        SELECT DISTINCT date_trunc('month', ma.period_start)::date AS billing_month
                        FROM meter_aggregate ma
                        WHERE ma.meter_id IN (SELECT id FROM project_meters)
                          AND ma.period_start IS NOT NULL
                        UNION
                        SELECT DISTINCT forecast_month AS billing_month
                        FROM production_forecast
                        WHERE project_id = %(pid)s
                    ),
                    -- Aggregate actuals per month
                    monthly_actuals AS (
                        SELECT
                            date_trunc('month', ma.period_start)::date AS billing_month,
                            ma.billing_period_id,
                            SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS actual_kwh
                        FROM meter_aggregate ma
                        WHERE ma.meter_id IN (SELECT id FROM project_meters)
                          AND ma.period_start IS NOT NULL
                        GROUP BY date_trunc('month', ma.period_start)::date, ma.billing_period_id
                    ),
                    -- Get forecasts per month
                    monthly_forecasts AS (
                        SELECT
                            forecast_month AS billing_month,
                            SUM(forecast_energy_kwh) AS forecast_kwh
                        FROM production_forecast
                        WHERE project_id = %(pid)s
                        GROUP BY forecast_month
                    )
                    SELECT
                        am.billing_month,
                        act.billing_period_id,
                        act.actual_kwh,
                        fc.forecast_kwh
                    FROM all_months am
                    LEFT JOIN monthly_actuals act ON act.billing_month = am.billing_month
                    LEFT JOIN monthly_forecasts fc ON fc.billing_month = am.billing_month
                    ORDER BY am.billing_month DESC
                """, {"pid": project_id})
                month_rows = cur.fetchall()

                # 4) Build rate lookup: for each product, get rates per month
                #    Priority: monthly_rate > annual_rate.final > annual_rate.effective > clause_tariff.base_rate
                rate_map: dict[str, dict[str, float]] = {}  # product_code -> {month_str -> rate}
                base_rate_map: dict[str, float] = {}  # product_code -> base fallback rate

                for p in products:
                    ct_id = p.clause_tariff_id
                    if ct_id is None:
                        continue

                    # Get base rate as ultimate fallback
                    for pr in product_rows:
                        if pr["product_code"] == p.product_code and pr["base_rate"] is not None:
                            base_rate_map[p.product_code] = float(pr["base_rate"])
                            break

                    # Get rates from tariff_rate (month-exact matching)
                    cur.execute("""
                        SELECT tr.billing_month, tr.effective_rate_billing_ccy,
                               tr.rate_granularity::text AS rate_granularity,
                               tr.period_start, tr.period_end,
                               tr.calc_status::text AS calc_status
                        FROM tariff_rate tr
                        WHERE tr.clause_tariff_id = %(ct_id)s
                          AND tr.calc_status IN ('computed', 'approved')
                        ORDER BY tr.rate_granularity = 'annual' ASC, tr.billing_month
                    """, {"ct_id": ct_id})
                    rate_rows = cur.fetchall()

                    month_rate_dict: dict[str, float] = {}
                    annual_rates = []
                    for nr in rate_rows:
                        if nr["rate_granularity"] == "monthly" and nr["effective_rate_billing_ccy"] is not None:
                            m_str = nr["billing_month"].strftime("%Y-%m-%d") if isinstance(nr["billing_month"], date) else str(nr["billing_month"])
                            month_rate_dict[m_str] = float(nr["effective_rate_billing_ccy"])
                        elif nr["rate_granularity"] == "annual":
                            annual_rates.append({
                                "period_start": nr["period_start"],
                                "period_end": nr["period_end"],
                                "effective_tariff": float(nr["effective_rate_billing_ccy"]) if nr["effective_rate_billing_ccy"] else None,
                                "final_effective_tariff": float(nr["effective_rate_billing_ccy"]) if nr["effective_rate_billing_ccy"] else None,
                            })

                    rate_map[p.product_code] = month_rate_dict
                    p.__dict__['_annual_rates'] = annual_rates

                # 5) Assemble rows
                rows: list[MonthlyBillingRow] = []
                totals = {
                    "actual_kwh": 0.0,
                    "forecast_kwh": 0.0,
                    "total_billing": 0.0,
                }

                for mr in month_rows:
                    bm = mr["billing_month"]
                    bm_str = bm.strftime("%Y-%m-%d") if isinstance(bm, date) else str(bm)
                    actual = _decimal_to_float(mr["actual_kwh"])
                    forecast = _decimal_to_float(mr["forecast_kwh"])

                    variance_kwh = None
                    variance_pct = None
                    if actual is not None and forecast is not None and forecast != 0:
                        variance_kwh = actual - forecast
                        variance_pct = (variance_kwh / forecast) * 100

                    product_amounts: dict[str, Optional[float]] = {}
                    product_rates_out: dict[str, Optional[float]] = {}
                    row_total = 0.0

                    for p in products:
                        # Resolve rate for this product + month
                        rate: Optional[float] = None

                        # Priority 1: monthly rate
                        monthly_dict = rate_map.get(p.product_code, {})
                        if bm_str in monthly_dict:
                            rate = monthly_dict[bm_str]

                        # Priority 2-3: annual rate (final then effective)
                        if rate is None and p.clause_tariff_id is not None:
                            annual_rates = p.__dict__.get('_annual_rates', [])
                            for ar in annual_rates:
                                ps = ar["period_start"]
                                pe = ar["period_end"]
                                if ps and ps <= bm and (pe is None or bm <= pe):
                                    rate = _decimal_to_float(ar["final_effective_tariff"]) or _decimal_to_float(ar["effective_tariff"])
                                    break

                        # Priority 4: base rate
                        if rate is None:
                            rate = base_rate_map.get(p.product_code)

                        product_rates_out[p.product_code] = rate

                        # Calculate amount
                        amount: Optional[float] = None
                        if rate is not None:
                            if p.is_metered:
                                if actual is not None:
                                    amount = actual * rate
                            else:
                                amount = rate  # flat fee

                        product_amounts[p.product_code] = amount
                        if amount is not None:
                            row_total += amount

                    if actual is not None:
                        totals["actual_kwh"] += actual
                    if forecast is not None:
                        totals["forecast_kwh"] += forecast
                    totals["total_billing"] += row_total

                    rows.append(MonthlyBillingRow(
                        billing_month=bm_str,
                        billing_period_id=mr.get("billing_period_id"),
                        actual_kwh=actual,
                        forecast_kwh=forecast,
                        variance_kwh=variance_kwh,
                        variance_pct=variance_pct,
                        product_amounts=product_amounts,
                        product_rates=product_rates_out,
                        total_billing_amount=row_total if row_total > 0 else None,
                    ))

                return MonthlyBillingResponse(
                    success=True,
                    rows=rows,
                    products=products,
                    currency_code=currency_code,
                    degradation_pct=degradation_pct,
                    summary=totals,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching monthly billing for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/monthly-billing/manual
# ============================================================================

@router.post(
    "/projects/{project_id}/monthly-billing/manual",
    response_model=ImportResponse,
    summary="Add/update a single month of billing data",
)
async def add_manual_entry(
    project_id: int = Path(..., description="Project ID"),
    body: ManualEntryRequest = ...,
) -> ImportResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    # Parse billing_month (accept YYYY-MM or YYYY-MM-DD)
    try:
        parts = body.billing_month.split("-")
        bm_date = date(int(parts[0]), int(parts[1]), 1)
    except Exception:
        raise HTTPException(status_code=400, detail="billing_month must be YYYY-MM or YYYY-MM-DD")

    if body.actual_kwh is None and body.forecast_kwh is None:
        raise HTTPException(status_code=400, detail="At least one of actual_kwh or forecast_kwh required")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get project org
                cur.execute("SELECT organization_id FROM project WHERE id = %(pid)s", {"pid": project_id})
                proj = cur.fetchone()
                if not proj:
                    raise HTTPException(status_code=404, detail="Project not found")
                org_id = proj["organization_id"]

                count = 0

                # Upsert actuals into meter_aggregate
                if body.actual_kwh is not None:
                    # Find or resolve billing_period
                    cur.execute("""
                        SELECT id FROM billing_period
                        WHERE start_date <= %(bm)s AND end_date >= %(bm)s
                        LIMIT 1
                    """, {"bm": bm_date})
                    bp_row = cur.fetchone()
                    bp_id = bp_row["id"] if bp_row else None

                    # Find project meter
                    cur.execute("SELECT id FROM meter WHERE project_id = %(pid)s LIMIT 1", {"pid": project_id})
                    meter_row = cur.fetchone()
                    if not meter_row:
                        raise HTTPException(status_code=400, detail="No meter found for project")
                    meter_id = meter_row["id"]

                    # Upsert: check if aggregate exists for this meter+month
                    cur.execute("""
                        SELECT id FROM meter_aggregate
                        WHERE meter_id = %(mid)s
                          AND date_trunc('month', period_start) = %(bm)s
                        LIMIT 1
                    """, {"mid": meter_id, "bm": bm_date})
                    existing = cur.fetchone()

                    if existing:
                        cur.execute("""
                            UPDATE meter_aggregate
                            SET energy_kwh = %(kwh)s, total_production = %(kwh)s
                            WHERE id = %(id)s
                        """, {"kwh": body.actual_kwh, "id": existing["id"]})
                    else:
                        period_end = date(bm_date.year, bm_date.month + 1, 1) if bm_date.month < 12 else date(bm_date.year + 1, 1, 1)
                        cur.execute("""
                            INSERT INTO meter_aggregate (
                                meter_id, billing_period_id, organization_id,
                                period_start, period_end, energy_kwh, total_production, unit
                            ) VALUES (
                                %(mid)s, %(bpid)s, %(oid)s,
                                %(ps)s, %(pe)s, %(kwh)s, %(kwh)s, 'kWh'
                            )
                        """, {
                            "mid": meter_id, "bpid": bp_id, "oid": org_id,
                            "ps": bm_date, "pe": period_end, "kwh": body.actual_kwh,
                        })
                    count += 1

                # Upsert forecast
                if body.forecast_kwh is not None:
                    cur.execute("""
                        SELECT id FROM production_forecast
                        WHERE project_id = %(pid)s AND forecast_month = %(bm)s
                        LIMIT 1
                    """, {"pid": project_id, "bm": bm_date})
                    existing_fc = cur.fetchone()

                    if existing_fc:
                        cur.execute("""
                            UPDATE production_forecast
                            SET forecast_energy_kwh = %(kwh)s, updated_at = NOW()
                            WHERE id = %(id)s
                        """, {"kwh": body.forecast_kwh, "id": existing_fc["id"]})
                    else:
                        cur.execute("""
                            INSERT INTO production_forecast (
                                project_id, organization_id, forecast_month,
                                forecast_energy_kwh, forecast_source
                            ) VALUES (%(pid)s, %(oid)s, %(bm)s, %(kwh)s, 'manual_entry')
                        """, {"pid": project_id, "oid": org_id, "bm": bm_date, "kwh": body.forecast_kwh})
                    count += 1

                return ImportResponse(success=True, imported_rows=count, message=f"Saved {bm_date.strftime('%Y-%m')}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving manual billing entry: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# POST /projects/{project_id}/monthly-billing/import
# ============================================================================

@router.post(
    "/projects/{project_id}/monthly-billing/import",
    response_model=ImportResponse,
    summary="Import billing data from CSV/Excel",
)
async def import_monthly_billing(
    project_id: int = Path(..., description="Project ID"),
    file: UploadFile = File(...),
) -> ImportResponse:
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    filename = (file.filename or "").lower()
    if not filename.endswith((".csv", ".xlsx")):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files accepted")

    try:
        import pandas as pd

        content = await file.read()

        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        # Normalize column names
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        if "billing_month" not in df.columns:
            raise HTTPException(status_code=400, detail="Missing required column: billing_month")

        imported = 0
        errors = []

        for _, row in df.iterrows():
            try:
                bm_raw = str(row["billing_month"]).strip()
                # Parse various date formats
                try:
                    bm_date = pd.to_datetime(bm_raw).date().replace(day=1)
                except Exception:
                    parts = bm_raw.split("-")
                    bm_date = date(int(parts[0]), int(parts[1]), 1)

                actual = float(row["actual_kwh"]) if "actual_kwh" in df.columns and pd.notna(row.get("actual_kwh")) else None
                forecast = float(row["forecast_kwh"]) if "forecast_kwh" in df.columns and pd.notna(row.get("forecast_kwh")) else None

                if actual is None and forecast is None:
                    continue

                # Re-use manual entry logic
                entry = ManualEntryRequest(
                    billing_month=bm_date.strftime("%Y-%m"),
                    actual_kwh=actual,
                    forecast_kwh=forecast,
                )
                await add_manual_entry(project_id, entry)
                imported += 1

            except HTTPException:
                raise
            except Exception as ex:
                errors.append(f"Row {_ + 1}: {ex}")

        msg = f"Imported {imported} rows"
        if errors:
            msg += f" ({len(errors)} errors)"

        return ImportResponse(success=True, imported_rows=imported, message=msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing billing data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET /projects/{project_id}/monthly-billing/export
# ============================================================================

@router.get(
    "/projects/{project_id}/monthly-billing/export",
    summary="Export monthly billing data as Excel",
)
async def export_monthly_billing(
    project_id: int = Path(..., description="Project ID"),
):
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        import pandas as pd

        # Get billing data
        billing_data = await get_monthly_billing(project_id)

        # Build DataFrame
        rows_data = []
        for row in billing_data.rows:
            rd: dict[str, Any] = {
                "Billing Month": row.billing_month,
                "Actual Generation (kWh)": row.actual_kwh,
                "Forecast (kWh)": row.forecast_kwh,
                "Variance (kWh)": row.variance_kwh,
                "Variance (%)": row.variance_pct,
            }
            for p in billing_data.products:
                rd[f"{p.product_name} Rate"] = row.product_rates.get(p.product_code)
                rd[f"{p.product_name} Amount"] = row.product_amounts.get(p.product_code)
            rd["Total Billing Amount"] = row.total_billing_amount
            rows_data.append(rd)

        df = pd.DataFrame(rows_data)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Monthly Billing")
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=monthly_billing_project_{project_id}.xlsx"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting billing data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
