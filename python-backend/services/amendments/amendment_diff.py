"""
Amendment diff utilities for comparing clause and tariff versions.

Provides field-level comparison of original vs amended clause/tariff rows
and amendment summary retrieval.
"""

import logging
from typing import Any, Dict, List, Optional

from db.database import get_db_connection

logger = logging.getLogger(__name__)

# Fields to compare when diffing clause versions
CLAUSE_DIFF_FIELDS = [
    "raw_text",
    "summary",
    "normalized_payload",
    "section_ref",
    "name",
    "beneficiary_party",
]

# Fields to compare when diffing tariff versions
TARIFF_DIFF_FIELDS = [
    "base_rate",
    "unit",
    "valid_from",
    "valid_to",
    "logic_parameters",
    "tariff_structure_id",
    "energy_sale_type_id",
    "escalation_type_id",
    "currency_id",
]


def compare_clause_versions(original: dict, amended: dict) -> dict:
    """
    Field-level diff of two clause versions.

    Args:
        original: Dict of the original clause row.
        amended: Dict of the amended clause row.

    Returns:
        Dict with changed fields, each containing 'before' and 'after' values.
    """
    changes = {}
    for field in CLAUSE_DIFF_FIELDS:
        old_val = original.get(field)
        new_val = amended.get(field)
        if old_val != new_val:
            changes[field] = {"before": old_val, "after": new_val}
    return changes


def compare_tariff_versions(original: dict, amended: dict) -> dict:
    """
    Field-level diff of two clause_tariff versions.

    Args:
        original: Dict of the original tariff row.
        amended: Dict of the amended tariff row.

    Returns:
        Dict with changed fields, each containing 'before' and 'after' values.
    """
    changes = {}
    for field in TARIFF_DIFF_FIELDS:
        old_val = original.get(field)
        new_val = amended.get(field)
        if old_val != new_val:
            changes[field] = {"before": old_val, "after": new_val}
    return changes


def get_amendment_summary(
    contract_id: int, amendment_id: int
) -> List[dict]:
    """
    Fetch all clause/tariff changes for an amendment with before/after diffs.

    Args:
        contract_id: Contract ID.
        amendment_id: Contract amendment ID.

    Returns:
        List of dicts, each describing a changed clause or tariff with diff details.
    """
    results: List[dict] = []

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get amended clauses
            cur.execute(
                """
                SELECT c.*, 'clause' AS entity_type
                FROM clause c
                WHERE c.contract_id = %s AND c.contract_amendment_id = %s
                ORDER BY c.id
                """,
                (contract_id, amendment_id),
            )
            amended_clauses = cur.fetchall()

            for clause in amended_clauses:
                clause_dict = dict(clause)
                entry = {
                    "entity_type": "clause",
                    "id": clause_dict["id"],
                    "change_action": clause_dict.get("change_action"),
                    "name": clause_dict.get("name"),
                    "section_ref": clause_dict.get("section_ref"),
                    "diff": {},
                }

                # If it supersedes another clause, compute diff
                supersedes_id = clause_dict.get("supersedes_clause_id")
                if supersedes_id:
                    cur.execute(
                        "SELECT * FROM clause WHERE id = %s",
                        (supersedes_id,),
                    )
                    original = cur.fetchone()
                    if original:
                        entry["diff"] = compare_clause_versions(
                            dict(original), clause_dict
                        )

                results.append(entry)

            # Get amended tariffs
            cur.execute(
                """
                SELECT ct.*, 'clause_tariff' AS entity_type
                FROM clause_tariff ct
                WHERE ct.contract_id = %s AND ct.contract_amendment_id = %s
                ORDER BY ct.id
                """,
                (contract_id, amendment_id),
            )
            amended_tariffs = cur.fetchall()

            for tariff in amended_tariffs:
                tariff_dict = dict(tariff)
                entry = {
                    "entity_type": "clause_tariff",
                    "id": tariff_dict["id"],
                    "change_action": tariff_dict.get("change_action"),
                    "name": tariff_dict.get("name"),
                    "tariff_group_key": tariff_dict.get("tariff_group_key"),
                    "diff": {},
                }

                supersedes_id = tariff_dict.get("supersedes_tariff_id")
                if supersedes_id:
                    cur.execute(
                        "SELECT * FROM clause_tariff WHERE id = %s",
                        (supersedes_id,),
                    )
                    original = cur.fetchone()
                    if original:
                        entry["diff"] = compare_tariff_versions(
                            dict(original), tariff_dict
                        )

                results.append(entry)

    logger.info(
        f"Amendment summary for contract={contract_id}, amendment={amendment_id}: "
        f"{len(results)} changes"
    )
    return results
