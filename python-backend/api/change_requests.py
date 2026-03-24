"""
Change Request API.

Endpoints for the two-step edit/approval workflow:
- List pending change requests for a project
- Approve / reject / cancel change requests
- Summary counts for dashboard badge
"""

import json
import logging
import os
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional


def _json_default(obj):
    """JSON serializer for types not handled by default."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from db.database import get_db_connection
from middleware.authorization import require_approve_access
from middleware.rate_limiter import limit_admin
from middleware.supabase_auth import require_supabase_auth
from services.approval_config import find_policy
from services.audit_service import AuditEvent, audit_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/change-requests", tags=["change-requests"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChangeRequestOut(BaseModel):
    id: int
    organization_id: int
    project_id: int
    target_table: str
    target_id: int
    field_name: str
    old_value: object | None = None
    new_value: object
    display_label: str | None = None
    change_type: str
    change_request_status: str
    auto_approved: bool
    requested_by: str
    requested_at: str
    request_note: str | None = None
    assigned_approver_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    requester_name: str | None = None
    reviewer_name: str | None = None
    # Multi-step approval fields
    approval_chain_type: str | None = None
    current_step_order: int = 1
    total_steps: int = 1
    approval_steps: list | None = None


class ReviewBody(BaseModel):
    note: str | None = None


class AssignBody(BaseModel):
    approver_id: str


class SummaryOut(BaseModel):
    pending: int
    conflicted: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_out(row: dict) -> dict:
    """Serialize a change_request row for the API response."""
    result = dict(row)
    for key in ("requested_at", "reviewed_at", "base_updated_at", "created_at"):
        if key in result and result[key] is not None:
            result[key] = result[key].isoformat() if hasattr(result[key], "isoformat") else str(result[key])
    # Convert UUIDs to strings
    for key in ("requested_by", "assigned_approver_id", "reviewed_by"):
        if key in result and result[key] is not None:
            result[key] = str(result[key])
    return result


def _resolve_project_id(table: str, target_id: int) -> int:
    """Resolve project_id from a target row when scope_project_id is not provided."""
    join_map = {
        "tariff_rate": """
            SELECT ct.project_id FROM tariff_rate tr
            JOIN clause_tariff ct ON ct.id = tr.clause_tariff_id
            WHERE tr.id = %s
        """,
        "exchange_rate": """
            SELECT p.id AS project_id FROM exchange_rate er
            JOIN project p ON p.organization_id = er.organization_id
            WHERE er.id = %s LIMIT 1
        """,
        "clause_tariff": "SELECT project_id FROM clause_tariff WHERE id = %s",
        "contract": "SELECT project_id FROM contract WHERE id = %s",
        "production_forecast": "SELECT project_id FROM production_forecast WHERE id = %s",
        "production_guarantee": "SELECT project_id FROM production_guarantee WHERE id = %s",
    }
    query = join_map.get(table)
    if not query:
        raise HTTPException(status_code=400, detail=f"Cannot resolve project_id for table {table}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (target_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Target row not found: {table} id={target_id}")
    return row["project_id"]


def _get_default_approver(project_id: int, org_id: int) -> str | None:
    """Get the default approver for a project, falling back to any org admin/approver."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check project-level default
            cur.execute("SELECT default_approver_id FROM project WHERE id = %s", (project_id,))
            row = cur.fetchone()
            if row and row["default_approver_id"]:
                return str(row["default_approver_id"])
            # Fallback: first active admin or approver in org
            cur.execute(
                """
                SELECT user_id FROM role
                WHERE organization_id = %s AND role_type IN ('admin', 'approver')
                  AND is_active = true AND member_status = 'active'
                ORDER BY CASE role_type WHEN 'approver' THEN 1 WHEN 'admin' THEN 2 END
                LIMIT 1
                """,
                (org_id,),
            )
            row = cur.fetchone()
            return str(row["user_id"]) if row else None


