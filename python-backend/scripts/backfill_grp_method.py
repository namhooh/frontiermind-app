#!/usr/bin/env python3
"""
Backfill grp_method into clause_tariff.logic_parameters for projects
that went through the structured pipeline (missing grp_method).

Mapping:
  FLOATING_GRID / GRID_DISCOUNT_BOUNDED → utility_variable_charges_tou
  FLOATING_GENERATOR                    → utility_total_charges
  FIXED                                 → no GRP needed (skip)

Usage:
    cd python-backend
    python scripts/backfill_grp_method.py
"""

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import get_db_connection, init_connection_pool, close_connection_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_grp_method")

# Mapping from energy_sale_type code → grp_method
GRP_METHOD_MAP = {
    "FLOATING_GRID": "utility_variable_charges_tou",
    "FLOATING_GENERATOR": "utility_total_charges",
}

# formula_type mapping for projects missing it
FORMULA_TYPE_MAP = {
    "FLOATING_GRID": "FLOATING_GRID",
    "FLOATING_GENERATOR": "FLOATING_GENERATOR",
}


def main():
    init_connection_pool(min_connections=1, max_connections=3)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Find clause_tariff rows missing grp_method
                cur.execute("""
                    SELECT ct.id, p.sage_id,
                           ct.logic_parameters,
                           est.code AS energy_sale_type_code
                    FROM clause_tariff ct
                    JOIN contract c ON ct.contract_id = c.id
                    JOIN project p ON c.project_id = p.id
                    LEFT JOIN energy_sale_type est ON ct.energy_sale_type_id = est.id
                    WHERE (ct.logic_parameters IS NULL
                           OR ct.logic_parameters->>'grp_method' IS NULL)
                    ORDER BY p.sage_id
                """)
                rows = cur.fetchall()

                if not rows:
                    logger.info("All clause_tariff rows already have grp_method. Nothing to do.")
                    return

                updated = 0
                skipped = 0

                for row in rows:
                    ct_id = row["id"]
                    sage_id = row["sage_id"]
                    est_code = row["energy_sale_type_code"]
                    lp = row["logic_parameters"] or {}

                    grp_method = GRP_METHOD_MAP.get(est_code)
                    if not grp_method:
                        # Also check formula_type already in logic_parameters
                        ft = lp.get("formula_type", "")
                        if ft in ("GRID_DISCOUNT_BOUNDED", "FLOATING_GRID"):
                            grp_method = "utility_variable_charges_tou"
                        elif ft == "FLOATING_GENERATOR":
                            grp_method = "utility_total_charges"

                    if not grp_method:
                        logger.info(
                            f"  SKIP ct_id={ct_id} sage_id={sage_id}: "
                            f"energy_sale_type={est_code}, no GRP method applicable"
                        )
                        skipped += 1
                        continue

                    # Merge grp_method (and formula_type if missing)
                    patch = {"grp_method": grp_method}
                    if not lp.get("formula_type") and est_code in FORMULA_TYPE_MAP:
                        patch["formula_type"] = FORMULA_TYPE_MAP[est_code]

                    if lp:
                        # Merge into existing logic_parameters
                        cur.execute(
                            """
                            UPDATE clause_tariff
                            SET logic_parameters = logic_parameters || %s::jsonb
                            WHERE id = %s
                            RETURNING id, logic_parameters->>'grp_method' AS grp_method
                            """,
                            (json.dumps(patch), ct_id),
                        )
                    else:
                        # logic_parameters was NULL, set it fresh
                        cur.execute(
                            """
                            UPDATE clause_tariff
                            SET logic_parameters = %s::jsonb
                            WHERE id = %s
                            RETURNING id, logic_parameters->>'grp_method' AS grp_method
                            """,
                            (json.dumps(patch), ct_id),
                        )

                    result = cur.fetchone()
                    logger.info(
                        f"  UPDATED ct_id={result['id']} sage_id={sage_id}: "
                        f"grp_method={result['grp_method']} (patch={patch})"
                    )
                    updated += 1

                conn.commit()
                logger.info(f"Done. Updated {updated}, skipped {skipped}.")

    finally:
        close_connection_pool()


if __name__ == "__main__":
    main()
