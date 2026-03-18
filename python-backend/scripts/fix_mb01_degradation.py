"""
Fix MB01 production_forecast degradation for projected rows.

The projected rows (forecast_source='projected', Jan 2027 onward) are flat copies
of the OY2 (2026) monthly pattern. They need degradation of 0.55%/year applied.

COD = 2025-01-01, so:
  - COD OY2 = calendar 2026 (ppw_summary, already has 1yr degradation) ← base for projected
  - COD OY3 = calendar 2027: projected × (1-0.0055)^1
  - COD OY4 = calendar 2028: projected × (1-0.0055)^2
  - ...
  - COD OY20 = calendar 2044: projected × (1-0.0055)^18

After fixing forecasts, deletes and re-populates production_guarantee rows.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from dotenv import load_dotenv
load_dotenv()

from db.database import init_connection_pool, close_connection_pool, get_db_connection
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ID = 57
COD_YEAR = 2025  # COD = 2025-01-01
DEGRADATION_RATE = 0.0055  # 0.55% per year
DRY_RUN = "--dry-run" in sys.argv


def main():
    init_connection_pool(min_connections=1, max_connections=3)
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Set degradation_pct in clause_tariff.logic_parameters
            cur.execute("""
                SELECT ct.id, ct.logic_parameters
                FROM clause_tariff ct
                JOIN contract c ON c.id = ct.contract_id
                WHERE c.project_id = %s
                LIMIT 1
            """, (PROJECT_ID,))
            tariff = cur.fetchone()
            if tariff:
                lp = tariff["logic_parameters"] or {}
                if lp.get("degradation_pct") != DEGRADATION_RATE:
                    lp["degradation_pct"] = DEGRADATION_RATE
                    logger.info("Setting degradation_pct=%.4f on clause_tariff %d", DEGRADATION_RATE, tariff["id"])
                    if not DRY_RUN:
                        cur.execute("""
                            UPDATE clause_tariff SET logic_parameters = %s WHERE id = %s
                        """, (json.dumps(lp), tariff["id"]))

            # 2. Apply degradation to projected forecast rows
            cur.execute("""
                SELECT id, forecast_month, forecast_energy_kwh, operating_year, forecast_source
                FROM production_forecast
                WHERE project_id = %s AND forecast_source = 'projected'
                ORDER BY forecast_month
            """, (PROJECT_ID,))
            projected_rows = cur.fetchall()

            updated = 0
            for row in projected_rows:
                month = row["forecast_month"]
                # Determine COD-based operating year from the calendar year
                cal_year = month.year
                cod_oy = cal_year - COD_YEAR + 1  # 2025→OY1, 2026→OY2, 2027→OY3...

                if cod_oy <= 2:
                    # OY1-2 are ppw_summary, shouldn't be here, but skip just in case
                    continue

                # The projected rows are copies of OY2 (2026) pattern
                # Apply degradation relative to OY2: factor = (1-d)^(cod_oy - 2)
                years_from_base = cod_oy - 2
                factor = (1 - DEGRADATION_RATE) ** years_from_base

                old_kwh = float(row["forecast_energy_kwh"])
                new_kwh = round(old_kwh * factor, 2)

                logger.info(
                    "  %s (COD OY%d): %.2f → %.2f (factor=%.6f, -%d yrs)",
                    month.strftime("%Y-%m"), cod_oy, old_kwh, new_kwh, factor, years_from_base,
                )

                if not DRY_RUN:
                    cur.execute("""
                        UPDATE production_forecast
                        SET forecast_energy_kwh = %s,
                            degradation_factor = %s,
                            operating_year = %s
                        WHERE id = %s
                    """, (new_kwh, round(factor, 6), cod_oy, row["id"]))
                updated += 1

            logger.info("Updated %d projected forecast rows", updated)

            # 3. Also fix operating_year on ppw_summary rows to match COD-based OY
            cur.execute("""
                SELECT id, forecast_month, operating_year
                FROM production_forecast
                WHERE project_id = %s AND forecast_source = 'ppw_summary'
                ORDER BY forecast_month
            """, (PROJECT_ID,))
            summary_rows = cur.fetchall()
            oy_fixes = 0
            for row in summary_rows:
                month = row["forecast_month"]
                correct_oy = month.year - COD_YEAR + 1
                if correct_oy < 1:
                    correct_oy = 0  # pre-COD
                if row["operating_year"] != correct_oy:
                    logger.info("  Fix OY: %s: %s → %d", month.strftime("%Y-%m"), row["operating_year"], correct_oy)
                    if not DRY_RUN:
                        cur.execute("""
                            UPDATE production_forecast SET operating_year = %s WHERE id = %s
                        """, (correct_oy, row["id"]))
                    oy_fixes += 1
            logger.info("Fixed %d ppw_summary OY values", oy_fixes)

            # 4. Delete existing production_guarantee rows and re-populate
            if not DRY_RUN:
                cur.execute("DELETE FROM production_guarantee WHERE project_id = %s", (PROJECT_ID,))
                deleted = cur.rowcount
                logger.info("Deleted %d existing production_guarantee rows", deleted)

                conn.commit()
                logger.info("Committed forecast changes")

            # 5. Re-populate guarantees using the populator service
            if not DRY_RUN:
                from services.production_guarantee_populator import ProductionGuaranteePopulator
                populator = ProductionGuaranteePopulator()
                result = populator.populate_for_project(PROJECT_ID)
                logger.info("Production guarantee result: %s", result)
            else:
                logger.info("[DRY RUN] Would delete and re-populate production_guarantee rows")

            # 6. Verify: show the new guarantee values
            cur.execute("""
                SELECT operating_year, p50_annual_kwh, guarantee_pct_of_p50, guaranteed_kwh
                FROM production_guarantee
                WHERE project_id = %s
                ORDER BY operating_year
            """, (PROJECT_ID,))
            guarantees = cur.fetchall()
            logger.info("\nFinal production_guarantee values:")
            logger.info("%-4s  %12s  %8s  %12s", "OY", "P50 kWh", "Pct", "Guaranteed")
            for g in guarantees:
                logger.info("%-4s  %12s  %8s  %12s",
                    g["operating_year"], g["p50_annual_kwh"],
                    g["guarantee_pct_of_p50"], g["guaranteed_kwh"])


if __name__ == "__main__":
    try:
        main()
    finally:
        close_connection_pool()
