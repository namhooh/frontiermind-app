#!/usr/bin/env python3
"""
Fix irradiance units and recalculate PR values directly in the database.

Problems found:
  1. POA stored in Wh/m² instead of kWh/m² for 27 of 29 projects
  2. MOH01 has some GHI values in Wh/m² (>1000)
  3. PR values not recalculated after GHI was fixed

Fix (pure SQL, no PPW parsing needed):
  1. Divide POA by 1000 where POA > 1000
  2. Divide GHI by 1000 where GHI > 1000
  3. Recalculate forecast_pr = energy / (GHI × capacity)
  4. Recalculate forecast_pr_poa = energy / (POA × capacity)

Usage:
    cd python-backend
    python scripts/fix_irradiance_units.py --dry-run    # Preview
    python scripts/fix_irradiance_units.py               # Execute
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fix_irradiance_units")

DEFAULT_ORG_ID = 1


def main():
    parser = argparse.ArgumentParser(description="Fix irradiance units and recalculate PR")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID)
    args = parser.parse_args()

    logger.info(f"Fix Irradiance Units & PR {'(DRY RUN)' if args.dry_run else ''}")

    init_connection_pool()

    try:
        with get_db_connection() as conn:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout = '300000'")  # 5 min

                    # ── Pre-fix snapshot ──
                    cur.execute("""
                        SELECT p.sage_id,
                               COUNT(*) as total_rows,
                               SUM(CASE WHEN pf.forecast_poa_irradiance > 1000 THEN 1 ELSE 0 END) as poa_wrong_unit,
                               SUM(CASE WHEN pf.forecast_ghi_irradiance > 1000 THEN 1 ELSE 0 END) as ghi_wrong_unit
                        FROM production_forecast pf
                        JOIN project p ON p.id = pf.project_id
                        WHERE p.organization_id = %s
                        GROUP BY p.sage_id
                        ORDER BY p.sage_id
                    """, (args.org_id,))
                    pre_snapshot = cur.fetchall()

                    logger.info("Pre-fix snapshot:")
                    total_poa_fix = 0
                    total_ghi_fix = 0
                    for row in pre_snapshot:
                        poa_wrong = row["poa_wrong_unit"]
                        ghi_wrong = row["ghi_wrong_unit"]
                        total_poa_fix += poa_wrong
                        total_ghi_fix += ghi_wrong
                        if poa_wrong > 0 or ghi_wrong > 0:
                            logger.info(
                                f"  {row['sage_id']:<10} "
                                f"POA wrong: {poa_wrong}/{row['total_rows']}  "
                                f"GHI wrong: {ghi_wrong}/{row['total_rows']}"
                            )

                    logger.info(f"\n  Total POA rows to fix: {total_poa_fix}")
                    logger.info(f"  Total GHI rows to fix: {total_ghi_fix}")

                    # ── Step 1: Fix POA units (Wh/m² → kWh/m²) ──
                    logger.info("\nStep 1: Fixing POA irradiance units (÷1000 where > 1000)...")
                    cur.execute("""
                        UPDATE production_forecast pf SET
                            forecast_poa_irradiance = forecast_poa_irradiance / 1000.0,
                            updated_at = NOW()
                        FROM project p
                        WHERE pf.project_id = p.id
                          AND p.organization_id = %s
                          AND pf.forecast_poa_irradiance > 1000
                    """, (args.org_id,))
                    poa_fixed = cur.rowcount
                    logger.info(f"  POA rows fixed: {poa_fixed}")

                    # ── Step 2: Fix GHI units (Wh/m² → kWh/m²) ──
                    logger.info("Step 2: Fixing GHI irradiance units (÷1000 where > 1000)...")
                    cur.execute("""
                        UPDATE production_forecast pf SET
                            forecast_ghi_irradiance = forecast_ghi_irradiance / 1000.0,
                            updated_at = NOW()
                        FROM project p
                        WHERE pf.project_id = p.id
                          AND p.organization_id = %s
                          AND pf.forecast_ghi_irradiance > 1000
                    """, (args.org_id,))
                    ghi_fixed = cur.rowcount
                    logger.info(f"  GHI rows fixed: {ghi_fixed}")

                    # ── Step 3: Recalculate PR values ──
                    # PR = forecast_energy_kwh / (irradiance_kWh_m2 × capacity_kWp)
                    logger.info("Step 3: Recalculating PR values...")
                    cur.execute("""
                        UPDATE production_forecast pf SET
                            forecast_pr = CASE
                                WHEN pf.forecast_ghi_irradiance IS NOT NULL
                                     AND pf.forecast_ghi_irradiance > 0
                                     AND p.installed_dc_capacity_kwp > 0
                                     AND pf.forecast_energy_kwh > 0
                                THEN pf.forecast_energy_kwh / (pf.forecast_ghi_irradiance * p.installed_dc_capacity_kwp)
                                ELSE pf.forecast_pr
                            END,
                            forecast_pr_poa = CASE
                                WHEN pf.forecast_poa_irradiance IS NOT NULL
                                     AND pf.forecast_poa_irradiance > 0
                                     AND p.installed_dc_capacity_kwp > 0
                                     AND pf.forecast_energy_kwh > 0
                                THEN pf.forecast_energy_kwh / (pf.forecast_poa_irradiance * p.installed_dc_capacity_kwp)
                                ELSE pf.forecast_pr_poa
                            END,
                            updated_at = NOW()
                        FROM project p
                        WHERE pf.project_id = p.id
                          AND p.organization_id = %s
                    """, (args.org_id,))
                    pr_updated = cur.rowcount
                    logger.info(f"  PR rows recalculated: {pr_updated}")

                    # ── Post-fix verification ──
                    logger.info("\nPost-fix verification:")
                    cur.execute("""
                        SELECT p.sage_id,
                               p.installed_dc_capacity_kwp,
                               COUNT(*) as rows,
                               ROUND(AVG(pf.forecast_ghi_irradiance)::numeric, 2) as avg_ghi,
                               ROUND(AVG(pf.forecast_poa_irradiance)::numeric, 2) as avg_poa,
                               ROUND(AVG(pf.forecast_pr)::numeric, 4) as avg_pr_ghi,
                               ROUND(AVG(pf.forecast_pr_poa)::numeric, 4) as avg_pr_poa,
                               ROUND(ABS(COALESCE(AVG(pf.forecast_ghi_irradiance), 0) -
                                   COALESCE(AVG(pf.forecast_poa_irradiance), 0))::numeric, 2) as ghi_poa_diff,
                               MAX(pf.forecast_poa_irradiance) as max_poa,
                               MAX(pf.forecast_ghi_irradiance) as max_ghi
                        FROM production_forecast pf
                        JOIN project p ON p.id = pf.project_id
                        WHERE p.organization_id = %s
                        GROUP BY p.sage_id, p.installed_dc_capacity_kwp
                        ORDER BY p.sage_id
                    """, (args.org_id,))
                    post_snapshot = cur.fetchall()

                    logger.info(
                        f"  {'SAGE_ID':<10} {'Capacity':<10} {'Avg GHI':<10} {'Avg POA':<10} "
                        f"{'PR GHI':<10} {'PR POA':<10} {'GHI≠POA':<10} {'Max POA':<10} {'Max GHI':<10}"
                    )
                    pr_warnings = []
                    for row in post_snapshot:
                        diff = float(row["ghi_poa_diff"]) if row["ghi_poa_diff"] else 0
                        diff_label = f"{diff:.1f}" if diff > 1.0 else "same"
                        max_poa = float(row["max_poa"]) if row["max_poa"] else 0
                        max_ghi = float(row["max_ghi"]) if row["max_ghi"] else 0
                        pr_ghi = float(row["avg_pr_ghi"]) if row["avg_pr_ghi"] else None
                        pr_poa = float(row["avg_pr_poa"]) if row["avg_pr_poa"] else None
                        logger.info(
                            f"  {row['sage_id']:<10} {str(row['installed_dc_capacity_kwp']):<10} "
                            f"{str(row['avg_ghi']):<10} {str(row['avg_poa']):<10} "
                            f"{str(row['avg_pr_ghi']):<10} {str(row['avg_pr_poa']):<10} "
                            f"{diff_label:<10} {max_poa:<10.1f} {max_ghi:<10.1f}"
                        )

                        # Sanity checks
                        if max_poa > 1000:
                            pr_warnings.append(f"{row['sage_id']}: POA still > 1000 ({max_poa})")
                        if max_ghi > 1000:
                            pr_warnings.append(f"{row['sage_id']}: GHI still > 1000 ({max_ghi})")
                        if pr_ghi and (pr_ghi > 1.0 or pr_ghi < 0.3):
                            pr_warnings.append(f"{row['sage_id']}: PR GHI out of range ({pr_ghi})")
                        if pr_poa and (pr_poa > 1.0 or pr_poa < 0.3):
                            pr_warnings.append(f"{row['sage_id']}: PR POA out of range ({pr_poa})")

                    if pr_warnings:
                        logger.warning(f"\nWarnings ({len(pr_warnings)}):")
                        for w in pr_warnings:
                            logger.warning(f"  {w}")
                    else:
                        logger.info("\n  All values in expected ranges.")

                    # ── Commit or rollback ──
                    if not args.dry_run:
                        conn.commit()
                        logger.info("\nChanges committed.")
                    else:
                        conn.rollback()
                        logger.info("\nDRY RUN — no changes committed.")

                    # ── Summary ──
                    logger.info("=" * 70)
                    logger.info(f"Fix Irradiance Units & PR {'(DRY RUN) ' if args.dry_run else ''}Complete")
                    logger.info(f"  POA rows fixed (÷1000): {poa_fixed}")
                    logger.info(f"  GHI rows fixed (÷1000): {ghi_fixed}")
                    logger.info(f"  PR rows recalculated: {pr_updated}")

            except Exception:
                conn.rollback()
                raise

    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
