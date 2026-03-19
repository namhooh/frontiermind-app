"""
Team Management API.

Endpoints for managing organization members: inviting users, updating roles,
deactivating/reactivating members, and retrieving the current user's membership.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from db.database import get_db_connection
from middleware.authorization import require_admin, require_role
from middleware.rate_limiter import limit_admin
from middleware.supabase_auth import require_supabase_auth, require_jwt_only
from services.audit_service import AuditEvent, audit_service
from services.email.ses_client import SESClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team", tags=["team"])

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

ses_client = SESClient()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class TeamMemberResponse(BaseModel):
    id: int
    user_id: str
    organization_id: int
    role_type: str
    name: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    status: str
    is_active: bool
    invited_by: Optional[str] = None
    invited_at: Optional[str] = None
    accepted_at: Optional[str] = None


class InviteRequest(BaseModel):
    email: str
    full_name: str
    role_type: str  # admin, approver, editor, viewer
    department: Optional[str] = None
    job_title: Optional[str] = None


class UpdateMemberRequest(BaseModel):
    role_type: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_member(row: dict) -> dict:
    """Convert a DB row to a serializable dict."""
    result = dict(row)
    for key in ("invited_at", "accepted_at", "deactivated_at", "created_at", "updated_at"):
        if key in result and result[key] is not None:
            result[key] = result[key].isoformat() if hasattr(result[key], "isoformat") else str(result[key])
    return result


def _count_active_admins(org_id: int) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM role WHERE organization_id = %s AND role_type = 'admin' AND is_active = true AND member_status = 'active'",
                (org_id,),
            )
            return cur.fetchone()["cnt"]


async def _generate_invite_link(email: str, full_name: str) -> dict:
    """Call Supabase Auth Admin API to generate an invite link."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role key not configured",
        )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{SUPABASE_URL}/auth/v1/admin/generate_link",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
            },
            json={
                "type": "invite",
                "email": email,
                "data": {"full_name": full_name},
            },
        )
        if resp.status_code >= 400:
            logger.error(f"Supabase generate_link failed: {resp.status_code} {resp.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to create invite via Supabase: {resp.text}",
            )
        return resp.json()


async def _delete_supabase_user(user_id: str) -> None:
    """Rollback: delete a Supabase user if role insert fails."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                },
            )
    except Exception as e:
        logger.error(f"Failed to rollback Supabase user {user_id}: {e}")


def _send_invite_email(email: str, full_name: str, action_link: str, inviter_name: str) -> None:
    """Send invite email via SES."""
    try:
        html_body = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>You've been invited to FrontierMind</h2>
            <p>Hi {full_name},</p>
            <p>{inviter_name} has invited you to join their organization on FrontierMind.</p>
            <p style="margin: 24px 0;">
                <a href="{action_link}"
                   style="background-color: #0f172a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">
                    Accept Invitation
                </a>
            </p>
            <p style="color: #64748b; font-size: 14px;">This invitation link will expire in 24 hours.</p>
        </div>
        """
        ses_client.send_email(
            to=[email],
            subject="You've been invited to FrontierMind",
            html_body=html_body,
            text_body=f"Hi {full_name}, {inviter_name} has invited you to FrontierMind. Accept here: {action_link}",
            sender_name="FrontierMind",
        )
    except Exception as e:
        logger.error(f"Failed to send invite email to {email}: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/me", response_model=TeamMemberResponse, summary="Get current user's membership")
@limit_admin
async def get_me(
    request: Request,
    auth: dict = Depends(require_jwt_only),
) -> TeamMemberResponse:
    """Return the authenticated user's role membership.

    Uses JWT-only auth (no X-Organization-ID header required) since this
    endpoint is the bootstrap call that tells the frontend which org the
    user belongs to.
    """
    org_id = auth["organization_id"]
    user_id = auth["user_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, organization_id, role_type, name, email,
                       department, job_title, member_status AS status, is_active,
                       invited_by, invited_at, accepted_at
                FROM role
                WHERE user_id = %s AND organization_id = %s AND is_active = true
                LIMIT 1
                """,
                (user_id, org_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Membership not found")
    return TeamMemberResponse(**_row_to_member(row))


@router.get("/members", response_model=list[TeamMemberResponse], summary="List org members")
@limit_admin
async def list_members(
    request: Request,
    auth: dict = Depends(require_supabase_auth),
) -> list[TeamMemberResponse]:
    """List all members of the authenticated organization. Admin only."""
    require_admin(auth)
    org_id = auth["organization_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, organization_id, role_type, name, email,
                       department, job_title, member_status AS status, is_active,
                       invited_by, invited_at, accepted_at
                FROM role
                WHERE organization_id = %s
                ORDER BY
                  CASE role_type WHEN 'admin' THEN 1 WHEN 'approver' THEN 2 WHEN 'editor' THEN 3 WHEN 'viewer' THEN 4 END,
                  name
                """,
                (org_id,),
            )
            rows = cur.fetchall()

    return [TeamMemberResponse(**_row_to_member(r)) for r in rows]


