"""
Portfolio API Endpoints

Provides portfolio-level (cross-project) revenue reporting:
aggregated monthly kWh, tariff rates, and revenue across all projects
in an organisation.
"""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.database import get_db_connection, init_connection_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/portfolio",
    tags=["portfolio"],
    responses={500: {"description": "Internal server error"}},
)

try:
    init_connection_pool()
    USE_DATABASE = True
except Exception as e:
    logger.error(f"Portfolio API: Database not available - {e}")
    USE_DATABASE = False


# ============================================================================
# Response Models
# ============================================================================

class PortfolioMonthRow(BaseModel):
    billing_month: str
    project_count: int = 0
    actual_kwh: Optional[float] = None
    forecast_kwh: Optional[float] = None
    weighted_avg_tariff_usd: Optional[float] = None
    revenue_usd: Optional[float] = None
    forecast_revenue_usd: Optional[float] = None


class PortfolioProjectSummary(BaseModel):
    project_id: int
    project_name: str
    country: Optional[str] = None
    customer_name: Optional[str] = None
    industry: Optional[str] = None
    total_actual_kwh: Optional[float] = None
    total_forecast_kwh: Optional[float] = None
    total_revenue_usd: Optional[float] = None
    months_with_data: int = 0


class PortfolioSummary(BaseModel):
    total_actual_kwh: Optional[float] = None
    total_forecast_kwh: Optional[float] = None
    total_revenue_usd: Optional[float] = None
    total_forecast_revenue_usd: Optional[float] = None


class DataCoverage(BaseModel):
    total_projects: int = 0
    projects_with_meter_data: int = 0
    projects_with_forecast: int = 0
    projects_with_tariff: int = 0


