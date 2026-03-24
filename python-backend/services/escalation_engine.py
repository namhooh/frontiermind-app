"""
Escalation engine for multi-approver approval chains.

Evaluates threshold-based escalation rules to determine whether a change
request should use a multi-step approval chain instead of the default
single-approver flow.
"""

import json
import logging
import operator
from typing import Optional

from db.connection import get_connection

logger = logging.getLogger(__name__)

# Operator mapping for condition evaluation
_OPS = {
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
    "eq": operator.eq,
    "neq": operator.ne,
}


def evaluate_escalation(
    org_id: int,
    change_type: str,
    old_value,
    new_value,
    project_id: int,
) -> Optional[str]:
    """Evaluate escalation rules for a change request.

    Loads active rules for (org_id, change_type) ordered by priority.
    Returns the approval_chain_type of the first matching rule, or None
    for the legacy single-approver flow.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT condition_type, condition_field, condition_operator,
                   condition_value, approval_chain_type
            FROM escalation_rule
            WHERE organization_id = %s
              AND change_type = %s
              AND is_active = true
            ORDER BY priority ASC
            """,
            (org_id, change_type),
        )
        rules = cur.fetchall()

    for rule in rules:
        if _evaluate_condition(rule, old_value, new_value):
            chain_type = rule["approval_chain_type"]
            logger.info(
                "Escalation matched: change_type=%s, chain=%s",
                change_type,
                chain_type,
            )
            return chain_type

    return None


def _evaluate_condition(rule: dict, old_value, new_value) -> bool:
    """Evaluate a single escalation rule condition."""
    condition_type = rule["condition_type"]
    field = rule["condition_field"]
    op_name = rule["condition_operator"]
    threshold = rule["condition_value"]

    op_fn = _OPS.get(op_name)
    if op_fn is None:
        logger.warning("Unknown operator: %s", op_name)
        return False

    # Parse threshold (stored as JSONB)
    if isinstance(threshold, str):
        threshold = json.loads(threshold)
    threshold_val = float(threshold) if not isinstance(threshold, (int, float)) else threshold

    try:
        # Extract the value to compare
        nv = _extract_value(new_value, field)
        if nv is None:
            return False

        if condition_type == "absolute_value":
            return op_fn(float(nv), threshold_val)

        elif condition_type == "pct_change":
            ov = _extract_value(old_value, field)
            if ov is None or float(ov) == 0:
                return False
            pct = abs((float(nv) - float(ov)) / float(ov) * 100)
            return op_fn(pct, threshold_val)

        elif condition_type == "value_threshold":
            ov = _extract_value(old_value, field)
            if ov is None:
                return False
            diff = abs(float(nv) - float(ov))
            return op_fn(diff, threshold_val)

        else:
            logger.warning("Unknown condition_type: %s", condition_type)
            return False

    except (TypeError, ValueError) as e:
        logger.warning("Condition evaluation error: %s", e)
        return False


def _extract_value(payload, field: Optional[str]):
    """Extract a value from a payload, optionally by field name."""
    if payload is None:
        return None
    if field is None:
        # Top-level value (for single-value changes like exchange rate)
        if isinstance(payload, dict):
            # Try common keys
            for key in ("value", "rate", "amount"):
                if key in payload:
                    return payload[key]
            return None
        return payload
    if isinstance(payload, dict):
        return payload.get(field)
    return None


def resolve_step_approvers(step_row: dict, org_id: int) -> list[str]:
    """Resolve eligible user_ids for an approval chain step.

    Checks (in order): assigned_approver_id, approver_role_type, approver_department.
    """
    if step_row.get("assigned_approver_id"):
        return [str(step_row["assigned_approver_id"])]

    conn = get_connection()
    conditions = ["organization_id = %s", "is_active = true"]
    params: list = [org_id]

    if step_row.get("approver_role_type"):
        conditions.append("role_type = %s")
        params.append(step_row["approver_role_type"])
    if step_row.get("approver_department"):
        conditions.append("department = %s")
        params.append(step_row["approver_department"])

    where = " AND ".join(conditions)
    with conn.cursor() as cur:
        cur.execute(f"SELECT user_id FROM role WHERE {where}", params)
        rows = cur.fetchall()

    return [str(r["user_id"]) for r in rows]


def build_approval_steps_json(
    approval_chain_type: str, org_id: int
) -> list[dict]:
    """Load chain steps and build the JSONB array for change_request.approval_steps.

    Step 1 gets status='pending', steps 2+ get status='waiting'.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT step_order, step_name, assigned_approver_id,
                   approver_role_type, approver_department, allow_self_approve
            FROM approval_chain
            WHERE organization_id = %s
              AND approval_chain_type = %s
              AND is_active = true
            ORDER BY step_order ASC
            """,
            (org_id, approval_chain_type),
        )
        rows = cur.fetchall()

    if not rows:
        return []

    steps = []
    for row in rows:
        steps.append({
            "step_order": row["step_order"],
            "step_name": row["step_name"],
            "step_status": "pending" if row["step_order"] == 1 else "waiting",
            "approved_by": None,
            "approved_at": None,
            "approval_note": None,
        })

    return steps


def get_chain_step_config(
    approval_chain_type: str, org_id: int, step_order: int
) -> Optional[dict]:
    """Load the configuration for a specific step in a chain."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT step_order, step_name, assigned_approver_id,
                   approver_role_type, approver_department, allow_self_approve
            FROM approval_chain
            WHERE organization_id = %s
              AND approval_chain_type = %s
              AND step_order = %s
              AND is_active = true
            """,
            (org_id, approval_chain_type, step_order),
        )
        return cur.fetchone()