def create_change_request(
    org_id: int,
    project_id: int,
    table: str,
    target_id: int,
    field_name: str,
    old_value,
    new_value,
    change_type: str,
    display_label: str | None,
    requested_by: str,
    base_updated_at,
    assigned_approver_id: str | None,
    auto_approved: bool = False,
    reviewed_by: str | None = None,
    cr_status: str = "pending",
) -> int:
    """Insert a change_request row and return its ID."""
    now = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Supersede any existing pending request for the same field
            cur.execute(
                """
                UPDATE change_request
                SET change_request_status = 'superseded', reviewed_at = %s
                WHERE target_table = %s AND target_id = %s AND field_name = %s
                  AND change_request_status = 'pending'
                """,
                (now, table, target_id, field_name),
            )

            cur.execute(
                """
                INSERT INTO change_request (
                    organization_id, project_id, target_table, target_id,
                    field_name, old_value, new_value, display_label, change_type,
                    change_request_status, auto_approved,
                    requested_by, requested_at,
                    assigned_approver_id,
                    reviewed_by, reviewed_at,
                    base_updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    org_id, project_id, table, target_id,
                    field_name,
                    json.dumps(old_value, default=_json_default) if old_value is not None else None,
                    json.dumps(new_value, default=_json_default),
                    display_label, change_type,
                    cr_status, auto_approved,
                    requested_by, now,
                    assigned_approver_id,
                    reviewed_by, now if auto_approved else None,
                    base_updated_at,
                ),
            )
            cr_id = cur.fetchone()["id"]

            # Evaluate escalation rules for non-auto-approved requests
            if not auto_approved:
                from services.escalation_engine import (
                    evaluate_escalation,
                    build_approval_steps_json,
                    resolve_step_approvers,
                    get_chain_step_config,
                )
                chain_type = evaluate_escalation(
                    org_id, change_type, old_value, new_value, project_id
                )
                if chain_type:
                    steps = build_approval_steps_json(chain_type, org_id)
                    if steps:
                        total = len(steps)
                        # Resolve step 1 approver for backward compat
                        step1_config = get_chain_step_config(chain_type, org_id, 1)
                        step1_approver = None
                        if step1_config:
                            approvers = resolve_step_approvers(step1_config, org_id)
                            step1_approver = approvers[0] if approvers else None
                        cur.execute(
                            """
                            UPDATE change_request
                            SET approval_chain_type = %s,
                                current_step_order = 1,
                                total_steps = %s,
                                approval_steps = %s,
                                assigned_approver_id = COALESCE(%s, assigned_approver_id)
                            WHERE id = %s
                            """,
                            (
                                chain_type,
                                total,
                                json.dumps(steps),
                                step1_approver,
                                cr_id,
                            ),
                        )

            conn.commit()
    return cr_id


# ---------------------------------------------------------------------------
# Full-row proposal dispatcher (Phase 3)
# ---------------------------------------------------------------------------

async def _apply_row_change(change_type: str, payload: dict, project_id: int, org_id: int) -> None:
    """Replay the original endpoint logic for a full-row change_request approval.

    Each change_type maps to the extracted core function from the original endpoint.
    """
    if change_type == "billing_entry":
        from api.billing import _apply_billing_entry, ManualEntryRequest
        body = ManualEntryRequest(**payload)
        parts = body.billing_month.split("-")
        bm_date = date(int(parts[0]), int(parts[1]), 1)
        # auth not needed for core logic — pass a minimal dict
        await _apply_billing_entry(project_id, body, bm_date, {"organization_id": org_id, "role": "admin"})

    elif change_type == "performance_entry":
        from api.performance import _apply_performance_entry, ManualPerformanceEntry
        body = ManualPerformanceEntry(**payload)
        parts = body.billing_month.split("-")
        bm_date = date(int(parts[0]), int(parts[1]), 1)
        await _apply_performance_entry(project_id, body, bm_date, {"organization_id": org_id, "role": "admin"})

    elif change_type == "mrp_manual_entry":
        from api.mrp import _apply_mrp_manual
        from models.mrp import ManualMRPBatchRequest
        body = ManualMRPBatchRequest(**payload)
        await _apply_mrp_manual(project_id, body, org_id)

    elif change_type == "mrp_upload":
        from api.mrp import _apply_mrp_upload
        # For MRP upload, the file is already in S3. Download and re-extract.
        import boto3
        s3_key = payload["s3_key"]
        try:
            s3 = boto3.client("s3")
            bucket = os.environ.get("MRP_S3_BUCKET", "frontiermind-mrp")
            obj = s3.get_object(Bucket=bucket, Key=s3_key)
            file_bytes = obj["Body"].read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to retrieve file from S3: {e}")

        await _apply_mrp_upload(
            file_bytes=file_bytes,
            filename=payload.get("filename", "uploaded.pdf"),
            project_id=project_id,
            org_id=org_id,
            billing_month_str=payload["billing_month"],
            operating_year=payload.get("operating_year", 1),
            s3_key=s3_key,
            file_hash=payload.get("file_hash", ""),
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown change_type for row change: {change_type}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=SummaryOut, summary="Pending change request counts")
@limit_admin
async def get_summary(
    request: Request,
    project_id: int | None = Query(None),
    auth: dict = Depends(require_supabase_auth),
) -> SummaryOut:
    org_id = auth["organization_id"]
    where = "organization_id = %s AND change_request_status IN ('pending', 'conflicted')"
    params: list = [org_id]
    if project_id is not None:
        where += " AND project_id = %s"
        params.append(project_id)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE change_request_status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE change_request_status = 'conflicted') AS conflicted
                FROM change_request
                WHERE {where}
                """,
                params,
            )
            row = cur.fetchone()
    return SummaryOut(pending=row["pending"], conflicted=row["conflicted"])


