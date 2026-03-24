"""
API endpoints for managing approval chains and escalation rules.

Admin-only CRUD — no UI for now, configured via API or direct SQL.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from db.database import get_db_connection
from middleware.supabase_auth import require_supabase_auth
from middleware.authorization import require_admin
from middleware.rate_limiter import limit_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approval-chains", tags=["approval-chains"])
rules_router = APIRouter(prefix="/api/escalation-rules", tags=["escalation-rules"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChainStepIn(BaseModel):
    step_order: int
    step_name: str | None = None
    assigned_approver_id: str | None = None
    approver_role_type: str | None = None
    approver_department: str | None = None
    allow_self_approve: bool = False


class ChainCreateIn(BaseModel):
    approval_chain_type: str
    steps: list[ChainStepIn]


class EscalationRuleIn(BaseModel):
    change_type: str
    name: str
    priority: int = 100
    condition_type: str
    condition_field: str | None = None
    condition_operator: str
    condition_value: float | int | str
    approval_chain_type: str


# ---------------------------------------------------------------------------
# Approval Chain Endpoints
# ---------------------------------------------------------------------------

@router.get("", summary="List approval chains")
@limit_admin
async def list_chains(
    request: Request,
    auth: dict = Depends(require_supabase_auth),
) -> list[dict]:
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM approval_chain
                WHERE organization_id = %s AND is_active = true
                ORDER BY approval_chain_type, step_order
                """,
                (org_id,),
            )
            rows = cur.fetchall()

    # Group by approval_chain_type
    chains: dict[str, list] = {}
    for row in rows:
        r = dict(row)
        for k in ("assigned_approver_id",):
            if k in r and r[k] is not None:
                r[k] = str(r[k])
        if r.get("created_at") and hasattr(r["created_at"], "isoformat"):
            r["created_at"] = r["created_at"].isoformat()
        ct = r["approval_chain_type"]
        chains.setdefault(ct, []).append(r)

    return [{"approval_chain_type": k, "steps": v} for k, v in chains.items()]


@router.post("", summary="Create approval chain with steps")
@limit_admin
async def create_chain(
    request: Request,
    body: ChainCreateIn,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    require_admin(auth)
    org_id = auth["organization_id"]

    if not body.steps:
        raise HTTPException(status_code=400, detail="At least one step is required")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check for existing active chain
            cur.execute(
                """
                SELECT COUNT(*) AS cnt FROM approval_chain
                WHERE organization_id = %s AND approval_chain_type = %s AND is_active = true
                """,
                (org_id, body.approval_chain_type),
            )
            if cur.fetchone()["cnt"] > 0:
                raise HTTPException(status_code=409, detail=f"Chain '{body.approval_chain_type}' already exists")

            for step in body.steps:
                if not (step.assigned_approver_id or step.approver_role_type or step.approver_department):
                    raise HTTPException(status_code=400, detail=f"Step {step.step_order}: at least one approver field required")
                cur.execute(
                    """
                    INSERT INTO approval_chain (
                        organization_id, approval_chain_type, step_order, step_name,
                        assigned_approver_id, approver_role_type, approver_department,
                        allow_self_approve
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        org_id, body.approval_chain_type, step.step_order, step.step_name,
                        step.assigned_approver_id, step.approver_role_type, step.approver_department,
                        step.allow_self_approve,
                    ),
                )
            conn.commit()

    return {"success": True, "approval_chain_type": body.approval_chain_type, "steps": len(body.steps)}


@router.delete("/{chain_type}", summary="Soft-delete approval chain")
@limit_admin
async def delete_chain(
    request: Request,
    chain_type: str,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE approval_chain
                SET is_active = false
                WHERE organization_id = %s AND approval_chain_type = %s AND is_active = true
                """,
                (org_id, chain_type),
            )
            affected = cur.rowcount
            conn.commit()

    if affected == 0:
        raise HTTPException(status_code=404, detail="Chain not found")
    return {"success": True, "deactivated_steps": affected}


# ---------------------------------------------------------------------------
# Escalation Rule Endpoints
# ---------------------------------------------------------------------------

@rules_router.get("", summary="List escalation rules")
@limit_admin
async def list_rules(
    request: Request,
    auth: dict = Depends(require_supabase_auth),
) -> list[dict]:
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM escalation_rule
                WHERE organization_id = %s AND is_active = true
                ORDER BY change_type, priority
                """,
                (org_id,),
            )
            rows = cur.fetchall()

    result = []
    for row in rows:
        r = dict(row)
        for k in ("created_at", "updated_at"):
            if k in r and r[k] is not None and hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
        result.append(r)
    return result


@rules_router.post("", summary="Create escalation rule")
@limit_admin
async def create_rule(
    request: Request,
    body: EscalationRuleIn,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO escalation_rule (
                    organization_id, change_type, name, priority,
                    condition_type, condition_field, condition_operator, condition_value,
                    approval_chain_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    org_id, body.change_type, body.name, body.priority,
                    body.condition_type, body.condition_field, body.condition_operator,
                    json.dumps(body.condition_value),
                    body.approval_chain_type,
                ),
            )
            rule_id = cur.fetchone()["id"]
            conn.commit()

    return {"success": True, "id": rule_id}


@rules_router.delete("/{rule_id}", summary="Soft-delete escalation rule")
@limit_admin
async def delete_rule(
    request: Request,
    rule_id: int,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE escalation_rule
                SET is_active = false, updated_at = NOW()
                WHERE id = %s AND organization_id = %s AND is_active = true
                """,
                (rule_id, org_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Rule not found")
            conn.commit()

    return {"success": True, "id": rule_id}
