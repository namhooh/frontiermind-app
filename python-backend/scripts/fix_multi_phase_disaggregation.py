#!/usr/bin/env python3
"""
Fix multi-phase project disaggregation for NBL01, KAS01, and IVL01.

Populates:
  - contract_line.phase_cod_date
  - contract_line.product_desc (with Phase N labels)
  - clause_tariff.logic_parameters.phases[]
  - project.installed_dc_capacity_kwp
  - Creates per-phase meter for IVL01

Usage:
  python -m scripts.fix_multi_phase_disaggregation --dry-run
  python -m scripts.fix_multi_phase_disaggregation
"""

import argparse
import json
import logging
import os
import sys

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ============================================================================
# Phase data (from PPW)
# ============================================================================

PHASE_DATA = {
    "NBL01": {
        "phases": [
            {"phase": 1, "kwp": 663, "cod_date": "2021-02-22", "degradation_pct": 0.007, "specific_yield_kwh_kwp": 1037.3},
            {"phase": 2, "kwp": 2511, "cod_date": "2025-01-01", "degradation_pct": 0.007},
        ],
        "combined_kwp": 3174,
    },
    "IVL01": {
        "phases": [
            {"phase": 1, "kwp": 967.68, "cod_date": "2023-10-02", "degradation_pct": 0.004, "specific_yield_kwh_kwp": 1597.63},
            {"phase": 2, "kwp": 2274.84, "cod_date": "2024-10-04", "degradation_pct": 0.004, "specific_yield_kwh_kwp": 1598.1},
        ],
        "combined_kwp": 3242.52,
    },
    "KAS01": {
        "phases": [
            {"phase": 1, "kwp": 400.44, "cod_date": "2018-10-17"},
            {"phase": 2, "kwp": 904.8, "cod_date": "2024-05-03"},
        ],
        "combined_kwp": 1305.24,
    },
}


def get_connection():
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def fix_nbl01(cur, dry_run: bool):
    """NBL01: Populate phase_cod_date on contract lines and update product_desc."""
    logger.info("=== NBL01 ===")

    # Get project info
    cur.execute("SELECT id FROM project WHERE sage_id = 'NBL01'")
    proj = cur.fetchone()
    if not proj:
        logger.warning("NBL01 project not found, skipping")
        return
    pid = proj["id"]

    # Get contract lines
    cur.execute("""
        SELECT cl.id, cl.contract_line_number, cl.meter_id, cl.product_desc, cl.phase_cod_date, m.name AS meter_name
        FROM contract_line cl
        JOIN contract c ON c.id = cl.contract_id
        LEFT JOIN meter m ON m.id = cl.meter_id
        WHERE c.project_id = %(pid)s AND cl.is_active = true
        ORDER BY cl.contract_line_number
    """, {"pid": pid})
    lines = cur.fetchall()
    logger.info(f"  Found {len(lines)} active contract lines")

    for cl in lines:
        cln = cl["contract_line_number"]
        mid = cl["meter_id"]
        desc = cl["product_desc"] or ""
        updates = {}

        # Assign phase_cod_date based on meter_id
        if mid == 89:  # Phase 1 meter
            updates["phase_cod_date"] = "2021-02-22"
            if "phase" not in desc.lower():
                updates["product_desc"] = f"{desc} Phase 1".strip() if desc else "Generator (EMetered) Phase 1"
        elif mid == 90:  # Phase 2 meter
            updates["phase_cod_date"] = "2025-01-01"
            if "phase" not in desc.lower():
                updates["product_desc"] = f"{desc} Phase 2".strip() if desc else "Generator (EMetered) Phase 2"
        elif mid == 88:  # Combined facility meter
            updates["phase_cod_date"] = "2021-02-22"
        elif desc and "phase 2" in desc.lower():
            updates["phase_cod_date"] = "2025-01-01"
        elif desc and "early operating" in desc.lower() and "phase 2" in desc.lower():
            updates["phase_cod_date"] = "2025-01-01"

        if updates:
            set_clauses = ", ".join(f"{k} = %({k})s" for k in updates)
            if dry_run:
                logger.info(f"  [DRY-RUN] Line {cln} (meter={mid}): SET {updates}")
            else:
                updates["id"] = cl["id"]
                cur.execute(f"UPDATE contract_line SET {set_clauses} WHERE id = %(id)s", updates)
                logger.info(f"  Updated line {cln} (meter={mid}): {updates}")