@router.get("", response_model=list[ChangeRequestOut], summary="List change requests")
@limit_admin
async def list_change_requests(
    request: Request,
    project_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    auth: dict = Depends(require_supabase_auth),
) -> list[ChangeRequestOut]:
    org_id = auth["organization_id"]
    where = "cr.organization_id = %s"
    params: list = [org_id]
    if project_id is not None:
        where += " AND cr.project_id = %s"
        params.append(project_id)
    if status_filter:
        where += " AND cr.change_request_status = %s"
        params.append(status_filter)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT cr.*,
                       req.name AS requester_name,
                       rev.name AS reviewer_name
                FROM change_request cr
                LEFT JOIN role req ON req.user_id = cr.requested_by AND req.organization_id = cr.organization_id
                LEFT JOIN role rev ON rev.user_id = cr.reviewed_by AND rev.organization_id = cr.organization_id
                WHERE {where}
                ORDER BY cr.created_at DESC
                """,
                params,
            )
            rows = cur.fetchall()

    return [ChangeRequestOut(**_row_to_out(r)) for r in rows]


@router.post("/{cr_id}/approve", summary="Approve a change request")
@limit_admin
async def approve_change_request(
    request: Request,
    cr_id: int,
    body: ReviewBody = ReviewBody(),
    background_tasks: BackgroundTasks = None,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    require_approve_access(auth)
    org_id = auth["organization_id"]
    user_id = auth["user_id"]

    # Fetch the change request
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM change_request WHERE id = %s AND organization_id = %s",
                (cr_id, org_id),
            )
            cr = cur.fetchone()

    if not cr:
        raise HTTPException(status_code=404, detail="Change request not found")
    if cr["change_request_status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot approve a {cr['change_request_status']} request")

    # -----------------------------------------------------------------------
    # Multi-step approval path
    # -----------------------------------------------------------------------
    if cr.get("approval_chain_type"):
        return await _approve_multi_step(cr, cr_id, user_id, org_id, body, background_tasks)

    # -----------------------------------------------------------------------
    # Legacy single-approver path
    # -----------------------------------------------------------------------

    # Four-eyes check
    from services.approval_config import find_policy_by_change_type
    policy = find_policy(cr["target_table"], cr["field_name"]) or find_policy_by_change_type(cr["change_type"])
    if policy and not policy.allow_self_approve and str(cr["requested_by"]) == user_id:
        raise HTTPException(status_code=403, detail="Cannot approve your own change request (four-eyes principle)")

    # Full-row proposal (Phase 3) vs single-field change (Phase 1-2)
    is_row_proposal = cr["field_name"] == "*"

    if not is_row_proposal:
        _conflict_check(cr, cr_id, user_id)

    # Apply the change
    new_value = cr["new_value"]
    if isinstance(new_value, str):
        new_value = json.loads(new_value)

    now = datetime.now(timezone.utc)

    if is_row_proposal:
        await _apply_row_change(cr["change_type"], new_value, cr["project_id"], cr["organization_id"])
    else:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {cr['target_table']} SET {cr['field_name']} = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                    (new_value, cr["target_id"]),
                )
                if not cur.fetchone():
                    conn.rollback()
                    raise HTTPException(status_code=404, detail="Target row not found during apply")
                conn.commit()

    # Mark approved
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE change_request
                SET change_request_status = 'approved', reviewed_by = %s, reviewed_at = %s, review_note = %s
                WHERE id = %s
                """,
                (user_id, now, body.note, cr_id),
            )
            conn.commit()

    _audit_approval(cr, cr_id, org_id, user_id, background_tasks)
    return {"success": True, "status": "approved", "id": cr_id}


