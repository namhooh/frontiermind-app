#!/usr/bin/env python3
"""
Normalize logic_parameters for MRP-dependent projects.

Populates missing structured fields (escalation_rules, formula_type,
discount_pct, floor_ceiling_currency) so the dashboard Escalation Rules
and MRP sections render correctly.

Defensive: never overwrites existing non-null values.
"""

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log = logging.getLogger('normalize_mrp_lp')

# ─── Per-project normalization specs ──────────────────────────────────────────
# Each entry: sage_id → dict of fields to merge into logic_parameters.
# Only merged if the key is absent or null in the current logic_parameters.

NORMALIZATIONS = {
    'GBL01': {
        'formula_type': 'GRID_DISCOUNT_BOUNDED',
        'escalation_rules': [],
        # discount_pct, floor_rate, ceiling_rate: unknown — leave null for manual entry
    },
    'JAB01': {
        'discount_pct': 0.20,  # normalize from existing discount_percentage
        'formula_type': 'GRID_DISCOUNT_BOUNDED',
        'escalation_rules': [
            {'type': 'NONE', 'component': 'min_solar_price'},
            {'type': 'NONE', 'component': 'max_solar_price'},
        ],
    },
    'KAS01': {
        # Already well-structured — just ensure formula_type present
        'formula_type': 'GRID_DISCOUNT_BOUNDED',
    },
    'MOH01': {
        'formula_type': 'GRID_DISCOUNT_BOUNDED',
    },
    'NBL01': {
        'discount_pct': 0.1517,  # normalize from existing discount_percentage
        'formula_type': 'GRID_DISCOUNT_BOUNDED',
        'escalation_rules': [],
        # floor_rate, ceiling_rate: unknown — leave null for manual entry
    },
    'NBL02': {
        # Derived from mrp_clause_text:
        #   "Minimum Solar Price is equal to 0.0799 USD"
        #   "Maximum Solar Price is equal to 0.210 USD"
        #   "Minimum Solar Price will escalate by 1.5%"
        #   "Maximum Solar Price ... for the full Term" (fixed)
        'floor_rate': 0.0799,
        'ceiling_rate': 0.210,
        'floor_ceiling_currency': 'USD',
        'formula_type': 'GENERATOR_DISCOUNT_BOUNDED',
        'escalation_rules': [
            {'type': 'FIXED', 'value': 0.015, 'component': 'min_solar_price', 'start_year': 2},
            {'type': 'NONE', 'component': 'max_solar_price'},
        ],
        # discount_pct: not stated in clause text — leave for manual entry
    },
    'TBM01': {
        'floor_ceiling_currency': 'USD',
        'escalation_rules': [
            {'type': 'FIXED', 'value': 0.025, 'component': 'min_solar_price', 'start_year': 2},
            {'type': 'NONE', 'component': 'max_solar_price'},
        ],
    },
    'UGL01': {
        'discount_pct': 0.16,  # normalize from existing discount_percentage
        'floor_ceiling_currency': 'USD',
        'escalation_rules': [
            {'type': 'FIXED', 'value': 0.02, 'component': 'min_solar_price', 'start_year': 2},
            {'type': 'NONE', 'component': 'max_solar_price'},
        ],
    },
    'UTK01': {
        'floor_ceiling_currency': 'USD',
        'escalation_rules': [
            {'type': 'FIXED', 'value': 0.025, 'component': 'min_solar_price', 'start_year': 2},
            {'type': 'NONE', 'component': 'max_solar_price'},
        ],
    },
}


def merge_lp(current: dict, updates: dict) -> tuple[dict, dict]:
    """Merge updates into current logic_parameters. Returns (merged, changes_applied)."""
    merged = dict(current)
    changes = {}
    for key, value in updates.items():
        existing = merged.get(key)
        if existing is None:
            merged[key] = value
            changes[key] = {'old': None, 'new': value}
        else:
            # Skip — defensive merge
            pass
    return merged, changes


def main():
    dry_run = '--dry-run' in sys.argv
    mode = 'DRY RUN' if dry_run else 'LIVE'
    log.info(f"Normalize MRP logic_parameters ({mode})")

    sage_ids = list(NORMALIZATIONS.keys())
    placeholders = ', '.join(['%s'] * len(sage_ids))

    init_connection_pool()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Fetch all clause_tariff rows for target projects
                cur.execute(f"""
                    SELECT ct.id, p.sage_id, ct.logic_parameters
                    FROM clause_tariff ct
                    JOIN project p ON ct.project_id = p.id
                    WHERE p.sage_id IN ({placeholders})
                    ORDER BY p.sage_id, ct.id
                """, sage_ids)
                rows = cur.fetchall()

            log.info(f"Found {len(rows)} clause_tariff rows across {len(sage_ids)} projects")

            total_updates = 0
            for row in rows:
                ct_id = row['id']
                sage_id = row['sage_id']
                lp = row['logic_parameters']
                # Handle various return types
                if isinstance(lp, str):
                    try:
                        lp = json.loads(lp) if lp.strip() else {}
                    except (json.JSONDecodeError, ValueError):
                        lp = {}
                if not isinstance(lp, dict):
                    lp = {}
                updates = NORMALIZATIONS.get(sage_id, {})
                if not updates:
                    continue

                merged, changes = merge_lp(lp, updates)

                if not changes:
                    log.info(f"  {sage_id} (ct={ct_id}): no changes needed")
                    continue

                log.info(f"  {sage_id} (ct={ct_id}): {len(changes)} field(s) to update:")
                for k, v in changes.items():
                    old_display = json.dumps(v['old']) if v['old'] is not None else 'null'
                    new_display = json.dumps(v['new']) if not isinstance(v['new'], (int, float, str)) else repr(v['new'])
                    log.info(f"    {k}: {old_display} → {new_display}")

                total_updates += 1
                if not dry_run:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE clause_tariff SET logic_parameters = %s WHERE id = %s",
                            (json.dumps(merged), ct_id)
                        )

            if not dry_run:
                conn.commit()
                log.info(f"Committed {total_updates} clause_tariff updates")
            else:
                log.info(f"Dry run — {total_updates} updates would be applied")

    finally:
        close_connection_pool()


if __name__ == '__main__':
    main()