def fix_ivl01(cur, dry_run: bool):
    """IVL01: Create Phase 2 meter, update contract lines with phase info."""
    logger.info("=== IVL01 ===")

    cur.execute("SELECT id, organization_id FROM project WHERE sage_id = 'IVL01'")
    proj = cur.fetchone()
    if not proj:
        logger.warning("IVL01 project not found, skipping")
        return
    pid = proj["id"]
    org_id = proj["organization_id"]

    # Get existing meters
    cur.execute("SELECT id, name FROM meter WHERE project_id = %(pid)s ORDER BY id", {"pid": pid})
    meters = cur.fetchall()
    logger.info(f"  Existing meters: {[(m['id'], m['name']) for m in meters]}")

    # Find the metered energy meter (meter 55 per plan)
    metered_meter = None
    for m in meters:
        if m["name"] and ("metered" in m["name"].lower() or "emetered" in m["name"].lower()):
            metered_meter = m
            break
    if not metered_meter and len(meters) >= 2:
        metered_meter = meters[1]  # fallback to second meter

    if not metered_meter:
        logger.warning("  Could not find metered energy meter for IVL01, skipping meter split")
        return

    # Rename existing metered meter to Phase 1
    phase1_meter_id = metered_meter["id"]
    new_name_p1 = "Phase 1 (EMetered)"
    if dry_run:
        logger.info(f"  [DRY-RUN] Rename meter {phase1_meter_id} to '{new_name_p1}'")
    else:
        cur.execute("UPDATE meter SET name = %(name)s WHERE id = %(id)s", {"name": new_name_p1, "id": phase1_meter_id})
        logger.info(f"  Renamed meter {phase1_meter_id} to '{new_name_p1}'")

    # Create Phase 2 meter
    # Get meter_type_id from existing meter
    cur.execute("SELECT meter_type_id FROM meter WHERE id = %(id)s", {"id": phase1_meter_id})
    mt = cur.fetchone()
    meter_type_id = mt["meter_type_id"] if mt else None

    phase2_meter_id = None
    if dry_run:
        logger.info(f"  [DRY-RUN] Create Phase 2 meter for IVL01")
        phase2_meter_id = -1  # placeholder
    else:
        cur.execute("""
            INSERT INTO meter (project_id, organization_id, name, meter_type_id, unit)
            VALUES (%(pid)s, %(oid)s, 'Phase 2 (EMetered)', %(mtid)s, 'kWh')
            RETURNING id
        """, {"pid": pid, "oid": org_id, "mtid": meter_type_id})
        phase2_meter_id = cur.fetchone()["id"]
        logger.info(f"  Created Phase 2 meter: id={phase2_meter_id}")

    # Get contract lines
    cur.execute("""
        SELECT cl.id, cl.contract_line_number, cl.meter_id, cl.product_desc, cl.contract_id,
               cl.energy_category, cl.billing_product_id, cl.is_active
        FROM contract_line cl
        JOIN contract c ON c.id = cl.contract_id
        WHERE c.project_id = %(pid)s AND cl.is_active = true
        ORDER BY cl.contract_line_number
    """, {"pid": pid})
    lines = cur.fetchall()
    logger.info(f"  Found {len(lines)} active contract lines")

    for cl in lines:
        cln = cl["contract_line_number"]
        mid = cl["meter_id"]
        desc = cl["product_desc"] or ""
        cat = cl["energy_category"]

        if cat == "metered" and mid == phase1_meter_id:
            # Update existing metered line → Phase 1
            updates = {
                "phase_cod_date": "2023-10-02",
                "product_desc": "Metered Energy (EMetered) Phase 1",
            }
            if dry_run:
                logger.info(f"  [DRY-RUN] Line {cln}: SET {updates}")
            else:
                cur.execute("""
                    UPDATE contract_line SET phase_cod_date = %(phase_cod_date)s, product_desc = %(product_desc)s
                    WHERE id = %(id)s
                """, {**updates, "id": cl["id"]})
                logger.info(f"  Updated line {cln}: {updates}")

            # Create Phase 2 metered contract line
            if phase2_meter_id and phase2_meter_id != -1:
                new_cln = cln + 1000  # e.g. 1000 → 2000
                if dry_run:
                    logger.info(f"  [DRY-RUN] Create Phase 2 contract line {new_cln}")
                else:
                    cur.execute("""
                        INSERT INTO contract_line (
                            contract_id, contract_line_number, meter_id,
                            energy_category, product_desc, phase_cod_date,
                            billing_product_id, is_active
                        ) VALUES (
                            %(cid)s, %(cln)s, %(mid)s,
                            'metered', 'Metered Energy (EMetered) Phase 2', '2024-10-04',
                            %(bpid)s, true
                        )
                    """, {
                        "cid": cl["contract_id"],
                        "cln": new_cln,
                        "mid": phase2_meter_id,
                        "bpid": cl["billing_product_id"],
                    })
                    logger.info(f"  Created Phase 2 contract line {new_cln}")

        elif cat == "available":
            # Update available energy line with Phase 1 COD
            if dry_run:
                logger.info(f"  [DRY-RUN] Line {cln} (available): SET phase_cod_date = 2023-10-02")
            else:
                cur.execute(
                    "UPDATE contract_line SET phase_cod_date = '2023-10-02' WHERE id = %(id)s",
                    {"id": cl["id"]},
                )
                logger.info(f"  Updated available line {cln}: phase_cod_date = 2023-10-02")