def _conflict_check(cr: dict, cr_id: int, user_id: str) -> None:
    """Check for concurrent edits on the target row (Phase 1-2 only)."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT updated_at FROM {cr['target_table']} WHERE id = %s",
                (cr["target_id"],),
            )
            target_row = cur.fetchone()

    if not target_row:
        raise HTTPException(status_code=404, detail="Target row no longer exists")

    if cr["base_updated_at"] and target_row.get("updated_at"):
        if target_row["updated_at"] != cr["base_updated_at"]:
            now = datetime.now(timezone.utc)
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE change_request
                        SET change_request_status = 'conflicted', reviewed_by = %s, reviewed_at = %s,
                            review_note = 'Underlying data changed since submission'
                        WHERE id = %s
                        """,
                        (user_id, now, cr_id),
                    )
                    conn.commit()
            raise HTTPException(
                status_code=409,
                detail={"success": False, "status": "conflicted",
                        "message": "Underlying data changed since submission. Please re-submit."},
            )


def _audit_approval(cr: dict, cr_id: int, org_id: int, user_id: str, background_tasks) -> None:
    """Log a CHANGE_APPROVED audit event."""
    if background_tasks:
        background_tasks.add_task(
            audit_service.log_event,
            AuditEvent(
                action="CHANGE_APPROVED",
                resource_type="change_request",
                resource_id=str(cr_id),
                resource_name=f"{cr['target_table']}.{cr['field_name']}",
                organization_id=org_id,
                user_id=user_id,
                details={
                    "target_table": cr["target_table"],
                    "target_id": cr["target_id"],
                    "field_name": cr["field_name"],
                    "old_value": cr["old_value"],
                    "new_value": cr["new_value"],
                },
            ),
        )


async def _approve_multi_step(
    cr: dict, cr_id: int, user_id: str, org_id: int, body, background_tasks
) -> dict:
    """Handle approval for a multi-step change request."""
    from services.escalation_engine import resolve_step_approvers, get_chain_step_config

    chain_type = cr["approval_chain_type"]
    current_step = cr["current_step_order"]
    total_steps = cr["total_steps"]
    steps = cr["approval_steps"]
    if isinstance(steps, str):
        steps = json.loads(steps)

    # Validate current step is pending
    step_idx = current_step - 1
    if step_idx >= len(steps) or steps[step_idx]["step_status"] != "pending":
        raise HTTPException(status_code=400, detail="Current step is not pending")

    # Load step config for eligibility and four-eyes check
    step_config = get_chain_step_config(chain_type, org_id, current_step)
    if not step_config:
        raise HTTPException(status_code=500, detail="Approval chain step config not found")

    # Check caller is eligible for this step
    eligible = resolve_step_approvers(step_config, org_id)
    if user_id not in eligible:
        raise HTTPException(status_code=403, detail="You are not eligible to approve this step")

    # Four-eyes check per step
    if not step_config.get("allow_self_approve", False) and str(cr["requested_by"]) == user_id:
        raise HTTPException(status_code=403, detail="Cannot approve your own change request (four-eyes principle)")

    # Conflict check for field-level changes
    is_row_proposal = cr["field_name"] == "*"
    if not is_row_proposal:
        _conflict_check(cr, cr_id, user_id)

    now = datetime.now(timezone.utc)

    # Update the current step in JSONB
    steps[step_idx]["step_status"] = "approved"
    steps[step_idx]["approved_by"] = user_id
    steps[step_idx]["approved_at"] = now.isoformat()
    steps[step_idx]["approval_note"] = body.note

    if current_step < total_steps:
        # Advance to next step
        next_step = current_step + 1
        steps[next_step - 1]["step_status"] = "pending"

        # Resolve next step's approver
        next_config = get_chain_step_config(chain_type, org_id, next_step)
        next_approver = None
        if next_config:
            next_eligible = resolve_step_approvers(next_config, org_id)
            next_approver = next_eligible[0] if next_eligible else None

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE change_request
                    SET current_step_order = %s,
                        approval_steps = %s,
                        assigned_approver_id = COALESCE(%s, assigned_approver_id)
                    WHERE id = %s
                    """,
                    (next_step, json.dumps(steps, default=_json_default), next_approver, cr_id),
                )
                conn.commit()

        _audit_approval(cr, cr_id, org_id, user_id, background_tasks)
        return {
            "success": True,
            "status": "step_approved",
            "id": cr_id,
            "current_step": next_step,
            "total_steps": total_steps,
            "step_name": steps[step_idx]["step_name"],
        }

    else:
        # Final step — apply the change
        new_value = cr["new_value"]
        if isinstance(new_value, str):
            new_value = json.loads(new_value)

        if is_row_proposal:
            await _apply_row_change(cr["change_type"], new_value, cr["project_id"], cr["organization_id"])
        else:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {cr['target_table']} SET {cr['field_name']} = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                        (new_value, cr["target_id"]),
                    )
                    if not cur.fetchone():
                        conn.rollback()
                        raise HTTPException(status_code=404, detail="Target row not found during apply")
                    conn.commit()

        # Mark fully approved
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE change_request
                    SET change_request_status = 'approved',
                        reviewed_by = %s, reviewed_at = %s, review_note = %s,
                        approval_steps = %s
                    WHERE id = %s
                    """,
                    (user_id, now, body.note, json.dumps(steps, default=_json_default), cr_id),
                )
                conn.commit()

        _audit_approval(cr, cr_id, org_id, user_id, background_tasks)
        return {"success": True, "status": "approved", "id": cr_id}