@router.post("/invite", response_model=TeamMemberResponse, summary="Invite a new member")
@limit_admin
async def invite_member(
    request: Request,
    body: InviteRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_supabase_auth),
) -> TeamMemberResponse:
    """Invite a new user to the organization. Admin only."""
    require_admin(auth)
    org_id = auth["organization_id"]
    inviter_id = auth["user_id"]

    # Validate role_type
    if body.role_type not in ("admin", "approver", "editor", "viewer"):
        raise HTTPException(status_code=400, detail=f"Invalid role_type: {body.role_type}")

    # Check for existing membership
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, member_status AS status FROM role WHERE email = %s AND organization_id = %s",
                (body.email, org_id),
            )
            existing = cur.fetchone()
    if existing:
        if existing["status"] == "deactivated":
            raise HTTPException(status_code=409, detail="User was previously deactivated. Use reactivate instead.")
        raise HTTPException(status_code=409, detail="User already exists in this organization")

    # Create Supabase user via Admin API
    invite_data = await _generate_invite_link(body.email, body.full_name)

    # Extract user_id from response — Supabase returns the user object
    # The response shape depends on version; handle both
    supabase_user_id = invite_data.get("id") or invite_data.get("user", {}).get("id")
    action_link = invite_data.get("action_link", "")

    if not supabase_user_id:
        logger.error(f"No user ID in Supabase response: {invite_data}")
        raise HTTPException(status_code=502, detail="Supabase did not return a user ID")

    # Insert role row
    now = datetime.now(timezone.utc)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO role (
                        user_id, organization_id, role_type, name, email,
                        department, job_title, member_status, is_active,
                        invited_by, invited_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'invited', false, %s, %s)
                    RETURNING id, user_id, organization_id, role_type, name, email,
                              department, job_title, member_status AS status, is_active,
                              invited_by, invited_at, accepted_at
                    """,
                    (
                        supabase_user_id, org_id, body.role_type, body.full_name, body.email,
                        body.department, body.job_title,
                        inviter_id, now,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to insert role row, rolling back Supabase user: {e}")
        await _delete_supabase_user(supabase_user_id)
        raise HTTPException(status_code=500, detail="Failed to create membership")

    # Get inviter name for email
    inviter_name = "A team admin"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM role WHERE user_id = %s AND organization_id = %s", (inviter_id, org_id))
                inviter_row = cur.fetchone()
                if inviter_row and inviter_row["name"]:
                    inviter_name = inviter_row["name"]
    except Exception:
        pass

    # Send invite email in background
    if action_link:
        background_tasks.add_task(_send_invite_email, body.email, body.full_name, action_link, inviter_name)

    # Audit log
    background_tasks.add_task(
        audit_service.log_event,
        AuditEvent(
            action="MEMBER_INVITED",
            resource_type="role",
            resource_id=str(row["id"]),
            resource_name=body.email,
            organization_id=org_id,
            user_id=inviter_id,
            details={"role_type": body.role_type, "email": body.email},
        ),
    )

    return TeamMemberResponse(**_row_to_member(row))


@router.patch("/members/{member_id}", response_model=TeamMemberResponse, summary="Update a member")
@limit_admin
async def update_member(
    request: Request,
    member_id: int,
    body: UpdateMemberRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_supabase_auth),
) -> TeamMemberResponse:
    """Update a member's role, department, or job title. Admin only."""
    require_admin(auth)
    org_id = auth["organization_id"]
    admin_user_id = auth["user_id"]

    # Fetch current member
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, role_type, organization_id FROM role WHERE id = %s AND organization_id = %s",
                (member_id, org_id),
            )
            member = cur.fetchone()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Self-demotion guard
    if body.role_type and member["user_id"] == admin_user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own role. Ask another admin.")

    # Last admin guard
    if body.role_type and body.role_type != "admin" and member["role_type"] == "admin":
        if _count_active_admins(org_id) <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last admin")

    # Validate role_type if provided
    if body.role_type and body.role_type not in ("admin", "approver", "editor", "viewer"):
        raise HTTPException(status_code=400, detail=f"Invalid role_type: {body.role_type}")

    # Build UPDATE dynamically
    updates = []
    params = []
    old_role = member["role_type"]
    if body.role_type is not None:
        updates.append("role_type = %s")
        params.append(body.role_type)
    if body.department is not None:
        updates.append("department = %s")
        params.append(body.department)
    if body.job_title is not None:
        updates.append("job_title = %s")
        params.append(body.job_title)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = NOW()")
    params.extend([member_id, org_id])

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE role SET {', '.join(updates)}
                WHERE id = %s AND organization_id = %s
                RETURNING id, user_id, organization_id, role_type, name, email,
                          department, job_title, member_status AS status, is_active,
                          invited_by, invited_at, accepted_at
                """,
                params,
            )
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    # Audit
    if body.role_type and body.role_type != old_role:
        background_tasks.add_task(
            audit_service.log_event,
            AuditEvent(
                action="MEMBER_ROLE_CHANGED",
                resource_type="role",
                resource_id=str(member_id),
                resource_name=row.get("email"),
                organization_id=org_id,
                user_id=admin_user_id,
                details={"old_role": old_role, "new_role": body.role_type},
            ),
        )

    return TeamMemberResponse(**_row_to_member(row))


@router.post("/members/{member_id}/deactivate", response_model=TeamMemberResponse, summary="Deactivate a member")
@limit_admin
async def deactivate_member(
    request: Request,
    member_id: int,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_supabase_auth),
) -> TeamMemberResponse:
    """Soft-delete a member. Admin only."""
    require_admin(auth)
    org_id = auth["organization_id"]
    admin_user_id = auth["user_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, role_type FROM role WHERE id = %s AND organization_id = %s",
                (member_id, org_id),
            )
            member = cur.fetchone()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Cannot deactivate yourself
    if member["user_id"] == admin_user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    # Last admin guard
    if member["role_type"] == "admin" and _count_active_admins(org_id) <= 1:
        raise HTTPException(status_code=400, detail="Cannot deactivate the last admin")

    now = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE role
                SET is_active = false, member_status = 'deactivated', deactivated_at = %s, updated_at = NOW()
                WHERE id = %s AND organization_id = %s
                RETURNING id, user_id, organization_id, role_type, name, email,
                          department, job_title, member_status AS status, is_active,
                          invited_by, invited_at, accepted_at
                """,
                (now, member_id, org_id),
            )
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    background_tasks.add_task(
        audit_service.log_event,
        AuditEvent(
            action="MEMBER_DEACTIVATED",
            resource_type="role",
            resource_id=str(member_id),
            resource_name=row.get("email"),
            organization_id=org_id,
            user_id=admin_user_id,
        ),
    )

    return TeamMemberResponse(**_row_to_member(row))