def update_logic_parameters(cur, sage_id: str, dry_run: bool):
    """Add phases[] to clause_tariff.logic_parameters."""
    logger.info(f"=== {sage_id}: Update logic_parameters ===")

    cur.execute("SELECT id FROM project WHERE sage_id = %(sid)s", {"sid": sage_id})
    proj = cur.fetchone()
    if not proj:
        logger.warning(f"  {sage_id} project not found, skipping")
        return
    pid = proj["id"]

    cur.execute("""
        SELECT id, logic_parameters
        FROM clause_tariff
        WHERE project_id = %(pid)s AND is_current = true
    """, {"pid": pid})
    tariffs = cur.fetchall()
    logger.info(f"  Found {len(tariffs)} current tariffs")

    phases = PHASE_DATA[sage_id]["phases"]

    for t in tariffs:
        lp = t["logic_parameters"] or {}
        if isinstance(lp, str):
            lp = json.loads(lp)

        # Skip if already has phases
        if "phases" in lp and len(lp["phases"]) > 0:
            logger.info(f"  Tariff {t['id']}: phases[] already present, skipping")
            continue

        lp["phases"] = phases
        if dry_run:
            logger.info(f"  [DRY-RUN] Tariff {t['id']}: add phases[] = {json.dumps(phases, default=str)[:100]}...")
        else:
            cur.execute(
                "UPDATE clause_tariff SET logic_parameters = %(lp)s WHERE id = %(id)s",
                {"lp": json.dumps(lp, default=str), "id": t["id"]},
            )
            logger.info(f"  Updated tariff {t['id']}: added phases[]")


def update_capacity(cur, sage_id: str, dry_run: bool):
    """Update project.installed_dc_capacity_kwp to combined phase total."""
    combined = PHASE_DATA[sage_id]["combined_kwp"]
    logger.info(f"=== {sage_id}: Update installed_dc_capacity_kwp → {combined} ===")

    cur.execute("SELECT id, installed_dc_capacity_kwp FROM project WHERE sage_id = %(sid)s", {"sid": sage_id})
    proj = cur.fetchone()
    if not proj:
        logger.warning(f"  {sage_id} not found")
        return

    current = float(proj["installed_dc_capacity_kwp"] or 0)
    if abs(current - combined) < 0.01:
        logger.info(f"  Already correct ({current})")
        return

    if dry_run:
        logger.info(f"  [DRY-RUN] {current} → {combined}")
    else:
        cur.execute(
            "UPDATE project SET installed_dc_capacity_kwp = %(kwp)s WHERE id = %(id)s",
            {"kwp": combined, "id": proj["id"]},
        )
        logger.info(f"  Updated: {current} → {combined}")


def verify(cur):
    """Print verification query."""
    logger.info("=== Verification ===")
    cur.execute("""
        SELECT p.sage_id, cl.contract_line_number, cl.phase_cod_date, cl.product_desc, m.name AS meter_name
        FROM contract_line cl
        JOIN contract c ON cl.contract_id = c.id
        JOIN project p ON c.project_id = p.id
        LEFT JOIN meter m ON cl.meter_id = m.id
        WHERE p.sage_id IN ('NBL01', 'KAS01', 'IVL01') AND cl.is_active = true
        ORDER BY p.sage_id, cl.contract_line_number
    """)
    rows = cur.fetchall()
    for r in rows:
        logger.info(
            f"  {r['sage_id']} | line {r['contract_line_number']:>5} | "
            f"phase_cod={r['phase_cod_date']} | desc={r['product_desc']} | meter={r['meter_name']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Fix multi-phase project disaggregation")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = '300s'")

        # A1. NBL01 contract lines
        fix_nbl01(cur, args.dry_run)

        # A2. IVL01 meter split + contract lines
        fix_ivl01(cur, args.dry_run)

        # A3. Add phases[] to logic_parameters for NBL01 and IVL01
        update_logic_parameters(cur, "NBL01", args.dry_run)
        update_logic_parameters(cur, "IVL01", args.dry_run)

        # A4. Update installed_dc_capacity_kwp
        update_capacity(cur, "NBL01", args.dry_run)
        update_capacity(cur, "IVL01", args.dry_run)

        # Verify
        verify(cur)

        if args.dry_run:
            logger.info("\n=== DRY RUN — no changes committed ===")
            conn.rollback()
        else:
            conn.commit()
            logger.info("\n=== Changes committed ===")

    except Exception as e:
        conn.rollback()
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