@router.post("/{cr_id}/reject", summary="Reject a change request")
@limit_admin
async def reject_change_request(
    request: Request,
    cr_id: int,
    body: ReviewBody = ReviewBody(),
    background_tasks: BackgroundTasks = None,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    require_approve_access(auth)
    org_id = auth["organization_id"]
    user_id = auth["user_id"]

    now = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, change_request_status, approval_steps FROM change_request WHERE id = %s AND organization_id = %s",
                (cr_id, org_id),
            )
            cr = cur.fetchone()
            if not cr:
                raise HTTPException(status_code=404, detail="Change request not found")
            if cr["change_request_status"] != "pending":
                raise HTTPException(status_code=400, detail=f"Cannot reject a {cr['change_request_status']} request")

            # Mark all remaining steps as rejected in JSONB
            steps = cr.get("approval_steps")
            steps_json = None
            if steps:
                if isinstance(steps, str):
                    steps = json.loads(steps)
                for s in steps:
                    if s["step_status"] in ("pending", "waiting"):
                        s["step_status"] = "rejected"
                steps_json = json.dumps(steps, default=_json_default)

            cur.execute(
                """
                UPDATE change_request
                SET change_request_status = 'rejected', reviewed_by = %s, reviewed_at = %s, review_note = %s,
                    approval_steps = COALESCE(%s, approval_steps)
                WHERE id = %s
                """,
                (user_id, now, body.note, steps_json, cr_id),
            )
            conn.commit()

    if background_tasks:
        background_tasks.add_task(
            audit_service.log_event,
            AuditEvent(
                action="CHANGE_REJECTED",
                resource_type="change_request",
                resource_id=str(cr_id),
                organization_id=org_id,
                user_id=user_id,
            ),
        )

    return {"success": True, "status": "rejected", "id": cr_id}


@router.post("/{cr_id}/cancel", summary="Cancel own change request")
@limit_admin
async def cancel_change_request(
    request: Request,
    cr_id: int,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    org_id = auth["organization_id"]
    user_id = auth["user_id"]

    now = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, requested_by, change_request_status FROM change_request WHERE id = %s AND organization_id = %s",
                (cr_id, org_id),
            )
            cr = cur.fetchone()
            if not cr:
                raise HTTPException(status_code=404, detail="Change request not found")
            if str(cr["requested_by"]) != user_id:
                raise HTTPException(status_code=403, detail="Can only cancel your own requests")
            if cr["change_request_status"] != "pending":
                raise HTTPException(status_code=400, detail=f"Cannot cancel a {cr['change_request_status']} request")

            cur.execute(
                "UPDATE change_request SET change_request_status = 'cancelled', reviewed_at = %s WHERE id = %s",
                (now, cr_id),
            )
            conn.commit()

    return {"success": True, "status": "cancelled", "id": cr_id}


@router.post("/{cr_id}/assign", summary="Reassign approver")
@limit_admin
async def assign_approver(
    request: Request,
    cr_id: int,
    body: AssignBody,
    auth: dict = Depends(require_supabase_auth),
) -> dict:
    from middleware.authorization import require_admin
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE change_request SET assigned_approver_id = %s
                WHERE id = %s AND organization_id = %s AND change_request_status = 'pending'
                RETURNING id
                """,
                (body.approver_id, cr_id, org_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Pending change request not found")
            conn.commit()

    return {"success": True, "id": cr_id, "assigned_to": body.approver_id}