@router.post("/members/{member_id}/reactivate", response_model=TeamMemberResponse, summary="Reactivate a member")
@limit_admin
async def reactivate_member(
    request: Request,
    member_id: int,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_supabase_auth),
) -> TeamMemberResponse:
    """Reactivate a deactivated member. Admin only."""
    require_admin(auth)
    org_id = auth["organization_id"]
    admin_user_id = auth["user_id"]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, member_status AS status FROM role WHERE id = %s AND organization_id = %s",
                (member_id, org_id),
            )
            member = cur.fetchone()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member["status"] != "deactivated":
        raise HTTPException(status_code=400, detail="Member is not deactivated")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE role
                SET is_active = true, member_status = 'active', deactivated_at = NULL, updated_at = NOW()
                WHERE id = %s AND organization_id = %s
                RETURNING id, user_id, organization_id, role_type, name, email,
                          department, job_title, member_status AS status, is_active,
                          invited_by, invited_at, accepted_at
                """,
                (member_id, org_id),
            )
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Member not found")

    background_tasks.add_task(
        audit_service.log_event,
        AuditEvent(
            action="MEMBER_REACTIVATED",
            resource_type="role",
            resource_id=str(member_id),
            resource_name=row.get("email"),
            organization_id=org_id,
            user_id=admin_user_id,
        ),
    )

    return TeamMemberResponse(**_row_to_member(row))