class PortfolioRevenueSummaryResponse(BaseModel):
    success: bool = True
    months: List[PortfolioMonthRow] = []
    projects: List[PortfolioProjectSummary] = []
    summary: PortfolioSummary = PortfolioSummary()
    data_coverage: DataCoverage = DataCoverage()


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/revenue-summary", response_model=PortfolioRevenueSummaryResponse)
async def get_revenue_summary(
    organization_id: int = Query(..., description="Organisation ID"),
):
    """
    Aggregate monthly kWh, tariff, and revenue across all projects for an org.

    Joins meter_aggregate → contract_line → contract → project for actuals,
    production_forecast for forecasts, and tariff_rate for USD pricing.
    """
    if not USE_DATABASE:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        with get_db_connection(dict_cursor=False) as conn:
            cur = conn.cursor()

            # ------------------------------------------------------------------
            # 1. Monthly actuals: energy per project per month + tariff rate
            # ------------------------------------------------------------------
            cur.execute("""
                WITH monthly_actuals AS (
                    SELECT
                        date_trunc('month', ma.period_start)::date AS billing_month,
                        c.project_id,
                        SUM(ma.energy_kwh)                        AS actual_kwh
                    FROM meter_aggregate ma
                    JOIN contract_line cl ON cl.id = ma.contract_line_id
                    JOIN contract c       ON c.id  = cl.contract_id
                    JOIN project p        ON p.id  = c.project_id
                    WHERE p.organization_id = %s
                      AND ma.energy_kwh IS NOT NULL
                    GROUP BY 1, 2
                ),
                monthly_rates AS (
                    SELECT DISTINCT ON (tr.clause_tariff_id, m.billing_month)
                        m.billing_month,
                        c.project_id,
                        tr.effective_rate_hard_ccy AS rate_usd
                    FROM (SELECT DISTINCT billing_month FROM monthly_actuals) m
                    CROSS JOIN LATERAL (
                        SELECT DISTINCT cl2.clause_tariff_id, c2.project_id
                        FROM contract_line cl2
                        JOIN contract c2 ON c2.id = cl2.contract_id
                        WHERE c2.organization_id = %s
                          AND cl2.clause_tariff_id IS NOT NULL
                    ) sub
                    JOIN contract_line cl3 ON cl3.clause_tariff_id = sub.clause_tariff_id
                    JOIN contract c ON c.id = cl3.contract_id AND c.project_id = sub.project_id
                    JOIN tariff_rate tr ON tr.clause_tariff_id = sub.clause_tariff_id
                    WHERE (
                        (tr.rate_granularity = 'monthly' AND tr.billing_month = m.billing_month)
                        OR (tr.rate_granularity = 'annual' AND tr.billing_month IS NULL)
                    )
                    ORDER BY tr.clause_tariff_id, m.billing_month,
                             CASE WHEN tr.rate_granularity = 'monthly' THEN 0 ELSE 1 END
                )
                SELECT
                    a.billing_month,
                    a.project_id,
                    a.actual_kwh,
                    r.rate_usd
                FROM monthly_actuals a
                LEFT JOIN monthly_rates r
                    ON r.billing_month = a.billing_month
                   AND r.project_id   = a.project_id
                ORDER BY a.billing_month DESC, a.project_id
            """, (organization_id, organization_id))

            actual_rows = cur.fetchall()

            # ------------------------------------------------------------------
            # 2. Monthly forecasts per project
            # ------------------------------------------------------------------
            cur.execute("""
                SELECT
                    pf.forecast_month::date AS billing_month,
                    pf.project_id,
                    SUM(pf.forecast_energy_kwh) AS forecast_kwh
                FROM production_forecast pf
                JOIN project p ON p.id = pf.project_id
                WHERE p.organization_id = %s
                  AND pf.forecast_energy_kwh IS NOT NULL
                GROUP BY 1, 2
                ORDER BY 1 DESC, 2
            """, (organization_id,))

            forecast_rows = cur.fetchall()

            # ------------------------------------------------------------------
            # 3. Data coverage
            # ------------------------------------------------------------------
            cur.execute("SELECT COUNT(*) FROM project WHERE organization_id = %s", (organization_id,))
            total_projects = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT c.project_id)
                FROM meter_aggregate ma
                JOIN contract_line cl ON cl.id = ma.contract_line_id
                JOIN contract c ON c.id = cl.contract_id
                JOIN project p ON p.id = c.project_id
                WHERE p.organization_id = %s AND ma.energy_kwh IS NOT NULL
            """, (organization_id,))
            projects_with_meter = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT pf.project_id)
                FROM production_forecast pf
                JOIN project p ON p.id = pf.project_id
                WHERE p.organization_id = %s AND pf.forecast_energy_kwh IS NOT NULL
            """, (organization_id,))
            projects_with_forecast = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(DISTINCT c.project_id)
                FROM contract_line cl
                JOIN contract c ON c.id = cl.contract_id
                JOIN project p ON p.id = c.project_id
                WHERE p.organization_id = %s AND cl.clause_tariff_id IS NOT NULL
            """, (organization_id,))
            projects_with_tariff = cur.fetchone()[0]

            # ------------------------------------------------------------------
            # 4. Aggregate into response structures
            # ------------------------------------------------------------------

            # Build lookup: {(month, project_id): {actual_kwh, rate_usd}}
            actuals_map: dict[tuple, dict] = {}
            for row in actual_rows:
                billing_month, project_id, actual_kwh, rate_usd = row
                key = (str(billing_month), project_id)
                actuals_map[key] = {
                    "actual_kwh": float(actual_kwh) if actual_kwh else None,
                    "rate_usd": float(rate_usd) if rate_usd else None,
                }

            # Build forecast lookup: {(month, project_id): forecast_kwh}
            forecast_map: dict[tuple, float] = {}
            for row in forecast_rows:
                billing_month, project_id, forecast_kwh = row
                forecast_map[(str(billing_month), project_id)] = float(forecast_kwh) if forecast_kwh else 0

            # Collect all months and all project_ids
            all_months: set[str] = set()
            all_project_ids: set[int] = set()
            for (m, pid) in actuals_map:
                all_months.add(m)
                all_project_ids.add(pid)
            for (m, pid) in forecast_map:
                all_months.add(m)
                all_project_ids.add(pid)

            # Build monthly aggregation
            month_rows: list[PortfolioMonthRow] = []
            total_actual = 0.0
            total_forecast = 0.0
            total_revenue = 0.0
            total_forecast_revenue = 0.0

            for month in sorted(all_months, reverse=True):
                month_actual = 0.0
                month_forecast = 0.0
                month_revenue = 0.0
                month_forecast_revenue = 0.0
                month_project_count = 0
                weighted_rate_num = 0.0
                weighted_rate_den = 0.0

                for pid in all_project_ids:
                    act = actuals_map.get((month, pid))
                    fcast = forecast_map.get((month, pid))
                    kwh = act["actual_kwh"] if act and act["actual_kwh"] else 0
                    rate = act["rate_usd"] if act and act["rate_usd"] else None

                    if kwh > 0:
                        month_actual += kwh
                        month_project_count += 1
                        if rate:
                            rev = kwh * rate
                            month_revenue += rev
                            weighted_rate_num += kwh * rate
                            weighted_rate_den += kwh

                    if fcast:
                        month_forecast += fcast
                        if rate:
                            month_forecast_revenue += fcast * rate

                total_actual += month_actual
                total_forecast += month_forecast
                total_revenue += month_revenue
                total_forecast_revenue += month_forecast_revenue

                month_rows.append(PortfolioMonthRow(
                    billing_month=month,
                    project_count=month_project_count,
                    actual_kwh=round(month_actual, 2) if month_actual else None,
                    forecast_kwh=round(month_forecast, 2) if month_forecast else None,
                    weighted_avg_tariff_usd=round(weighted_rate_num / weighted_rate_den, 8) if weighted_rate_den else None,
                    revenue_usd=round(month_revenue, 2) if month_revenue else None,
                    forecast_revenue_usd=round(month_forecast_revenue, 2) if month_forecast_revenue else None,
                ))

            # Build per-project summary
            # Need project names, countries, customer names, industries
            project_info: dict[int, dict] = {}
            if all_project_ids:
                placeholders = ",".join(["%s"] * len(all_project_ids))
                cur.execute(
                    f"""SELECT p.id, p.name, p.country, cp.name, cp.industry
                        FROM project p
                        LEFT JOIN contract c ON c.project_id = p.id
                        LEFT JOIN counterparty cp ON cp.id = c.counterparty_id
                        WHERE p.id IN ({placeholders})
                        GROUP BY p.id, p.name, p.country, cp.name, cp.industry""",
                    tuple(all_project_ids),
                )
                for row in cur.fetchall():
                    project_info[row[0]] = {
                        "name": row[1],
                        "country": row[2],
                        "customer_name": row[3],
                        "industry": row[4],
                    }

            project_summaries: list[PortfolioProjectSummary] = []
            for pid in sorted(all_project_ids):
                info = project_info.get(pid, {"name": f"Project {pid}", "country": None, "customer_name": None, "industry": None})
                proj_kwh = 0.0
                proj_forecast_kwh = 0.0
                proj_revenue = 0.0
                months_count = 0
                for month in all_months:
                    act = actuals_map.get((month, pid))
                    fcast = forecast_map.get((month, pid))
                    if act and act["actual_kwh"] and act["actual_kwh"] > 0:
                        proj_kwh += act["actual_kwh"]
                        months_count += 1
                        if act["rate_usd"]:
                            proj_revenue += act["actual_kwh"] * act["rate_usd"]
                    if fcast:
                        proj_forecast_kwh += fcast

                project_summaries.append(PortfolioProjectSummary(
                    project_id=pid,
                    project_name=info["name"],
                    country=info["country"],
                    customer_name=info.get("customer_name"),
                    industry=info.get("industry"),
                    total_actual_kwh=round(proj_kwh, 2) if proj_kwh else None,
                    total_forecast_kwh=round(proj_forecast_kwh, 2) if proj_forecast_kwh else None,
                    total_revenue_usd=round(proj_revenue, 2) if proj_revenue else None,
                    months_with_data=months_count,
                ))

            return PortfolioRevenueSummaryResponse(
                months=month_rows,
                projects=project_summaries,
                summary=PortfolioSummary(
                    total_actual_kwh=round(total_actual, 2) if total_actual else None,
                    total_forecast_kwh=round(total_forecast, 2) if total_forecast else None,
                    total_revenue_usd=round(total_revenue, 2) if total_revenue else None,
                    total_forecast_revenue_usd=round(total_forecast_revenue, 2) if total_forecast_revenue else None,
                ),
                data_coverage=DataCoverage(
                    total_projects=total_projects,
                    projects_with_meter_data=projects_with_meter,
                    projects_with_forecast=projects_with_forecast,
                    projects_with_tariff=projects_with_tariff,
                ),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to build portfolio revenue summary")
        raise HTTPException(status_code=500, detail=str(e))
