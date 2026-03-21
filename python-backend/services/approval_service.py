"""
Approval service for endpoint-level approval checks.

Phase 3: Handles full-row proposals (POST endpoints) where the entire payload
needs approval, as opposed to Phase 1-2 which intercepts single-field PATCH edits.

Convention: field_name = '*' means full-row proposal (not a single field edit).
target_id = 0 means the row doesn't exist yet (will be created on approve).
"""

import logging
from typing import Optional

from api.change_requests import create_change_request, _get_default_approver
from services.approval_config import POLICIES

logger = logging.getLogger(__name__)


def check_approval_required(auth: dict, policy_key: str) -> bool:
    """Return True if this action requires approval (editor role + policy exists)."""
    if auth.get("role") in ("admin", "approver"):
        return False
    return policy_key in POLICIES


def create_row_change_request(
    auth: dict,
    org_id: int,
    project_id: int,
    policy_key: str,
    target_table: str,
    payload: dict,
    display_label: str,
) -> int:
    """Create a change_request for a full-row proposal.

    Returns the change_request ID.
    """
    policy = POLICIES.get(policy_key)
    approver_id = _get_default_approver(project_id, org_id)

    return create_change_request(
        org_id=org_id,
        project_id=project_id,
        table=target_table,
        target_id=0,
        field_name="*",
        old_value=None,
        new_value=payload,
        policy_key=policy_key,
        display_label=display_label or (policy.display_name if policy else policy_key),
        requested_by=auth["user_id"],
        base_updated_at=None,
        assigned_approver_id=approver_id,
    )


def create_auto_approved_row_record(
    auth: dict,
    org_id: int,
    project_id: int,
    policy_key: str,
    target_table: str,
    payload: dict,
    display_label: str,
) -> int:
    """Create an auto-approved audit record for admin/approver actions."""
    policy = POLICIES.get(policy_key)

    return create_change_request(
        org_id=org_id,
        project_id=project_id,
        table=target_table,
        target_id=0,
        field_name="*",
        old_value=None,
        new_value=payload,
        policy_key=policy_key,
        display_label=display_label or (policy.display_name if policy else policy_key),
        requested_by=auth["user_id"],
        base_updated_at=None,
        assigned_approver_id=None,
        auto_approved=True,
        reviewed_by=auth["user_id"],
        cr_status="approved",
    )
