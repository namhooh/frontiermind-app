"""
Plant Performance Compute Service.

Computes plant_performance from existing meter_aggregate data and production_forecast.
Extracted from api/performance.py add_performance_manual handler (lines 520-650).
"""

import logging
from datetime import date
from typing import Any, Dict, Optional

from db.database import get_db_connection

logger = logging.getLogger(__name__)


def _d2f(val: Any) -> Optional[float]:
    """Decimal/number → float or None."""
    if val is None:
        return None
    return float(val)


class PerformanceService:
    """Compute plant_performance from meter_aggregate + production_forecast."""

    def compute(self, project_id: int, billing_month: str) -> Dict[str, Any]:
        """Compute and upsert plant_performance for a project/month.

        Reads from meter_aggregate and production_forecast (no manual input needed).
        Returns computation result dict.
        """
        bm_date = _parse_billing_month(billing_month)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get project metadata
                cur.execute("""
                    SELECT p.organization_id, p.installed_dc_capacity_kwp, p.cod_date,
                           ct.logic_parameters->>'degradation_pct' AS degradation_pct,
                           ct.logic_parameters->>'oy_start_date' AS oy_start_date
                    FROM project p
                    LEFT JOIN clause_tariff ct ON ct.project_id = p.id AND ct.is_current = true
                    WHERE p.id = %s
                    LIMIT 1
                """, (project_id,))
                proj = cur.fetchone()
                if not proj:
                    return {"success": False, "error": f"Project {project_id} not found"}

                org_id = proj["organization_id"]
                capacity = _d2f(proj.get("installed_dc_capacity_kwp"))
                # Use oy_start_date as canonical OY anchor
                cod_date = date.fromisoformat(proj["oy_start_date"]) if proj.get("oy_start_date") else proj.get("cod_date")

                # Derive operating year from OY anchor
                oy = None
                if cod_date and isinstance(bm_date, date):
                    months_since_cod = (bm_date.year - cod_date.year) * 12 + (bm_date.month - cod_date.month)
                    if months_since_cod < 0:
                        oy = 0
                    else:
                        oy = (months_since_cod // 12) + 1

                # Aggregate meter data for this month
                cur.execute("""
                    SELECT
                        SUM(COALESCE(ma.energy_kwh, ma.total_production, 0)) AS metered,
                        SUM(COALESCE(ma.available_energy_kwh, 0)) AS available
                    FROM meter_aggregate ma
                    JOIN meter m ON m.id = ma.meter_id
                    WHERE m.project_id = %s
                      AND date_trunc('month', ma.period_start) = %s
                """, (project_id, bm_date))
                agg = cur.fetchone()
                total_metered = float(agg["metered"] or 0) if agg else 0.0
                total_available = float(agg["available"] or 0) if agg else 0.0
                total_energy = total_metered + total_available

                if total_energy == 0:
                    return {
                        "success": False,
                        "error": f"No meter_aggregate data for project {project_id} in {billing_month}",
                        "blocked_by": "meter_aggregate",
                    }

                # Get irradiance
                cur.execute("""
                    SELECT MAX(ghi_irradiance_wm2) AS ghi
                    FROM meter_aggregate ma
                    JOIN meter m ON m.id = ma.meter_id
                    WHERE m.project_id = %s
                      AND date_trunc('month', ma.period_start) = %s
                      AND ghi_irradiance_wm2 IS NOT NULL
                """, (project_id, bm_date))
                irr_row = cur.fetchone()
                actual_ghi = _d2f(irr_row["ghi"]) if irr_row else None

                # Get forecast
                cur.execute("""
                    SELECT id, forecast_energy_kwh, forecast_ghi_irradiance, forecast_pr
                    FROM production_forecast
                    WHERE project_id = %s AND forecast_month = %s
                    LIMIT 1
                """, (project_id, bm_date))
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
                    # actual_ghi is Wh/m², forecast_ghi is kWh/m²
                    irr_comparison = (actual_ghi / 1000) / forecast_ghi

                pr_comparison = None
                if actual_pr and forecast_pr and forecast_pr > 0:
                    pr_comparison = actual_pr / forecast_pr

                # Resolve billing_period_id
                cur.execute("""
                    SELECT id FROM billing_period
                    WHERE start_date <= %s AND end_date >= %s
                    LIMIT 1
                """, (bm_date, bm_date))
                bp_row = cur.fetchone()
                bp_id = bp_row["id"] if bp_row else None

                # Upsert plant_performance
                cur.execute("""
                    SELECT id FROM plant_performance
                    WHERE project_id = %s AND billing_month = %s
                    LIMIT 1
                """, (project_id, bm_date))
                existing_pp = cur.fetchone()

                if existing_pp:
                    cur.execute("""
                        UPDATE plant_performance SET
                            billing_period_id = COALESCE(%s, billing_period_id),
                            production_forecast_id = COALESCE(%s, production_forecast_id),
                            operating_year = COALESCE(%s, operating_year),
                            actual_pr = %s,
                            energy_comparison = %s,
                            irr_comparison = %s,
                            pr_comparison = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (
                        bp_id, forecast_id, oy,
                        actual_pr, energy_comparison, irr_comparison, pr_comparison,
                        existing_pp["id"],
                    ))
                else:
                    cur.execute("""
                        INSERT INTO plant_performance (
                            project_id, organization_id, billing_period_id,
                            production_forecast_id,
                            billing_month, operating_year,
                            actual_pr, energy_comparison, irr_comparison, pr_comparison
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        project_id, org_id, bp_id, forecast_id,
                        bm_date, oy,
                        actual_pr, energy_comparison, irr_comparison, pr_comparison,
                    ))

                return {
                    "success": True,
                    "project_id": project_id,
                    "billing_month": billing_month,
                    "total_metered_kwh": total_metered,
                    "total_available_kwh": total_available,
                    "total_energy_kwh": total_energy,
                    "actual_pr": actual_pr,
                    "energy_comparison": energy_comparison,
                    "irr_comparison": irr_comparison,
                    "pr_comparison": pr_comparison,
                    "operating_year": oy,
                }


def _parse_billing_month(billing_month: str) -> date:
    """Parse 'YYYY-MM' to date(YYYY, MM, 1)."""
    parts = billing_month.split("-")
    return date(int(parts[0]), int(parts[1]), 1)
