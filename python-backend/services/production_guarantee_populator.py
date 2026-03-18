"""
Production Guarantee Populator Service.

Bridges PERFORMANCE_GUARANTEE clauses → production_guarantee table rows.
Called automatically after clause extraction (Step 11 Phase 2.5 and API parse endpoint).

For each project with a PERFORMANCE_GUARANTEE clause containing a threshold:
  1. Reads threshold from clause.normalized_payload
  2. Reads P50 forecast data from production_forecast grouped by operating_year
  3. Computes: guaranteed_kwh = P50_annual × (threshold / 100)
  4. Inserts production_guarantee rows (one per operating year)
  5. If guaranteed_annual_production_kwh is explicitly in the clause, uses that instead

Skips projects without COD date or forecast data (guarantees can be populated later
once forecasts are available via Step 5/6).
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from db.database import get_db_connection

logger = logging.getLogger(__name__)


class ProductionGuaranteePopulator:
    """Populate production_guarantee rows from PERFORMANCE_GUARANTEE clauses."""

    def populate_for_project(
        self,
        project_id: int,
        contract_id: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Populate production_guarantee rows for a single project.

        Args:
            project_id: The project to populate guarantees for.
            contract_id: Optional contract filter (uses latest if not specified).
            dry_run: If True, compute but don't insert.

        Returns:
            Dict with keys: rows_created, rows_skipped, threshold_pct, skipped_reason
        """
        result: Dict[str, Any] = {
            "rows_created": 0,
            "rows_skipped": 0,
            "threshold_pct": None,
            "skipped_reason": None,
        }

        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Find PERFORMANCE_GUARANTEE clause with threshold
                clause = self._get_guarantee_clause(cur, project_id, contract_id)
                if not clause:
                    result["skipped_reason"] = "no PERFORMANCE_GUARANTEE clause with threshold"
                    return result

                payload = clause["normalized_payload"] or {}
                threshold_pct = float(payload.get("threshold", 0))
                if threshold_pct <= 0:
                    result["skipped_reason"] = f"threshold={threshold_pct} (invalid)"
                    return result

                # Normalize: >1 means percentage, ≤1 means fraction
                guarantee_fraction = threshold_pct / 100.0 if threshold_pct > 1 else threshold_pct
                result["threshold_pct"] = guarantee_fraction * 100

                # Check for explicit annual production kWh in clause
                explicit_kwh = payload.get("guaranteed_annual_production_kwh")

                # 2. Get project info (COD, org, contract term)
                project_info = self._get_project_info(cur, project_id, contract_id)
                if not project_info:
                    result["skipped_reason"] = "project not found"
                    return result

                cod_date = project_info["cod_date"]
                if not cod_date:
                    result["skipped_reason"] = "no COD date"
                    return result

                if hasattr(cod_date, "date"):
                    cod_date = cod_date.date()

                org_id = project_info["organization_id"]
                contract_term = project_info["contract_term_years"] or 20

                # 3. Get P50 forecast by operating year (derived from COD date ranges)
                forecasts = self._get_forecast_by_oy(cur, project_id, cod_date, contract_term)
                if not forecasts and explicit_kwh is None:
                    result["skipped_reason"] = "no forecast data and no explicit guaranteed_kwh"
                    return result

                # 4. Get existing guarantee rows (skip duplicates)
                existing_oys = self._get_existing_oys(cur, project_id)

                # 5. Compute and insert guarantee rows
                rows_to_insert = []

                if explicit_kwh is not None:
                    # Contract specifies exact annual kWh — use for all OYs
                    explicit_kwh = float(explicit_kwh)
                    for oy in range(1, contract_term + 1):
                        if oy in existing_oys:
                            result["rows_skipped"] += 1
                            continue
                        p50 = round(explicit_kwh / guarantee_fraction) if guarantee_fraction > 0 else None
                        rows_to_insert.append(self._build_row(
                            project_id, org_id, oy, cod_date,
                            p50_kwh=p50,
                            guarantee_fraction=guarantee_fraction,
                            guaranteed_kwh=round(explicit_kwh),
                            clause_id=clause["id"],
                            threshold_pct=threshold_pct,
                            reference=payload.get("reference_annex", ""),
                        ))
                else:
                    # Compute from P50 forecast × threshold
                    forecast_by_oy = {int(f["operating_year"]): float(f["p50_kwh"]) for f in forecasts}
                    for oy in range(1, contract_term + 1):
                        if oy in existing_oys:
                            result["rows_skipped"] += 1
                            continue
                        p50 = forecast_by_oy.get(oy)
                        if p50 is None:
                            continue  # No forecast for this OY yet
                        guaranteed_kwh = round(p50 * guarantee_fraction)
                        rows_to_insert.append(self._build_row(
                            project_id, org_id, oy, cod_date,
                            p50_kwh=round(p50),
                            guarantee_fraction=guarantee_fraction,
                            guaranteed_kwh=guaranteed_kwh,
                            clause_id=clause["id"],
                            threshold_pct=threshold_pct,
                            reference=payload.get("reference_annex", ""),
                        ))

                if not rows_to_insert:
                    result["skipped_reason"] = "all OYs already populated or no forecast data"
                    return result

                if dry_run:
                    result["rows_created"] = len(rows_to_insert)
                    return result

                # 6. Insert
                for row in rows_to_insert:
                    cur.execute("""
                        INSERT INTO production_guarantee (
                            project_id, organization_id, operating_year,
                            year_start_date, year_end_date,
                            p50_annual_kwh, guarantee_pct_of_p50, guaranteed_kwh,
                            source_metadata
                        ) VALUES (
                            %(pid)s, %(oid)s, %(oy)s,
                            %(start)s, %(end)s,
                            %(p50)s, %(pct)s, %(gkwh)s,
                            %(meta)s
                        )
                        ON CONFLICT (project_id, operating_year) DO NOTHING
                    """, row)

                conn.commit()
                result["rows_created"] = len(rows_to_insert)

                logger.info(
                    "ProductionGuaranteePopulator: project_id=%d, threshold=%.0f%%, "
                    "created=%d, skipped=%d",
                    project_id, guarantee_fraction * 100,
                    result["rows_created"], result["rows_skipped"],
                )

        return result

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_guarantee_clause(
        self, cur, project_id: int, contract_id: Optional[int]
    ) -> Optional[Dict]:
        """Find the PERFORMANCE_GUARANTEE clause with a threshold."""
        sql = """
            SELECT c.id, c.normalized_payload
            FROM clause c
            JOIN clause_category cc ON cc.id = c.clause_category_id
            WHERE c.project_id = %(pid)s
              AND cc.code = 'PERFORMANCE_GUARANTEE'
              AND c.normalized_payload->>'threshold' IS NOT NULL
              AND c.is_current = true
        """
        params: Dict[str, Any] = {"pid": project_id}
        if contract_id:
            sql += " AND c.contract_id = %(cid)s"
            params["cid"] = contract_id
        sql += " ORDER BY c.id LIMIT 1"
        cur.execute(sql, params)
        return cur.fetchone()

    def _get_project_info(
        self, cur, project_id: int, contract_id: Optional[int]
    ) -> Optional[Dict]:
        """Get project + contract info needed for guarantee computation."""
        sql = """
            SELECT p.id, p.organization_id, p.cod_date, con.contract_term_years
            FROM project p
            JOIN contract con ON con.project_id = p.id
            WHERE p.id = %(pid)s
        """
        params: Dict[str, Any] = {"pid": project_id}
        if contract_id:
            sql += " AND con.id = %(cid)s"
            params["cid"] = contract_id
        sql += " ORDER BY con.id LIMIT 1"
        cur.execute(sql, params)
        return cur.fetchone()

    def _get_forecast_by_oy(self, cur, project_id: int, cod_date: date, contract_term: int) -> List[Dict]:
        """Get P50 annual forecast totals by operating year, derived from COD date ranges.

        Each OY is computed as: OY_start = COD + (OY-1) years, OY_end = COD + OY years.
        P50 = SUM(forecast_energy_kwh) for months within that range.
        This avoids relying on the stored operating_year field which may be stale.
        """
        results = []
        for oy in range(1, contract_term + 1):
            oy_start = date(cod_date.year + (oy - 1), cod_date.month, cod_date.day)
            oy_end = date(cod_date.year + oy, cod_date.month, cod_date.day)
            cur.execute("""
                SELECT SUM(forecast_energy_kwh) as p50_kwh, COUNT(*) as months
                FROM production_forecast
                WHERE project_id = %(pid)s
                  AND forecast_month >= %(start)s
                  AND forecast_month < %(end)s
            """, {"pid": project_id, "start": oy_start, "end": oy_end})
            row = cur.fetchone()
            if row and row["p50_kwh"] is not None:
                results.append({
                    "operating_year": oy,
                    "p50_kwh": row["p50_kwh"],
                    "months": row["months"],
                })
        return results

    def _get_existing_oys(self, cur, project_id: int) -> set:
        """Get set of operating years that already have guarantee rows."""
        cur.execute("""
            SELECT operating_year FROM production_guarantee
            WHERE project_id = %(pid)s
        """, {"pid": project_id})
        return {row["operating_year"] for row in cur.fetchall()}

    def _build_row(
        self,
        project_id: int,
        org_id: int,
        oy: int,
        cod_date: date,
        p50_kwh: Optional[int],
        guarantee_fraction: float,
        guaranteed_kwh: int,
        clause_id: int,
        threshold_pct: float,
        reference: str,
    ) -> Dict[str, Any]:
        """Build a parameter dict for the INSERT statement."""
        year_start = date(cod_date.year + (oy - 1), cod_date.month, cod_date.day)
        year_end = date(cod_date.year + oy, cod_date.month, cod_date.day)

        return {
            "pid": project_id,
            "oid": org_id,
            "oy": oy,
            "start": year_start,
            "end": year_end,
            "p50": p50_kwh,
            "pct": round(guarantee_fraction, 4),
            "gkwh": guaranteed_kwh,
            "meta": json.dumps({
                "source": "clause_performance_guarantee",
                "clause_id": clause_id,
                "threshold_pct": threshold_pct,
                "reference_annex": reference,
                "populated_by": "ProductionGuaranteePopulator",
            }),
        }
