#!/usr/bin/env python3
"""
One-off fix: Retroactively tag LOI01 clauses with amendment tracking.

Problem:
  - 415 clauses were parsed from 3 docs (base_ssa, amendment_1, annexures)
  - All stored under contract_id=47 (COD certificate) instead of contract_id=22 (SSA)
  - No contract_amendment_id tagging
  - Duplicates from multi-pass extraction

Fix:
  1. Move all clauses from contract_id=47 → contract_id=22
  2. Tag amendment clauses (IDs 1072-1216) with contract_amendment_id=16
  3. Set version=1 on base clauses
  4. Deduplicate multi-pass extraction artifacts
  5. Match amendment clauses to base (supersession chain)

Usage:
    cd python-backend
    python scripts/fix_loi01_amendment_tagging.py --dry-run
    python scripts/fix_loi01_amendment_tagging.py
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from db.database import init_connection_pool, close_connection_pool, get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fix_loi01_amendment_tagging")

# Constants derived from DB analysis
OLD_CONTRACT_ID = 47   # COD Acceptance Certificate (wrong)
NEW_CONTRACT_ID = 22   # Loisaba SSA (correct)
AMENDMENT_ID = 16      # contract_amendment id for LOI01 amendment_1

# ID ranges from batch analysis:
#   889-1071  (183): base_ssa (original 2015 SSA)
#   1072-1216 (145): amendment_1 (1st Amendment 2018-10-16, 3 passes, has dupes)
#   1217-1303  (87): revised annexures (same date 2018-10-16 — part of amendment package)
BASE_SSA_RANGE = (889, 1071)
AMENDMENT_RANGE = (1072, 1216)
REVISED_ANNEXURES_RANGE = (1217, 1303)
# Both amendment + revised annexures belong to the same amendment package
AMENDMENT_FULL_RANGE = (1072, 1303)


def run_fix(dry_run: bool = False):
    init_connection_pool(min_connections=1, max_connections=2)

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Verify current state
                cur.execute(
                    "SELECT count(*) as cnt FROM clause WHERE contract_id = %s",
                    (OLD_CONTRACT_ID,),
                )
                count = cur.fetchone()["cnt"]
                logger.info(f"Clauses on contract_id={OLD_CONTRACT_ID}: {count}")

                if count == 0:
                    logger.info("No clauses to fix — already moved or doesn't exist")
                    return

                if count != 415:
                    logger.warning(f"Expected 415 clauses, found {count} — proceeding cautiously")

                # All mutations run within one transaction; dry_run rolls back at the end.

                # Step 1: Move clauses to correct contract
                logger.info(f"\n--- Step 1: Move clauses {OLD_CONTRACT_ID} → {NEW_CONTRACT_ID} ---")
                cur.execute(
                    "UPDATE clause SET contract_id = %s WHERE contract_id = %s",
                    (NEW_CONTRACT_ID, OLD_CONTRACT_ID),
                )
                logger.info(f"  Moved {cur.rowcount} clauses to contract_id={NEW_CONTRACT_ID}")

                # Step 2: Tag amendment clauses (both amendment text + revised annexures)
                logger.info(f"\n--- Step 2: Tag amendment clauses with contract_amendment_id={AMENDMENT_ID} ---")
                logger.info(f"  Amendment text range: {AMENDMENT_RANGE}")
                logger.info(f"  Revised annexures range: {REVISED_ANNEXURES_RANGE}")
                cur.execute(
                    """
                    UPDATE clause
                    SET contract_amendment_id = %s
                    WHERE id BETWEEN %s AND %s AND contract_id = %s
                    """,
                    (AMENDMENT_ID, AMENDMENT_FULL_RANGE[0], AMENDMENT_FULL_RANGE[1], NEW_CONTRACT_ID),
                )
                logger.info(f"  Tagged {cur.rowcount} clauses with contract_amendment_id={AMENDMENT_ID}")

                # Step 3: Set version=1 on base clauses (no amendment)
                logger.info("\n--- Step 3: Set version=1 on base SSA + annexure clauses ---")
                cur.execute(
                    """
                    UPDATE clause
                    SET version = 1
                    WHERE contract_id = %s
                      AND contract_amendment_id IS NULL
                      AND (version IS NULL OR version = 0)
                    """,
                    (NEW_CONTRACT_ID,),
                )
                logger.info(f"  Set version=1 on {cur.rowcount} base clauses")

                # Step 4: Deduplicate within each doc group
                logger.info("\n--- Step 4: Deduplicate multi-pass extraction artifacts ---")

                total_deduped = 0
                for label, id_min, id_max in [
                    ("base_ssa", BASE_SSA_RANGE[0], BASE_SSA_RANGE[1]),
                    ("amendment_1_text", AMENDMENT_RANGE[0], AMENDMENT_RANGE[1]),
                    ("amendment_1_annexures", REVISED_ANNEXURES_RANGE[0], REVISED_ANNEXURES_RANGE[1]),
                ]:
                    cur.execute(
                        """
                        WITH ranked AS (
                            SELECT id, name,
                                   md5(COALESCE(raw_text, '')) as text_hash,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY md5(COALESCE(raw_text, ''))
                                       ORDER BY id ASC
                                   ) as rn
                            FROM clause
                            WHERE contract_id = %s
                              AND id BETWEEN %s AND %s
                        )
                        SELECT id FROM ranked WHERE rn > 1
                        """,
                        (NEW_CONTRACT_ID, id_min, id_max),
                    )
                    dup_ids = [row["id"] for row in cur.fetchall()]

                    if dup_ids:
                        cur.execute(
                            "DELETE FROM clause WHERE id = ANY(%s)",
                            (dup_ids,),
                        )
                        logger.info(f"  [{label}]: Deleted {cur.rowcount} duplicates (kept first of each)")
                        total_deduped += len(dup_ids)
                    else:
                        logger.info(f"  [{label}]: No exact duplicates found")

                logger.info(f"  Total deduped: {total_deduped}")

                # Step 5: Supersession — match amendment clauses to base clauses
                logger.info("\n--- Step 5: Amendment supersession matching ---")

                cur.execute(
                    """
                    SELECT id, name, section_ref, clause_category_id
                    FROM clause
                    WHERE contract_id = %s AND contract_amendment_id IS NULL
                    ORDER BY id
                    """,
                    (NEW_CONTRACT_ID,),
                )
                base_clauses = cur.fetchall()

                cur.execute(
                    """
                    SELECT id, name, section_ref, clause_category_id
                    FROM clause
                    WHERE contract_id = %s AND contract_amendment_id = %s
                    ORDER BY id
                    """,
                    (NEW_CONTRACT_ID, AMENDMENT_ID),
                )
                amendment_clauses = cur.fetchall()

                logger.info(
                    f"  After dedup: {len(base_clauses)} base, "
                    f"{len(amendment_clauses)} amendment clauses"
                )

                # Build base lookup by category
                base_by_cat = {}
                for bc in base_clauses:
                    cat = bc["clause_category_id"]
                    base_by_cat.setdefault(cat, []).append(dict(bc))

                matched = 0
                added = 0
                for ac in amendment_clauses:
                    ac_name = ac["name"] or ""
                    ac_cat = ac["clause_category_id"]

                    best_match = None
                    best_score = 0.0
                    for bc in base_by_cat.get(ac_cat, []):
                        score = _name_similarity(bc["name"] or "", ac_name)
                        if score > best_score:
                            best_score = score
                            best_match = bc

                    if best_match and best_score >= 0.6:
                        # supersedes_clause_id triggers trg_clause_supersede
                        # which auto-sets is_current=false on the base clause
                        cur.execute(
                            """
                            UPDATE clause
                            SET supersedes_clause_id = %s,
                                change_action = 'MODIFIED',
                                version = 2
                            WHERE id = %s
                            """,
                            (best_match["id"], ac["id"]),
                        )
                        matched += 1
                        logger.info(
                            f"    MODIFIED: '{ac_name[:60]}' supersedes "
                            f"'{best_match['name'][:60]}' (score={best_score:.2f})"
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE clause
                            SET change_action = 'ADDED', version = 1
                            WHERE id = %s
                            """,
                            (ac["id"],),
                        )
                        added += 1

                logger.info(f"  Supersession: {matched} MODIFIED, {added} ADDED")

                # --- Commit or rollback ---
                if dry_run:
                    conn.rollback()
                    logger.info("\n=== DRY RUN — all changes rolled back ===")
                else:
                    conn.commit()
                    logger.info("\n=== All changes committed ===")

                # --- Verification (reads current state) ---
                logger.info("\n--- Verification ---")
                cur.execute(
                    """
                    SELECT contract_amendment_id, count(*) as cnt
                    FROM clause WHERE contract_id = %s
                    GROUP BY contract_amendment_id
                    ORDER BY contract_amendment_id NULLS FIRST
                    """,
                    (NEW_CONTRACT_ID,),
                )
                for row in cur.fetchall():
                    logger.info(
                        f"  contract_amendment_id={row['contract_amendment_id']}: "
                        f"{row['cnt']} clauses"
                    )

                cur.execute(
                    """
                    SELECT change_action::text, count(*) as cnt
                    FROM clause WHERE contract_id = %s AND contract_amendment_id IS NOT NULL
                    GROUP BY change_action
                    """,
                    (NEW_CONTRACT_ID,),
                )
                for row in cur.fetchall():
                    logger.info(f"  change_action={row['change_action']}: {row['cnt']}")

                # Check pricing supersession
                cur.execute(
                    """
                    SELECT cl.name, cl.version, cl.is_current, cl.change_action::text,
                           cl.supersedes_clause_id,
                           cl.normalized_payload->>'base_rate_per_kwh' as rate
                    FROM clause cl
                    JOIN clause_category cc ON cl.clause_category_id = cc.id
                    WHERE cl.contract_id = %s AND cc.code = 'PRICING'
                    ORDER BY cl.version NULLS FIRST, cl.id
                    """,
                    (NEW_CONTRACT_ID,),
                )
                pricing = cur.fetchall()
                if pricing:
                    logger.info(f"\n  PRICING clause chain ({len(pricing)} rows):")
                    for p in pricing:
                        logger.info(
                            f"    v{p['version']} | current={p['is_current']} | "
                            f"action={p['change_action']} | supersedes={p['supersedes_clause_id']} | "
                            f"rate={p['rate']} | {p['name'][:60]}"
                        )

    finally:
        close_connection_pool()


def _name_similarity(a: str, b: str) -> float:
    """Jaccard token-overlap similarity."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix LOI01 amendment tagging")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()
    run_fix(dry_run=args.dry_run)
